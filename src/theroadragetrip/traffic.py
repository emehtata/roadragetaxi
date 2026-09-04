import logging
import heapq
import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .geo import boxes_intersect, dist_point_to_segment, get_oriented_box_corners, point_in_polygon
from .osm import (
    IntersectionApproach,
    LogicalIntersection,
    ParkingSpace,
    SignalGroup,
    StopSign,
    YieldSign,
    TrafficLight,
    Way,
    build_logical_intersections,
)
from .physics import Car, connected_drivable_ways
from .residents import ResidentManager

logger = logging.getLogger(__name__)

NPC_COLORS = [
    (60, 140, 230),   # Blue
    (230, 200, 50),   # Yellow
    (240, 240, 240),  # White
    (50, 50, 50),     # Dark gray
    (50, 180, 80),    # Green
    (220, 120, 40),   # Orange
    (160, 60, 180),   # Purple
    (180, 180, 190),  # Silver
]
MAX_TRAFFIC_COUNT = 50
MAX_NPC_SPAWNS_PER_UPDATE = 2
MAX_ROUTE_PLANS_PER_UPDATE = 1
NPC_TAXI_COLOR = (245, 205, 35)
NPC_LOD_NEAR_RADIUS_M = 500.0
NPC_LOD_MEDIUM_RADIUS_M = 1500.0
NPC_LOD_UPDATE_INTERVALS = (1.0 / 30.0, 1.0 / 8.0, 0.5)
NPC_STATIC_COLLISION_RADIUS_M = 500.0


def recommended_traffic_count(ways: List[Way], minimum: int = 5, maximum: int = MAX_TRAFFIC_COUNT) -> int:
    """Choose a traffic population from the number of connected drivable road ways."""
    road_count = len(connected_drivable_ways(ways))
    return max(minimum, min(maximum, round(road_count / 10)))


def traffic_count_for_zoom(base_count: int, px_per_m: float, minimum: int = 5) -> int:
    """Use fewer active NPCs when zoomed in, where less traffic is visible."""
    zoom_factor = min(1.0, 3.0 / max(0.1, px_per_m))
    return max(0, min(base_count, max(minimum, round(base_count * zoom_factor))))


def calculate_npc_turning_geometry(
    length_m: float, vehicle_type: str = "car"
) -> Tuple[float, float]:
    """Return wheelbase and maximum front-wheel angle for a vehicle."""
    wheelbase_m = max(1.2, min(3.2, length_m * 0.62))
    max_angle_by_type = {
        "motorcycle": math.radians(35.0),
        "moped": math.radians(30.0),
        "car": math.radians(32.0),
    }
    max_steering_angle = max_angle_by_type.get(vehicle_type, math.radians(32.0))
    return wheelbase_m, max_steering_angle


@dataclass
class NPCDriver:
    """Persistent driver identity associated with one NPC vehicle."""

    driver_id: int
    present: bool = True


@dataclass
class NPCCar:
    """Autonomous traffic vehicle driving along real-world road networks."""
    x: float
    y: float
    heading: float
    speed: float
    way: Way
    segment_idx: int
    direction: int  # 1 for forward along points_m, -1 for reverse
    target_speed: float
    color: Tuple[int, int, int]
    lane_offset: float = 0.0  # Lateral offset in meters (positive = right of centerline)
    target_lane_offset: float = 0.0
    steering_angle: float = 0.0
    wheelbase_m: float = 2.7
    max_steering_angle: float = math.radians(32.0)
    turning_radius_m: float = 4.32
    turn_recovery_timer: float = 0.0
    layer: int = 0
    length_m: float = 4.0
    width_m: float = 1.8
    # Personality traits: compliance multiplier (1.0 = exact limit, >1.25 = speeder / kaahari)
    speed_factor: float = 1.0
    is_speeder: bool = False
    # Overhaul/passing state
    overtaking: bool = False
    overtake_timer: float = 0.0
    # Crash / disable state
    crashed_timer: float = 0.0
    blocked_timer: float = 0.0
    escape_timer: float = 0.0
    rage_timer: float = 0.0
    turn_signal: str = ""  # "left" or "right" while completing a turn
    turn_signal_elapsed: float = 0.0
    braking: bool = False
    is_taxi: bool = False
    is_on_foot: bool = False
    taxi_pickup_timer: float = 0.0
    waiting_at_taxi_stop: bool = False
    taxi_stop_target: Optional[Tuple[float, float]] = None
    vehicle_type: str = "car"  # "car", "motorcycle", or "moped"
    fallen: bool = False
    driver_spawned: bool = False
    is_police: bool = False
    pursuing: bool = False
    pursuit_elapsed: float = 0.0
    pursuit_distance_check_elapsed: float = 2.0
    pursuit_phase: str = "passing"
    stopped: bool = False
    penalty_given: bool = False
    scared_timer: float = 0.0
    pursuit_cancelled: bool = False
    next_route: Optional[Tuple[Way, int, int]] = None
    travel_route: Optional[List[Tuple[float, float]]] = None
    travel_route_index: int = 0
    turn_trajectory: Optional[List[Tuple[float, float]]] = None
    turn_trajectory_index: int = 0
    destination: Optional[Tuple[float, float]] = None
    destination_parking_space_id: Optional[int] = None
    route_retry_timer: float = 0.0
    lod_level: int = 0
    lod_time_accumulator: float = 0.0
    lod_update_due: bool = True
    state: str = "driving"
    debug_last_action: str = ""
    debug_waiting_for: str = ""
    debug_in_view: Optional[bool] = None
    reserved_intersection_id: Optional[str] = None
    parking_space_id: Optional[int] = None
    parking_departure_pending: bool = False
    parking_target_id: Optional[int] = None
    parking_route: Optional[List[Tuple[float, float]]] = None
    parking_route_index: int = 0
    parking_stuck_timer: float = 0.0
    parking_last_distance: Optional[float] = None
    junction_wait_timer: float = 0.0
    stop_sign_id: Optional[int] = None
    stop_sign_wait_timer: float = 0.0
    reserved_by_pedestrian_id: Optional[int] = None
    current_driver_id: Optional[int] = None
    owner_id: Optional[int] = None
    assigned_driver_id: Optional[int] = None
    driver_present: bool = True
    driver: Optional[NPCDriver] = None

    def __post_init__(self) -> None:
        """Give every NPC vehicle a stable associated driver identity."""
        if self.assigned_driver_id is None:
            self.assigned_driver_id = id(self)
        if self.driver is None:
            self.driver = NPCDriver(self.assigned_driver_id, self.driver_present)
        else:
            self.assigned_driver_id = self.driver.driver_id

    def has_driver(self) -> bool:
        """Return whether this vehicle's associated driver can currently drive."""
        return (
            self.driver_present
            and self.assigned_driver_id is not None
            and self.driver is not None
            and self.driver.present
        )

    def set_driver_present(self, present: bool) -> None:
        """Keep legacy presence flag and persistent driver state synchronized."""
        self.driver_present = present
        if self.driver is not None:
            self.driver.present = present


CarAI = NPCCar


class IntersectionManager:
    """Reserve signalized intersection conflict areas for near-field NPCs."""

    def __init__(self, intersections: List[LogicalIntersection]):
        self.intersections = intersections
        self._reservations: dict[str, dict[int, str]] = {}

    def _intersection_for(self, approach: IntersectionApproach) -> Optional[LogicalIntersection]:
        for intersection in self.intersections:
            if approach in intersection.approaches:
                return intersection
        return None

    def can_enter(self, npc: NPCCar, approach: IntersectionApproach) -> bool:
        intersection = self._intersection_for(approach)
        if intersection is None:
            return True
        reservations = self._reservations.get(intersection.intersection_id, {})
        return all(owner_id == id(npc) or reserved_approach == approach.approach_id
                   for owner_id, reserved_approach in reservations.items())

    def request_enter(self, npc: NPCCar, approach: IntersectionApproach) -> bool:
        if not self.can_enter(npc, approach):
            return False
        intersection = self._intersection_for(approach)
        if intersection is None:
            return True
        self._reservations.setdefault(intersection.intersection_id, {})[id(npc)] = approach.approach_id
        npc.reserved_intersection_id = intersection.intersection_id
        return True

    def release(self, npc: NPCCar) -> None:
        for intersection_id, reservations in list(self._reservations.items()):
            reservations.pop(id(npc), None)
            if not reservations:
                self._reservations.pop(intersection_id, None)
        npc.reserved_intersection_id = None

    def update(self, npcs: List[NPCCar]) -> None:
        active_ids = {id(npc) for npc in npcs}
        for intersection in self.intersections:
            reservations = self._reservations.get(intersection.intersection_id)
            if not reservations:
                continue
            for npc_id in list(reservations):
                npc = next((candidate for candidate in npcs if id(candidate) == npc_id), None)
                if npc is None or npc_id not in active_ids:
                    reservations.pop(npc_id, None)
                    continue
                if npc.layer != intersection.layer or math.hypot(
                    npc.x - intersection.center[0], npc.y - intersection.center[1]
                ) > intersection.radius_m + 6.0:
                    self.release(npc)


class TrafficLightManager:
    """Update cached logical signal groups and answer NPC signal queries."""

    def __init__(self, intersections: List[LogicalIntersection]):
        self.intersections = intersections
        self._groups: dict[str, SignalGroup] = {}
        for intersection in intersections:
            for approach in intersection.approaches:
                if approach.signal_group is not None:
                    self._groups[approach.signal_group.approach_id] = approach.signal_group

    def update(self, current_time: float) -> None:
        """Advance all signal groups from simulation time without rebuilding geometry."""
        for group in self._groups.values():
            group.get_state(current_time)

    def get_signal_state(self, approach: IntersectionApproach, current_time: float) -> str:
        """Return the signal state for an approach, or green when uncontrolled."""
        if approach.signal_group is None:
            return "green"
        return approach.signal_group.get_state(current_time)

    def find_approach(self, npc: NPCCar) -> Optional[IntersectionApproach]:
        """Find the cached incoming approach matching an NPC's road and heading."""
        best_approach = None
        best_distance = float("inf")
        heading_x = math.cos(npc.heading)
        heading_y = math.sin(npc.heading)
        for intersection in self.intersections:
            distance_to_center = math.hypot(
                npc.x - intersection.center[0], npc.y - intersection.center[1]
            )
            if distance_to_center > intersection.radius_m + 40.0:
                continue
            for approach in intersection.approaches:
                if npc.way not in approach.road_segments:
                    continue
                direction_x, direction_y = approach.direction_vector
                if heading_x * direction_x + heading_y * direction_y < 0.5:
                    continue
                if distance_to_center < best_distance:
                    best_approach = approach
                    best_distance = distance_to_center
        return best_approach

def calculate_npc_target_speed(way: Way, speed_factor: float) -> float:
    """Compute realistic driving target speed in m/s based on Finnish road limit and vehicle personality."""
    limit_kmh = getattr(way, "speed_limit_kmh", 50)
    # Target speed = speed limit * speed_factor (m/s)
    base_mps = (limit_kmh / 3.6) * speed_factor
    return max(4.0, base_mps)


def compute_desired_lane_offset(way: Way, is_overtaking: bool = False, travel_direction: int = 1) -> float:
    """Calculate lateral lane offset (meters) to keep right or pass on multi-lane roads."""
    half_w = getattr(way, "half_width_m", 4.0)
    oneway = getattr(way, "oneway", 0)

    # On two-way roads (oneway == 0), right side is half_w * 0.45
    # If overtaking on two-way or multi-lane, move towards left/center
    if oneway == 0:
        base_offset = max(1.2, half_w * 0.45)
        if is_overtaking:
            offset = -base_offset * 0.7  # Passing lane in oncoming / middle
        else:
            offset = base_offset
    else:
        # On wide one-way roads (e.g. half_w >= 5.0m), default to right lane, overtake on left
        if half_w >= 5.0:
            right_lane = half_w * 0.5
            left_lane = -half_w * 0.5
            offset = left_lane if is_overtaking else right_lane
        else:
            offset = 0.0
    return offset


def compute_turn_lane_offset(way: Way, turn_signal: str) -> float:
    """Return the furthest practical lane offset for a left or right turn."""
    if turn_signal not in {"left", "right"}:
        return compute_desired_lane_offset(way)
    half_width = getattr(way, "half_width_m", 4.0)
    edge_clearance = 1.0
    edge_offset = max(0.0, half_width - edge_clearance)
    return -edge_offset if turn_signal == "left" else edge_offset


