import logging
import heapq
import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .geo import boxes_intersect
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
MAX_TRAFFIC_COUNT = 200
NPC_TAXI_COLOR = (245, 205, 35)
NPC_LOD_NEAR_RADIUS_M = 500.0
NPC_LOD_MEDIUM_RADIUS_M = 1500.0
NPC_LOD_UPDATE_INTERVALS = (1.0 / 30.0, 1.0 / 12.0, 0.2)


def recommended_traffic_count(ways: List[Way], minimum: int = 5, maximum: int = MAX_TRAFFIC_COUNT) -> int:
    """Choose a traffic population from the number of connected drivable road ways."""
    road_count = len(connected_drivable_ways(ways))
    return max(minimum, min(maximum, round(road_count / 10)))


def traffic_count_for_zoom(base_count: int, px_per_m: float, minimum: int = 5) -> int:
    """Use fewer active NPCs when zoomed in, where less traffic is visible."""
    zoom_factor = min(1.0, 3.0 / max(0.1, px_per_m))
    return max(0, min(base_count, max(minimum, round(base_count * zoom_factor))))


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
    lod_level: int = 0
    lod_time_accumulator: float = 0.0
    lod_update_due: bool = True
    state: str = "driving"
    debug_last_action: str = ""
    debug_in_view: Optional[bool] = None
    reserved_intersection_id: Optional[str] = None
    parking_space_id: Optional[int] = None
    parking_departure_pending: bool = False
    parking_target_id: Optional[int] = None
    parking_route: Optional[List[Tuple[float, float]]] = None
    parking_route_index: int = 0
    stop_sign_id: Optional[int] = None
    stop_sign_wait_timer: float = 0.0
    reserved_by_pedestrian_id: Optional[int] = None
    current_driver_id: Optional[int] = None
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
        self.npcs: List[NPCCar] = []
        self._log_timer: float = 0.0
        self.sim_time: float = 0.0
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
        self._parking_grid_cell_size = 100.0
        self._parking_grid: dict[Tuple[int, int], List] = {}
        self._route_nodes: List[Tuple[float, float, int]] = []
        self._route_edges: dict[int, List[Tuple[int, float]]] = {}
        self.logical_intersections = build_logical_intersections(self.traffic_lights, self.ways)
        self.traffic_light_manager = TrafficLightManager(self.logical_intersections)
        self.intersection_manager = IntersectionManager(self.logical_intersections)
        self._build_route_graph()
        self._build_parking_grid()
        self._taxi_stop_spawns: set[Tuple[float, float, object]] = set()
        self._taxi_stop_targets: dict[Tuple[float, float, object], int] = {}
        self._build_spatial_indices()

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

    def _build_npc_spatial_grid(self) -> None:
        cell_size = self._npc_grid_cell_size
        self._npc_grid.clear()
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
        npc.state = "parked"
        npc.speed = 0.0
        npc.target_speed = 0.0
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
                clearance = math.hypot(
                    parking_space.bbox[2] - parking_space.bbox[0],
                    parking_space.bbox[3] - parking_space.bbox[1],
                ) * 0.5 + npc.length_m * 0.5 + 1.0
                exit_position = (
                    center_x + math.cos(parking_space.orientation) * clearance,
                    center_y + math.sin(parking_space.orientation) * clearance,
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
            if not space.occupied
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
        npc.heading = parking_space.orientation
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
            if not space.occupied
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
        route = self.plan_route((npc.x, npc.y), center, layer=getattr(npc.way, "layer", 0))
        if not route or len(route) < 2:
            self.npcs.remove(npc)
            return None
        parking_space.reserved = True
        parking_space.vehicle_id = id(npc)
        npc.parking_target_id = self.parking_space_id(parking_space)
        npc.parking_route = route
        npc.parking_route_index = 1
        npc.state = "parking"
        return npc

    def _start_destination_parking(self, npc: NPCCar) -> bool:
        """Reserve a nearby OSM space and route a vehicle there from a dead end."""
        available_spaces = [
            space for space in self.nearby_parking_spaces(npc.x, npc.y, 80.0)
            if not space.occupied and not space.reserved
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
        route = self.plan_route((npc.x, npc.y), center, layer=getattr(npc.way, "layer", 0))
        if not route or len(route) < 2:
            return False
        parking_space.reserved = True
        parking_space.vehicle_id = id(npc)
        npc.parking_target_id = self.parking_space_id(parking_space)
        npc.parking_route = route
        npc.parking_route_index = 1
        npc.state = "parking"
        npc.speed = 0.0
        return True

    def _advance_parking_npc(self, npc: NPCCar, dt: float) -> None:
        """Follow planned road points, then occupy the selected parking space."""
        route = npc.parking_route
        if not route or npc.parking_route_index >= len(route):
            return
        target_x, target_y = route[npc.parking_route_index]
        dx = target_x - npc.x
        dy = target_y - npc.y
        distance = math.hypot(dx, dy)
        speed = max(4.0, min(npc.target_speed, 12.0))
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
                    npc.heading = parking_space.orientation
                    self.occupy_parking_space(npc, parking_space)
                else:
                    npc.state = "driving"
            return
        npc.heading = math.atan2(dy, dx)
        npc.speed = speed
        npc.x += dx / distance * speed * dt
        npc.y += dy / distance * speed * dt

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
        cell_size = self._npc_grid_cell_size
        cell_x = int(math.floor(npc.x / cell_size))
        cell_y = int(math.floor(npc.y / cell_size))
        nearby: List[NPCCar] = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                nearby.extend(self._npc_grid.get((cell_x + offset_x, cell_y + offset_y), []))
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
        for npc in self.npcs:
            distance = math.hypot(npc.x - player_car.x, npc.y - player_car.y)
            if distance < NPC_LOD_NEAR_RADIUS_M:
                npc.lod_level = 0
            elif distance < NPC_LOD_MEDIUM_RADIUS_M:
                npc.lod_level = 1
            else:
                npc.lod_level = 2
            npc.lod_time_accumulator += dt
            npc.lod_update_due = self._lod_update_due(npc)

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
        resolved_pairs = set()
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
                if npc.state == "parking" or other.state == "parking":
                    if npc.state == "parking" and other.state == "parking":
                        npc.speed = 0.0
                        other.speed = 0.0
                    elif npc.state == "parking":
                        other.x -= nx * push * 2.0
                        other.y -= ny * push * 2.0
                        other.speed = 0.0
                    else:
                        npc.x += nx * push * 2.0
                        npc.y += ny * push * 2.0
                        npc.speed = 0.0
                    continue
                npc.x += nx * push
                npc.y += ny * push
                other.x -= nx * push
                other.y -= ny * push
                npc.speed = 0.0
                other.speed = 0.0

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

    def sync_map_data(
        self,
        ways: List[Way],
        traffic_lights: Optional[List[TrafficLight]] = None,
        stop_signs: Optional[List[StopSign]] = None,
        crossings: Optional[List] = None,
    ) -> None:
        """Update road references when dynamic tiles expand."""
        self.ways = connected_drivable_ways(ways)
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights
        if stop_signs is not None:
            self.stop_signs = stop_signs
        if crossings is not None:
            self.crossings = crossings
        self.logical_intersections = build_logical_intersections(self.traffic_lights, self.ways)
        self.traffic_light_manager = TrafficLightManager(self.logical_intersections)
        self.intersection_manager = IntersectionManager(self.logical_intersections)
        self._build_route_graph()
        self._build_spatial_indices()

    def plan_route(
        self,
        start: Tuple[float, float],
        target: Tuple[float, float],
        layer: Optional[int] = None,
    ) -> Optional[List[Tuple[float, float]]]:
        """Return a shortest route over road vertices between two map positions."""
        nodes = self._route_nodes
        edges = self._route_edges
        if layer is not None:
            allowed_nodes = {index for index, node in enumerate(nodes) if node[2] == layer}
            nodes_for_route = [node for node in nodes]
            edges_for_route = {
                index: [(neighbor, distance) for neighbor, distance in neighbors if neighbor in allowed_nodes]
                for index, neighbors in edges.items()
                if index in allowed_nodes
            }
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
        best_path = None
        best_score = math.inf
        for start_id in start_candidates:
            distances = {start_id: 0.0}
            previous: dict[int, int] = {}
            queue = [(0.0, start_id)]
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
            for target_id in target_candidates:
                if target_id not in distances:
                    continue
                start_connector = math.hypot(nodes_for_route[start_id][0] - start[0], nodes_for_route[start_id][1] - start[1])
                target_connector = math.hypot(nodes_for_route[target_id][0] - target[0], nodes_for_route[target_id][1] - target[1])
                score = distances[target_id] + start_connector + target_connector
                if score >= best_score:
                    continue
                path = [target_id]
                while path[-1] != start_id:
                    path.append(previous[path[-1]])
                path.reverse()
                best_path = path
                best_score = score
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
        if npc.next_route is not None or len(npc.way.points_m) < 2:
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
        npc.next_route = self._find_next_way_and_segment(
            npc.way,
            junction_point,
            incoming_heading=npc.heading,
        )

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
            if other is npc or other.layer != npc.layer:
                continue
            if math.hypot(other.x - junction_point[0], other.y - junction_point[1]) < 12.0:
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
            if other is npc or other.layer != npc.layer or not other.has_driver():
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

                    # Speed behavior distribution:
                    # ~15% are aggressive speeders (kaaharit, 1.25x - 1.55x limit)
                    # ~70% follow limits closely (0.92x - 1.05x limit)
                    # ~15% are cautious/slow drivers (0.78x - 0.90x limit)
                    r_prof = random.random()
                    if r_prof < 0.18:
                        is_speeder = True
                        speed_factor = random.uniform(1.25, 1.55)
                    elif r_prof < 0.85:
                        is_speeder = False
                        speed_factor = random.uniform(0.92, 1.05)
                    else:
                        is_speeder = False
                        speed_factor = random.uniform(0.78, 0.90)

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
                    initial_spd = target_spd * random.uniform(0.85, 1.0)
                    color = random.choice(NPC_COLORS)
                    if vehicle_type == "motorcycle":
                        length_m, width_m = 2.2, 0.8
                    elif vehicle_type == "moped":
                        length_m, width_m = 1.9, 0.7
                    else:
                        length_m = random.uniform(3.5, 5.0)
                        width_m = max(1.7, min(2.0, length_m * 0.45))

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
        self.traffic_light_manager.update(self.sim_time)
        self.intersection_manager.update(self.npcs)
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
        max_attempts = max(200, self.target_count * 20)
        regular_target = max(0, self.target_count - sum(1 for npc in self.npcs if npc.is_taxi))
        parked_target = round(regular_target * self.parking_density)
        while len(self.npcs) < self.target_count and attempts < max_attempts:
            attempts += 1
            parked_count = sum(1 for candidate in self.npcs if candidate.state == "parked" and not candidate.is_taxi)
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
            npc.rage_timer = max(0.0, npc.rage_timer - dt)
            if npc.turn_signal:
                npc.turn_signal_elapsed += dt
            if getattr(npc.way, "oneway", 0) == 0 and npc.rage_timer <= 0.0:
                npc.overtaking = False
                npc.overtake_timer = 0.0
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
            if npc.state == "parking_departure":
                continue
            if not npc.has_driver() and npc.current_driver_id is None:
                continue
            if npc.lod_level > 0 or not npc.lod_update_due:
                continue
            if npc.crashed_timer > 0.0:
                continue

            blocked_by_npc = False

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
                            elif dist < min_gap + 10.0 and npc.speed > other.speed:
                                # Match or follow leader speed smoothly
                                target_follow_speed = max(0.0, other.speed * 0.9)
                                if npc.escape_timer <= 0.0:
                                    npc.speed = max(target_follow_speed, npc.speed - 16.0 * dt)
                                blocked_by_npc = True

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
                            elif p_dist < min_p_gap + 10.0 and npc.speed > max(0.0, player_car.speed):
                                target_p_speed = max(0.0, player_car.speed * 0.9)
                                npc.speed = max(target_p_speed, npc.speed - 16.0 * dt)

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
                if -25.0 < longitudinal <= -2.0:
                    passed_matching_light = True
                elif -2.0 < longitudinal < 25.0:
                    if nearest_light is None or longitudinal < nearest_light[0]:
                        nearest_light = (longitudinal, tl)

            if nearest_light is not None and not passed_matching_light:
                state = nearest_light[1].get_state(self.sim_time)
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

            # Continue through the junction if the NPC has already entered it.
            if self._junction_near_point((npc.x, npc.y), npc.layer):
                must_stop = False

            # Calculate cornering speed limit based on heading angle to next vertex / sharp curves
            turn_limit_speed = npc.target_speed
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

            # Check if NPC is in crashed recovery state
            if npc.crashed_timer > 0.0 or getattr(npc, "fallen", False):
                action = "fallen" if getattr(npc, "fallen", False) else "recovering from crash"
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
                    reason = "stop sign"
                elif nearest_yield_sign is not None:
                    reason = "yield sign"
                elif nearest_light is not None:
                    reason = "red/yellow traffic light"
                else:
                    reason = "roadworks"
            elif junction_blocked:
                action = "stopping"
                reason = "junction occupied"
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
        for npc in self.npcs:
            if npc.is_police:
                continue
            if npc.state == "parking_departure":
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

                    # Smooth heading towards target vertex with angular rate limiting
                if dist_to_tgt > 1e-3:
                    target_heading = math.atan2(to_tgt_y, to_tgt_x)
                    heading_diff = (target_heading - npc.heading + math.pi) % (2 * math.pi) - math.pi
                    # Limit turn rate so junction turns are visibly gradual.
                    max_turn = 1.8 * dt
                    if abs(heading_diff) <= max_turn:
                        npc.heading = target_heading
                    else:
                        npc.heading += math.copysign(max_turn, heading_diff)
                    if (
                        npc.turn_signal
                        and npc.next_route is None
                        and npc.turn_signal_elapsed >= 0.45
                        and abs(heading_diff) < 0.12
                    ):
                        npc.turn_signal = ""

                if dist_step < dist_to_tgt:
                    # Advance partially along current segment
                    ratio = dist_step / dist_to_tgt
                    npc.x += to_tgt_x * ratio
                    npc.y += to_tgt_y * ratio
                    dist_step = 0.0
                else:
                    # Reach the vertex
                    npc.x = shifted_target_x
                    npc.y = shifted_target_y
                    dist_step -= dist_to_tgt

                    # Advance to next segment or next connected way
                    if npc.direction == 1:
                        # At intermediate vertices, check if there is an intersecting road to turn onto
                        turned = False
                        if npc.segment_idx + 1 < len(pts) - 1:
                            # 35% chance to make a turn at an intersection along the way
                            if random.random() < 0.35:
                                turn_route = npc.next_route or self._find_next_way_and_segment(
                                    npc.way, target_pt, exclude_reverse=True, incoming_heading=npc.heading
                                )
                                if turn_route and turn_route[0] is not npc.way:
                                    old_heading = npc.heading
                                    npc.way, npc.segment_idx, npc.direction = turn_route
                                    npc.turn_signal = self._turn_signal_for_route(old_heading, npc)
                                    npc.turn_signal_elapsed = 0.0
                                    npc.layer = getattr(npc.way, "layer", 0)
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(
                                        npc.way, npc.overtaking, npc.direction
                                    )
                                    npc.next_route = None
                                    pts = npc.way.points_m
                                    turned = True
                            if not turned:
                                npc.segment_idx += 1
                        else:
                            # Reached end of way, find connecting road
                            next_route = npc.next_route or self._find_next_way_and_segment(
                                npc.way, target_pt, incoming_heading=npc.heading
                            )
                            if next_route:
                                old_heading = npc.heading
                                npc.way, npc.segment_idx, npc.direction = next_route
                                npc.turn_signal = self._turn_signal_for_route(old_heading, npc)
                                npc.turn_signal_elapsed = 0.0
                                npc.layer = getattr(npc.way, "layer", 0)
                                npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                npc.target_lane_offset = compute_desired_lane_offset(
                                    npc.way, npc.overtaking, npc.direction
                                )
                                npc.next_route = None
                                pts = npc.way.points_m
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
                            if random.random() < 0.35:
                                turn_route = npc.next_route or self._find_next_way_and_segment(
                                    npc.way, target_pt, exclude_reverse=True, incoming_heading=npc.heading
                                )
                                if turn_route and turn_route[0] is not npc.way:
                                    old_heading = npc.heading
                                    npc.way, npc.segment_idx, npc.direction = turn_route
                                    npc.turn_signal = self._turn_signal_for_route(old_heading, npc)
                                    npc.turn_signal_elapsed = 0.0
                                    npc.layer = getattr(npc.way, "layer", 0)
                                    npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                    npc.target_lane_offset = compute_desired_lane_offset(
                                        npc.way, npc.overtaking, npc.direction
                                    )
                                    npc.next_route = None
                                    pts = npc.way.points_m
                                    turned = True
                            if not turned:
                                npc.segment_idx -= 1
                        else:
                            # Reached start of way in reverse
                            next_route = npc.next_route or self._find_next_way_and_segment(
                                npc.way, target_pt, incoming_heading=npc.heading
                            )
                            if next_route:
                                old_heading = npc.heading
                                npc.way, npc.segment_idx, npc.direction = next_route
                                npc.turn_signal = self._turn_signal_for_route(old_heading, npc)
                                npc.turn_signal_elapsed = 0.0
                                npc.layer = getattr(npc.way, "layer", 0)
                                npc.target_speed = calculate_npc_target_speed(npc.way, npc.speed_factor)
                                npc.target_lane_offset = compute_desired_lane_offset(
                                    npc.way, npc.overtaking, npc.direction
                                )
                                npc.next_route = None
                                pts = npc.way.points_m
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
