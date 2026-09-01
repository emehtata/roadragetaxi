import logging
import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .osm import TrafficLight, Way
from .geo import closest_point_and_dist_to_segment, dist_point_to_segment, point_in_polygon
from .physics import Car, is_car_road, is_pedestrian_way

logger = logging.getLogger(__name__)

CURSE_SYMBOLS = ["@#*!%", "#$@&!", "!%#&*", "%$!#@", "@!*#$"]

PEDESTRIAN_COLORS = [
    (230, 80, 80),    # Red
    (70, 130, 240),   # Blue
    (240, 200, 70),   # Yellow
    (60, 180, 100),   # Green
    (180, 80, 190),   # Purple
    (240, 140, 60),   # Orange
    (220, 220, 230),  # Light gray
    (50, 50, 60),     # Dark
]

VENUE_TYPES = {
    "bar",
    "biergarten",
    "cafe",
    "fast_food",
    "food_court",
    "ice_cream",
    "nightclub",
    "pub",
    "restaurant",
}

CYCLIST_COLORS = [
    (50, 120, 220),
    (220, 60, 60),
    (50, 170, 90),
    (220, 150, 40),
    (150, 70, 190),
    (230, 230, 230),
]


@dataclass
class Pedestrian:
    """Pedestrian walking on footpaths/sidewalks and crossing roads."""
    x: float
    y: float
    heading: float
    speed: float  # Current walking speed in m/s
    base_speed: float  # Base natural walking speed
    way: Way
    segment_idx: int
    direction: int  # 1 for forward along points_m, -1 for reverse
    color: Tuple[int, int, int]
    radius_m: float = 0.45
    # Natural walking dynamics
    lateral_offset_m: float = 0.0  # Lateral position across sidewalk width (-half_width to +half_width)
    target_lateral_offset_m: float = 0.0  # Natural drift target
    lateral_speed_mps: float = 0.15  # Speed of subtle lateral drift
    sway_phase: float = 0.0  # Phase for slight gait sway
    sway_frequency: float = 4.0  # Gait frequency
    sway_amplitude: float = 0.04  # Subtle visual step sway (m)
    pace_timer: float = 0.0  # Timer to slightly vary natural cadence/speed
    speed_variation_factor: float = 1.0  # Multiplier on base_speed (0.9 - 1.1)
    # Cursing / reaction state
    curse_timer: float = 0.0
    curse_text: str = "@#*!%"
    # Dodging / evasive state
    dodge_vx: float = 0.0
    dodge_vy: float = 0.0
    dodge_timer: float = 0.0
    wants_taxi: bool = False
    taxi_stop_target: Optional[Tuple[float, float]] = None
    is_walking_to_taxi_stop: bool = False
    is_drunk: bool = False
    drunk_phase: float = 0.0
    drunk_vomit_cooldown: float = 0.0


@dataclass
class PlayerPedestrian:
    """Player character while walking outside the taxi."""
    x: float
    y: float
    heading: float = 0.0
    speed: float = 0.0
    color: Tuple[int, int, int] = (255, 215, 60)
    radius_m: float = 0.55
    way: Optional[Way] = None


