import collections
import concurrent.futures
from collections import defaultdict
import json
import logging
import math
import multiprocessing
import os
import random
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from .geo import dist_point_to_segment, point_in_polygon

logger = logging.getLogger(__name__)
CACHE_VERSION = "v0.6.2beta4"

# Top 10 cities of Finland by population with center coordinates (lat, lon)
CITY_CENTERS: Dict[str, Tuple[float, float]] = {
    "Helsinki": (60.169525, 24.935446),
    "Espoo": (60.205000, 24.652000),
    "Tampere": (61.499113, 23.787117),
    "Vantaa": (60.294000, 25.041000),
    "Oulu": (65.012000, 25.468000),
    "Turku": (60.451483, 22.268686),
    "Jyväskylä": (62.241470, 25.720880),
    "Kuopio": (62.892382, 27.677028),
    "Lahti": (60.982674, 25.661509),
    "Sysmä": (61.502271, 25.680613),
}


def bbox_from_center(lat: float, lon: float, size_km: float = 4.0) -> Tuple[float, float, float, float]:
    """Calculate (south, west, north, east) bbox around a center coordinate of size_km x size_km."""
    half_size_km = size_km / 2.0
    # 1 deg latitude is approx 111.0 km
    dlat = half_size_km / 111.0
    # 1 deg longitude varies with latitude
    dlon = half_size_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return (
        round(lat - dlat, 6),
        round(lon - dlon, 6),
        round(lat + dlat, 6),
        round(lon + dlon, 6),
    )


# Bounding box presets: south, west, north, east (lat/lon)
# Generate presets for all top 10 cities (4x4 km area) while preserving lowercase lookups
BBOX_PRESETS: Dict[str, Tuple[float, float, float, float]] = {
    name.lower(): bbox_from_center(lat, lon, size_km=4.0)
    for name, (lat, lon) in CITY_CENTERS.items()
}
DEFAULT_BBOX = BBOX_PRESETS["oulu"]

# Road drawing thickness (in meters, will be scaled)
DEFAULT_ROAD_HALF_WIDTH_M = 3.0

# Simple widths by highway type (half-width meters per direction-ish)
HIGHWAY_HALF_WIDTH = {
    "motorway": 7.0,
    "trunk": 6.5,
    "primary": 6.0,
    "secondary": 5.5,
    "tertiary": 5.0,
    "unclassified": 4.5,
    "residential": 4.5,
    "living_street": 4.0,
    "busway": 4.0,
    "service": 3.5,
    "track": 2.0,
    "path": 1.2,
    "footway": 1.2,
    "cycleway": 1.5,
}

# Standard Finnish default speed limits in km/h by highway type
# - Motorway / moottoritie: 100 or 120 km/h (default 100 km/h general baseline)
# - Trunk / moottoriliikennetie: 80 or 100 km/h
# - Primary / kantatiet & valtatiet: 80 km/h
# - Secondary / seututiet: 80 km/h (or 60 km/h near populated areas)
# - Tertiary / yhdystiet: 60 km/h
# - Urban unclassified / connecting: 50 km/h
# - Residential / taajama-alue: 40 km/h (or 30 km/h)
# - Living street / pihamaa / kävelykatu / pihatie: 20 km/h
# - Service road / tonttiliittymä / pihatie: 30 km/h
# - Busway: 50 km/h
DEFAULT_SPEED_LIMITS_KMH = {
    "motorway": 100,
    "trunk": 80,
    "primary": 80,
    "secondary": 80,
    "tertiary": 60,
    "unclassified": 50,
    "residential": 40,
    "living_street": 20,
    "busway": 50,
    "service": 30,
    "track": 30,
    "path": 20,
    "footway": 20,
    "cycleway": 20,
}


def parse_speed_limit_kmh(maxspeed_tag: Optional[str], highway_type: str) -> int:
    """Parse OSM maxspeed tag into integer km/h with Finnish statutory fallbacks."""
    if maxspeed_tag:
        tag_str = str(maxspeed_tag).strip().lower()
        if tag_str.isdigit():
            return int(tag_str)
        # Handle formats like "50 km/h" or "FI:urban" / "FI:rural"
        if " " in tag_str:
            num_part = tag_str.split()[0]
            if num_part.isdigit():
                return int(num_part)
        if "urban" in tag_str:
            return 50
        if "rural" in tag_str:
            return 80
        if "motorway" in tag_str:
            return 100
        if "living_street" in tag_str:
            return 20

    return DEFAULT_SPEED_LIMITS_KMH.get(highway_type, 50)


DEFAULT_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

OVERPASS_HEADERS = {
    "User-Agent": "TheRoadRageTrip/0.0.1 (https://github.com/theroadragetrip; educational driving game poc)"
}


def configure_user_agent(user_agent_id: str) -> None:
    """Attach the persistent first-run identity to Overpass requests."""
    OVERPASS_HEADERS["User-Agent"] = (
        "TheRoadRageTrip/0.0.1 "
        f"(https://github.com/theroadragetrip; educational driving game poc; id={user_agent_id})"
    )

