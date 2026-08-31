"""Hidden police speed cameras."""

import math
import random
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .geo import point_in_polygon, segments_intersect
from .osm import Building, TaxiStop, Way
from .physics import Car, connected_drivable_ways
from .traffic import NPCCar, TrafficManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeedCamera:
    x: float
    y: float
    heading: float
    speed_limit_kmh: int
    way_id: Optional[int]


class PoliceManager:
    """Manage patrol cars that pursue and stop a speeding taxi."""

    def __init__(
        self,
        traffic: TrafficManager,
        x: float,
        y: float,
        count: int = 1,
        buildings: Optional[List[Building]] = None,
        building_grid=None,
    ):
        self.buildings = buildings or []
        self.building_grid = building_grid
        self.cars: List[NPCCar] = []
        for _ in range(count):
            npc = traffic.spawn_npc(x, y)
            if npc is None:
                break
            npc.is_police = True
            npc.is_taxi = False
            npc.vehicle_type = "car"
            npc.color = (235, 235, 240)
            npc.speed = 0.0
            npc.target_speed = 0.0
            self.cars.append(npc)

    def update(self, taxi: Car, way: Optional[Way], dt: float) -> bool:
        """Pursue a speeding taxi; return true while the taxi must remain stopped."""
        for police in self.cars:
            if police.scared_timer > 0.0:
                police.scared_timer = max(0.0, police.scared_timer - dt)
                police.speed = 0.0
                continue
        speeding = (
            way is not None
            and abs(taxi.speed) * 3.6 > way.speed_limit_kmh + 10.0
        )
        active = next(
            (
                car for car in self.cars
                if not car.pursuit_cancelled
                and car.scared_timer <= 0.0
                and (car.pursuing or not car.penalty_given)
            ),
            None,
        )
        can_see_taxi = (
            active is not None
            and math.hypot(active.x - taxi.x, active.y - taxi.y) <= 90.0
            and _has_line_of_sight(
                active.x, active.y, taxi.x, taxi.y, self.buildings, self.building_grid
            )
        )
        if active is not None and speeding and can_see_taxi and not active.stopped and not active.pursuing:
            active.pursuing = True
            relative_forward = (
                (active.x - taxi.x) * math.cos(taxi.heading)
                + (active.y - taxi.y) * math.sin(taxi.heading)
            )
            heading_error = abs((active.heading - taxi.heading + math.pi) % (2.0 * math.pi) - math.pi)
            active.pursuit_phase = "yielding" if relative_forward > 0.0 and heading_error > math.pi / 2.0 else "behind"
        for police in self.cars:
            if not police.pursuing:
                continue
            if police.penalty_given:
                police.speed = 0.0
                continue
            if police.stopped:
                if math.hypot(police.x - taxi.x, police.y - taxi.y) > 8.0:
                    police.stopped = False
                else:
                    return True

            relative_forward = (
                (police.x - taxi.x) * math.cos(taxi.heading)
                + (police.y - taxi.y) * math.sin(taxi.heading)
            )
            if police.pursuit_phase == "yielding":
                police.speed = 0.0
                if relative_forward <= -8.0:
                    police.pursuit_phase = "behind"
                    police.heading = taxi.heading
                    police.speed = 0.0
                    continue
                else:
                    continue

            if police.pursuit_phase == "passing" and relative_forward >= 6.0:
                police.pursuit_phase = "behind"

            behind_distance = 5.0
            longitudinal = -behind_distance
            target_x = taxi.x + math.cos(taxi.heading) * longitudinal + math.sin(taxi.heading) * 3.5
            target_y = taxi.y + math.sin(taxi.heading) * longitudinal - math.cos(taxi.heading) * 3.5
            dx = target_x - police.x
            dy = target_y - police.y
            distance = math.hypot(dx, dy)
            if not _has_line_of_sight(
                police.x, police.y, target_x, target_y, self.buildings, self.building_grid
            ):
                police.speed = 0.0
                continue
            if distance <= 2.0:
                police.x, police.y = target_x, target_y
                police.heading = taxi.heading
                police.speed = 0.0
                police.stopped = True
                return True
            police.heading = math.atan2(dy, dx)
            police.speed = min(30.0, max(8.0, distance * 2.0))
            step = min(distance, police.speed * dt)
            police.x += dx / distance * step
            police.y += dy / distance * step
        return False

    def scare(self) -> bool:
        """Make an active patrol stop and turn away after a rage shout."""
        interrupted = False
        for police in self.cars:
            if police.pursuing and not police.penalty_given:
                police.pursuing = False
                police.stopped = False
                police.scared_timer = 3.0
                police.pursuit_cancelled = True
                police.heading = (police.heading + math.pi) % (2.0 * math.pi)
                police.speed = 0.0
                interrupted = True
        if interrupted:
            logger.info("Police pursuit interrupted by rage shout")
        return interrupted

    def collect_penalty(self, taxi: Car, way: Optional[Way], penalty: int = 300) -> bool:
        """Mark a completed stop and return whether a new penalty should be issued."""
        for police in self.cars:
            if police.stopped and not police.penalty_given:
                police.penalty_given = True
                return True
        return False


def _has_line_of_sight(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    buildings: List[Building],
    building_grid=None,
) -> bool:
    """Return false when a building footprint blocks the view or direct path."""
    if building_grid is not None:
        margin = 2.0
        candidate_buildings = building_grid.ways_in_rect(
            min(start_x, end_x) - margin,
            min(start_y, end_y) - margin,
            max(start_x, end_x) + margin,
            max(start_y, end_y) + margin,
        )
    else:
        candidate_buildings = buildings
    for building in candidate_buildings:
        polygon = building.points_m
        if len(polygon) < 3:
            continue
        if point_in_polygon(start_x, start_y, polygon) or point_in_polygon(end_x, end_y, polygon):
            return False
        if any(
            segments_intersect(
                (start_x, start_y),
                (end_x, end_y),
                edge_start,
                edge_end,
            )
            for edge_start, edge_end in zip(polygon, polygon[1:] + polygon[:1])
        ):
            return False
    return True


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
    candidates = [way for way in ways if way.is_drivable and len(way.points_m) >= 2]
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