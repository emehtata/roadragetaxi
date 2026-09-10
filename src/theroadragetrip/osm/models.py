from collections import defaultdict
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


from ..geo import point_in_polygon

logger = logging.getLogger(__name__)


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
    is_roundabout: bool = False
    priority_road: bool = False
    service: Optional[str] = None
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


@dataclass
class Water:
    points_m: List[Tuple[float, float]]
    kind: str
    is_polygon: bool
    name: Optional[str] = None
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    layer: int = 0


@dataclass
class Curb:
    """A raised kerbstone line (OSM barrier=kerb). Driving over one bumps the car."""
    points_m: List[Tuple[float, float]]
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class Building:
    points_m: List[Tuple[float, float]]
    name: Optional[str] = None
    housenumber: Optional[str] = None
    street: Optional[str] = None
    height_m: float = 8.0
    levels: Optional[int] = None
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    venue_type: Optional[str] = None
    center_m: Tuple[float, float] = (0.0, 0.0)
    texture_seed: float = 0.0
    entrances: List[Tuple[float, float]] = field(default_factory=list)
    associated_places: List["Place"] = field(default_factory=list, repr=False)


@dataclass
class ParkingSpace:
    points_m: List[Tuple[float, float]]
    bbox: Tuple[float, float, float, float]
    orientation: object = None
    osm_id: Optional[int] = None
    occupied: bool = False
    reserved: bool = False
    vehicle_id: Optional[int] = None
    reserved_by_pedestrian_id: Optional[int] = None

    def __post_init__(self) -> None:
        orientation = self.orientation
        if isinstance(orientation, str):
            orientation = orientation.strip().casefold()
            self.orientation = orientation
        if len(self.points_m) < 2:
            return
        longest_edge = max(
            zip(self.points_m, self.points_m[1:] + self.points_m[:1]),
            key=lambda edge: (edge[1][0] - edge[0][0]) ** 2 + (edge[1][1] - edge[0][1]) ** 2,
        )
        axis = math.atan2(
            longest_edge[1][1] - longest_edge[0][1],
            longest_edge[1][0] - longest_edge[0][0],
        )
        if isinstance(orientation, str):
            self.orientation = {
                "parallel": axis,
                "perpendicular": axis + math.pi / 2.0,
                "diagonal": axis + math.pi / 4.0,
                "across": axis + math.pi / 2.0,
                "multi": axis,
            }.get(orientation, axis)
        elif orientation == 0.0:
            self.orientation = axis


@dataclass
class Scenery:
    points_m: List[Tuple[float, float]]
    kind: str
    name: Optional[str] = None
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    trees: List[Tuple[float, float]] = field(default_factory=list)
    tree_variations: List[float] = field(default_factory=list)
    # Set by remove_trees_under_roads() once it has swept this scenery's
    # trees against the road network, so a later re-sync (a new tile
    # merging in) doesn't re-scan every scenery ever loaded - just the
    # newly-added ones.
    trees_checked_against_roads: bool = field(default=False, repr=False)
    # Set by plant_trees() when .trees came from real OSM natural=tree
    # nodes rather than procedural placement - marks this scenery as done
    # so a later plant_trees() call (e.g. autofetch's re-merge with a
    # fuller road list) never tops it up with fake trees alongside real
    # ones.
    trees_from_osm: bool = field(default=False, repr=False)


def _building_height(tags: Dict[str, Any], points: List[Tuple[float, float]]) -> float:
    """Return explicit OSM height, then level-derived or footprint fallback."""
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
                return max(3.0, min(levels * 3.0, 120.0))
        except (TypeError, ValueError):
            pass

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    footprint_scale = math.sqrt(max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys))))
    return min(24.0, 5.0 + footprint_scale * 0.18)


def _building_levels(tags: Dict[str, Any]) -> Optional[int]:
    raw_levels = tags.get("building:levels") or tags.get("levels")
    try:
        levels = int(float(raw_levels))
    except (TypeError, ValueError):
        return None
    return max(1, min(levels, 40)) if levels > 0 else None


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


@dataclass
class StopSign:
    """OSM stop sign position used by NPC approach logic."""

    x: float
    y: float
    layer: int = 0
    id: Optional[int] = None


