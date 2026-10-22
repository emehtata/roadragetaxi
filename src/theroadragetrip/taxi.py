import itertools
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .geo import clamp, closest_point_and_dist_to_segment, compute_bbox, dist_point_to_segment, get_oriented_box_corners, point_in_polygon, segments_intersect
from .map_level import SURFACE_LEVEL, on_map_level
from .osm import OPEN_ROOF_BUILDING_TYPES, Building, Curb, Place, SpeedBump, TaxiStop, Way
from .physics import (
    Car, SpatialWayGrid, connected_drivable_ways, is_car_road, is_point_on_light_traffic_way, is_point_on_road,
    is_violating_oneway,
)
from .localization import tr
from .fare import calculate_fare_cents, format_euros, star_rating_from_happiness, tip_cents_from_happiness
from .police import SpeedCamera, camera_sees_car
from .rail_bookings import ACCEPTED, IN_TAXI, MISSED, PASSENGER_MET, PASSENGER_WAITING, TRAIN_ARRIVING, waiting_booking
from .residents import CITY_DATA, Resident, ResidentManager
from .traffic_rules import nearest_traffic_light_ahead

logger = logging.getLogger(__name__)
MAX_PHONE_OFFERS = 3
PHONE_OFFER_MIN_LIFETIME_S = 30.0
PHONE_OFFER_MAX_LIFETIME_S = 90.0
PHONE_OFFER_MIN_INTERVAL_S = 10.0
PHONE_OFFER_MAX_INTERVAL_S = 60.0
NIGHTLIFE_VENUE_TYPES = {
    "bar",
    "pub",
    "nightclub",
    "restaurant",
    "cafe",
    "fast_food",
    "food_court",
    "biergarten",
}
MOTION_SICKNESS_THRESHOLD = 8.0
POST_KINDS = ("bollard", "street_lamp")  # solid poles the taxi can hit
POST_RADIUS_M = 0.15
TREE_TRUNK_RADIUS_M = 0.4
POST_KNOCK_DOWN_KMH = 50.0  # faster than this a post bends over instead of stopping the taxi
# Long fares: a phone offer to another municipality. Only the town is known
# at first (its map isn't loaded); the edge arrow points the way, and near
# the town the street address is picked from the map streamed in by then.
LONG_FARE_CHANCE = 0.10
AIRPORT_FARE_CHANCE = 0.10
LONG_FARE_MIN_M = 20_000.0
LONG_FARE_MAX_M = 100_000.0
LONG_FARE_RESOLVE_M = 1500.0  # this close to the town centre its map is loaded
LONG_FARE_RETRY_S = 2.0  # bounded: one address search per this, until one is found
LANDMARK_SNAP_M = 400.0  # an airport/station drop-off: the nearest road this close
LANDMARK_STAND_M = 800.0  # ...but first its taxi stand, this close (terminals sit off the mapped point)
# Popular long-fare destinations besides towns (world_places.py), weighted
# as if a town of this many people.
LANDMARK_WEIGHTS = {"airport": 100_000, "railway_station": 10_000}
GREET_RADIUS_M = 2.0
SOLID_AREA_KINDS = ("construction", "ice_rink", "stadium")  # fenced or walled all round: a crash, never a drive-in  # how close the driver on foot must be to greet a booked rail customer


def car_hits_tree_trunk(car: Car, tree_x: float, tree_y: float) -> bool:
    """Whether the circular trunk touches the car's oriented body."""
    dx, dy = tree_x - car.x, tree_y - car.y
    cos_h, sin_h = math.cos(car.heading), math.sin(car.heading)
    outside_x = max(0.0, abs(dx * cos_h + dy * sin_h) - car.length_m * 0.5)
    outside_y = max(0.0, abs(-dx * sin_h + dy * cos_h) - car.width_m * 0.5)
    return math.hypot(outside_x, outside_y) <= TREE_TRUNK_RADIUS_M

@dataclass
class TaxiTarget:
    """A target destination or pickup point with generated realistic address."""
    x: float
    y: float
    address: str
    way_name: Optional[str] = None
    district_name: Optional[str] = None
    radius_m: float = 20.0  # Pickup/dropoff stop radius
    venue_type: Optional[str] = None
    municipality: Optional[str] = None  # a long fare's town/landmark, until its address is picked
    intercity_place_id: Optional[str] = None


@dataclass
class TaxiPassenger:
    name: str
    pickup: TaxiTarget
    dropoff: TaxiTarget
    gender: str = "woman"
    resident_id: Optional[int] = None
    # Client pedestrian representation walking into the taxi
    ped_x: float = 0.0
    ped_y: float = 0.0
    ped_heading: float = 0.0
    ped_speed: float = 2.0  # Walking speed to taxi in m/s
    ped_color: Tuple[int, int, int] = (240, 220, 60)  # Bright gold/yellow
    is_walking_to_car: bool = False
    boarded: bool = False
    is_drunk: bool = False
    motion_sickness: float = 0.0
    nausea_delay: float = 0.0
    nausea_warning_timer: float = 0.0
    nausea_resolved: bool = False
    nausea_vomited: bool = False
    weight_kg: float = field(default_factory=lambda: random.uniform(50.0, 120.0))
    # rail_bookings.TaxiBooking when this is a pre-booked rail customer: its
    # destination and pre-booking fee (on top of the normal fare) ride along.
    rail_booking: Any = None
    companions: List["TaxiPassenger"] = field(default_factory=list)

    @property
    def members(self) -> List["TaxiPassenger"]:
        return [self, *self.companions]


_offer_ids = itertools.count(1)


@dataclass
class TaxiOffer:
    """A ride request shown in the driver's phone."""
    passenger: TaxiPassenger
    pickup_distance_m: float
    time_remaining_s: float = PHONE_OFFER_MIN_LIFETIME_S
    # Stable while the offer lives: clients answer an offer by id, not by its
    # row (rows shift as offers expire and arrive).
    offer_id: int = field(default_factory=lambda: next(_offer_ids))


class TaxiState:
    WAITING_FOR_PICKUP = "PICKUP"
    CLIENT_WALKING_TO_CAR = "WALKING"
    DRIVING_TO_DROPOFF = "DROPOFF"
    COMPLETED = "COMPLETED"


# Phone pickups from buildings: this share from homes (a street address),
# the rest from named places - real taxi orders mostly start at home.
HOME_PICKUP_SHARE = 0.6
HOME_BUILDING_TYPES = frozenset({"residential", "house", "detached", "semidetached_house", "terrace",
                                 "apartments", "bungalow", "cabin", "farm", "yes"})

_municipality_points: Optional[List[Tuple[str, float, float, int, Optional[str]]]] = None


def municipality_points() -> List[Tuple[str, float, float, int, Optional[str]]]:
    """(name, x, y, weight, landmark type) of every long-fare destination in
    map metres: bundled municipalities (weight: population, type None) and
    airports/railway stations (LANDMARK_WEIGHTS)."""
    global _municipality_points
    if _municipality_points is None:
        from pyproj import Transformer
        from .world_places import load_places
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)
        _municipality_points = []
        for entry in CITY_DATA.values():
            coords = entry.get("koordinaatit") or {}
            x, y = transformer.transform(float(coords["longitude"]), float(coords["latitude"]))
            _municipality_points.append((entry["taajama"], x, y, int(entry.get("väkiluku") or 1), None))
        for place in load_places():
            if place.type in LANDMARK_WEIGHTS:
                x, y = transformer.transform(place.lon, place.lat)
                _municipality_points.append((place.name, x, y, LANDMARK_WEIGHTS[place.type], place.type))
    return _municipality_points


def speed_bonus_points(speed_kmh: float) -> int:
    """Return the nonlinear speed bonus: 10 km/h = 100, 50 = 1,000, 100 = 10,000."""
    speed_kmh = max(0.0, speed_kmh)
    if speed_kmh <= 50.0:
        exponent = math.log(10.0) / math.log(5.0)
        return round(100.0 * (speed_kmh / 10.0) ** exponent) if speed_kmh else 0
    exponent = math.log(10.0) / math.log(2.0)
    return round(1000.0 * (speed_kmh / 50.0) ** exponent)


def nausea_probability(venue_type: Optional[str], game_time_seconds: float = 12.0 * 3600.0) -> float:
    """Return passenger nausea probability based on venue and in-game time."""
    if venue_type in {"bar", "pub", "nightclub"}:
        probability = 0.50
    elif venue_type in {
        "restaurant",
        "cafe",
        "fast_food",
        "food_court",
        "biergarten",
        "ice_cream",
        "confectionery",
    }:
        probability = 0.10
    else:
        probability = 0.0

    hour = (game_time_seconds / 3600.0) % 24.0
    if hour >= 20.0 or hour < 1.0:
        probability += 0.10
    elif 1.0 <= hour < 5.0:
        probability += 0.25
    return min(0.95, probability)


def nausea_delay_for_pickup(pickup: TaxiTarget, game_time_seconds: float = 12.0 * 3600.0) -> float:
    """Return a random in-trip delay when a pickup triggers nausea."""
    if random.random() >= nausea_probability(pickup.venue_type, game_time_seconds):
        return float("inf")
    return random.uniform(5.0, 45.0)


