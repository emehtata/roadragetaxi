import math
import random
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from .geo import clamp, closest_point_and_dist_to_segment, compute_bbox, dist_point_to_segment, point_in_polygon

# Car physics (arcade)
ACCEL = 4.0  # m/s^2; approximately 0-100 km/h in 7 seconds
REVERSE_ACCEL = 2.5  # m/s^2; slower acceleration while reversing
BRAKE = 28.0  # m/s^2
FRICTION = 6.0  # m/s^2
STEER_RATE = 2.6  # rad/s at low speed
STEER_SPEED_FACTOR = 0.10  # less steering at higher speed
MAX_SPEED = 205.0 / 3.6  # m/s (205 km/h)
SPEED_LIMIT_DECEL = 4.0  # m/s^2; smooth automatic braking at a speed limit
OFFROAD_MAX_SPEED = 2.0  # m/s (~7 km/h)
LIGHT_TRAFFIC_MAX_SPEED = 6.0  # m/s (~22 km/h) on footways, paths, and cycleways
OFFROAD_DECEL = 10.0  # m/s^2 when slowing from road speed

NON_DRIVABLE_HIGHWAYS = {
    "footway",
    "path",
    "pedestrian",
    "cycleway",
    "steps",
    "bridleway",
    "corridor",
    "track",
}

LIGHT_TRAFFIC_HIGHWAYS = {
    "footway",
    "path",
    "pedestrian",
    "cycleway",
    "steps",
    "bridleway",
    "corridor",
}


@dataclass
class Car:
    x: float
    y: float
    heading: float  # radians, 0 = east
    speed: float  # m/s
    layer: int = 0  # current vertical layer / bridge level (default 0 = ground)
    trip_m: float = 0.0  # trip distance in meters
    odometer_m: float = 0.0  # total odometer distance in meters
    length_m: float = 4.0  # length in meters
    width_m: float = 1.8  # width in meters
    time_since_last_steer: float = 0.0  # seconds elapsed without manual steer input
    lane_assist_enabled: bool = False  # user toggle for lane assist feature (default False)
    lane_assist_active: bool = False  # whether lane assist is currently steering


def is_car_road(way) -> bool:
    """Check if a road way is allowed for passenger cars and taxis."""
    if getattr(way, "is_ice_road", False):
        return False
    if getattr(way, "is_busway", False):
        return True
    if getattr(way, "highway", "") == "living_street":
        return True
    if not getattr(way, "is_drivable", True):
        return False
    if getattr(way, "highway", "") in NON_DRIVABLE_HIGHWAYS:
        return False
    return True


def is_pedestrian_way(way) -> bool:
    """Check if a way is suitable for pedestrians (dedicated footways, paths, sidewalks, pedestrian zones, crossings, steps)."""
    if getattr(way, "is_ice_road", False):
        return False
    hw = getattr(way, "highway", "")
    # Dedicated footpaths, sidewalks, cycleways, tracks, steps, and pedestrian zones
    if hw in ("footway", "path", "pedestrian", "cycleway", "steps", "track", "crossing", "bridleway", "corridor"):
        return True
    return False


def is_light_traffic_way(way) -> bool:
    """Return whether a way gets the light-traffic speed cap off-road."""
    return getattr(way, "highway", "") in LIGHT_TRAFFIC_HIGHWAYS


def is_point_on_light_traffic_way(
    px: float,
    py: float,
    ways: Optional[List] = None,
    spatial_grid: Optional["SpatialWayGrid"] = None,
) -> bool:
    """Check whether a point lies on a mapped footway, path, or cycleway."""
    candidates = (
        spatial_grid._candidate_ways(px, py)
        if spatial_grid is not None
        else ((way, getattr(way, "half_width_m", 3.0)) for way in (ways or []))
    )
    for way, half_width in candidates:
        if not is_light_traffic_way(way):
            continue
        for p1, p2 in zip(way.points_m, way.points_m[1:]):
            if dist_point_to_segment(px, py, p1[0], p1[1], p2[0], p2[1]) <= half_width:
                return True
    return False


