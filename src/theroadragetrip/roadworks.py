import math
import random
import logging
from dataclasses import dataclass
from typing import List, Tuple

from .osm import TrafficLight, Way

logger = logging.getLogger(__name__)


@dataclass
class Roadwork:
    way: Way
    start_m: float
    end_m: float
    lane_closed: bool
    start: Tuple[float, float]
    end: Tuple[float, float]

    def contains(self, x: float, y: float, margin_m: float = 0.0) -> bool:
        """Return whether a point lies inside this work zone along the road."""
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        length_sq = dx * dx + dy * dy
        if length_sq <= 0.0:
            return False
        progress = ((x - self.start[0]) * dx + (y - self.start[1]) * dy) / length_sq
        lateral = abs((x - self.start[0]) * dy - (y - self.start[1]) * dx) / math.sqrt(length_sq)
        return -margin_m <= progress * math.sqrt(length_sq) <= math.sqrt(length_sq) + margin_m and lateral <= getattr(self.way, "half_width_m", 4.0)


def _way_length(way: Way) -> float:
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(way.points_m, way.points_m[1:])
    )


def _point_at(way: Way, distance_m: float) -> Tuple[float, float]:
    remaining = distance_m
    for start, end in zip(way.points_m, way.points_m[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        segment_length = math.hypot(dx, dy)
        if segment_length >= remaining:
            fraction = remaining / max(0.001, segment_length)
            return start[0] + dx * fraction, start[1] + dy * fraction
        remaining -= segment_length
    return way.points_m[-1]


def create_roadworks(ways: List[Way], count: int = 3) -> Tuple[List[Roadwork], List[TrafficLight]]:
    candidates = [way for way in ways if way.is_drivable and _way_length(way) >= 90.0]
    random.shuffle(candidates)
    roadworks: List[Roadwork] = []
    traffic_lights: List[TrafficLight] = []
    for way in candidates[:max(0, count)]:
        length = _way_length(way)
        start_m = random.uniform(20.0, max(20.0, length - 60.0))
        end_m = min(length - 20.0, start_m + random.uniform(25.0, 55.0))
        start = _point_at(way, start_m)
        end = _point_at(way, end_m)
        lane_closed = random.random() >= 0.35
        work = Roadwork(way, start_m, end_m, lane_closed, start, end)
        roadworks.append(work)
        logger.info(
            "Roadwork generated: osm_way_id=%s start=(%.1f, %.1f) end=(%.1f, %.1f) "
            "length=%.1fm closure=%s",
            way.osm_id,
            start[0],
            start[1],
            end[0],
            end[1],
            end_m - start_m,
            "one-lane" if lane_closed else "full-road",
        )
        if lane_closed:
            angle = math.atan2(end[1] - start[1], end[0] - start[0])
            traffic_lights.extend([
                TrafficLight(start[0], start[1], offset=0.0, direction_angle=angle),
                TrafficLight(end[0], end[1], offset=8.0, direction_angle=angle),
            ])
    return roadworks, traffic_lights