def _default_cache_dir() -> str:
    if sys.platform.startswith("win"):
        data_dir = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    else:
        data_dir = os.getenv("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(data_dir, "RoadRageTrip", "osm_cache")


CACHE_DIR = _default_cache_dir()
DEAD_ENDS_CACHE_FILE = os.path.join(CACHE_DIR, "dead_ends.json")


def load_dead_ends_cache() -> List[dict]:
    """Load cached dead-end / empty-tile fetch boundaries."""
    if not os.path.exists(DEAD_ENDS_CACHE_FILE):
        return []
    try:
        with open(DEAD_ENDS_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("dead_ends", [])
    except Exception as e:
        logger.warning("Failed to load dead-ends cache: %s", e)
        return []


def save_dead_end_to_cache(entry: dict) -> None:
    """Save a dead-end entry (coordinates, direction/bbox, reason) to cache file."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    dead_ends = load_dead_ends_cache()
    dead_ends.append(entry)
    try:
        with open(DEAD_ENDS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"version": CACHE_VERSION, "updated_at": time.time(), "dead_ends": dead_ends},
                f,
                indent=2,
            )
        logger.info("Saved dead-end road record to %s", DEAD_ENDS_CACHE_FILE)
    except Exception as e:
        logger.warning("Failed to save dead-end cache: %s", e)


def _snap_projected_bbox(
    bbox: Tuple[float, float, float, float], tile_size_m: float
) -> Tuple[float, float, float, float]:
    """Normalize auto-fetch bounds so nearby requests share one cache key."""
    step = max(1.0, tile_size_m)
    minx, miny, maxx, maxy = bbox
    return (
        math.floor(minx / step) * step,
        math.floor(miny / step) * step,
        math.ceil(maxx / step) * step,
        math.ceil(maxy / step) * step,
    )


def _map_object_key(obj) -> tuple:
    """Return a stable key for deduplicating overlapping auto-fetch results."""
    object_id = getattr(obj, "osm_id", None)
    if object_id is None:
        object_id = getattr(obj, "id", None)
    if object_id is not None:
        return (type(obj).__name__, "id", object_id)

    points = getattr(obj, "points_m", None)
    if points:
        bbox = getattr(obj, "bbox", None)
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
            shape = tuple(round(value, 1) for value in bbox)
        else:
            shape = tuple(round(value, 1) for point in (points[0], points[-1]) for value in point)
        return (type(obj).__name__, getattr(obj, "kind", None), getattr(obj, "name", None), shape, len(points))

    return (
        type(obj).__name__,
        getattr(obj, "name", None),
        getattr(obj, "kind", None),
        round(getattr(obj, "x", 0.0), 1),
        round(getattr(obj, "y", 0.0), 1),
    )


def _extend_unique(target: list, new_items: list) -> int:
    known = {_map_object_key(item) for item in target}
    unique_items = [item for item in new_items if _map_object_key(item) not in known]
    target.extend(unique_items)
    return len(unique_items)



@dataclass
class Way:
    points_m: List[Tuple[float, float]]
    highway: str
    half_width_m: float
    name: Optional[str] = None
    surface: Optional[str] = None
    lit: Optional[str] = None
    is_ice_road: bool = False
    is_drivable: bool = True
    is_drivable_surface: bool = False
    is_busway: bool = False
    oneway: int = 0  # 0: two-way, 1: forward direction, -1: backward direction
    lanes: int = 1  # number of lanes
    layer: int = 0  # OSM vertical layer / level (-5 to 5)
    is_bridge: bool = False
    is_tunnel: bool = False
    speed_limit_kmh: int = 50  # Finnish speed limit in km/h
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    osm_id: Optional[int] = None
    lanes_forward: Optional[int] = None
    lanes_backward: Optional[int] = None
    turn_lanes: Optional[str] = None
    segment_lengths: List[float] = field(default_factory=list, init=False, repr=False)
    segment_headings: List[float] = field(default_factory=list, init=False, repr=False)
    total_length_m: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        for start, end in zip(self.points_m, self.points_m[1:]):
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            self.segment_lengths.append(length)
            self.segment_headings.append(math.atan2(dy, dx) if length > 0.0 else 0.0)
            self.total_length_m += length


def _parking_surface_way(
    points_m: List[Tuple[float, float]],
    bbox: Tuple[float, float, float, float],
    name: Optional[str] = None,
    surface: Optional[str] = None,
) -> Way:
    """Create the collision surface corresponding to an OSM parking area."""
    return Way(
            points_m=points_m,
            highway="parking",
            half_width_m=0.0,
            name=name,
            surface=surface,
            is_drivable=True,
            is_drivable_surface=True,
            bbox=bbox,
    )


@dataclass
class Water:
    points_m: List[Tuple[float, float]]
    kind: str
    is_polygon: bool
    name: Optional[str] = None
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class Building:
    points_m: List[Tuple[float, float]]
    name: Optional[str] = None
    housenumber: Optional[str] = None
    street: Optional[str] = None
    height_m: float = 8.0
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    venue_type: Optional[str] = None
    center_m: Tuple[float, float] = (0.0, 0.0)
    texture_seed: float = 0.0
    entrances: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class ParkingSpace:
    points_m: List[Tuple[float, float]]
    bbox: Tuple[float, float, float, float]
    orientation: float = 0.0
    osm_id: Optional[int] = None
    occupied: bool = False
    reserved: bool = False
    vehicle_id: Optional[int] = None
    reserved_by_pedestrian_id: Optional[int] = None

    def __post_init__(self) -> None:
        if len(self.points_m) < 2 or self.orientation != 0.0:
            return
        longest_edge = max(
            zip(self.points_m, self.points_m[1:] + self.points_m[:1]),
            key=lambda edge: (edge[1][0] - edge[0][0]) ** 2 + (edge[1][1] - edge[0][1]) ** 2,
        )
        self.orientation = math.atan2(
            longest_edge[1][1] - longest_edge[0][1],
            longest_edge[1][0] - longest_edge[0][0],
        )


@dataclass
class Scenery:
    points_m: List[Tuple[float, float]]
    kind: str
    name: Optional[str] = None
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    trees: List[Tuple[float, float]] = field(default_factory=list)
    tree_variations: List[float] = field(default_factory=list)


def _building_height(tags: Dict[str, Any], points: List[Tuple[float, float]]) -> float:
    """Return OSM height, level-derived height, or a footprint-based default."""
    raw_height = tags.get("height")
    if raw_height:
        try:
            height = float(str(raw_height).lower().replace("m", "").strip())
            if height > 0:
                return max(3.0, min(height, 120.0))
        except (TypeError, ValueError):
            pass

    raw_levels = tags.get("building:levels") or tags.get("levels")
    if raw_levels:
        try:
            levels = float(raw_levels)
            if levels > 0:
                return max(3.0, min(3.2 * levels + 1.5, 120.0))
        except (TypeError, ValueError):
            pass

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    footprint_scale = math.sqrt(max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys))))
    return min(24.0, 5.0 + footprint_scale * 0.18)


@dataclass
class SignalGroup:
    """Logical signal controlling one or more physical traffic lights."""
    approach_id: str
    allowed_movements: frozenset[str] = frozenset({"straight", "right"})
    phase_id: int = 0
    cycle_time: float = 16.0
    offset: float = 0.0
    state: str = "red"
    green_duration: float = 5.5
    yellow_duration: float = 1.5
    all_red_duration: float = 0.0
    red_duration: float = 7.5
    red_yellow_duration: float = 1.5

    def get_state(self, current_time: float) -> str:
        """Return the current state using the standard four-phase cycle."""
        phase_cycle = (
            self.green_duration + self.yellow_duration + self.all_red_duration
            + self.red_duration + self.red_yellow_duration
        )
        t = (current_time + self.offset) % (phase_cycle if phase_cycle > 0.0 else self.cycle_time)
        if t < self.green_duration:
            self.state = "green"
        elif t < self.green_duration + self.yellow_duration:
            self.state = "yellow"
        elif t < self.green_duration + self.yellow_duration + self.all_red_duration:
            self.state = "all-red"
        elif t < self.green_duration + self.yellow_duration + self.all_red_duration + self.red_duration:
            self.state = "red"
        else:
            self.state = "red+yellow"
        return self.state


@dataclass
class IntersectionApproach:
    """Incoming road direction and generated stop line for one intersection."""
    approach_id: str
    road_segments: List[Way]
    direction_vector: Tuple[float, float]
    stop_line: Tuple[Tuple[float, float], Tuple[float, float]]
    allowed_movements: frozenset[str] = frozenset({"straight", "right"})
    signal_group: Optional[SignalGroup] = None


@dataclass
class LogicalIntersection:
    """Cached signal-controlled intersection assembled from OSM evidence."""
    intersection_id: str
    center: Tuple[float, float]
    radius_m: float
    layer: int = 0
    approaches: List[IntersectionApproach] = field(default_factory=list)
    traffic_lights: List["TrafficLight"] = field(default_factory=list)


@dataclass
class TrafficLight:
    x: float
    y: float
    cycle_time: float = 16.0  # seconds per full cycle
    offset: float = 0.0  # phase offset in seconds (e.g. 0.0 for NS/Main, 8.0 for EW/Cross)
    layer: int = 0
    id: Optional[int] = None
    direction_angle: Optional[float] = None  # Road alignment heading in radians
    signal_group: Optional[SignalGroup] = None
    approach_id: Optional[str] = None
    allowed_movements: frozenset[str] = frozenset({"straight", "right"})
    renderable: bool = True

    def get_state(self, current_time: float) -> str:
        """Return a signal state following the Finnish sequence.

        In a 16s cycle:
        - 0.0s to 5.5s: Green (5.5s)
        - 5.5s to 7.0s: Yellow (1.5s transition before red)
        - 7.0s to 14.5s: Red (7.5s clearance / waiting)
        - 14.5s to 16.0s: Red+Yellow (1.5s preparation before green)
        Opposing phase has an 8.0s offset.
        """
        if self.signal_group is not None:
            return self.signal_group.get_state(current_time)
        return SignalGroup(
            approach_id=self.approach_id or str(self.id),
            cycle_time=self.cycle_time,
            offset=self.offset,
        ).get_state(current_time)


def deduplicate_traffic_lights(traffic_lights: List[TrafficLight]) -> List[TrafficLight]:
    """Keep at most one OSM signal for each approach of a junction."""
    kept: List[TrafficLight] = []
    junction_radius = 60.0
    approach_angle = math.radians(45.0)

    for light in traffic_lights:
        nearby = [
            existing for existing in kept
            if existing.layer == light.layer
            and math.hypot(existing.x - light.x, existing.y - light.y) <= junction_radius
        ]
        same_approach = next(
            (
                existing for existing in nearby
                if (
                    existing.direction_angle is None
                    and light.direction_angle is None
                    and math.hypot(existing.x - light.x, existing.y - light.y) <= 8.0
                )
                or (
                    existing.direction_angle is not None
                    and light.direction_angle is not None
                    and abs(
                    (existing.direction_angle - light.direction_angle + math.pi) % (2.0 * math.pi) - math.pi
                    ) <= approach_angle
                )
            ),
            None,
        )
        if same_approach is None:
            kept.append(light)

    return kept


def complete_traffic_light_approaches(traffic_lights: List[TrafficLight], ways: List) -> List[TrafficLight]:
    """Add missing approach signals around an already signalized junction."""
    completed = list(traffic_lights)
    junction_radius = 60.0
    approach_angle = math.radians(45.0)
    visited: set[int] = set()

    for index, light in enumerate(traffic_lights):
        if index in visited:
            continue
        component = []
        pending = [index]
        visited.add(index)
        while pending:
            current_index = pending.pop()
            current = traffic_lights[current_index]
            component.append(current)
            for other_index, other in enumerate(traffic_lights):
                if other_index in visited or other.layer != current.layer:
                    continue
                if math.hypot(current.x - other.x, current.y - other.y) <= junction_radius:
                    visited.add(other_index)
                    pending.append(other_index)

        layer = component[0].layer
        center_x = sum(signal.x for signal in component) / len(component)
        center_y = sum(signal.y for signal in component) / len(component)
        arm_angles: List[float] = []
        for way in ways:
            if getattr(way, "layer", 0) != layer or len(way.points_m) < 2:
                continue
            segment = min(
                zip(way.points_m, way.points_m[1:]),
                key=lambda pair: dist_point_to_segment(
                    center_x, center_y, pair[0][0], pair[0][1], pair[1][0], pair[1][1]
                ),
            )
            if dist_point_to_segment(center_x, center_y, *segment[0], *segment[1]) > 100.0:
                continue
            angle = math.atan2(segment[1][1] - segment[0][1], segment[1][0] - segment[0][0])
            for arm_angle in (angle, angle + math.pi):
                if all(
                    abs((arm_angle - existing + math.pi) % (2.0 * math.pi) - math.pi) > math.radians(25)
                    for existing in arm_angles
                ):
                    arm_angles.append(arm_angle)

        if len(arm_angles) < 3:
            continue
        for arm_index, arm_angle in enumerate(arm_angles):
            approach_direction = (arm_angle + math.pi) % (2.0 * math.pi)
            if any(
                signal.direction_angle is not None
                and abs(
                    (signal.direction_angle - approach_direction + math.pi) % (2.0 * math.pi) - math.pi
                ) <= approach_angle
                for signal in component
            ):
                continue
            signal_axis = arm_angle % math.pi
            signal_offset = 8.0 if (math.pi * 0.25) <= signal_axis < (math.pi * 0.75) else 0.0
            completed.append(
                TrafficLight(
                    x=center_x + math.cos(arm_angle) * 14.0,
                    y=center_y + math.sin(arm_angle) * 14.0,
                    cycle_time=16.0,
                    offset=signal_offset,
                    layer=layer,
                    id=-(index + 1) * 100 - arm_index,
                    direction_angle=approach_direction,
                )
            )

        for signal in component:
            if math.hypot(signal.x - center_x, signal.y - center_y) <= 10.0:
                signal.renderable = False

        grouped: dict[int, SignalGroup] = {}
        for signal in completed:
            if signal.layer != layer or math.hypot(signal.x - center_x, signal.y - center_y) > junction_radius:
                continue
            if signal.direction_angle is None:
                continue
            direction = signal.direction_angle % (2.0 * math.pi)
            axis = direction % math.pi
            direction_key = round(direction / math.radians(25.0))
            group = grouped.get(direction_key)
            if group is None:
                phase_id = 1 if math.sin(axis) ** 2 > 0.5 else 0
                group = SignalGroup(
                    approach_id=f"{layer}:{center_x:.0f}:{center_y:.0f}:{direction_key}",
                    phase_id=phase_id,
                    offset=8.0 if phase_id else 0.0,
                )
                grouped[direction_key] = group
            signal.signal_group = group
            signal.approach_id = group.approach_id
            signal.allowed_movements = group.allowed_movements

    return deduplicate_traffic_lights(completed)


def build_logical_intersections(
    traffic_lights: List[TrafficLight], ways: List[Way], cluster_radius_m: float = 60.0
) -> List[LogicalIntersection]:
    """Build immutable-ish intersection geometry once from signal OSM evidence."""
    intersections: List[LogicalIntersection] = []
    for signal in traffic_lights:
        if any(
            existing.layer == signal.layer
            and math.hypot(signal.x - existing.center[0], signal.y - existing.center[1]) <= cluster_radius_m
            for existing in intersections
        ):
            continue
        nearby_signals = [
            candidate for candidate in traffic_lights
            if candidate.layer == signal.layer
            and math.hypot(candidate.x - signal.x, candidate.y - signal.y) <= cluster_radius_m
        ]
        center = (
            sum(candidate.x for candidate in nearby_signals) / len(nearby_signals),
            sum(candidate.y for candidate in nearby_signals) / len(nearby_signals),
        )
        candidate_ways = [
            way for way in ways
            if getattr(way, "layer", 0) == signal.layer
            and len(way.points_m) >= 2
            and min(
                dist_point_to_segment(center[0], center[1], start[0], start[1], end[0], end[1])
                for start, end in zip(way.points_m, way.points_m[1:])
            ) <= 100.0
        ]
        approaches: List[IntersectionApproach] = []
        for way in candidate_ways:
            segment = min(
                zip(way.points_m, way.points_m[1:]),
                key=lambda pair: dist_point_to_segment(center[0], center[1], *pair[0], *pair[1]),
            )
            dx = segment[1][0] - segment[0][0]
            dy = segment[1][1] - segment[0][1]
            length = math.hypot(dx, dy)
            if length <= 1e-6:
                continue
            for direction_x, direction_y in ((dx / length, dy / length), (-dx / length, -dy / length)):
                approach_id = f"{signal.layer}:{center[0]:.0f}:{center[1]:.0f}:{round(math.atan2(direction_y, direction_x), 2)}"
                if any(approach.approach_id == approach_id for approach in approaches):
                    continue
                stop_center = (
                    center[0] - direction_x * 12.0,
                    center[1] - direction_y * 12.0,
                )
                half_width = getattr(way, "half_width_m", 4.0)
                stop_line = (
                    (stop_center[0] - direction_y * half_width, stop_center[1] + direction_x * half_width),
                    (stop_center[0] + direction_y * half_width, stop_center[1] - direction_x * half_width),
                )
                matching_signal = next(
                    (
                        candidate for candidate in nearby_signals
                        if candidate.direction_angle is not None
                        and abs((candidate.direction_angle - math.atan2(direction_y, direction_x) + math.pi) % (2.0 * math.pi) - math.pi) <= math.radians(45.0)
                    ),
                    None,
                )
                allowed_movements = frozenset({"straight", "right"})
                turn_lanes = getattr(way, "turn_lanes", None)
                if turn_lanes:
                    movement_names = {
                        movement
                        for lane in turn_lanes.split("|")
                        for movement in lane.split(";")
                        if movement in {"left", "through", "right", "slight_left", "slight_right"}
                    }
                    allowed_movements = frozenset(
                        {"straight" if movement == "through" else movement for movement in movement_names}
                    ) or allowed_movements
                elif getattr(way, "lanes", 1) >= 3:
                    allowed_movements = frozenset({"left", "straight", "right"})
                if matching_signal is not None and allowed_movements != matching_signal.allowed_movements:
                    matching_signal.allowed_movements = allowed_movements
                    if matching_signal.signal_group is not None:
                        matching_signal.signal_group.allowed_movements = allowed_movements
                approaches.append(
                    IntersectionApproach(
                        approach_id=approach_id,
                        road_segments=[way],
                        direction_vector=(direction_x, direction_y),
                        stop_line=stop_line,
                        allowed_movements=allowed_movements,
                        signal_group=matching_signal.signal_group if matching_signal else None,
                    )
                )
        if len(approaches) >= 3:
            intersections.append(
                LogicalIntersection(
                    intersection_id=f"{signal.layer}:{center[0]:.0f}:{center[1]:.0f}",
                    center=center,
                    radius_m=cluster_radius_m,
                    layer=signal.layer,
                    approaches=approaches,
                    traffic_lights=nearby_signals,
                )
            )
    return intersections


@dataclass
class Place:
    x: float
    y: float
    name: str
    kind: str  # suburb, neighbourhood, quarter, village, town, city


@dataclass
class Crossing:
    """Pedestrian crossing (suojatie)."""
    x: float
    y: float
    layer: int = 0
    id: Optional[int] = None
    crossing_type: str = "zebra"  # zebra, marked, uncontrolled, traffic_signals
    direction_angle: Optional[float] = None  # Road axis alignment angle in radians
    width_m: float = 3.5  # Width across road (length of crossing)
    length_m: float = 2.4  # Depth along road (stripe length)


@dataclass
class TaxiStop:
    x: float
    y: float
    id: Optional[int] = None


@dataclass
class BusStop:
    x: float
    y: float
    name: Optional[str] = None
    id: Optional[int] = None
    layer: int = 0
    shelter: bool = False


def load_local_sample(path: str = "sample_osm.json") -> Optional[List[dict]]:
    """Load a small local sample OSM 'elements' list for offline testing.

    Tries the provided path, package-relative samples, and `sample_osm_large.json`.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    bundle_dir = getattr(sys, "_MEIPASS", "")
    candidates = [
        path,
        os.path.join(root_dir, path),
        os.path.join(root_dir, "sample_osm.json"),
        "sample_osm_large.json",
        os.path.join(root_dir, "sample_osm_large.json"),
    ]
    if bundle_dir:
        candidates.extend([
            os.path.join(bundle_dir, path),
            os.path.join(bundle_dir, "sample_osm.json"),
            os.path.join(bundle_dir, "sample_osm_large.json"),
        ])
    for p in candidates:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("elements")
    return None


def _bbox_cache_path(bbox: Tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    # Keep tiny projection/float differences from creating duplicate cache files.
    precision = 5
    south = math.floor(south * 10**precision) / 10**precision
    west = math.floor(west * 10**precision) / 10**precision
    north = math.ceil(north * 10**precision) / 10**precision
    east = math.ceil(east * 10**precision) / 10**precision
    fname = f"bbox_{south}_{west}_{north}_{east}.json"
    stem, extension = os.path.splitext(fname)
    safe = stem.replace(".", "p").replace("-", "m") + extension
    return os.path.join(CACHE_DIR, safe)


def _bbox_from_cache_name(name: str) -> Optional[Tuple[float, float, float, float]]:
    if not name.startswith("bbox_"):
        return None
    try:
        suffix_length = 5 if name.endswith((".json", "pjson")) else 0
        if suffix_length == 0:
            return None
        values = name[5:-suffix_length].split("_")
        if len(values) != 4:
            return None
        return tuple(float(value.replace("p", ".").replace("m", "-")) for value in values)
    except ValueError:
        return None


def _legacy_bbox_cache_path(path: str) -> str:
    """Return the corrected .json path for a legacy pjson cache file."""
    if not path.endswith("pjson"):
        return path
    return path[:-5] + ".json"


def load_osm_cache(
    bbox: Tuple[float, float, float, float],
    point: Optional[Tuple[float, float]] = None,
) -> Optional[List[dict]]:
    requested_south, requested_west, requested_north, requested_east = bbox
    point_lat, point_lon = point if point is not None else (None, None)
    paths = [_bbox_cache_path(bbox)]
    if os.path.isdir(CACHE_DIR):
        paths.extend(
            entry.path
            for entry in os.scandir(CACHE_DIR)
            if entry.is_file() and entry.path != paths[0] and _bbox_from_cache_name(entry.name) is not None
        )

    for path in paths:
        try:
            cache_bbox = _bbox_from_cache_name(os.path.basename(path))
            if cache_bbox is not None:
                south, west, north, east = cache_bbox
                covers_point = (
                    point_lat is not None
                    and south <= point_lat <= north
                    and west <= point_lon <= east
                )
                covers_request = (
                    south <= requested_south
                    and west <= requested_west
                    and north >= requested_north
                    and east >= requested_east
                )
                if point is not None:
                    if not covers_point:
                        logger.info(
                            "Cache skip %s: point (%.6f, %.6f) outside bbox %s",
                            os.path.basename(path), point_lat, point_lon, cache_bbox,
                        )
                        continue
                elif not covers_request:
                    continue
                logger.info(
                    "Cache candidate %s: point=%s request_covered=%s",
                    os.path.basename(path), covers_point, covers_request,
                )
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read cache %s: %s", path, e)
            continue
        ts = d.get("fetched_at", 0)
        if d.get("version") != CACHE_VERSION:
            logger.info(
                "Cache skip %s: version %s != %s",
                os.path.basename(path),
                d.get("version", "missing"),
                CACHE_VERSION,
            )
            try:
                os.remove(path)
            except OSError as e:
                logger.warning("Failed to remove outdated cache %s: %s", path, e)
            continue
        ttl = int(os.getenv("OSM_CACHE_TTL", str(24 * 3600)))
        age = time.time() - ts
        if age <= ttl:
            if path.endswith("pjson"):
                migrated_path = _legacy_bbox_cache_path(path)
                try:
                    if not os.path.exists(migrated_path):
                        os.replace(path, migrated_path)
                        path = migrated_path
                        logger.info("Migrated OSM cache to %s", path)
                except OSError as e:
                    logger.warning("Failed to migrate legacy cache %s: %s", path, e)
            if cache_bbox is not None:
                logger.info(
                    "CACHE HIT: %s | bbox=%s | reason=%s | elements=%d | age=%.1fh",
                    path,
                    cache_bbox,
                    "car point" if point is not None else "request covered",
                    len(d.get("elements", [])),
                    age / 3600.0,
                )
            return d.get("elements")
        logger.info(
            "Cache skip %s: expired (age %.1fh, TTL %.1fh)",
            os.path.basename(path), age / 3600.0, ttl / 3600.0,
        )
    return None


def save_osm_cache(bbox: Tuple[float, float, float, float], elements: List[dict]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _bbox_cache_path(bbox)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": CACHE_VERSION, "fetched_at": time.time(), "elements": elements}, f)
        logger.info("Saved OSM cache to %s", path)
    except Exception as e:
        logger.warning("Failed to save cache %s: %s", path, e)


def clear_osm_cache() -> int:
    """Delete all files stored in the OSM cache directory."""
    if not os.path.isdir(CACHE_DIR):
        return 0
    removed = 0
    for entry in os.scandir(CACHE_DIR):
        try:
            if entry.is_dir():
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
            removed += 1
        except OSError as e:
            logger.warning("Failed to remove OSM cache entry %s: %s", entry.path, e)
    logger.info("Cleared OSM cache (%d entries)", removed)
    return removed


def has_outdated_osm_cache() -> bool:
    """Return whether the cache contains data from an older cache format."""
    if not os.path.isdir(CACHE_DIR):
        return False
    dead_ends_path = os.path.join(CACHE_DIR, "dead_ends.json")
    if os.path.isfile(dead_ends_path):
        try:
            with open(dead_ends_path, "r", encoding="utf-8") as f:
                if json.load(f).get("version") != CACHE_VERSION:
                    return True
        except (OSError, json.JSONDecodeError):
            return False
    for entry in os.scandir(CACHE_DIR):
        if not entry.is_file() or entry.path == dead_ends_path or _bbox_from_cache_name(entry.name) is None:
            continue
        try:
            with open(entry.path, "r", encoding="utf-8") as f:
                if json.load(f).get("version") != CACHE_VERSION:
                    return True
        except (OSError, json.JSONDecodeError):
            continue
    return False


def fetch_osm_ways(
    bbox: Tuple[float, float, float, float],
    endpoints: Optional[List[str]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    force_refresh: bool = False,
) -> List[dict]:
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:25];
    (
      node["highway"="traffic_signals"]({south},{west},{north},{east});
      node["highway"="crossing"]({south},{west},{north},{east});
      node["highway"="taxi_stop"]({south},{west},{north},{east});
    node["highway"="bus_stop"]({south},{west},{north},{east});
    node["public_transport"~"platform|stop_position"]({south},{west},{north},{east});
      node["amenity"="taxi"]({south},{west},{north},{east});
      node["crossing"]({south},{west},{north},{east});
    node["entrance"]({south},{west},{north},{east});
    node["amenity"="parking_space"]({south},{west},{north},{east});
      node["place"~"suburb|neighbourhood|quarter|village|town|city|hamlet"]({south},{west},{north},{east});
    node["name"]({south},{west},{north},{east});
      way["highway"]({south},{west},{north},{east});
    way["name"]({south},{west},{north},{east});
      way["natural"="water"]({south},{west},{north},{east});
    way["natural"="bay"]({south},{west},{north},{east});
    way["natural"="strait"]({south},{west},{north},{east});
      way["waterway"]({south},{west},{north},{east});
      way["landuse"="reservoir"]({south},{west},{north},{east});
      way["building"]({south},{west},{north},{east});
    way["amenity"="parking"]({south},{west},{north},{east});
    way["landuse"="parking"]({south},{west},{north},{east});
    way["amenity"="parking_space"]({south},{west},{north},{east});
      way["landuse"~"forest|grass|park|meadow|residential|commercial|industrial|recreation_ground"]({south},{west},{north},{east});
      way["leisure"~"park|garden|pitch|playground"]({south},{west},{north},{east});
      way["natural"~"wood|scrub|grass|sand|heath"]({south},{west},{north},{east});
      way["place"~"suburb|neighbourhood|quarter|village"]({south},{west},{north},{east});
      relation["natural"="water"]({south},{west},{north},{east});
    relation["natural"="bay"]({south},{west},{north},{east});
    relation["natural"="strait"]({south},{west},{north},{east});
      relation["landuse"="reservoir"]({south},{west},{north},{east});
      relation["building"]({south},{west},{north},{east});
    relation["amenity"="parking"]({south},{west},{north},{east});
    relation["landuse"="parking"]({south},{west},{north},{east});
      relation["leisure"="park"]({south},{west},{north},{east});
      relation["landuse"~"forest|grass|park|meadow"]({south},{west},{north},{east});
      relation["place"~"suburb|neighbourhood|quarter"]({south},{west},{north},{east});
    );
    out body;
    >;
    out skel qt;
    """

    if progress_callback:
        progress_callback(0.1, "Checking cache...")

    force_refresh = force_refresh or os.getenv("OVERPASS_FORCE_REFRESH", "0").lower() in ("1", "true", "yes")
    if not force_refresh:
        cached = load_osm_cache(bbox)
        if cached is not None:
            logger.info("Loaded OSM data from local cache")
            if progress_callback:
                progress_callback(0.5, f"Loaded {len(cached)} cached elements")
            return cached

    endpoints = endpoints or DEFAULT_OVERPASS_ENDPOINTS
    env_eps = os.getenv("OVERPASS_ENDPOINTS")
    if env_eps:
        endpoints = [e.strip() for e in env_eps.split(",") if e.strip()]
    last_err = None

    for ep in endpoints:
        for attempt in range(1, 4):
            try:
                if progress_callback:
                    progress_callback(0.25, f"Fetching scenery from {ep[:35]}...")
                r = requests.post(ep, data={"data": query}, headers=OVERPASS_HEADERS, timeout=60)
                if r.status_code >= 500:
                    last_err = Exception(f"{r.status_code} Server Error from {ep}")
                    time.sleep(2 ** (attempt - 1))
                    continue
                r.raise_for_status()
                if progress_callback:
                    progress_callback(0.5, "Parsing OSM payload...")
                data = r.json()
                els = data.get("elements", [])
                logger.info("Loaded OSM data from %s (%d elements)", ep, len(els))
                try:
                    save_osm_cache(bbox, els)
                except Exception:
                    pass
                if progress_callback:
                    progress_callback(0.6, f"Downloaded {len(els)} elements")
                return els
            except requests.exceptions.Timeout as e:
                last_err = e
                logger.warning("Timeout from %s (attempt %d)", ep, attempt)
                time.sleep(2 ** (attempt - 1))
                continue
            except requests.exceptions.ConnectionError as e:
                last_err = e
                logger.warning("Connection error to %s (attempt %d)", ep, attempt)
                time.sleep(2 ** (attempt - 1))
                continue
            except requests.exceptions.HTTPError as e:
                last_err = e
                status = getattr(e.response, "status_code", None)
                if status and 400 <= status < 500:
                    logger.warning("HTTP %s from %s; moving to next endpoint", status, ep)
                    break
                logger.warning("HTTP error from %s (attempt %d): %s", ep, attempt, e)
                time.sleep(2 ** (attempt - 1))
                continue
            except Exception as e:
                last_err = e
                logger.warning("Error when contacting %s: %s", ep, e)
                time.sleep(2 ** (attempt - 1))
                continue

    sample = load_local_sample()
    if sample:
        logger.info("Using local sample OSM data as fallback.")
        if progress_callback:
            progress_callback(0.5, f"Loaded {len(sample)} sample elements")
        return sample
    raise last_err or Exception("Failed to fetch OSM data from any endpoint or local sample.")


def _stitch_member_ways_into_rings(
    way_ids: List[int],
    ways_by_id: Dict[int, dict],
    process_node_ids_fn: Callable[[List[int]], Optional[List[Tuple[float, float]]]],
) -> List[Tuple[List[Tuple[float, float]], bool]]:
    """Stitch member ways into closed polygon rings or continuous linestrings in O(N) time.

    Returns a list of (points_m, is_closed) tuples.
    """
    segments: List[List[int]] = []
    for wid in way_ids:
        way_el = ways_by_id.get(wid)
        if way_el and way_el.get("nodes") and len(way_el["nodes"]) >= 2:
            segments.append(list(way_el["nodes"]))

    if not segments:
        return []

    node_to_segs = defaultdict(list)
    for seg_idx, nodes in enumerate(segments):
        node_to_segs[nodes[0]].append((seg_idx, True))
        node_to_segs[nodes[-1]].append((seg_idx, False))

    used = [False] * len(segments)
    rings: List[Tuple[List[Tuple[float, float]], bool]] = []

    for start_idx in range(len(segments)):
        if used[start_idx]:
            continue
        used[start_idx] = True
        chain = collections.deque(segments[start_idx])

        # Extend forward from chain[-1]
        while chain[0] != chain[-1]:
            end_node = chain[-1]
            found_next = False
            for seg_idx, is_start in node_to_segs[end_node]:
                if not used[seg_idx]:
                    used[seg_idx] = True
                    nodes = segments[seg_idx]
                    if is_start:
                        chain.extend(nodes[1:])
                    else:
                        chain.extend(reversed(nodes[:-1]))
                    found_next = True
                    break
            if not found_next:
                break

        # Extend backward from chain[0]
        while chain[0] != chain[-1]:
            start_node = chain[0]
            found_prev = False
            for seg_idx, is_start in node_to_segs[start_node]:
                if not used[seg_idx]:
                    used[seg_idx] = True
                    nodes = segments[seg_idx]
                    if is_start:
                        for n in nodes[1:]:
                            chain.appendleft(n)
                    else:
                        for n in reversed(nodes[:-1]):
                            chain.appendleft(n)
                    found_prev = True
                    break
            if not found_prev:
                break

        chain_list = list(chain)
        is_closed = len(chain_list) >= 4 and chain_list[0] == chain_list[-1]
        pts = process_node_ids_fn(chain_list)
        if pts and len(pts) >= 2:
            rings.append((pts, is_closed))

    return rings


class MapData(tuple):
    """Container tuple for build_ways results returning 6 elements for backward compatibility while providing traffic_lights and crossings via attributes and slicing."""

    def __new__(cls, ways, waters, buildings, sceneries, places, bounds, traffic_lights=None, crossings=None, taxi_stops=None, bus_stops=None, parking_spaces=None, logical_intersections=None):
        return super().__new__(cls, (ways, waters, buildings, sceneries, places, bounds))

    def __init__(self, ways, waters, buildings, sceneries, places, bounds, traffic_lights=None, crossings=None, taxi_stops=None, bus_stops=None, parking_spaces=None, logical_intersections=None):
        self.ways = ways
        self.waters = waters
        self.buildings = buildings
        self.sceneries = sceneries
        self.places = places
        self.bounds = bounds
        self.traffic_lights = traffic_lights if traffic_lights is not None else []
        self.crossings = crossings if crossings is not None else []
        self.taxi_stops = taxi_stops if taxi_stops is not None else []
        self.bus_stops = bus_stops if bus_stops is not None else []
        self.parking_spaces = parking_spaces if parking_spaces is not None else []
        self.logical_intersections = logical_intersections if logical_intersections is not None else []

    @property
    def traffic_signals(self):
        return self.traffic_lights


def plant_trees(sceneries: List[Scenery], ways: List[Way]) -> None:
    """Add deterministic tree centers to green areas while keeping them off roads."""
    tree_density = {
        "forest": 100.0,
        "wood": 100.0,
        "scrub": 250.0,
        "park": 1800.0,
        "garden": 1800.0,
    }
    for scenery in sceneries:
        kind = scenery.kind.lower()
        density = tree_density.get(kind)
        if density is None or len(scenery.points_m) < 3:
            continue
        minx, miny, maxx, maxy = scenery.bbox
        area = max(0.0, (maxx - minx) * (maxy - miny))
        target = min(80, max(1, int(area / density)))
        rng = random.Random(f"{round(minx)}:{round(miny)}:{kind}")
        road_candidates = [
            way for way in ways
            if getattr(way, "is_drivable", True)
            and way.bbox[2] >= minx - way.half_width_m - 3.0
            and way.bbox[0] <= maxx + way.half_width_m + 3.0
            and way.bbox[3] >= miny - way.half_width_m - 3.0
            and way.bbox[1] <= maxy + way.half_width_m + 3.0
        ]
        for _ in range(target * 5):
            if len(scenery.trees) >= target:
                break
            x = rng.uniform(minx, maxx)
            y = rng.uniform(miny, maxy)
            if not point_in_polygon(x, y, scenery.points_m):
                continue
            if any(
                dist_point_to_segment(x, y, p1[0], p1[1], p2[0], p2[1]) < way.half_width_m + 3.0
                for way in road_candidates
                for p1, p2 in zip(way.points_m, way.points_m[1:])
            ):
                continue
            scenery.trees.append((x, y))
            scenery.tree_variations.append(abs(math.sin(x * 12.9898 + y * 78.233)))


def build_ways(
    elements: List[dict],
    progress_callback: Optional[Callable[[float, str], None]] = None,
    include_bus_stops: bool = True,
) -> MapData:
    """Convert OSM elements to EPSG:3067 meters.

    Returns:
      - MapData (ways, waters, buildings, sceneries, places, (minx, miny, maxx, maxy))
        with .traffic_lights attribute, compatible with 6-tuple unpacking `ways, waters, buildings, sceneries, places, bounds = build_ways(...)`.
    """
    t_start = time.time()
    if progress_callback:
        progress_callback(0.65, "Indexing OSM elements...")

    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)

    node_ids_list: List[int] = []
    node_lons: List[float] = []
    node_lats: List[float] = []

    place_nodes_raw: List[Tuple[dict, int]] = []
    named_nodes_raw: List[Tuple[dict, int]] = []
    traffic_signals_raw: List[Tuple[dict, int]] = []
    crossings_raw: List[Tuple[dict, int]] = []
    taxi_stops_raw: List[Tuple[dict, int]] = []
    bus_stops_raw: List[Tuple[dict, int]] = []
    bus_platforms_raw: List[Tuple[dict, List[int], int]] = []
    entrance_node_ids: set[int] = set()
    ways_by_id: Dict[int, dict] = {}
    ways_raw: List[Tuple[dict, str, List[int]]] = []
    water_raw: List[Tuple[dict, List[int]]] = []
    building_raw: List[Tuple[dict, List[int]]] = []
    parking_space_raw: List[Tuple[dict, List[int], Optional[int]]] = []
    scenery_raw: List[Tuple[dict, List[int]]] = []
    named_ways_raw: List[Tuple[dict, List[int]]] = []
    parking_space_nodes_raw: List[Tuple[dict, int]] = []
    relations_raw: List[Tuple[dict, List[dict]]] = []

    for el in elements:
        el_type = el.get("type")
        if el_type == "node":
            nid = el["id"]
            node_ids_list.append(nid)
            node_lons.append(el["lon"])
            node_lats.append(el["lat"])
            tags = el.get("tags", {})
            if "place" in tags and "name" in tags:
                place_nodes_raw.append((tags, nid))
            elif "name" in tags:
                named_nodes_raw.append((tags, nid))
            if tags.get("highway") == "traffic_signals":
                traffic_signals_raw.append((tags, nid))
            if tags.get("highway") == "taxi_stop" or tags.get("amenity") == "taxi":
                taxi_stops_raw.append((tags, nid))
            if include_bus_stops and (tags.get("highway") == "bus_stop" or tags.get("public_transport") in ("platform", "stop_position")):
                bus_stops_raw.append((tags, nid))
            if "entrance" in tags:
                entrance_node_ids.add(nid)
            if tags.get("amenity") == "parking_space":
                parking_space_nodes_raw.append((tags, nid))
            if tags.get("highway") == "crossing" or tags.get("crossing") in ("zebra", "marked", "uncontrolled", "traffic_signals", "yes"):
                crossings_raw.append((tags, nid))
        elif el_type == "way":
            tags = el.get("tags", {})
            node_ids = el.get("nodes", [])
            way_id = el.get("id")
            if way_id is not None:
                ways_by_id[way_id] = el
            if len(node_ids) < 2:
                continue
            if include_bus_stops and tags.get("public_transport") == "platform":
                bus_platforms_raw.append((tags, node_ids, way_id))
            if "building" in tags:
                building_raw.append((tags, node_ids))
            elif tags.get("amenity") == "parking_space":
                parking_space_raw.append((tags, node_ids, way_id))
            elif tags.get("natural") in ("water", "bay", "strait") or ("waterway" in tags) or tags.get("landuse") == "reservoir":
                water_raw.append((tags, node_ids))
            elif tags.get("amenity") == "parking" or tags.get("landuse") == "parking":
                scenery_raw.append((tags, node_ids))
            elif "leisure" in tags or "landuse" in tags or tags.get("natural") in ("wood", "scrub", "grass", "sand", "heath"):
                scenery_raw.append((tags, node_ids))
            elif "highway" in tags:
                highway = tags.get("highway", "unclassified")
                ways_raw.append((tags, highway, node_ids, way_id))
            elif "name" in tags:
                named_ways_raw.append((tags, node_ids))
        elif el_type == "relation":
            tags = el.get("tags", {})
            if tags.get("type") == "multipolygon":
                members = el.get("members", [])
                relations_raw.append((tags, members))

    logger.info(
        "Parsed %d OSM elements: %d nodes, %d ways, %d relations",
        len(elements),
        len(node_ids_list),
        len(ways_by_id),
        len(relations_raw),
    )

    # Transform coordinates in batch
    nodes_m: Dict[int, Tuple[float, float]] = {}
    if node_ids_list:
        if progress_callback:
            progress_callback(0.70, f"Transforming {len(node_ids_list)} coordinates...")
        logger.info("Transforming %d node coordinates to EPSG:3067...", len(node_ids_list))

        try:
            xs, ys = transformer.transform(node_lons, node_lats)
            if hasattr(xs, "__len__") and len(xs) == len(node_ids_list):
                nodes_m = {nid: (x, y) for nid, x, y in zip(node_ids_list, xs, ys)}
            else:
                nodes_m = {
                    nid: transformer.transform(lon, lat)
                    for nid, lon, lat in zip(node_ids_list, node_lons, node_lats)
                }
        except Exception:
            nodes_m = {
                nid: transformer.transform(lon, lat)
                for nid, lon, lat in zip(node_ids_list, node_lons, node_lats)
            }

    t_transform = time.time() - t_start
    logger.info("Coordinate transformation finished in %.3fs (%d nodes)", t_transform, len(nodes_m))

    ways: List[Way] = []
    waters: List[Water] = []
    buildings: List[Building] = []
    sceneries: List[Scenery] = []
    places: List[Place] = []
    traffic_lights: List[TrafficLight] = []
    crossings: List[Crossing] = []
    taxi_stops: List[TaxiStop] = []
    bus_stops: List[BusStop] = []
    parking_spaces: List[ParkingSpace] = []

    minx = miny = float("inf")
    maxx = maxy = float("-inf")

    # Helper to convert node_ids to metric coordinates, calculate item bbox, and update global bounds
    def process_node_ids(
        node_ids: List[int],
    ) -> Tuple[Optional[List[Tuple[float, float]]], Tuple[float, float, float, float]]:
        pts = []
        iminx = iminy = float("inf")
        imaxx = imaxy = float("-inf")
        for nid in node_ids:
            pt = nodes_m.get(nid)
            if pt is None:
                return None, (0.0, 0.0, 0.0, 0.0)
            pts.append(pt)
            x, y = pt
            if x < iminx:
                iminx = x
            if x > imaxx:
                imaxx = x
            if y < iminy:
                iminy = y
            if y > imaxy:
                imaxy = y
        return pts, (iminx, iminy, imaxx, imaxy)

    # 1. Scenery polygons (parks, forests, grass)
    if progress_callback:
        progress_callback(0.78, f"Building scenery ({len(scenery_raw)} areas)...")
    for tags, node_ids in scenery_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 3:
            continue
        kind = (
            "parking"
            if tags.get("amenity") == "parking" or tags.get("landuse") == "parking"
            else tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "park"
        )
        name = tags.get("name")
        sceneries.append(Scenery(points_m=pts, kind=kind, name=name, bbox=ibbox))

    for tags, node_ids, parking_id in parking_space_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts:
            continue
        if len(pts) < 3:
            x, y = pts[0]
            half_width = 1.25
            half_length = 2.5
            pts = [
                (x - half_width, y - half_length),
                (x + half_width, y - half_length),
                (x + half_width, y + half_length),
                (x - half_width, y + half_length),
            ]
            ibbox = (x - half_width, y - half_length, x + half_width, y + half_length)
        parking_spaces.append(ParkingSpace(points_m=pts, bbox=ibbox, osm_id=parking_id))
    for tags, node_id in parking_space_nodes_raw:
        point = nodes_m.get(node_id)
        if point is None:
            continue
        x, y = point
        half_width = 1.25
        half_length = 2.5
        points = [
            (x - half_width, y - half_length),
            (x + half_width, y - half_length),
            (x + half_width, y + half_length),
            (x - half_width, y + half_length),
        ]
        parking_spaces.append(
            ParkingSpace(
                points_m=points,
                bbox=(x - half_width, y - half_length, x + half_width, y + half_length),
                osm_id=node_id,
            )
        )

    # 2. Water polygons and waterways
    if progress_callback:
        progress_callback(0.84, f"Building water features ({len(water_raw)} elements)...")
    for tags, node_ids in water_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 2:
            continue
        is_poly = pts[0] == pts[-1]
        kind = tags.get("natural") or tags.get("waterway") or tags.get("landuse") or "water"
        name = tags.get("name")
        waters.append(Water(points_m=pts, kind=kind, is_polygon=is_poly, name=name, bbox=ibbox))

    # 3. Buildings
    if progress_callback:
        progress_callback(0.90, f"Building structures ({len(building_raw)} buildings)...")
    for tags, node_ids in building_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 3:
            continue
        name = tags.get("name")
        housenumber = tags.get("addr:housenumber")
        street = tags.get("addr:street")
        center_x = sum(point[0] for point in pts) / len(pts)
        center_y = sum(point[1] for point in pts) / len(pts)
        entrances = [nodes_m[nid] for nid in node_ids if nid in entrance_node_ids]
        buildings.append(Building(
            points_m=pts,
            name=name,
            housenumber=housenumber,
            street=street,
            height_m=_building_height(tags, pts),
            bbox=ibbox,
            venue_type=tags.get("amenity"),
            center_m=(center_x, center_y),
            texture_seed=abs(math.sin(center_x * 0.013 + center_y * 0.017)),
            entrances=entrances,
        ))

    # 4. Roads (ways)
    if progress_callback:
        progress_callback(0.94, f"Building road network ({len(ways_raw)} ways)...")
    non_drivable_highways = {
        "footway",
        "path",
        "pedestrian",
        "cycleway",
        "steps",
        "bridleway",
        "corridor",
        "track",
    }
    for tags, highway, node_ids, way_id in ways_raw:
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 2:
            continue
        # Update road coverage bounds based specifically on drivable roads
        for px, py in pts:
            if px < minx:
                minx = px
            if px > maxx:
                maxx = px
            if py < miny:
                miny = py
            if py > maxy:
                maxy = py
        halfw = HIGHWAY_HALF_WIDTH.get(highway, DEFAULT_ROAD_HALF_WIDTH_M)
        name = tags.get("name") or tags.get("name:fi") or tags.get("name:en") or tags.get("official_name")
        ref_num = tags.get("ref")
        if not name and ref_num:
            # Check if road is a main Finnish valtatie / kantatie / seututie
            if ref_num.startswith("E") or highway in ("motorway", "trunk"):
                name = f"Valtatie {ref_num}"
            elif highway == "primary":
                name = f"Kantatie {ref_num}"
            elif highway in ("secondary", "tertiary"):
                name = f"Seututie {ref_num}"
            else:
                name = f"Yhdystie {ref_num}"
        is_ice = (
            tags.get("ice_road") in ("yes", "seasonal")
            or tags.get("winter_road") in ("yes", "seasonal")
            or tags.get("seasonal") in ("winter", "ice", "yes")
        )
        # Underground / parking garage detection
        # Filter out underground aisles, underground parking garages, or underground tunnel service roads
        parking_tag = tags.get("parking", "")
        parking_aisle = tags.get("service") == "parking_aisle"
        location_tag = tags.get("location", "")
        covered_tag = tags.get("covered", "")
        tunnel_tag = tags.get("tunnel", "")
        level_tag = tags.get("level", "")
        layer_tag = tags.get("layer", "")

        is_underground = (
            location_tag == "underground"
            or parking_tag in ("underground", "multi-storey", "sheds", "carports")
            or covered_tag in ("yes", "arcade")
            or tunnel_tag in ("yes", "building_passage")
        )
        if level_tag:
            try:
                # Negative floor levels (e.g. -1, -2) are underground
                if float(level_tag) < 0:
                    is_underground = True
            except ValueError:
                pass

        # Parse layer integer
        layer_val = 0
        if layer_tag:
            try:
                layer_val = int(layer_tag)
            except ValueError:
                pass
        elif tunnel_tag in ("yes", "building_passage"):
            layer_val = -1
        elif tags.get("bridge") in ("yes", "viaduct", "movable"):
            layer_val = 1

        if layer_val < 0:
            is_underground = True

        # If underground parking/service route, exclude from map
        if is_underground and (parking_aisle or highway in ("service", "track") or "parking" in tags):
            continue

        is_bridge = tags.get("bridge") in ("yes", "viaduct", "movable") or layer_val > 0
        is_tunnel = tunnel_tag in ("yes", "building_passage") or layer_val < 0

        # Check busways and public transport lanes (taxis are legally permitted to drive on bus lanes/busways)
        bus_tag = tags.get("bus")
        psv_tag = tags.get("psv")  # Public service vehicle
        taxi_tag = tags.get("taxi")
        lanes_bus = tags.get("lanes:bus") or tags.get("bus:lanes") or tags.get("lanes:psv")
        is_bus_route = (
            highway == "busway"
            or bus_tag in ("yes", "designated", "permissive", "only")
            or psv_tag in ("yes", "designated", "permissive", "only")
            or taxi_tag in ("yes", "designated", "permissive")
            or bool(lanes_bus)
        )

        # Check car access
        motorcar = tags.get("motorcar")
        vehicle = tags.get("vehicle")
        access = tags.get("access")

        # In Finland, living streets (pihatiet), service drives, and bus lanes are fully allowed for taxis
        if highway == "living_street":
            is_drivable = True
        elif is_bus_route:
            is_drivable = True
        elif taxi_tag in ("yes", "designated", "permissive"):
            is_drivable = True
        elif motorcar in ("no", "private") or vehicle in ("no", "private") or access in ("no", "private"):
            is_drivable = False
        elif motorcar in ("yes", "designated", "permissive"):
            is_drivable = True
        elif highway in non_drivable_highways:
            is_drivable = False
        else:
            is_drivable = True

        # Check oneway driving direction
        # oneway values in OSM: 'yes', '1', 'true', '-1', 'reverse', 'no'
        oneway_tag = str(tags.get("oneway", "")).lower()
        junction_tag = str(tags.get("junction", "")).lower()
        oneway_dir = 0
        if oneway_tag in ("yes", "1", "true"):
            oneway_dir = 1
        elif oneway_tag in ("-1", "reverse"):
            oneway_dir = -1
        elif oneway_tag == "no":
            oneway_dir = 0
        elif highway in ("motorway", "motorway_link") or junction_tag == "roundabout":
            oneway_dir = 1

        # Parse lanes
        lanes_val = 1
        lanes_tag = tags.get("lanes")
        if lanes_tag:
            try:
                lanes_val = max(1, int(str(lanes_tag).split(";")[0].strip()))
            except ValueError:
                pass
        elif oneway_dir != 0:
            # Multi-lane default for wide oneways / motorways
            if highway in ("motorway", "trunk") or halfw >= 6.0:
                lanes_val = 2

        # Parse speed limit (OSM maxspeed tag with Finnish fallback)
        speed_lim = parse_speed_limit_kmh(tags.get("maxspeed"), highway)
        def parse_lane_count(value: object) -> Optional[int]:
            try:
                return max(1, int(str(value).split(";")[0].strip()))
            except (TypeError, ValueError):
                return None

        lanes_forward = parse_lane_count(tags.get("lanes:forward"))
        lanes_backward = parse_lane_count(tags.get("lanes:backward"))
        lit_tag = str(tags.get("lit", "")).strip().lower() or None
        surface_tag = str(tags.get("surface", "")).strip().lower() or None

        ways.append(
            Way(
                points_m=pts,
                highway=highway,
                half_width_m=halfw,
                name=name,
                surface=surface_tag,
                lit=lit_tag,
                is_ice_road=is_ice,
                is_drivable=is_drivable,
                is_busway=is_bus_route,
                oneway=oneway_dir,
                lanes=lanes_val,
                layer=layer_val,
                is_bridge=is_bridge,
                is_tunnel=is_tunnel,
                speed_limit_kmh=speed_lim,
                bbox=ibbox,
                osm_id=way_id,
                lanes_forward=lanes_forward,
                lanes_backward=lanes_backward,
                turn_lanes=tags.get("turn:lanes") or tags.get("turn:lanes:forward"),
            )
        )

    # Keep parking areas as scenery for their existing appearance, while also
    # indexing their polygon as a drivable surface for vehicle collision checks.
    for tags, node_ids in scenery_raw:
        if tags.get("amenity") != "parking" and tags.get("landuse") != "parking":
            continue
        pts, ibbox = process_node_ids(node_ids)
        if not pts or len(pts) < 3:
            continue
        ways.append(
            _parking_surface_way(
                pts,
                ibbox,
                name=tags.get("name"),
                surface=str(tags.get("surface", "")).strip().lower() or None,
            )
        )
    if progress_callback:
        progress_callback(0.965, f"Planting trees ({len(sceneries)} scenery areas)...")
    plant_trees(sceneries, ways)

    # 5. Multipolygon Relations (stitched into proper closed rings)
    if progress_callback:
        progress_callback(0.97, f"Processing {len(relations_raw)} multipolygon relations...")
    for tags, members in relations_raw:
        outer_way_ids = [
            m["ref"]
            for m in members
            if m.get("type") == "way" and (m.get("role") == "outer" or m.get("role") == "")
        ]
        rings = _stitch_member_ways_into_rings(
            outer_way_ids, ways_by_id, lambda nids: process_node_ids(nids)[0]
        )
        name = tags.get("name")
        for pts, is_closed in rings:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ibbox = (min(xs), min(ys), max(xs), max(ys))
            if "building" in tags:
                housenumber = tags.get("addr:housenumber")
                street = tags.get("addr:street")
                center_x = sum(point[0] for point in pts) / len(pts)
                center_y = sum(point[1] for point in pts) / len(pts)
                buildings.append(Building(
                    points_m=pts,
                    name=name,
                    housenumber=housenumber,
                    street=street,
                    height_m=_building_height(tags, pts),
                    bbox=ibbox,
                    venue_type=tags.get("amenity"),
                    center_m=(center_x, center_y),
                    texture_seed=abs(math.sin(center_x * 0.013 + center_y * 0.017)),
                ))
            elif tags.get("natural") in ("water", "bay", "strait") or tags.get("landuse") == "reservoir":
                kind = tags.get("natural") or tags.get("landuse") or "water"
                waters.append(Water(points_m=pts, kind=kind, is_polygon=is_closed, name=name, bbox=ibbox))
            elif tags.get("amenity") == "parking" or tags.get("landuse") == "parking":
                sceneries.append(Scenery(points_m=pts, kind="parking", name=name, bbox=ibbox))
                ways.append(_parking_surface_way(pts, ibbox, name=name))
            elif "leisure" in tags or "landuse" in tags or tags.get("natural") in ("forest", "wood", "scrub", "grass"):
                kind = tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "park"
                scenery = Scenery(points_m=pts, kind=kind, name=name, bbox=ibbox)
                plant_trees([scenery], ways)
                sceneries.append(scenery)
            elif "place" in tags and name and pts:
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                places.append(Place(x=cx, y=cy, name=name, kind=tags.get("place", "suburb")))

    # 6. Place nodes (suburbs, neighbourhoods, districts)
    for tags, nid in place_nodes_raw:
        pt = nodes_m.get(nid)
        if pt:
            places.append(Place(x=pt[0], y=pt[1], name=tags["name"], kind=tags.get("place", "suburb")))

    # 6b. Other named OSM points and areas (e.g. attractions and named venues)
    for tags, nid in named_nodes_raw:
        pt = nodes_m.get(nid)
        if pt:
            places.append(Place(x=pt[0], y=pt[1], name=tags["name"], kind="poi"))
    for tags, node_ids in named_ways_raw:
        pts, _ = process_node_ids(node_ids)
        if pts:
            places.append(
                Place(
                    x=sum(point[0] for point in pts) / len(pts),
                    y=sum(point[1] for point in pts) / len(pts),
                    name=tags["name"],
                    kind=tags.get("amenity", "poi"),
                )
            )

    for tags, nid in taxi_stops_raw:
        pt = nodes_m.get(nid)
        if pt:
            taxi_stops.append(TaxiStop(x=pt[0], y=pt[1], id=nid))

    for tags, nid in bus_stops_raw:
        pt = nodes_m.get(nid)
        if pt:
            bus_stops.append(
                BusStop(
                    x=pt[0],
                    y=pt[1],
                    name=tags.get("name"),
                    id=nid,
                    shelter=str(tags.get("shelter", "")).lower() in {"yes", "true", "1"},
                )
            )
    for tags, node_ids, way_id in bus_platforms_raw:
        pts, _ = process_node_ids(node_ids)
        if pts:
            bus_stops.append(
                BusStop(
                    x=sum(point[0] for point in pts) / len(pts),
                    y=sum(point[1] for point in pts) / len(pts),
                    name=tags.get("name"),
                    id=way_id,
                    shelter=str(tags.get("shelter", "")).lower() in {"yes", "true", "1"},
                )
            )

    # 7. Traffic signals from OSM nodes
    # Find road direction at node to assign orthogonal phase offsets for intersecting streets
    if traffic_signals_raw:
        # Build spatial grid for fast candidate lookup
        signals_grid: dict[Tuple[int, int], List[Way]] = defaultdict(list)
        grid_size = 50.0
        for w in ways:
            bbox = getattr(w, "bbox", None)
            if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
                continue
            minx_b, miny_b, maxx_b, maxy_b = bbox
            gx0 = int((minx_b - 5.0) // grid_size)
            gx1 = int((maxx_b + 5.0) // grid_size)
            gy0 = int((miny_b - 5.0) // grid_size)
            gy1 = int((maxy_b + 5.0) // grid_size)
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    signals_grid[(gx, gy)].append(w)

        signal_points = {
            nid: nodes_m[nid]
            for _tags, nid in traffic_signals_raw
            if nid in nodes_m
        }
        for tags, nid in traffic_signals_raw:
            pt = nodes_m.get(nid)
            if pt:
                layer_tag = tags.get("layer", "")
                layer_val = 0
                if layer_tag:
                    try:
                        layer_val = int(layer_tag)
                    except ValueError:
                        pass

                # Detect road orientation at signal position (0 to pi)
                road_angle = 0.0
                best_dist = 5.0
                found_orientation = False

                gx = int(pt[0] // grid_size)
                gy = int(pt[1] // grid_size)
                candidate_ways = []
                for dx_c in (-1, 0, 1):
                    for dy_c in (-1, 0, 1):
                        candidate_ways.extend(signals_grid.get((gx + dx_c, gy + dy_c), []))

                for w in candidate_ways:
                    if getattr(w, "layer", 0) != layer_val:
                        continue
                    pts = w.points_m
                    for i in range(len(pts) - 1):
                        p1, p2 = pts[i], pts[i + 1]
                        dx = p2[0] - p1[0]
                        dy = p2[1] - p1[1]
                        seg_len = math.hypot(dx, dy)
                        if seg_len > 1e-3:
                            # Distance to line segment
                            t = max(0.0, min(1.0, ((pt[0] - p1[0]) * dx + (pt[1] - p1[1]) * dy) / (seg_len * seg_len)))
                            px = p1[0] + t * dx
                            py = p1[1] + t * dy
                            d = math.hypot(pt[0] - px, pt[1] - py)
                            if d < best_dist:
                                best_dist = d
                                ang = math.atan2(dy, dx) % math.pi  # Normalized direction 0 to pi
                                road_angle = ang
                                found_orientation = True

                # Phase offset: Group into two orthogonal corridors (e.g., North-South vs East-West)
                # If road is closer to EW (angles < pi/4 or > 3pi/4), offset is 0.0s; if NS (pi/4 to 3pi/4), offset is 8.0s.
                if found_orientation:
                    is_north_south = (math.pi * 0.25) <= road_angle < (math.pi * 0.75)
                    phase_offset = 8.0 if is_north_south else 0.0
                else:
                    phase_offset = 0.0

                # Some OSM junctions map one signal node at the center instead of
                # one signal per approach. Split that incomplete representation.
                arm_angles: List[float] = []
                for way_tags, _highway, way_node_ids, _way_id in ways_raw:
                    if nid not in way_node_ids:
                        continue
                    node_index = way_node_ids.index(nid)
                    neighbor_ids = []
                    if node_index > 0:
                        neighbor_ids.append(way_node_ids[node_index - 1])
                    if node_index + 1 < len(way_node_ids):
                        neighbor_ids.append(way_node_ids[node_index + 1])
                    for neighbor_id in neighbor_ids:
                        neighbor = nodes_m.get(neighbor_id)
                        if neighbor is None:
                            continue
                        angle = math.atan2(neighbor[1] - pt[1], neighbor[0] - pt[0])
                        if all(abs((angle - existing + math.pi) % (2 * math.pi) - math.pi) > math.radians(25)
                               for existing in arm_angles):
                            arm_angles.append(angle)

                # Some extracts omit the signal node from the road ways. In
                # that case, recover arms from nearby road geometry.
                if len(arm_angles) < 3:
                    for way in candidate_ways:
                        if getattr(way, "layer", 0) != layer_val or len(way.points_m) < 2:
                            continue
                        closest_segment = min(
                            zip(way.points_m, way.points_m[1:]),
                            key=lambda segment: dist_point_to_segment(
                                pt[0], pt[1], segment[0][0], segment[0][1], segment[1][0], segment[1][1]
                            ),
                        )
                        (p1, p2) = closest_segment
                        if dist_point_to_segment(pt[0], pt[1], p1[0], p1[1], p2[0], p2[1]) > 12.0:
                            continue
                        angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                        for arm_angle in (angle, angle + math.pi):
                            if all(
                                abs((arm_angle - existing + math.pi) % (2 * math.pi) - math.pi)
                                > math.radians(25)
                                for existing in arm_angles
                            ):
                                arm_angles.append(arm_angle)

                nearby_signal_points = [
                    other_pt for other_nid, other_pt in signal_points.items()
                    if other_nid != nid
                    and math.hypot(pt[0] - other_pt[0], pt[1] - other_pt[1]) <= 60.0
                ]
                has_nearby_signal = bool(nearby_signal_points)
                if has_nearby_signal:
                    junction_center = (
                        sum(other_pt[0] for other_pt in nearby_signal_points) / len(nearby_signal_points),
                        sum(other_pt[1] for other_pt in nearby_signal_points) / len(nearby_signal_points),
                    )
                    approach_direction = math.atan2(
                        junction_center[1] - pt[1],
                        junction_center[0] - pt[0],
                    ) % (2.0 * math.pi)
                else:
                    approach_direction = road_angle if found_orientation else None
                if len(arm_angles) >= 3 and not has_nearby_signal:
                    for arm_index, arm_angle in enumerate(arm_angles):
                        signal_axis = arm_angle % math.pi
                        signal_offset = 8.0 if (math.pi * 0.25) <= signal_axis < (math.pi * 0.75) else 0.0
                        traffic_lights.append(
                            TrafficLight(
                                x=pt[0] + math.cos(arm_angle) * 6.0,
                                y=pt[1] + math.sin(arm_angle) * 6.0,
                                cycle_time=16.0,
                                offset=signal_offset,
                                layer=layer_val,
                                id=nid * 10 + arm_index,
                                # The signal controls traffic moving from its arm toward the junction.
                                direction_angle=(arm_angle + math.pi) % (2.0 * math.pi),
                            )
                        )
                else:
                    traffic_lights.append(
                        TrafficLight(
                            x=pt[0],
                            y=pt[1],
                            cycle_time=16.0,
                            offset=phase_offset,
                            layer=layer_val,
                            id=nid,
                            direction_angle=approach_direction,
                        )
                    )

        traffic_lights = complete_traffic_light_approaches(
            deduplicate_traffic_lights(traffic_lights), ways
        )
    logical_intersections = build_logical_intersections(traffic_lights, ways)

    # 8. Pedestrian Crossings (suojatiet) from OSM nodes and ways
    if crossings_raw:
        # Build spatial grid of drivable roads to find road direction and road width at crossing
        roads_grid: dict[Tuple[int, int], List[Way]] = defaultdict(list)
        r_grid_size = 50.0
        for w in ways:
            if not getattr(w, "is_drivable", True):
                continue
            bbox = getattr(w, "bbox", None)
            if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
                continue
            minx_b, miny_b, maxx_b, maxy_b = bbox
            gx0 = int((minx_b - 5.0) // r_grid_size)
            gx1 = int((maxx_b + 5.0) // r_grid_size)
            gy0 = int((miny_b - 5.0) // r_grid_size)
            gy1 = int((maxy_b + 5.0) // r_grid_size)
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    roads_grid[(gx, gy)].append(w)

        seen_crossing_locs: Set[Tuple[int, int]] = set()

        for tags, nid in crossings_raw:
            pt = nodes_m.get(nid)
            if not pt:
                continue

            # Deduplicate closely co-located crossing nodes within 2 meters
            loc_key = (int(round(pt[0] / 2.0)), int(round(pt[1] / 2.0)))
            if loc_key in seen_crossing_locs:
                continue
            seen_crossing_locs.add(loc_key)

            layer_tag = tags.get("layer", "")
            layer_val = 0
            if layer_tag:
                try:
                    layer_val = int(layer_tag)
                except ValueError:
                    pass

            crossing_type = tags.get("crossing") or tags.get("crossing_ref") or "zebra"
            road_angle = 0.0
            road_half_w = 3.5
            best_dist = 8.0
            found_orientation = False

            gx = int(pt[0] // r_grid_size)
            gy = int(pt[1] // r_grid_size)
            candidate_roads = []
            for dx_c in (-1, 0, 1):
                for dy_c in (-1, 0, 1):
                    candidate_roads.extend(roads_grid.get((gx + dx_c, gy + dy_c), []))

            for w in candidate_roads:
                if getattr(w, "layer", 0) != layer_val:
                    continue
                pts = w.points_m
                for i in range(len(pts) - 1):
                    p1, p2 = pts[i], pts[i + 1]
                    dx = p2[0] - p1[0]
                    dy = p2[1] - p1[1]
                    seg_len = math.hypot(dx, dy)
                    if seg_len > 1e-3:
                        t = max(0.0, min(1.0, ((pt[0] - p1[0]) * dx + (pt[1] - p1[1]) * dy) / (seg_len * seg_len)))
                        px = p1[0] + t * dx
                        py = p1[1] + t * dy
                        d = math.hypot(pt[0] - px, pt[1] - py)
                        if d < best_dist:
                            best_dist = d
                            ang = math.atan2(dy, dx) % math.pi
                            road_angle = ang
                            road_half_w = getattr(w, "half_width_m", 3.5)
                            found_orientation = True

            crossings.append(
                Crossing(
                    x=pt[0],
                    y=pt[1],
                    layer=layer_val,
                    id=nid,
                    crossing_type=crossing_type,
                    direction_angle=road_angle if found_orientation else None,
                    width_m=max(3.0, road_half_w * 1.8),
                    length_m=2.4,
                )
            )

    t_total = time.time() - t_start
    logger.info(
        "Map generation complete in %.3fs: %d roads, %d waters, %d buildings, %d scenery polygons, %d places, %d traffic signals, %d crossings",
        t_total,
        len(ways),
        len(waters),
        len(buildings),
        len(sceneries),
        len(places),
        len(traffic_lights),
        len(crossings),
    )

    if progress_callback:
        progress_callback(
            1.0,
            f"Ready ({len(ways)} roads, {len(places)} districts, {len(buildings)} buildings, {len(waters)} waters, {len(crossings)} crossings)",
        )

    # Fallback if no roads were loaded
    if minx == float("inf") or miny == float("inf"):
        all_pts = []
        for w in waters:
            all_pts.extend(w.points_m)
        for s in sceneries:
            all_pts.extend(s.points_m)
        for b in buildings:
            all_pts.extend(b.points_m)
        if all_pts:
            xs = [p[0] for p in all_pts]
            ys = [p[1] for p in all_pts]
            minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
        else:
            minx = miny = 0.0
            maxx = maxy = 1000.0

    return MapData(
        ways, waters, buildings, sceneries, places, (minx, miny, maxx, maxy),
        traffic_lights, crossings, taxi_stops, bus_stops, parking_spaces, logical_intersections,
    )


class AutoFetchManager:
    """Background auto-fetch manager for expanding map boundaries dynamically."""

    def __init__(
        self,
        ways: List[Way],
        bounds: Tuple[float, float, float, float],
        transformer,
        waters: Optional[List[Water]] = None,
        buildings: Optional[List[Building]] = None,
        sceneries: Optional[List[Scenery]] = None,
        places: Optional[List[Place]] = None,
        traffic_lights: Optional[List[TrafficLight]] = None,
        crossings: Optional[List[Crossing]] = None,
        bus_stops: Optional[List[BusStop]] = None,
        fetch_func=fetch_osm_ways,
        build_func=build_ways,
        cooldown_s: float = 5.0,
        build_in_process: bool = False,
    ):
        self.ways = ways
        self.waters = waters if waters is not None else []
        self.buildings = buildings if buildings is not None else []
        self.sceneries = sceneries if sceneries is not None else []
        self.places = places if places is not None else []
        self.traffic_lights = traffic_lights if traffic_lights is not None else []
        self.crossings = crossings if crossings is not None else []
        self.bus_stops = bus_stops if bus_stops is not None else []
        self.bounds = bounds
        self.transformer = transformer
        self.fetch_func = fetch_func
        self.build_func = build_func
        self.cooldown_s = cooldown_s
        self.build_in_process = build_in_process
        self.lock = threading.Lock()
        self.is_fetching = False
        self.fetch_progress = 0.0
        self.last_fetch_time = 0.0
        self.last_trigger_reason = ""
        self._attempted_endpoints: Set[Tuple[int, str]] = set()
        self._completed_fetch_targets: Set[Tuple[float, float, float, float]] = set()
        # Load known dead-end boundaries from disk cache
        self.dead_ends: List[dict] = load_dead_ends_cache()

    def get_bounds(self) -> Tuple[float, float, float, float]:
        with self.lock:
            return self.bounds

    def get_progress(self) -> float:
        with self.lock:
            return self.fetch_progress

    def get_fetching(self) -> bool:
        with self.lock:
            return self.is_fetching

    def get_trigger_reason(self) -> str:
        with self.lock:
            return self.last_trigger_reason

    def is_known_dead_end(self, car_x: float, car_y: float, direction: str, tolerance_m: float = 300.0) -> bool:
        """Check if vehicle is near a recorded dead-end in the given expansion direction."""
        for entry in self.dead_ends:
            if entry.get("direction") == direction:
                dx = entry.get("x", 0.0) - car_x
                dy = entry.get("y", 0.0) - car_y
                if (dx * dx + dy * dy) ** 0.5 < tolerance_m:
                    return True
        return False

    def start_if_needed(
        self,
        car,
        auto_fetch: bool,
        margin_m: float,
        tile_size_m: float,
        current_way: Optional[Way] = None,
    ) -> bool:
        if not auto_fetch:
            return False
        with self.lock:
            if self.is_fetching:
                return False
            now = time.time()
            if now - self.last_fetch_time < self.cooldown_s:
                return False

            minx, miny, maxx, maxy = self.bounds
            expanded = False
            trigger_reason = ""
            # Expand in the direction the car is approaching or heading
            fetch_minx, fetch_miny, fetch_maxx, fetch_maxy = minx, miny, maxx, maxy
            direction = ""

            # Determine expansion boxes centered around car's position with overlap into existing area
            half_span = tile_size_m / 2.0
            overlap = max(margin_m, 500.0)

            if car.x < minx + margin_m:
                direction = "west"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_minx = car.x - tile_size_m
                    fetch_maxx = car.x + overlap
                    fetch_miny = car.y - half_span
                    fetch_maxy = car.y + half_span
                    expanded = True
                    trigger_reason = "bbox west edge"
            elif car.x > maxx - margin_m:
                direction = "east"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_minx = car.x - overlap
                    fetch_maxx = car.x + tile_size_m
                    fetch_miny = car.y - half_span
                    fetch_maxy = car.y + half_span
                    expanded = True
                    trigger_reason = "bbox east edge"

            if not expanded:
                if car.y < miny + margin_m:
                    direction = "south"
                    if not self.is_known_dead_end(car.x, car.y, direction):
                        fetch_miny = car.y - tile_size_m
                        fetch_maxy = car.y + overlap
                        fetch_minx = car.x - half_span
                        fetch_maxx = car.x + half_span
                        expanded = True
                        trigger_reason = "bbox south edge"

            if not expanded and car.y > maxy - margin_m:
                direction = "north"
                if not self.is_known_dead_end(car.x, car.y, direction):
                    fetch_miny = car.y - overlap
                    fetch_maxy = car.y + tile_size_m
                    fetch_minx = car.x - half_span
                    fetch_maxx = car.x + half_span
                    expanded = True
                    trigger_reason = "bbox north edge"

            if not expanded and current_way is not None and len(current_way.points_m) >= 2:
                endpoint_candidates = (
                    (current_way.points_m[0], current_way.points_m[1]),
                    (current_way.points_m[-1], current_way.points_m[-2]),
                )
                endpoint, previous = min(
                    endpoint_candidates,
                    key=lambda candidate: math.hypot(car.x - candidate[0][0], car.y - candidate[0][1]),
                )
                endpoint_distance = math.hypot(car.x - endpoint[0], car.y - endpoint[1])
                approach_x = endpoint[0] - previous[0]
                approach_y = endpoint[1] - previous[1]
                approach_length = math.hypot(approach_x, approach_y)
                heading_alignment = (
                    (math.cos(car.heading) * approach_x + math.sin(car.heading) * approach_y) / approach_length
                    if approach_length > 0.0 else -1.0
                )
                connected = any(
                    other is not current_way
                    and any(
                        math.hypot(endpoint[0] - point[0], endpoint[1] - point[1])
                        <= max(12.0, current_way.half_width_m + getattr(other, "half_width_m", 3.0))
                        for point in getattr(other, "points_m", ())
                    )
                    for other in self.ways
                )
                direction = "east" if abs(approach_x) >= abs(approach_y) and approach_x >= 0 else "west"
                if abs(approach_y) > abs(approach_x):
                    direction = "north" if approach_y >= 0 else "south"
                endpoint_key = (id(current_way), direction)
                if (
                    endpoint_distance <= margin_m
                    and not connected
                    and heading_alignment > 0.2
                    and endpoint_key not in self._attempted_endpoints
                ):
                    if not self.is_known_dead_end(car.x, car.y, direction):
                        fetch_minx = car.x - (tile_size_m if approach_x < 0 else overlap)
                        fetch_maxx = car.x + (tile_size_m if approach_x >= 0 else overlap)
                        fetch_miny = car.y - (tile_size_m if approach_y < 0 else overlap)
                        fetch_maxy = car.y + (tile_size_m if approach_y >= 0 else overlap)
                        expanded = True
                        trigger_reason = "road endpoint"
                        self._attempted_endpoints.add((id(current_way), direction))

            if not expanded:
                return False

            fetch_bbox = (
                car.x - half_span,
                car.y - half_span,
                car.x + half_span,
                car.y + half_span,
            )
            target = _snap_projected_bbox(fetch_bbox, tile_size_m)
            if target in self._completed_fetch_targets:
                return False
            self.is_fetching = True
            self.fetch_progress = 0.1
            self.last_fetch_time = now
            self.last_trigger_reason = trigger_reason
            car_pos = (car.x, car.y)

        t = threading.Thread(
            target=self._background_fetch,
            args=(fetch_bbox, direction, car_pos, target),
            daemon=True,
        )
        t.start()
        return True

    def _background_fetch(
        self,
        fetch_bbox: Tuple[float, float, float, float],
        direction: str = "",
        car_pos: Tuple[float, float] = (0.0, 0.0),
        target_bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> None:
        if target_bbox is None:
            target_bbox = fetch_bbox
        new_minx, new_miny, new_maxx, new_maxy = fetch_bbox
        try:
            lon1, lat1 = self.transformer.transform(new_minx, new_miny)
            lon2, lat2 = self.transformer.transform(new_maxx, new_maxy)
            car_lon, car_lat = self.transformer.transform(car_pos[0], car_pos[1])
            south = min(lat1, lat2)
            west = min(lon1, lon2)
            north = max(lat1, lat2)
            east = max(lon1, lon2)
        except Exception as e:
            logger.warning("Failed to compute lat/lon bbox for auto-fetch: %s", e)
            with self.lock:
                self.is_fetching = False
                self.fetch_progress = 0.0
            return

        def _bg_progress(fraction: float, msg: str):
            with self.lock:
                self.fetch_progress = fraction

        try:
            with self.lock:
                self.fetch_progress = 0.25
            elems = load_osm_cache(
                (south, west, north, east),
                point=(car_lat, car_lon),
            )
            if elems is None:
                logger.info(
                    "Auto-fetch cache miss at car point (%.6f, %.6f); requesting network",
                    car_lat, car_lon,
                )
                elems = self.fetch_func((south, west, north, east))
            else:
                logger.info(
                    "Auto-fetch cache hit at car point (%.6f, %.6f); network skipped",
                    car_lat, car_lon,
                )
            with self.lock:
                self.fetch_progress = 0.65
            if self.build_in_process:
                context = multiprocessing.get_context("spawn")
                try:
                    with concurrent.futures.ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
                        res = executor.submit(self.build_func, elems).result()
                except (concurrent.futures.process.BrokenProcessPool, OSError) as exc:
                    logger.warning("Auto-fetch process build failed; retrying in background thread: %s", exc)
                    res = self.build_func(elems)
            else:
                res = self.build_func(elems)
            with self.lock:
                self.fetch_progress = 0.9
            new_crossings = getattr(res, "crossings", [])
            new_bus_stops = getattr(res, "bus_stops", [])
            if len(res) == 8:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds, new_traffic_lights, new_crossings = res
            elif len(res) == 7:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds, new_traffic_lights = res
            elif len(res) == 6:
                new_ways, new_waters, new_buildings, new_sceneries, new_places, new_bounds = res
                new_traffic_lights = getattr(res, "traffic_lights", [])
            elif len(res) == 5:
                new_ways, new_waters, new_buildings, new_sceneries, new_bounds = res
                new_places, new_traffic_lights = [], []
            elif len(res) == 3:
                new_ways, new_waters, new_bounds = res
                new_buildings, new_sceneries, new_places, new_traffic_lights = [], [], [], []
            else:
                new_ways, new_bounds = res[0], res[-1]
                new_waters, new_buildings, new_sceneries, new_places, new_traffic_lights = [], [], [], [], []

            # Check if fetch returned no new drivable roads in target area (dead end)
            drivable_new = [w for w in new_ways if w.is_drivable]
            if not drivable_new:
                logger.info(
                    "No drivable roads found in direction %s at (%.1f, %.1f); marking as dead end in cache",
                    direction,
                    car_pos[0],
                    car_pos[1],
                )
                entry = {
                    "x": car_pos[0],
                    "y": car_pos[1],
                    "direction": direction,
                    "target_bbox": list(target_bbox),
                    "recorded_at": time.time(),
                }
                save_dead_end_to_cache(entry)
                with self.lock:
                    self.dead_ends.append(entry)

            with self.lock:
                known_way_ids = {
                    way.osm_id for way in self.ways if getattr(way, "osm_id", None) is not None
                }
                unique_new_ways = [
                    way for way in new_ways
                    if way.osm_id is None or way.osm_id not in known_way_ids
                ]
                plant_trees(new_sceneries, self.ways + unique_new_ways)
                self.ways.extend(unique_new_ways)
                added_waters = _extend_unique(self.waters, new_waters)
                added_buildings = _extend_unique(self.buildings, new_buildings)
                added_sceneries = _extend_unique(self.sceneries, new_sceneries)
                added_places = _extend_unique(self.places, new_places)
                added_traffic_lights = _extend_unique(self.traffic_lights, new_traffic_lights)
                added_crossings = _extend_unique(self.crossings, new_crossings)
                added_bus_stops = _extend_unique(self.bus_stops, new_bus_stops)
                minx = min(self.bounds[0], new_bounds[0])
                miny = min(self.bounds[1], new_bounds[1])
                maxx = max(self.bounds[2], new_bounds[2])
                maxy = max(self.bounds[3], new_bounds[3])
                self.bounds = (minx, miny, maxx, maxy)
                self.last_fetch_time = time.time()
                self._completed_fetch_targets.add(target_bbox)

            # Rebuilding the segment index can be expensive; keep the game loop
            # responsive while the background fetch finishes indexing new roads.
            with self.lock:
                self.fetch_progress = 1.0
                self.is_fetching = False
            logger.info(
                "Auto-fetched and added %d ways, %d waters, %d buildings, %d scenery, %d places, %d traffic lights, %d crossings; new bounds: %s",
                len(unique_new_ways),
                added_waters,
                added_buildings,
                added_sceneries,
                added_places,
                added_traffic_lights,
                added_crossings,
                self.bounds,
            )
        except Exception as e:
            logger.warning("Auto-fetch failed: %s", e)
            with self.lock:
                self.is_fetching = False
                self.fetch_progress = 0.0