def is_point_in_water(px: float, py: float, waters: List) -> bool:
    """Check if point (px, py) is inside any water polygon or on a waterway with fast AABB rejection."""
    if not waters:
        return False
    for w in waters:
        # Pre-filter using bounding box if available
        bbox = getattr(w, "_bbox", None)
        if bbox is None and getattr(w, "points_m", None):
            bbox = compute_bbox(w.points_m)
            w._bbox = bbox

        if bbox is not None:
            minx, miny, maxx, maxy = bbox
            if not (minx - 5.0 <= px <= maxx + 5.0 and miny - 5.0 <= py <= maxy + 5.0):
                continue

        if getattr(w, "is_polygon", False) and len(w.points_m) >= 3:
            if point_in_polygon(px, py, w.points_m):
                return True
        elif len(w.points_m) >= 2:
            for i in range(len(w.points_m) - 1):
                ax, ay = w.points_m[i]
                bx, by = w.points_m[i + 1]
                if dist_point_to_segment(px, py, ax, ay, bx, by) <= 5.0:
                    return True
    return False


def is_car_fully_in_water(car: Car, waters: List, current_way=None) -> bool:
    """Return whether all four corners are in water, except while on a bridge."""
    if getattr(current_way, "is_bridge", False):
        return False
    half_length = getattr(car, "length_m", 4.0) * 0.5
    half_width = getattr(car, "width_m", 1.8) * 0.5
    forward_x = math.cos(car.heading)
    forward_y = math.sin(car.heading)
    right_x = math.sin(car.heading)
    right_y = -math.cos(car.heading)
    corners = (
        (half_length, half_width),
        (half_length, -half_width),
        (-half_length, half_width),
        (-half_length, -half_width),
    )
    return bool(waters) and all(
        is_point_in_water(
            car.x + forward_x * longitudinal + right_x * lateral,
            car.y + forward_y * longitudinal + right_y * lateral,
            waters,
        )
        for longitudinal, lateral in corners
    )


def compute_largest_connected_road_component(ways: List) -> List:
    """Find the largest connected component among drivable car roads."""
    drivable = [w for w in ways if is_car_road(w) and len(w.points_m) >= 2]
    if not drivable:
        return ways

    # Map grid coordinates (discretized to ~1.0m to handle floating point tolerance) to way indices
    grid_res = 1.0
    pt_to_ways: dict[Tuple[int, int], List[int]] = {}

    def quantize(pt: Tuple[float, float]) -> Tuple[int, int]:
        return int(round(pt[0] / grid_res)), int(round(pt[1] / grid_res))

    for idx, w in enumerate(drivable):
        for pt in (w.points_m[0], w.points_m[-1]):
            key = quantize(pt)
            if key not in pt_to_ways:
                pt_to_ways[key] = []
            pt_to_ways[key].append(idx)

    # Build adjacency graph between ways
    adj: dict[int, set[int]] = {i: set() for i in range(len(drivable))}
    for way_indices in pt_to_ways.values():
        if len(way_indices) < 2:
            continue
        representative = way_indices[0]
        for way_index in way_indices[1:]:
            adj[representative].add(way_index)
            adj[way_index].add(representative)

    # Find connected components with BFS/DFS
    visited: set[int] = set()
    components: List[List[int]] = []

    for i in range(len(drivable)):
        if i in visited:
            continue
        comp = []
        queue = [i]
        visited.add(i)
        for curr in queue:
            comp.append(curr)
            for neighbor in adj[curr]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(comp)

    # Find component with greatest total road length
    def component_total_length(comp: List[int]) -> float:
        total = 0.0
        for widx in comp:
            w = drivable[widx]
            for s in range(len(w.points_m) - 1):
                total += math.hypot(
                    w.points_m[s + 1][0] - w.points_m[s][0],
                    w.points_m[s + 1][1] - w.points_m[s][1],
                )
        return total

    largest_comp = max(components, key=component_total_length)
    return [drivable[i] for i in largest_comp]


def connected_drivable_ways(ways: List, named: bool = False) -> List:
    connected = compute_largest_connected_road_component(ways) if ways else []
    candidates = [w for w in connected if is_car_road(w) and len(w.points_m) >= 2]
    if named:
        named_candidates = [w for w in candidates if getattr(w, "name", None)]
        candidates = named_candidates or candidates
    return candidates or [w for w in ways if is_car_road(w) and len(w.points_m) >= 2]