class PedestrianManager:
    """Manages spawning, walking, road crossing at traffic lights, and vehicle evasion for pedestrians."""

    def __init__(
        self,
        ways: List[Way],
        target_count: int = 15,
        spawn_radius_m: float = 120.0,
        despawn_radius_m: float = 160.0,
        traffic_lights: Optional[List[TrafficLight]] = None,
        venue_buildings: Optional[List] = None,
    ):
        self.target_count = target_count
        self.spawn_radius_m = spawn_radius_m
        self.despawn_radius_m = despawn_radius_m
        self.pedestrians: List[Pedestrian] = []
        self.traffic_lights: List[TrafficLight] = traffic_lights or []
        self.sim_time: float = 0.0
        self._population_update_elapsed: float = 0.5
        self._visible_taxi_stops: Set[Tuple[float, float, Optional[int]]] = set()
        self._taxi_stop_visibility_initialized = False
        self.venue_locations: List[Tuple[float, float]] = []
        self.buildings: List = []
        self.vomit_puddles: List[Tuple[float, float]] = []

        self.ped_ways: List[Way] = []
        self._way_grid: Dict[Tuple[int, int], List[Way]] = {}
        self._way_grid_cell_size: float = 100.0
        self._junction_grid: Dict[Tuple[int, int], List[Tuple[Way, int, Tuple[float, float], int, int]]] = {}
        self._junction_grid_cell_size: float = 20.0
        self._traffic_light_grid: Dict[Tuple[int, int], List[TrafficLight]] = {}
        self._traffic_light_grid_cell_size: float = 60.0

        self.sync_map_data(ways, traffic_lights=traffic_lights)
        self.set_venue_buildings(venue_buildings)

    def set_venue_buildings(self, buildings: Optional[List] = None) -> None:
        """Index hospitality venues as preferred pedestrian spawn locations."""
        self.buildings = list(buildings or [])
        self.venue_locations = []
        for building in buildings or []:
            if getattr(building, "venue_type", None) not in VENUE_TYPES or len(building.points_m) < 3:
                continue
            self.venue_locations.append(
                (
                    sum(point[0] for point in building.points_m) / len(building.points_m),
                    sum(point[1] for point in building.points_m) / len(building.points_m),
                )
            )

    def _point_near_building(self, x: float, y: float, radius_m: float = 250.0) -> bool:
        """Return whether a point is near a mapped building."""
        building_data = [
            building
            for building in self.buildings
            if (bbox := getattr(building, "bbox", None))
            and bbox != (0.0, 0.0, 0.0, 0.0)
        ]
        if not building_data:
            return True
        radius_sq = radius_m * radius_m
        for building in building_data:
            min_x, min_y, max_x, max_y = building.bbox
            nearest_x = min(max(x, min_x), max_x)
            nearest_y = min(max(y, min_y), max_y)
            if (x - nearest_x) ** 2 + (y - nearest_y) ** 2 <= radius_sq:
                return True
        return False

    def _taxi_stop_waiting_position(self, stop) -> Tuple[float, float]:
        """Return the nearest pedestrian-way point instead of the road center."""
        nearest = None
        nearest_distance = float("inf")
        for way in self.ped_ways:
            for p1, p2 in zip(way.points_m, way.points_m[1:]):
                x, y, _, distance = closest_point_and_dist_to_segment(
                    stop.x, stop.y, p1[0], p1[1], p2[0], p2[1]
                )
                if distance < nearest_distance:
                    nearest = (x, y)
                    nearest_distance = distance
        return nearest or (stop.x, stop.y)

    def sync_map_data(self, ways: List[Way], traffic_lights: Optional[List[TrafficLight]] = None) -> None:
        """Update road/path network and rebuild spatial grids for pedestrian routing."""
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights

        self._traffic_light_grid.clear()
        signal_cell_size = self._traffic_light_grid_cell_size
        for traffic_light in self.traffic_lights:
            cell = (
                int(math.floor(traffic_light.x / signal_cell_size)),
                int(math.floor(traffic_light.y / signal_cell_size)),
            )
            self._traffic_light_grid.setdefault(cell, []).append(traffic_light)

        # Prefer dedicated pedestrian paths (footway, path, pedestrian, cycleway, steps, track, crossing)
        dedicated = [w for w in ways if is_pedestrian_way(w) and len(w.points_m) >= 2]
        if dedicated:
            self.ped_ways = dedicated
        else:
            # Fallback only if map has no footpaths at all (e.g. sparse highway-only maps)
            self.ped_ways = [w for w in ways if getattr(w, "highway", "") in ("residential", "living_street", "unclassified", "service") and len(w.points_m) >= 2]

        self._way_grid.clear()
        cs = self._way_grid_cell_size
        for w in self.ped_ways:
            minx = min(p[0] for p in w.points_m)
            maxx = max(p[0] for p in w.points_m)
            miny = min(p[1] for p in w.points_m)
            maxy = max(p[1] for p in w.points_m)

            min_cx = int(math.floor(minx / cs))
            max_cx = int(math.floor(maxx / cs))
            min_cy = int(math.floor(miny / cs))
            max_cy = int(math.floor(maxy / cs))

            for cx in range(min_cx, max_cx + 1):
                for cy in range(min_cy, max_cy + 1):
                    self._way_grid.setdefault((cx, cy), []).append(w)

        self._build_junction_grid()

    def set_target_count(self, target_count: int, player_car: Optional[Car] = None) -> None:
        """Adjust active pedestrian count and discard farthest characters when needed."""
        self.target_count = max(0, target_count)
        self._population_update_elapsed = 0.5
        if len(self.pedestrians) > self.target_count:
            if player_car is not None:
                self.pedestrians.sort(key=lambda ped: math.hypot(ped.x - player_car.x, ped.y - player_car.y))
            del self.pedestrians[self.target_count:]

    def ensure_taxi_stop_waiter(
        self,
        taxi_stops: List,
        player_car: Car,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> None:
        """Sometimes send a visible or newly spawned pedestrian to a taxi stop."""
        if not taxi_stops:
            return

        visible_stops = set()
        if viewport_bounds:
            vminx, vminy, vmaxx, vmaxy = viewport_bounds
            visible_stops = {
                (stop.x, stop.y, stop.id)
                for stop in taxi_stops
                if vminx <= stop.x <= vmaxx and vminy <= stop.y <= vmaxy
            }
            if self._taxi_stop_visibility_initialized:
                newly_visible_stops = visible_stops - self._visible_taxi_stops
            else:
                newly_visible_stops = set()
                self._taxi_stop_visibility_initialized = True
            self._visible_taxi_stops = visible_stops
        else:
            newly_visible_stops = None

        if any(getattr(ped, "is_taxi_stop_waiter", False) for ped in self.pedestrians):
            return

        candidates = sorted(
            taxi_stops,
            key=lambda stop: math.hypot(stop.x - player_car.x, stop.y - player_car.y),
        )
        for stop in candidates:
            stop_key = (stop.x, stop.y, stop.id)
            if newly_visible_stops is not None and stop_key not in newly_visible_stops:
                continue
            if math.hypot(stop.x - player_car.x, stop.y - player_car.y) > self.spawn_radius_m:
                continue
            if viewport_bounds is None:
                waiter = self.spawn_pedestrian(stop.x, stop.y)
                if waiter is None:
                    continue
                waiter.x, waiter.y = self._taxi_stop_waiting_position(stop)
                waiter.is_taxi_stop_waiter = True
                waiter.wants_taxi = True
                waiter.speed = 0.0
                waiter.base_speed = 0.0
                self.pedestrians.append(waiter)
                return
            vminx = vminy = vmaxx = vmaxy = 0.0
            if viewport_bounds:
                vminx, vminy, vmaxx, vmaxy = viewport_bounds
            visible_pedestrians = [
                ped for ped in self.pedestrians
                if not getattr(ped, "is_walking_to_taxi_stop", False)
                and not getattr(ped, "is_taxi_stop_waiter", False)
                and (
                    viewport_bounds is None
                    or vminx <= ped.x <= vmaxx and vminy <= ped.y <= vmaxy
                )
            ]
            customer = random.choice(visible_pedestrians) if visible_pedestrians else None
            customer_chance = 0.70 if customer is not None else 0.35
            if random.random() >= customer_chance:
                continue
            if customer is None:
                customer = self.spawn_pedestrian(
                    player_car.x,
                    player_car.y,
                    viewport_bounds=viewport_bounds,
                )
                if customer is None:
                    continue
                self.pedestrians.append(customer)

            customer.taxi_stop_target = self._taxi_stop_waiting_position(stop)
            customer.is_walking_to_taxi_stop = True
            customer.wants_taxi = True
            customer.is_taxi_stop_waiter = False
            logger.info(
                "Pedestrian heading to taxi stop: x=%.1f y=%.1f spawned=%s",
                stop.x,
                stop.y,
                customer not in visible_pedestrians,
            )
            return

    def _build_junction_grid(self) -> None:
        """Build spatial grid indexing way endpoints and vertices for seamless path transitions."""
        self._junction_grid.clear()
        j_cs = self._junction_grid_cell_size
        for w in self.ped_ways:
            n_pts = len(w.points_m)
            if n_pts < 2:
                continue
            layer = getattr(w, "layer", 0)
            for i, pt in enumerate(w.points_m):
                cx = int(math.floor(pt[0] / j_cs))
                cy = int(math.floor(pt[1] / j_cs))
                self._junction_grid.setdefault((cx, cy), []).append((w, i, pt, layer, n_pts))

    def _find_next_way_and_segment(
        self,
        current_way: Way,
        at_point: Tuple[float, float],
        exclude_reverse: bool = False,
        incoming_heading: Optional[float] = None,
    ) -> Optional[Tuple[Way, int, int]]:
        """Find a connected pedestrian way at junction point to continue walking."""
        tol = 4.0
        tol_sq = tol * tol
        current_layer = getattr(current_way, "layer", 0)
        candidates: List[Tuple[Way, int, int]] = []

        j_cs = self._junction_grid_cell_size
        cx = int(math.floor(at_point[0] / j_cs))
        cy = int(math.floor(at_point[1] / j_cs))
        at_x, at_y = at_point

        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cell = self._junction_grid.get((cx + dx, cy + dy))
                if not cell:
                    continue
                for w, i, pt, layer, n_pts in cell:
                    if layer != current_layer:
                        continue
                    dist_sq = (pt[0] - at_x) ** 2 + (pt[1] - at_y) ** 2
                    if dist_sq <= tol_sq:
                        # Pedestrians can walk bidirectional on all footpaths
                        if i < n_pts - 1:
                            candidates.append((w, i, 1))
                        if i > 0:
                            candidates.append((w, i - 1, -1))

        if not candidates:
            return None

        # Filter candidates by forward direction if incoming_heading given
        if incoming_heading is not None:
            forward_candidates = []
            for cand in candidates:
                cand_way, cand_seg_idx, cand_dir = cand
                cand_pts = cand_way.points_m
                if cand_dir == 1:
                    p1 = cand_pts[cand_seg_idx]
                    p2 = cand_pts[cand_seg_idx + 1]
                else:
                    p1 = cand_pts[cand_seg_idx + 1]
                    p2 = cand_pts[cand_seg_idx]
                out_heading = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                angle_diff = abs((out_heading - incoming_heading + math.pi) % (2 * math.pi) - math.pi)
                if angle_diff < math.radians(135):
                    forward_candidates.append(cand)
            if forward_candidates:
                candidates = forward_candidates

        alternatives = [c for c in candidates if c[0] is not current_way]
        if alternatives and random.random() < 0.6:
            return random.choice(alternatives)

        valid_candidates = candidates
        if exclude_reverse:
            valid_candidates = [c for c in candidates if c[0] is not current_way]
            if not valid_candidates:
                return None

        return random.choice(valid_candidates)

    def spawn_pedestrian(
        self,
        near_x: float,
        near_y: float,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
        max_distance_m: Optional[float] = None,
    ) -> Optional[Pedestrian]:
        """Spawn a new pedestrian near location, just outside viewport edge."""
        if not self.ped_ways:
            return None

        w_cs = self._way_grid_cell_size
        r = self.spawn_radius_m
        min_cx = int(math.floor((near_x - r) / w_cs))
        max_cx = int(math.floor((near_x + r) / w_cs))
        min_cy = int(math.floor((near_y - r) / w_cs))
        max_cy = int(math.floor((near_y + r) / w_cs))

        nearby_ways = []
        seen: Set[int] = set()
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                cell = self._way_grid.get((cx, cy))
                if cell:
                    for w in cell:
                        wid = id(w)
                        if wid not in seen:
                            seen.add(wid)
                            nearby_ways.append(w)

        if not nearby_ways:
            return None

        valid_ways = []
        for w in nearby_ways:
            for p in w.points_m:
                if (p[0] - near_x) ** 2 + (p[1] - near_y) ** 2 <= r * r:
                    valid_ways.append(w)
                    break

        if not valid_ways:
            return None

        # Try up to 30 candidate ways/segments to place pedestrians outside viewport
        random.shuffle(valid_ways)
        for chosen_way in valid_ways[:30]:
            if len(chosen_way.points_m) < 2:
                continue

            candidate_segments = list(range(len(chosen_way.points_m) - 1))
            random.shuffle(candidate_segments)

            for seg_idx in candidate_segments:
                p1 = chosen_way.points_m[seg_idx]
                p2 = chosen_way.points_m[seg_idx + 1]

                for _ in range(8):  # Try multiple random points along segment
                    t = random.uniform(0.05, 0.95)
                    x = p1[0] + t * (p2[0] - p1[0])
                    y = p1[1] + t * (p2[1] - p1[1])

                    if viewport_bounds:
                        vminx, vminy, vmaxx, vmaxy = viewport_bounds
                        if vminx <= x <= vmaxx and vminy <= y <= vmaxy:
                            continue

                    direction = 1 if random.random() < 0.5 else -1
                    if direction == 1:
                        heading = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                    else:
                        heading = math.atan2(p1[1] - p2[1], p1[0] - p2[0])

                    # Natural pedestrian speed distribution:
                    # - 15% slow walkers / seniors: ~0.8 - 1.05 m/s (~3.0 - 3.8 km/h)
                    # - 65% average walkers / commuters: ~1.15 - 1.45 m/s (~4.1 - 5.2 km/h)
                    # - 15% brisk / fast walkers: ~1.5 - 1.85 m/s (~5.4 - 6.7 km/h)
                    # - 5% joggers: ~2.2 - 3.0 m/s (~7.9 - 10.8 km/h)
                    roll = random.random()
                    if roll < 0.15:
                        base_speed = random.uniform(0.80, 1.05)
                    elif roll < 0.80:
                        base_speed = random.uniform(1.15, 1.45)
                    elif roll < 0.95:
                        base_speed = random.uniform(1.50, 1.85)
                    else:
                        base_speed = random.uniform(2.20, 3.00)

                    color = random.choice(PEDESTRIAN_COLORS)

                    # Natural lateral offset across the path width
                    hw = max(0.5, getattr(chosen_way, "half_width_m", 1.2))
                    max_lat = max(0.2, hw * 0.7)
                    # Walk slightly to the right or left of center, or spread naturally
                    init_lat = random.uniform(-max_lat, max_lat)
                    target_lat = random.uniform(-max_lat, max_lat)

                    # Offset initial position laterally
                    perp_x = -math.sin(heading)
                    perp_y = math.cos(heading)
                    x += perp_x * init_lat
                    y += perp_y * init_lat

                    if not self._point_near_building(x, y):
                        continue

                    if max_distance_m is not None and math.hypot(x - near_x, y - near_y) > max_distance_m:
                        continue

                    # Sanity check: do not spawn directly on top of player car
                    if math.hypot(x - near_x, y - near_y) < 3.0:
                        continue

                    # Sanity check: do not cluster pedestrians on top of each other
                    if any(math.hypot(x - p.x, y - p.y) < 0.5 for p in self.pedestrians):
                        continue

                    return Pedestrian(
                        x=x,
                        y=y,
                        heading=heading,
                        speed=base_speed,
                        base_speed=base_speed,
                        way=chosen_way,
                        segment_idx=seg_idx,
                        direction=direction,
                        color=color,
                        lateral_offset_m=init_lat,
                        target_lateral_offset_m=target_lat,
                        sway_phase=random.uniform(0.0, 2 * math.pi),
                        sway_frequency=random.uniform(3.5, 4.5),
                        pace_timer=random.uniform(1.0, 4.0),
                        wants_taxi=random.random() < 0.05,
                    )

        return None

    def spawn_pedestrian_at(self, x: float, y: float, heading: float = 0.0) -> Optional[Pedestrian]:
        """Create an ordinary pedestrian at a specific location on the nearest walkable way."""
        if not self.ped_ways:
            return None

        nearest = None
        for way in self.ped_ways:
            for segment_idx, (start, end) in enumerate(zip(way.points_m, way.points_m[1:])):
                _, _, progress, distance = closest_point_and_dist_to_segment(
                    x, y, start[0], start[1], end[0], end[1]
                )
                if nearest is None or distance < nearest[0]:
                    nearest = (distance, way, segment_idx, progress)
        if nearest is None:
            return None

        _, way, segment_idx, progress = nearest
        start = way.points_m[segment_idx]
        end = way.points_m[segment_idx + 1]
        segment_heading = math.atan2(end[1] - start[1], end[0] - start[0])
        direction = 1 if math.cos(heading - segment_heading) >= 0.0 else -1
        return Pedestrian(
            x=x,
            y=y,
            heading=heading,
            speed=1.3,
            base_speed=1.3,
            way=way,
            segment_idx=segment_idx,
            direction=direction,
            color=random.choice(PEDESTRIAN_COLORS),
            lateral_offset_m=0.0,
            target_lateral_offset_m=0.0,
        )

    def _is_pedestrian_red_light(self, ped: Pedestrian) -> bool:
        """Check if pedestrian is stopped by a red traffic light at an intersection/crossing."""
        # For pedestrians crossing roads: when vehicular light is green, pedestrian crossing is red (wait).
        # When vehicular light is red, pedestrian crossing is green (safe to cross).
        ped_stop_dist = 6.0
        cell_size = self._traffic_light_grid_cell_size
        cell_x = int(math.floor(ped.x / cell_size))
        cell_y = int(math.floor(ped.y / cell_size))
        nearby_lights = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby_lights.extend(self._traffic_light_grid.get((cell_x + offset_x, cell_y + offset_y), ()))

        for tl in nearby_lights:
            dx = tl.x - ped.x
            dy = tl.y - ped.y
            dist_sq = dx * dx + dy * dy
            if dist_sq > ped_stop_dist * ped_stop_dist:
                continue

            dist = math.sqrt(dist_sq)
            if dist < 0.5:
                continue

            # Pedestrian heading towards traffic light
            to_tl_x = dx / dist
            to_tl_y = dy / dist
            ped_dir_x = math.cos(ped.heading)
            ped_dir_y = -math.sin(ped.heading)
            dot = to_tl_x * ped_dir_x + to_tl_y * ped_dir_y
            if dot > 0.5:
                state = tl.get_state(self.sim_time)
                # If traffic light is green or yellow, vehicles have right of way -> pedestrian must wait
                if state in ("green", "yellow"):
                    return True
        return False

    def check_player_avoidance(self, player_car: Car, dt: float) -> bool:
        """Detect close approach and trigger pedestrian or cyclist avoidance."""
        car_speed = player_car.speed
        car_moving = abs(car_speed) > 1.5
        car_dir_x = math.cos(player_car.heading)
        car_dir_y = -math.sin(player_car.heading)
        car_perp_x = math.sin(player_car.heading)
        car_perp_y = -math.cos(player_car.heading)
        cyclist_collision = False

        for ped in self.pedestrians:
            if getattr(ped, "is_walking_to_taxi_stop", False):
                continue
            was_dodging = ped.dodge_timer > 0.0
            # Update timers
            if ped.curse_timer > 0.0:
                ped.curse_timer = max(0.0, ped.curse_timer - dt)
            if ped.dodge_timer > 0.0:
                ped.dodge_timer = max(0.0, ped.dodge_timer - dt)
                ped.x += ped.dodge_vx * dt
                ped.y += ped.dodge_vy * dt

            dx = ped.x - player_car.x
            dy = ped.y - player_car.y
            dist_sq = dx * dx + dy * dy

            # Longitudinal distance along car trajectory and lateral offset across car width
            long_dist = dx * car_dir_x + dy * car_dir_y
            lat_offset = abs(dx * car_perp_x + dy * car_perp_y)

            # Check if car is heading directly at pedestrian in its driving corridor
            is_directly_ahead = (
                car_moving
                and 0.0 < long_dist < 3.5  # Only when close ahead (within 3.5m)
                and lat_offset < 1.8       # Within vehicle width corridor
            )
            is_too_close = dist_sq < (1.25 * 1.25)  # Physical touch danger distance

            if is_directly_ahead or is_too_close:
                dist = math.sqrt(dist_sq) or 1.0
                to_ped_x = dx / dist
                to_ped_y = dy / dist

                side_sign = 1.0 if (dx * car_perp_x + dy * car_perp_y) >= 0 else -1.0
                dodge_fx = to_ped_x * 0.3 + car_perp_x * side_sign * 1.0
                dodge_fy = to_ped_y * 0.3 + car_perp_y * side_sign * 1.0
                mag = math.hypot(dodge_fx, dodge_fy) or 1.0

                dodge_speed = 3.5
                ped.dodge_vx = (dodge_fx / mag) * dodge_speed
                ped.dodge_vy = (dodge_fy / mag) * dodge_speed
                ped.dodge_timer = 0.4
                if getattr(ped, "is_cyclist", False) and not was_dodging:
                    cyclist_collision = True

                if ped.curse_timer <= 0.0:
                    ped.curse_timer = 2.0
                    ped.curse_text = random.choice(CURSE_SYMBOLS)

        return cyclist_collision

    def update(
        self,
        player_car: Car,
        dt: float,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> bool:
        """Update pedestrian simulation: despawning, spawning, waypoint traversal, traffic lights, and evasion."""
        self.sim_time += dt
        self._population_update_elapsed += dt

        if self._population_update_elapsed >= 0.5:
            self._population_update_elapsed = 0.0

            # Despawn pedestrians outside radius
            kept_peds = []
            d_sq = self.despawn_radius_m * self.despawn_radius_m
            for ped in self.pedestrians:
                dist_sq = (ped.x - player_car.x) ** 2 + (ped.y - player_car.y) ** 2
                if dist_sq <= d_sq:
                    kept_peds.append(ped)
            self.pedestrians = kept_peds

            # Spawn new pedestrians up to target_count
            attempts = 0
            max_attempts = max(50, self.target_count * 5)
            nearby_venues = [
                location for location in self.venue_locations
                if math.hypot(location[0] - player_car.x, location[1] - player_car.y) <= self.spawn_radius_m
            ]
            while len(self.pedestrians) < self.target_count and attempts < max_attempts:
                attempts += 1
                spawned_near_venue = bool(nearby_venues and random.random() < 0.6)
                if spawned_near_venue:
                    venue_x, venue_y = random.choice(nearby_venues)
                    new_ped = self.spawn_pedestrian(venue_x, venue_y, max_distance_m=45.0)
                else:
                    new_ped = self.spawn_pedestrian(player_car.x, player_car.y, viewport_bounds=viewport_bounds)
                if not new_ped and viewport_bounds:
                    new_ped = self.spawn_pedestrian(
                        player_car.x,
                        player_car.y,
                        viewport_bounds=None,
                    )
                if not new_ped:
                    break
                if spawned_near_venue and random.random() < 0.35:
                    new_ped.is_drunk = True
                    new_ped.drunk_phase = random.uniform(0.0, 2.0 * math.pi)
                    new_ped.drunk_vomit_cooldown = random.uniform(8.0, 25.0)
                self.pedestrians.append(new_ped)

        # Check interaction and dodging with player car
        cyclist_collision = self.check_player_avoidance(player_car, dt)

        # Update walking movement
        for ped in self.pedestrians:
            taxi_stop_target = getattr(ped, "taxi_stop_target", None)
            if getattr(ped, "is_walking_to_taxi_stop", False) and taxi_stop_target is not None:
                target_x, target_y = taxi_stop_target
                dx = target_x - ped.x
                dy = target_y - ped.y
                distance = math.hypot(dx, dy)
                if distance <= 1.0:
                    ped.x = target_x
                    ped.y = target_y
                    ped.speed = 0.0
                    ped.base_speed = 0.0
                    ped.is_walking_to_taxi_stop = False
                    ped.is_taxi_stop_waiter = True
                    logger.info("Pedestrian arrived at taxi stop: x=%.1f y=%.1f", target_x, target_y)
                    continue
                ped.heading = math.atan2(dy, dx)
                ped.speed = ped.base_speed
                step = min(distance, ped.speed * dt)
                ped.x += math.cos(ped.heading) * step
                ped.y += math.sin(ped.heading) * step
                continue
            if getattr(ped, "is_taxi_stop_waiter", False):
                ped.speed = 0.0
                continue
            if getattr(ped, "is_drunk", False):
                ped.drunk_phase += dt * 2.7
                ped.drunk_vomit_cooldown = max(0.0, ped.drunk_vomit_cooldown - dt)
                if ped.drunk_vomit_cooldown <= 0.0 and random.random() < 0.012 * dt:
                    self.vomit_puddles.append((ped.x, ped.y))
                    if len(self.vomit_puddles) > 50:
                        del self.vomit_puddles[:-50]
                    ped.drunk_vomit_cooldown = random.uniform(18.0, 40.0)
            # Check traffic light stop
            if self._is_pedestrian_red_light(ped):
                ped.speed = 0.0
                continue
            else:
                # Slight natural pace fluctuations (±8%)
                ped.pace_timer -= dt
                if ped.pace_timer <= 0.0:
                    ped.pace_timer = random.uniform(2.0, 5.0)
                    ped.speed_variation_factor = random.uniform(0.92, 1.08)
                ped.speed = ped.base_speed * ped.speed_variation_factor

            if ped.dodge_timer > 0.0:
                # Controlled by dodge physics
                continue

            pts = ped.way.points_m
            n_pts = len(pts)
            if n_pts < 2:
                continue

            # Ensure valid segment
            ped.segment_idx = max(0, min(ped.segment_idx, n_pts - 2))

            p_start = pts[ped.segment_idx]
            p_end = pts[ped.segment_idx + 1]

            # Segment baseline direction and heading
            seg_dx = p_end[0] - p_start[0] if ped.direction == 1 else p_start[0] - p_end[0]
            seg_dy = p_end[1] - p_start[1] if ped.direction == 1 else p_start[1] - p_end[1]
            seg_len = math.hypot(seg_dx, seg_dy) or 1.0
            seg_heading = math.atan2(seg_dy, seg_dx)

            # Lateral offset drift along sidewalk width
            hw = max(0.5, getattr(ped.way, "half_width_m", 1.2))
            max_lat = max(0.2, hw * (0.85 if getattr(ped, "is_cyclist", False) else 0.7))

            # Slowly drift towards target lateral offset, re-rolling target periodically
            if abs(ped.lateral_offset_m - ped.target_lateral_offset_m) < 0.05 or random.random() < (0.01 * dt):
                if getattr(ped, "is_cyclist", False):
                    ped.target_lateral_offset_m = max(0.3, min(max_lat, hw * 0.75))
                else:
                    ped.target_lateral_offset_m = random.uniform(-max_lat, max_lat)

            lat_diff = ped.target_lateral_offset_m - ped.lateral_offset_m
            if abs(lat_diff) > 0.001:
                shift = math.copysign(min(abs(lat_diff), ped.lateral_speed_mps * dt), lat_diff)
                ped.lateral_offset_m = max(-max_lat, min(max_lat, ped.lateral_offset_m + shift))

            # Segment target waypoint with lateral offset
            target_base = p_end if ped.direction == 1 else p_start
            if getattr(ped, "is_cyclist", False):
                perp_x = math.sin(seg_heading)
                perp_y = -math.cos(seg_heading)
            else:
                perp_x = -math.sin(seg_heading)
                perp_y = math.cos(seg_heading)

            target_x = target_base[0] + perp_x * ped.lateral_offset_m
            target_y = target_base[1] + perp_y * ped.lateral_offset_m

            dx = target_x - ped.x
            dy = target_y - ped.y
            dist_to_target = math.hypot(dx, dy)

            # Update sway phase based on walking speed
            ped.sway_phase += ped.sway_frequency * (ped.speed / max(0.5, ped.base_speed)) * dt
            # Small natural curve/wobble in heading
            sway_angle = math.sin(ped.sway_phase) * math.radians(18.0 if getattr(ped, "is_drunk", False) else 3.5)
            if getattr(ped, "is_drunk", False):
                sway_angle += math.sin(ped.drunk_phase) * math.radians(10.0)

            target_heading = math.atan2(dy, dx)
            ped.heading = target_heading + sway_angle

            move_dist = ped.speed * dt
            if move_dist < dist_to_target:
                ped.x += math.cos(ped.heading) * move_dist
                ped.y += math.sin(ped.heading) * move_dist
            else:
                # Reached waypoint target
                ped.x = target_x
                ped.y = target_y
                remaining_dist = move_dist - dist_to_target

                reached_end = (ped.direction == 1 and ped.segment_idx >= n_pts - 2) or (
                    ped.direction == -1 and ped.segment_idx <= 0
                )

                if reached_end:
                    next_choice = self._find_next_way_and_segment(
                        ped.way,
                        target_base,
                        incoming_heading=seg_heading,
                    )
                    if next_choice:
                        ped.way, ped.segment_idx, ped.direction = next_choice
                    else:
                        # Turn around on same path
                        ped.direction = -ped.direction
                        if ped.direction == 1:
                            ped.segment_idx = 0
                        else:
                            ped.segment_idx = max(0, len(ped.way.points_m) - 2)
                else:
                    ped.segment_idx += ped.direction

                # Move along new segment with remaining distance
                new_pts = ped.way.points_m
                if len(new_pts) >= 2:
                    ped.segment_idx = max(0, min(ped.segment_idx, len(new_pts) - 2))
                    if ped.direction == 1:
                        p_next = new_pts[ped.segment_idx + 1]
                    else:
                        p_next = new_pts[ped.segment_idx]
                    ndx = p_next[0] - ped.x
                    ndy = p_next[1] - ped.y
                    if math.hypot(ndx, ndy) > 0.001:
                        ped.heading = math.atan2(ndy, ndx) + sway_angle
                        ped.x += math.cos(ped.heading) * remaining_dist
                        ped.y += math.sin(ped.heading) * remaining_dist

        return cyclist_collision


class CyclistManager(PedestrianManager):
    """Manage cyclists on light-traffic paths and ordinary city roads."""

    def sync_map_data(self, ways: List[Way], traffic_lights: Optional[List[TrafficLight]] = None) -> None:
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights
        self.ped_ways = [
            way for way in ways
            if len(way.points_m) >= 2
            and (
                is_pedestrian_way(way)
                or (
                    is_car_road(way)
                    and getattr(way, "highway", "") not in {"motorway", "motorway_link", "trunk", "trunk_link"}
                )
            )
        ]
        self._way_grid.clear()
        cs = self._way_grid_cell_size
        for way in self.ped_ways:
            minx = min(point[0] for point in way.points_m)
            maxx = max(point[0] for point in way.points_m)
            miny = min(point[1] for point in way.points_m)
            maxy = max(point[1] for point in way.points_m)
            for cx in range(int(math.floor(minx / cs)), int(math.floor(maxx / cs)) + 1):
                for cy in range(int(math.floor(miny / cs)), int(math.floor(maxy / cs)) + 1):
                    self._way_grid.setdefault((cx, cy), []).append(way)
        self._build_junction_grid()

    @property
    def cyclists(self) -> List[Pedestrian]:
        return self.pedestrians

    def spawn_pedestrian(
        self,
        near_x: float,
        near_y: float,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> Optional[Pedestrian]:
        cyclist = super().spawn_pedestrian(near_x, near_y, viewport_bounds)
        if cyclist is None:
            return None
        cyclist.is_cyclist = True
        cyclist.color = random.choice(CYCLIST_COLORS)
        cyclist.base_speed = random.uniform(3.5, 6.5)
        cyclist.speed = cyclist.base_speed
        cyclist.radius_m = 0.6
        cyclist.lateral_offset_m = max(
            0.3,
            min(
                max(0.2, getattr(cyclist.way, "half_width_m", 1.2) * 0.85),
                getattr(cyclist.way, "half_width_m", 1.2) * 0.75,
            ),
        )
        cyclist.target_lateral_offset_m = cyclist.lateral_offset_m
        start = cyclist.way.points_m[cyclist.segment_idx]
        end = cyclist.way.points_m[cyclist.segment_idx + 1]
        segment_dx = end[0] - start[0]
        segment_dy = end[1] - start[1]
        segment_length_sq = segment_dx * segment_dx + segment_dy * segment_dy
        if segment_length_sq > 0.0:
            position_dx = cyclist.x - start[0]
            position_dy = cyclist.y - start[1]
            progress = max(
                0.05,
                min(
                    0.95,
                    (position_dx * segment_dx + position_dy * segment_dy) / segment_length_sq,
                ),
            )
            base_x = start[0] + segment_dx * progress
            base_y = start[1] + segment_dy * progress
            right_x = math.sin(cyclist.heading)
            right_y = -math.cos(cyclist.heading)
            cyclist.x = base_x + right_x * cyclist.lateral_offset_m
            cyclist.y = base_y + right_y * cyclist.lateral_offset_m
        return cyclist