@dataclass
class YieldSign:
    """OSM give-way sign position used by NPC approach logic."""

    x: float
    y: float
    layer: int = 0
    id: Optional[int] = None


@dataclass
class Place:
    x: float
    y: float
    name: str
    kind: str


def associate_places_with_buildings(buildings: List[Building], places: List[Place]) -> None:
    """Attach named venue places to buildings once, before rendering."""
    cell_size = 128.0
    building_cells = defaultdict(list)
    for building in buildings:
        building.associated_places.clear()
        bbox = getattr(building, "bbox", (0.0, 0.0, 0.0, 0.0))
        if bbox == (0.0, 0.0, 0.0, 0.0):
            continue
        for cell_x in range(math.floor(bbox[0] / cell_size), math.floor(bbox[2] / cell_size) + 1):
            for cell_y in range(math.floor(bbox[1] / cell_size), math.floor(bbox[3] / cell_size) + 1):
                building_cells[(cell_x, cell_y)].append(building)
    venue_places = [
        place for place in places
        if place.name and place.kind not in {
            "suburb", "neighbourhood", "quarter", "village", "town", "city",
        }
    ]
    for place in venue_places:
        candidates = building_cells.get(
            (math.floor(place.x / cell_size), math.floor(place.y / cell_size)),
            (),
        )
        for building in candidates:
            bbox = getattr(building, "bbox", (0.0, 0.0, 0.0, 0.0))
            if not (bbox[0] <= place.x <= bbox[2] and bbox[1] <= place.y <= bbox[3]):
                continue
            if point_in_polygon(place.x, place.y, building.points_m):
                building.associated_places.append(place)
                break


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
    length_m: float = 2.4


@dataclass
class SpeedBump:
    """OSM traffic_calming=bump/table/cushion/hump (a real physical raised
    road feature, not just a "traffic_calming=no/island" tag with no
    physical bump). Same shape as Crossing - a bar across the road at a
    point along it - since it's the same "snap to nearest road, get
    direction+width" geometry problem; see osm/build.py."""
    x: float
    y: float
    layer: int = 0
    id: Optional[int] = None
    kind: str = "bump"  # bump, table, cushion, hump
    direction_angle: Optional[float] = None  # Road axis alignment angle in radians
    width_m: float = 3.5  # Across-road width


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


@dataclass
class SceneryObject:
    """A small decorative point object from OSM (bench, waste basket,
    bicycle parking, statue/memorial, ...), differentiated by `kind`.

    One shared class rather than one per kind: none of these need their
    own behavior (unlike e.g. TrafficLight's signal timing) - they're all
    just a position, a kind to pick a small icon by, and an id for
    dedup/caching. See osm/build.py for the OSM tags -> kind mapping and
    render/scenery.py:draw_scenery_objects() for how each kind is drawn.
    """

    x: float
    y: float
    kind: str
    name: Optional[str] = None
    id: Optional[int] = None


class MapData(tuple):
    """Container tuple for build_ways results returning 6 elements for backward compatibility while providing traffic_lights and crossings via attributes and slicing."""

    def __new__(cls, ways, waters, buildings, sceneries, places, bounds, traffic_lights=None, crossings=None, taxi_stops=None, bus_stops=None, parking_spaces=None, logical_intersections=None, stop_signs=None, yield_signs=None, curbs=None, scenery_objects=None, speed_bumps=None):
        return super().__new__(cls, (ways, waters, buildings, sceneries, places, bounds))

    def __init__(self, ways, waters, buildings, sceneries, places, bounds, traffic_lights=None, crossings=None, taxi_stops=None, bus_stops=None, parking_spaces=None, logical_intersections=None, stop_signs=None, yield_signs=None, curbs=None, scenery_objects=None, speed_bumps=None):
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
        self.stop_signs = stop_signs if stop_signs is not None else []
        self.yield_signs = yield_signs if yield_signs is not None else []
        self.scenery_objects = scenery_objects if scenery_objects is not None else []
        self.curbs = curbs if curbs is not None else []
        self.speed_bumps = speed_bumps if speed_bumps is not None else []

    @property
    def traffic_signals(self):
        return self.traffic_lights