def respawn_car(
    car: Car,
    ways: List,
    near_center: bool = False,
    bounds: Optional[Tuple[float, float, float, float]] = None,
    waters: Optional[List] = None,
    taxi_stops: Optional[List] = None,
) -> None:
    """Place the car on a main connected drivable land road, avoiding isolated road segments."""
    if not ways:
        return

    if taxi_stops:
        stop = random.choice(taxi_stops)
        road_ways = [way for way in ways if is_car_road(way) and len(way.points_m) >= 2]
        nearest = None
        nearest_segment = None
        nearest_distance = float("inf")
        for way in road_ways:
            for p1, p2 in zip(way.points_m, way.points_m[1:]):
                cx, cy, _, distance = closest_point_and_dist_to_segment(
                    stop.x, stop.y, p1[0], p1[1], p2[0], p2[1]
                )
                if distance < nearest_distance:
                    nearest = way
                    nearest_segment = (p1, p2, cx, cy)
                    nearest_distance = distance
        if nearest:
            segment = nearest_segment
            car.x, car.y = segment[2], segment[3]
            car.heading = math.atan2(segment[1][1] - segment[0][1], segment[1][0] - segment[0][0])
        else:
            car.x, car.y = stop.x, stop.y
            car.heading = 0.0
        car.speed = 0.0
        car.layer = getattr(nearest or ways[0], "layer", 0)
        return

    # Extract connected component of main road network
    main_network = compute_largest_connected_road_component(ways)
    candidate_ways = [w for w in main_network if not getattr(w, "is_ice_road", False)]
    if not candidate_ways:
        candidate_ways = main_network if main_network else ways

    # Sort/rank candidate ways by distance to center if near_center requested
    if near_center and bounds:
        cx = (bounds[0] + bounds[2]) / 2
        cy = (bounds[1] + bounds[3]) / 2

        def way_center_dist_sq(w):
            if len(w.points_m) >= 2:
                mx = (w.points_m[0][0] + w.points_m[1][0]) / 2
                my = (w.points_m[0][1] + w.points_m[1][1]) / 2
                return (mx - cx) ** 2 + (my - cy) ** 2
            elif len(w.points_m) == 1:
                return (w.points_m[0][0] - cx) ** 2 + (w.points_m[0][1] - cy) ** 2
            return float("inf")

        candidate_ways = sorted(candidate_ways, key=way_center_dist_sq)
    else:
        # Random shuffle to avoid checking all ways if not near_center
        candidate_ways = list(candidate_ways)
        random.shuffle(candidate_ways)

    # Keep nearby valid roads for randomized startup placement.
    valid_ways = []
    for w in candidate_ways:
        if len(w.points_m) >= 2:
            mx = (w.points_m[0][0] + w.points_m[1][0]) / 2
            my = (w.points_m[0][1] + w.points_m[1][1]) / 2
            if not waters or not is_point_in_water(mx, my, waters):
                valid_ways.append(w)
        elif len(w.points_m) == 1:
            if not waters or not is_point_in_water(w.points_m[0][0], w.points_m[0][1], waters):
                valid_ways.append(w)
        if near_center and bounds and len(valid_ways) >= 20:
            break

    if near_center and bounds:
        w = random.choice(valid_ways or candidate_ways or ways)
    else:
        w = valid_ways[0] if valid_ways else (candidate_ways[0] if candidate_ways else ways[0])

    if len(w.points_m) >= 2:
        segment_idx = random.randrange(len(w.points_m) - 1) if near_center and bounds else 0
        ax, ay = w.points_m[segment_idx]
        bx, by = w.points_m[segment_idx + 1]
        progress = random.uniform(0.2, 0.8) if near_center and bounds else 0.5
        car.x = ax + (bx - ax) * progress
        car.y = ay + (by - ay) * progress
        car.heading = math.atan2(by - ay, bx - ax)
    elif len(w.points_m) == 1:
        car.x, car.y = w.points_m[0]
        car.heading = 0.0
    car.speed = 0.0
    car.layer = getattr(w, "layer", 0)


def reset_trip(car: Car) -> None:
    """Reset the car's trip meter."""
    car.trip_m = 0.0


