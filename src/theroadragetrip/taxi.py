import logging
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .geo import clamp, dist_point_to_segment
from .osm import Building, Place, Way
from .physics import Car, SpatialWayGrid, compute_largest_connected_road_component, is_car_road, is_violating_oneway

logger = logging.getLogger(__name__)

# Finnish passenger name generator for immersion
FIRST_NAMES = [
    "Matti", "Maija", "Antti", "Liisa", "Juho", "Anna", "Mikko", "Sari",
    "Pekka", "Tuula", "Jari", "Tiina", "Heikki", "Katri", "Kari", "Elina",
    "Ville", "Johanna", "Aleksi", "Laura", "Janne", "Emilia", "Lauri", "Sofia",
    "Markus", "Sanna", "Eero", "Hanna", "Petri", "Maria", "Timo", "Veera"
]


@dataclass
class TaxiTarget:
    """A target destination or pickup point with generated realistic address."""
    x: float
    y: float
    address: str
    way_name: Optional[str] = None
    district_name: Optional[str] = None
    radius_m: float = 20.0  # Pickup/dropoff stop radius


@dataclass
class TaxiPassenger:
    name: str
    pickup: TaxiTarget
    dropoff: TaxiTarget
    # Client pedestrian representation walking into the taxi
    ped_x: float = 0.0
    ped_y: float = 0.0
    ped_heading: float = 0.0
    ped_speed: float = 2.0  # Walking speed to taxi in m/s
    ped_color: Tuple[int, int, int] = (240, 220, 60)  # Bright gold/yellow
    is_walking_to_car: bool = False
    boarded: bool = False


class TaxiState:
    WAITING_FOR_PICKUP = "PICKUP"
    CLIENT_WALKING_TO_CAR = "WALKING"
    DRIVING_TO_DROPOFF = "DROPOFF"
    COMPLETED = "COMPLETED"


