import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .geo import clamp, dist_point_to_segment, point_in_polygon

# Car physics (arcade)
ACCEL = 18.0  # m/s^2
BRAKE = 28.0  # m/s^2
FRICTION = 6.0  # m/s^2
STEER_RATE = 2.6  # rad/s at low speed
STEER_SPEED_FACTOR = 0.10  # less steering at higher speed
MAX_SPEED = 36.0  # m/s (~130 km/h)

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


@dataclass
class Car:
    x: float
    y: float
    heading: float  # radians, 0 = east
    speed: float  # m/s
    trip_m: float = 0.0  # trip distance in meters
    odometer_m: float = 0.0  # total odometer distance in meters


def is_car_road(way) -> bool:
    """Check if a road way is allowed for passenger cars."""
    if getattr(way, "is_ice_road", False):
        return False
    if not getattr(way, "is_drivable", True):
        return False
    if getattr(way, "highway", "") in NON_DRIVABLE_HIGHWAYS:
        return False
    return True


def _compute_bbox_2d(points_m: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Compute (minx, miny, maxx, maxy) for a list of points."""
    xs = [p[0] for p in points_m]
    ys = [p[1] for p in points_m]
    return min(xs), min(ys), max(xs), max(ys)


def is_point_in_water(px: float, py: float, waters: List) -> bool:
    """Check if point (px, py) is inside any water polygon or on a waterway with fast AABB rejection."""
    if not waters:
        return False
    for w in waters:
        # Pre-filter using bounding box if available
        bbox = getattr(w, "_bbox", None)
        if bbox is None and getattr(w, "points_m", None):
            bbox = _compute_bbox_2d(w.points_m)
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


def respawn_car(
    car: Car,
    ways: List,
    near_center: bool = False,
    bounds: Optional[Tuple[float, float, float, float]] = None,
    waters: Optional[List] = None,
) -> None:
    """Place the car on a drivable land road, avoiding water bodies, pedestrian paths, and seasonal ice roads."""
    if not ways:
        return

    # Filter for drivable roads (for cars) on land, excluding ice roads and pedestrian/cycle paths
    candidate_ways = [w for w in ways if is_car_road(w)]
    if not candidate_ways:
        candidate_ways = [w for w in ways if not getattr(w, "is_ice_road", False)]
    if not candidate_ways:
        candidate_ways = ways

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

    # Pick the first road that is not on water (lazily checking without scanning all 30k+ roads)
    chosen_way = None
    for w in candidate_ways:
        if len(w.points_m) >= 2:
            mx = (w.points_m[0][0] + w.points_m[1][0]) / 2
            my = (w.points_m[0][1] + w.points_m[1][1]) / 2
            if not waters or not is_point_in_water(mx, my, waters):
                chosen_way = w
                break
        elif len(w.points_m) == 1:
            if not waters or not is_point_in_water(w.points_m[0][0], w.points_m[0][1], waters):
                chosen_way = w
                break

    w = chosen_way or (candidate_ways[0] if candidate_ways else ways[0])

    if len(w.points_m) >= 2:
        ax, ay = w.points_m[0]
        bx, by = w.points_m[1]
        car.x = (ax + bx) / 2
        car.y = (ay + by) / 2
        car.heading = math.atan2(by - ay, bx - ax)
    elif len(w.points_m) == 1:
        car.x, car.y = w.points_m[0]
        car.heading = 0.0
    car.speed = 0.0


def reset_trip(car: Car) -> None:
    """Reset the car's trip meter."""
    car.trip_m = 0.0


class SpatialWayGrid:
    """Spatial hash grid indexing road ways for fast O(1) road collision checks."""

    def __init__(self, cell_size: float = 200.0):
        self.cell_size = cell_size
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

    def is_point_on_road(self, px: float, py: float, car_roads_only: bool = False) -> bool:
        gx = int(px // self.cell_size)
        gy = int(py // self.cell_size)
        candidates = self.grid.get((gx, gy))
        if not candidates:
            return False

        for w in candidates:
            if car_roads_only and not is_car_road(w):
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
                    return True
        return False

    def is_on_road(self, car: Car, car_roads_only: bool = False) -> bool:
        return self.is_point_on_road(car.x, car.y, car_roads_only=car_roads_only)


def is_point_on_road(
    px: float,
    py: float,
    ways: Optional[List] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
    car_roads_only: bool = False,
) -> bool:
    """Check if point (px, py) is on a road (optionally restricted to car roads only)."""
    if spatial_grid is not None:
        return spatial_grid.is_point_on_road(px, py, car_roads_only=car_roads_only)

    if ways is None:
        return False

    attached_grid = getattr(ways, "_spatial_grid", None)
    if attached_grid is not None:
        return attached_grid.is_point_on_road(px, py, car_roads_only=car_roads_only)

    for w in ways:
        if car_roads_only and not is_car_road(w):
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


def is_on_road(
    car: Car,
    ways: Optional[List] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
    car_roads_only: bool = False,
) -> bool:
    """Check proximity using spatial grid or dist_point_to_segment and way half-widths."""
    return is_point_on_road(car.x, car.y, ways=ways, spatial_grid=spatial_grid, car_roads_only=car_roads_only)


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
) -> bool:
    """Update car speed, heading, and position.

    When block_offroad is True and road data is provided, restricts motion to drivable
    car roads only, blocking movement if the vehicle attempts to leave the road.
    Returns True if vehicle movement was blocked against the road boundary.
    """
    if throttle > 0:
        car.speed += ACCEL * dt
    elif brake > 0:
        car.speed -= BRAKE * dt
    else:
        # friction slows towards 0
        if car.speed > 0:
            car.speed = max(0.0, car.speed - FRICTION * dt)
        else:
            car.speed = min(0.0, car.speed + FRICTION * dt)

    car.speed = clamp(car.speed, -10.0, MAX_SPEED)

    # steer: positive -> turn left (counter-clockwise), negative -> turn right
    steer = steer_left - steer_right
    steer_effective = STEER_RATE / (1.0 + abs(car.speed) * STEER_SPEED_FACTOR)
    car.heading += steer * steer_effective * dt * (1.0 if car.speed >= 0 else -1.0)

    dx = math.cos(car.heading) * car.speed * dt
    dy = math.sin(car.heading) * car.speed * dt
    target_x = car.x + dx
    target_y = car.y + dy

    blocked = False
    has_road_data = (spatial_grid is not None) or (ways is not None and len(ways) > 0)

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
            elif slide_y and not slide_x and abs(dy) > 1e-4:
                car.y = target_y
                dist = abs(dy)
                car.speed = car.speed * abs(math.sin(car.heading))
                blocked = True
            else:
                # Fully blocked against road edge
                blocked = True
                car.speed = 0.0
                dist = 0.0
    else:
        car.x = target_x
        car.y = target_y
        dist = math.hypot(dx, dy)

    # Accumulate trip and odometer distances based on speed magnitude
    car.trip_m += dist
    car.odometer_m += dist
    return blocked