class TrafficManager:
    """Manages autonomous NPC traffic simulation around the player."""

    def __init__(
        self,
        ways: List[Way],
        target_count: int = 15,
        spawn_radius_m: float = 300.0,
        despawn_radius_m: float = 450.0,
        traffic_lights: Optional[List[TrafficLight]] = None,
        stop_signs: Optional[List[StopSign]] = None,
        yield_signs: Optional[List[YieldSign]] = None,
        crossings: Optional[List] = None,
        parking_spaces: Optional[List] = None,
        parking_density: float = 0.5,
        roadworks: Optional[List] = None,
        enable_two_wheelers: bool = False,
        residents: Optional[ResidentManager] = None,
        buildings: Optional[List] = None,
        sceneries: Optional[List] = None,
    ):
        self.ways = connected_drivable_ways(ways)
        self.target_count = max(0, min(MAX_TRAFFIC_COUNT, target_count))
        self.spawn_radius_m = spawn_radius_m
        self.despawn_radius_m = despawn_radius_m
        self.min_spawn_dist_to_player_m: float = 12.0
        self.min_spawn_dist_to_npc_m: float = 6.0
        self.traffic_lights = traffic_lights if traffic_lights is not None else []
        self.stop_signs = stop_signs if stop_signs is not None else []
        self.yield_signs = yield_signs if yield_signs is not None else []
        self.crossings = crossings if crossings is not None else []
        self.parking_spaces = parking_spaces if parking_spaces is not None else []
        self.parking_density = max(0.0, min(1.0, parking_density))
        self.roadworks = roadworks if roadworks is not None else []
        self.enable_two_wheelers = enable_two_wheelers
        self.residents = residents if residents is not None else ResidentManager()
        self.buildings = buildings if buildings is not None else []
        self.sceneries = sceneries if sceneries is not None else []
        self._static_collision_cell_size = 100.0
        self._building_collision_grid: dict[Tuple[int, int], List] = {}
        self._tree_collision_grid: dict[Tuple[int, int], List[Tuple[float, float]]] = {}
        self.npcs: List[NPCCar] = []
        self._log_timer: float = 0.0
        self.sim_time: float = 0.0
        self._signal_update_elapsed: float = 0.0
        self._lod_distance_update_elapsed: float = 0.0
        self._junction_grid_cell_size: float = 60.0
        self._junction_grid: dict = {}
        self._way_grid_cell_size: float = 200.0
        self._way_grid: dict = {}
        self._signal_grid_cell_size: float = 60.0
        self._traffic_light_grid: dict[Tuple[int, int], List[TrafficLight]] = {}
        self._crossing_grid: dict[Tuple[int, int], List] = {}
        self._npc_grid_cell_size: float = 32.0
        self._npc_grid: dict[Tuple[int, int], List[NPCCar]] = {}
        self._npc_grid_npc_ids: Tuple[int, ...] = ()
        self._nearby_npc_cache: dict[int, List[NPCCar]] = {}
        self._parking_grid_cell_size = 100.0
        self._parking_grid: dict[Tuple[int, int], List] = {}
        self._route_nodes: List[Tuple[float, float, int]] = []
        self._route_edges: dict[int, List[Tuple[int, float]]] = {}
        self._route_edges_by_layer: dict[int, dict[int, List[Tuple[int, float]]]] = {}
        self.logical_intersections = build_logical_intersections(self.traffic_lights, self.ways)
        self.traffic_light_manager = TrafficLightManager(self.logical_intersections)
        self.intersection_manager = IntersectionManager(self.logical_intersections)
        self._build_route_graph()
        self._build_parking_grid()
        self._build_static_collision_grids()
        self._taxi_stop_spawns: set[Tuple[float, float, object]] = set()
        self._taxi_stop_targets: dict[Tuple[float, float, object], int] = {}
        self._crashed_npc_events: List[Tuple[NPCCar, float, float, str]] = []
        self._build_spatial_indices()

    def take_crashed_npc_events(self) -> List[Tuple[NPCCar, float, float, str]]:
        """Return newly crashed NPCs that need to exit their vehicles."""
        events = self._crashed_npc_events
        self._crashed_npc_events = []
        return events

    def _crash_npc(self, npc: NPCCar, crashed_timer: float = math.inf) -> None:
        """Leave a crashed NPC at the collision site and notify its resident."""
        if npc.state == "crashed":
            return
        npc.state = "crashed"
        npc.crashed_timer = crashed_timer
        npc.speed = 0.0
        npc.target_speed = 0.0
        npc.set_driver_present(False)
        npc.current_driver_id = None
        resident = self.residents.get(npc.owner_id)
        if resident is not None:
            resident.mode = "walking"
            resident.active_vehicle_id = None
        curse_text = random.choice(("@#*!%", "#$@&!", "!%#&*", "%$!#@", "@!*#$"))
        self._crashed_npc_events.append((npc, npc.x, npc.y, curse_text))

    def _static_collision_cells(self, minx: float, miny: float, maxx: float, maxy: float):
        cell_size = self._static_collision_cell_size
        for cell_x in range(math.floor(minx / cell_size), math.floor(maxx / cell_size) + 1):
            for cell_y in range(math.floor(miny / cell_size), math.floor(maxy / cell_size) + 1):
                yield cell_x, cell_y

    def _build_static_collision_grids(self) -> None:
        """Index buildings and trees so NPC collision checks stay local."""
        self._building_collision_grid.clear()
        self._tree_collision_grid.clear()
        for building in self.buildings:
            points = getattr(building, "points_m", ())
            if len(points) < 3:
                continue
            bbox = getattr(building, "bbox", (0.0, 0.0, 0.0, 0.0))
            if bbox == (0.0, 0.0, 0.0, 0.0):
                xs, ys = zip(*points)
                bbox = (min(xs), min(ys), max(xs), max(ys))
            for cell in self._static_collision_cells(*bbox):
                self._building_collision_grid.setdefault(cell, []).append(building)
        for scenery in self.sceneries:
            for tree_x, tree_y in getattr(scenery, "trees", ()):
                cell = (
                    math.floor(tree_x / self._static_collision_cell_size),
                    math.floor(tree_y / self._static_collision_cell_size),
                )
                self._tree_collision_grid.setdefault(cell, []).append((tree_x, tree_y))

    def _nearby_static_buildings(self, x: float, y: float, radius: float) -> List:
        buildings = []
        seen = set()
        for cell in self._static_collision_cells(x - radius, y - radius, x + radius, y + radius):
            for building in self._building_collision_grid.get(cell, ()):
                if id(building) not in seen:
                    seen.add(id(building))
                    buildings.append(building)
        return buildings

    def _nearby_static_trees(self, x: float, y: float, radius: float) -> List[Tuple[float, float]]:
        trees = []
        for cell in self._static_collision_cells(x - radius, y - radius, x + radius, y + radius):
            trees.extend(self._tree_collision_grid.get(cell, ()))
        return trees

    def _nearby_ways(self, x: float, y: float, radius: float) -> List:
        """Return unique ways in the local way-grid cells."""
        cell_size = self._way_grid_cell_size
        min_cx = int(math.floor((x - radius) / cell_size))
        max_cx = int(math.floor((x + radius) / cell_size))
        min_cy = int(math.floor((y - radius) / cell_size))
        max_cy = int(math.floor((y + radius) / cell_size))
        nearby = []
        seen = set()
        for cell_x in range(min_cx, max_cx + 1):
            for cell_y in range(min_cy, max_cy + 1):
                for way in self._way_grid.get((cell_x, cell_y), ()):
                    way_id = id(way)
                    if way_id not in seen:
                        seen.add(way_id)
                        nearby.append(way)
        return nearby

    def _npc_hits_static_obstacle(
        self,
        npc: NPCCar,
        previous_position: Tuple[float, float],
    ) -> bool:
        """Stop an NPC that reaches a building or tree outside a drivable road."""
        car_radius = math.hypot(npc.length_m, npc.width_m) * 0.5
        corners = get_oriented_box_corners(
            npc.x, npc.y, npc.heading, npc.length_m, npc.width_m
        )
        for building in self._nearby_static_buildings(npc.x, npc.y, car_radius):
            if getattr(building, "layer", 0) != npc.layer:
                continue
            points = getattr(building, "points_m", ())
            if len(points) < 3:
                continue
            bbox = getattr(building, "bbox", None)
            if bbox == (0.0, 0.0, 0.0, 0.0):
                xs, ys = zip(*points)
                bbox = (min(xs), min(ys), max(xs), max(ys))
            if bbox and not (
                bbox[0] - car_radius <= npc.x <= bbox[2] + car_radius
                and bbox[1] - car_radius <= npc.y <= bbox[3] + car_radius
            ):
                continue
            intersects = point_in_polygon(npc.x, npc.y, points) or any(
                point_in_polygon(x, y, points) for x, y in corners
            )
            if not intersects:
                intersects = any(
                    dist_point_to_segment(
                        npc.x, npc.y, points[index][0], points[index][1],
                        points[(index + 1) % len(points)][0], points[(index + 1) % len(points)][1],
                    ) <= car_radius
                    for index in range(len(points))
                )
            if not intersects:
                continue
            if any(
                getattr(way, "layer", 0) == npc.layer
                and not getattr(way, "is_tunnel", False)
                and any(
                    dist_point_to_segment(
                        npc.x, npc.y, start[0], start[1], end[0], end[1]
                    ) <= getattr(way, "half_width_m", 3.0)
                    for start, end in zip(way.points_m, way.points_m[1:])
                )
                for way in self._nearby_ways(npc.x, npc.y, car_radius)
            ):
                continue
            npc.x, npc.y = previous_position
            self._crash_npc(npc, crashed_timer=3.0)
            return True

        tree_radius = car_radius + 1.0
        for tree_x, tree_y in self._nearby_static_trees(npc.x, npc.y, tree_radius):
            if math.hypot(npc.x - tree_x, npc.y - tree_y) > tree_radius:
                continue
            away_x = previous_position[0] - tree_x
            away_y = previous_position[1] - tree_y
            away_distance = math.hypot(away_x, away_y)
            if away_distance < 1e-6:
                away_x = -math.cos(npc.heading)
                away_y = -math.sin(npc.heading)
                away_distance = 1.0
            safe_distance = tree_radius + 0.2
            npc.x = tree_x + away_x / away_distance * safe_distance
            npc.y = tree_y + away_y / away_distance * safe_distance
            self._crash_npc(npc, crashed_timer=3.0)
            return True
        return False

    def _build_route_graph(self) -> None:
        """Build the immutable vertex graph used by navigation routing."""
        nodes: List[Tuple[float, float, int]] = []
        edges: dict[int, List[Tuple[int, float]]] = {}
        endpoint_buckets: dict[Tuple[int, int, int], List[int]] = {}

        def node_id(point: Tuple[float, float], point_layer: int) -> int:
            bucket = (round(point[0] / 3.0), round(point[1] / 3.0), point_layer)
            for candidate in endpoint_buckets.get(bucket, []):
                candidate_point = nodes[candidate]
                if math.hypot(candidate_point[0] - point[0], candidate_point[1] - point[1]) <= 3.0:
                    return candidate
            candidate = len(nodes)
            nodes.append((point[0], point[1], point_layer))
            endpoint_buckets.setdefault(bucket, []).append(candidate)
            edges[candidate] = []
            return candidate

        for way in self.ways:
            if len(way.points_m) < 2:
                continue
            point_layer = getattr(way, "layer", 0)
            point_ids = [node_id(point, point_layer) for point in way.points_m]
            oneway = getattr(way, "oneway", 0)
            if getattr(way, "is_roundabout", False):
                oneway = self._roundabout_direction(way)
            for first, second in zip(point_ids, point_ids[1:]):
                distance = math.hypot(
                    nodes[second][0] - nodes[first][0], nodes[second][1] - nodes[first][1]
                )
                if oneway >= 0:
                    edges[first].append((second, distance))
                if oneway <= 0:
                    edges[second].append((first, distance))

        self._route_nodes = nodes
        self._route_edges = edges
        layers = {node[2] for node in nodes}
        self._route_edges_by_layer = {
            layer: {
                index: [(neighbor, distance) for neighbor, distance in neighbors if nodes[neighbor][2] == layer]
                for index, neighbors in edges.items()
                if nodes[index][2] == layer
            }
            for layer in layers
        }

    def _build_npc_spatial_grid(self) -> None:
        cell_size = self._npc_grid_cell_size
        self._npc_grid.clear()
        self._nearby_npc_cache.clear()
        for npc in self.npcs:
            cell = (int(math.floor(npc.x / cell_size)), int(math.floor(npc.y / cell_size)))
            self._npc_grid.setdefault(cell, []).append(npc)
        self._npc_grid_npc_ids = tuple(id(npc) for npc in self.npcs)

    def _build_parking_grid(self) -> None:
        cell_size = self._parking_grid_cell_size
        self._parking_grid.clear()
        for parking_space in self.parking_spaces:
            center_x = (parking_space.bbox[0] + parking_space.bbox[2]) * 0.5
            center_y = (parking_space.bbox[1] + parking_space.bbox[3]) * 0.5
            cell = (int(math.floor(center_x / cell_size)), int(math.floor(center_y / cell_size)))
            self._parking_grid.setdefault(cell, []).append(parking_space)

    def nearby_parking_spaces(self, x: float, y: float, radius_m: float) -> List:
        """Return existing OSM parking spaces within a radius of a world position."""
        cell_size = self._parking_grid_cell_size
        cell_x = int(math.floor(x / cell_size))
        cell_y = int(math.floor(y / cell_size))
        radius_sq = radius_m * radius_m
        spaces: List = []
        cell_radius = max(1, int(math.ceil(radius_m / cell_size)))
        for offset_x in range(-cell_radius, cell_radius + 1):
            for offset_y in range(-cell_radius, cell_radius + 1):
                for parking_space in self._parking_grid.get((cell_x + offset_x, cell_y + offset_y), ()):
                    center_x = (parking_space.bbox[0] + parking_space.bbox[2]) * 0.5
                    center_y = (parking_space.bbox[1] + parking_space.bbox[3]) * 0.5
                    if (center_x - x) ** 2 + (center_y - y) ** 2 <= radius_sq:
                        spaces.append(parking_space)
        return spaces

    @staticmethod
    def parking_space_id(parking_space: ParkingSpace) -> int:
        """Return a stable runtime ID even for hand-built test parking spaces."""
        return parking_space.osm_id if parking_space.osm_id is not None else id(parking_space)

    @staticmethod
    def parking_heading(parking_space: ParkingSpace) -> float:
        """Return the tagged parking direction for an eligible space."""
        orientation = parking_space.orientation
        return float(orientation) if orientation is not None else random.uniform(-math.pi, math.pi)

    @staticmethod
    def parking_space_has_orientation(parking_space: ParkingSpace) -> bool:
        return parking_space.orientation is not None

    def reserve_parking_space(self, parking_space: ParkingSpace, pedestrian_id: int) -> bool:
        """Reserve a free OSM parking space for a pedestrian or vehicle interaction."""
        if parking_space.occupied or parking_space.reserved:
            return False
        parking_space.reserved = True
        parking_space.reserved_by_pedestrian_id = pedestrian_id
        return True

    def occupy_parking_space(self, npc: NPCCar, parking_space: ParkingSpace) -> bool:
        """Associate an NPC with a reserved or free existing OSM parking space."""
        if parking_space.occupied or (
            parking_space.reserved
            and parking_space.reserved_by_pedestrian_id not in (None, npc.current_driver_id)
        ):
            return False
        parking_space.occupied = True
        parking_space.reserved = False
        parking_space.reserved_by_pedestrian_id = None
        parking_space.vehicle_id = id(npc)
        npc.parking_space_id = self.parking_space_id(parking_space)
        npc.parking_departure_pending = False
        npc.parking_target_id = None
        npc.parking_route = None
        npc.parking_route_index = 0
        npc.parking_stuck_timer = 0.0
        npc.parking_last_distance = None
        npc.destination = None
        npc.travel_route = None
        npc.travel_route_index = 0
        npc.destination_parking_space_id = None
        npc.state = "parked"
        npc.speed = 0.0
        npc.target_speed = 0.0
        npc.current_driver_id = None
        resident = self.residents.get(npc.owner_id)
        if resident is not None:
            resident.mode = "walking"
            resident.active_vehicle_id = None
        return True

    def release_parking_space(self, npc: NPCCar) -> None:
        """Release the OSM space associated with an NPC and clear its reservation."""
        for parking_space in self.parking_spaces:
            if parking_space.vehicle_id == id(npc) or (
                npc.parking_space_id is not None
                and self.parking_space_id(parking_space) == npc.parking_space_id
            ):
                parking_space.occupied = False
                parking_space.reserved = False
                parking_space.vehicle_id = None
                parking_space.reserved_by_pedestrian_id = None
                break
        npc.parking_space_id = None
        npc.parking_departure_pending = False
        npc.parking_target_id = None
        npc.parking_route = None
        npc.parking_route_index = 0
        npc.parking_stuck_timer = 0.0
        npc.parking_last_distance = None
        npc.destination = None
        npc.travel_route = None
        npc.travel_route_index = 0
        npc.destination_parking_space_id = None
        npc.reserved_by_pedestrian_id = None

    def activate_occupied_vehicle(self, npc: NPCCar) -> bool:
        """Start a physical departure before handing an occupied NPC to CarAI."""
        if npc.state not in {"reserved", "parked", "occupied"}:
            return False
        was_occupied = npc.state == "occupied"
        if not was_occupied:
            self.release_parking_space(npc)
        else:
            npc.parking_departure_pending = npc.parking_space_id is not None
        npc.current_driver_id = None
        npc.target_speed = max(npc.target_speed, 4.0)
        if npc.parking_departure_pending:
            parking_space = next(
                (
                    space for space in self.parking_spaces
                    if self.parking_space_id(space) == npc.parking_space_id
                ),
                None,
            )
            if parking_space is not None:
                center_x = (parking_space.bbox[0] + parking_space.bbox[2]) * 0.5
                center_y = (parking_space.bbox[1] + parking_space.bbox[3]) * 0.5
                parking_heading = self.parking_heading(parking_space)
                clearance = math.hypot(
                    parking_space.bbox[2] - parking_space.bbox[0],
                    parking_space.bbox[3] - parking_space.bbox[1],
                ) * 0.5 + npc.length_m * 0.5 + 1.0
                exit_position = (
                    center_x + math.cos(parking_heading) * clearance,
                    center_y + math.sin(parking_heading) * clearance,
                )
                npc.parking_route = [(npc.x, npc.y), exit_position]
                npc.parking_route_index = 1
                npc.state = "parking_departure"
                return True
        npc.state = "driving"
        return True

    def spawn_parked_npc(
        self,
        near_x: float,
        near_y: float,
        near_heading: float = 0.0,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> Optional[NPCCar]:
        """Spawn an NPC directly only into a free parking space outside the view."""
        available_spaces = [
            space for space in self.nearby_parking_spaces(near_x, near_y, self.spawn_radius_m)
            if self.parking_space_has_orientation(space) and not space.occupied
            and not space.reserved
            and (
                viewport_bounds is None
                or not (
                    viewport_bounds[0]
                    <= (space.bbox[0] + space.bbox[2]) * 0.5
                    <= viewport_bounds[2]
                    and viewport_bounds[1]
                    <= (space.bbox[1] + space.bbox[3]) * 0.5
                    <= viewport_bounds[3]
                )
            )
        ]
        if not available_spaces:
            return None
        parking_space = random.choice(available_spaces)
        center_x = (parking_space.bbox[0] + parking_space.bbox[2]) * 0.5
        center_y = (parking_space.bbox[1] + parking_space.bbox[3]) * 0.5
        npc = self.spawn_npc(near_x, near_y, viewport_bounds=None, near_heading=None)
        if npc is None:
            return None
        npc.is_taxi = False
        npc.vehicle_type = "car"
        npc.x = center_x
        npc.y = center_y
        npc.heading = self.parking_heading(parking_space)
        if not self.occupy_parking_space(npc, parking_space):
            self.npcs.remove(npc)
            return None
        return npc

    def spawn_parking_npc(
        self,
        near_x: float,
        near_y: float,
        viewport_bounds: Tuple[float, float, float, float],
    ) -> Optional[NPCCar]:
        """Spawn outside the viewport and drive a normal NPC toward a visible OSM space."""
        available_spaces = [
            space for space in self.nearby_parking_spaces(near_x, near_y, self.spawn_radius_m)
            if self.parking_space_has_orientation(space) and not space.occupied
            and not space.reserved
            and viewport_bounds[0]
            <= (space.bbox[0] + space.bbox[2]) * 0.5
            <= viewport_bounds[2]
            and viewport_bounds[1]
            <= (space.bbox[1] + space.bbox[3]) * 0.5
            <= viewport_bounds[3]
        ]
        if not available_spaces:
            return None
        parking_space = random.choice(available_spaces)
        npc = self.spawn_npc(near_x, near_y, viewport_bounds=viewport_bounds, near_heading=None)
        if npc is None:
            return None
        center = (
            (parking_space.bbox[0] + parking_space.bbox[2]) * 0.5,
            (parking_space.bbox[1] + parking_space.bbox[3]) * 0.5,
        )
        route = self._plan_parking_route((npc.x, npc.y), center, layer=getattr(npc.way, "layer", 0))
        if not route or len(route) < 2:
            self.npcs.remove(npc)
            return None
        parking_space.reserved = True
        parking_space.vehicle_id = id(npc)
        npc.parking_target_id = self.parking_space_id(parking_space)
        npc.destination = center
        npc.destination_parking_space_id = npc.parking_target_id
        npc.travel_route = None
        npc.travel_route_index = 0
        npc.parking_route = route
        npc.parking_route_index = 1
        npc.parking_stuck_timer = 0.0
        npc.parking_last_distance = None
        npc.state = "parking"
        return npc

    def _start_destination_parking(self, npc: NPCCar) -> bool:
        """Reserve a nearby OSM space and route a vehicle there from a dead end."""
        available_spaces = [
            space for space in self.nearby_parking_spaces(npc.x, npc.y, 80.0)
            if self.parking_space_has_orientation(space) and not space.occupied and not space.reserved
        ]
        if not available_spaces:
            return False
        parking_space = min(
            available_spaces,
            key=lambda space: math.hypot(
                (space.bbox[0] + space.bbox[2]) * 0.5 - npc.x,
                (space.bbox[1] + space.bbox[3]) * 0.5 - npc.y,
            ),
        )
        center = (
            (parking_space.bbox[0] + parking_space.bbox[2]) * 0.5,
            (parking_space.bbox[1] + parking_space.bbox[3]) * 0.5,
        )
        route = self._plan_parking_route((npc.x, npc.y), center, layer=getattr(npc.way, "layer", 0))
        if not route or len(route) < 2:
            return False
        parking_space.reserved = True
        parking_space.vehicle_id = id(npc)
        npc.parking_target_id = self.parking_space_id(parking_space)
        npc.destination = center
        npc.destination_parking_space_id = npc.parking_target_id
        npc.travel_route = None
        npc.travel_route_index = 0
        npc.parking_route = route
        npc.parking_route_index = 1
        npc.parking_stuck_timer = 0.0
        npc.parking_last_distance = None
        npc.state = "parking"
        npc.speed = 0.0
        return True

    def _plan_parking_route(
        self,
        start: Tuple[float, float],
        parking_center: Tuple[float, float],
        layer: Optional[int] = None,
    ) -> Optional[List[Tuple[float, float]]]:
        """Route on roads first, then allow only a short approach into the space."""
        nearest_point = None
        nearest_distance_sq = math.inf
        for way in self.ways:
            if layer is not None and getattr(way, "layer", 0) != layer:
                continue
            points = way.points_m
            for first, second in zip(points, points[1:]):
                segment_x = second[0] - first[0]
                segment_y = second[1] - first[1]
                segment_length_sq = segment_x * segment_x + segment_y * segment_y
                if segment_length_sq <= 1e-9:
                    continue
                projection = (
                    (parking_center[0] - first[0]) * segment_x
                    + (parking_center[1] - first[1]) * segment_y
                ) / segment_length_sq
                projection = max(0.0, min(1.0, projection))
                candidate = (
                    first[0] + projection * segment_x,
                    first[1] + projection * segment_y,
                )
                distance_sq = (
                    (candidate[0] - parking_center[0]) ** 2
                    + (candidate[1] - parking_center[1]) ** 2
                )
                if distance_sq < nearest_distance_sq:
                    nearest_point = candidate
                    nearest_distance_sq = distance_sq
        if nearest_point is None or nearest_distance_sq > 10.0 * 10.0:
            return None
        route = self.plan_route(start, nearest_point, layer=layer)
        if not route:
            return None
        return route + [parking_center]

    def _advance_parking_npc(self, npc: NPCCar, dt: float) -> None:
        """Follow planned road points, then occupy the selected parking space."""
        route = npc.parking_route
        if not route or npc.parking_route_index >= len(route):
            self.release_parking_space(npc)
            npc.state = "driving"
            npc.speed = 0.0
            return
        target_x, target_y = route[npc.parking_route_index]
        dx = target_x - npc.x
        dy = target_y - npc.y
        distance = math.hypot(dx, dy)
        if npc.parking_last_distance is not None and distance >= npc.parking_last_distance - 0.02:
            npc.parking_stuck_timer += dt
        else:
            npc.parking_stuck_timer = 0.0
        npc.parking_last_distance = distance
        if npc.parking_stuck_timer >= 3.0:
            self.release_parking_space(npc)
            npc.state = "driving"
            npc.speed = 0.0
            return
        speed = max(4.0, min(npc.target_speed, 12.0))
        if self._parking_step_blocked(npc, target_x, target_y, speed * dt):
            npc.speed = 0.0
            return
        if distance <= speed * dt or distance <= 0.01:
            npc.x, npc.y = target_x, target_y
            npc.heading = math.atan2(dy, dx) if distance > 0.01 else npc.heading
            npc.parking_route_index += 1
            if npc.parking_route_index >= len(route):
                parking_space = next(
                    (space for space in self.parking_spaces if self.parking_space_id(space) == npc.parking_target_id),
                    None,
                )
                if parking_space is not None:
                    npc.heading = self.parking_heading(parking_space)
                    if not self.occupy_parking_space(npc, parking_space):
                        self.release_parking_space(npc)
                        npc.state = "driving"
                        npc.speed = 0.0
                else:
                    npc.state = "driving"
                    npc.speed = 0.0
            return
        npc.heading = math.atan2(dy, dx)
        npc.speed = speed
        npc.x += dx / distance * speed * dt
        npc.y += dy / distance * speed * dt

    def _parking_step_blocked(self, npc: NPCCar, target_x: float, target_y: float, step: float) -> bool:
        """Prevent a parking maneuver from driving through another vehicle."""
        distance = math.hypot(target_x - npc.x, target_y - npc.y)
        if distance <= 1e-6:
            return False
        candidate_x = npc.x + (target_x - npc.x) / distance * min(step, distance)
        candidate_y = npc.y + (target_y - npc.y) / distance * min(step, distance)
        for other in self._nearby_npcs(npc):
            if other is npc or other.layer != npc.layer:
                continue
            if boxes_intersect(
                candidate_x, candidate_y, npc.heading, npc.length_m, npc.width_m,
                other.x, other.y, other.heading, other.length_m, other.width_m,
            ):
                return True
        return False

    def _advance_parking_departure(self, npc: NPCCar, dt: float) -> None:
        """Move an NPC beyond its parking space before releasing the space."""
        route = npc.parking_route
        if not route or npc.parking_route_index >= len(route):
            self.release_parking_space(npc)
            npc.state = "driving"
            return
        target_x, target_y = route[npc.parking_route_index]
        dx = target_x - npc.x
        dy = target_y - npc.y
        distance = math.hypot(dx, dy)
        speed = max(2.0, min(npc.target_speed, 8.0))
        if distance <= speed * dt or distance <= 0.01:
            npc.x, npc.y = target_x, target_y
            npc.heading = math.atan2(dy, dx) if distance > 0.01 else npc.heading
            self.release_parking_space(npc)
            npc.state = "driving"
            npc.speed = 0.0
            return
        npc.heading = math.atan2(dy, dx)
        npc.speed = speed
        npc.x += dx / distance * speed * dt
        npc.y += dy / distance * speed * dt

    def _nearby_npcs(self, npc: NPCCar) -> List[NPCCar]:
        cached = self._nearby_npc_cache.get(id(npc))
        if cached is not None:
            return cached
        cell_size = self._npc_grid_cell_size
        cell_x = int(math.floor(npc.x / cell_size))
        cell_y = int(math.floor(npc.y / cell_size))
        nearby: List[NPCCar] = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby.extend(self._npc_grid.get((cell_x + offset_x, cell_y + offset_y), []))
        self._nearby_npc_cache[id(npc)] = nearby
        return nearby

    def nearby_npcs_at(self, x: float, y: float) -> List[NPCCar]:
        """Return NPCs in the nine grid cells around a world position."""
        cell_size = self._npc_grid_cell_size
        cell_x = int(math.floor(x / cell_size))
        cell_y = int(math.floor(y / cell_size))
        nearby: List[NPCCar] = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby.extend(self._npc_grid.get((cell_x + offset_x, cell_y + offset_y), []))
        return nearby

    def update_lod(self, player_car: Car, dt: float) -> None:
        """Assign traffic LOD and accumulate each NPC's scheduled update time."""
        self._lod_distance_update_elapsed += dt
        update_distances = self._lod_distance_update_elapsed >= 0.1
        if update_distances:
            lod_dt = self._lod_distance_update_elapsed
            self._lod_distance_update_elapsed = 0.0
        for npc in self.npcs:
            if update_distances:
                distance = math.hypot(npc.x - player_car.x, npc.y - player_car.y)
                if distance < NPC_LOD_NEAR_RADIUS_M:
                    npc.lod_level = 0
                elif distance < NPC_LOD_MEDIUM_RADIUS_M:
                    npc.lod_level = 1
                else:
                    npc.lod_level = 2
            npc.lod_time_accumulator += dt
            npc.lod_update_due = self._lod_update_due(npc)
            if update_distances:
                self.residents.update_lod(npc.owner_id, npc.x, npc.y, player_car.x, player_car.y, lod_dt)

    @staticmethod
    def _lod_update_due(npc: NPCCar) -> bool:
        interval = NPC_LOD_UPDATE_INTERVALS[npc.lod_level]
        if npc.lod_time_accumulator < interval:
            return False
        npc.lod_time_accumulator %= interval
        return True

    def _resolve_npc_collisions(self) -> None:
        """Separate overlapping nearby NPC cars so traffic cannot occupy the same space."""
        self._build_npc_spatial_grid()
        for _ in range(24):
            self._build_npc_spatial_grid()
            resolved_pairs = set()
            found_collision = False
            for npc in self.npcs:
                for other in self._nearby_npcs(npc):
                    if other is npc or other.layer != npc.layer:
                        continue
                    pair = tuple(sorted((id(npc), id(other))))
                    if pair in resolved_pairs:
                        continue
                    resolved_pairs.add(pair)

                    if not boxes_intersect(
                        npc.x, npc.y, npc.heading, npc.length_m, npc.width_m,
                        other.x, other.y, other.heading, other.length_m, other.width_m,
                    ):
                        continue
                    found_collision = True


                    dx = npc.x - other.x
                    dy = npc.y - other.y
                    distance = math.hypot(dx, dy)
                    if distance <= 1e-6:
                        dx = math.cos(npc.heading)
                        dy = math.sin(npc.heading)
                        normalizing_distance = 1.0
                    else:
                        normalizing_distance = distance

                    min_distance = (npc.length_m + other.length_m) * 0.5 + 1.0
                    push = max(0.5, min(8.0, min_distance - distance)) * 0.5
                    nx = dx / normalizing_distance
                    ny = dy / normalizing_distance
                    npc_is_static = npc.state in {"parked", "reserved"}
                    other_is_static = other.state in {"parked", "reserved"}
                    if npc_is_static or other_is_static:
                        if npc_is_static and other_is_static:
                            npc.speed = 0.0
                            other.speed = 0.0
                        elif npc_is_static:
                            other.x -= nx * push * 2.0
                            other.y -= ny * push * 2.0
                            other.speed = 0.0
                            self._keep_npc_near_own_way(other)
                        else:
                            npc.x += nx * push * 2.0
                            npc.y += ny * push * 2.0
                            npc.speed = 0.0
                            self._keep_npc_near_own_way(npc)
                        continue
                    if npc.state == "parking" or other.state == "parking":
                        if npc.state == "parking" and other.state == "parking":
                            npc.speed = 0.0
                            other.speed = 0.0
                        elif npc.state == "parking":
                            other.x -= nx * push * 2.0
                            other.y -= ny * push * 2.0
                            other.speed = 0.0
                            self._keep_npc_near_own_way(other)
                        else:
                            npc.x += nx * push * 2.0
                            npc.y += ny * push * 2.0
                            npc.speed = 0.0
                            self._keep_npc_near_own_way(npc)
                        continue
                    if abs(math.cos(npc.heading - other.heading)) > 0.7:
                        separation = (
                            (npc.x - other.x) * math.cos(npc.heading)
                            + (npc.y - other.y) * math.sin(npc.heading)
                        )
                        direction = 1.0 if separation >= 0.0 else -1.0
                        backoff = 8.0
                        trailing_npc = other if separation >= 0.0 else npc
                        npc.x += math.cos(npc.heading) * backoff * direction
                        npc.y += math.sin(npc.heading) * backoff * direction
                        other.x -= math.cos(npc.heading) * backoff * direction
                        other.y -= math.sin(npc.heading) * backoff * direction
                        self._keep_npc_near_own_way(npc)
                        self._keep_npc_near_own_way(other)
                        trailing_npc.blocked_timer = max(trailing_npc.blocked_timer, 2.0)
                        trailing_npc.escape_timer = max(trailing_npc.escape_timer, 2.0)
                        trailing_npc.overtaking = True
                        trailing_npc.overtake_timer = trailing_npc.escape_timer
                        trailing_npc.target_lane_offset = compute_desired_lane_offset(
                            trailing_npc.way,
                            is_overtaking=getattr(trailing_npc.way, "oneway", 0) != 0,
                            travel_direction=trailing_npc.direction,
                        )
                        npc.speed = 0.0
                        other.speed = 0.0
                        continue
                    npc.x += nx * push
                    npc.y += ny * push
                    other.x -= nx * push
                    other.y -= ny * push
                    self._keep_npc_near_own_way(npc)
                    self._keep_npc_near_own_way(other)
                    if boxes_intersect(
                        npc.x, npc.y, npc.heading, npc.length_m, npc.width_m,
                        other.x, other.y, other.heading, other.length_m, other.width_m,
                    ):
                        backoff = 6.0
                        heading_alignment = abs(
                            math.cos(npc.heading - other.heading)
                        )
                        if heading_alignment > 0.7:
                            separation = (
                                (npc.x - other.x) * math.cos(npc.heading)
                                + (npc.y - other.y) * math.sin(npc.heading)
                            )
                            direction = 1.0 if separation >= 0.0 else -1.0
                            npc.x += math.cos(npc.heading) * backoff * direction
                            npc.y += math.sin(npc.heading) * backoff * direction
                            other.x -= math.cos(other.heading) * backoff * direction
                            other.y -= math.sin(other.heading) * backoff * direction
                        else:
                            npc.x -= math.cos(npc.heading) * backoff
                            npc.y -= math.sin(npc.heading) * backoff
                            other.x -= math.cos(other.heading) * backoff
                            other.y -= math.sin(other.heading) * backoff
                        self._keep_npc_near_own_way(npc)
                        self._keep_npc_near_own_way(other)
                    npc.speed = 0.0
                    other.speed = 0.0
                    self._crash_npc(npc)
                    self._crash_npc(other)
            if not found_collision:
                break

    @staticmethod
    def _speed_profile_for_age(age: int) -> Tuple[bool, float]:
        """Return an age-weighted driving profile for an NPC resident."""
        if 17 <= age <= 25:
            if random.random() < 0.55:
                return True, random.uniform(1.25, 1.55)
            return False, random.uniform(0.92, 1.05)
        if age > 60:
            if random.random() < 0.55:
                return False, random.uniform(0.68, 0.84)
            return False, random.uniform(0.85, 0.98)
        roll = random.random()
        if roll < 0.18:
            return True, random.uniform(1.25, 1.55)
        if roll < 0.85:
            return False, random.uniform(0.92, 1.05)
        return False, random.uniform(0.78, 0.90)

    @staticmethod
    def _keep_npc_near_own_way(npc: NPCCar) -> None:
        """Undo collision displacement that would place a car off its road."""
        best_point = None
        best_distance_sq = math.inf
        points = npc.way.points_m
        for first, second in zip(points, points[1:]):
            dx = second[0] - first[0]
            dy = second[1] - first[1]
            length_sq = dx * dx + dy * dy
            if length_sq <= 1e-9:
                continue
            ratio = max(0.0, min(1.0, ((npc.x - first[0]) * dx + (npc.y - first[1]) * dy) / length_sq))
            point = (first[0] + ratio * dx, first[1] + ratio * dy)
            distance_sq = (npc.x - point[0]) ** 2 + (npc.y - point[1]) ** 2
            if distance_sq < best_distance_sq:
                best_distance_sq = distance_sq
                best_point = point
        if best_point is not None and best_distance_sq > getattr(npc.way, "half_width_m", 4.0) ** 2:
            npc.x, npc.y = best_point

    def _build_spatial_indices(self) -> None:
        """Build spatial index for instant junction lookups and spawning."""
        self._junction_grid.clear()
        self._way_grid.clear()
        self._traffic_light_grid.clear()
        self._crossing_grid.clear()
        j_cs = self._junction_grid_cell_size
        w_cs = self._way_grid_cell_size
        signal_cs = self._signal_grid_cell_size

        for traffic_light in self.traffic_lights:
            cell = (
                int(math.floor(traffic_light.x / signal_cs)),
                int(math.floor(traffic_light.y / signal_cs)),
            )
            self._traffic_light_grid.setdefault(cell, []).append(traffic_light)
        for crossing in self.crossings:
            cell = (
                int(math.floor(crossing.x / signal_cs)),
                int(math.floor(crossing.y / signal_cs)),
            )
            self._crossing_grid.setdefault(cell, []).append(crossing)

        for w in self.ways:
            layer = getattr(w, "layer", 0)
            pts = w.points_m
            n_pts = len(pts)
            for i, pt in enumerate(pts):
                cx = int(math.floor(pt[0] / j_cs))
                cy = int(math.floor(pt[1] / j_cs))
                self._junction_grid.setdefault((cx, cy), []).append((w, i, pt, layer, n_pts))

            bb = getattr(w, "bbox", None)
            if not bb or bb == (0.0, 0.0, 0.0, 0.0):
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                bb = (min(xs), min(ys), max(xs), max(ys))
            min_cx = int(math.floor(bb[0] / w_cs))
            max_cx = int(math.floor(bb[2] / w_cs))
            min_cy = int(math.floor(bb[1] / w_cs))
            max_cy = int(math.floor(bb[3] / w_cs))
            for cx in range(min_cx, max_cx + 1):
                for cy in range(min_cy, max_cy + 1):
                    self._way_grid.setdefault((cx, cy), []).append(w)

    def _nearby_traffic_lights(self, x: float, y: float) -> List[TrafficLight]:
        cell_size = self._signal_grid_cell_size
        cell_x = int(math.floor(x / cell_size))
        cell_y = int(math.floor(y / cell_size))
        nearby: List[TrafficLight] = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby.extend(self._traffic_light_grid.get((cell_x + offset_x, cell_y + offset_y), []))
        return nearby

    def _nearby_crossings(self, x: float, y: float) -> List:
        cell_size = self._signal_grid_cell_size
        cell_x = int(math.floor(x / cell_size))
        cell_y = int(math.floor(y / cell_size))
        nearby = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby.extend(self._crossing_grid.get((cell_x + offset_x, cell_y + offset_y), []))
        return nearby

    def _roadwork_stop_distance(self, npc: NPCCar) -> Optional[float]:
        """Return distance to an upcoming fully closed work zone."""
        heading_x = math.cos(npc.heading)
        heading_y = math.sin(npc.heading)
        for work in self.roadworks:
            if work.lane_closed or work.way is not npc.way or work.way.layer != npc.layer:
                continue
            axis_x = work.end[0] - work.start[0]
            axis_y = work.end[1] - work.start[1]
            axis_length = math.hypot(axis_x, axis_y)
            if axis_length <= 0.0:
                continue
            axis_x /= axis_length
            axis_y /= axis_length
            if heading_x * axis_x + heading_y * axis_y < 0.7:
                axis_x = -axis_x
                axis_y = -axis_y
                boundary_x, boundary_y = work.end
            else:
                boundary_x, boundary_y = work.start
            lateral = abs((boundary_x - npc.x) * -heading_y + (boundary_y - npc.y) * heading_x)
            distance = (boundary_x - npc.x) * heading_x + (boundary_y - npc.y) * heading_y
            if 0.0 < distance < 35.0 and lateral <= getattr(work.way, "half_width_m", 4.0):
                return max(0.0, distance - 2.0)
        return None

    @staticmethod
    def _turn_signal_for_route(old_heading: float, npc: NPCCar) -> str:
        """Return turn direction for a newly selected route."""
        points = npc.way.points_m
        if len(points) < 2:
            return ""

        if npc.direction == 1 and npc.segment_idx + 1 < len(points):
            target = points[npc.segment_idx + 1]
        elif npc.direction == -1 and npc.segment_idx < len(points):
            target = points[npc.segment_idx]
        else:
            return ""
        new_heading = math.atan2(target[1] - npc.y, target[0] - npc.x)
        turn = (new_heading - old_heading + math.pi) % (2 * math.pi) - math.pi
        if math.radians(20) < turn < math.radians(160):
            return "left"
        if -math.radians(160) < turn < -math.radians(20):
            return "right"
        return ""

    @staticmethod
    def _turn_signal_for_next_route(npc: NPCCar) -> str:
        """Return the indicator direction for a route prepared at the next junction."""
        if npc.next_route is None:
            return ""
        next_way, next_segment_idx, next_direction = npc.next_route
        points = next_way.points_m
        if next_direction == 1:
            if next_segment_idx + 1 >= len(points):
                return ""
            next_start, next_end = points[next_segment_idx], points[next_segment_idx + 1]
        else:
            if next_segment_idx < 0 or next_segment_idx + 1 >= len(points):
                return ""
            next_start, next_end = points[next_segment_idx + 1], points[next_segment_idx]
        new_heading = math.atan2(next_end[1] - next_start[1], next_end[0] - next_start[0])
        turn = (new_heading - npc.heading + math.pi) % (2 * math.pi) - math.pi
        if math.radians(20) < turn < math.radians(160):
            return "left"
        if -math.radians(160) < turn < -math.radians(20):
            return "right"
        return ""

    @staticmethod
    def _turn_path(
            npc: NPCCar, next_route: Tuple[Way, int, int], start: Tuple[float, float]
    ) -> Optional[List[Tuple[float, float]]]:
            """Build a sampled tangent Bézier path through a non-straight junction."""
            next_way, next_segment_idx, next_direction = next_route
            incoming_points = npc.way.points_m
            if npc.direction == 1:
                incoming_start = incoming_points[max(0, npc.segment_idx)]
                incoming_end = incoming_points[min(len(incoming_points) - 1, npc.segment_idx + 1)]
            else:
                incoming_start = incoming_points[min(len(incoming_points) - 1, npc.segment_idx + 1)]
                incoming_end = incoming_points[max(0, npc.segment_idx)]
            outgoing_points = next_way.points_m
            if next_direction == 1:
                outgoing_start = outgoing_points[next_segment_idx]
                outgoing_end = outgoing_points[next_segment_idx + 1]
            else:
                outgoing_start = outgoing_points[next_segment_idx + 1]
                outgoing_end = outgoing_points[next_segment_idx]
            in_length = math.hypot(incoming_end[0] - incoming_start[0], incoming_end[1] - incoming_start[1])
            out_length = math.hypot(outgoing_end[0] - outgoing_start[0], outgoing_end[1] - outgoing_start[1])
            if in_length < 1e-3 or out_length < 1e-3:
                return None
            in_dir = ((incoming_end[0] - incoming_start[0]) / in_length,
                      (incoming_end[1] - incoming_start[1]) / in_length)
            out_dir = ((outgoing_end[0] - outgoing_start[0]) / out_length,
                       (outgoing_end[1] - outgoing_start[1]) / out_length)
            out_normal = (out_dir[1], -out_dir[0])
            lane_offset = compute_desired_lane_offset(next_way, False, next_direction)
            exit_distance = max(8.0, min(16.0, out_length * 0.4))
            exit_point = (
                outgoing_start[0] + out_dir[0] * exit_distance + out_normal[0] * lane_offset,
                outgoing_start[1] + out_dir[1] * exit_distance + out_normal[1] * lane_offset,
            )
            # Scale handles by road width, wheelbase, and angle without imposing one radius.
            angle = abs(math.atan2(in_dir[0] * out_dir[1] - in_dir[1] * out_dir[0],
                                   in_dir[0] * out_dir[0] + in_dir[1] * out_dir[1]))
            if angle <= math.radians(20.0) or angle >= math.radians(160.0):
                return None
            handle = max(3.0, min(12.0, npc.turning_radius_m * (0.7 + angle / math.pi)))
            handle = min(handle, in_length * 0.45, out_length * 0.45)
            p0 = start
            p1 = (p0[0] + in_dir[0] * handle, p0[1] + in_dir[1] * handle)
            p2 = (exit_point[0] - out_dir[0] * handle, exit_point[1] - out_dir[1] * handle)
            points = []
            for index in range(1, 17):
                t = index / 16.0
                inv = 1.0 - t
                points.append((
                    inv**3 * p0[0] + 3 * inv**2 * t * p1[0] + 3 * inv * t**2 * p2[0] + t**3 * exit_point[0],
                    inv**3 * p0[1] + 3 * inv**2 * t * p1[1] + 3 * inv * t**2 * p2[1] + t**3 * exit_point[1],
                ))
            return [p0] + points

    def _transition_to_route(
            self, npc: NPCCar, next_route: Tuple[Way, int, int], old_heading: float
    ) -> None:
            """Switch logical roads while bridging a turn with a physical trajectory."""
            turn_path = self._turn_path(npc, next_route, (npc.x, npc.y))
            next_way, next_segment_idx, next_direction = next_route
            npc.way, npc.segment_idx, npc.direction = next_way, next_segment_idx, next_direction
            npc.layer = getattr(next_way, "layer", 0)
            npc.target_speed = calculate_npc_target_speed(next_way, npc.speed_factor)
            npc.turn_signal = self._turn_signal_for_route(old_heading, npc)
            npc.turn_signal_elapsed = 0.0
            npc.target_lane_offset = compute_desired_lane_offset(next_way, npc.overtaking, next_direction)
            npc.next_route = None
            npc.turn_recovery_timer = 60.0
            npc.turn_trajectory = turn_path
            npc.turn_trajectory_index = 0

    @staticmethod
    def _advance_turn_trajectory(npc: NPCCar, distance: float, movement_dt: float) -> bool:
            """Move along the sampled turn path; return whether it is still active."""
            path = npc.turn_trajectory
            if not path:
                return False
            while distance > 1e-6 and npc.turn_trajectory_index < len(path) - 1:
                index = npc.turn_trajectory_index
                start, end = path[index], path[index + 1]
                dx, dy = end[0] - start[0], end[1] - start[1]
                length = math.hypot(dx, dy)
                if length < 1e-6:
                    npc.turn_trajectory_index += 1
                    continue
                direction = (dx / length, dy / length)
                next_heading = math.atan2(direction[1], direction[0])
                heading_delta = (next_heading - npc.heading + math.pi) % (2.0 * math.pi) - math.pi
                desired_steering = max(
                    -npc.max_steering_angle,
                    min(npc.max_steering_angle, math.atan2(npc.wheelbase_m * heading_delta, max(length, 1.0))),
                )
                steering_delta = desired_steering - npc.steering_angle
                max_delta = math.radians(85.0) * movement_dt
                npc.steering_angle += max(-max_delta, min(max_delta, steering_delta))
                step = min(distance, length)
                ratio = step / length
                npc.x += dx * ratio
                npc.y += dy * ratio
                npc.heading = next_heading
                distance -= step
                if step >= length - 1e-6:
                    npc.turn_trajectory_index += 1
                else:
                    # Consume the polyline segment so the next frame continues
                    # from the vehicle rather than replaying its first portion.
                    path[index] = (npc.x, npc.y)
            if npc.turn_trajectory_index >= len(path) - 1:
                npc.x, npc.y = path[-1]
                npc.turn_trajectory = None
                npc.turn_trajectory_index = 0
                npc.lane_offset = npc.target_lane_offset
                return False
            return True
    def sync_map_data(
        self,
        ways: List[Way],
        traffic_lights: Optional[List[TrafficLight]] = None,
        stop_signs: Optional[List[StopSign]] = None,
        crossings: Optional[List] = None,
        buildings: Optional[List] = None,
        sceneries: Optional[List] = None,
    ) -> None:
        """Update road references when dynamic tiles expand."""
        self.ways = connected_drivable_ways(ways)
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights
        if stop_signs is not None:
            self.stop_signs = stop_signs
        if crossings is not None:
            self.crossings = crossings
        if hasattr(self, "parking_spaces"):
            self._build_parking_grid()
        if buildings is not None:
            self.buildings = buildings
        if sceneries is not None:
            self.sceneries = sceneries
        self.logical_intersections = build_logical_intersections(self.traffic_lights, self.ways)
        self.traffic_light_manager = TrafficLightManager(self.logical_intersections)
        self.intersection_manager = IntersectionManager(self.logical_intersections)
        self._build_route_graph()
        self._build_static_collision_grids()
        self._build_spatial_indices()

    def plan_route(
        self,
        start: Tuple[float, float],
        target: Tuple[float, float],
        layer: Optional[int] = None,
    ) -> Optional[List[Tuple[float, float]]]:
        """Return a shortest route over road vertices between two map positions."""
        nodes = self._route_nodes
        edges = self._route_edges_by_layer.get(layer, {}) if layer is not None else self._route_edges
        if layer is not None:
            allowed_nodes = {index for index, node in enumerate(nodes) if node[2] == layer}
            nodes_for_route = [node for node in nodes]
            edges_for_route = edges
        else:
            nodes_for_route = nodes
            edges_for_route = edges

        if not nodes:
            return None
        start_candidates = sorted(
            edges_for_route,
            key=lambda index: (nodes_for_route[index][0] - start[0]) ** 2 + (nodes_for_route[index][1] - start[1]) ** 2,
        )[:12]
        target_candidates = sorted(
            edges_for_route,
            key=lambda index: (nodes_for_route[index][0] - target[0]) ** 2 + (nodes_for_route[index][1] - target[1]) ** 2,
        )[:12]
        distances = {}
        previous: dict[int, int] = {}
        queue = []
        for start_id in start_candidates:
            connector = math.hypot(nodes_for_route[start_id][0] - start[0], nodes_for_route[start_id][1] - start[1])
            distances[start_id] = connector
            heapq.heappush(queue, (connector, start_id))
        while queue:
            distance, current = heapq.heappop(queue)
            if distance != distances.get(current):
                continue
            for neighbor, edge_distance in edges_for_route[current]:
                new_distance = distance + edge_distance
                if new_distance < distances.get(neighbor, math.inf):
                    distances[neighbor] = new_distance
                    previous[neighbor] = current
                    heapq.heappush(queue, (new_distance, neighbor))
        best_path = None
        best_score = math.inf
        best_target = None
        for target_id in target_candidates:
            if target_id not in distances:
                continue
            target_connector = math.hypot(nodes_for_route[target_id][0] - target[0], nodes_for_route[target_id][1] - target[1])
            score = distances[target_id] + target_connector
            if score < best_score:
                best_score = score
                best_target = target_id
        if best_target is not None:
            path = [best_target]
            while path[-1] in previous:
                path.append(previous[path[-1]])
            path.reverse()
            best_path = path
        if best_path is None:
            return None
        return [(start[0], start[1])] + [(nodes_for_route[index][0], nodes_for_route[index][1]) for index in best_path] + [target]

    def set_target_count(self, target_count: int, player_car: Optional[Car] = None) -> None:
        """Adjust active traffic count and discard farthest cars when zoom reduces it."""
        self.target_count = max(0, min(MAX_TRAFFIC_COUNT, target_count))
        regular_npcs = [npc for npc in self.npcs if not npc.is_taxi]
        if len(regular_npcs) > self.target_count:
            if player_car is not None:
                regular_npcs.sort(key=lambda npc: math.hypot(npc.x - player_car.x, npc.y - player_car.y))
            keep_ids = {id(npc) for npc in regular_npcs[:self.target_count]}
            for npc in regular_npcs:
                if id(npc) not in keep_ids:
                    self.release_parking_space(npc)
            self.npcs = [npc for npc in self.npcs if npc.is_taxi or id(npc) in keep_ids]

    def spawn_taxis_at_nearby_stops(
        self,
        taxi_stops: List,
        player_car: Car,
        viewport_bounds: Optional[Tuple[float, float, float, float]],
        all_stops: bool = False,
    ) -> int:
        """Keep each taxi stand populated with zero to one parked taxi."""
        if viewport_bounds is None and not all_stops:
            return 0

        vmin_x, vmin_y, vmax_x, vmax_y = viewport_bounds or (0.0, 0.0, 0.0, 0.0)
        spawned = 0
        for stop in taxi_stops:
            stop_key = (stop.x, stop.y, getattr(stop, "id", None))
            if not all_stops and stop_key in self._taxi_stop_spawns:
                continue
            if not all_stops and vmin_x <= stop.x <= vmax_x and vmin_y <= stop.y <= vmax_y:
                continue
            if not all_stops and math.hypot(stop.x - player_car.x, stop.y - player_car.y) > 120.0:
                continue

            nearby_taxis = [
                npc for npc in self.npcs
                if npc.is_taxi and math.hypot(npc.x - stop.x, npc.y - stop.y) <= 12.0
            ]
            if all_stops:
                desired_count = self._taxi_stop_targets.setdefault(stop_key, random.randint(0, 1))
            else:
                self._taxi_stop_spawns.add(stop_key)
                desired_count = random.randint(0, 1)
            for _ in range(max(0, desired_count - len(nearby_taxis))):
                npc = self.spawn_npc(
                    stop.x,
                    stop.y, viewport_bounds=None if all_stops else viewport_bounds,
                    near_heading=player_car.heading,
                    max_distance_m=12.0,
                )
                if npc is None:
                    break
                npc.is_taxi = True
                npc.vehicle_type = "car"
                npc.speed = 0.0
                npc.target_speed = 0.0
                npc.taxi_stop_target = (stop.x, stop.y) if all_stops else None
                npc.waiting_at_taxi_stop = not all_stops
                spawned += 1
        return spawned

    def let_taxi_pick_up_waiter(self, taxi_stops: List, pedestrians: List, dt: float = 1.0 / 60.0) -> None:
        """Let a nearby NPC taxi collect one waiting customer at a time."""
        for npc in self.npcs:
            if not npc.is_taxi:
                continue
            for pedestrian in pedestrians[:]:
                if getattr(pedestrian, "rival_taxi", None) is not npc:
                    continue
                dx = npc.x - pedestrian.x
                dy = npc.y - pedestrian.y
                distance = math.hypot(dx, dy)
                if distance <= 1.5:
                    pedestrians.remove(pedestrian)
                    npc.taxi_pickup_timer = 0.8
                else:
                    pedestrian.heading = math.atan2(dy, dx)
                    step = min(distance, 2.2 * dt)
                    pedestrian.x += math.cos(pedestrian.heading) * step
                    pedestrian.y += math.sin(pedestrian.heading) * step
                break
            if npc.taxi_pickup_timer > 0.0:
                continue
            for stop in taxi_stops:
                if math.hypot(npc.x - stop.x, npc.y - stop.y) > 8.0:
                    continue
                for pedestrian in pedestrians:
                    if not getattr(pedestrian, "is_taxi_stop_waiter", False):
                        continue
                    if math.hypot(pedestrian.x - stop.x, pedestrian.y - stop.y) > 5.0:
                        continue
                    npc.speed = 0.0
                    npc.taxi_pickup_timer = 1.5
                    pedestrian.rival_taxi = npc
                    pedestrian.is_walking_to_car = True
                    break
                if npc.taxi_pickup_timer > 0.0:
                    break

    def rage_shout(self, player_car: Car, radius_m: float = 50.0) -> int:
        """Move NPCs ahead of the player toward their road edge immediately."""
        moved = 0
        player_heading_x = math.cos(player_car.heading)
        player_heading_y = math.sin(player_car.heading)

        for npc in self.npcs:
            if npc.layer != player_car.layer:
                continue
            delta_x = npc.x - player_car.x
            delta_y = npc.y - player_car.y
            distance = math.hypot(delta_x, delta_y)
            if distance > radius_m or delta_x * player_heading_x + delta_y * player_heading_y <= 0.0:
                continue

            road_half_width = getattr(npc.way, "half_width_m", 4.0)
            edge_offset = road_half_width + max(1.0, npc.width_m * 0.75)
            segment_index = min(max(npc.segment_idx, 0), len(npc.way.points_m) - 2)
            start = npc.way.points_m[segment_index]
            end = npc.way.points_m[segment_index + 1]
            segment_x = end[0] - start[0]
            segment_y = end[1] - start[1]
            segment_length = math.hypot(segment_x, segment_y)
            if segment_length <= 1e-3:
                continue

            normal_x = segment_y / segment_length
            normal_y = -segment_x / segment_length
            center_delta_x = npc.x - start[0]
            center_delta_y = npc.y - start[1]
            current_offset = center_delta_x * normal_x + center_delta_y * normal_y
            edge_sign = 1.0 if current_offset >= 0.0 else -1.0
            npc.target_lane_offset = edge_sign * edge_offset
            npc.lane_offset = npc.target_lane_offset
            npc.x += normal_x * (npc.target_lane_offset - current_offset)
            npc.y += normal_y * (npc.target_lane_offset - current_offset)
            npc.rage_timer = 5.0
            npc.escape_timer = max(npc.escape_timer, 5.0)
            moved += 1

        if moved:
            logger.info("Rattiraivo moved %d NPC vehicles aside", moved)
        return moved

    def _find_next_way_and_segment(
        self,
        current_way: Way,
        at_point: Tuple[float, float],
        incoming_heading: Optional[float] = None,
        exclude_reverse: bool = False,
        preferred_point: Optional[Tuple[float, float]] = None,
    ) -> Optional[Tuple[Way, int, int]]:
        """Find a connected way at junction point to continue driving seamlessly using spatial grid."""
        tol = 3.0  # 3 meter connection tolerance
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
                    same_layer = layer == current_layer
                    current_endpoint = any(
                        math.hypot(at_point[0] - endpoint[0], at_point[1] - endpoint[1]) <= tol
                        for endpoint in (current_way.points_m[0], current_way.points_m[-1])
                    )
                    candidate_endpoint = i in (0, n_pts - 1)
                    roundabout = getattr(w, "is_roundabout", False)
                    layer_transition = (
                        current_endpoint
                        and candidate_endpoint
                        and (
                            getattr(current_way, "is_bridge", False)
                            or getattr(current_way, "is_tunnel", False)
                            or getattr(w, "is_bridge", False)
                            or getattr(w, "is_tunnel", False)
                        )
                    )
                    if not same_layer and not layer_transition:
                        continue
                    dist_sq = (pt[0] - at_x) ** 2 + (pt[1] - at_y) ** 2
                    if dist_sq <= tol_sq:
                        oneway = getattr(w, "oneway", 0)
                        if roundabout:
                            # Finnish roundabouts circulate counter-clockwise, regardless
                            # of the direction in which OSM stored the closed way.
                            direction = self._roundabout_direction(w)
                            if direction == 1 and i < n_pts - 1:
                                candidates.append((w, i, 1))
                            elif direction == -1 and i > 0:
                                candidates.append((w, i - 1, -1))
                        else:
                            # Can travel forward from vertex i (if not at the end)
                            if i < n_pts - 1 and oneway >= 0:
                                candidates.append((w, i, 1))
                            # Can travel backward from vertex i (if not at the start)
                            if i > 0 and oneway <= 0:
                                candidates.append((w, i - 1, -1))

        if not candidates:
            return None

        # Filter candidates based on incoming heading to prevent 180-degree U-turns unless no other option
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
                # Angle difference > 135 deg (~2.35 rad) is considered a 180-deg reversal/U-turn
                if angle_diff < math.radians(135):
                    forward_candidates.append(cand)
            if forward_candidates:
                candidates = forward_candidates

        if preferred_point is not None:
            def exit_point(candidate: Tuple[Way, int, int]) -> Tuple[float, float]:
                way, segment_index, direction = candidate
                return way.points_m[segment_index + 1 if direction == 1 else segment_index]

            candidates.sort(
                key=lambda candidate: (
                    (exit_point(candidate)[0] - preferred_point[0]) ** 2
                    + (exit_point(candidate)[1] - preferred_point[1]) ** 2,
                    candidate[0] is current_way,
                )
            )
            alternatives = (
                [candidate for candidate in candidates if candidate[0] is not current_way]
                if getattr(current_way, "is_roundabout", False)
                else []
            )
            if alternatives:
                return alternatives[0]
            return candidates[0]

        # Filter out exact same way if alternatives exist to encourage turns
        alternatives = [c for c in candidates if c[0] is not current_way]
        if alternatives:
            if any(getattr(c[0], "layer", 0) != current_layer for c in alternatives):
                return random.choice(alternatives)
            # 70% chance to turn into another intersecting street if available
            if random.random() < 0.7:
                return random.choice(alternatives)

        # If asked to exclude reverse on the same segment
        valid_candidates = candidates
        if exclude_reverse:
            valid_candidates = [c for c in candidates if c[0] is not current_way]
            if not valid_candidates:
                return None

        return random.choice(valid_candidates)

    def _assign_new_travel_plan(self, npc: NPCCar) -> bool:
        """Assign a complete road-node route to an NPC and its resident driver."""
        if npc.route_retry_timer > 0.0:
            return False
        if not self._route_nodes:
            npc.route_retry_timer = 1.0
            return False
        current_layer = getattr(npc.way, "layer", 0)
        destinations = [
            (node[0], node[1])
            for node in self._route_nodes
            if node[2] == current_layer
            and math.hypot(node[0] - npc.x, node[1] - npc.y) >= 150.0
        ]
        if not destinations:
            npc.route_retry_timer = 1.0
            return False
        resident = self.residents.get(npc.owner_id)
        if not self.residents.can_drive(resident):
            return False
        destination = random.choice(destinations)
        route = self.plan_route((npc.x, npc.y), destination, layer=current_layer)
        if not route or len(route) < 2:
            npc.route_retry_timer = 1.0
            return False
        npc.travel_route = route
        npc.travel_route_index = 1
        npc.destination = route[-1]
        npc.destination_parking_space_id = None
        npc.next_route = None
        npc.route_retry_timer = 0.0
        if resident is not None:
            resident.mode = "driving"
            resident.active_vehicle_id = id(npc)
        return True

    @staticmethod
    def _roundabout_direction(way: Way) -> int:
        """Return point traversal direction that is geometrically counter-clockwise."""
        points = way.points_m
        area = sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(points, points[1:])
        )
        return 1 if area >= 0.0 else -1

    def _roundabout_entry_blocked(
        self, npc: NPCCar, roundabout: Way, entry: Tuple[float, float]
    ) -> bool:
        """Yield at a roundabout entry when circulating traffic is approaching it."""
        for other in self.npcs:
            if other is npc or other.way is not roundabout or other.layer != npc.layer:
                continue
            if math.hypot(other.x - entry[0], other.y - entry[1]) <= 28.0:
                return True
        return False

    def _prepare_next_route(self, npc: NPCCar) -> None:
        """Choose the next route as soon as the NPC approaches a known junction."""
        if npc.next_route is not None or npc.turn_trajectory is not None or len(npc.way.points_m) < 2:
            return
        if npc.direction == 1:
            if npc.segment_idx + 1 >= len(npc.way.points_m):
                return
            junction_point = npc.way.points_m[npc.segment_idx + 1]
        else:
            if npc.segment_idx >= len(npc.way.points_m):
                return
            junction_point = npc.way.points_m[npc.segment_idx]
        if self._junction_at_point(junction_point, npc.layer) is None:
            return
        preferred_point = None
        if npc.travel_route:
            route_points = npc.travel_route
            remaining_indices = range(
                min(npc.travel_route_index, len(route_points) - 1),
                len(route_points),
            )
            preferred_index = min(
                remaining_indices,
                key=lambda index: math.hypot(
                    route_points[index][0] - junction_point[0],
                    route_points[index][1] - junction_point[1],
                ),
            )
            npc.travel_route_index = preferred_index
            if preferred_index + 1 < len(route_points):
                preferred_point = route_points[preferred_index + 1]
        npc.next_route = self._find_next_way_and_segment(
            npc.way,
            junction_point,
            incoming_heading=npc.heading,
            preferred_point=preferred_point,
        )

    def _advance_travel_route(self, npc: NPCCar, junction_point: Tuple[float, float]) -> None:
        """Advance the persistent route cursor after crossing a planned junction."""
        if not npc.travel_route:
            return
        for index in range(npc.travel_route_index, len(npc.travel_route)):
            point = npc.travel_route[index]
            if math.hypot(point[0] - junction_point[0], point[1] - junction_point[1]) <= 8.0:
                npc.travel_route_index = min(index + 1, len(npc.travel_route) - 1)
                return

    def _junction_at_point(self, point: Tuple[float, float], layer: int) -> Optional[Tuple[float, float]]:
        """Return a shared same-layer way vertex when point belongs to a junction."""
        tol = 3.0
        cx = int(math.floor(point[0] / self._junction_grid_cell_size))
        cy = int(math.floor(point[1] / self._junction_grid_cell_size))
        matches = []
        way_ids = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for way, _, vertex, vertex_layer, _ in self._junction_grid.get((cx + dx, cy + dy), []):
                    if vertex_layer == layer and math.hypot(point[0] - vertex[0], point[1] - vertex[1]) <= tol:
                        way_ids.add(id(way))
                        matches.append(vertex)
        if len(way_ids) < 2 or not matches:
            return None
        return matches[0]

    def _junction_is_occupied(self, junction_point: Tuple[float, float], npc: NPCCar) -> bool:
        """Check whether another same-layer NPC is still inside a junction."""
        for other in self.npcs:
            if other is npc or other.layer != npc.layer or other.state in {"parked", "reserved", "parking"}:
                continue
            distance = math.hypot(other.x - junction_point[0], other.y - junction_point[1])
            if distance < 8.0 or (other.state == "turning" and distance < 12.0):
                return True
        return False

    @staticmethod
    def _planned_turn_direction(npc: NPCCar) -> str:
        """Return planned turn direction, treating an unknown movement as straight."""
        if npc.turn_signal in {"left", "right"}:
            return npc.turn_signal
        if npc.next_route is None:
            return "straight"
        next_way, next_segment_idx, next_direction = npc.next_route
        points = next_way.points_m
        if next_direction == 1:
            start, end = points[next_segment_idx], points[next_segment_idx + 1]
        else:
            start, end = points[next_segment_idx + 1], points[next_segment_idx]
        next_heading = math.atan2(end[1] - start[1], end[0] - start[0])
        turn = (next_heading - npc.heading + math.pi) % (2.0 * math.pi) - math.pi
        if math.radians(20) < turn < math.radians(160):
            return "left"
        if -math.radians(160) < turn < -math.radians(20):
            return "right"
        return "straight"

    def _junction_is_clear_for(self, npc: NPCCar, junction_point: Tuple[float, float]) -> bool:
        """Apply priority-road, left-turn, and Finnish yield-to-right rules."""
        npc_priority = bool(getattr(npc.way, "priority_road", False))
        npc_turn = self._planned_turn_direction(npc)
        for other in self.npcs:
            if (
                other is npc
                or other.layer != npc.layer
                or other.state in {"parked", "reserved", "parking"}
                or not other.has_driver()
            ):
                continue
            dx = other.x - junction_point[0]
            dy = other.y - junction_point[1]
            distance = math.hypot(dx, dy)
            if distance > 24.0:
                continue
            toward_x = -dx / max(distance, 1e-6)
            toward_y = -dy / max(distance, 1e-6)
            if math.cos(other.heading) * toward_x + math.sin(other.heading) * toward_y < 0.5:
                continue
            other_priority = bool(getattr(other.way, "priority_road", False))
            if npc_priority and not other_priority:
                continue
            if not npc_priority and other_priority:
                return False
            if npc_turn == "left":
                opposing = math.cos(other.heading) * math.cos(npc.heading) + math.sin(other.heading) * math.sin(npc.heading)
                if opposing < -0.5 and self._planned_turn_direction(other) != "left":
                    return False
            right_x = math.sin(npc.heading)
            right_y = -math.cos(npc.heading)
            relative_x = other.x - npc.x
            relative_y = other.y - npc.y
            if relative_x * right_x + relative_y * right_y > 0.0:
                return False
        return True

    def _junction_deadlock_can_proceed(self, npc: NPCCar, junction_point: Tuple[float, float]) -> bool:
        """Let the closest fully stopped queue leader force its planned movement."""
        candidates = []
        for other in self.npcs:
            if other.layer != npc.layer or other.state in {"parked", "reserved", "parking"} or not other.has_driver():
                continue
            distance = math.hypot(other.x - junction_point[0], other.y - junction_point[1])
            if distance > 24.0:
                continue
            if other is npc or (other.state != "turning" and other.speed <= 1.0):
                candidates.append((distance, other))
        candidates.sort(
            key=lambda candidate: (candidate[0], -candidate[1].junction_wait_timer, id(candidate[1]))
        )
        if not candidates:
            return False
        leader = candidates[0][1]
        if leader is npc:
            return True
        # Let an aging queue move after the nearer approach has had a fair turn.
        # This breaks cyclic right-of-way waits without changing normal ordering.
        return npc.junction_wait_timer >= leader.junction_wait_timer + 2.0

    def _junction_near_point(self, point: Tuple[float, float], layer: int) -> bool:
        """Return whether point is inside a shared same-layer junction."""
        cx = int(math.floor(point[0] / self._junction_grid_cell_size))
        cy = int(math.floor(point[1] / self._junction_grid_cell_size))
        nearby_ways = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for way, _, vertex, vertex_layer, _ in self._junction_grid.get((cx + dx, cy + dy), []):
                    if vertex_layer == layer and math.hypot(point[0] - vertex[0], point[1] - vertex[1]) <= 10.0:
                        nearby_ways.add(id(way))
        return len(nearby_ways) >= 2

    def spawn_npc(
        self,
        near_x: float,
        near_y: float,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
        near_heading: Optional[float] = None,
        max_distance_m: Optional[float] = None,
    ) -> Optional[NPCCar]:
        """Spawn a new NPC car near the given location just outside the viewport edge."""
        if not self.ways:
            return None

        # Query nearby ways from spatial grid
        w_cs = self._way_grid_cell_size
        r = self.spawn_radius_m
        min_cx = int(math.floor((near_x - r) / w_cs))
        max_cx = int(math.floor((near_x + r) / w_cs))
        min_cy = int(math.floor((near_y - r) / w_cs))
        max_cy = int(math.floor((near_y + r) / w_cs))

        nearby_ways = []
        seen = set()
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

        # Filter ways that actually pass within spawn_radius_m of (near_x, near_y)
        valid_ways = []
        for w in nearby_ways:
            for p in w.points_m:
                if (p[0] - near_x) ** 2 + (p[1] - near_y) ** 2 <= r * r:
                    valid_ways.append(w)
                    break

        if not valid_ways:
            return None

        # Try up to 30 candidate ways/segments to place car outside viewport
        random.shuffle(valid_ways)
        for chosen_way in valid_ways[:30]:
            if len(chosen_way.points_m) < 2:
                continue

            # Pick a candidate segment
            candidate_segments = []
            for s_idx in range(len(chosen_way.points_m) - 1):
                sp1 = chosen_way.points_m[s_idx]
                sp2 = chosen_way.points_m[s_idx + 1]
                smx = (sp1[0] + sp2[0]) * 0.5
                smy = (sp1[1] + sp2[1]) * 0.5
                if (smx - near_x) ** 2 + (smy - near_y) ** 2 <= (r * 1.5) ** 2:
                    candidate_segments.append(s_idx)

            if not candidate_segments:
                candidate_segments = list(range(len(chosen_way.points_m) - 1))

            random.shuffle(candidate_segments)
            for seg_idx in candidate_segments:
                p1 = chosen_way.points_m[seg_idx]
                p2 = chosen_way.points_m[seg_idx + 1]

                for _ in range(8):  # Try multiple random points along segment
                    t = random.uniform(0.1, 0.9)
                    x = p1[0] + t * (p2[0] - p1[0])
                    y = p1[1] + t * (p2[1] - p1[1])

                    # When viewport bounds are supplied, enforce spawning just outside view edges
                    if viewport_bounds:
                        vminx, vminy, vmaxx, vmaxy = viewport_bounds
                        if vminx <= x <= vmaxx and vminy <= y <= vmaxy:
                            continue
                    if max_distance_m is not None and math.hypot(x - near_x, y - near_y) > max_distance_m:
                        continue

                    if near_heading is not None:
                        forward_distance = (
                            (x - near_x) * math.cos(near_heading)
                            + (y - near_y) * math.sin(near_heading)
                        )
                        if forward_distance <= 0.0:
                            continue

                    oneway = getattr(chosen_way, "oneway", 0)
                    if getattr(chosen_way, "is_roundabout", False):
                        direction = self._roundabout_direction(chosen_way)
                    else:
                        direction = 1 if oneway >= 0 else -1
                    if oneway == 0 and not getattr(chosen_way, "is_roundabout", False):
                        direction = 1 if random.random() < 0.5 else -1

                    if direction == 1:
                        heading = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                    else:
                        heading = math.atan2(p1[1] - p2[1], p1[0] - p2[0])

                    lane_offset = compute_desired_lane_offset(
                        chosen_way, is_overtaking=False, travel_direction=direction
                    )

                    # Apply lane offset perpendicularly to heading (positive = to the right)
                    right_perp_x = math.sin(heading)
                    right_perp_y = -math.cos(heading)
                    x += right_perp_x * lane_offset
                    y += right_perp_y * lane_offset

                    # Re-verify position is outside viewport after lane offset
                    if viewport_bounds:
                        vminx, vminy, vmaxx, vmaxy = viewport_bounds
                        if vminx <= x <= vmaxx and vminy <= y <= vmaxy:
                            continue

                    layer = getattr(chosen_way, "layer", 0)

                    # Keep initial traffic out of junction conflict zones.
                    junction_ids = set()
                    j_cx = int(math.floor(x / self._junction_grid_cell_size))
                    j_cy = int(math.floor(y / self._junction_grid_cell_size))
                    for jdx in (-1, 0, 1):
                        for jdy in (-1, 0, 1):
                            for junction_way, _, junction_point, junction_layer, _ in self._junction_grid.get(
                                (j_cx + jdx, j_cy + jdy), []
                            ):
                                if junction_layer == layer and math.hypot(
                                    x - junction_point[0], y - junction_point[1]
                                ) < 18.0:
                                    junction_ids.add(id(junction_way))
                    near_junction = len(junction_ids) > 1
                    if near_junction:
                        continue

                    # Sanity check: do not spawn right on top of player
                    dist_to_player = math.hypot(x - near_x, y - near_y)
                    if dist_to_player < self.min_spawn_dist_to_player_m:
                        continue

                    # Sanity check: do not spawn too close to existing NPC cars on same layer
                    too_close_to_npc = False
                    for existing_npc in self.npcs:
                        if existing_npc.layer == layer:
                            distance = math.hypot(x - existing_npc.x, y - existing_npc.y)
                            lateral_distance = abs(
                                -math.sin(heading) * (existing_npc.x - x)
                                + math.cos(heading) * (existing_npc.y - y)
                            )
                            same_lane = lateral_distance < (1.8 + existing_npc.width_m) * 0.75
                            if distance < self.min_spawn_dist_to_npc_m and same_lane:
                                too_close_to_npc = True
                                break
                    if too_close_to_npc:
                        continue

                    owner = self.residents.create("driving", age=17)
                    is_speeder, speed_factor = self._speed_profile_for_age(
                        self.residents.age_of(owner)
                    )

                    vehicle_type = "car"
                    if self.enable_two_wheelers:
                        vehicle_roll = random.random()
                        if vehicle_roll < 0.12:
                            vehicle_type = "motorcycle"
                        elif vehicle_roll < 0.24:
                            vehicle_type = "moped"

                    target_spd = calculate_npc_target_speed(chosen_way, speed_factor)
                    if vehicle_type == "motorcycle":
                        target_spd = min(target_spd, 32.0)
                    elif vehicle_type == "moped":
                        target_spd = min(target_spd, 14.0)
                    initial_spd = target_spd
                    color = random.choice(NPC_COLORS)
                    if vehicle_type == "motorcycle":
                        length_m, width_m = 2.2, 0.8
                    elif vehicle_type == "moped":
                        length_m, width_m = 1.9, 0.7
                    else:
                        length_m = random.uniform(3.5, 5.0)
                        width_m = max(1.7, min(2.0, length_m * 0.45))
                    wheelbase_m, max_steering_angle = calculate_npc_turning_geometry(
                        length_m, vehicle_type
                    )

                    npc = NPCCar(
                        x=x,
                        y=y,
                        heading=heading,
                        speed=initial_spd,
                        way=chosen_way,
                        segment_idx=seg_idx,
                        direction=direction,
                        target_speed=target_spd,
                        color=color,
                        lane_offset=lane_offset,
                        target_lane_offset=lane_offset,
                        wheelbase_m=wheelbase_m,
                        max_steering_angle=max_steering_angle,
                        layer=layer,
                        length_m=length_m,
                        width_m=width_m,
                        speed_factor=speed_factor,
                        is_speeder=is_speeder,
                        is_taxi=random.random() < 0.12,
                        vehicle_type=vehicle_type,
                    )
                    if npc.is_taxi:
                        npc.vehicle_type = "car"
                    owner.vehicle_ids.add(id(npc))
                    owner.active_vehicle_id = id(npc)
                    npc.owner_id = owner.resident_id
                    npc.current_driver_id = owner.resident_id
                    npc.lod_time_accumulator = 1.0
                    self.npcs.append(npc)
                    return npc

        return None

    def update(
        self,
        player_car: Car,
        dt: float,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
        pedestrians: Optional[List] = None,
        cyclists: Optional[List] = None,
        police_cars: Optional[List] = None,
    ) -> None:
        """Update all NPC cars, manage spawning/despawning around player."""
        self.sim_time += dt
        self._signal_update_elapsed += dt
        route_plans_this_update = 0
        if self._signal_update_elapsed >= 0.1:
            self.traffic_light_manager.update(self.sim_time)
            self.intersection_manager.update(self.npcs)
            self._signal_update_elapsed = 0.0
        for npc in self.npcs:
            if npc.owner_id is None:
                owner = self.residents.create("driving", vehicle_id=id(npc), age=17)
                npc.owner_id = owner.resident_id
                if npc.state == "driving" and npc.assigned_driver_id is not None and npc.has_driver():
                    npc.current_driver_id = owner.resident_id
        previous_speeds = {id(npc): npc.speed for npc in self.npcs}
        npc_population_changed = tuple(id(npc) for npc in self.npcs) != self._npc_grid_npc_ids

        # Despawn distant NPCs
        surviving = []
        for npc in self.npcs:
            if npc.is_police:
                surviving.append(npc)
                continue
            if (
                npc.parking_departure_pending
                or npc.state in {"parked", "reserved", "parking", "parking_departure"}
            ) and (
                npc.reserved_by_pedestrian_id is not None
                or npc.current_driver_id is not None
                or npc.parking_departure_pending
                or npc.state == "parking"
            ):
                surviving.append(npc)
                continue
            d = math.hypot(npc.x - player_car.x, npc.y - player_car.y)
            if d > self.despawn_radius_m:
                logger.debug("NPC %s despawned: distance=%.1fm exceeds %.1fm", id(npc), d, self.despawn_radius_m)
                self.release_parking_space(npc)
                npc_population_changed = True
                continue
            if viewport_bounds:
                vminx, vminy, vmaxx, vmaxy = viewport_bounds
                in_view = vminx <= npc.x <= vmaxx and vminy <= npc.y <= vmaxy
                behind = (
                    (npc.x - player_car.x) * math.cos(player_car.heading)
                    + (npc.y - player_car.y) * math.sin(player_car.heading)
                ) < 0.0
                if not in_view and behind:
                    logger.debug("NPC %s despawned: behind player and outside viewport", id(npc))
                    npc_population_changed = True
                    continue
            surviving.append(npc)
        self.npcs = surviving

        # Spawn new NPCs up to target_count (preferring just outside viewport)
        attempts = 0
        spawned_this_update = 0
        spawn_limit = MAX_NPC_SPAWNS_PER_UPDATE if viewport_bounds else self.target_count
        max_attempts = max(200, self.target_count * 20)
        regular_target = max(0, self.target_count - sum(1 for npc in self.npcs if npc.is_taxi))
        parked_target = round(regular_target * self.parking_density)
        parked_count = sum(1 for candidate in self.npcs if candidate.state == "parked" and not candidate.is_taxi)
        while (
            len(self.npcs) < self.target_count
            and attempts < max_attempts
            and spawned_this_update < spawn_limit
        ):
            attempts += 1
            if parked_count < parked_target:
                npc = self.spawn_parking_npc(player_car.x, player_car.y, viewport_bounds) if viewport_bounds else None
                if npc is None:
                    npc = self.spawn_parked_npc(
                        player_car.x,
                        player_car.y,
                        near_heading=player_car.heading,
                        viewport_bounds=viewport_bounds,
                    )
            else:
                npc = self.spawn_npc(
                    player_car.x,
                    player_car.y,
                    viewport_bounds=viewport_bounds,
                    near_heading=player_car.heading,
                )
            if npc is None and parked_count < parked_target:
                npc = self.spawn_npc(
                    player_car.x,
                    player_car.y,
                    viewport_bounds=viewport_bounds,
                    near_heading=player_car.heading,
                )
            if not npc:
                break
            spawned_this_update += 1
            if npc.state == "parked" and not npc.is_taxi:
                parked_count += 1
            npc_population_changed = True
            logger.debug(
                "NPC %s spawned: position=(%.1f, %.1f), way=%s, direction=%s",
                id(npc), npc.x, npc.y, getattr(npc.way, "osm_id", None), npc.direction,
            )

        if viewport_bounds:
            vminx, vminy, vmaxx, vmaxy = viewport_bounds
            for npc in self.npcs:
                in_view = vminx <= npc.x <= vmaxx and vminy <= npc.y <= vmaxy
                if npc.debug_in_view != in_view:
                    logger.debug(
                        "NPC %s viewport: %s at (%.1f, %.1f)",
                        id(npc), "entered" if in_view else "left", npc.x, npc.y,
                    )
                    npc.debug_in_view = in_view

        if npc_population_changed:
            self._build_npc_spatial_grid()
        self.update_lod(player_car, dt)

        # Periodic log of active NPC traffic count (total and in-view)
        self._log_timer += dt
        if self._log_timer >= 5.0:
            self._log_timer = 0.0
            pedestrians = pedestrians or []
            cyclists = cyclists or []
            police_cars = police_cars or []
            taxi_npcs = [npc for npc in self.npcs if npc.is_taxi]
            taxi_details = ",".join(
                f"{id(npc)}@({npc.x:.0f},{npc.y:.0f}):{'stand' if npc.waiting_at_taxi_stop else 'driving'}"
                for npc in taxi_npcs
            ) or "none"
            if viewport_bounds:
                vminx, vminy, vmaxx, vmaxy = viewport_bounds
                in_view_count = sum(
                    1 for npc in self.npcs
                    if vminx <= npc.x <= vmaxx and vminy <= npc.y <= vmaxy
                )
                def is_entity_in_view(entity) -> bool:
                    return vminx <= entity.x <= vmaxx and vminy <= entity.y <= vmaxy

                logger.info(
                    "NPC active: cars=%d (%d view), taxis=%d [%s], police=%d (%d view), pedestrians=%d (%d view), cyclists=%d (%d view)",
                    len(self.npcs),
                    in_view_count,
                    len(taxi_npcs),
                    taxi_details,
                    len(police_cars),
                    sum(1 for car in police_cars if is_entity_in_view(car)),
                    len(pedestrians),
                    sum(1 for ped in pedestrians if is_entity_in_view(ped)),
                    len(cyclists),
                    sum(1 for cyclist in cyclists if is_entity_in_view(cyclist)),
                )
            else:
                logger.info(
                    "NPC active: cars=%d, taxis=%d [%s], police=%d, pedestrians=%d, cyclists=%d",
                    len(self.npcs), len(taxi_npcs), taxi_details,
                    len(police_cars), len(pedestrians), len(cyclists),
                )

        # Check vehicle-ahead distances and manage overtaking / slowing down behind player or other NPCs
        p_len = getattr(player_car, "length_m", 4.0)
        p_wid = getattr(player_car, "width_m", 1.8)

        for i, npc in enumerate(self.npcs):
            if npc.is_police:
                continue
            npc.route_retry_timer = max(0.0, npc.route_retry_timer - dt)
            if (
                route_plans_this_update < MAX_ROUTE_PLANS_PER_UPDATE
                and npc.travel_route is None
                and npc.state not in {"parked", "reserved", "parking", "parking_departure"}
            ):
                if self._assign_new_travel_plan(npc):
                    route_plans_this_update += 1
            if not npc.lod_update_due:
                continue
            if not npc.has_driver() and npc.current_driver_id is None:
                npc.speed = 0.0
                npc.target_speed = 0.0
                npc.state = "waiting"
                continue
            if npc.state in {"parked", "reserved"}:
                npc.speed = 0.0
                npc.target_speed = 0.0
                continue
            if npc.state == "parking_departure":
                departure_dt = dt if npc.lod_level == 0 else NPC_LOD_UPDATE_INTERVALS[npc.lod_level]
                self._advance_parking_departure(npc, departure_dt)
                continue
            if npc.state == "parking":
                parking_dt = dt if npc.lod_level == 0 else NPC_LOD_UPDATE_INTERVALS[npc.lod_level]
                self._advance_parking_npc(npc, parking_dt)
                continue
            self._prepare_next_route(npc)
            if npc.next_route is not None and not npc.turn_signal:
                next_turn_signal = self._turn_signal_for_next_route(npc)
                if next_turn_signal:
                    npc.turn_signal = next_turn_signal
                    npc.turn_signal_elapsed = 0.0
            if npc.taxi_pickup_timer > 0.0:
                npc.taxi_pickup_timer = max(0.0, npc.taxi_pickup_timer - dt)
                npc.speed = 0.0
                npc.state = "waiting"
                continue
            if getattr(npc, "waiting_at_taxi_stop", False):
                npc.speed = 0.0
                npc.target_speed = 0.0
                npc.state = "waiting"
                continue
            if (
                npc.destination is not None
                and npc.destination_parking_space_id is None
                and math.hypot(npc.x - npc.destination[0], npc.y - npc.destination[1]) <= max(6.0, npc.length_m)
            ):
                if route_plans_this_update < MAX_ROUTE_PLANS_PER_UPDATE:
                    if self._assign_new_travel_plan(npc):
                        route_plans_this_update += 1
            if npc.taxi_stop_target is not None:
                target_x, target_y = npc.taxi_stop_target
                dx = target_x - npc.x
                dy = target_y - npc.y
                distance = math.hypot(dx, dy)
                if distance <= 3.0:
                    npc.x, npc.y = target_x, target_y
                    npc.taxi_stop_target = None
                    npc.waiting_at_taxi_stop = True
                    npc.speed = 0.0
                    npc.target_speed = 0.0
                    npc.state = "waiting"
                    continue
                npc.heading = math.atan2(dy, dx)
                npc.speed = min(8.0, distance / max(dt, 0.001))
                npc.x += dx / distance * npc.speed * dt
                npc.y += dy / distance * npc.speed * dt
                continue
            npc.escape_timer = max(0.0, npc.escape_timer - dt)
            npc.turn_recovery_timer = max(0.0, npc.turn_recovery_timer - dt)
            npc.rage_timer = max(0.0, npc.rage_timer - dt)
            if npc.turn_signal:
                npc.turn_signal_elapsed += dt
            if getattr(npc.way, "oneway", 0) == 0 and npc.rage_timer <= 0.0:
                npc.overtaking = False
                npc.overtake_timer = 0.0
                if npc.turn_signal and npc.next_route is not None:
                    npc.target_lane_offset = compute_turn_lane_offset(npc.way, npc.turn_signal)
                else:
                    npc.target_lane_offset = compute_desired_lane_offset(
                        npc.way, is_overtaking=False, travel_direction=npc.direction
                    )
                npc.lane_offset = npc.target_lane_offset
            if npc.overtaking:
                npc.overtake_timer -= dt
                if npc.overtake_timer <= 0:
                    npc.overtaking = False
                    npc.target_lane_offset = compute_desired_lane_offset(
                        npc.way, is_overtaking=False, travel_direction=npc.direction
                    )
            else:
                # Check if there is a slower car or player car ahead in same lane
                car_ahead = False
                # Check against other NPCs
                for other in self._nearby_npcs(npc):
                    if other is npc or other.layer != npc.layer:
                        continue
                    dx = other.x - npc.x
                    dy = other.y - npc.y
                    dist = math.hypot(dx, dy)
                    if 3.0 < dist < 25.0:
                        angle_to_other = math.atan2(dy, dx)
                        angle_diff = (angle_to_other - npc.heading + math.pi) % (2 * math.pi) - math.pi
                        if abs(angle_diff) < 0.6:  # Ahead within ~35 degrees
                            if npc.speed > other.speed:
                                car_ahead = True
                                break

                # Also check player car ahead
                if not car_ahead and player_car.layer == npc.layer:
                    p_dx = player_car.x - npc.x
                    p_dy = player_car.y - npc.y
                    p_dist = math.hypot(p_dx, p_dy)
                    if 3.0 < p_dist < 25.0:
                        angle_to_p = math.atan2(p_dy, p_dx)
                        angle_diff = (angle_to_p - npc.heading + math.pi) % (2 * math.pi) - math.pi
                        if abs(angle_diff) < 0.6:
                            if npc.speed > player_car.speed:
                                car_ahead = True

                if car_ahead:
                    # Initiate overtaking maneuver
                    if getattr(npc.way, "oneway", 0) != 0:
                        npc.overtaking = True
                        npc.overtake_timer = random.uniform(3.0, 6.0)
                        npc.target_lane_offset = compute_desired_lane_offset(
                            npc.way, is_overtaking=True, travel_direction=npc.direction
                        )

            # Smoothly interpolate lane_offset towards target_lane_offset
            offset_diff = npc.target_lane_offset - npc.lane_offset
            if abs(offset_diff) > 0.01:
                shift_speed = 3.0  # meters per second lateral shift
                npc.lane_offset += math.copysign(min(abs(offset_diff), shift_speed * dt), offset_diff)

        # Vehicle-vehicle collision avoidance and emergency braking between NPCs and obstacles
        for i, npc in enumerate(self.npcs):
            if npc.is_police:
                continue
            if npc.state == "parking":
                continue
            if npc.state == "parking_departure":
                continue
            if not npc.has_driver() and npc.current_driver_id is None:
                continue
            if npc.lod_level > 0 or not npc.lod_update_due:
                continue
            if npc.state == "crashed" or npc.crashed_timer > 0.0:
                continue

            blocked_by_npc = False
            npc.debug_waiting_for = ""

            # Check for leading NPC in close proximity (same direction or blocking path)
            for other in self._nearby_npcs(npc):
                if other is npc or other.layer != npc.layer:
                    continue

                dx = other.x - npc.x
                dy = other.y - npc.y
                dist = math.hypot(dx, dy)

                min_gap = (npc.length_m + other.length_m) * 0.5 + 2.0  # ~5-6 meters minimum distance
                if dist < 28.0:
                    angle_to_other = math.atan2(dy, dx)
                    angle_diff = abs((angle_to_other - npc.heading + math.pi) % (2 * math.pi) - math.pi)

                    # Other car is in the cone ahead (within 45 degrees)
                    if angle_diff < math.radians(45):
                        # Lateral offset relative to npc heading
                        lat_offset = abs(-math.sin(npc.heading) * dx + math.cos(npc.heading) * dy)
                        # Check if cars share the same corridor/lane laterally
                        if lat_offset < (npc.width_m + other.width_m) * 0.75:
                            if dist < min_gap:
                                # Emergency hard braking / yield
                                if npc.escape_timer <= 0.0:
                                    npc.speed = 0.0
                                blocked_by_npc = True
                                npc.debug_waiting_for = f"NPC {id(other) % 1000}"
                            elif dist < min_gap + 10.0 and npc.speed > other.speed:
                                # Match or follow leader speed smoothly
                                target_follow_speed = max(0.0, other.speed * 0.9)
                                if npc.escape_timer <= 0.0:
                                    npc.speed = max(target_follow_speed, npc.speed - 16.0 * dt)
                                blocked_by_npc = True
                                npc.debug_waiting_for = f"NPC {id(other) % 1000}"

            # Also check player car collision avoidance
            if player_car.layer == npc.layer:
                p_dx = player_car.x - npc.x
                p_dy = player_car.y - npc.y
                p_dist = math.hypot(p_dx, p_dy)
                min_p_gap = (npc.length_m + p_len) * 0.5 + 2.0

                if p_dist < 28.0:
                    angle_to_p = math.atan2(p_dy, p_dx)
                    angle_diff = abs((angle_to_p - npc.heading + math.pi) % (2 * math.pi) - math.pi)
                    if angle_diff < math.radians(45):
                        lat_p_offset = abs(-math.sin(npc.heading) * p_dx + math.cos(npc.heading) * p_dy)
                        if lat_p_offset < (npc.width_m + p_wid) * 0.75:
                            if p_dist < min_p_gap:
                                npc.speed = max(0.0, npc.speed - 22.0 * dt)
                                npc.debug_waiting_for = "player"
                            elif p_dist < min_p_gap + 10.0 and npc.speed > max(0.0, player_car.speed):
                                target_p_speed = max(0.0, player_car.speed * 0.9)
                                npc.speed = max(target_p_speed, npc.speed - 16.0 * dt)
                                npc.debug_waiting_for = "player"

            if blocked_by_npc and npc.speed < 1.0:
                npc.blocked_timer += dt
            else:
                npc.blocked_timer = max(0.0, npc.blocked_timer - dt * 0.5)

            if npc.blocked_timer >= 2.0 and npc.escape_timer <= 0.0:
                npc.escape_timer = 2.0
                npc.blocked_timer = 0.0
                npc.overtaking = True
                npc.overtake_timer = npc.escape_timer
                npc.target_lane_offset = compute_desired_lane_offset(
                    npc.way,
                    is_overtaking=getattr(npc.way, "oneway", 0) != 0,
                    travel_direction=npc.direction,
                )
                npc.speed = max(npc.speed, min(npc.target_speed, 4.0))

        # Check red traffic lights ahead and adjust speed
        for npc in self.npcs:
            if npc.is_police:
                continue
            if npc.state == "turning":
                npc.junction_wait_timer = 0.0
                if npc.debug_waiting_for == "junction":
                    npc.debug_waiting_for = ""
            if not npc.has_driver() and npc.current_driver_id is None:
                npc.speed = 0.0
                npc.target_speed = 0.0
                npc.state = "waiting"
                continue
            if npc.state in {"parked", "reserved", "parking", "parking_departure"}:
                continue
            if not npc.lod_update_due:
                continue
            must_stop = False
            junction_blocked = False
            nearest_light = None
            stop_distance = None
            nearest_stop_sign = None
            nearest_yield_sign = None
            yield_slowdown = False
            passed_matching_light = False
            passed_light_state = None
            passed_light_distance = None
            departure_signal_state = None
            logical_approach = self.traffic_light_manager.find_approach(npc)
            if logical_approach is not None:
                logical_stop_center = (
                    (logical_approach.stop_line[0][0] + logical_approach.stop_line[1][0]) * 0.5,
                    (logical_approach.stop_line[0][1] + logical_approach.stop_line[1][1]) * 0.5,
                )
                logical_dx = logical_stop_center[0] - npc.x
                logical_dy = logical_stop_center[1] - npc.y
                logical_distance = logical_dx * math.cos(npc.heading) + logical_dy * math.sin(npc.heading)
                logical_state = self.traffic_light_manager.get_signal_state(logical_approach, self.sim_time)
                departure_signal_state = logical_state
                if logical_state == "green" and 0.0 < logical_distance < 16.0 and npc.lod_level == 0:
                    if not self.intersection_manager.request_enter(npc, logical_approach):
                        junction_blocked = True
                braking_distance = npc.speed * npc.speed / (2.0 * 15.0)
                yellow_requires_stop = logical_state != "yellow" or logical_distance >= braking_distance
                if 0.0 < logical_distance < 35.0 and logical_state in ("red", "all-red", "yellow", "red+yellow") and yellow_requires_stop:
                    stop_distance = logical_distance - 1.5
                    must_stop = stop_distance >= -1.0
            roadwork_stop_distance = self._roadwork_stop_distance(npc)
            if roadwork_stop_distance is not None:
                must_stop = True
                stop_distance = roadwork_stop_distance
            heading_x = math.cos(npc.heading)
            heading_y = math.sin(npc.heading)
            for stop_sign in self.stop_signs:
                if getattr(stop_sign, "layer", 0) != npc.layer:
                    continue
                sign_dx = stop_sign.x - npc.x
                sign_dy = stop_sign.y - npc.y
                sign_longitudinal = sign_dx * heading_x + sign_dy * heading_y
                sign_lateral = abs(sign_dx * -heading_y + sign_dy * heading_x)
                if 0.0 < sign_longitudinal < 30.0 and sign_lateral <= 5.0:
                    if nearest_stop_sign is None or sign_longitudinal < nearest_stop_sign[0]:
                        nearest_stop_sign = (sign_longitudinal, stop_sign)
            if nearest_stop_sign is not None:
                stop_sign_distance, stop_sign = nearest_stop_sign
                stop_distance = stop_sign_distance - 2.0
                if npc.stop_sign_id != stop_sign.id:
                    npc.stop_sign_id = stop_sign.id
                    npc.stop_sign_wait_timer = 0.0
                if npc.speed < 0.2 and stop_distance <= 0.5:
                    npc.stop_sign_wait_timer += dt
                must_stop = npc.stop_sign_wait_timer < 1.0 or stop_distance >= -1.0
            elif npc.stop_sign_id is not None:
                npc.stop_sign_id = None
                npc.stop_sign_wait_timer = 0.0
            for yield_sign in self.yield_signs:
                if getattr(yield_sign, "layer", 0) != npc.layer:
                    continue
                sign_dx = yield_sign.x - npc.x
                sign_dy = yield_sign.y - npc.y
                sign_longitudinal = sign_dx * heading_x + sign_dy * heading_y
                sign_lateral = abs(sign_dx * -heading_y + sign_dy * heading_x)
                if 0.0 < sign_longitudinal < 30.0 and sign_lateral <= 5.0:
                    if nearest_yield_sign is None or sign_longitudinal < nearest_yield_sign[0]:
                        nearest_yield_sign = (sign_longitudinal, yield_sign)
            for tl in self._nearby_traffic_lights(npc.x, npc.y) if logical_approach is None else []:
                if tl.layer != npc.layer:
                    continue
                dx = tl.x - npc.x
                dy = tl.y - npc.y
                dist = math.hypot(dx, dy)
                # Traffic light ahead within 25m. Use longitudinal/lateral
                # distance so lane offset does not hide a nearby signal.
                longitudinal = dx * heading_x + dy * heading_y
                lateral = abs(dx * -heading_y + dy * heading_x)
                if lateral > 8.0:
                    continue
                # If traffic light has orientation, check alignment with NPC heading.
                if tl.direction_angle is not None:
                    tl_ang = tl.direction_angle
                    npc_ang = npc.heading % math.pi
                    ang_err = abs(tl_ang - npc_ang)
                    ang_err = min(ang_err, math.pi - ang_err)
                    if ang_err > math.radians(45):
                        continue  # Signal is for cross traffic, skip
                if -25.0 < longitudinal <= 0.0:
                    passed_matching_light = True
                    passed_light_state = tl.get_state(self.sim_time)
                    passed_light_distance = longitudinal
                elif -2.0 < longitudinal < 25.0:
                    if nearest_light is None or longitudinal < nearest_light[0]:
                        nearest_light = (longitudinal, tl)

            if nearest_light is not None and not passed_matching_light:
                state = nearest_light[1].get_state(self.sim_time)
                departure_signal_state = state
                braking_distance = npc.speed * npc.speed / (2.0 * 15.0)
                yellow_requires_stop = state != "yellow" or longitudinal >= braking_distance
                if state in ("red", "all-red", "red+yellow", "yellow") and yellow_requires_stop:
                    stop_distance = nearest_light[0] - 1.5
                    nearest_crossing = None
                    for crossing in self._nearby_crossings(npc.x, npc.y):
                        if getattr(crossing, "layer", 0) != npc.layer:
                            continue
                        crossing_dx = crossing.x - npc.x
                        crossing_dy = crossing.y - npc.y
                        crossing_longitudinal = crossing_dx * heading_x + crossing_dy * heading_y
                        crossing_lateral = abs(crossing_dx * -heading_y + crossing_dy * heading_x)
                        if 0.0 < crossing_longitudinal < nearest_light[0] and crossing_lateral <= 8.0:
                            if nearest_crossing is None or crossing_longitudinal > nearest_crossing:
                                nearest_crossing = crossing_longitudinal
                    if nearest_crossing is not None:
                        stop_distance = nearest_crossing - 2.0
                    must_stop = stop_distance >= -1.0
            if (
                passed_matching_light
                and npc.speed < 0.5
                and passed_light_distance is not None
                and passed_light_distance > -10.0
                and passed_light_state in ("red", "all-red", "red+yellow", "yellow")
            ):
                must_stop = True
                stop_distance = 0.0

            pts = npc.way.points_m
            target_pt = None
            if len(pts) >= 2:
                if npc.direction == 1 and npc.segment_idx + 1 < len(pts):
                    target_pt = pts[npc.segment_idx + 1]
                elif npc.direction == -1 and npc.segment_idx < len(pts):
                    target_pt = pts[npc.segment_idx]
            if target_pt is not None:
                junction_point = self._junction_at_point(target_pt, npc.layer)
                if junction_point is not None:
                    distance_to_junction = math.hypot(npc.x - junction_point[0], npc.y - junction_point[1])
                    junction_blocked = (
                        7.0 < distance_to_junction < 20.0
                        and self._junction_is_occupied(junction_point, npc)
                    )
                    uncontrolled_approach = logical_approach is None and nearest_stop_sign is None
                    if (
                        distance_to_junction < 20.0
                        and (nearest_yield_sign is not None or uncontrolled_approach)
                        and not self._junction_is_clear_for(npc, junction_point)
                    ):
                        junction_blocked = True
                    if (
                        npc.next_route is not None
                        and getattr(npc.next_route[0], "is_roundabout", False)
                        and not getattr(npc.way, "is_roundabout", False)
                        and distance_to_junction < 24.0
                        and self._roundabout_entry_blocked(npc, npc.next_route[0], junction_point)
                    ):
                        junction_blocked = True
                        stop_distance = max(0.0, distance_to_junction - 2.5)
                    if nearest_yield_sign is not None:
                        yield_distance = nearest_yield_sign[0]
                        if not self._junction_is_clear_for(npc, junction_point):
                            stop_distance = yield_distance - 2.5
                            must_stop = stop_distance >= -1.0
                        else:
                            yield_slowdown = 0.6

                    if junction_blocked:
                        npc.junction_wait_timer += dt
                        if (
                            npc.junction_wait_timer >= 5.0
                            and self._junction_deadlock_can_proceed(npc, junction_point)
                        ):
                            junction_blocked = False
                            npc.debug_waiting_for = ""
                    else:
                        npc.junction_wait_timer = 0.0
                        if npc.debug_waiting_for == "junction":
                            npc.debug_waiting_for = ""

            # Continue through the junction if the NPC has already entered it.
            if self._junction_near_point((npc.x, npc.y), npc.layer):
                must_stop = False
                if npc.speed < 0.5 and departure_signal_state in (
                    "red", "all-red", "red+yellow", "yellow"
                ):
                    must_stop = True
                    stop_distance = 0.0

            # Calculate cornering speed limit based on heading angle to next vertex / sharp curves
            turn_limit_speed = npc.target_speed
            if npc.turn_recovery_timer > 0.0:
                turn_limit_speed = min(turn_limit_speed, 5.0)
            if yield_slowdown:
                turn_limit_speed = min(turn_limit_speed, max(3.0, npc.target_speed * yield_slowdown))
            if target_pt is not None:
                next_heading = None
                if npc.next_route is not None:
                    next_way, next_segment_idx, next_direction = npc.next_route
                    next_pts = next_way.points_m
                    if next_direction == 1:
                        next_start, next_end = next_pts[next_segment_idx], next_pts[next_segment_idx + 1]
                    else:
                        next_start, next_end = next_pts[next_segment_idx + 1], next_pts[next_segment_idx]
                    next_heading = math.atan2(next_end[1] - next_start[1], next_end[0] - next_start[0])
                if next_heading is not None:
                    angle_err = abs((next_heading - npc.heading + math.pi) % (2 * math.pi) - math.pi)
                    if angle_err > math.radians(25):
                        turn_factor = max(0.25, math.cos(min(math.pi / 2, angle_err)))
                        turn_limit_speed = max(3.5, npc.target_speed * turn_factor)

            # Keep crashed NPCs disabled.
            if npc.state == "crashed" or npc.crashed_timer > 0.0 or getattr(npc, "fallen", False):
                action = "fallen" if getattr(npc, "fallen", False) else "crashed"
                npc.state = "crashed"
                if npc.debug_last_action != action:
                    logger.debug("NPC %s action=%s reason=disabled state", id(npc), action)
                    npc.debug_last_action = action
                npc.crashed_timer = max(0.0, npc.crashed_timer - dt)
                npc.speed = 0.0
                continue

            if must_stop:
                action = "stopping"
                if nearest_stop_sign is not None:
                    reason = f"stop sign {getattr(nearest_stop_sign, 'id', '?')}"
                elif nearest_yield_sign is not None:
                    reason = f"yield sign {getattr(nearest_yield_sign[1], 'id', '?')}"
                elif nearest_light is not None:
                    reason = f"traffic light {getattr(nearest_light, 'id', '?')}"
                else:
                    reason = "roadworks"
            elif junction_blocked:
                action = "stopping"
                reason = "junction occupied"
                npc.debug_waiting_for = "junction"
            elif npc.overtaking:
                action = "overtaking"
                reason = "blocked vehicle"
            else:
                action = "driving"
                reason = "prepared turn" if npc.turn_signal else "normal route"
            if must_stop or junction_blocked:
                npc.state = "waiting" if npc.speed < 1.0 else "braking"
            elif npc.overtaking or npc.turn_signal:
                npc.state = "turning"
            else:
                npc.state = "driving"
            action_state = f"{action}: {reason}"
            if npc.debug_last_action != action_state:
                logger.debug(
                    "NPC %s action=%s speed=%.1fm/s position=(%.1f, %.1f)",
                    id(npc), action_state, npc.speed, npc.x, npc.y,
                )
                npc.debug_last_action = action_state

            if must_stop or junction_blocked:
                # Decelerate to stop at red light
                if must_stop and stop_distance is not None:
                    target_stop_speed = math.sqrt(2.0 * 15.0 * max(0.0, stop_distance))
                    if npc.speed > target_stop_speed:
                        npc.speed = max(target_stop_speed, npc.speed - 15.0 * dt)
                    else:
                        npc.speed = min(target_stop_speed, npc.speed + 8.0 * dt)
                    if stop_distance >= 0.0:
                        npc.speed = min(npc.speed, stop_distance / max(dt, 1e-6))
                    if npc.speed < 0.05:
                        npc.speed = 0.0
                else:
                    npc.speed = max(0.0, npc.speed - 15.0 * dt)
            else:
                desired_speed = min(npc.target_speed, turn_limit_speed)
                if npc.speed < desired_speed and not npc.overtaking:
                    # Accelerate towards desired speed if not blocked
                    npc.speed = min(desired_speed, npc.speed + 8.0 * dt)
                elif npc.speed > desired_speed:
                    # Brake for steep turn
                    npc.speed = max(desired_speed, npc.speed - 14.0 * dt)

        # Move each NPC along its way segments
        finished_npcs = set()
        previous_positions = {id(npc): (npc.x, npc.y) for npc in self.npcs}
        for npc in self.npcs:
            if id(npc) in finished_npcs or npc.state in {"parked", "reserved", "parking", "parking_departure"}:
                continue
            if not npc.lod_update_due:
                continue
            if math.hypot(npc.x - player_car.x, npc.y - player_car.y) > NPC_STATIC_COLLISION_RADIUS_M:
                continue
            self._npc_hits_static_obstacle(npc, previous_positions.get(id(npc), (npc.x, npc.y)))

        for npc in self.npcs:
            if npc.is_police:
                continue
            if npc.state in {"parking", "parking_departure"}:
                continue
            if not npc.lod_update_due:
                continue
            if npc.speed <= 0.0:
                continue
            pts = npc.way.points_m
            if len(pts) < 2:
                continue

            movement_dt = dt if npc.lod_level == 0 else NPC_LOD_UPDATE_INTERVALS[npc.lod_level]
            dist_step = npc.speed * movement_dt
            if npc.turn_trajectory is not None:
                self._advance_turn_trajectory(npc, dist_step, movement_dt)
                continue
            step_limit = 10  # Prevent infinite loop on degenerate/zero-length segments

            while dist_step > 0 and step_limit > 0:
                step_limit -= 1
                if npc.direction == 1:
                    target_pt = pts[npc.segment_idx + 1]
                    seg_start = pts[npc.segment_idx]
                else:
                    target_pt = pts[npc.segment_idx]
                    seg_start = pts[npc.segment_idx + 1]

                # Centerline vector and normal
                seg_dx = target_pt[0] - seg_start[0]
                seg_dy = target_pt[1] - seg_start[1]
                seg_len = math.hypot(seg_dx, seg_dy)

                if seg_len > 1e-3:
                    seg_dir_x = seg_dx / seg_len
                    seg_dir_y = seg_dy / seg_len
                    # Right perpendicular normal in Cartesian space (forward=(dx,dy) -> right=(dy,-dx))
                    norm_x = seg_dir_y
                    norm_y = -seg_dir_x
                else:
                    seg_dir_x, seg_dir_y = 1.0, 0.0
                    norm_x, norm_y = 0.0, -1.0

                # Target point adjusted with lateral lane offset
                shifted_target_x = target_pt[0] + norm_x * npc.lane_offset
                shifted_target_y = target_pt[1] + norm_y * npc.lane_offset

                to_tgt_x = shifted_target_x - npc.x
                to_tgt_y = shifted_target_y - npc.y
                dist_to_tgt = math.hypot(to_tgt_x, to_tgt_y)

                # Use a bounded bicycle model instead of steering directly at
                # the next vertex.  The next-segment blend gives turns a
                # finite radius and keeps the body heading continuous.
                path_heading = math.atan2(seg_dir_y, seg_dir_x)
                current_lateral = (
                    (npc.x - seg_start[0]) * norm_x
                    + (npc.y - seg_start[1]) * norm_y
                )
                lateral_error = npc.lane_offset - current_lateral
                lookahead = max(5.0, min(12.0, npc.speed * 0.6 + 4.0))
                path_heading -= math.atan2(1.5 * lateral_error, lookahead)
                segment_progress = (
                    (npc.x - seg_start[0]) * seg_dir_x
                    + (npc.y - seg_start[1]) * seg_dir_y
                )
                target_behind_vehicle = (
                    (target_pt[0] - npc.x) * math.cos(npc.heading)
                    + (target_pt[1] - npc.y) * math.sin(npc.heading)
                ) <= 0.0
                node_was_passed = segment_progress >= seg_len and target_behind_vehicle
                if dist_to_tgt < max(14.0, npc.speed * 1.5) and npc.next_route is not None:
                    next_way, next_segment_idx, next_direction = npc.next_route
                    next_points = next_way.points_m
                    if 0 <= next_segment_idx < len(next_points) - 1:
                        if next_direction == 1:
                            next_start, next_end = next_points[next_segment_idx], next_points[next_segment_idx + 1]
                        else:
                            next_start, next_end = next_points[next_segment_idx + 1], next_points[next_segment_idx]
                        next_dx = next_end[0] - next_start[0]
                        next_dy = next_end[1] - next_start[1]
                        next_length = math.hypot(next_dx, next_dy)
                        if next_length > 1e-3:
                            next_norm_x = next_dy / next_length
                            next_norm_y = -next_dx / next_length
                            next_lane_offset = compute_desired_lane_offset(
                                next_way,
                                is_overtaking=False,
                                travel_direction=next_direction,
                            )
                            next_start = (
                                next_start[0] + next_norm_x * next_lane_offset,
                                next_start[1] + next_norm_y * next_lane_offset,
                            )
                            next_end = (
                                next_end[0] + next_norm_x * next_lane_offset,
                                next_end[1] + next_norm_y * next_lane_offset,
                            )
                        next_heading = math.atan2(next_end[1] - next_start[1], next_end[0] - next_start[0])
                        blend = max(0.0, min(1.0, 1.0 - dist_to_tgt / max(14.0, npc.speed * 1.5)))
                        heading_delta = (next_heading - path_heading + math.pi) % (2.0 * math.pi) - math.pi
                        path_heading += heading_delta * blend
                heading_error = (path_heading - npc.heading + math.pi) % (2.0 * math.pi) - math.pi
                # Never let a route transition demand an instantaneous
                # right-angle body rotation; the bicycle model must settle
                # toward the road direction over multiple updates.
                heading_error = max(-math.radians(60.0), min(math.radians(60.0), heading_error))
                desired_steering = math.atan2(
                    npc.wheelbase_m * math.sin(heading_error), lookahead
                )
                desired_steering = max(
                    -npc.max_steering_angle,
                    min(npc.max_steering_angle, desired_steering),
                )
                steering_rate = math.radians(85.0)
                steering_delta = desired_steering - npc.steering_angle
                max_steering_delta = steering_rate * movement_dt
                npc.steering_angle += max(-max_steering_delta, min(max_steering_delta, steering_delta))
                if npc.speed > 1e-3:
                    yaw_rate = npc.speed / npc.wheelbase_m * math.tan(npc.steering_angle)
                    npc.heading += yaw_rate * movement_dt
                    npc.heading = (npc.heading + math.pi) % (2.0 * math.pi) - math.pi
                    if (
                        npc.turn_signal
                        and npc.next_route is None
                        and (
                            (npc.turn_signal_elapsed >= 0.45 and abs(heading_error) < 0.12)
                            or npc.turn_signal_elapsed >= 3.0
                        )
                    ):
                        npc.turn_signal = ""
                        npc.turn_recovery_timer = max(npc.turn_recovery_timer, 2.0)

                remaining_along_segment = 0.0 if node_was_passed else max(0.0, seg_len - segment_progress)
                if dist_step < remaining_along_segment:
                    npc.x += math.cos(npc.heading) * dist_step
                    npc.y += math.sin(npc.heading) * dist_step
                    dist_step = 0.0
                else:
                    npc.x += math.cos(npc.heading) * remaining_along_segment
                    npc.y += math.sin(npc.heading) * remaining_along_segment
                    dist_step -= remaining_along_segment

                    # Advance to next segment or next connected way
                    if npc.direction == 1:
                        # At intermediate vertices, check if there is an intersecting road to turn onto
                        turned = False
                        if npc.segment_idx + 1 < len(pts) - 1:
                            # Follow the persistent route; unplanned test or legacy NPCs stay on this way.
                            if npc.travel_route is not None:
                                turn_route = npc.next_route or self._find_next_way_and_segment(
                                    npc.way, target_pt, exclude_reverse=True, incoming_heading=npc.heading
                                )
                                if turn_route and turn_route[0] is not npc.way:
                                    self._advance_travel_route(npc, target_pt)
                                    old_heading = npc.heading
                                    self._transition_to_route(npc, turn_route, old_heading)
                                    pts = npc.way.points_m
                                    turned = True
                                    dist_step = 0.0
                                    break
                            if not turned:
                                npc.segment_idx += 1
                        else:
                            # Reached end of way, find connecting road
                            next_route = npc.next_route or self._find_next_way_and_segment(
                                npc.way, target_pt, incoming_heading=npc.heading
                            )
                            if next_route:
                                self._advance_travel_route(npc, target_pt)
                                old_heading = npc.heading
                                self._transition_to_route(npc, next_route, old_heading)
                                pts = npc.way.points_m
                                dist_step = 0.0
                                break
                            else:
                                # Reverse on two-way or loop (dead end)
                                if self._start_destination_parking(npc):
                                    dist_step = 0.0
                                    break
                                if getattr(npc.way, "oneway", 0) == 0:
                                    npc.direction = -1
                                    npc.segment_idx = len(pts) - 2
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(
                                        npc.way, npc.overtaking, npc.direction
                                    )
                                else:
                                    dist_step = 0.0
                                    finished_npcs.add(id(npc))
                                    break
                    else:
                        turned = False
                        if npc.segment_idx > 0:
                            if npc.travel_route is not None:
                                turn_route = npc.next_route or self._find_next_way_and_segment(
                                    npc.way, target_pt, exclude_reverse=True, incoming_heading=npc.heading
                                )
                                if turn_route and turn_route[0] is not npc.way:
                                    self._advance_travel_route(npc, target_pt)
                                    old_heading = npc.heading
                                    self._transition_to_route(npc, turn_route, old_heading)
                                    pts = npc.way.points_m
                                    turned = True
                                    dist_step = 0.0
                                    break
                            if not turned:
                                npc.segment_idx -= 1
                        else:
                            # Reached start of way in reverse
                            next_route = npc.next_route or self._find_next_way_and_segment(
                                npc.way, target_pt, incoming_heading=npc.heading
                            )
                            if next_route:
                                self._advance_travel_route(npc, target_pt)
                                old_heading = npc.heading
                                self._transition_to_route(npc, next_route, old_heading)
                                pts = npc.way.points_m
                                dist_step = 0.0
                                break
                            else:
                                if self._start_destination_parking(npc):
                                    dist_step = 0.0
                                    break
                                if getattr(npc.way, "oneway", 0) == 0:
                                    npc.direction = 1
                                    npc.segment_idx = 0
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(
                                        npc.way, npc.overtaking, npc.direction
                                    )
                                else:
                                    dist_step = 0.0
                                    finished_npcs.add(id(npc))
                                    break
            if (
                npc.state not in {"parking", "parking_departure"}
                and npc.speed > 0.0
                and npc.next_route is None
                and npc.turn_trajectory is None
            ):
                self._keep_npc_near_own_way(npc)

        for npc in self.npcs:
            if not npc.parking_departure_pending or npc.parking_space_id is None:
                continue
            parking_space = next(
                (
                    space
                    for space in self.parking_spaces
                    if self.parking_space_id(space) == npc.parking_space_id
                ),
                None,
            )
            if parking_space is None:
                npc.parking_departure_pending = False
                npc.parking_space_id = None
                continue
            center_x = (parking_space.bbox[0] + parking_space.bbox[2]) * 0.5
            center_y = (parking_space.bbox[1] + parking_space.bbox[3]) * 0.5
            space_radius = math.hypot(
                parking_space.bbox[2] - parking_space.bbox[0],
                parking_space.bbox[3] - parking_space.bbox[1],
            ) * 0.5 + npc.length_m * 0.5
            if math.hypot(npc.x - center_x, npc.y - center_y) > space_radius:
                self.release_parking_space(npc)

        if finished_npcs:
            self.npcs = [npc for npc in self.npcs if id(npc) not in finished_npcs]
        for npc in self.npcs:
            previous_speed = previous_speeds.get(id(npc))
            npc.braking = previous_speed is not None and npc.speed < previous_speed - 0.05
        self._resolve_npc_collisions()
        self._build_npc_spatial_grid()
