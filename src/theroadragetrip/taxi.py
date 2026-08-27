import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .geo import clamp, dist_point_to_segment
from .osm import Building, Place, Way
from .physics import Car, is_car_road

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


class TaxiState:
    WAITING_FOR_PICKUP = "PICKUP"
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
        # Only consider drivable car roads with valid real names
        self.ways = [w for w in ways if is_car_road(w) and len(w.points_m) >= 2 and getattr(w, "name", None)]
        # Fallback if no named roads exist in bbox
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

    def sync_map_data(
        self,
        ways: List[Way],
        places: Optional[List[Place]] = None,
        buildings: Optional[List[Building]] = None,
    ) -> None:
        """Update road and place references when map expands dynamically."""
        named = [w for w in ways if is_car_road(w) and len(w.points_m) >= 2 and getattr(w, "name", None)]
        self.ways = named if named else [w for w in ways if is_car_road(w) and len(w.points_m) >= 2]
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
        if self.state == TaxiState.WAITING_FOR_PICKUP:
            return self.current_passenger.pickup
        elif self.state == TaxiState.DRIVING_TO_DROPOFF:
            return self.current_passenger.dropoff
        return None

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
                    # Picked up passenger!
                    self.state = TaxiState.DRIVING_TO_DROPOFF
                    self.elapsed_time = 0.0
                    p = self.current_passenger
                    self.trip_distance_m = math.hypot(p.dropoff.x - p.pickup.x, p.dropoff.y - p.pickup.y)
                    self.notification_msg = (
                        f"{p.name} boarded! Destination: {p.dropoff.address}"
                    )
                    self.notification_timer = 6.0
                else:
                    self.notification_msg = "Slow down to pick up passenger!"
                    self.notification_timer = 1.0

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
