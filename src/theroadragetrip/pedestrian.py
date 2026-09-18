import logging
import heapq
import math
import random
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .osm import BusStop, Crossing, LogicalIntersection, Scenery, SceneryObject, TrafficLight, Way
from .geo import closest_point_and_dist_to_segment, compute_bbox, dist_point_to_segment, point_in_polygon
from .npc import NPCState
from .physics import Car, is_car_road, is_pedestrian_way
from .residents import ResidentManager
from .activities import ActivityContext, ActivityInstance, ActivityManager

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

PEDESTRIAN_LOD_UPDATE_INTERVALS = (1.0 / 30.0, 1.0 / 12.0, 0.2)
MAX_VEHICLE_RESERVATION_DISTANCE_M = 100.0
TRIP_GROUP_SPAWN_SPACING_M = 1.1
# Rolled per ordinary walking pedestrian on each 5s population tick, not
# every frame (residents-live.md section 19's perf requirement) - keeps
# activity starts spread out rather than everyone starting at once.
ACTIVITY_CONSIDER_PROBABILITY = 0.15


def _fanned_out_position(
    anchor_x: float, anchor_y: float, index: int, total: int, heading: float = 0.0,
    spacing_m: float = TRIP_GROUP_SPAWN_SPACING_M,
) -> Tuple[float, float]:
    """A small spread-out point beside `anchor` for the index-th of
    `total` trip-group members disembarking together (multi-passenger-
    car.md section 9: "sensible position ... not stacked on one pixel").
    Not a rigid formation - just enough separation that five passengers
    don't spawn on the exact same point; each walks its own route from
    here afterwards.

    Spread along the vehicle's own heading (front-to-back), not a full
    circle around the anchor - `anchor` (_vehicle_entry_position) is
    only offset far enough to clear the car on the passenger side, so a
    circle pushes roughly half the members back across that clearance
    and into the vehicle's own footprint regardless of its orientation
    (reported: "people get out of car and walk thru the car"). Spreading
    along heading instead keeps every member at that same lateral
    clearance, just spaced out door-to-door beside the car.
    """
    if total <= 1:
        return anchor_x, anchor_y
    offset = (index - (total - 1) / 2.0) * spacing_m
    return anchor_x + math.cos(heading) * offset, anchor_y + math.sin(heading) * offset


class PedestrianNetwork:
    """Reusable graph and spatial queries for walkable OSM ways."""

    def __init__(self, ways: Optional[List[Way]] = None) -> None:
        self.ways: List[Way] = []
        self.nodes: List[Tuple[float, float]] = []
        self.edges: Dict[int, List[Tuple[int, float]]] = {}
        self.set_ways(ways or [])

    def set_ways(self, ways: List[Way]) -> None:
        self.ways = [way for way in ways if len(way.points_m) >= 2]
        self.nodes = []
        self.edges = {}
        buckets: Dict[Tuple[int, int], List[int]] = {}

        def node_id(point: Tuple[float, float]) -> int:
            bucket = (round(point[0] / 3.0), round(point[1] / 3.0))
            for candidate in buckets.get(bucket, []):
                if math.hypot(self.nodes[candidate][0] - point[0], self.nodes[candidate][1] - point[1]) <= 3.0:
                    return candidate
            candidate = len(self.nodes)
            self.nodes.append(point)
            self.edges[candidate] = []
            buckets.setdefault(bucket, []).append(candidate)
            return candidate

        for way in self.ways:
            point_ids = [node_id(point) for point in way.points_m]
            for first, second in zip(point_ids, point_ids[1:]):
                distance = math.hypot(
                    self.nodes[second][0] - self.nodes[first][0],
                    self.nodes[second][1] - self.nodes[first][1],
                )
                self.edges[first].append((second, distance))
                self.edges[second].append((first, distance))

    def nearest_point(
        self, point: Tuple[float, float], reject: Optional[Callable[[float, float], bool]] = None,
    ) -> Optional[Tuple[float, float]]:
        """Return closest point on network, or ``None`` when network is
        empty (or every candidate is rejected). `reject(x, y)` returning
        True skips that candidate - e.g. PedestrianManager._footway_route_to
        uses it to rule out a point that's closer as the crow flies but
        only reachable by cutting through a building."""
        nearest = None
        nearest_distance = float("inf")
        for way in self.ways:
            for first, second in zip(way.points_m, way.points_m[1:]):
                x, y, _, distance = closest_point_and_dist_to_segment(
                    point[0], point[1], first[0], first[1], second[0], second[1]
                )
                if distance >= nearest_distance:
                    continue
                if reject is not None and reject(x, y):
                    continue
                nearest, nearest_distance = (x, y), distance
        return nearest

    def route(self, start: Tuple[float, float], target: Tuple[float, float]) -> List[Tuple[float, float]]:
        """Return shortest network route with direct connectors at both ends."""
        if not self.nodes:
            return [start, target] if math.hypot(target[0] - start[0], target[1] - start[1]) > 0.01 else [start]
        start_id = min(self.edges, key=lambda i: (self.nodes[i][0] - start[0]) ** 2 + (self.nodes[i][1] - start[1]) ** 2)
        target_id = min(self.edges, key=lambda i: (self.nodes[i][0] - target[0]) ** 2 + (self.nodes[i][1] - target[1]) ** 2)
        distances = {start_id: 0.0}
        previous: Dict[int, int] = {}
        queue = [(0.0, start_id)]
        while queue:
            distance, current = heapq.heappop(queue)
            if distance != distances.get(current):
                continue
            if current == target_id:
                break
            for neighbor, edge_distance in self.edges[current]:
                new_distance = distance + edge_distance
                if new_distance < distances.get(neighbor, math.inf):
                    distances[neighbor] = new_distance
                    previous[neighbor] = current
                    heapq.heappush(queue, (new_distance, neighbor))
        if target_id not in distances:
            return [start, target] if math.hypot(target[0] - start[0], target[1] - start[1]) > 0.01 else [start]
        path = [target_id]
        while path[-1] != start_id:
            path.append(previous[path[-1]])
        path.reverse()
        return [start] + [self.nodes[index] for index in path] + [target]


class PedestrianState(str, Enum):
    """Stable state names for pedestrian AI and renderer integrations."""

    WALKING = "walking"
    APPROACHING_CROSSING = "approaching_crossing"
    WAITING_AT_LIGHT = "waiting_at_light"
    CROSSING = "crossing"
    WAITING = "waiting"
    ENTERING_BUILDING = "entering_building"
    IN_BUILDING = "in_building"
    EXITING_BUILDING = "exiting_building"
    ENTERING_VEHICLE = "entering_vehicle"
    EXITING_VEHICLE = "exiting_vehicle"
    IN_VEHICLE = "in_vehicle"
    DESPAWNING = "despawning"