class TaxiManager:
    """Manages taxi missions, addresses, pickups, dropoffs, fares, and speed bonuses."""

    def __init__(
        self,
        ways: List[Way],
        places: Optional[List[Place]] = None,
        buildings: Optional[List[Building]] = None,
        min_distance_m: float = 300.0,
        max_distance_m: float = 2500.0,
        pickup_radius_m: float = 25.0,
        max_stop_speed_mps: float = 3.0,  # Must slow down below ~10 km/h to pickup/dropoff
    ):
        # Filter to the largest connected road network to avoid isolated trapped roads
        connected_ways = compute_largest_connected_road_component(ways)
        # Only consider drivable car roads with valid real names
        self.ways = [w for w in connected_ways if is_car_road(w) and len(w.points_m) >= 2 and getattr(w, "name", None)]
        # Fallback if no named roads exist in bbox
        if not self.ways:
            self.ways = [w for w in connected_ways if is_car_road(w) and len(w.points_m) >= 2]
        if not self.ways:
            self.ways = [w for w in ways if is_car_road(w) and len(w.points_m) >= 2]
        self.places = places or []
        self.buildings = buildings or []
        self.min_distance_m = min_distance_m
        self.max_distance_m = max_distance_m
        self.pickup_radius_m = pickup_radius_m
        self.max_stop_speed_mps = max_stop_speed_mps

        self.current_passenger: Optional[TaxiPassenger] = None
        self.state: str = TaxiState.WAITING_FOR_PICKUP
        self.total_score: int = 0
        self.completed_fares: int = 0
        self.trip_start_time: float = 0.0
        self.elapsed_time: float = 0.0
        self.trip_distance_m: float = 0.0
        self.last_fare_points: int = 0
        self.notification_msg: str = "Welcome! Drive to the pickup location to collect passenger."
        self.notification_timer: float = 5.0
        self._passed_red_signals: Dict[int, float] = {}  # signal id -> timestamp cooldown
        self._approaching_red_signals: Dict[int, float] = {}  # signal id -> last signed distance along travel
        self._crashed_npc_cooldowns: Dict[int, float] = {}  # npc id -> timestamp cooldown
        self.wrong_way_duration: float = 0.0  # seconds continuously driving wrong way
        self.wrong_way_penalty_cooldown: float = 0.0  # timer between recurring penalties (5.0s)

    def check_car_collision(
        self,
        player_car: Car,
        npcs: List[Any],
        sim_time: float,
        penalty: int = 150,
    ) -> bool:
        """Check if player car collided with any NPC vehicle and apply crash physics + penalty."""
        from .geo import boxes_intersect

        # Clean expired crash cooldowns (> 3.0 seconds ago)
        expired = [nid for nid, t in self._crashed_npc_cooldowns.items() if sim_time - t > 3.0]
        for nid in expired:
            del self._crashed_npc_cooldowns[nid]

        p_len = getattr(player_car, "length_m", 4.0)
        p_wid = getattr(player_car, "width_m", 1.8)
        crashed = False

        for npc in npcs:
            if getattr(npc, "layer", 0) != getattr(player_car, "layer", 0):
                continue

            npc_id = id(npc)
            n_len = getattr(npc, "length_m", 4.0)
            n_wid = getattr(npc, "width_m", 1.8)

            if boxes_intersect(
                player_car.x, player_car.y, player_car.heading, p_len, p_wid,
                npc.x, npc.y, npc.heading, n_len, n_wid,
            ):
                # Apply bounce-back / collision impulse physics
                dx = player_car.x - npc.x
                dy = player_car.y - npc.y
                dist = math.hypot(dx, dy)
                if dist > 1e-3:
                    nx = dx / dist
                    ny = dy / dist
                else:
                    nx = math.cos(player_car.heading)
                    ny = math.sin(player_car.heading)

                # Push vehicles apart
                separation = max(0.5, (p_wid + n_wid) * 0.5)
                player_car.x += nx * 0.4
                player_car.y += ny * 0.4
                npc.x -= nx * 0.4
                npc.y -= ny * 0.4

                # Exchange and damp speeds
                impact_speed = max(abs(player_car.speed), abs(npc.speed), 3.0)
                player_car.speed = -player_car.speed * 0.4
                npc.speed = 0.0
                npc.crashed_timer = max(getattr(npc, "crashed_timer", 0.0), 5.0)  # stop & smoke for 5 seconds

                crashed = True
                if npc_id not in self._crashed_npc_cooldowns:
                    self._crashed_npc_cooldowns[npc_id] = sim_time
                    self.total_score -= penalty
                    self.notification_msg = f"Crash! -{penalty} pts"
                    self.notification_timer = 3.5
                    logger.info("Player crashed into NPC vehicle: -%d pts penalty (impact speed: %.1f m/s)", penalty, impact_speed)

        return crashed

    def check_red_light_violation(
        self,
        car: Car,
        traffic_lights: List[Any],
        sim_time: float,
        penalty: int = 100,
    ) -> None:
        """Check if player car passes across a red/yellow traffic light line and apply penalty upon crossing."""
        if abs(car.speed) < 2.0:
            return  # Standing or creeping slowly before line is not running a red light

        # Clean expired signal cooldowns (> 10 seconds ago)
        expired = [sid for sid, t in self._passed_red_signals.items() if sim_time - t > 10.0]
        for sid in expired:
            del self._passed_red_signals[sid]

        # Unit vector along car's motion
        move_heading = car.heading if car.speed >= 0 else (car.heading + math.pi)
        dir_x = math.cos(move_heading)
        dir_y = math.sin(move_heading)
        perp_x = -math.sin(move_heading)
        perp_y = math.cos(move_heading)

        for tl in traffic_lights:
            tl_id = getattr(tl, "id", id(tl))
            if tl_id in self._passed_red_signals:
                continue

            # Vector from car to traffic light
            dx = tl.x - car.x
            dy = tl.y - car.y
            dist = math.hypot(dx, dy)

            # Only track lights within detection zone (e.g. 15 meters)
            if dist > 15.0:
                self._approaching_red_signals.pop(tl_id, None)
                continue

            # Check alignment with signal direction if available
            if getattr(tl, "direction_angle", None) is not None:
                tl_ang = tl.direction_angle
                car_ang = car.heading % math.pi
                ang_err = abs(tl_ang - car_ang)
                ang_err = min(ang_err, math.pi - ang_err)
                if ang_err > math.radians(45):
                    self._approaching_red_signals.pop(tl_id, None)
                    continue  # Signal is for cross traffic

            # Longitudinal distance along direction of travel:
            # Positive = traffic light is ahead of car
            # Negative = traffic light is behind car (car has crossed the stop line)
            long_dist = dx * dir_x + dy * dir_y
            lat_dist = abs(dx * perp_x + dy * perp_y)

            # Must be reasonably aligned laterally to the traffic light post / stop line (within 8m)
            if lat_dist > 8.0:
                self._approaching_red_signals.pop(tl_id, None)
                continue

            prev_long_dist = self._approaching_red_signals.get(tl_id)
            self._approaching_red_signals[tl_id] = long_dist

            state = tl.get_state(sim_time)
            is_red = state in ("red", "red+yellow")

            # Crossed line condition:
            # 1) Previously ahead (prev >= 0.0) and now behind (long_dist < 0.0), or
            # 2) Directly at/past line (-4.0 <= long_dist <= 0.0) while driving through at speed
            crossed_line = False
            if prev_long_dist is not None and prev_long_dist >= -1.0 and long_dist < 0.0:
                crossed_line = True
            elif -4.0 <= long_dist <= 0.0 and dist <= 6.0:
                crossed_line = True

            if crossed_line and is_red:
                self._passed_red_signals[tl_id] = sim_time
                self._approaching_red_signals.pop(tl_id, None)
                self.total_score -= penalty
                self.notification_msg = f"Red Light Violation! -{penalty} pts"
                self.notification_timer = 4.0
                logger.info("Player passed red traffic light %s: -%d pts penalty", tl_id, penalty)
                break

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
                self.notification_msg = f"Wrong Way Penalty! -{penalty} pts"
                self.notification_timer = 3.5
                logger.info("Player driving wrong way on one-way road: -%d pts penalty", penalty)
            return True
        else:
            self.wrong_way_duration = 0.0
            self.wrong_way_penalty_cooldown = 0.0
            return False

    def sync_map_data(
        self,
        ways: List[Way],
        places: Optional[List[Place]] = None,
        buildings: Optional[List[Building]] = None,
    ) -> None:
        """Update road and place references when map expands dynamically."""
        connected_ways = compute_largest_connected_road_component(ways)
        named = [w for w in connected_ways if is_car_road(w) and len(w.points_m) >= 2 and getattr(w, "name", None)]
        self.ways = named if named else [w for w in connected_ways if is_car_road(w) and len(w.points_m) >= 2]
        if not self.ways:
            self.ways = [w for w in ways if is_car_road(w) and len(w.points_m) >= 2]
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

    def pick_random_road_point(
        self,
        ref_x: Optional[float] = None,
        ref_y: Optional[float] = None,
        min_dist: float = 0.0,
        max_dist: float = float("inf"),
    ) -> Optional[TaxiTarget]:
        """Pick a valid road coordinate with a verified real street name within distance constraints."""
        if not self.ways:
            return None

        candidate_ways = self.ways[:]
        random.shuffle(candidate_ways)

        for w in candidate_ways:
            if len(w.points_m) < 2:
                continue

            way_name = getattr(w, "name", None)
            if not way_name:
                continue

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

            addr = self.generate_address_for_point(px, py, way_name)
            if not addr:
                continue

            district = self.get_nearest_district(px, py)
            return TaxiTarget(
                x=px,
                y=py,
                address=addr,
                way_name=way_name,
                district_name=district,
                radius_m=self.pickup_radius_m,
            )

        # If strict distance search didn't match, pick any named way
        for w in candidate_ways:
            way_name = getattr(w, "name", None)
            if not way_name or len(w.points_m) < 2:
                continue
            idx = random.randint(0, len(w.points_m) - 2)
            p1 = w.points_m[idx]
            p2 = w.points_m[idx + 1]
            t = random.uniform(0.1, 0.9)
            px = p1[0] + t * (p2[0] - p1[0])
            py = p1[1] + t * (p2[1] - p1[1])
            addr = self.generate_address_for_point(px, py, way_name)
            if addr:
                return TaxiTarget(
                    x=px,
                    y=py,
                    address=addr,
                    way_name=way_name,
                    district_name=self.get_nearest_district(px, py),
                    radius_m=self.pickup_radius_m,
                )
        return None

    def spawn_mission(self, car_x: float, car_y: float) -> None:
        """Spawn a new passenger pickup and dropoff destination."""
        pickup_target = self.pick_random_road_point(
            ref_x=car_x,
            ref_y=car_y,
            min_dist=150.0,
            max_dist=1200.0,
        )
        if not pickup_target:
            return

        dropoff_target = self.pick_random_road_point(
            ref_x=pickup_target.x,
            ref_y=pickup_target.y,
            min_dist=self.min_distance_m,
            max_dist=self.max_distance_m,
        )
        if not dropoff_target:
            dropoff_target = pickup_target

        passenger_name = random.choice(FIRST_NAMES)
        self.current_passenger = TaxiPassenger(
            name=passenger_name,
            pickup=pickup_target,
            dropoff=dropoff_target,
            ped_x=pickup_target.x,
            ped_y=pickup_target.y,
            ped_heading=0.0,
            ped_speed=2.2,
            is_walking_to_car=False,
            boarded=False,
        )
        self.state = TaxiState.WAITING_FOR_PICKUP
        self.elapsed_time = 0.0
        self.notification_msg = f"New Fare! Pickup {passenger_name} at {pickup_target.address}"
        self.notification_timer = 5.0

    def calculate_score(self, distance_m: float, elapsed_sec: float) -> int:
        """Calculate points based on distance and speed (distance / time)."""
        base_points = int(distance_m * 0.5)  # 500 points per km base
        elapsed_sec = max(1.0, elapsed_sec)
        speed_mps = distance_m / elapsed_sec
        speed_kmh = speed_mps * 3.6

        # Speed multiplier bonus (e.g. 50 km/h avg -> 1.5x, 80 km/h -> 2.0x)
        speed_bonus_factor = max(1.0, 1.0 + (speed_kmh / 80.0))
        time_bonus = int(speed_kmh * 15.0)

        fare = int(base_points * speed_bonus_factor + time_bonus)
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

    def discard_mission(self, car_x: float, car_y: float, penalty: int = 150, reason: str = "Fare cancelled") -> int:
        """Discard the active pickup or onboard passenger mission with a score penalty."""
        if not self.current_passenger:
            return 0
        p_name = self.current_passenger.name
        self.total_score -= penalty
        if self.state in (TaxiState.DRIVING_TO_DROPOFF, TaxiState.CLIENT_WALKING_TO_CAR):
            msg = f"{reason}! Client {p_name} abandoned (-{penalty} pts)"
        else:
            msg = f"{reason}! Pickup for {p_name} cancelled (-{penalty} pts)"
        self.notification_msg = msg
        self.notification_timer = 5.0
        self.spawn_mission(car_x, car_y)
        return penalty

    def handle_respawn(self, car_x: float, car_y: float) -> None:
        """Handle car respawn: discard fare and apply penalty if a passenger is onboard."""
        if self.current_passenger and self.state in (TaxiState.DRIVING_TO_DROPOFF, TaxiState.CLIENT_WALKING_TO_CAR):
            self.discard_mission(car_x, car_y, penalty=200, reason="Respawned while transporting passenger")

    def update(self, car: Car, dt: float) -> None:
        """Update mission timers, pickup/dropoff collision, and fare progression."""
        if self.notification_timer > 0.0:
            self.notification_timer -= dt

        if not self.current_passenger:
            self.spawn_mission(car.x, car.y)
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
                    self.notification_msg = f"{self.current_passenger.name} is walking to the taxi..."
                    self.notification_timer = 3.0
                else:
                    self.notification_msg = "Slow down to pick up passenger!"
                    self.notification_timer = 1.0

        elif self.state == TaxiState.CLIENT_WALKING_TO_CAR:
            # Passenger walks towards the passenger side door of the taxi
            p = self.current_passenger
            # Passenger door position (side offset relative to car heading)
            door_offset_side = 1.2
            door_offset_long = -0.5
            door_x = car.x + math.cos(car.heading) * door_offset_long + math.sin(car.heading) * door_offset_side
            door_y = car.y - math.sin(car.heading) * door_offset_long - math.cos(car.heading) * door_offset_side

            dx = door_x - p.ped_x
            dy = door_y - p.ped_y
            dist_to_door = math.hypot(dx, dy)

            # If player drives away too fast while passenger is boarding, passenger cancels/abandons
            if dist_to_target > target.radius_m * 1.8:
                self.discard_mission(car.x, car.y, penalty=100, reason="Drove away during pickup")
                return

            if dist_to_door <= 0.8:
                # Client reached taxi door and boarded!
                p.boarded = True
                p.is_walking_to_car = False
                self.state = TaxiState.DRIVING_TO_DROPOFF
                self.elapsed_time = 0.0
                self.trip_distance_m = math.hypot(p.dropoff.x - p.pickup.x, p.dropoff.y - p.pickup.y)
                self.notification_msg = (
                    f"{p.name} boarded! Destination: {p.dropoff.address}"
                )
                self.notification_timer = 6.0
            else:
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
            if dist_to_target <= target.radius_m:
                if is_stopped:
                    # Completed fare!
                    p = self.current_passenger
                    earned = self.calculate_score(self.trip_distance_m, self.elapsed_time)
                    self.total_score += earned
                    self.completed_fares += 1
                    self.last_fare_points = earned
                    avg_kmh = (self.trip_distance_m / max(1.0, self.elapsed_time)) * 3.6
                    self.notification_msg = (
                        f"Fare Complete! +{earned} pts ({avg_kmh:.0f} km/h avg in {self.elapsed_time:.1f}s)"
                    )
                    self.notification_timer = 6.0
                    # Immediately spawn next customer
                    self.spawn_mission(car.x, car.y)
                else:
                    self.notification_msg = "Slow down at destination to drop off!"
                    self.notification_timer = 1.0
