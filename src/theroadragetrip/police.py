"""Hidden police speed cameras."""

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .osm import TaxiStop, Way
from .physics import connected_drivable_ways


@dataclass(frozen=True)
class SpeedCamera:
    x: float
    y: float
    heading: float
    speed_limit_kmh: int
    way_id: int


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
) -> List[SpeedCamera]:
    """Place cameras at taxi stops, then fill remaining network-based slots."""
    candidates = [way for way in ways if way.is_drivable and len(way.points_m) >= 2]
    if not candidates:
        return []
    target_count = max(camera_count(ways, city_name), len(taxi_stops or []))
    target_count = min(20, target_count)
    rng = random.Random(repr(bounds))
    result: List[SpeedCamera] = []

    for stop in taxi_stops or []:
        if len(result) >= target_count:
            break
        nearest = min(
            ((way, start, end) for way in candidates for start, end in zip(way.points_m, way.points_m[1:])),
            key=lambda item: _distance_to_segment(stop.x, stop.y, item[1], item[2]),
        )
        way, start, end = nearest
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        segment_length_squared = dx * dx + dy * dy
        ratio = max(0.0, min(1.0, ((stop.x - start[0]) * dx + (stop.y - start[1]) * dy) / segment_length_squared))
        road_x = start[0] + ratio * dx
        road_y = start[1] + ratio * dy
        side = (stop.x - road_x) * -dy + (stop.y - road_y) * dx
        side_sign = 1.0 if side >= 0.0 else -1.0
        offset_x = side_sign * -dy / math.sqrt(segment_length_squared) * 4.5
        offset_y = side_sign * dx / math.sqrt(segment_length_squared) * 4.5
        result.append(SpeedCamera(road_x + offset_x, road_y + offset_y, math.atan2(dy, dx), way.speed_limit_kmh, len(result)))

    rng.shuffle(candidates)
    for way in candidates:
        if len(result) >= target_count:
            break
        segment_index = rng.randrange(len(way.points_m) - 1)
        start = way.points_m[segment_index]
        end = way.points_m[segment_index + 1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        segment_length = math.hypot(dx, dy)
        if segment_length < 30.0:
            continue
        ratio = rng.uniform(0.25, 0.75)
        result.append(SpeedCamera(
            start[0] + dx * ratio,
            start[1] + dy * ratio,
            math.atan2(dy, dx),
            way.speed_limit_kmh,
            len(result),
        ))
    return result


def _distance_to_segment(x: float, y: float, start: Tuple[float, float], end: Tuple[float, float]) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    ratio = 0.0 if length_squared == 0.0 else max(0.0, min(1.0, ((x - start[0]) * dx + (y - start[1]) * dy) / length_squared))
    return math.hypot(x - (start[0] + ratio * dx), y - (start[1] + ratio * dy))


def camera_sees_car(camera: SpeedCamera, car_x: float, car_y: float, heading: float) -> bool:
    """Return true while a car approaches from the camera's 50-meter viewing direction."""
    dx = car_x - camera.x
    dy = car_y - camera.y
    forward = dx * math.cos(camera.heading) + dy * math.sin(camera.heading)
    lateral = abs(dx * -math.sin(camera.heading) + dy * math.cos(camera.heading))
    heading_error = abs((heading - camera.heading + math.pi) % (2 * math.pi) - math.pi)
    return -50.0 <= forward <= 0.0 and lateral <= 8.0 and heading_error <= math.radians(60.0)