@dataclass
class PedestrianAppearance:
    """Composable top-down appearance; rendering can add components later."""

    body: Tuple[int, int, int]
    head: Tuple[int, int, int] = (238, 185, 145)
    hair: Tuple[int, int, int] = (45, 30, 25)
    clothing: Optional[Tuple[int, int, int]] = None
    arms: Optional[Tuple[int, int, int]] = None
    legs: Tuple[int, int, int] = (35, 35, 45)


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
    wants_vehicle: bool = False
    taxi_stop_target: Optional[Tuple[float, float]] = None
    is_walking_to_taxi_stop: bool = False
    is_taxi_stop_waiter: bool = False
    is_cyclist: bool = False
    is_drunk: bool = False
    blood_alcohol_promille: float = 0.0
    drunk_phase: float = 0.0
    drunk_vomit_cooldown: float = 0.0
    fall_timer: float = 0.0
    fall_cooldown: float = 0.0
    door_grace_timer: float = 0.0
    offscreen_timer: float = 0.0
    spawned_at_door: bool = False
    state: str = "walking"
    animation_state: str = "walking"
    route: Optional[List[Tuple[float, float]]] = None
    current_route_segment: int = 0
    destination: Optional[Tuple[float, float]] = None
    crossing: Optional[Crossing] = None
    lod_level: int = 0
    lod_time_accumulator: float = 0.0
    lod_update_due: bool = True
    lod_update_dt: float = 0.0
    reserved_vehicle_id: Optional[int] = None
    current_vehicle_id: Optional[int] = None
    resident_id: Optional[int] = None
    vehicle_destination: Optional[Tuple[float, float]] = None
    linked_vehicle_id: Optional[int] = None
    linked_building_entrance: Optional[Tuple[float, float]] = None
    building_visit_timer: float = 0.0
    vehicle_entry_timer: float = 0.0
    building_entry_timer: float = 0.0
    animation_time: float = 0.0
    appearance: Optional[PedestrianAppearance] = None
    # Ambient activity system (residents-live.md) - the one live-instance
    # object while performing an activity, and a small generic scratch
    # dict for cross-activity bookkeeping (cooldowns) - not a field per
    # spec property, see activities/base.py's ActivityInstance.
    activity: Optional[ActivityInstance] = None
    activity_flags: Dict[str, Any] = field(default_factory=dict)
    # NPC-004 section 17: a departed accident driver's visible mood -
    # separate from animation_state, which the activity system already
    # overwrites to "idle" while performing an activity (would otherwise
    # clobber "annoyed" the moment the phone-checking activity starts).
    mood: str = "normal"


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
        crossings: Optional[List[Crossing]] = None,
        logical_intersections: Optional[List[LogicalIntersection]] = None,
        traffic_vehicles: Optional[List] = None,
        traffic_manager=None,
        venue_buildings: Optional[List] = None,
        residents: Optional[ResidentManager] = None,
        scenery_objects: Optional[List[SceneryObject]] = None,
        sceneries: Optional[List[Scenery]] = None,
        bus_stops: Optional[List[BusStop]] = None,
    ):
        self.target_count = target_count
        self.spawn_radius_m = spawn_radius_m
        self.despawn_radius_m = despawn_radius_m
        self.pedestrians: List[Pedestrian] = []
        self.traffic_lights: List[TrafficLight] = traffic_lights or []
        self.crossings: List[Crossing] = crossings or []
        self.logical_intersections = logical_intersections or []
        self.traffic_vehicles = traffic_vehicles if traffic_vehicles is not None else []
        self.traffic_manager = traffic_manager
        self.residents = residents if residents is not None else ResidentManager()
        self.sim_time: float = 0.0
        self._population_update_elapsed: float = 4.9
        self._visible_taxi_stops: Set[Tuple[float, float, Optional[int]]] = set()
        self._taxi_stop_visibility_initialized = False
        self.venue_locations: List[Tuple[float, float]] = []
        self.entrance_locations: List[Tuple[float, float]] = []
        self.amenity_entrance_locations: List[Tuple[float, float]] = []
        self._entrance_grid: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
        self._amenity_spawn_elapsed = 10.0
        self.buildings: List = []
        self._building_grid: Dict[Tuple[int, int], List] = {}
        self._building_grid_cell_size = 100.0
        # _point_near_building's deduplicated per-cell-window building list,
        # keyed by the (min_cx, max_cx, min_cy, max_cy) window - see that
        # method's docstring. Cleared whenever _building_grid itself is
        # rebuilt (set_venue_buildings), never otherwise.
        self._near_building_window_cache: Dict[Tuple[int, int, int, int], List] = {}
        self.vomit_puddles: List[Tuple[float, float]] = []

        self.activity_manager = ActivityManager()
        self.scenery_objects: List[SceneryObject] = []
        self.sceneries: List[Scenery] = []
        self._scenery_object_grid: Dict[Tuple[int, int], List[SceneryObject]] = {}
        self._scenery_grid: Dict[Tuple[int, int], List[Scenery]] = {}
        self._activity_grid_cell_size = 100.0

        self.ped_ways: List[Way] = []
        self._spawn_ways: List[Way] = []
        # id(way) for way in self.ped_ways, kept up to date wherever
        # ped_ways is (re)built - spawn_pedestrian() used to recompute this
        # set from scratch on every single spawn *attempt* (not just
        # successful spawns), which against a real city-scale ped_ways
        # (tens of thousands of ways after autofetch has grown the map)
        # dominated the whole 5-second population-update pass: ~300 wasted
        # attempts x rebuilding a tens-of-thousands-entry set each time.
        self._ped_way_ids: Set[int] = set()
        self._way_grid: Dict[Tuple[int, int], List[Way]] = {}
        self._way_grid_cell_size: float = 100.0
        self._route_nodes: List[Tuple[float, float]] = []
        self._route_edges: Dict[int, List[Tuple[int, float]]] = {}
        self.network = PedestrianNetwork()
        self._junction_grid: Dict[Tuple[int, int], List[Tuple[Way, int, Tuple[float, float], int, int]]] = {}
        self._junction_grid_cell_size: float = 20.0
        self._traffic_light_grid: Dict[Tuple[int, int], List[TrafficLight]] = {}
        self._traffic_light_grid_cell_size: float = 60.0
        self._crossing_grid: Dict[Tuple[int, int], List[Crossing]] = {}
        self._source_ways: List[Way] = []

        self.set_venue_buildings(venue_buildings)
        self.set_scenery_features(scenery_objects, sceneries, bus_stops)
        self.sync_map_data(
            ways,
            traffic_lights=traffic_lights,
            crossings=crossings,
            logical_intersections=logical_intersections,
        )

    def _register_resident(self, pedestrian: Pedestrian) -> Pedestrian:
        if pedestrian.resident_id is None:
            pedestrian.resident_id = self.residents.create("walking").resident_id
        return pedestrian

    def add_pedestrian(self, pedestrian: Pedestrian) -> bool:
        """Keep one active pedestrian per resident."""
        if pedestrian.resident_id is not None and any(
            candidate.resident_id == pedestrian.resident_id
            for candidate in self.pedestrians
        ):
            return False
        self.pedestrians.append(pedestrian)
        return True

    def _materialize_parked_drivers(self) -> None:
        """Keep a parked NPC vehicle empty while placing every trip-group
        member beside the car (multi-passenger-car.md sections 7-11) - one
        pedestrian per member, not just a single "owner", each walking to
        the *same* shared building entrance (picked once per group, cached
        on TripGroup.destination_entrance)."""
        vehicles = self.traffic_manager.npcs if self.traffic_manager is not None else self.traffic_vehicles
        linked_residents = {
            pedestrian.resident_id
            for pedestrian in self.pedestrians
            if pedestrian.resident_id is not None
        }
        for vehicle in vehicles:
            if getattr(vehicle, "state", "driving") != NPCState.PARKED:
                continue
            trip_group = getattr(vehicle, "trip_group", None)
            if trip_group is None or not self.entrance_locations:
                continue
            pending_members = [
                resident_id for resident_id in trip_group.member_resident_ids
                if resident_id not in linked_residents
            ]
            if not pending_members:
                continue
            entry_x, entry_y = self._vehicle_entry_position(vehicle)
            if trip_group.destination_entrance is None:
                trip_group.destination_entrance = min(
                    self.entrance_locations,
                    key=lambda entrance: math.hypot(entrance[0] - entry_x, entrance[1] - entry_y),
                )
            total_members = len(trip_group.member_resident_ids)
            for resident_id in pending_members:
                index = trip_group.member_resident_ids.index(resident_id)
                spawn_x, spawn_y = _fanned_out_position(
                    entry_x, entry_y, index, total_members, heading=getattr(vehicle, "heading", 0.0),
                )
                pedestrian = self.spawn_pedestrian_at(spawn_x, spawn_y, getattr(vehicle, "heading", 0.0))
                if pedestrian is None:
                    # The fanned-out point landed somewhere with no nearby
                    # walkable way - fall back to the exact entry point
                    # (a minor overlap between members is fine; not
                    # spawning the passenger at all is not).
                    pedestrian = self.spawn_pedestrian_at(entry_x, entry_y, getattr(vehicle, "heading", 0.0))
                if pedestrian is None:
                    continue
                pedestrian.resident_id = resident_id
                pedestrian.linked_vehicle_id = id(vehicle)
                pedestrian.linked_building_entrance = trip_group.destination_entrance
                pedestrian.destination = trip_group.destination_entrance
                # spawn_pedestrian_at above set route/current_route_segment
                # for its own generic walk-along-the-way purpose - clear them
                # so _walk_route_to builds a real footway route to the
                # entrance instead of treating that leftover route's
                # (unrelated) endpoint as "arrived".
                pedestrian.route = None
                pedestrian.state = "walking_to_building"
                pedestrian.animation_state = "walking"
                pedestrian.door_grace_timer = 5.0
                trip_group.boarded_resident_ids.discard(resident_id)
                self.add_pedestrian(pedestrian)
                linked_residents.add(resident_id)

    def _walk_route_to(self, pedestrian: Pedestrian, update_dt: float, target: Tuple[float, float]) -> bool:
        """Step `pedestrian` along a footway route toward `target`, building
        the route on first call (same mapped-sidewalk network as an
        ordinary pedestrian's vehicle approach) so a trip-group member
        walks around buildings/parked cars instead of straight through
        them. Returns True once `target` is reached."""
        if pedestrian.route is None or pedestrian.destination != target:
            pedestrian.destination = target
            pedestrian.route = self._footway_route_to(pedestrian, target)
            pedestrian.current_route_segment = 1
        route = pedestrian.route
        route_index = min(max(1, pedestrian.current_route_segment), len(route) - 1)
        target_x, target_y = route[route_index]
        distance = math.hypot(target_x - pedestrian.x, target_y - pedestrian.y)
        if distance <= 1.0:
            pedestrian.x, pedestrian.y = target_x, target_y
            pedestrian.current_route_segment = route_index + 1
            if pedestrian.current_route_segment < len(route):
                return False
            pedestrian.speed = 0.0
            pedestrian.route = None
            return True
        pedestrian.heading = math.atan2(target_y - pedestrian.y, target_x - pedestrian.x)
        pedestrian.speed = pedestrian.base_speed
        step = min(distance, pedestrian.speed * update_dt)
        pedestrian.x += math.cos(pedestrian.heading) * step
        pedestrian.y += math.sin(pedestrian.heading) * step
        pedestrian.animation_state = "walking"
        return False

    def set_scenery_features(
        self,
        scenery_objects: Optional[List[SceneryObject]] = None,
        sceneries: Optional[List[Scenery]] = None,
        bus_stops: Optional[List[BusStop]] = None,
    ) -> None:
        """Index benches/waste-baskets/parks/bus stops etc. for the
        activity system's nearby_* queries (residents-live.md) - the same
        bbox/cell-grid idiom set_venue_buildings already uses for
        _building_grid. bus_stops stays a plain list, not gridded - city
        bus-stop counts are small enough that the same linear-filter
        idiom self.crossings/venue_locations already use elsewhere in
        this file is plenty."""
        self.scenery_objects = list(scenery_objects or [])
        self.sceneries = list(sceneries or [])
        self.bus_stops = list(bus_stops or [])
        cell_size = self._activity_grid_cell_size
        self._scenery_object_grid = {}
        for scenery_object in self.scenery_objects:
            cell = (math.floor(scenery_object.x / cell_size), math.floor(scenery_object.y / cell_size))
            self._scenery_object_grid.setdefault(cell, []).append(scenery_object)
        self._scenery_grid = {}
        for scenery in self.sceneries:
            bbox = getattr(scenery, "bbox", None)
            if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
                continue
            for cell_x in range(math.floor(bbox[0] / cell_size), math.floor(bbox[2] / cell_size) + 1):
                for cell_y in range(math.floor(bbox[1] / cell_size), math.floor(bbox[3] / cell_size) + 1):
                    self._scenery_grid.setdefault((cell_x, cell_y), []).append(scenery)

    def nearby_scenery_objects(self, x: float, y: float, radius_m: float) -> List[SceneryObject]:
        """Point-furniture (bench/waste-basket/...) within radius_m -
        activity plugins filter the result by .kind themselves; this
        method has no notion of which kinds exist."""
        cell_size = self._activity_grid_cell_size
        span = math.ceil(radius_m / cell_size)
        cell_x, cell_y = math.floor(x / cell_size), math.floor(y / cell_size)
        radius_sq = radius_m * radius_m
        found = []
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                for scenery_object in self._scenery_object_grid.get((cell_x + dx, cell_y + dy), ()):
                    if (scenery_object.x - x) ** 2 + (scenery_object.y - y) ** 2 <= radius_sq:
                        found.append(scenery_object)
        return found

    def nearby_sceneries(self, x: float, y: float, radius_m: float) -> List[Scenery]:
        """Area features (parks/grass/...) whose bbox is within radius_m -
        activity plugins filter by .kind themselves."""
        cell_size = self._activity_grid_cell_size
        span = math.ceil(radius_m / cell_size)
        cell_x, cell_y = math.floor(x / cell_size), math.floor(y / cell_size)
        seen: Set[int] = set()
        found = []
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                for scenery in self._scenery_grid.get((cell_x + dx, cell_y + dy), ()):
                    if id(scenery) not in seen:
                        seen.add(id(scenery))
                        found.append(scenery)
        return found

    def _activity_context(self, pedestrian: Pedestrian) -> ActivityContext:
        return ActivityContext(
            pedestrian=pedestrian,
            pedestrian_manager=self,
            residents=self.residents,
            sim_time=self.sim_time,
        )

    def _consider_activities(self) -> None:
        """Periodically (called from the existing 5s population-management
        tick, not every frame) roll ordinary walking pedestrians for a new
        ambient activity. A pedestrian mid vehicle-passenger-lifecycle
        (linked_vehicle_id) must never also be mid-activity - that state
        is exclusively owned by _update_linked_driver."""
        for pedestrian in self.pedestrians:
            if (
                pedestrian.state != "walking"
                or pedestrian.activity is not None
                or pedestrian.linked_vehicle_id is not None
                or pedestrian.reserved_vehicle_id is not None
                or pedestrian.current_vehicle_id is not None
                or pedestrian.is_cyclist
                or pedestrian.is_drunk
                or pedestrian.wants_taxi
                or pedestrian.wants_vehicle
                or pedestrian.is_walking_to_taxi_stop
                or pedestrian.is_taxi_stop_waiter
            ):
                continue
            if random.random() >= ACTIVITY_CONSIDER_PROBABILITY:
                continue
            selected = self.activity_manager.select_activity(self._activity_context(pedestrian))
            if selected is None:
                continue
            plugin, location = selected
            pedestrian.activity = ActivityInstance(
                plugin_id=plugin.definition.id, location=location, started_sim_time=self.sim_time
            )
            pedestrian.state = "walking_to_activity"
            pedestrian.route = None

    def _update_activity(self, pedestrian: Pedestrian, update_dt: float) -> bool:
        """Drive an already-selected activity to completion (mirrors
        _update_linked_driver's shape: owns the pedestrian for the frame,
        callers `continue` when this returns True). Never decides to
        *start* an activity - only _consider_activities does that."""
        instance = pedestrian.activity
        if instance is None:
            return False
        plugin = self.activity_manager.registry.get(instance.plugin_id)
        if plugin is None:
            self._end_activity(pedestrian, instance)
            return False
        context = self._activity_context(pedestrian)
        if pedestrian.state == "walking_to_activity":
            arrived = (
                instance.location is None
                or self._walk_route_to(pedestrian, update_dt, (instance.location.x, instance.location.y))
            )
            if arrived:
                pedestrian.state = "performing_activity"
                pedestrian.speed = 0.0
                pedestrian.animation_state = "idle"
                plugin.start(context, instance)
            return True
        if pedestrian.state == "performing_activity":
            pedestrian.speed = 0.0
            if plugin.update(context, instance, update_dt):
                plugin.finish(context, instance)
                self._end_activity(pedestrian, instance)
            return True
        self._end_activity(pedestrian, instance)  # defensive: state drifted unexpectedly
        return False

    def _end_activity(self, pedestrian: Pedestrian, instance: ActivityInstance) -> None:
        self.activity_manager.release(instance.location)
        pedestrian.activity_flags["last_activity_id"] = instance.plugin_id
        pedestrian.activity_flags["last_activity_end_time"] = self.sim_time
        pedestrian.activity = None
        pedestrian.state = "walking"
        pedestrian.animation_state = "walking"

    def _update_linked_driver(self, pedestrian: Pedestrian, update_dt: float) -> bool:
        """Move one trip-group member between the shared destination
        building and its own group's vehicle (multi-passenger-car.md
        sections 9-15, 19). Each Pedestrian is independent, so this same
        function already serves however many members of the group are
        currently linked - it only ever reads/writes the one instance
        passed in."""
        if pedestrian.linked_vehicle_id is None:
            return False
        vehicles = self.traffic_manager.npcs if self.traffic_manager is not None else self.traffic_vehicles
        vehicle = next((candidate for candidate in vehicles if id(candidate) == pedestrian.linked_vehicle_id), None)
        trip_group = getattr(vehicle, "trip_group", None) if vehicle is not None else None
        if vehicle is None or trip_group is None:
            pedestrian.linked_vehicle_id = None
            return False
        if pedestrian.state == "walking_to_building":
            target = pedestrian.linked_building_entrance
            if target is None:
                return False
            if self._walk_route_to(pedestrian, update_dt, target):
                pedestrian.state = PedestrianState.ENTERING_BUILDING.value
                pedestrian.building_entry_timer = 0.35
                pedestrian.building_visit_timer = trip_group.activity_duration_s
                pedestrian.animation_state = "idle"
            return True
        if pedestrian.state == PedestrianState.ENTERING_BUILDING.value:
            pedestrian.speed = 0.0
            pedestrian.building_entry_timer = max(0.0, pedestrian.building_entry_timer - update_dt)
            if pedestrian.building_entry_timer <= 0.0:
                pedestrian.state = PedestrianState.IN_BUILDING.value
                pedestrian.animation_state = "idle"
            return True
        if pedestrian.state == PedestrianState.IN_BUILDING.value:
            pedestrian.building_visit_timer = max(0.0, pedestrian.building_visit_timer - update_dt)
            if pedestrian.building_visit_timer <= 0.0:
                pedestrian.state = "returning_to_vehicle"
            return True
        if pedestrian.state == "returning_to_vehicle":
            target = self._vehicle_entry_position(vehicle)
            if self._walk_route_to(pedestrian, update_dt, target):
                pedestrian.state = PedestrianState.ENTERING_VEHICLE.value
                pedestrian.vehicle_entry_timer = 0.4
                pedestrian.animation_state = "idle"
            return True
        if pedestrian.state == PedestrianState.ENTERING_VEHICLE.value:
            # multi-passenger-car.md section 19: a *group* reboard - not
            # the single-exclusive-claimant reservation dance
            # reserve_parked_vehicle/enter_reserved_vehicle use, which
            # would deadlock members 2..N against vehicle.state no longer
            # being NPCState.PARKED once the first member reboards. Each
            # member instead just marks itself boarded and despawns -
            # npc.update_npc/continue_npc_trip is what actually decides
            # when the vehicle leaves (once trip_group.all_aboard).
            pedestrian.speed = 0.0
            pedestrian.vehicle_entry_timer = max(0.0, pedestrian.vehicle_entry_timer - update_dt)
            if pedestrian.vehicle_entry_timer <= 0.0:
                trip_group.boarded_resident_ids.add(pedestrian.resident_id)
                pedestrian.state = PedestrianState.DESPAWNING.value
                pedestrian.linked_vehicle_id = None
            return True
        return False

    def set_venue_buildings(self, buildings: Optional[List] = None) -> None:
        """Index hospitality venues as preferred pedestrian spawn locations."""
        self.buildings = list(buildings or [])
        self.venue_locations = []
        self.entrance_locations = []
        self.amenity_entrance_locations = []
        self._entrance_grid = {}
        self._building_grid = {}
        self._near_building_window_cache = {}
        for building in buildings or []:
            bbox = getattr(building, "bbox", None)
            if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
                cell_size = self._building_grid_cell_size
                for cell_x in range(math.floor(bbox[0] / cell_size), math.floor(bbox[2] / cell_size) + 1):
                    for cell_y in range(math.floor(bbox[1] / cell_size), math.floor(bbox[3] / cell_size) + 1):
                        self._building_grid.setdefault((cell_x, cell_y), []).append(building)
            entrances = getattr(building, "entrances", ())
            self.entrance_locations.extend(entrances)
            if getattr(building, "venue_type", None):
                self.amenity_entrance_locations.extend(entrances)
            if getattr(building, "venue_type", None) not in VENUE_TYPES or len(building.points_m) < 3:
                continue
            self.venue_locations.append(
                (
                    sum(point[0] for point in building.points_m) / len(building.points_m),
                    sum(point[1] for point in building.points_m) / len(building.points_m),
                )
            )
        for entrance_x, entrance_y in self.entrance_locations:
            cell = (
                int(math.floor(entrance_x / self._way_grid_cell_size)),
                int(math.floor(entrance_y / self._way_grid_cell_size)),
            )
            self._entrance_grid.setdefault(cell, []).append((entrance_x, entrance_y))
        if self._source_ways:
            self.sync_map_data(
                self._source_ways,
                traffic_lights=self.traffic_lights,
                crossings=self.crossings,
                logical_intersections=self.logical_intersections,
            )

    def _point_inside_building(self, x: float, y: float) -> bool:
        """Return whether a point is inside a mapped building footprint."""
        cell_size = self._building_grid_cell_size
        cell = (math.floor(x / cell_size), math.floor(y / cell_size))
        for building in self._building_grid.get(cell, ()):
            min_x, min_y, max_x, max_y = building.bbox
            if min_x <= x <= max_x and min_y <= y <= max_y and point_in_polygon(x, y, building.points_m):
                return True
        return False

    def _path_crosses_building(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        """Whether the straight line from (x1,y1) to (x2,y2) passes
        through a building's interior. Sampled strictly between the
        endpoints (0.2/0.4/0.6/0.8), never at the endpoints themselves -
        one end is often a door/entrance/vehicle position sitting exactly
        on a building's own wall line, where point-in-polygon is a coin
        flip and irrelevant to whether the path itself cuts through the
        building. Used wherever a pedestrian's next step is a raw (x, y)
        point rather than an already-safe mapped-way segment (see
        spawn_pedestrian_at's nearest-way search and _footway_route_to's
        final approach hop)."""
        return any(
            self._point_inside_building(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
            for t in (0.2, 0.4, 0.6, 0.8)
        )

    def _segment_inside_building(self, start: Tuple[float, float], end: Tuple[float, float]) -> bool:
        """Return whether a walkable segment enters a building footprint."""
        for progress in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = start[0] + (end[0] - start[0]) * progress
            y = start[1] + (end[1] - start[1]) * progress
            if self._point_inside_building(x, y):
                return True
        return False

    def _building_free_ways(self, ways: List[Way]) -> List[Way]:
        """Split mapped ways so pedestrian routes cannot cross building interiors."""
        if not self._building_grid:
            return ways
        safe_ways: List[Way] = []
        for way in ways:
            way_safe_ways: List[Way] = []
            safe_points: List[Tuple[float, float]] = []
            for start, end in zip(way.points_m, way.points_m[1:]):
                if self._segment_inside_building(start, end):
                    if len(safe_points) >= 2:
                        way_safe_ways.append(replace(way, points_m=safe_points, bbox=compute_bbox(safe_points)))
                    safe_points = []
                    continue
                if not safe_points:
                    safe_points = [start]
                safe_points.append(end)
            if len(safe_points) >= 2:
                way_safe_ways.append(replace(way, points_m=safe_points, bbox=compute_bbox(safe_points)))
            safe_ways.extend(way_safe_ways or [way])
        return safe_ways

    def _point_near_building(self, x: float, y: float, radius_m: float = 250.0) -> bool:
        """Return whether a point is near a mapped building.

        The deduplicated candidate-building list for a given cell window is
        cached (self._near_building_window_cache, keyed by the window
        itself and cleared whenever _building_grid is rebuilt - see
        set_venue_buildings). spawn_pedestrian's retry loop calls this for
        every candidate point tried along a segment - up to 8 per segment,
        for up to 30 candidate ways per spawn attempt - and nearby points
        along the same short segment overwhelmingly land in the exact same
        window. Confirmed via profiling a real drive: ~1M id() calls across
        2100 calls to this method in one slow population-update pass,
        almost entirely re-deriving the same handful of distinct windows
        over and over."""
        cell_size = self._building_grid_cell_size
        min_cell_x = math.floor((x - radius_m) / cell_size)
        max_cell_x = math.floor((x + radius_m) / cell_size)
        min_cell_y = math.floor((y - radius_m) / cell_size)
        max_cell_y = math.floor((y + radius_m) / cell_size)
        window_key = (min_cell_x, max_cell_x, min_cell_y, max_cell_y)
        building_data = self._near_building_window_cache.get(window_key)
        if building_data is None:
            building_data = []
            seen = set()
            for cell_x in range(min_cell_x, max_cell_x + 1):
                for cell_y in range(min_cell_y, max_cell_y + 1):
                    for building in self._building_grid.get((cell_x, cell_y), ()):
                        if id(building) not in seen:
                            seen.add(id(building))
                            building_data.append(building)
            self._near_building_window_cache[window_key] = building_data
        if not building_data:
            return not self._building_grid
        radius_sq = radius_m * radius_m
        for building in building_data:
            min_x, min_y, max_x, max_y = building.bbox
            nearest_x = min(max(x, min_x), max_x)
            nearest_y = min(max(y, min_y), max_y)
            if (x - nearest_x) ** 2 + (y - nearest_y) ** 2 <= radius_sq:
                return True
        return False

    def _choose_destination(self, x: float, y: float, way: Way, direction: int) -> Tuple[float, float]:
        """Choose a mapped entrance when available, otherwise a route endpoint."""
        candidates = [
            entrance
            for entrance in self.entrance_locations
            if math.hypot(entrance[0] - x, entrance[1] - y) > 5.0
        ]
        if candidates and random.random() < 0.35:
            return random.choice(candidates)
        return way.points_m[-1] if direction == 1 else way.points_m[0]

    def find_available_parked_vehicle(self, x: float, y: float, radius_m: float = 100.0):
        """Find the nearest reusable parked vehicle from the supplied vehicle source."""
        if self.traffic_manager is not None:
            vehicles = self.traffic_manager.nearby_npcs_at(x, y)
        else:
            vehicles = self.traffic_vehicles
        candidates = [
            vehicle
            for vehicle in vehicles
            if getattr(vehicle, "state", "driving") == "parked"
            and getattr(vehicle, "reserved_by_pedestrian_id", None) is None
            and getattr(vehicle, "current_driver_id", None) is None
            # multi-passenger-car.md section 16: never let this generic
            # "grab any nearby idle vehicle" mechanic claim a vehicle that
            # belongs to a trip group - its own members must be the only
            # ones who ever reboard it (see _update_linked_driver).
            and getattr(vehicle, "trip_group", None) is None
            and math.hypot(vehicle.x - x, vehicle.y - y) <= radius_m
        ]
        return min(candidates, key=lambda vehicle: math.hypot(vehicle.x - x, vehicle.y - y), default=None)

    def reserve_parked_vehicle(self, pedestrian: Pedestrian, vehicle) -> bool:
        """Reserve any suitable parked vehicle without assuming prior ownership."""
        if getattr(vehicle, "state", "driving") != "parked":
            return False
        if getattr(vehicle, "reserved_by_pedestrian_id", None) is not None:
            return False
        if math.hypot(vehicle.x - pedestrian.x, vehicle.y - pedestrian.y) > MAX_VEHICLE_RESERVATION_DISTANCE_M:
            return False
        vehicle.reserved_by_pedestrian_id = id(pedestrian)
        vehicle.state = "reserved"
        pedestrian.reserved_vehicle_id = id(vehicle)
        pedestrian.destination = self._vehicle_entry_position(vehicle)
        pedestrian.route = self._footway_route_to(pedestrian, pedestrian.destination)
        pedestrian.current_route_segment = 1
        pedestrian.state = "approaching_vehicle"
        pedestrian.animation_state = "walking"
        return True

    def _footway_route_to(
        self,
        pedestrian: Pedestrian,
        entry_position: Tuple[float, float],
    ) -> List[Tuple[float, float]]:
        """Build a short mapped-footway approach followed by the final door
        step, from wherever `pedestrian` currently stands to `entry_position`
        (a vehicle's door or a building's entrance - the network routing
        doesn't care which).

        The final hop from the nearest mapped footway point to
        `entry_position` is a straight line, not routed - reject a
        candidate footway point where that line would cut through a
        building (closer as the crow flies than the actual door-side
        footway is a common shape: a service alley right behind the
        building, an open plaza in front, ...), same as
        spawn_pedestrian_at's nearest-way search.
        """
        nearest = self.network.nearest_point(
            entry_position,
            reject=lambda x, y: self._path_crosses_building(entry_position[0], entry_position[1], x, y),
        )
        start = (pedestrian.x, pedestrian.y)
        route = self._plan_pedestrian_route(start, nearest) if nearest is not None else [start]
        if math.hypot(entry_position[0] - route[-1][0], entry_position[1] - route[-1][1]) > 0.01:
            route.append(entry_position)
        return route

    def _build_route_graph(self) -> None:
        """Build a small undirected graph from mapped pedestrian-way vertices."""
        self.network.set_ways(self.ped_ways)
        self._route_nodes = self.network.nodes
        self._route_edges = self.network.edges

    def _plan_pedestrian_route(
        self,
        start: Tuple[float, float],
        target: Tuple[float, float],
    ) -> List[Tuple[float, float]]:
        """Return a shortest mapped-footway route with direct endpoint connectors."""
        return self.network.route(start, target)

    @staticmethod
    def _vehicle_entry_position(vehicle) -> Tuple[float, float]:
        """Return a walkable point beside the vehicle's passenger side."""
        offset = getattr(vehicle, "width_m", 1.8) * 0.5 + 1.0
        heading = getattr(vehicle, "heading", 0.0)
        return (
            vehicle.x - math.sin(heading) * offset,
            vehicle.y + math.cos(heading) * offset,
        )

    def cancel_vehicle_reservation(self, pedestrian: Pedestrian) -> None:
        """Release any vehicle reservation owned by a pedestrian."""
        vehicle_id = pedestrian.reserved_vehicle_id
        if vehicle_id is None:
            return
        vehicles = self.traffic_manager.npcs if self.traffic_manager is not None else self.traffic_vehicles
        for vehicle in vehicles:
            if id(vehicle) == vehicle_id and getattr(vehicle, "reserved_by_pedestrian_id", None) == id(pedestrian):
                vehicle.reserved_by_pedestrian_id = None
                if vehicle.state == "reserved":
                    vehicle.state = "parked"
                break
        pedestrian.reserved_vehicle_id = None

    def enter_reserved_vehicle(self, pedestrian: Pedestrian, vehicle) -> bool:
        """Complete a reserved pedestrian-to-vehicle entry without creating entities."""
        if (
            pedestrian.reserved_vehicle_id != id(vehicle)
            or vehicle.state != "reserved"
            or math.hypot(vehicle.x - pedestrian.x, vehicle.y - pedestrian.y) > 3.0
        ):
            return False
        vehicle.current_driver_id = id(pedestrian)
        vehicle.reserved_by_pedestrian_id = None
        vehicle.state = "occupied"
        if self.residents is not None and pedestrian.resident_id is not None:
            vehicle.owner_id = pedestrian.resident_id
            resident = self.residents.get(pedestrian.resident_id)
            if resident is not None:
                resident.mode = "driving"
                resident.active_vehicle_id = id(vehicle)
        vehicle_way = getattr(vehicle, "way", None)
        vehicle_points = getattr(vehicle_way, "points_m", ())
        if len(vehicle_points) >= 2:
            pedestrian.vehicle_destination = (
                vehicle_points[-1] if getattr(vehicle, "direction", 1) == 1 else vehicle_points[0]
            )
        pedestrian.reserved_vehicle_id = None
        pedestrian.current_vehicle_id = id(vehicle)
        if pedestrian.linked_vehicle_id == id(vehicle):
            pedestrian.linked_vehicle_id = None
            pedestrian.linked_building_entrance = None
            pedestrian.building_visit_timer = 0.0
            pedestrian.vehicle_destination = None
        pedestrian.x = vehicle.x
        pedestrian.y = vehicle.y
        pedestrian.state = "in_vehicle"
        pedestrian.animation_state = "idle"
        return True

    def exit_vehicle(self, pedestrian: Pedestrian, vehicle, animate: bool = False) -> bool:
        """Return a pedestrian beside an occupied vehicle and resume normal driving."""
        if (
            pedestrian.current_vehicle_id != id(vehicle)
            or getattr(vehicle, "current_driver_id", None) != id(pedestrian)
            or getattr(vehicle, "state", "driving") != "occupied"
        ):
            return False
        pedestrian.x, pedestrian.y = self._vehicle_entry_position(vehicle)
        pedestrian.current_vehicle_id = None
        pedestrian.reserved_vehicle_id = None
        pedestrian.vehicle_destination = None
        pedestrian.destination = None
        pedestrian.speed = 0.0
        pedestrian.state = (
            PedestrianState.EXITING_VEHICLE.value if animate else PedestrianState.WALKING.value
        )
        pedestrian.animation_state = "walking"
        pedestrian.vehicle_entry_timer = 0.35 if animate else 0.0
        if self.traffic_manager is not None:
            self.traffic_manager.activate_occupied_vehicle(vehicle)
        else:
            vehicle.current_driver_id = None
            vehicle.state = "driving"
        return True

    def _at_building_entrance(self, x: float, y: float, radius_m: float = 1.5) -> bool:
        """Check nearby doors without scanning every mapped entrance."""
        cell_size = self._way_grid_cell_size
        cell_x = int(math.floor(x / cell_size))
        cell_y = int(math.floor(y / cell_size))
        radius_sq = radius_m * radius_m
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for entrance_x, entrance_y in self._entrance_grid.get((cell_x + offset_x, cell_y + offset_y), ()):
                    if (x - entrance_x) ** 2 + (y - entrance_y) ** 2 <= radius_sq:
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

    def sync_map_data(
        self,
        ways: List[Way],
        traffic_lights: Optional[List[TrafficLight]] = None,
        crossings: Optional[List[Crossing]] = None,
        logical_intersections: Optional[List[LogicalIntersection]] = None,
    ) -> None:
        """Update road/path network and rebuild spatial grids for pedestrian routing."""
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights
        if crossings is not None:
            self.crossings = crossings
        if logical_intersections is not None:
            self.logical_intersections = logical_intersections

        self._traffic_light_grid.clear()
        signal_cell_size = self._traffic_light_grid_cell_size
        for traffic_light in self.traffic_lights:
            cell = (
                int(math.floor(traffic_light.x / signal_cell_size)),
                int(math.floor(traffic_light.y / signal_cell_size)),
            )
            self._traffic_light_grid.setdefault(cell, []).append(traffic_light)
        self._crossing_grid.clear()
        for crossing in self.crossings:
            cell = (
                int(math.floor(crossing.x / signal_cell_size)),
                int(math.floor(crossing.y / signal_cell_size)),
            )
            self._crossing_grid.setdefault(cell, []).append(crossing)

        # Prefer dedicated pedestrian paths (footway, path, pedestrian, cycleway, steps, track, crossing)
        self._source_ways = list(ways)
        dedicated = [w for w in ways if is_pedestrian_way(w) and len(w.points_m) >= 2]
        fallback = [
            w for w in ways
            if getattr(w, "highway", "") in ("residential", "living_street", "unclassified", "service")
            and len(w.points_m) >= 2
        ]
        self.ped_ways = self._building_free_ways(dedicated or fallback)
        self._build_route_graph()
        self._spawn_ways = []
        seen_way_ids: Set[int] = set()
        for way in self.ped_ways:
            if id(way) not in seen_way_ids:
                seen_way_ids.add(id(way))
                self._spawn_ways.append(way)
        self._ped_way_ids = seen_way_ids

        self._way_grid.clear()
        cs = self._way_grid_cell_size
        for w in self._spawn_ways:
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
        new_target_count = max(0, target_count)
        if new_target_count != self.target_count:
            self.target_count = new_target_count
            self._population_update_elapsed = 0.5
        if len(self.pedestrians) > self.target_count:
            if player_car is not None:
                self.pedestrians.sort(key=lambda ped: math.hypot(ped.x - player_car.x, ped.y - player_car.y))
            for dropped in self.pedestrians[self.target_count:]:
                if dropped.activity is not None:
                    self.activity_manager.release(dropped.activity.location)
            del self.pedestrians[self.target_count:]

    def update_lod(self, player_car: Car, dt: float) -> None:
        """Schedule pedestrian simulation using distance bands."""
        for pedestrian in self.pedestrians:
            distance = math.hypot(pedestrian.x - player_car.x, pedestrian.y - player_car.y)
            pedestrian.lod_level = 0 if distance < 500.0 else 1 if distance < 1500.0 else 2
            pedestrian.lod_time_accumulator += dt
            interval = PEDESTRIAN_LOD_UPDATE_INTERVALS[pedestrian.lod_level]
            if pedestrian.lod_update_due or pedestrian.lod_time_accumulator >= interval:
                pedestrian.lod_update_dt = pedestrian.lod_time_accumulator
                pedestrian.lod_update_due = True
                pedestrian.lod_time_accumulator = 0.0
            else:
                pedestrian.lod_update_due = False
            self.residents.update_lod(
                pedestrian.resident_id,
                pedestrian.x,
                pedestrian.y,
                player_car.x,
                player_car.y,
                dt,
            )

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
                self.add_pedestrian(waiter)
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
                    self.add_pedestrian(customer)

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
        if viewport_bounds is not None:
            vminx, vminy, vmaxx, vmaxy = viewport_bounds
            if vminx <= near_x - r and near_x + r <= vmaxx and vminy <= near_y - r and near_y + r <= vmaxy:
                # The whole spawn_radius_m search area already sits inside
                # the viewport, so every candidate point the retry loop
                # below would generate is guaranteed to fail its "outside
                # viewport" check anyway - at low zoom (viewport wider than
                # 2x spawn_radius_m), this was burning the entire retry
                # budget (up to 30 candidate ways x every segment x 8
                # points each) on attempts that could never have
                # succeeded, every single one of the (up to
                # max(50, target_count*5)) attempts update() makes per
                # 5-second population pass.
                return None
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

        valid_ways = []
        for w in nearby_ways:
            for p in w.points_m:
                if (p[0] - near_x) ** 2 + (p[1] - near_y) ** 2 <= r * r:
                    valid_ways.append(w)
                    break

        if not nearby_ways or not valid_ways:
            fallback_radius = max(r, 1000.0)
            fallback_radius_sq = fallback_radius * fallback_radius
            nearest_ways = sorted(
                self._spawn_ways,
                key=lambda way: min(
                    (point[0] - near_x) ** 2 + (point[1] - near_y) ** 2
                    for point in way.points_m
                ),
            )
            valid_ways = [
                way for way in nearest_ways
                if min(
                    (point[0] - near_x) ** 2 + (point[1] - near_y) ** 2
                    for point in way.points_m
                ) <= fallback_radius_sq
            ][:30]
            if not valid_ways:
                return None

        # self._ped_way_ids is exactly {id(way) for way in self.ped_ways},
        # kept up to date in sync_map_data() - rebuilding that set here
        # instead, on every single spawn *attempt* (not just successful
        # ones - see the retry loop in update()), was the actual cost of
        # the periodic population-update freeze: against a real city-scale
        # ped_ways this one line dominated the whole 5-second pass.
        valid_ways.sort(key=lambda way: 0 if id(way) in self._ped_way_ids else 1)

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

                    if self._point_inside_building(x, y):
                        continue
                    if not self._point_near_building(x, y):
                        continue

                    if random.random() > self.residents.density_spawn_probability(x, y):
                        continue

                    if max_distance_m is not None and math.hypot(x - near_x, y - near_y) > max_distance_m:
                        continue

                    # Sanity check: do not spawn directly on top of player car
                    if math.hypot(x - near_x, y - near_y) < 3.0:
                        continue

                    # Sanity check: do not cluster pedestrians on top of each other
                    if any(math.hypot(x - p.x, y - p.y) < 0.5 for p in self.pedestrians):
                        continue

                    pedestrian = Pedestrian(
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
                        wants_vehicle=random.random() < 0.05,
                        appearance=PedestrianAppearance(body=color),
                    )
                    pedestrian.route = list(chosen_way.points_m)
                    pedestrian.current_route_segment = seg_idx
                    pedestrian.destination = self._choose_destination(x, y, chosen_way, direction)
                    return self._register_resident(pedestrian)

        return None

    def _nearby_ped_ways(self, x: float, y: float) -> List[Way]:
        """Return ped_ways within an expanding radius of (x, y) via
        self._way_grid, instead of the full self.ped_ways list.

        spawn_pedestrian_at() used to scan every mapped walkable way (tens
        of thousands once autofetch has grown the map) to find the single
        nearest segment to one door/entrance point - real cost, confirmed
        via profiling a real drive: ~20000 closest_point_and_dist_to_segment
        calls per spawn_pedestrian_at() call, dominating the periodic
        population-update pass. spawn_pedestrian() (the other spawn path)
        already avoided this via the same self._way_grid; this gives
        spawn_pedestrian_at() the same locality.
        """
        cs = self._way_grid_cell_size
        radius = cs * 2.0
        max_radius = max(self.spawn_radius_m, 1000.0) * 2.0
        while radius <= max_radius:
            min_cx = int(math.floor((x - radius) / cs))
            max_cx = int(math.floor((x + radius) / cs))
            min_cy = int(math.floor((y - radius) / cs))
            max_cy = int(math.floor((y + radius) / cs))
            seen: Set[int] = set()
            nearby: List[Way] = []
            for cx in range(min_cx, max_cx + 1):
                for cy in range(min_cy, max_cy + 1):
                    for w in self._way_grid.get((cx, cy), ()):
                        if id(w) not in seen:
                            seen.add(id(w))
                            nearby.append(w)
            if nearby:
                return nearby
            radius *= 2.0
        return self._spawn_ways

    def spawn_pedestrian_at(
        self,
        x: float,
        y: float,
        heading: float = 0.0,
        resident_id: Optional[int] = None,
        allow_building_interior: bool = False,
    ) -> Optional[Pedestrian]:
        """Create an ordinary pedestrian at a specific location on the nearest walkable way."""
        if not self.ped_ways or (not allow_building_interior and self._point_inside_building(x, y)):
            return None

        nearest = None
        for way in self._nearby_ped_ways(x, y):
            for segment_idx, (start, end) in enumerate(zip(way.points_m, way.points_m[1:])):
                closest_x, closest_y, progress, distance = closest_point_and_dist_to_segment(
                    x, y, start[0], start[1], end[0], end[1]
                )
                if nearest is not None and distance >= nearest[0]:
                    continue
                if allow_building_interior and self._path_crosses_building(x, y, closest_x, closest_y):
                    # A door's nearest mapped way by raw distance can sit
                    # on the far side of the building it belongs to (e.g.
                    # a footway along the back, closer as the crow flies
                    # than the one out front) - snapping onto it would
                    # have the spawned pedestrian walk straight through
                    # the building to reach it. Skip it; a farther-but-
                    # actually-reachable way is what should win instead.
                    continue
                nearest = (distance, way, segment_idx, progress)
        if nearest is None:
            return None

        _, way, segment_idx, progress = nearest
        start = way.points_m[segment_idx]
        end = way.points_m[segment_idx + 1]
        segment_heading = math.atan2(end[1] - start[1], end[0] - start[0])
        direction = 1 if math.cos(heading - segment_heading) >= 0.0 else -1
        pedestrian = Pedestrian(
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
            resident_id=resident_id,
        )
        pedestrian.route = list(way.points_m)
        pedestrian.current_route_segment = segment_idx
        pedestrian.destination = self._choose_destination(x, y, way, direction)
        return self._register_resident(pedestrian)

    def spawn_pedestrian_at_door(self, x: float, y: float) -> Optional[Pedestrian]:
        """Create a pedestrian at a mapped building entrance."""
        pedestrian = self.spawn_pedestrian_at(x, y, allow_building_interior=True)
        if pedestrian is None:
            return None
        pedestrian.door_grace_timer = 5.0
        pedestrian.spawned_at_door = True
        return pedestrian

    def _find_nearby_signalized_crossing(self, ped: Pedestrian) -> Optional[Crossing]:
        """Return the nearby signalized crossing, if any."""
        cell_size = self._traffic_light_grid_cell_size
        cell_x = int(math.floor(ped.x / cell_size))
        cell_y = int(math.floor(ped.y / cell_size))
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for crossing in self._crossing_grid.get((cell_x + offset_x, cell_y + offset_y), ()):
                    if (
                        crossing.crossing_type == "traffic_signals"
                        and math.hypot(crossing.x - ped.x, crossing.y - ped.y) <= crossing.width_m
                    ):
                        return crossing
        return None

    def _is_pedestrian_red_light(self, ped: Pedestrian) -> bool:
        """Check if pedestrian is stopped by a red traffic light at an intersection/crossing."""
        crossing_radius = 8.0
        cell_size = self._traffic_light_grid_cell_size
        cell_x = int(math.floor(ped.x / cell_size))
        cell_y = int(math.floor(ped.y / cell_size))
        nearby_crossings = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby_crossings.extend(self._crossing_grid.get((cell_x + offset_x, cell_y + offset_y), ()))

        controlled_crossing = next(
            (
                crossing
                for crossing in nearby_crossings
                if crossing.crossing_type == "traffic_signals"
                and math.hypot(crossing.x - ped.x, crossing.y - ped.y) <= crossing_radius
            ),
            None,
        )
        if controlled_crossing is not None and self.logical_intersections:
            nearest_intersection = min(
                self.logical_intersections,
                key=lambda intersection: math.hypot(
                    intersection.center[0] - controlled_crossing.x,
                    intersection.center[1] - controlled_crossing.y,
                ),
            )
            if math.hypot(
                nearest_intersection.center[0] - controlled_crossing.x,
                nearest_intersection.center[1] - controlled_crossing.y,
            ) <= nearest_intersection.radius_m + crossing_radius:
                signal_states = [
                    approach.signal_group.get_state(self.sim_time)
                    for approach in nearest_intersection.approaches
                    if approach.signal_group is not None
                ]
                if any(state in ("green", "yellow") for state in signal_states):
                    return True
                return not self._crossing_is_safe(controlled_crossing)

        # Sparse OSM data may lack logical intersection records.
        ped_stop_dist = 6.0
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

    def _crossing_is_safe(self, crossing: Crossing) -> bool:
        """Keep pedestrians waiting when a moving vehicle is close to the crossing."""
        for vehicle in self.traffic_vehicles:
            distance = math.hypot(vehicle.x - crossing.x, vehicle.y - crossing.y)
            if distance <= 10.0 and abs(getattr(vehicle, "speed", 0.0)) >= 2.0:
                return False
        return True

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
        game_time_seconds: Optional[float] = None,
    ) -> bool:
        """Update pedestrian simulation: despawning, spawning, waypoint traversal, traffic lights, and evasion."""
        self.sim_time += dt
        self.update_lod(player_car, dt)
        self._materialize_parked_drivers()
        self._amenity_spawn_elapsed += dt
        self._population_update_elapsed += dt

        if self._population_update_elapsed >= 5.0:
            population_check_dt = self._population_update_elapsed
            self._population_update_elapsed = 0.0

            # Despawn pedestrians outside radius
            kept_peds = []
            d_sq = self.despawn_radius_m * self.despawn_radius_m
            vehicles = self.traffic_manager.npcs if self.traffic_manager is not None else self.traffic_vehicles
            for ped in self.pedestrians:
                linked_vehicle_id = ped.current_vehicle_id or ped.reserved_vehicle_id
                if (
                    ped.state in {"approaching_vehicle", "entering_vehicle", "in_vehicle"}
                    and linked_vehicle_id is not None
                    and any(id(vehicle) == linked_vehicle_id for vehicle in vehicles)
                ):
                    kept_peds.append(ped)
                    continue
                # multi-passenger-car.md: a trip-group member mid-journey
                # (walking to the building, inside it, or walking back -
                # any state _update_linked_driver drives) must never be
                # culled by ordinary distance/offscreen population
                # trimming, same as the vehicle it's tied to must stay
                # reserved throughout (section 17/18). Without this a
                # pedestrian more than despawn_radius_m from the player
                # got removed here, then _materialize_parked_drivers
                # (which runs every frame, not just every 5s) immediately
                # spawned a brand-new one right back at the car next
                # frame - "walks a bit, thrown back to the car, walks
                # again" forever, and section 6's explicit "passenger
                # spawned twice" case.
                if ped.linked_vehicle_id is not None and any(
                    id(vehicle) == ped.linked_vehicle_id for vehicle in vehicles
                ):
                    kept_peds.append(ped)
                    continue
                # residents-live.md: same exemption as the trip-group one
                # above, and for the same reason - a pedestrian mid
                # activity (walking to a bench, sitting, ...) must not be
                # culled and immediately re-spawned elsewhere.
                if ped.activity is not None:
                    kept_peds.append(ped)
                    continue
                ped.door_grace_timer = max(0.0, ped.door_grace_timer - population_check_dt)
                dist_sq = (ped.x - player_car.x) ** 2 + (ped.y - player_car.y) ** 2
                outside_viewport = False
                if viewport_bounds is not None:
                    vmin_x, vmin_y, vmax_x, vmax_y = viewport_bounds
                    outside_viewport = not (vmin_x <= ped.x <= vmax_x and vmin_y <= ped.y <= vmax_y)
                ped.offscreen_timer = ped.offscreen_timer + population_check_dt if outside_viewport else 0.0
                at_door = self._at_building_entrance(ped.x, ped.y)
                if ped.state == "despawning":
                    continue
                if ped.spawned_at_door and not at_door:
                    ped.spawned_at_door = False
                outside_long_enough = ped.offscreen_timer >= 5.0
                if (
                    dist_sq <= d_sq
                    and not outside_long_enough
                    and (not at_door or ped.spawned_at_door or ped.door_grace_timer > 0.0)
                ):
                    kept_peds.append(ped)
            self.pedestrians = kept_peds

            game_hour = ((game_time_seconds or 0.0) / 3600.0) % 24.0
            amenity_interval = 10.0 if game_time_seconds is not None and game_hour >= 17.0 else 20.0
            amenity_spawn_ready = self._amenity_spawn_elapsed >= amenity_interval
            if amenity_spawn_ready:
                nearby_amenity_entrances = [
                    entrance for entrance in self.amenity_entrance_locations
                    if math.hypot(entrance[0] - player_car.x, entrance[1] - player_car.y) <= self.spawn_radius_m
                ]
                amenity_pedestrian_limit = self.target_count + 10
                if nearby_amenity_entrances and len(self.pedestrians) < amenity_pedestrian_limit:
                    entrance_x, entrance_y = random.choice(nearby_amenity_entrances)
                    amenity_pedestrian = self.spawn_pedestrian_at_door(entrance_x, entrance_y)
                    if amenity_pedestrian is not None:
                        self.add_pedestrian(amenity_pedestrian)
                self._amenity_spawn_elapsed = 0.0

            # Spawn new pedestrians up to target_count
            attempts = 0
            spawned_this_update = 0
            spawn_limit = self.target_count if viewport_bounds is None else 2
            max_attempts = max(50, self.target_count * 5)
            nearby_venues = [
                location for location in self.venue_locations
                if math.hypot(location[0] - player_car.x, location[1] - player_car.y) <= self.spawn_radius_m
            ]
            nearby_entrances = [
                entrance for entrance in self.entrance_locations
                if math.hypot(entrance[0] - player_car.x, entrance[1] - player_car.y) <= self.spawn_radius_m
            ]
            while (
                len(self.pedestrians) < self.target_count
                and attempts < max_attempts
                and spawned_this_update < spawn_limit
            ):
                attempts += 1
                spawn_at_door = bool(amenity_spawn_ready and nearby_entrances and random.random() < 0.45)
                spawned_near_venue = bool(nearby_venues and random.random() < 0.6)
                if spawn_at_door:
                    entrance_x, entrance_y = random.choice(nearby_entrances)
                    new_ped = self.spawn_pedestrian_at_door(entrance_x, entrance_y)
                elif spawned_near_venue:
                    venue_x, venue_y = random.choice(nearby_venues)
                    new_ped = self.spawn_pedestrian(
                        venue_x,
                        venue_y,
                        viewport_bounds=viewport_bounds,
                        max_distance_m=45.0,
                    )
                else:
                    new_ped = self.spawn_pedestrian(player_car.x, player_car.y, viewport_bounds=viewport_bounds)
                if not new_ped:
                    continue
                spawned_this_update += 1
                if spawned_near_venue and random.random() < 0.35:
                    new_ped.is_drunk = True
                    new_ped.blood_alcohol_promille = random.uniform(0.5, 3.0)
                    new_ped.drunk_phase = random.uniform(0.0, 2.0 * math.pi)
                    new_ped.drunk_vomit_cooldown = random.uniform(8.0, 25.0)
                self.add_pedestrian(new_ped)

            self._consider_activities()

        # Check interaction and dodging with player car
        cyclist_collision = self.check_player_avoidance(player_car, dt)

        # Update walking movement
        for ped in self.pedestrians:
            if not ped.lod_update_due:
                continue
            update_dt = max(dt, ped.lod_update_dt)
            if self._update_linked_driver(ped, update_dt):
                continue
            if self._update_activity(ped, update_dt):
                continue
            if ped.state == "in_vehicle":
                ped.speed = 0.0
                ped.animation_state = "idle"
                vehicles = self.traffic_manager.npcs if self.traffic_manager is not None else self.traffic_vehicles
                vehicle = next((candidate for candidate in vehicles if id(candidate) == ped.current_vehicle_id), None)
                if vehicle is None or getattr(vehicle, "current_driver_id", None) != id(ped):
                    ped.current_vehicle_id = None
                    ped.state = "walking"
                    ped.animation_state = "walking"
                else:
                    ped.x = vehicle.x
                    ped.y = vehicle.y
                    if (
                        ped.vehicle_destination is not None
                        and math.hypot(
                            vehicle.x - ped.vehicle_destination[0],
                            vehicle.y - ped.vehicle_destination[1],
                        ) <= 3.0
                    ):
                        self.exit_vehicle(ped, vehicle)
                continue
            if ped.state == PedestrianState.EXITING_VEHICLE.value:
                ped.speed = 0.0
                ped.vehicle_entry_timer = max(0.0, ped.vehicle_entry_timer - update_dt)
                if ped.vehicle_entry_timer <= 0.0:
                    ped.state = PedestrianState.WALKING.value
                    ped.animation_state = "walking"
                continue
            if ped.state == "walking" and getattr(ped, "wants_vehicle", False):
                vehicle = self.find_available_parked_vehicle(ped.x, ped.y)
                if vehicle is not None and self.reserve_parked_vehicle(ped, vehicle):
                    ped.wants_vehicle = False
                    continue
            if ped.reserved_vehicle_id is not None:
                vehicles = self.traffic_manager.npcs if self.traffic_manager is not None else self.traffic_vehicles
                vehicle = next((candidate for candidate in vehicles if id(candidate) == ped.reserved_vehicle_id), None)
                if vehicle is None or getattr(vehicle, "reserved_by_pedestrian_id", None) != id(ped):
                    self.cancel_vehicle_reservation(ped)
                    ped.state = "walking"
                    ped.animation_state = "walking"
                    ped.destination = None
                elif ped.state == "entering_vehicle":
                    ped.vehicle_entry_timer = max(0.0, ped.vehicle_entry_timer - update_dt)
                    ped.speed = 0.0
                    ped.animation_state = "idle"
                    if ped.vehicle_entry_timer <= 0.0:
                        self.enter_reserved_vehicle(ped, vehicle)
                    continue
                else:
                    route = ped.route or [(ped.x, ped.y), self._vehicle_entry_position(vehicle)]
                    route_index = min(max(1, ped.current_route_segment), len(route) - 1)
                    target_x, target_y = route[route_index]
                    distance = math.hypot(target_x - ped.x, target_y - ped.y)
                    if distance <= 1.0:
                        ped.x = target_x
                        ped.y = target_y
                        ped.current_route_segment = route_index + 1
                        if ped.current_route_segment < len(route):
                            continue
                        ped.speed = 0.0
                        ped.state = "entering_vehicle"
                        ped.animation_state = "idle"
                        ped.vehicle_entry_timer = 0.4
                        continue
                    ped.heading = math.atan2(target_y - ped.y, target_x - ped.x)
                    ped.speed = ped.base_speed
                    step = min(distance, ped.speed * update_dt)
                    ped.x += math.cos(ped.heading) * step
                    ped.y += math.sin(ped.heading) * step
                    ped.state = "approaching_vehicle"
                    ped.animation_state = "walking"
                    continue
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
                    ped.state = "waiting"
                    ped.animation_state = "idle"
                    logger.info("Pedestrian arrived at taxi stop: x=%.1f y=%.1f", target_x, target_y)
                    continue
                ped.heading = math.atan2(dy, dx)
                ped.speed = ped.base_speed
                step = min(distance, ped.speed * update_dt)
                ped.x += math.cos(ped.heading) * step
                ped.y += math.sin(ped.heading) * step
                continue
            if getattr(ped, "is_taxi_stop_waiter", False):
                ped.speed = 0.0
                ped.state = "waiting"
                ped.animation_state = "idle"
                continue
            if ped.destination is not None and self._at_building_entrance(ped.x, ped.y):
                if math.hypot(ped.destination[0] - ped.x, ped.destination[1] - ped.y) <= 1.5:
                    ped.speed = 0.0
                    ped.state = PedestrianState.ENTERING_BUILDING.value
                    ped.building_entry_timer = 0.35
                    ped.animation_state = "idle"
                    continue
            if ped.state == PedestrianState.ENTERING_BUILDING.value:
                ped.speed = 0.0
                ped.building_entry_timer = max(0.0, ped.building_entry_timer - update_dt)
                if ped.building_entry_timer <= 0.0:
                    ped.state = PedestrianState.DESPAWNING.value
                continue
            if ped.fall_timer > 0.0:
                ped.fall_timer = max(0.0, ped.fall_timer - update_dt)
                ped.speed = 0.0
                ped.animation_state = "fallen"
                if ped.fall_timer <= 0.0:
                    ped.state = PedestrianState.WALKING.value
                    ped.animation_state = "walking"
                continue
            if getattr(ped, "is_drunk", False):
                promille = max(0.5, min(3.0, getattr(ped, "blood_alcohol_promille", 0.5)))
                drunk_level = (promille - 0.5) / 2.5
                ped.drunk_phase += update_dt * (2.7 + drunk_level * 2.5)
                ped.fall_cooldown = max(0.0, ped.fall_cooldown - update_dt)
                ped.drunk_vomit_cooldown = max(0.0, ped.drunk_vomit_cooldown - update_dt)
                if ped.drunk_vomit_cooldown <= 0.0 and random.random() < 0.012 * update_dt:
                    self.vomit_puddles.append((ped.x, ped.y))
                    if len(self.vomit_puddles) > 50:
                        del self.vomit_puddles[:-50]
                    ped.drunk_vomit_cooldown = random.uniform(18.0, 40.0)
                if promille >= 1.5 and ped.fall_cooldown <= 0.0 and random.random() < (0.004 + drunk_level * 0.018) * update_dt:
                    ped.fall_timer = 1.0 + drunk_level * 2.0
                    ped.fall_cooldown = 8.0 - drunk_level * 3.0
                    ped.speed = 0.0
                    ped.state = "fallen"
                    ped.animation_state = "fallen"
                    continue
            # Check traffic light stop
            if self._is_pedestrian_red_light(ped):
                ped.speed = 0.0
                ped.state = PedestrianState.WAITING_AT_LIGHT.value
                ped.animation_state = "idle"
                ped.crossing = self._find_nearby_signalized_crossing(ped)
                continue
            else:
                # Slight natural pace fluctuations (±8%)
                ped.pace_timer -= dt
                if ped.pace_timer <= 0.0:
                    ped.pace_timer = random.uniform(2.0, 5.0)
                    ped.speed_variation_factor = random.uniform(0.92, 1.08)
                promille = max(0.5, min(3.0, getattr(ped, "blood_alcohol_promille", 0.5)))
                drunk_level = (promille - 0.5) / 2.5 if getattr(ped, "is_drunk", False) else 0.0
                ped.speed = ped.base_speed * ped.speed_variation_factor * (1.0 - drunk_level * 0.35)
                ped.crossing = self._find_nearby_signalized_crossing(ped)
                ped.state = PedestrianState.CROSSING.value if ped.crossing is not None else PedestrianState.WALKING.value
                ped.animation_state = "walking"
            if ped.dodge_timer > 0.0:
                # Controlled by dodge physics
                continue

            pts = ped.way.points_m
            ped.animation_time += update_dt
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
                shift = math.copysign(min(abs(lat_diff), ped.lateral_speed_mps * update_dt), lat_diff)
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
            ped.sway_phase += ped.sway_frequency * (ped.speed / max(0.5, ped.base_speed)) * update_dt
            # Small natural curve/wobble in heading
            drunk_promille = max(0.5, min(3.0, getattr(ped, "blood_alcohol_promille", 0.5)))
            drunk_level = (drunk_promille - 0.5) / 2.5 if getattr(ped, "is_drunk", False) else 0.0
            sway_angle = math.sin(ped.sway_phase) * math.radians(3.5 + drunk_level * 38.0)
            if getattr(ped, "is_drunk", False):
                sway_angle += math.sin(ped.drunk_phase) * math.radians(8.0 + drunk_level * 24.0)

            target_heading = math.atan2(dy, dx)
            heading_delta = (target_heading - ped.heading + math.pi) % (2.0 * math.pi) - math.pi
            max_turn = 7.0 * update_dt
            ped.heading += max(-max_turn, min(max_turn, heading_delta))
            ped.heading += sway_angle

            move_dist = ped.speed * update_dt
            if move_dist < dist_to_target:
                next_x = ped.x + math.cos(ped.heading) * move_dist
                next_y = ped.y + math.sin(ped.heading) * move_dist
                if not self._point_inside_building(next_x, next_y):
                    ped.x, ped.y = next_x, next_y
            else:
                # Reached waypoint target
                if not self._point_inside_building(target_x, target_y):
                    ped.x, ped.y = target_x, target_y
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
                        next_x = ped.x + math.cos(ped.heading) * remaining_dist
                        next_y = ped.y + math.sin(ped.heading) * remaining_dist
                        if not self._point_inside_building(next_x, next_y):
                            ped.x, ped.y = next_x, next_y

        for ped in self.pedestrians:
            if ped.lod_update_due:
                ped.lod_update_due = False
                ped.lod_update_dt = 0.0

        return cyclist_collision


class CyclistManager(PedestrianManager):
    """Manage cyclists on light-traffic paths and ordinary city roads."""

    def sync_map_data(
        self,
        ways: List[Way],
        traffic_lights: Optional[List[TrafficLight]] = None,
        crossings: Optional[List[Crossing]] = None,
        logical_intersections: Optional[List[LogicalIntersection]] = None,
    ) -> None:
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights
        if crossings is not None:
            self.crossings = crossings
        if logical_intersections is not None:
            self.logical_intersections = logical_intersections
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
        self._spawn_ways = list(self.ped_ways)
        self._ped_way_ids = {id(way) for way in self.ped_ways}
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