class SpatialWayGrid:
    """Spatial hash grid indexing road ways for fast O(1) road collision checks."""

    def __init__(self, ways_or_cell_size=200.0, cell_size: float = 200.0):
        if isinstance(ways_or_cell_size, (list, tuple)):
            self.cell_size = cell_size
            self.grid: dict[Tuple[int, int], List] = {}
            self.indexed_way_count = 0
            self.rebuild(list(ways_or_cell_size))
        else:
            self.cell_size = float(ways_or_cell_size)
            self.grid: dict[Tuple[int, int], List] = {}
            self.indexed_way_count = 0

    def insert(self, way) -> None:
        bbox = getattr(way, "bbox", None)
        if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
            if not way.points_m:
                return
            xs = [p[0] for p in way.points_m]
            ys = [p[1] for p in way.points_m]
            bbox = (min(xs), min(ys), max(xs), max(ys))
            way.bbox = bbox

        hw = getattr(way, "half_width_m", 3.0)
        minx, miny, maxx, maxy = bbox
        gx0 = int((minx - hw) // self.cell_size)
        gx1 = int((maxx + hw) // self.cell_size)
        gy0 = int((miny - hw) // self.cell_size)
        gy1 = int((maxy + hw) // self.cell_size)
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                cell = (gx, gy)
                if cell not in self.grid:
                    self.grid[cell] = []
                self.grid[cell].append(way)

    def rebuild(self, ways: List) -> None:
        self.grid.clear()
        for w in ways:
            self.insert(w)
        self.indexed_way_count = len(ways)

    def _candidate_ways(
        self, px: float, py: float, car_roads_only: bool = False, layer: Optional[int] = None
    ):
        candidates = self.grid.get((int(px // self.cell_size), int(py // self.cell_size)), [])
        for way in candidates:
            if car_roads_only and not is_car_road(way):
                continue
            if layer is not None and getattr(way, "layer", 0) != layer:
                continue
            bbox = getattr(way, "bbox", None)
            half_width = getattr(way, "half_width_m", 3.0)
            if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
                if not (bbox[0] - half_width <= px <= bbox[2] + half_width and bbox[1] - half_width <= py <= bbox[3] + half_width):
                    continue
            yield way, half_width

    def is_point_on_road(self, px: float, py: float, car_roads_only: bool = False, layer: Optional[int] = None) -> bool:
        for way, half_width in self._candidate_ways(px, py, car_roads_only, layer):
            pts = way.points_m
            for i in range(len(pts) - 1):
                ax, ay = pts[i]
                bx, by = pts[i + 1]
                if dist_point_to_segment(px, py, ax, ay, bx, by) <= half_width:
                    return True
        return False

    def get_road_layer_at_point(self, px: float, py: float, current_layer: int = 0) -> int:
        """Find the matching road layer at (px, py), preferring the current layer if still on it."""
        matching_layers = []
        for way, half_width in self._candidate_ways(px, py, car_roads_only=True):
            pts = way.points_m
            for i in range(len(pts) - 1):
                ax, ay = pts[i]
                bx, by = pts[i + 1]
                if dist_point_to_segment(px, py, ax, ay, bx, by) <= half_width:
                    w_layer = getattr(way, "layer", 0)
                    if w_layer == current_layer:
                        return current_layer
                    matching_layers.append(w_layer)
                    break

        return matching_layers[0] if matching_layers else current_layer

    def get_current_road(self, px: float, py: float, layer: Optional[int] = None, car_roads_only: bool = True) -> Optional[Any]:
        """Find the specific road (Way) the given position is on, if any."""
        best_way = None
        best_dist = float("inf")
        for way, half_width in self._candidate_ways(px, py, car_roads_only, layer):
            pts = way.points_m
            for i in range(len(pts) - 1):
                ax, ay = pts[i]
                bx, by = pts[i + 1]
                d = dist_point_to_segment(px, py, ax, ay, bx, by)
                if d <= half_width and d < best_dist:
                    best_dist = d
                    best_way = way

        return best_way

    def is_on_road(self, car: Car, car_roads_only: bool = False) -> bool:
        return self.is_point_on_road(car.x, car.y, car_roads_only=car_roads_only)

    def is_violating_oneway(self, car: Car, px: float, py: float, dx: float, dy: float) -> bool:
        """Check if vehicle movement (dx, dy) opposes a one-way road direction."""
        move_len = math.hypot(dx, dy)
        if move_len < 1e-5:
            return False

        # Find roads covering the current position
        on_roads = []
        for way, half_width in self._candidate_ways(px, py, car_roads_only=True):
            pts = way.points_m
            for i in range(len(pts) - 1):
                ax, ay = pts[i]
                bx, by = pts[i + 1]
                _, _, _, dist = closest_point_and_dist_to_segment(px, py, ax, ay, bx, by)
                if dist <= half_width:
                    on_roads.append((way, i, ax, ay, bx, by))
                    break

        if not on_roads:
            return False

        # If ANY overlapping road allows two-way traffic (oneway == 0), don't block
        has_two_way = any(getattr(w, "oneway", 0) == 0 for w, _, _, _, _, _ in on_roads)
        if has_two_way:
            return False

        # Check if movement opposes all one-way roads at this location
        all_opposing = True
        for w, i, ax, ay, bx, by in on_roads:
            oneway_val = getattr(w, "oneway", 0)
            seg_dx = (bx - ax) * oneway_val
            seg_dy = (by - ay) * oneway_val
            seg_len = math.hypot(seg_dx, seg_dy)
            if seg_len > 1e-4:
                dot = (dx * seg_dx + dy * seg_dy) / (move_len * seg_len)
                # If aligned with at least one one-way road direction, it's valid movement
                if dot >= -0.2:
                    all_opposing = False
                    break

        return all_opposing


def is_violating_oneway(
    car: Car,
    px: float,
    py: float,
    dx: float,
    dy: float,
    ways: Optional[List] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
) -> bool:
    """Check if vehicle movement (dx, dy) at point (px, py) is driving against a one-way street."""
    if spatial_grid is not None:
        return spatial_grid.is_violating_oneway(car, px, py, dx, dy)

    if ways is None:
        return False

    move_len = math.hypot(dx, dy)
    if move_len < 1e-5:
        return False

    # Find roads covering the current position
    on_roads = []
    for w in ways:
        if not is_car_road(w):
            continue
        hw = getattr(w, "half_width_m", 3.0)
        pts = w.points_m
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            _, _, _, dist = closest_point_and_dist_to_segment(px, py, ax, ay, bx, by)
            if dist <= hw:
                on_roads.append((w, i, ax, ay, bx, by))
                break

    if not on_roads:
        return False

    has_two_way = any(getattr(w, "oneway", 0) == 0 for w, _, _, _, _, _ in on_roads)
    if has_two_way:
        return False

    all_opposing = True
    for w, i, ax, ay, bx, by in on_roads:
        oneway_val = getattr(w, "oneway", 0)
        seg_dx = (bx - ax) * oneway_val
        seg_dy = (by - ay) * oneway_val
        seg_len = math.hypot(seg_dx, seg_dy)
        if seg_len > 1e-4:
            dot = (dx * seg_dx + dy * seg_dy) / (move_len * seg_len)
            if dot >= -0.2:
                all_opposing = False
                break

    return all_opposing


def is_point_on_road(
    px: float,
    py: float,
    ways: Optional[List] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
    car_roads_only: bool = False,
    layer: Optional[int] = None,
) -> bool:
    """Check if point (px, py) is on a road (optionally restricted to car roads only and/or specific layer)."""
    if spatial_grid is not None:
        return spatial_grid.is_point_on_road(px, py, car_roads_only=car_roads_only, layer=layer)

    if ways is None:
        return False

    attached_grid = getattr(ways, "_spatial_grid", None)
    if attached_grid is not None:
        return attached_grid.is_point_on_road(px, py, car_roads_only=car_roads_only, layer=layer)

    for w in ways:
        if car_roads_only and not is_car_road(w):
            continue
        if layer is not None and getattr(w, "layer", 0) != layer:
            continue
        bbox = getattr(w, "bbox", None)
        hw = getattr(w, "half_width_m", 3.0)
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
            if not (bbox[0] - hw <= px <= bbox[2] + hw and bbox[1] - hw <= py <= bbox[3] + hw):
                continue
        pts = w.points_m
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            d = dist_point_to_segment(px, py, ax, ay, bx, by)
            if d <= hw:
                return True
    return False


def get_road_layer_at_point(
    px: float,
    py: float,
    current_layer: int = 0,
    ways: Optional[List] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
) -> int:
    """Find the matching road layer at (px, py), preferring current_layer if still on it."""
    if spatial_grid is not None:
        return spatial_grid.get_road_layer_at_point(px, py, current_layer=current_layer)

    if ways is None:
        return current_layer

    attached_grid = getattr(ways, "_spatial_grid", None)
    if attached_grid is not None:
        return attached_grid.get_road_layer_at_point(px, py, current_layer=current_layer)

    matching_layers = []
    for w in ways:
        if not is_car_road(w):
            continue
        bbox = getattr(w, "bbox", None)
        hw = getattr(w, "half_width_m", 3.0)
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
            if not (bbox[0] - hw <= px <= bbox[2] + hw and bbox[1] - hw <= py <= bbox[3] + hw):
                continue
        pts = w.points_m
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            if dist_point_to_segment(px, py, ax, ay, bx, by) <= hw:
                w_layer = getattr(w, "layer", 0)
                if w_layer == current_layer:
                    return current_layer
                matching_layers.append(w_layer)
                break

    return matching_layers[0] if matching_layers else current_layer


def is_on_road(
    car: Car,
    ways: Optional[List] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
    car_roads_only: bool = False,
) -> bool:
    """Check proximity using spatial grid or dist_point_to_segment and way half-widths."""
    return is_point_on_road(car.x, car.y, ways=ways, spatial_grid=spatial_grid, car_roads_only=car_roads_only, layer=car.layer)


def get_current_road_at_car(
    car: Car,
    ways: Optional[List] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
    car_roads_only: bool = True,
    current_way: Optional[Any] = None,
) -> Optional[Any]:
    """Find the specific Way the car is currently driving on, checking current way segment first before spatial lookup."""
    # Fast-path: check if car is still within bounds of current_way
    if current_way is not None:
        if (not car_roads_only or is_car_road(current_way)) and getattr(current_way, "layer", 0) == car.layer:
            hw = getattr(current_way, "half_width_m", 3.0)
            pts = current_way.points_m
            for i in range(len(pts) - 1):
                ax, ay = pts[i]
                bx, by = pts[i + 1]
                if dist_point_to_segment(car.x, car.y, ax, ay, bx, by) <= hw:
                    return current_way

    if spatial_grid:
        return spatial_grid.get_current_road(car.x, car.y, layer=car.layer, car_roads_only=car_roads_only)

    if not ways:
        return None

    best_way = None
    best_dist = float("inf")
    for w in ways:
        if car_roads_only and not is_car_road(w):
            continue
        if getattr(w, "layer", 0) != car.layer:
            continue
        bbox = getattr(w, "bbox", None)
        hw = getattr(w, "half_width_m", 3.0)
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
            if not (bbox[0] - hw <= car.x <= bbox[2] + hw and bbox[1] - hw <= car.y <= bbox[3] + hw):
                continue
        pts = w.points_m
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            d = dist_point_to_segment(car.x, car.y, ax, ay, bx, by)
            if d <= hw and d < best_dist:
                best_dist = d
                best_way = w

    return best_way


def update_car_physics(
    car: Car,
    throttle: float,
    brake: float,
    steer_left: float,
    steer_right: float,
    dt: float,
    ways: Optional[List] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
    block_offroad: bool = True,
    enforce_oneway: bool = False,
    speed_limit_mps: Optional[float] = None,
    nearby_vehicles: Optional[List] = None,
) -> bool:
    """Update car speed, heading, and position.

    When block_offroad is True and road data is provided, restricts motion to drivable
    car roads only, blocking movement if the vehicle attempts to leave the road.
    When enforce_oneway is True, prevents moving against the legal direction on one-way streets.
    Returns True if vehicle movement was blocked against the road boundary or one-way restriction.
    """
    if speed_limit_mps is not None and car.speed > speed_limit_mps:
        car.speed = max(speed_limit_mps, car.speed - SPEED_LIMIT_DECEL * dt)
    elif speed_limit_mps is not None and car.speed < -speed_limit_mps:
        car.speed = min(-speed_limit_mps, car.speed + SPEED_LIMIT_DECEL * dt)
    elif throttle > 0:
        car.speed = min(car.speed + ACCEL * dt, speed_limit_mps) if speed_limit_mps is not None else car.speed + ACCEL * dt
    elif brake > 0:
        if car.speed > 0.0:
            car.speed = max(0.0, car.speed - BRAKE * dt)
        else:
            car.speed -= REVERSE_ACCEL * dt
        if speed_limit_mps is not None:
            car.speed = max(-speed_limit_mps, car.speed)
    else:
        # friction slows towards 0
        if car.speed > 0:
            car.speed = max(0.0, car.speed - FRICTION * dt)
        else:
            car.speed = min(0.0, car.speed + FRICTION * dt)

    car.speed = clamp(car.speed, -10.0, MAX_SPEED)

    # Manual steering check
    steer_input = steer_left - steer_right
    if abs(steer_input) > 0.01:
        car.time_since_last_steer = 0.0
        car.lane_assist_active = False
    else:
        car.time_since_last_steer += dt

    # steer: positive -> turn left (counter-clockwise), negative -> turn right
    # Cars cannot steer in-place while stationary; turning requires moving forward or backward
    if abs(car.speed) > 0.05:
        if abs(steer_input) > 0.01:
            steer_effective = STEER_RATE / (1.0 + abs(car.speed) * STEER_SPEED_FACTOR)
            car.heading += steer_input * steer_effective * dt * (1.0 if car.speed >= 0 else -1.0)
        elif car.lane_assist_enabled and car.time_since_last_steer >= 0.35 and car.speed > 1.5:
            # Lane assist: when enabled and driver hasn't steered for a moment, gently track lane center
            current_road = get_current_road_at_car(
                car, ways=ways, spatial_grid=spatial_grid, car_roads_only=True
            )
            if current_road and len(current_road.points_m) >= 2:
                # Find closest road segment
                pts = current_road.points_m
                best_seg_idx = 0
                best_seg_dist = float("inf")
                best_px, best_py = pts[0]
                best_t = 0.0
                for i in range(len(pts) - 1):
                    p1 = pts[i]
                    p2 = pts[i + 1]
                    px, py, t, d = closest_point_and_dist_to_segment(car.x, car.y, p1[0], p1[1], p2[0], p2[1])
                    if d < best_seg_dist:
                        best_seg_dist = d
                        best_seg_idx = i
                        best_px, best_py = px, py
                        best_t = t

                p1 = pts[best_seg_idx]
                p2 = pts[best_seg_idx + 1]
                seg_dx = p2[0] - p1[0]
                seg_dy = p2[1] - p1[1]
                seg_len = math.hypot(seg_dx, seg_dy) or 1.0

                # Determine driving direction along road points
                forward_angle = math.atan2(seg_dy, seg_dx)
                rev_angle = math.atan2(-seg_dy, -seg_dx)
                diff_fwd = abs((car.heading - forward_angle + math.pi) % (2 * math.pi) - math.pi)
                diff_rev = abs((car.heading - rev_angle + math.pi) % (2 * math.pi) - math.pi)

                is_forward = diff_fwd <= diff_rev
                road_heading = forward_angle if is_forward else rev_angle
                heading_diff = (road_heading - car.heading + math.pi) % (2 * math.pi) - math.pi

                # Only assist if car is roughly aligned with road (< 60 degrees)
                if abs(heading_diff) < math.radians(60):
                    car.lane_assist_active = True
                    hw = getattr(current_road, "half_width_m", 3.5)
                    oneway = getattr(current_road, "oneway", 0)
                    lanes = getattr(current_road, "lanes", 1)

                    # Lateral unit vector to the right of road heading in EPSG:3067 Cartesian space
                    # Heading 0 (East) -> forward=(1, 0), right=(0, -1) (South)
                    # Heading pi/2 (North) -> forward=(0, 1), right=(1, 0) (East)
                    right_nx = math.sin(road_heading)
                    right_ny = -math.cos(road_heading)

                    # Desired lateral offset from road centerline (Finland: drive on the right)
                    if oneway == 0 and hw >= 2.5:
                        # 2-way road: right-hand lane (center between centerline and right edge)
                        desired_offset = max(1.0, min(hw - 1.2, hw * 0.5))
                    elif oneway != 0 and (lanes >= 2 or hw >= 4.5):
                        # Multi-lane 1-way road: drive on the rightmost lane
                        # Lane width is total_width / lanes = (2 * hw) / lanes
                        # Right edge is at +hw, rightmost lane center is at +hw - lane_width/2
                        lane_width = (2.0 * hw) / max(2, lanes)
                        desired_offset = max(1.0, min(hw - 1.0, hw - lane_width * 0.5))
                    else:
                        # Single-lane 1-way road: center of the road
                        desired_offset = 0.0

                    current_offset = (car.x - best_px) * right_nx + (car.y - best_py) * right_ny
                    offset_error = desired_offset - current_offset  # positive -> car is too far left, steer right

                    target_x = best_px + right_nx * desired_offset
                    target_y = best_py + right_ny * desired_offset
                    lane_blocked = any(
                        getattr(vehicle, "layer", 0) == car.layer
                        and math.hypot(vehicle.x - target_x, vehicle.y - target_y)
                        < (getattr(vehicle, "length_m", 4.0) + car.length_m) * 0.5
                        + (getattr(vehicle, "width_m", 1.8) + car.width_m) * 0.5
                        for vehicle in (nearby_vehicles or [])
                        if vehicle is not car
                    )

                    # PD-like gentle corrective steering
                    # Steer right when offset_error > 0 (in Cartesian space, right is negative angle delta)
                    desired_angle = road_heading if lane_blocked else road_heading - clamp(offset_error * 0.22, -0.35, 0.35)
                    corrective_diff = (desired_angle - car.heading + math.pi) % (2 * math.pi) - math.pi

                    assist_rate = 2.0  # rad/s max assist authority
                    max_steer_delta = assist_rate * dt
                    steer_step = clamp(corrective_diff * 3.0 * dt, -max_steer_delta, max_steer_delta)
                    car.heading += steer_step
                else:
                    car.lane_assist_active = False
            else:
                car.lane_assist_active = False
        else:
            car.lane_assist_active = False
    else:
        car.lane_assist_active = False

    dx = math.cos(car.heading) * car.speed * dt
    dy = math.sin(car.heading) * car.speed * dt
    target_x = car.x + dx
    target_y = car.y + dy

    blocked = False
    has_road_data = (spatial_grid is not None) or (ways is not None and len(ways) > 0)

    # Off-road driving is allowed by the game, with a higher cap on light-traffic ways.
    if has_road_data and not block_offroad:
        target_on_road = is_point_on_road(
            target_x, target_y, ways=ways, spatial_grid=spatial_grid, car_roads_only=True
        )
        if not target_on_road:
            target_on_light_traffic = is_point_on_light_traffic_way(
                target_x, target_y, ways=ways, spatial_grid=spatial_grid
            )
            speed_cap = LIGHT_TRAFFIC_MAX_SPEED if target_on_light_traffic else OFFROAD_MAX_SPEED
            if throttle > 0.0:
                if car.speed < 0.0:
                    car.speed = min(0.0, car.speed + ACCEL * dt)
                elif car.speed < speed_cap:
                    car.speed = min(speed_cap, car.speed + ACCEL * dt)
            if car.speed > speed_cap:
                car.speed = max(speed_cap, car.speed - OFFROAD_DECEL * dt)
            elif car.speed < -speed_cap:
                car.speed = min(-speed_cap, car.speed + OFFROAD_DECEL * dt)
            dx = math.cos(car.heading) * car.speed * dt
            dy = math.sin(car.heading) * car.speed * dt
            target_x = car.x + dx
            target_y = car.y + dy

    # Check one-way road violation
    if enforce_oneway and has_road_data and (dx != 0.0 or dy != 0.0):
        if is_violating_oneway(car, car.x, car.y, dx, dy, ways=ways, spatial_grid=spatial_grid):
            blocked = True
            car.speed = 0.0
            dx = 0.0
            dy = 0.0
            target_x = car.x
            target_y = car.y

    if block_offroad and has_road_data and (dx != 0.0 or dy != 0.0):
        currently_on_road = is_point_on_road(
            car.x, car.y, ways=ways, spatial_grid=spatial_grid, car_roads_only=True
        )
        target_on_road = is_point_on_road(
            target_x, target_y, ways=ways, spatial_grid=spatial_grid, car_roads_only=True
        )

        if target_on_road or not currently_on_road:
            car.x = target_x
            car.y = target_y
            dist = math.hypot(dx, dy)
            # Update car layer if vehicle entered a transition or road at a different layer
            car.layer = get_road_layer_at_point(
                car.x, car.y, current_layer=car.layer, ways=ways, spatial_grid=spatial_grid
            )
        else:
            # Try sliding along road edge on individual axes
            slide_x = is_point_on_road(
                target_x, car.y, ways=ways, spatial_grid=spatial_grid, car_roads_only=True
            )
            slide_y = is_point_on_road(
                car.x, target_y, ways=ways, spatial_grid=spatial_grid, car_roads_only=True
            )

            if slide_x and not slide_y and abs(dx) > 1e-4:
                car.x = target_x
                dist = abs(dx)
                car.speed = car.speed * abs(math.cos(car.heading))
                blocked = True
                car.layer = get_road_layer_at_point(
                    car.x, car.y, current_layer=car.layer, ways=ways, spatial_grid=spatial_grid
                )
            elif slide_y and not slide_x and abs(dy) > 1e-4:
                car.y = target_y
                dist = abs(dy)
                car.speed = car.speed * abs(math.sin(car.heading))
                blocked = True
                car.layer = get_road_layer_at_point(
                    car.x, car.y, current_layer=car.layer, ways=ways, spatial_grid=spatial_grid
                )
            else:
                # Fully blocked against road edge
                blocked = True
                car.speed = 0.0
                dist = 0.0
    else:
        car.x = target_x
        car.y = target_y
        dist = math.hypot(dx, dy)
        if has_road_data:
            car.layer = get_road_layer_at_point(
                car.x, car.y, current_layer=car.layer, ways=ways, spatial_grid=spatial_grid
            )

    # Accumulate trip and odometer distances based on speed magnitude
    car.trip_m += dist
    car.odometer_m += dist
    return blocked
