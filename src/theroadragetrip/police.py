"""Hidden police speed cameras."""

import math
import random
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .geo import angle_diff
from .osm import TaxiStop, Way
from .physics import connected_drivable_ways

logger = logging.getLogger(__name__)

SPEED_CAMERA_HIGHWAYS = {"motorway", "trunk", "primary", "secondary", "tertiary"}


@dataclass(frozen=True)
class SpeedCamera:
    x: float
    y: float
    heading: float
    speed_limit_kmh: int
    way_id: Optional[int]
    road_offset_m: float = 0.0  # pole to watched road centre, positive to the camera's left
    road_half_width_m: float = 8.0
    layer: int = 0
    map_level: int = 0


def camera_count(ways: List[Way], city_name: Optional[str] = None) -> int:
    """Scale cameras from one to twenty; Helsinki is the maximum case."""
    if city_name and city_name.casefold() == "helsinki":
        return 20
    road_count = len(connected_drivable_ways(ways))
    return max(1, min(20, round(road_count / 10)))


def place_speed_cameras(
    ways: List[Way],
    bounds: Tuple[float, float, float, float],
    city_name: Optional[str] = None,
    taxi_stops: Optional[List[TaxiStop]] = None,
    seed: Optional[int] = None,
) -> List[SpeedCamera]:
    """Place directional cameras across the connected road network."""
    candidates = [
        way for way in ways
        if way.is_drivable and way.highway in SPEED_CAMERA_HIGHWAYS and len(way.points_m) >= 2
    ]
    if not candidates:
        return []
    target_count = camera_count(ways, city_name)
    rng = random.Random(repr(bounds) if seed is None else seed)
    result: List[SpeedCamera] = []

    rng.shuffle(candidates)
    for way in candidates:
        if len(result) >= target_count:
            break
        segment_index = rng.randrange(len(way.points_m) - 1)
        start = way.points_m[segment_index]
        end = way.points_m[segment_index + 1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if way.oneway == -1:
            start, end = end, start
            dx, dy = -dx, -dy
        segment_length = math.hypot(dx, dy)
        if segment_length < 30.0:
            continue
        ratio = rng.uniform(0.25, 0.75)
        right_offset = getattr(way, "half_width_m", 4.0) + 1.0
        result.append(SpeedCamera(
            start[0] + dx * ratio + dy / segment_length * right_offset,
            start[1] + dy * ratio - dx / segment_length * right_offset,
            math.atan2(dy, dx),
            way.speed_limit_kmh,
            way.osm_id,
            road_offset_m=right_offset,
            road_half_width_m=way.half_width_m,
            layer=getattr(way, "layer", 0),
            map_level=getattr(way, "map_level", None) or 0,
        ))
    for index, camera in enumerate(result, start=1):
        logger.info(
            "Speed camera %d placed at x=%.1f y=%.1f heading=%.1f deg limit=%d km/h osm_way_id=%s",
            index,
            camera.x,
            camera.y,
            math.degrees(camera.heading),
            camera.speed_limit_kmh,
            camera.way_id,
        )
    return result


def camera_sees_car(camera: SpeedCamera, car_x: float, car_y: float, heading: float,
                    previous_position=None) -> bool:
    """Return true while a car approaches from the camera's 50-meter viewing direction."""
    dx = car_x - camera.x
    dy = car_y - camera.y
    forward = dx * math.cos(camera.heading) + dy * math.sin(camera.heading)
    lateral = dx * -math.sin(camera.heading) + dy * math.cos(camera.heading) - camera.road_offset_m
    heading_error = abs(angle_diff(heading, camera.heading))
    if heading_error > math.radians(60.0):
        return False
    if previous_position is None:
        return -50.0 <= forward <= 0.0 and abs(lateral) <= camera.road_half_width_m
    # Clip this tick's movement against the watched road rectangle: even a
    # very fast car must not jump over the entire zone between observations.
    px, py = previous_position[0] - camera.x, previous_position[1] - camera.y
    old_forward = px * math.cos(camera.heading) + py * math.sin(camera.heading)
    old_lateral = px * -math.sin(camera.heading) + py * math.cos(camera.heading) - camera.road_offset_m
    enter, leave = 0.0, 1.0
    for a, b, low, high in ((old_forward, forward, -50.0, 0.0),
                            (old_lateral, lateral, -camera.road_half_width_m, camera.road_half_width_m)):
        if abs(b - a) < 1e-9:
            if not low <= a <= high:
                return False
            continue
        t1, t2 = (low - a) / (b - a), (high - a) / (b - a)
        enter, leave = max(enter, min(t1, t2)), min(leave, max(t1, t2))
        if enter > leave:
            return False
    return True