class TaxiManager:
    """Manages taxi missions, addresses, pickups, dropoffs, fares, and speed bonuses."""

    def __init__(
        self,
        ways: List[Way],
        places: Optional[List[Place]] = None,
        buildings: Optional[List[Building]] = None,
        taxi_stops: Optional[List[TaxiStop]] = None,
        min_distance_m: float = 300.0,
        max_distance_m: float = 2500.0,
        pickup_radius_m: float = 25.0,
        max_stop_speed_mps: float = 3.0,  # Must slow down below ~10 km/h to pickup/dropoff
        language: str = "fi",
        resident_manager: Optional[ResidentManager] = None,
    ):
        # Filter to the largest connected road network to avoid isolated trapped roads
        self.ways = connected_drivable_ways(ways)
        self._ways_grid = None  # (the self.ways list it indexes, SpatialWayGrid, id(way) -> position): _ways_near
        self.places = places or []
        self.buildings = buildings or []
        self.taxi_stops = taxi_stops or []
        self.min_distance_m = min_distance_m
        self.max_distance_m = max_distance_m
        self.pickup_radius_m = pickup_radius_m
        self.max_stop_speed_mps = max_stop_speed_mps
        self.language = language
        self.residents = resident_manager if resident_manager is not None else ResidentManager()
        self.game_time_seconds = 18.0 * 60.0 * 60.0

        self.current_passenger: Optional[TaxiPassenger] = None
        self.released_parties: List[TaxiPassenger] = []
        self.rail_bookings = None
        self.driver_on_foot = False  # set every tick by simulation.advance_simulation
        self.offers: List[TaxiOffer] = []
        self._initial_offer_pending = True
        self.fares_open = True  # False while the game starts up (the server opens it for the first client)
        self.state: str = TaxiState.WAITING_FOR_PICKUP
        self.total_score: int = 0
        self.completed_fares: int = 0
        self.trip_start_time: float = 0.0
        self.elapsed_time: float = 0.0
        self.trip_distance_m: float = 0.0
        self.last_fare_points: int = 0
        self.balance_cents: int = 0
        self.last_fare_cents: int = 0
        self.last_tip_cents: int = 0
        self.passenger_happiness: float = 50.0
        self.game_date: date = date.today()
        self.fare_started_at: Optional[datetime] = None
        self.fare_start_odometer_m: Optional[float] = None
        self.fare_distance_m: float = 0.0
        self.live_fare_cents: int = 0
        self.notification_msg: str = ""
        self.notification_timer: float = 0.0
        self.next_offer_timer: float = random.uniform(PHONE_OFFER_MIN_INTERVAL_S, PHONE_OFFER_MAX_INTERVAL_S)
        self.stand_wait_timer: float = 0.0
        self.long_fare_retry_timer: float = 0.0
        self.intercity_fares_enabled = False
        self.intercity_places = None

        self._crashed_building_cooldowns: Dict[int, float] = {}  # building id -> timestamp cooldown
        self._crashed_tree_cooldowns: Dict[Tuple[int, int], float] = {}
        self._crashed_fence_cooldowns: Dict[int, float] = {}  # scenery id -> timestamp cooldown
        self._tram_crash_at = -1e9  # sim time of the last tram crash (one penalty an impact)
        self._crashed_post_cooldowns: Dict[int, float] = {}  # bollard/lamp id -> timestamp cooldown
        self._post_grid: Dict[Tuple[int, int], List[Any]] = {}
        self._post_ref = None
        self._post_count = 0
        self.knocked_posts = 0  # how many bollards/lamps lie flat (render cache revision)
        self.broken_lamps: set = set()  # (x, y) of knocked-down street lamps: their light is off
        self._curb_bump_cooldowns: Dict[int, float] = {}  # curb id -> timestamp cooldown
        self._speed_bump_cooldowns: Dict[int, float] = {}  # speed bump id -> timestamp cooldown
        self._speed_camera_hits: set[int] = set()
        self.tree_effects: Dict[Tuple[int, int], Dict[str, float]] = {}
        self.fallen_trees: set[Tuple[int, int]] = set()
        self.tree_wait_timer: float = 0.0
        self._building_collision_grid: Dict[Tuple[int, int], List[Building]] = {}
        self._building_collision_ref = None
        self._building_collision_count = 0
        self._tree_collision_grid: Dict[Tuple[int, int], List[Tuple[int, int, float, float]]] = {}
        self._tree_collision_ref = None
        self._tree_collision_count = 0
        self._fence_collision_grid: Dict[Tuple[int, int], List[Any]] = {}
        self._fence_collision_ref = None
        self._fence_collision_count = 0
        self.broken_hedges: Dict[Any, List[List[Tuple[float, float]]]] = {}  # session damage, keyed by original geometry and layer
        self.barrier_sound = "collision.fence"
        self._barrier_grid: Dict[Tuple[int, int], List[Any]] = {}  # linear barriers (Railing), indexed as they stream in
        self._barrier_ref = None
        self._barrier_count = 0
        self.vomit_puddles: List[Tuple[float, float]] = []
        self.taxi_smoke_timer: float = 0.0
        self.speed_camera_flash_timer: float = 0.0
        self.speed_camera_flash_index: Optional[int] = None
        self.speed_camera_notice_timer: float = 0.0
        self.speed_camera_notice_msg: str = ""
        self.wrong_way_duration: float = 0.0
        self.wrong_way_penalty_cooldown: float = 0.0
        self.pedestrian_way_penalty_cooldown: float = 0.0

    def _new_passenger_identity(
        self, resident: Optional[Resident] = None
    ) -> tuple[str, str, int, float]:
        resident = resident or self.residents.create("walking", min_age=18)
        gender = {"female": "woman", "male": "man"}.get(resident.gender, "woman")
        return (
            f"{resident.first_name} {resident.surname}",
            gender,
            resident.resident_id,
            resident.weight_kg,
        )

    def _make_party(self, passenger: TaxiPassenger, *, generated=False, pedestrians=()) -> bool:
        """One fare, at most four passengers; minors travel with their own adult parent."""
        ids = [passenger.resident_id]
        resident = self.residents.get(passenger.resident_id)
        if resident is None:
            return True  # Legacy/test passengers without a registry identity.
        if self.residents.age_of(resident) < 18:
            passenger.is_drunk = False
            passenger.nausea_delay = float("inf")
        if not generated and self.residents.age_of(resident) >= 18:
            ids.extend(p.resident_id for p in pedestrians
                       if getattr(p, "resident_id", None) in resident.child_ids
                       and self.residents.get(p.resident_id) is not None
                       and self.residents.age_of(self.residents.get(p.resident_id)) < 18
                       and math.hypot(p.x - passenger.ped_x, p.y - passenger.ped_y) <= 5.0)
        if generated and random.random() < 0.35:
            for _ in range(random.randint(1, 3)):
                member = self.residents.create("walking", min_age=18)
                ids.append(member.resident_id)
        parent_age = self.residents.age_of(resident)
        if generated and len(ids) <= 2 and 25 <= parent_age <= 61 and random.random() < 0.25:
            child = self.residents.create("walking", age=random.randint(max(7, parent_age - 44), min(17, parent_age - 18)))
            # This newly generated family travels together; don't borrow a parent elsewhere in the city.
            for pid in child.parent_ids:
                self.residents.get(pid).child_ids.discard(child.resident_id)
            child.parent_ids = {resident.resident_id}
            resident.child_ids.add(child.resident_id)
            ids.append(child.resident_id)
        for rid in list(ids):
            child = self.residents.get(rid)
            if child is None or self.residents.age_of(child) >= 18:
                continue
            parents = [self.residents.get(pid) for pid in sorted(child.parent_ids)]
            parents = [p for p in parents if p is not None and self.residents.age_of(p) >= 18]
            reserved = {p.resident_id for offer in self.offers for p in offer.passenger.members}
            parents = [p for p in parents if p.active_vehicle_id is None
                       and (p.resident_id in ids or p.resident_id not in reserved)]
            if not generated:
                parents = [p for p in parents if any(
                    getattr(ped, "resident_id", None) == p.resident_id and math.hypot(ped.x - passenger.ped_x, ped.y - passenger.ped_y) <= 5.0
                    for ped in pedestrians)]
            if not parents:
                return False
            parent = next((p for p in parents if p.resident_id in ids), parents[0])
            if parent.resident_id not in ids:
                ids.append(parent.resident_id)
        if len(set(ids)) != len(ids) or len(ids) > 4:
            return False
        passenger.companions = []
        for index, rid in enumerate(ids[1:], 1):
            member = self.residents.get(rid)
            name, gender, _, weight = self._new_passenger_identity(member)
            pedestrian = next((p for p in pedestrians if p.resident_id == rid), None)
            passenger.companions.append(TaxiPassenger(
                name, passenger.pickup, passenger.dropoff, gender=gender, resident_id=rid, weight_kg=weight,
                ped_x=pedestrian.x if pedestrian else passenger.ped_x + math.cos(passenger.ped_heading) * index * 0.8,
                ped_y=pedestrian.y if pedestrian else passenger.ped_y + math.sin(passenger.ped_heading) * index * 0.8,
                ped_speed=passenger.ped_speed, boarded=passenger.boarded,
                is_walking_to_car=passenger.is_walking_to_car, nausea_delay=float("inf"),
            ))
        return True

    def _party_valid(self, passenger: TaxiPassenger) -> bool:
        members = passenger.members
        ids = [p.resident_id for p in members if p.resident_id is not None]
        if len(members) > 4 or len(ids) != len(set(ids)) or any(p.companions for p in passenger.companions):
            return False
        if passenger.boarded and not all(p.boarded for p in members):
            return False
        if any((r := self.residents.get(rid)) is not None and r.active_vehicle_id is not None for rid in ids):
            return False
        adults = {rid for rid in ids if (r := self.residents.get(rid)) is not None and self.residents.age_of(r) >= 18}
        return all(r is None or self.residents.age_of(r) >= 18 or bool(r.parent_ids & adults)
                   for p in members for r in [self.residents.get(p.resident_id)])

    def nausea_delay_for_pickup(self, pickup: TaxiTarget) -> float:
        return nausea_delay_for_pickup(pickup, self.game_time_seconds)

    def _warn_if_passenger_is_drunk(self, passenger: TaxiPassenger) -> None:
        if passenger.is_drunk:
            self.notification_msg = tr(self.language, "passenger_smells_intoxicated")
            self.notification_timer = 4.0

    def _current_game_datetime(self) -> datetime:
        return datetime.combine(self.game_date, datetime.min.time()) + timedelta(seconds=self.game_time_seconds)

    def current_fare_cents(self) -> int:
        """Return the live meter amount for the onboard passenger."""
        return self.live_fare_cents

    def phone_item_index(self, item_id: str) -> Optional[int]:
        """The phone row of a client-side id ("offer-N" / "booking-N"), or None
        once it is gone (expired, taken, declined)."""
        for index, (kind, item) in enumerate(self.phone_items()):
            if f"{kind}-{item.offer_id if kind == 'offer' else item.id}" == item_id:
                return index
        return None

    def phone_items(self):
        """The three numbered phone rows: rail bookings first, then ordinary offers."""
        bookings = self.rail_bookings.visible() if self.rail_bookings is not None else []
        bookings.sort(key=lambda booking: booking.status != "PENDING")
        return ([("booking", item) for item in bookings] + [("offer", item) for item in self.offers])[:MAX_PHONE_OFFERS]

    def has_new_requests(self) -> bool:
        """Something in the phone to answer: a ride offer or a rail
        pre-booking still pending (accepted ones are no longer requests)."""
        return bool(self.offers or (self.rail_bookings is not None and self.rail_bookings.pending()))

    def visible_rail_bookings(self):
        return self.rail_bookings.visible() if self.rail_bookings is not None else []

    def has_active_job(self) -> bool:
        """A fare under way, or a booked rail passenger waiting to be met:
        either way the game clock runs in real time, not 60x (a waiting
        booking's pickup window is game time)."""
        return self.current_passenger is not None or bool(self.rail_bookings is not None and self.rail_bookings.waiting())

    def has_job(self) -> bool:
        """A fare on, or an accepted pre-booking not yet finished: the phone
        takes nothing more until it's done (nothing is queued)."""
        return self.current_passenger is not None or any(
            booking.status in (ACCEPTED, TRAIN_ARRIVING, PASSENGER_WAITING, PASSENGER_MET)
            for booking in (self.rail_bookings.bookings if self.rail_bookings is not None else ())
        )

    def meet_booking(self):
        """The booking the driver is meeting now: the earliest-arriving
        passenger still waiting, while no other fare is under way."""
        if self.current_passenger is not None or self.rail_bookings is None:
            return None
        return min(self.rail_bookings.waiting(), key=lambda booking: booking.arrival_at, default=None)

    def meet_context(self):
        """The pre-booked pickup in progress, from accepting it until the
        passenger is in the taxi: the greeted one walking to the taxi, the
        one being met, else the next accepted one whose train is due."""
        booking = getattr(self.current_passenger, "rail_booking", None)
        if booking is not None and booking.status == PASSENGER_MET:
            return booking
        booking = self.meet_booking()
        if booking is not None or self.current_passenger is not None or self.rail_bookings is None:
            return booking
        return min(
            (b for b in self.rail_bookings.bookings if b.status in (ACCEPTED, TRAIN_ARRIVING)),
            key=lambda b: b.arrival_at, default=None,
        )

    def meet_prompt(self, player: Any) -> Optional[Tuple[Any, str]]:
        """(booking, localization key of what the driver should do now) for
        the meet & greet in progress, or None."""
        booking = self.meet_context()
        if booking is None:
            return None
        if booking.status == PASSENGER_MET:
            return booking, "meet_back_to_taxi" if self.driver_on_foot else "meet_passenger_to_taxi"
        if booking.status in (ACCEPTED, TRAIN_ARRIVING):
            return booking, "meet_train_due"
        if booking.passenger.pedestrian is None:
            return booking, "meet_go_to_stand"
        if not self.driver_on_foot:
            return booking, "meet_get_out"
        return booking, "hint_greet_passenger" if self.greetable(player) is not None else "meet_walk_to_passenger"

    def greetable(self, player: Any):
        """(booking, pedestrian) when the driver on foot stands by the
        meet booking's own pedestrian (booking -> passenger -> pedestrian)."""
        booking = self.meet_booking()
        pedestrian = booking.passenger.pedestrian if booking is not None else None
        if pedestrian is None or math.hypot(player.x - pedestrian.x, player.y - pedestrian.y) > GREET_RADIUS_M:
            return None
        return booking, pedestrian

    def greet_booked_passenger(self, player: Any, car: Car, pedestrians=()) -> Optional[Any]:
        """The driver's explicit greeting: the only way to PASSENGER_MET. The
        passenger then walks to the taxi; returns their pedestrian (now the
        fare's) or None."""
        found = self.greetable(player)
        if found is None:
            return None
        booking, pedestrian = found
        if not self._board_waiting_pedestrian(
            pedestrian, self.make_target(car.x, car.y), "stand_boarded", walk_to_car=True, booking=booking,
            pedestrians=pedestrians,
        ):
            return None
        # The same pedestrian walks to the taxi door along the footways (the
        # pedestrian system's own stand walk, now routed), no longer a stand
        # customer anyone else could pick up.
        pedestrian.wants_taxi = pedestrian.is_taxi_stop_waiter = False
        pedestrian.taxi_stop_target = self._door_position(car)
        pedestrian.is_walking_to_taxi_stop = True
        pedestrian.base_speed = self.current_passenger.ped_speed
        pedestrian.route = None
        self.notification_msg = tr(
            self.language, "rail_booking_met", name=self.current_passenger.name,
            train=booking.train_number, address=booking.destination.address,
        )
        return pedestrian

    @staticmethod
    def _door_position(car: Car) -> Tuple[float, float]:
        """The taxi's passenger-side door (side offset relative to heading)."""
        door_offset_side = 1.2
        door_offset_long = -0.5
        return (
            car.x + math.cos(car.heading) * door_offset_long + math.sin(car.heading) * door_offset_side,
            car.y - math.sin(car.heading) * door_offset_long - math.cos(car.heading) * door_offset_side,
        )

    def notify_rail_booking(self, booking) -> None:
        self.notification_msg = tr(
            self.language, "rail_booking_notice", train=booking.train_number,
            station=booking.station, arrival=f"{booking.arrival_at:%H:%M}",
        )
        self.notification_timer = 5.0

    def adjust_passenger_happiness(self, amount: float) -> None:
        if self.current_passenger is not None and self.state == TaxiState.DRIVING_TO_DROPOFF:
            self.passenger_happiness = max(0.0, min(100.0, self.passenger_happiness + amount))

    def update_passenger_happiness(
        self, dt: float, speed_mps: float, speed_limit_mps: Optional[float], is_sliding: bool,
    ) -> None:
        """Reward brisk legal progress and penalize reckless driving."""
        if self.current_passenger is None or self.state != TaxiState.DRIVING_TO_DROPOFF:
            return
        speed_kmh = abs(speed_mps) * 3.6
        if speed_kmh >= 30.0:
            safe_speed_factor = min(1.0, (speed_kmh - 30.0) / 50.0)
            self.adjust_passenger_happiness(0.08 * safe_speed_factor * dt)
        if speed_limit_mps is not None and abs(speed_mps) > speed_limit_mps * 1.15:
            excess_ratio = abs(speed_mps) / max(0.1, speed_limit_mps) - 1.15
            self.adjust_passenger_happiness(-0.35 * (1.0 + excess_ratio) * dt)
        if is_sliding:
            self.adjust_passenger_happiness(-0.6 * dt)

    @staticmethod
    def _collision_cells(minx: float, miny: float, maxx: float, maxy: float, cell_size: float = 100.0):
        for cell_x in range(math.floor(minx / cell_size), math.floor(maxx / cell_size) + 1):
            for cell_y in range(math.floor(miny / cell_size), math.floor(maxy / cell_size) + 1):
                yield cell_x, cell_y

    def _nearby_collision_buildings(self, buildings: List[Building], x: float, y: float, radius: float):
        # autofetch.py's _extend_unique() only ever grows this list in
        # place (target.extend(...) - same list object, never reordered
        # or shrunk) as new tiles stream in, so a real, growing city map
        # made this fire on nearly every frame right after a tile
        # integrated - and rebuilt the *entire* grid from every building
        # ever loaded, not just the new ones, every single time. Confirmed
        # via a real autofetch-enabled drive: "collisions" dominated 97%
        # of frames that missed the 60fps budget, several ms each,
        # clustered right around tile-integration frames, car speed
        # irrelevant (0 m/s reproduced it too - this scales with total
        # loaded map size, not how far the player has driven). Indexing
        # only the newly appended tail is safe exactly because of that
        # append-only guarantee; only fall back to a full rebuild for a
        # genuinely different list (a new city) or the list somehow
        # shrinking (defensive - autofetch never does this today).
        if buildings is not self._building_collision_ref:
            self._building_collision_grid.clear()
            self._building_collision_ref = buildings
            self._building_collision_count = 0
        if len(buildings) < self._building_collision_count:
            self._building_collision_grid.clear()
            self._building_collision_count = 0
        if len(buildings) > self._building_collision_count:
            for building in buildings[self._building_collision_count:]:
                if str(getattr(building, "building_type", "") or "").casefold() in OPEN_ROOF_BUILDING_TYPES:
                    continue
                bbox = getattr(building, "bbox", (0.0, 0.0, 0.0, 0.0))
                if bbox == (0.0, 0.0, 0.0, 0.0):
                    points = getattr(building, "points_m", [])
                    if not points:
                        continue
                    xs, ys = zip(*points)
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    building.bbox = bbox
                for cell in self._collision_cells(*bbox):
                    self._building_collision_grid.setdefault(cell, []).append(building)
            self._building_collision_count = len(buildings)
        nearby = []
        seen = set()
        for cell in self._collision_cells(x - radius, y - radius, x + radius, y + radius):
            for building in self._building_collision_grid.get(cell, ()):
                building_id = id(building)
                if building_id not in seen:
                    seen.add(building_id)
                    nearby.append(building)
        return nearby

    def _nearby_collision_trees(self, sceneries: List[Any], x: float, y: float, radius: float):
        if sceneries is not self._tree_collision_ref:
            self._tree_collision_grid.clear()
            self._tree_collision_ref = sceneries
            self._tree_collision_count = 0
        if len(sceneries) < self._tree_collision_count:
            self.invalidate_tree_collision_index()
            self._tree_collision_ref = sceneries
        for scenery_index in range(self._tree_collision_count, len(sceneries)):
            for tree_index, (tree_x, tree_y) in enumerate(getattr(sceneries[scenery_index], "trees", ())):
                cell = (math.floor(tree_x / 100.0), math.floor(tree_y / 100.0))
                self._tree_collision_grid.setdefault(cell, []).append(
                    (scenery_index, tree_index, tree_x, tree_y)
                )
        self._tree_collision_count = len(sceneries)
        nearby = []
        for cell in self._collision_cells(x - radius, y - radius, x + radius, y + radius):
            nearby.extend(self._tree_collision_grid.get(cell, ()))
        return nearby

    def invalidate_tree_collision_index(self) -> None:
        self._tree_collision_grid.clear()
        self._tree_collision_ref = None
        self._tree_collision_count = 0

    def _nearby_collision_fences(self, sceneries: List[Any], x: float, y: float, radius: float):
        # Same fix, same reason, as _nearby_collision_buildings above -
        # autofetch only ever appends to this list, so index just the new
        # tail on growth instead of rebuilding from every scenery ever
        # loaded.
        if sceneries is not self._fence_collision_ref:
            self._fence_collision_grid.clear()
            self._fence_collision_ref = sceneries
            self._fence_collision_count = 0
        if len(sceneries) < self._fence_collision_count:
            self._fence_collision_grid.clear()
            self._fence_collision_count = 0
        if len(sceneries) > self._fence_collision_count:
            for scenery in sceneries[self._fence_collision_count:]:
                if str(getattr(scenery, "kind", "")).lower() not in SOLID_AREA_KINDS:
                    continue
                bbox = getattr(scenery, "bbox", (0.0, 0.0, 0.0, 0.0))
                if bbox == (0.0, 0.0, 0.0, 0.0):
                    points = getattr(scenery, "points_m", [])
                    if not points:
                        continue
                    xs, ys = zip(*points)
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                for cell in self._collision_cells(*bbox):
                    self._fence_collision_grid.setdefault(cell, []).append(scenery)
            self._fence_collision_count = len(sceneries)
        nearby = []
        seen = set()
        for cell in self._collision_cells(x - radius, y - radius, x + radius, y + radius):
            for scenery in self._fence_collision_grid.get(cell, ()):
                scenery_id = id(scenery)
                if scenery_id not in seen:
                    seen.add(scenery_id)
                    nearby.append(scenery)
        return nearby

    def set_language(self, language: str) -> None:
        self.language = language

    def check_speed_cameras(self, car: Car, cameras: List[SpeedCamera], penalty: int = 300,
                            previous_position=None) -> bool:
        """Fine a speeding car seen in a camera's directional 50-meter zone."""
        hit = False
        visible_ids: set[int] = set()
        for camera_index, camera in enumerate(cameras):
            if camera.layer != getattr(car, "layer", 0) or camera.map_level != getattr(car, "map_level", 0):
                continue
            if not camera_sees_car(camera, car.x, car.y, car.heading, previous_position):
                continue
            visible_ids.add(camera_index)
            if abs(car.speed) * 3.6 <= camera.speed_limit_kmh:
                continue
            if camera_index in self._speed_camera_hits:
                continue
            self._speed_camera_hits.add(camera_index)
            self.total_score -= penalty
            self.adjust_passenger_happiness(-10.0)
            self.speed_camera_flash_timer = 0.35
            self.speed_camera_flash_index = camera_index
            speeding_kmh = max(0, round(abs(car.speed) * 3.6 - camera.speed_limit_kmh))
            self.speed_camera_notice_timer = 4.0
            self.speed_camera_notice_msg = tr(
                self.language,
                "speed_camera_hit",
                penalty=penalty,
                excess=speeding_kmh,
            )
            self.notification_msg = self.speed_camera_notice_msg
            self.notification_timer = 4.0
            logger.info("Speed camera triggered: -%d pts", penalty)
            hit = True
        self._speed_camera_hits.intersection_update(visible_ids)
        return hit

    def check_building_collision(
        self,
        player_car: Car,
        buildings: List[Building],
        sim_time: float,
        previous_position: Optional[Tuple[float, float]] = None,
        penalty: int = 200,
        ways: Optional[List[Way]] = None,
        current_way: Optional[Way] = None,
    ) -> bool:
        """Stop the car at a building footprint and apply one crash penalty per impact."""
        expired = [bid for bid, t in self._crashed_building_cooldowns.items() if sim_time - t > 3.0]
        for bid in expired:
            del self._crashed_building_cooldowns[bid]

        car_radius = math.hypot(player_car.length_m, player_car.width_m) * 0.5
        car_corners = get_oriented_box_corners(
            player_car.x, player_car.y, player_car.heading, player_car.length_m, player_car.width_m
        )

        car_level = getattr(player_car, "map_level", SURFACE_LEVEL)
        # OSM bridge layers and logical garage floors are separate coordinates.
        on_elevated_bridge = (
            car_level == SURFACE_LEVEL
            and current_way is not None
            and on_map_level(current_way, car_level)
            and current_way.is_bridge
            and current_way.layer > 0
            and current_way.layer == getattr(player_car, "layer", 0)
            and is_car_road(current_way)
            and any(
                dist_point_to_segment(player_car.x, player_car.y, a[0], a[1], b[0], b[1])
                <= current_way.half_width_m
                for a, b in zip(current_way.points_m, current_way.points_m[1:])
            )
        )
        for building in self._nearby_collision_buildings(buildings, player_car.x, player_car.y, car_radius):
            if not on_map_level(building, car_level):  # only the car's own map level collides
                continue
            # shortcut: surface building heights lack bridge clearance; use deck support until elevations exist.
            if on_elevated_bridge:
                continue
            points = getattr(building, "points_m", [])
            if len(points) < 3:
                continue
            bbox = getattr(building, "bbox", (0.0, 0.0, 0.0, 0.0))
            if bbox != (0.0, 0.0, 0.0, 0.0):
                if (player_car.x < bbox[0] - car_radius or player_car.x > bbox[2] + car_radius
                        or player_car.y < bbox[1] - car_radius or player_car.y > bbox[3] + car_radius):
                    continue

            intersects = point_in_polygon(player_car.x, player_car.y, points)
            if not intersects:
                intersects = any(point_in_polygon(x, y, points) for x, y in car_corners)
            if not intersects:  # an edge or corner poking into the car's side: it crosses the box (not its half-diagonal circle)
                intersects = any(
                    segments_intersect(a, b, points[i], points[(i + 1) % len(points)])
                    for a, b in zip(car_corners, car_corners[1:] + car_corners[:1])
                    for i in range(len(points))
                )
            if not intersects:
                continue

            # OSM occasionally contains building footprints crossed by mapped roads.
            # Check this expensive exception only after a real building collision.
            if ways and any(
                self._road_overlaps_building(way, points, bbox)
                and (
                    getattr(way, "is_tunnel", False)
                    or getattr(way, "layer", 0) == getattr(player_car, "layer", 0)
                )
                and any(
                    dist_point_to_segment(
                        player_car.x, player_car.y,
                        road_start[0], road_start[1], road_end[0], road_end[1],
                    ) <= getattr(way, "half_width_m", 3.0)
                    for road_start, road_end in zip(way.points_m, way.points_m[1:])
                )
                for way in ways
                if is_car_road(way)
            ):
                continue

            if previous_position is not None:
                player_car.x, player_car.y = previous_position
            player_car.speed = 0.0
            self.taxi_smoke_timer = max(self.taxi_smoke_timer, 5.0)
            building_id = id(building)
            if building_id not in self._crashed_building_cooldowns:
                self.total_score -= penalty
                self.adjust_passenger_happiness(-35.0)
                self.notification_msg = tr(self.language, "building_crash", penalty=penalty)
                self.notification_timer = 3.5
                logger.info("Player crashed into building: -%d pts", penalty)
            self._crashed_building_cooldowns[building_id] = sim_time  # every contact frame: pressing on stays one impact
            return True

        return False

    @staticmethod
    def _road_overlaps_building(
        way: Way,
        building_points: List[Tuple[float, float]],
        building_bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> bool:
        """Return whether a road corridor intersects a building footprint."""
        half_width = getattr(way, "half_width_m", 3.0)
        road_points = getattr(way, "points_m", [])
        if len(road_points) < 2:
            return False

        road_bbox = getattr(way, "bbox", None)
        if road_bbox is None or road_bbox == (0.0, 0.0, 0.0, 0.0):
            road_bbox = compute_bbox(road_points)
        if building_bbox is None or building_bbox == (0.0, 0.0, 0.0, 0.0):
            building_bbox = compute_bbox(building_points)
        if (
            road_bbox[2] + half_width < building_bbox[0]
            or road_bbox[0] - half_width > building_bbox[2]
            or road_bbox[3] + half_width < building_bbox[1]
            or road_bbox[1] - half_width > building_bbox[3]
        ):
            return False

        for road_start, road_end in zip(road_points, road_points[1:]):
            if point_in_polygon(road_start[0], road_start[1], building_points):
                return True
            for building_start, building_end in zip(building_points, building_points[1:] + building_points[:1]):
                if segments_intersect(road_start, road_end, building_start, building_end):
                    return True
                if (
                    dist_point_to_segment(
                        building_start[0], building_start[1],
                        road_start[0], road_start[1], road_end[0], road_end[1],
                    ) <= half_width
                ):
                    return True
        return False

    def check_tree_collision(
        self,
        player_car: Car,
        sceneries: List[Any],
        sim_time: float,
        previous_position: Optional[Tuple[float, float]] = None,
        penalty: int = 100,
        ways: Optional[List[Way]] = None,
    ) -> bool:
        """Stop the car at a tree and apply one penalty per impact."""
        expired = [key for key, t in self._crashed_tree_cooldowns.items() if sim_time - t > 3.0]
        for key in expired:
            del self._crashed_tree_cooldowns[key]

        radius = math.hypot(player_car.length_m, player_car.width_m) * 0.5 + TREE_TRUNK_RADIUS_M
        for scenery_index, tree_index, tree_x, tree_y in self._nearby_collision_trees(
            sceneries, player_car.x, player_car.y, radius
        ):
                if not car_hits_tree_trunk(player_car, tree_x, tree_y):
                    continue
                if ways and is_point_on_road(tree_x, tree_y, ways=ways, car_roads_only=True):
                    continue
                scenery = sceneries[scenery_index]
                if previous_position is not None:
                    restore_x, restore_y = previous_position
                else:
                    restore_x, restore_y = player_car.x, player_car.y
                player_car.x, player_car.y = restore_x, restore_y
                impact_speed_kmh = abs(player_car.speed) * 3.6
                player_car.speed = 0.0
                key = (id(scenery), tree_index)
                self.tree_effects[key] = {
                    "shake": 0.55,
                    "leaves": 1.2,
                    "angle": player_car.heading,
                    # World position: the client finds the tree to shake.
                    "x": tree_x,
                    "y": tree_y,
                }
                if impact_speed_kmh > 80.0:
                    self.fallen_trees.add(key)
                    self.tree_wait_timer = 5.0
                self.taxi_smoke_timer = max(self.taxi_smoke_timer, 5.0)
                if key not in self._crashed_tree_cooldowns:
                    self.total_score -= penalty
                    self.adjust_passenger_happiness(-30.0)
                    self.notification_msg = tr(self.language, "tree_crash", penalty=penalty)
                    self.notification_timer = 3.5
                self._crashed_tree_cooldowns[key] = sim_time  # every contact frame: pressing on stays one impact
                return True
        return False

    def check_fence_collision(
        self,
        player_car: Car,
        sceneries: List[Any],
        sim_time: float,
        previous_position: Optional[Tuple[float, float]] = None,
        penalty: int = 150,
    ) -> bool:
        """Stop the car at a construction-site fence or an ice rink's boards
        (SOLID_AREA_KINDS) and apply one crash penalty per impact."""
        expired = [fid for fid, t in self._crashed_fence_cooldowns.items() if sim_time - t > 3.0]
        for fid in expired:
            del self._crashed_fence_cooldowns[fid]

        car_radius = math.hypot(player_car.length_m, player_car.width_m) * 0.5
        car_corners = get_oriented_box_corners(
            player_car.x, player_car.y, player_car.heading, player_car.length_m, player_car.width_m
        )

        for scenery in self._nearby_collision_fences(sceneries, player_car.x, player_car.y, car_radius):
            points = getattr(scenery, "points_m", [])
            if len(points) < 3:
                continue
            bbox = getattr(scenery, "bbox", (0.0, 0.0, 0.0, 0.0))
            if bbox != (0.0, 0.0, 0.0, 0.0):
                if (player_car.x < bbox[0] - car_radius or player_car.x > bbox[2] + car_radius
                        or player_car.y < bbox[1] - car_radius or player_car.y > bbox[3] + car_radius):
                    continue

            intersects = point_in_polygon(player_car.x, player_car.y, points)
            if not intersects:
                intersects = any(point_in_polygon(x, y, points) for x, y in car_corners)
            if not intersects:  # an edge or corner poking into the car's side: it crosses the box (not its half-diagonal circle)
                intersects = any(
                    segments_intersect(a, b, points[i], points[(i + 1) % len(points)])
                    for a, b in zip(car_corners, car_corners[1:] + car_corners[:1])
                    for i in range(len(points))
                )
            if not intersects:
                continue

            if previous_position is not None:
                player_car.x, player_car.y = previous_position
            player_car.speed = 0.0
            self.taxi_smoke_timer = max(self.taxi_smoke_timer, 5.0)
            fence_id = id(scenery)
            if fence_id not in self._crashed_fence_cooldowns:
                self.total_score -= penalty
                self.adjust_passenger_happiness(-25.0)
                self.notification_msg = tr(self.language, "fence_crash", penalty=penalty)
                self.notification_timer = 3.5
                logger.info("Player crashed into construction fence: -%d pts", penalty)
            self._crashed_fence_cooldowns[fence_id] = sim_time  # every contact frame: pressing on stays one impact
            return True

        return False

    def _nearby_barriers(self, railings: List[Any], x: float, y: float, radius: float):
        """Railings near (x, y): a 50 m grid, only its new tail indexed as
        the streamed map appends (like _nearby_collision_fences)."""
        if railings is not self._barrier_ref or len(railings) < self._barrier_count:
            self._barrier_grid.clear()
            self._barrier_ref = railings
            self._barrier_count = 0
        for railing in railings[self._barrier_count:]:
            box = railing.bbox
            for cx in range(int(box[0] // 50), int(box[2] // 50) + 1):
                for cy in range(int(box[1] // 50), int(box[3] // 50) + 1):
                    self._barrier_grid.setdefault((cx, cy), []).append(railing)
        self._barrier_count = len(railings)
        seen = set()
        for cx in range(int((x - radius) // 50), int((x + radius) // 50) + 1):
            for cy in range(int((y - radius) // 50), int((y + radius) // 50) + 1):
                for railing in self._barrier_grid.get((cx, cy), ()):
                    if id(railing) not in seen:
                        seen.add(id(railing))
                        yield railing

    @staticmethod
    def hedge_key(railing):
        return (getattr(railing, "layer", 0), tuple((x, y) for x, y in railing.points_m))

    def check_barrier_collision(
        self,
        player_car: Car,
        railings: List[Any],
        sim_time: float,
        previous_position: Optional[Tuple[float, float]] = None,
        current_way: Optional[Way] = None,
        penalty: int = 150,
    ) -> bool:
        """Break hedges locally; stop at other barriers (open at their gates).
        Apply one crash penalty per impact. On a car
        road they never block: one mapped across a road is not a wall there."""
        self.barrier_sound = "collision.fence"
        if current_way is not None and is_car_road(current_way):
            return False
        car_radius = math.hypot(player_car.length_m, player_car.width_m) * 0.5
        corners = get_oriented_box_corners(
            player_car.x, player_car.y, player_car.heading, player_car.length_m, player_car.width_m
        )
        edges = list(zip(corners, corners[1:] + corners[:1]))
        layer = getattr(player_car, "layer", 0)
        travel = math.dist(previous_position, (player_car.x, player_car.y)) if previous_position else 0.0
        radius = car_radius + travel
        hedge_sweep = None
        damaged = False
        for railing in self._nearby_barriers(railings, player_car.x, player_car.y, radius):
            if getattr(railing, "layer", 0) != layer:
                continue
            box = railing.bbox
            if (player_car.x < box[0] - radius or player_car.x > box[2] + radius
                    or player_car.y < box[1] - radius or player_car.y > box[3] + radius):
                continue
            points = railing.points_m
            if railing.kind == "hedge":
                from shapely.geometry import LineString, MultiLineString, Polygon
                if hedge_sweep is None:
                    hedge_sweep = Polygon(corners)
                    if previous_position is not None:
                        previous_corners = get_oriented_box_corners(*previous_position, player_car.heading, player_car.length_m, player_car.width_m)
                        hedge_sweep = hedge_sweep.union(Polygon(previous_corners)).convex_hull
                key = self.hedge_key(railing)
                fragments = self.broken_hedges.get(key, [points])
                geometry = MultiLineString(fragments) if fragments else LineString()
                if not geometry.intersects(hedge_sweep):
                    continue
                remaining = geometry.difference(hedge_sweep.buffer(0.65))
                pieces = [remaining] if remaining.geom_type == "LineString" else list(remaining.geoms)
                self.broken_hedges[key] = [list(piece.coords) for piece in pieces if not piece.is_empty and piece.length > .05]
                player_car.speed *= .85
                self.barrier_sound = "collision.hedge_break"
                damaged = True
                barrier_id = id(railing)
                if barrier_id not in self._crashed_fence_cooldowns:
                    self.total_score -= penalty
                    self.adjust_passenger_happiness(-10.0)
                    self.notification_msg = tr(self.language, "fence_crash", penalty=penalty)
                    self.notification_timer = 3.5
                self._crashed_fence_cooldowns[barrier_id] = sim_time
                continue
            hit = any(
                point_in_polygon(a[0], a[1], corners)
                or any(segments_intersect(a, b, c, d) for c, d in edges)
                for a, b in zip(points, points[1:])
            )
            if not hit:
                continue
            if previous_position is not None:
                from shapely.geometry import LineString, Point
                line = LineString(points)
                if line.distance(Point(player_car.x, player_car.y)) >= line.distance(Point(previous_position)):
                    continue  # already touching, backing away from it: let the car go
                player_car.x, player_car.y = previous_position
            player_car.speed = 0.0
            barrier_id = id(railing)
            if barrier_id not in self._crashed_fence_cooldowns:
                self.total_score -= penalty
                self.adjust_passenger_happiness(-25.0)
                self.notification_msg = tr(self.language, "fence_crash", penalty=penalty)
                self.notification_timer = 3.5
                logger.info("Player crashed into a %s: -%d pts", railing.kind, penalty)
            self._crashed_fence_cooldowns[barrier_id] = sim_time  # every contact frame: pressing on stays one impact
            return True
        return damaged

    def check_tram_collision(
        self,
        player_car: Car,
        tram_mgr,
        sim_time: float,
        previous_position: Optional[Tuple[float, float]] = None,
        penalty: int = 300,
    ) -> bool:
        """Driving into a tram (trams.py): stopped where it was, one penalty
        an impact. A taxi a tram moved into (it overlapped at its previous
        position too) is never held there: it can always drive out."""
        if tram_mgr is None or not tram_mgr.trams:
            return False
        corners = get_oriented_box_corners(
            player_car.x, player_car.y, player_car.heading, player_car.length_m, player_car.width_m
        )
        if not tram_mgr.hits(corners):
            return False
        if previous_position is not None and not tram_mgr.hits(get_oriented_box_corners(
            previous_position[0], previous_position[1], player_car.heading, player_car.length_m, player_car.width_m
        )):
            player_car.x, player_car.y = previous_position
            player_car.speed = 0.0
        self.taxi_smoke_timer = max(self.taxi_smoke_timer, 5.0)
        if sim_time - self._tram_crash_at > 3.0:
            self._tram_crash_at = sim_time
            self.total_score -= penalty
            self.adjust_passenger_happiness(-30.0)
            self.notification_msg = tr(self.language, "tram_crash", penalty=penalty)
            self.notification_timer = 3.5
            logger.info("Player crashed into a tram: -%d pts", penalty)
        return True

    def _nearby_posts(self, objects: List[Any], x: float, y: float):
        """Bollards and lamp posts near (x, y) from a 20 m grid, indexing
        only newly appended objects (the scenery list only grows, like the
        building list in _nearby_collision_buildings)."""
        if objects is not self._post_ref or len(objects) < self._post_count:
            self._post_grid, self._post_ref, self._post_count = {}, objects, 0
        for obj in objects[self._post_count:]:
            if getattr(obj, "kind", None) in POST_KINDS:
                self._post_grid.setdefault((math.floor(obj.x / 20.0), math.floor(obj.y / 20.0)), []).append(obj)
        self._post_count = len(objects)
        cell_x, cell_y = math.floor(x / 20.0), math.floor(y / 20.0)
        return [obj for dx in (-1, 0, 1) for dy in (-1, 0, 1) for obj in self._post_grid.get((cell_x + dx, cell_y + dy), ())]

    def check_post_collision(
        self,
        player_car: Car,
        scenery_objects: List[Any],
        sim_time: float,
        previous_position: Optional[Tuple[float, float]] = None,
        penalty: int = 50,
    ) -> bool:
        """Stop the car at a bollard or lamp post (OSM barrier=bollard,
        highway=street_lamp) and apply one penalty per impact. Hit at
        POST_KNOCK_DOWN_KMH or more, the post bends over in the driving
        direction (post.knocked_angle) and no longer blocks, a lamp breaks
        and goes dark, and the taxi carries on slowed."""
        for key in [k for k, t in self._crashed_post_cooldowns.items() if sim_time - t > 3.0]:
            del self._crashed_post_cooldowns[key]
        cos_h, sin_h = math.cos(player_car.heading), math.sin(player_car.heading)
        half_l = player_car.length_m / 2 + POST_RADIUS_M
        half_w = player_car.width_m / 2 + POST_RADIUS_M
        for post in self._nearby_posts(scenery_objects, player_car.x, player_car.y):
            if getattr(post, "knocked_angle", None) is not None:
                continue  # already lying flat
            dx, dy = post.x - player_car.x, post.y - player_car.y
            if abs(dx * cos_h + dy * sin_h) > half_l or abs(-dx * sin_h + dy * cos_h) > half_w:
                continue
            if abs(player_car.speed) * 3.6 >= POST_KNOCK_DOWN_KMH:
                post.knocked_angle = player_car.heading if player_car.speed >= 0.0 else player_car.heading + math.pi
                self.knocked_posts += 1
                if post.kind == "street_lamp":
                    self.broken_lamps.add((post.x, post.y))
                player_car.speed *= 0.6
            else:
                if previous_position is not None:
                    player_car.x, player_car.y = previous_position
                player_car.speed = 0.0
            if id(post) not in self._crashed_post_cooldowns:
                self.total_score -= penalty
                self.adjust_passenger_happiness(-20.0)
                self.notification_msg = tr(self.language, "post_crash", penalty=penalty)
                self.notification_timer = 3.5
            self._crashed_post_cooldowns[id(post)] = sim_time  # every contact frame: pressing on stays one impact
            return True
        return False

    def check_curb_bump(
        self,
        player_car: Car,
        curbs: List[Curb],
        previous_position: Optional[Tuple[float, float]],
        sim_time: float,
        curb_grid: Optional[SpatialWayGrid] = None,
        speed_factor: float = 0.85,
        bump_back_max_speed_kmh: float = 15.0,
    ) -> bool:
        """Hit a mapped kerb line: at parking/walking speed a real curb is
        a hard stop, so bump the car back onto the road side it came from;
        faster than that it's just a jolt (the car has enough momentum to
        climb it) that slows the car down without stopping it outright."""
        if not curbs or previous_position is None:
            return False
        px, py = previous_position
        if px == player_car.x and py == player_car.y:
            return False

        expired = [key for key, t in self._curb_bump_cooldowns.items() if sim_time - t > 0.5]
        for key in expired:
            del self._curb_bump_cooldowns[key]

        radius = math.hypot(player_car.length_m, player_car.width_m) * 0.5
        candidates = (
            curb_grid.ways_in_rect(
                min(px, player_car.x) - radius, min(py, player_car.y) - radius,
                max(px, player_car.x) + radius, max(py, player_car.y) + radius,
            )
            if curb_grid is not None
            else curbs
        )
        for curb in candidates:
            curb_id = id(curb)
            if curb_id in self._curb_bump_cooldowns:
                continue
            points = curb.points_m
            for start, end in zip(points, points[1:]):
                if segments_intersect((px, py), (player_car.x, player_car.y), start, end):
                    self._curb_bump_cooldowns[curb_id] = sim_time
                    if abs(player_car.speed) * 3.6 <= bump_back_max_speed_kmh:
                        player_car.x, player_car.y = px, py
                        player_car.speed = 0.0
                    else:
                        player_car.speed *= speed_factor
                    return True
        return False

    def check_speed_bump(
        self,
        player_car: Car,
        speed_bumps: List[SpeedBump],
        previous_position: Optional[Tuple[float, float]],
        sim_time: float,
        speed_bump_grid: Optional[SpatialWayGrid] = None,
        safe_speed_kmh: float = 25.0,
        max_slowdown: float = 0.5,
    ) -> bool:
        """Jolt and slow the car when it drives over a speed bump/table/
        cushion - harder the faster it was going, like a real one. Under
        `safe_speed_kmh` (a driver taking it properly slow) there's no
        penalty at all; above it, the car loses more speed the further
        over that it was going, capped at `max_slowdown` so it can never
        outright stop the car."""
        if not speed_bumps or previous_position is None:
            return False
        px, py = previous_position
        if px == player_car.x and py == player_car.y:
            return False

        expired = [key for key, t in self._speed_bump_cooldowns.items() if sim_time - t > 1.0]
        for key in expired:
            del self._speed_bump_cooldowns[key]

        radius = math.hypot(player_car.length_m, player_car.width_m) * 0.5
        candidates = (
            speed_bump_grid.ways_in_rect(
                min(px, player_car.x) - radius, min(py, player_car.y) - radius,
                max(px, player_car.x) + radius, max(py, player_car.y) + radius,
            )
            if speed_bump_grid is not None
            else speed_bumps
        )
        for bump in candidates:
            bump_id = id(bump)
            if bump_id in self._speed_bump_cooldowns:
                continue
            # The bump spans width_m across the road, centered on (x, y);
            # build that short perpendicular segment and test whether the
            # car's movement this frame crossed it.
            angle = getattr(bump, "direction_angle", None) or 0.0
            half_w = getattr(bump, "width_m", 3.5) * 0.5
            perp_x, perp_y = -math.sin(angle), math.cos(angle)
            start = (bump.x - perp_x * half_w, bump.y - perp_y * half_w)
            end = (bump.x + perp_x * half_w, bump.y + perp_y * half_w)
            if segments_intersect((px, py), (player_car.x, player_car.y), start, end):
                self._speed_bump_cooldowns[bump_id] = sim_time
                speed_kmh = abs(player_car.speed) * 3.6
                if speed_kmh > safe_speed_kmh:
                    excess_kmh = speed_kmh - safe_speed_kmh
                    slowdown = min(max_slowdown, excess_kmh / 150.0)
                    player_car.speed *= (1.0 - slowdown)
                return True
        return False

    def get_red_light_assist_speed_limit(
        self,
        car: Car,
        traffic_lights: List[Any],
        sim_time: float,
        detection_distance_m: float = 45.0,
        stop_buffer_m: float = 4.0,
        deceleration_mps2: float = 4.0,
    ) -> Optional[float]:
        """Return a comfortable speed target for the nearest red light ahead."""
        nearest = nearest_traffic_light_ahead(car.x, car.y, car.heading, traffic_lights, detection_distance_m)
        if nearest is None or nearest[1].get_state(sim_time) not in ("red", "red+yellow"):
            return None

        available_distance = max(0.0, nearest[0] - stop_buffer_m)
        return math.sqrt(2.0 * deceleration_mps2 * available_distance)

    def sees_red_light(
        self,
        car: Car,
        traffic_lights: List[Any],
        sim_time: float,
        detection_distance_m: float = 45.0,
    ) -> bool:
        """Return whether the taxi is approaching a visible red traffic light."""
        nearest = nearest_traffic_light_ahead(car.x, car.y, car.heading, traffic_lights, detection_distance_m)
        return nearest is not None and nearest[1].get_state(sim_time) in ("red", "red+yellow")

    def check_wrong_way_violation(
        self,
        car: Car,
        dt: float,
        ways: Optional[List[Way]] = None,
        spatial_grid: Optional[SpatialWayGrid] = None,
        penalty: int = 50,
        interval_s: float = 5.0,
    ) -> bool:
        """Check if player is driving in wrong direction on a one-way road and apply penalty every 5 seconds."""
        # Only check if car is actually moving (speed > 1.5 m/s)
        if abs(car.speed) < 1.5:
            self.wrong_way_duration = 0.0
            return False

        dx = math.cos(car.heading) * car.speed * dt
        dy = math.sin(car.heading) * car.speed * dt

        is_violating = is_violating_oneway(
            car,
            car.x,
            car.y,
            dx,
            dy,
            ways=ways,
            spatial_grid=spatial_grid,
        )

        if is_violating:
            self.wrong_way_duration += dt
            self.wrong_way_penalty_cooldown += dt
            if self.wrong_way_penalty_cooldown >= interval_s:
                self.wrong_way_penalty_cooldown = 0.0
                self.total_score -= penalty
                self.adjust_passenger_happiness(-10.0)
                self.notification_msg = tr(self.language, "wrong_way_penalty", penalty=penalty)
                self.notification_timer = 3.5
                logger.info("Player driving wrong way on one-way road: -%d pts penalty", penalty)
            return True
        else:
            self.wrong_way_duration = 0.0
            self.wrong_way_penalty_cooldown = 0.0
            return False

    def check_pedestrian_way_violation(
        self,
        car: Car,
        dt: float,
        ways: Optional[List[Way]] = None,
        spatial_grid: Optional[SpatialWayGrid] = None,
        penalty: int = 50,
        interval_s: float = 5.0,
    ) -> bool:
        """Driving along a footway/path/cycleway is never slowed down, but
        costs penalty points every interval_s, like driving the wrong way
        on a one-way road."""
        if abs(car.speed) < 1.5 or is_point_on_road(
            car.x, car.y, ways=ways, spatial_grid=spatial_grid, car_roads_only=True, layer=car.layer
        ) or not is_point_on_light_traffic_way(car.x, car.y, ways=ways, spatial_grid=spatial_grid):
            self.pedestrian_way_penalty_cooldown = 0.0
            return False
        self.pedestrian_way_penalty_cooldown += dt
        if self.pedestrian_way_penalty_cooldown >= interval_s:
            self.pedestrian_way_penalty_cooldown = 0.0
            self.total_score -= penalty
            self.adjust_passenger_happiness(-15.0)
            self.notification_msg = tr(self.language, "pedestrian_way_penalty", penalty=penalty)
            self.notification_timer = 3.5
            logger.info("Player driving on a pedestrian way: -%d pts penalty", penalty)
        return True

    def sync_map_data(
        self,
        ways: List[Way],
        places: Optional[List[Place]] = None,
        buildings: Optional[List[Building]] = None,
        connected: Optional[List[Way]] = None,
    ) -> None:
        """Update road and place references when map expands dynamically.
        `connected`: connected_drivable_ways(ways) computed by the
        caller already (map sync does it off the tick)."""
        self.ways = connected if connected is not None else connected_drivable_ways(ways)
        if places is not None:
            self.places = places
        if buildings is not None:
            self.buildings = buildings

    def get_nearest_district(self, x: float, y: float) -> Optional[str]:
        """Find the closest named district / suburb / place."""
        if not self.places:
            return None
        best_p = None
        best_dist = float("inf")
        for p in self.places:
            d = math.hypot(p.x - x, p.y - y)
            if d < best_dist:
                best_dist = d
                best_p = p
        if best_p and best_dist < 4000.0:
            return best_p.name
        return None

    def find_nearest_named_road(self, x: float, y: float, max_search_m: float = 600.0) -> Optional[str]:
        """Find the name of the nearest named road to a given position."""
        best_name = None
        best_dist = float("inf")
        for w in self.ways:
            if getattr(w, "name", None) and len(w.points_m) >= 2:
                # Check distance to segments in this way
                for i in range(len(w.points_m) - 1):
                    p1 = w.points_m[i]
                    p2 = w.points_m[i + 1]
                    d = dist_point_to_segment(x, y, p1[0], p1[1], p2[0], p2[1])
                    if d < best_dist:
                        best_dist = d
                        best_name = w.name
        if best_name and best_dist <= max_search_m:
            return best_name
        return None

    def _ways_near(self, x: float, y: float, reach: float) -> List[Way]:
        """self.ways that may come within `reach` of (x, y), in self.ways
        order - a nearest-road search over them ends on the same road as one
        over every way, ties included. The index is built on first use after
        the ways change (map sync)."""
        if self._ways_grid is None or self._ways_grid[0] is not self.ways:
            self._ways_grid = (self.ways, SpatialWayGrid(self.ways, cell_size=250.0),
                               {id(way): index for index, way in enumerate(self.ways)})
        _, grid, order = self._ways_grid
        return sorted(grid.ways_in_rect(x - reach, y - reach, x + reach, y + reach), key=lambda way: order[id(way)])

    def passenger_waiting_position(self, target: TaxiTarget) -> Tuple[float, float, float]:
        """Place a phone passenger at the right edge of the nearest road."""
        reach = 250.0
        while True:  # the nearest road found within `reach` is the nearest of all
            nearest = None
            nearest_distance = float("inf")
            for way in self._ways_near(target.x, target.y, reach):
                for start, end in zip(way.points_m, way.points_m[1:]):
                    px, py, _, distance = closest_point_and_dist_to_segment(
                        target.x, target.y, start[0], start[1], end[0], end[1]
                    )
                    if distance < nearest_distance:
                        nearest = (way, start, end, px, py)
                        nearest_distance = distance
            if nearest_distance <= reach or reach > 1e6:
                break
            reach *= 4.0
        if nearest is None:
            return target.x, target.y, 0.0

        way, start, end, px, py = nearest
        heading = math.atan2(end[1] - start[1], end[0] - start[0])
        half_width = max(0.0, getattr(way, "half_width_m", 4.0))
        # Must clear the road's own half-width (is_point_on_road's exact
        # threshold) plus a curb/sidewalk margin - this used to cap the
        # offset *below* half_width, which placed the passenger inside
        # the roadway itself (a lane or more into a wide road like a
        # motorway) instead of on the sidewalk beside it.
        offset = half_width + 1.8
        return (
            px + math.sin(heading) * offset,
            py - math.cos(heading) * offset,
            heading,
        )

    def find_nearest_osm_address(
        self, x: float, y: float, street_name: Optional[str] = None, max_search_m: float = 250.0
    ) -> Optional[str]:
        """Look for real OSM house numbers on buildings near (x, y)."""
        if not self.buildings:
            return None

        best_housenumber: Optional[str] = None
        best_dist = float("inf")

        for b in self.buildings:
            if not b.housenumber:
                continue

            # If street name is specified, prioritize buildings on matching street
            if street_name and b.street:
                if b.street.lower() != street_name.lower():
                    continue

            # Check distance to building centroid or bounding box
            if b.points_m:
                cx = sum(p[0] for p in b.points_m) / len(b.points_m)
                cy = sum(p[1] for p in b.points_m) / len(b.points_m)
            else:
                bb = getattr(b, "bbox", (0.0, 0.0, 0.0, 0.0))
                cx = (bb[0] + bb[2]) / 2.0
                cy = (bb[1] + bb[3]) / 2.0

            d = math.hypot(cx - x, cy - y)
            if d < best_dist:
                best_dist = d
                best_housenumber = b.housenumber

        if best_housenumber and best_dist <= max_search_m:
            return best_housenumber
        return None

    def generate_address_for_point(self, x: float, y: float, way_name: Optional[str] = None) -> Optional[str]:
        """Generate a real street address from OSM data with real road name and real house number if present.

        Returns None if no real street name is available.
        """
        street = way_name
        if not street:
            street = self.find_nearest_named_road(x, y)

        if not street:
            return None

        # Look up real OSM house number nearby on buildings
        real_housenumber = self.find_nearest_osm_address(x, y, street_name=street)
        district = self.get_nearest_district(x, y)

        if real_housenumber:
            if district and district.lower() not in street.lower():
                return f"{street} {real_housenumber}, {district}"
            return f"{street} {real_housenumber}"
        else:
            # Only use real street name without fabricated house number
            if district and district.lower() not in street.lower():
                return f"{street}, {district}"
            return f"{street}"

    def roadside_address(self, x: float, y: float) -> str:
        """An address for a point with no named road near: the roadside of its district."""
        district = self.get_nearest_district(x, y)
        roadside = tr(self.language, "roadside")
        return f"{roadside}, {district}" if district else roadside

    def pick_random_building_point(
        self,
        ref_x: Optional[float] = None,
        ref_y: Optional[float] = None,
        min_dist: float = 0.0,
        max_dist: float = float("inf"),
        max_road_distance: float = 250.0,
        venue_types: Optional[set] = None,
        homes: bool = False,
    ) -> Optional[TaxiTarget]:
        """Pick a named building (or, `homes`, a home with a street address)
        and place its target at the nearest reachable road point."""
        if homes:  # most taxis are ordered home: a house on its own street, not just a venue on a main road
            candidates = [
                building for building in self.buildings
                if getattr(building, "street", None) and getattr(building, "housenumber", None)
                and getattr(building, "building_type", None) in HOME_BUILDING_TYPES
                and len(building.points_m) >= 3
            ]
        else:
            candidates = [
                building for building in self.buildings
                if building.name
                and len(building.points_m) >= 3
                and (venue_types is None or getattr(building, "venue_type", None) in venue_types)
            ]
            candidates.extend(
                place for place in self.places
                if place.name
                and getattr(place, "kind", None) in NIGHTLIFE_VENUE_TYPES
                and (venue_types is None or place.kind in venue_types)
            )
        random.shuffle(candidates)

        for building in candidates:
            points = getattr(building, "points_m", ())
            if points:
                center_x = sum(point[0] for point in points) / len(points)
                center_y = sum(point[1] for point in points) / len(points)
                anchors = list(getattr(building, "entrances", ())) or list(points)
            else:
                center_x = building.x
                center_y = building.y
                anchors = [(center_x, center_y)]
            anchors.append((center_x, center_y))
            # A road point within max_road_distance of an anchor is within `reach` of the
            # centre: only those roads are scanned, and a building that can't meet the
            # distance limits is skipped before any.
            reach = max_road_distance + max(math.hypot(ax - center_x, ay - center_y) for ax, ay in anchors)
            if ref_x is not None and ref_y is not None:
                centre_distance = math.hypot(center_x - ref_x, center_y - ref_y)
                if centre_distance + reach < min_dist or centre_distance - reach > max_dist:
                    continue
            nearest: Optional[Tuple[float, float, str, float]] = None
            nearby = self._ways_near(center_x, center_y, reach)

            for anchor_x, anchor_y in anchors:
                for way in nearby:
                    if len(way.points_m) < 2 or not is_car_road(way):
                        continue
                    for start, end in zip(way.points_m, way.points_m[1:]):
                        dx = end[0] - start[0]
                        dy = end[1] - start[1]
                        length_squared = dx * dx + dy * dy
                        if length_squared <= 1e-9:
                            continue
                        fraction = clamp(
                            ((anchor_x - start[0]) * dx + (anchor_y - start[1]) * dy) / length_squared,
                            0.0,
                            1.0,
                        )
                        road_x = start[0] + fraction * dx
                        road_y = start[1] + fraction * dy
                        road_distance = math.hypot(anchor_x - road_x, anchor_y - road_y)
                        if nearest is None or road_distance < nearest[3]:
                            nearest = (road_x, road_y, way.name or "", road_distance)

            if nearest is None or nearest[3] > max_road_distance:
                continue
            road_x, road_y, way_name, _ = nearest
            if ref_x is not None and ref_y is not None:
                distance = math.hypot(road_x - ref_x, road_y - ref_y)
                if not min_dist <= distance <= max_dist:
                    continue

            venue_type = getattr(building, "venue_type", None) or getattr(building, "kind", None)
            return TaxiTarget(
                x=road_x,
                y=road_y,
                address=building.name if not homes else f"{building.street} {building.housenumber}",
                way_name=way_name,
                district_name=self.get_nearest_district(road_x, road_y),
                radius_m=self.pickup_radius_m,
                venue_type=venue_type,
            )
        return None

    def pick_random_road_point(
        self,
        ref_x: Optional[float] = None,
        ref_y: Optional[float] = None,
        min_dist: float = 0.0,
        max_dist: float = float("inf"),
    ) -> Optional[TaxiTarget]:
        """Pick a road coordinate within distance constraints; an unnamed
        road (a service road, a track) is as good a stop as a street."""
        if not self.ways:
            return None

        candidate_ways = self.ways[:]
        random.shuffle(candidate_ways)

        for w in candidate_ways:
            if len(w.points_m) < 2:
                continue

            way_name = getattr(w, "name", None)

            # Pick a random segment in this way
            idx = random.randint(0, len(w.points_m) - 2)
            p1 = w.points_m[idx]
            p2 = w.points_m[idx + 1]
            t = random.uniform(0.1, 0.9)
            px = p1[0] + t * (p2[0] - p1[0])
            py = p1[1] + t * (p2[1] - p1[1])

            if ref_x is not None and ref_y is not None:
                dist = math.hypot(px - ref_x, py - ref_y)
                if not (min_dist <= dist <= max_dist):
                    continue

            addr = self.generate_address_for_point(px, py, way_name) or self.roadside_address(px, py)

            district = self.get_nearest_district(px, py)
            return TaxiTarget(
                x=px,
                y=py,
                address=addr,
                way_name=way_name,
                district_name=district,
                radius_m=self.pickup_radius_m,
            )

        # If strict distance search didn't match, pick any way
        for w in candidate_ways:
            way_name = getattr(w, "name", None)
            if len(w.points_m) < 2:
                continue
            idx = random.randint(0, len(w.points_m) - 2)
            p1 = w.points_m[idx]
            p2 = w.points_m[idx + 1]
            t = random.uniform(0.1, 0.9)
            px = p1[0] + t * (p2[0] - p1[0])
            py = p1[1] + t * (p2[1] - p1[1])
            return TaxiTarget(
                x=px,
                y=py,
                address=self.generate_address_for_point(px, py, way_name) or self.roadside_address(px, py),
                way_name=way_name,
                district_name=self.get_nearest_district(px, py),
                radius_m=self.pickup_radius_m,
            )
        return None

    def pick_random_taxi_stop(
        self,
        ref_x: Optional[float] = None,
        ref_y: Optional[float] = None,
        min_dist: float = 0.0,
        max_dist: float = float("inf"),
    ) -> Optional[TaxiTarget]:
        stops = self.taxi_stops[:]
        random.shuffle(stops)
        for stop in stops:
            if ref_x is not None and ref_y is not None:
                distance = math.hypot(stop.x - ref_x, stop.y - ref_y)
                if not min_dist <= distance <= max_dist:
                    continue
            way_name = self.find_nearest_named_road(stop.x, stop.y)
            address = self.generate_address_for_point(stop.x, stop.y, way_name) or "Taxi stop"
            return TaxiTarget(
                x=stop.x,
                y=stop.y,
                address=address,
                way_name=way_name,
                district_name=self.get_nearest_district(stop.x, stop.y),
                radius_m=self.pickup_radius_m,
            )
        return None

    def make_target(self, x: float, y: float) -> TaxiTarget:
        """Create a pickup target at an already known position."""
        way_name = self.find_nearest_named_road(x, y)
        return TaxiTarget(
            x=x,
            y=y,
            address=self.generate_address_for_point(x, y, way_name) or self.roadside_address(x, y),
            way_name=way_name,
            district_name=self.get_nearest_district(x, y),
            radius_m=self.pickup_radius_m,
        )

    def spawn_mission(self, car_x: float, car_y: float) -> None:
        """Spawn a new passenger pickup and dropoff destination."""
        hour = (self.game_time_seconds / 3600.0) % 24.0
        if hour < 8.0 or hour >= 20.0:
            pickup_target = self.pick_phone_pickup(car_x, car_y)
        else:
            pickup_target = self.pick_random_building_point(
                ref_x=car_x,
                ref_y=car_y,
                min_dist=150.0,
                max_dist=1200.0,
            )
            if not pickup_target or not pickup_target.address:
                pickup_target = self.pick_random_taxi_stop(
                    ref_x=car_x, ref_y=car_y, min_dist=150.0, max_dist=1200.0
                )
            if not pickup_target:
                pickup_target = self.pick_random_road_point(
                    ref_x=car_x, ref_y=car_y, min_dist=150.0, max_dist=1200.0
                )
        if not pickup_target:
            return

        if hour < 8.0 or hour >= 20.0:
            dropoff_target = self.pick_phone_dropoff(pickup_target.x, pickup_target.y)
        else:
            dropoff_target = self.pick_random_building_point(
                ref_x=pickup_target.x,
                ref_y=pickup_target.y,
                min_dist=self.min_distance_m,
                max_dist=float("inf"),
            )
            if not dropoff_target:
                dropoff_target = self.pick_random_road_point(
                    ref_x=pickup_target.x,
                    ref_y=pickup_target.y,
                    min_dist=self.min_distance_m,
                    max_dist=float("inf"),
                )
        if not dropoff_target:
            dropoff_target = pickup_target

        passenger_name, passenger_gender, resident_id, passenger_weight_kg = self._new_passenger_identity()
        nausea_delay = self.nausea_delay_for_pickup(pickup_target)
        ped_x, ped_y, ped_heading = self.passenger_waiting_position(pickup_target)
        self.current_passenger = TaxiPassenger(
            name=passenger_name,
            pickup=pickup_target,
            dropoff=dropoff_target,
            gender=passenger_gender,
            resident_id=resident_id,
            weight_kg=passenger_weight_kg,
            ped_x=ped_x,
            ped_y=ped_y,
            ped_heading=ped_heading,
            ped_speed=2.2,
            is_walking_to_car=False,
            boarded=False,
            is_drunk=math.isfinite(nausea_delay),
            nausea_delay=nausea_delay,
        )
        if not self._make_party(self.current_passenger, generated=True):
            self.current_passenger = None
            return
        self.state = TaxiState.WAITING_FOR_PICKUP
        self.elapsed_time = 0.0
        self.notification_msg = tr(
            self.language, "new_fare_at", name=passenger_name, address=pickup_target.address
        )
        self.notification_timer = 5.0
        logger.info(
            "Taxi mission spawned: passenger=%s pickup=%s dropoff=%s",
            passenger_name,
            pickup_target.address,
            dropoff_target.address,
        )

    def pick_phone_pickup(self, car_x: float, car_y: float) -> Optional[TaxiTarget]:
        """Pick a phone-order pickup using the intended location mix.

        Every hour bracket falls back to any nearby named road point if its
        preferred source(s) come up empty (e.g. no taxi stop within range
        at night, no building at all in a sparse area) - matching
        spawn_mission's robustness. Without this, a sparse area/time-of-
        day combination could leave generate_offers stuck returning
        nothing indefinitely, since (unlike spawn_mission) it has no other
        fallback of its own.
        """
        hour = (self.game_time_seconds / 3600.0) % 24.0
        pickup: Optional[TaxiTarget] = None
        if 0.0 <= hour < 5.0:
            pickup = self.pick_random_taxi_stop(ref_x=car_x, ref_y=car_y, min_dist=150.0, max_dist=1200.0)
        elif 20.0 <= hour < 24.0 and random.random() < 0.30:
            pickup = self.pick_random_building_point(
                ref_x=car_x,
                ref_y=car_y,
                min_dist=150.0,
                max_dist=1200.0,
                venue_types=NIGHTLIFE_VENUE_TYPES,
            ) or self.pick_random_building_point(
                ref_x=car_x,
                ref_y=car_y,
                min_dist=150.0,
                max_dist=1200.0,
                venue_types=None,
            )
        elif 5.0 <= hour < 8.0 or 20.0 <= hour < 24.0 or 8.0 <= hour < 12.0:
            pickup = self._pick_home_or_building(car_x, car_y)
        else:
            roll = random.random()
            building = lambda x, y, min_dist, max_dist: self._pick_home_or_building(x, y)
            if roll < 0.70:
                sources = (building, self.pick_random_road_point, self.pick_random_taxi_stop)
            elif roll < 0.95:
                sources = (self.pick_random_road_point, building, self.pick_random_taxi_stop)
            else:
                sources = (self.pick_random_taxi_stop, building, self.pick_random_road_point)
            for source in sources:
                pickup = source(car_x, car_y, min_dist=150.0, max_dist=1200.0)
                if pickup:
                    break
        if pickup:
            return pickup
        return self.pick_random_road_point(ref_x=car_x, ref_y=car_y, min_dist=150.0, max_dist=1200.0)

    def _pick_home_or_building(self, car_x: float, car_y: float) -> Optional[TaxiTarget]:
        """A building pickup: a home (HOME_PICKUP_SHARE) or a named place,
        each falling back to the other."""
        homes_first = random.random() < HOME_PICKUP_SHARE
        for homes in (homes_first, not homes_first):
            pickup = self.pick_random_building_point(
                ref_x=car_x, ref_y=car_y, min_dist=150.0, max_dist=1200.0, homes=homes,
            )
            if pickup:
                return pickup
        return None

    def pick_phone_dropoff(self, pickup_x: float, pickup_y: float) -> Optional[TaxiTarget]:
        """Pick a phone-order dropoff using places and addresses only.

        Falls back to any nearby named road point for every hour bracket
        if the preferred building search comes up empty - see
        pick_phone_pickup's docstring for why."""
        hour = (self.game_time_seconds / 3600.0) % 24.0
        dropoff: Optional[TaxiTarget] = None
        if 0.0 <= hour < 5.0 or 5.0 <= hour < 8.0 or 8.0 <= hour < 12.0:
            dropoff = self.pick_random_building_point(
                ref_x=pickup_x,
                ref_y=pickup_y,
                min_dist=self.min_distance_m,
                max_dist=float("inf"),
                venue_types={None},
            )
        elif 20.0 <= hour < 24.0:
            dropoff = self.pick_random_building_point(
                ref_x=pickup_x,
                ref_y=pickup_y,
                min_dist=self.min_distance_m,
                max_dist=float("inf"),
                venue_types=NIGHTLIFE_VENUE_TYPES,
            ) or self.pick_random_building_point(
                ref_x=pickup_x,
                ref_y=pickup_y,
                min_dist=self.min_distance_m,
                max_dist=float("inf"),
                venue_types={None},
            )
        else:
            if random.random() < 0.70:
                sources = (self.pick_random_building_point, self.pick_random_road_point)
            else:
                sources = (self.pick_random_road_point, self.pick_random_building_point)
            for source in sources:
                dropoff = source(pickup_x, pickup_y, self.min_distance_m, float("inf"))
                if dropoff:
                    break
        if dropoff:
            return dropoff
        return self.pick_random_road_point(ref_x=pickup_x, ref_y=pickup_y, min_dist=self.min_distance_m, max_dist=float("inf"))

    def pick_long_dropoff(self, pickup_x: float, pickup_y: float) -> Optional[TaxiTarget]:
        """Another municipality LONG_FARE_MIN_M..
        MAX_M away, bigger ones likelier; only its spot is known until the
        taxi gets near."""
        towns = [town for town in municipality_points()
                 if town[4] is None and LONG_FARE_MIN_M <= math.hypot(town[1] - pickup_x, town[2] - pickup_y) <= LONG_FARE_MAX_M]
        from .intercity_places import place_id
        if self.intercity_places is not None:
            towns = [town for town in towns if place_id(town[0],town[1],town[2],town[4]) in self.intercity_places]
        if not towns:
            return None
        name, x, y, _, landmark = random.choices(towns, weights=[town[3] for town in towns])[0]
        return TaxiTarget(x=x, y=y, address=name, radius_m=self.pickup_radius_m, municipality=name, venue_type=landmark,
                          intercity_place_id=place_id(name,x,y,landmark))

    def pick_airport_dropoff(self, pickup_x: float, pickup_y: float) -> Optional[TaxiTarget]:
        """Nearest airport, or its nearest town when collecting at the airport."""
        from .intercity_places import place_id
        places = municipality_points()
        airports = [p for p in places if p[4] == "airport"]
        if not airports:
            return None
        airport = min(airports,key=lambda p:math.hypot(p[1]-pickup_x,p[2]-pickup_y))
        target = airport
        if math.hypot(airport[1]-pickup_x,airport[2]-pickup_y) <= LANDMARK_STAND_M:
            towns = [p for p in places if p[4] is None]
            if not towns:
                return None
            target = min(towns,key=lambda p:math.hypot(p[1]-airport[1],p[2]-airport[2]))
        name,x,y,_,kind = target
        identity = place_id(name,x,y,kind)
        if self.intercity_places is not None and identity not in self.intercity_places:
            return None
        return TaxiTarget(x,y,name,radius_m=self.pickup_radius_m,municipality=name,
                          venue_type=kind,intercity_place_id=identity)

    def _resolve_long_dropoff(self, passenger: TaxiPassenger, dt: float) -> None:
        """Near a long fare's town: its address, once the map has a road there."""
        self.long_fare_retry_timer -= dt
        if self.long_fare_retry_timer > 0.0:
            return
        self.long_fare_retry_timer = LONG_FARE_RETRY_S
        town = passenger.dropoff
        if town.venue_type in LANDMARK_WEIGHTS:  # the place itself: its taxi stand, else its road; its name
            final = (self.pick_random_taxi_stop(town.x, town.y, 0.0, LANDMARK_STAND_M)
                     or self.pick_random_road_point(town.x, town.y, 0.0, LANDMARK_SNAP_M))
        else:
            final = (self.pick_random_building_point(town.x, town.y, 0.0, LONG_FARE_RESOLVE_M)
                     or self.pick_random_road_point(town.x, town.y, 0.0, LONG_FARE_RESOLVE_M))
        if final is None or math.hypot(final.x-town.x,final.y-town.y) > (LANDMARK_STAND_M if town.venue_type in LANDMARK_WEIGHTS else LONG_FARE_RESOLVE_M):
            return
        if town.venue_type in LANDMARK_WEIGHTS:
            final.address, final.venue_type = town.address, town.venue_type
        else:
            final.address = f"{final.address}, {town.municipality}"
        passenger.dropoff = final
        for companion in passenger.companions:
            companion.dropoff = final
        self.notification_msg = tr(self.language, "long_fare_address", name=passenger.name, address=final.address)
        self.notification_timer = 6.0
        logger.info("Long fare address picked: passenger=%s dropoff=%s", passenger.name, final.address)

    def generate_offers(
        self, car_x: float, car_y: float, count: int = 3, append: bool = False
    ) -> List[TaxiOffer]:
        """Create realistic ride requests without activating one until accepted."""
        if not self.fares_open:
            return []
        if self.current_passenger:
            self.offers = []
            return []
        self._initial_offer_pending = False
        offers: List[TaxiOffer] = []
        available_slots = MAX_PHONE_OFFERS - len(self.offers) if append else MAX_PHONE_OFFERS
        for _ in range(min(max(1, count), max(0, available_slots))):
            pickup = self.pick_phone_pickup(car_x, car_y)
            if not pickup:
                continue
            dropoff = None
            if self.intercity_fares_enabled:
                roll = random.random()
                if roll < LONG_FARE_CHANCE:
                    dropoff = self.pick_long_dropoff(pickup.x, pickup.y)
                elif roll < LONG_FARE_CHANCE + AIRPORT_FARE_CHANCE:
                    dropoff = self.pick_airport_dropoff(pickup.x, pickup.y)
            dropoff = dropoff or self.pick_phone_dropoff(pickup.x, pickup.y)
            if not dropoff:
                continue
            passenger_name, passenger_gender, resident_id, passenger_weight_kg = self._new_passenger_identity()
            nausea_delay = self.nausea_delay_for_pickup(pickup)
            ped_x, ped_y, ped_heading = self.passenger_waiting_position(pickup)
            passenger = TaxiPassenger(
                name=passenger_name,
                pickup=pickup,
                dropoff=dropoff,
                gender=passenger_gender,
                resident_id=resident_id,
                weight_kg=passenger_weight_kg,
                ped_x=ped_x,
                ped_y=ped_y,
                ped_heading=ped_heading,
                ped_speed=2.2,
                is_drunk=math.isfinite(nausea_delay),
                nausea_delay=nausea_delay,
            )
            if not self._make_party(passenger, generated=True):
                continue
            offers.append(TaxiOffer(
                passenger=passenger,
                pickup_distance_m=math.hypot(car_x - pickup.x, car_y - pickup.y),
                time_remaining_s=random.uniform(PHONE_OFFER_MIN_LIFETIME_S, PHONE_OFFER_MAX_LIFETIME_S),
            ))
        self.offers = (self.offers + offers)[:MAX_PHONE_OFFERS] if append else offers[:MAX_PHONE_OFFERS]
        logger.info(
            "Taxi phone offers generated: count=%d pickup_distances=%s",
            len(offers),
            [round(offer.pickup_distance_m) for offer in offers],
        )
        if not append and not self.offers:
            # A fresh "player just became available" attempt (discard,
            # dropoff, vomit-abandon - see their call sites) found nothing,
            # e.g. no eligible pickup/dropoff in range for the current
            # time of day/location. next_offer_timer isn't decremented
            # while a passenger is aboard, so it can be sitting on a stale
            # value up to PHONE_OFFER_MAX_INTERVAL_S old from before that
            # ride even started - without this, the player could be stuck
            # staring at zero offers for up to a minute after this attempt
            # already failed, instead of the game retrying soon.
            self.next_offer_timer = min(self.next_offer_timer, random.uniform(2.0, 6.0))
        return offers

    def accept_offer(self, index: int, car_x: float, car_y: float) -> bool:
        """Activate one phone offer and remove the offer list."""
        items = self.phone_items()
        if index < 0 or index >= len(items) or self.has_job():
            return False
        kind, item = items[index]
        if kind == "booking":
            accepted = self.rail_bookings.accept(item)
            if accepted:
                self.notification_msg = tr(
                    self.language, "rail_booking_accepted", train=item.train_number,
                    station=item.station, arrival=f"{item.arrival_at:%H:%M}",
                )
                self.notification_timer = 5.0
            return accepted
        if not self._party_valid(item.passenger):
            return False
        self.current_passenger = item.passenger
        self.offers = []
        self.state = TaxiState.WAITING_FOR_PICKUP
        self.elapsed_time = 0.0
        self.notification_msg = tr(
            self.language,
            "new_fare_at",
            name=self.current_passenger.name,
            address=self.current_passenger.pickup.address,
        )
        self.notification_timer = 5.0
        logger.info(
            "Taxi phone offer accepted: passenger=%s pickup=%s dropoff=%s",
            self.current_passenger.name,
            self.current_passenger.pickup.address,
            self.current_passenger.dropoff.address,
        )
        return True

    def reject_offer(self, index: int = 0, car_x: float = 0.0, car_y: float = 0.0) -> bool:
        """Reject one pending phone request without starting its fare."""
        items = self.phone_items()
        if index == 0 and items and items[0][0] == "booking" and items[0][1].status != "PENDING":
            pending = next((entry for entry in items if entry[0] == "booking" and entry[1].status == "PENDING"), None)
            if pending is None:
                return False
            kind, item = pending
            return self.rail_bookings.decline(item)
        if index < 0 or index >= len(items):
            return False
        kind, item = items[index]
        if kind == "booking":
            return self.rail_bookings.decline(item)
        self.offers.remove(item)
        self.next_offer_timer = random.uniform(PHONE_OFFER_MIN_INTERVAL_S, PHONE_OFFER_MAX_INTERVAL_S)
        self.notification_msg = tr(self.language, "no_requests")
        self.notification_timer = 2.0
        logger.info("Taxi phone offer rejected: index=%d remaining=%d", index, len(self.offers))
        return True

    def _board_waiting_pedestrian(
        self,
        pedestrian: Any,
        pickup: TaxiTarget,
        message_key: str,
        walk_to_car: bool = False,
        booking: Any = None,
        pedestrians=(),
    ) -> bool:
        """Turn a nearby waiting pedestrian into a fare, optionally walking to
        the car first. A booked rail customer keeps the booking's destination."""
        dropoff = booking.destination if booking is not None else self.pick_random_building_point(
            pickup.x, pickup.y, self.min_distance_m, float("inf"), venue_types={None}
        )
        if not dropoff:
            dropoff = self.pick_random_road_point(pickup.x, pickup.y, self.min_distance_m, float("inf"))
        if not dropoff:
            return False
        resident = self.residents.get(getattr(pedestrian, "resident_id", None))
        passenger_name, passenger_gender, resident_id, passenger_weight_kg = self._new_passenger_identity(resident)
        if booking is not None and booking.passenger.name:
            passenger_name = booking.passenger.name  # the name on the booking, and its gender (the voice)
            passenger_gender = {"female": "woman", "male": "man"}.get(getattr(booking.passenger, "gender", ""), passenger_gender)
        is_drunk = bool(getattr(pedestrian, "is_drunk", False))
        passenger = TaxiPassenger(
            name=passenger_name,
            pickup=pickup,
            dropoff=dropoff,
            gender=passenger_gender,
            resident_id=resident_id,
            weight_kg=passenger_weight_kg,
            ped_x=pedestrian.x,
            ped_y=pedestrian.y,
            ped_heading=pedestrian.heading,
            boarded=True,
            is_drunk=is_drunk,
            nausea_delay=self.nausea_delay_for_pickup(pickup) if is_drunk else float("inf"),
            rail_booking=booking,
        )
        if not self._make_party(passenger, pedestrians=pedestrians):
            return False
        if booking is not None:
            booking.status = PASSENGER_MET
        self.current_passenger = passenger
        self.offers = []
        if walk_to_car:
            passenger.boarded = False
            passenger.is_walking_to_car = True
            self.state = TaxiState.CLIENT_WALKING_TO_CAR
            for member in passenger.companions:
                member.boarded = False
                member.is_walking_to_car = True
        else:
            self.state = TaxiState.DRIVING_TO_DROPOFF
            self.fare_started_at = self._current_game_datetime()
            self.fare_start_odometer_m = None
            self.fare_distance_m = 0.0
            self.live_fare_cents = calculate_fare_cents(0.0, 0.0, self.fare_started_at)
            self.passenger_happiness = 50.0
        self.elapsed_time = 0.0
        self.trip_distance_m = math.hypot(dropoff.x - pickup.x, dropoff.y - pickup.y)
        if walk_to_car and message_key == "hail_boarded":
            notification_key = "hail_walking"
        else:
            notification_key = "walking_named" if walk_to_car else message_key
        self.notification_msg = tr(
            self.language,
            notification_key,
            name=passenger.name,
            address=dropoff.address,
        )
        self.notification_timer = 5.0
        if passenger.boarded:
            self._warn_if_passenger_is_drunk(passenger)
        logger.info(
            "Passenger boarded: passenger=%s pickup=%s dropoff=%s walking=%s",
            passenger.name,
            pickup.address,
            dropoff.address,
            walk_to_car,
        )
        companion_ids = {p.resident_id for p in passenger.companions}
        if isinstance(pedestrians, list):
            pedestrians[:] = [p for p in pedestrians if getattr(p, "resident_id", None) not in companion_ids]
        return True

    def check_waiting_pickup(self, car: Car, pedestrians: List[Any], dt: float) -> Optional[Any]:
        """Let a taxi pick up a pedestrian at a stand or by a street hail."""
        if self.current_passenger:
            self.stand_wait_timer = 0.0
            return None

        # A street hail can happen as the taxi passes a nearby pedestrian.
        if not self.taxi_stops and abs(car.speed) > self.max_stop_speed_mps:
            car_dir_x = math.cos(car.heading)
            car_dir_y = math.sin(car.heading)
            car_side_x = -car_dir_y
            car_side_y = car_dir_x
            passing_candidates = [
                ped for ped in pedestrians
                if getattr(ped, "wants_taxi", False) and waiting_booking(ped) is None
                if abs((ped.x - car.x) * car_dir_x + (ped.y - car.y) * car_dir_y) <= 6.0
                and abs((ped.x - car.x) * car_side_x + (ped.y - car.y) * car_side_y) <= 4.0
            ]
            if passing_candidates and random.random() < min(1.0, dt * 1.5):
                pedestrian = min(
                    passing_candidates,
                    key=lambda ped: math.hypot(car.x - ped.x, car.y - ped.y),
                )
                pickup = self.make_target(pedestrian.x, pedestrian.y)
                if self._board_waiting_pedestrian(
                    pedestrian,
                    pickup,
                    "hail_boarded",
                    walk_to_car=True,
                    pedestrians=pedestrians,
                ):
                    return pedestrian
            self.stand_wait_timer = 0.0
            return None

        if abs(car.speed) > self.max_stop_speed_mps:
            self.stand_wait_timer = 0.0
            return None
        self.stand_wait_timer += dt
        if self.stand_wait_timer < 2.0:
            return None
        pickup = None
        message_key = "stand_boarded"
        stand_stop = None
        if self.taxi_stops:
            nearby_stops = [stop for stop in self.taxi_stops if math.hypot(car.x - stop.x, car.y - stop.y) <= 22.0]
            if nearby_stops:
                stand_stop = nearby_stops[0]
        candidates = [
            ped for ped in pedestrians
            if getattr(ped, "wants_taxi", True)
            and math.hypot(car.x - ped.x, car.y - ped.y) <= 15.0
            and waiting_booking(ped) is None
        ]
        is_hail = stand_stop is None and not self.taxi_stops and candidates
        if is_hail and random.random() < min(1.0, dt * 0.35):
            pickup = self.make_target(candidates[0].x, candidates[0].y)
            message_key = "hail_boarded"
        elif stand_stop is not None and candidates:
            # Only now: make_target's street/house-number lookup scans the
            # whole loaded city, and used to run every frame while the taxi
            # idled at a stand with nobody there to board.
            pickup = self.make_target(stand_stop.x, stand_stop.y)
        if pickup is None or not candidates:
            return None
        if message_key == "stand_boarded" and random.random() >= min(1.0, dt * 0.35):
            return None
        pedestrian = candidates[0]
        if self._board_waiting_pedestrian(
            pedestrian,
            pickup,
            message_key,
            walk_to_car=message_key in ("stand_boarded", "hail_boarded"),
            pedestrians=pedestrians,
        ):
            self.stand_wait_timer = 0.0
            return pedestrian
        return None

    def calculate_score(self, distance_m: float, elapsed_sec: float) -> int:
        """Calculate points based on distance and speed (distance / time)."""
        base_points = int(distance_m * 0.5)  # 500 points per km base
        elapsed_sec = max(1.0, elapsed_sec)
        speed_mps = distance_m / elapsed_sec
        speed_kmh = speed_mps * 3.6

        fare = base_points + speed_bonus_points(speed_kmh)
        return max(50, fare)

    def get_current_target(self) -> Optional[TaxiTarget]:
        """Return currently active target (pickup or dropoff)."""
        if not self.current_passenger:
            return None
        if self.state in (TaxiState.WAITING_FOR_PICKUP, TaxiState.CLIENT_WALKING_TO_CAR):
            return self.current_passenger.pickup
        elif self.state == TaxiState.DRIVING_TO_DROPOFF:
            return self.current_passenger.dropoff
        return None

    def discard_mission(self, car_x: float, car_y: float, penalty: int = 150, reason: str = "discard_cancelled") -> int:
        """Discard the active pickup or onboard passenger mission with a score penalty."""
        if not self.current_passenger:
            return 0
        p_name = self.current_passenger.name
        if self.current_passenger.rail_booking is not None and self.current_passenger.rail_booking.status == PASSENGER_MET:
            self.current_passenger.rail_booking.status = MISSED
        self.total_score -= penalty
        if self.state in (TaxiState.DRIVING_TO_DROPOFF, TaxiState.CLIENT_WALKING_TO_CAR):
            key = "discard_abandoned"
        else:
            key = "discard_pickup_cancelled"
        self.notification_msg = tr(self.language, key, reason=tr(self.language, reason), name=p_name, penalty=penalty)
        self.notification_timer = 5.0
        logger.info("Taxi mission discarded: passenger=%s reason=%s penalty=%d", p_name, reason, penalty)
        self.released_parties.append(self.current_passenger)
        self.current_passenger = None
        self.live_fare_cents = 0
        self.state = TaxiState.WAITING_FOR_PICKUP
        self.generate_offers(car_x, car_y, count=1)
        return penalty

    def handle_respawn(self, car_x: float, car_y: float) -> None:
        """Handle car respawn: discard fare and apply penalty if a passenger is onboard."""
        if self.current_passenger and self.state in (TaxiState.DRIVING_TO_DROPOFF, TaxiState.CLIENT_WALKING_TO_CAR):
            self.discard_mission(car_x, car_y, penalty=200, reason="discard_respawned")

    def _update_passenger_nausea(self, car: Car, dt: float) -> None:
        passenger = self.current_passenger
        if (
            passenger is None
            or not passenger.boarded
            or self.state != TaxiState.DRIVING_TO_DROPOFF
        ):
            return
        if passenger.nausea_resolved or passenger.nausea_vomited:
            return

        is_stopped = abs(car.speed) <= self.max_stop_speed_mps
        if passenger.nausea_warning_timer > 0.0:
            if is_stopped:
                passenger.nausea_warning_timer = 0.0
                passenger.nausea_resolved = True
                puddle_x = car.x + math.sin(car.heading) * 2.4
                puddle_y = car.y - math.cos(car.heading) * 2.4
                self.vomit_puddles.append((puddle_x, puddle_y))
                if len(self.vomit_puddles) > 50:
                    del self.vomit_puddles[:-50]
                self.notification_msg = tr(self.language, "passenger_nausea_relieved")
                self.notification_timer = 4.0
                logger.info("Passenger nausea relieved after taxi stopped: passenger=%s", passenger.name)
                return
            passenger.nausea_warning_timer -= dt
            if passenger.nausea_warning_timer <= 0.0:
                passenger.nausea_vomited = True
                self.total_score -= 500
                self.adjust_passenger_happiness(-30.0)
                self.notification_msg = tr(self.language, "passenger_vomited", penalty=500)
                self.notification_timer = 5.0
                logger.info("Passenger vomited in taxi: passenger=%s penalty=%d", passenger.name, 500)
            return

        roughness = (
            max(0.0, abs(car.lateral_g) - 0.35) * 2.0
            + max(0.0, abs(car.forward_g) - 0.35) * 1.5
            + max(0.0, abs(car.speed) - 120.0 / 3.6) / (80.0 / 3.6) * 0.4
        )
        passenger.motion_sickness = max(
            0.0,
            passenger.motion_sickness + (roughness - 0.2) * dt,
        )
        if passenger.motion_sickness >= MOTION_SICKNESS_THRESHOLD:
            passenger.nausea_warning_timer = 4.0
            self.notification_msg = tr(self.language, "passenger_nausea_warning")
            self.notification_timer = 4.0
            logger.info("Passenger reported motion sickness: passenger=%s", passenger.name)
            return

        if not passenger.is_drunk:
            return
        passenger.nausea_delay -= dt
        if passenger.nausea_delay <= 0.0:
            passenger.nausea_warning_timer = 4.0
            self.notification_msg = tr(self.language, "passenger_nausea_warning")
            self.notification_timer = 4.0
            logger.info("Passenger reported nausea: passenger=%s", passenger.name)

    def take_vomited_passenger(self, car: Car) -> Optional[TaxiPassenger]:
        """Release a passenger who vomited once the taxi has stopped."""
        passenger = self.current_passenger
        if passenger is None or not passenger.nausea_vomited or abs(car.speed) > self.max_stop_speed_mps:
            return None
        passenger.ped_x = car.x + math.sin(car.heading) * 1.8
        passenger.ped_y = car.y - math.cos(car.heading) * 1.8
        passenger.ped_heading = car.heading
        self.vomit_puddles.append((passenger.ped_x, passenger.ped_y))
        if len(self.vomit_puddles) > 50:
            del self.vomit_puddles[:-50]
        passenger.boarded = False
        passenger.is_walking_to_car = False
        self.current_passenger = None
        self.state = TaxiState.WAITING_FOR_PICKUP
        self.generate_offers(car.x, car.y, count=1)
        self.notification_msg = tr(self.language, "passenger_vomited_outside")
        self.notification_timer = 6.0  # the fare is over: long enough to read why the route is gone
        logger.info("Passenger left taxi after vomiting: passenger=%s", passenger.name)
        return passenger

    def update(self, car: Car, dt: float, game_time_seconds: Optional[float] = None) -> None:
        """Update mission timers, pickup/dropoff collision, and fare progression."""
        if game_time_seconds is not None:
            self.game_time_seconds = game_time_seconds
        if self.current_passenger:
            self.offers.clear()
        self.speed_camera_flash_timer = max(0.0, self.speed_camera_flash_timer - dt)
        if self.speed_camera_flash_timer <= 0.0:
            self.speed_camera_flash_index = None
        self.speed_camera_notice_timer = max(0.0, self.speed_camera_notice_timer - dt)
        if self.speed_camera_notice_timer <= 0.0:
            self.speed_camera_notice_msg = ""
        self.tree_wait_timer = max(0.0, self.tree_wait_timer - dt)
        self.taxi_smoke_timer = max(0.0, self.taxi_smoke_timer - dt)
        for key, effect in list(self.tree_effects.items()):
            effect["shake"] = max(0.0, effect["shake"] - dt)
            effect["leaves"] = max(0.0, effect["leaves"] - dt)
            if effect["shake"] <= 0.0 and effect["leaves"] <= 0.0 and key not in self.fallen_trees:
                del self.tree_effects[key]
        if self.notification_timer > 0.0:
            self.notification_timer -= dt

        if not self.current_passenger:
            for offer in self.offers:
                offer.time_remaining_s -= dt
            self.offers = [offer for offer in self.offers if offer.time_remaining_s > 0.0]

        if not self.current_passenger and len(self.offers) < MAX_PHONE_OFFERS:
            self.next_offer_timer -= dt
            if self.next_offer_timer <= 0.0:
                self.generate_offers(car.x, car.y, count=1, append=True)
                self.next_offer_timer = random.uniform(PHONE_OFFER_MIN_INTERVAL_S, PHONE_OFFER_MAX_INTERVAL_S)
                if self.offers:
                    self.notification_msg = tr(self.language, "new_request")
                    self.notification_timer = 5.0

        if not self.current_passenger:
            return

        if not self._party_valid(self.current_passenger):
            self.discard_mission(car.x, car.y, penalty=0, reason="discard_invalid_group")
            return

        self._update_passenger_nausea(car, dt)
        if self.current_passenger and self.current_passenger.nausea_vomited:
            return

        target = self.get_current_target()
        if not target:
            return

        dist_to_target = math.hypot(car.x - target.x, car.y - target.y)
        is_stopped = abs(car.speed) <= self.max_stop_speed_mps

        if self.state == TaxiState.WAITING_FOR_PICKUP:
            if dist_to_target <= target.radius_m:
                if is_stopped:
                    # Car arrived at pickup area and stopped: client begins walking to taxi
                    self.state = TaxiState.CLIENT_WALKING_TO_CAR
                    self.current_passenger.is_walking_to_car = True
                    for member in self.current_passenger.companions:
                        member.is_walking_to_car = True
                    self.notification_msg = tr(self.language, "walking_named", name=self.current_passenger.name)
                    self.notification_timer = 3.0
                    logger.info("Passenger reached pickup: passenger=%s walking to taxi", self.current_passenger.name)
                else:
                    self.notification_msg = tr(self.language, "slow_pickup_notice")
                    self.notification_timer = 1.0

        elif self.state == TaxiState.CLIENT_WALKING_TO_CAR:
            # Passenger walks towards the passenger side door of the taxi
            p = self.current_passenger
            door_x, door_y = self._door_position(car)
            # A greeted rail customer is still their own pedestrian, walked
            # by the pedestrian system; the fare just follows it.
            walker = p.rail_booking.passenger.pedestrian if p.rail_booking is not None else None
            if walker is not None:
                p.ped_x, p.ped_y, p.ped_heading = walker.x, walker.y, walker.heading

            dx = door_x - p.ped_x
            dy = door_y - p.ped_y
            dist_to_door = math.hypot(dx, dy)
            companions_ready = True
            for member in p.companions:
                mx, my = door_x - member.ped_x, door_y - member.ped_y
                distance = math.hypot(mx, my)
                if distance > 0.8:
                    member.ped_heading = math.atan2(my, mx)
                    step = min(distance, member.ped_speed * dt)
                    member.ped_x += math.cos(member.ped_heading) * step
                    member.ped_y += math.sin(member.ped_heading) * step
                    companions_ready = False

            # If player drives away too fast while passenger is boarding, passenger cancels/abandons
            if dist_to_target > target.radius_m * 1.8:
                self.discard_mission(car.x, car.y, penalty=100, reason="discard_drove_away")
                return

            if dist_to_door <= 0.8 or (walker is not None and not walker.is_walking_to_taxi_stop):
                if not is_stopped or not companions_ready:
                    return
                if p.rail_booking is not None and self.driver_on_foot:
                    return  # a booked customer waits at the door for the driver
                # Client reached taxi door and boarded!
                p.boarded = True
                for member in p.companions:
                    member.boarded = True
                    member.is_walking_to_car = False
                if p.rail_booking is not None:
                    p.rail_booking.status = IN_TAXI
                p.is_walking_to_car = False
                self.state = TaxiState.DRIVING_TO_DROPOFF
                self.elapsed_time = 0.0
                self.fare_started_at = self._current_game_datetime()
                self.fare_start_odometer_m = car.odometer_m
                self.fare_distance_m = 0.0
                self.live_fare_cents = calculate_fare_cents(0.0, 0.0, self.fare_started_at)
                self.passenger_happiness = 50.0
                self.trip_distance_m = math.hypot(p.dropoff.x - p.pickup.x, p.dropoff.y - p.pickup.y)
                self.notification_msg = tr(
                    self.language, "boarded_destination", name=p.name, address=p.dropoff.address
                )
                self.notification_timer = 6.0
                self._warn_if_passenger_is_drunk(p)
                logger.info(
                    "Passenger boarded after walking: passenger=%s dropoff=%s",
                    p.name,
                    p.dropoff.address,
                )
            elif walker is None:
                p.ped_heading = math.atan2(dy, dx)
                step = p.ped_speed * dt
                if step < dist_to_door:
                    p.ped_x += math.cos(p.ped_heading) * step
                    p.ped_y += math.sin(p.ped_heading) * step
                else:
                    p.ped_x = door_x
                    p.ped_y = door_y

        elif self.state == TaxiState.DRIVING_TO_DROPOFF:
            self.elapsed_time += dt
            if self.fare_start_odometer_m is None:
                self.fare_start_odometer_m = car.odometer_m
            self.fare_distance_m = max(0.0, car.odometer_m - self.fare_start_odometer_m)
            self.live_fare_cents = calculate_fare_cents(
                self.fare_distance_m,
                self.elapsed_time,
                self.fare_started_at or self._current_game_datetime(),
            )
            if target.municipality is not None:  # a long fare: no stop at the bare town centre
                if dist_to_target <= LONG_FARE_RESOLVE_M:
                    self._resolve_long_dropoff(self.current_passenger, dt)
            elif dist_to_target <= target.radius_m:
                if is_stopped:
                    # Completed fare!
                    p = self.current_passenger
                    earned = self.calculate_score(self.trip_distance_m, self.elapsed_time)
                    self.total_score += earned
                    self.completed_fares += 1
                    self.last_fare_points = earned
                    fare_cents = self.live_fare_cents
                    expected_duration_s = max(60.0, self.trip_distance_m / (40.0 / 3.6))
                    if self.elapsed_time <= expected_duration_s:
                        time_saved_ratio = 1.0 - self.elapsed_time / expected_duration_s
                        self.adjust_passenger_happiness(10.0 + 15.0 * time_saved_ratio)
                    tip_cents = tip_cents_from_happiness(self.passenger_happiness)
                    self.balance_cents += fare_cents + tip_cents
                    self.last_fare_cents = fare_cents
                    self.last_tip_cents = tip_cents
                    avg_kmh = (self.trip_distance_m / max(1.0, self.elapsed_time)) * 3.6
                    rating = star_rating_from_happiness(self.passenger_happiness)
                    self.notification_msg = tr(
                        self.language, "fare_complete_points", earned=earned, avg=avg_kmh,
                        seconds=self.elapsed_time, amount=format_euros(fare_cents, self.language),
                        tip=format_euros(tip_cents, self.language), rating=rating,
                        stars="★" * rating + "☆" * (5 - rating),
                    )
                    self.notification_timer = 6.0
                    logger.info(
                        "Taxi fare completed: passenger=%s earned=%d fare_cents=%d tip_cents=%d happiness=%.0f balance_cents=%d total_score=%d elapsed=%.1fs",
                        p.name,
                        earned,
                        fare_cents,
                        tip_cents,
                        self.passenger_happiness,
                        self.balance_cents,
                        self.total_score,
                        self.elapsed_time,
                    )
                    # New requests are selected through the phone.
                    self.current_passenger = None
                    self.generate_offers(car.x, car.y, count=1)
                else:
                    self.notification_msg = tr(self.language, "slow_dropoff_notice")
                    self.notification_timer = 1.0
