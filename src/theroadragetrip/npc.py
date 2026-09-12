"""NPC-001: the first properly architected autonomous NPC car.

One Resident -> one Driver -> one NPCVehicle -> one preplanned OSM route,
driven with real traffic rules. See .github/prompts/NPC-001.md.

Layering (section 18 of that spec):

    Resident -> Driver -> route (TrafficWorld.plan_route) -> lane planning
    -> traffic rule engine (traffic_rules.py) -> vehicle controller
    (physics.update_car_physics) -> NPCVehicle (physical + render state)

No Pygame anywhere in this module - rendering lives entirely in
render/vehicles.py's draw_npc_cars, which NPCVehicle is shaped to satisfy
directly (that renderer already existed, unused, ahead of this feature).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .geo import clamp
from .osm import Way
from .physics import Car, SpatialWayGrid, update_car_physics
from .residents import ResidentManager
from .traffic_rules import TrafficAction, TrafficDecision, decide_traffic_action
from .traffic_world import TrafficWorld


class NPCState:
    """Vehicle state machine (NPC-001 section 10).

    The architecture must support future states without rework, but
    NPC-001 only implements these: CRASHED, DISABLED, DRIVER_EXITED,
    ABANDONED, PARKING, DESPAWNING are deliberately not implemented yet.
    """
    SPAWNING = "SPAWNING"
    CRUISING = "CRUISING"
    APPROACHING_INTERSECTION = "APPROACHING_INTERSECTION"
    WAITING = "WAITING"
    TURNING = "TURNING"
    ARRIVING = "ARRIVING"


WAYPOINT_REACH_RADIUS_M = 4.0
INTERSECTION_APPROACH_RADIUS_M = 25.0
CORNER_ANGLE_THRESHOLD_DEG = 20.0
CORNER_RADIUS_M = 6.0
CORNER_SAMPLE_COUNT = 5
STEER_FULL_ANGLE_DEG = 25.0  # heading error at/beyond which steering saturates at full lock
ARRIVAL_DECEL_MPS2 = 3.0  # comfortable braking rate approaching the final destination waypoint
LANE_BIAS_LOOKAHEAD_M = 20.0  # start easing into a turn lane this far before the corner (NPC-002 section 5)


@dataclass
class PathPoint:
    x: float
    y: float
    way: Optional[Way] = None
    is_turn: bool = False
    maneuver: Optional[str] = None  # "left" | "right", set on a turn's sampled points
    lane_bias: Optional[str] = None  # "left" | "right" | None, which lane this point was placed in


def _lane_offset_point(
    way: Optional[Way], x: float, y: float, heading: float, vehicle_width_m: float = 1.8,
    maneuver: Optional[str] = None,
) -> Tuple[float, float]:
    """Shift a road-centerline point to the appropriate travel lane.

    Base case mirrors physics._place_car_on_right_lane's exact offset
    formula (same right-hand-traffic convention already used to place the
    player's car), just returning a point instead of mutating a Car. When
    a turn is coming up (`maneuver`), bias within that same right-hand
    half of the road instead: hug the curb for a right turn, hug the
    centerline for a left turn - NPC-002 section 5's required lane
    selection, without inventing a discrete per-lane model nothing else
    in this codebase has (the player's own lane placement is this same
    continuous half-width offset); real turn:lanes-tagged lane geometry
    is future work if a road actually needs more than this.
    """
    if way is None:
        return x, y
    half_width = max(0.0, getattr(way, "half_width_m", 4.0))
    max_offset = max(0.0, half_width - vehicle_width_m * 0.5)
    if maneuver == "right":
        lane_offset = max_offset
    elif maneuver == "left":
        lane_offset = min(1.0, max_offset)
    else:
        lane_offset = min(max(1.2, half_width * 0.45), max_offset)
    return x + math.sin(heading) * lane_offset, y - math.cos(heading) * lane_offset


def _round_corner(
    prev_pt: Tuple[float, float],
    corner_pt: Tuple[float, float],
    next_pt: Tuple[float, float],
    radius_m: float = CORNER_RADIUS_M,
    samples: int = CORNER_SAMPLE_COUNT,
) -> List[Tuple[float, float]]:
    """Replace a sharp route vertex with a sampled quadratic-Bezier arc
    (NPC-001 section 9), so a turn is a smooth curve, never a pivot on a
    single point. corner_pt is used as the Bezier control point."""
    in_dx, in_dy = corner_pt[0] - prev_pt[0], corner_pt[1] - prev_pt[1]
    out_dx, out_dy = next_pt[0] - corner_pt[0], next_pt[1] - corner_pt[1]
    in_len = math.hypot(in_dx, in_dy)
    out_len = math.hypot(out_dx, out_dy)
    if in_len < 1e-6 or out_len < 1e-6:
        return [corner_pt]
    pull = min(radius_m, in_len * 0.5, out_len * 0.5)
    start = (corner_pt[0] - in_dx / in_len * pull, corner_pt[1] - in_dy / in_len * pull)
    end = (corner_pt[0] + out_dx / out_len * pull, corner_pt[1] + out_dy / out_len * pull)
    points = [start]
    for i in range(1, samples + 1):
        t = i / (samples + 1)
        points.append((
            (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * corner_pt[0] + t ** 2 * end[0],
            (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * corner_pt[1] + t ** 2 * end[1],
        ))
    points.append(end)
    return points


def _dedupe_points(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Collapse consecutive points closer than 1cm together.

    plan_route() prepends the raw start and appends the raw target onto
    its nearest graph nodes, which are frequently that exact same point
    (an origin/destination chosen ON a road) - without this, heading/lane
    math would divide by a zero-length leading/trailing segment.
    """
    deduped: List[Tuple[float, float]] = []
    for point in points:
        if not deduped or math.hypot(point[0] - deduped[-1][0], point[1] - deduped[-1][1]) > 0.01:
            deduped.append(point)
    return deduped


def _way_at_point(
    spatial_grid: Optional[SpatialWayGrid], ways: List[Way], x: float, y: float
) -> Tuple[Optional[Way], float]:
    """Return the Way nearest (x, y) and the distance to it in meters -
    via the shared spatial grid when one is available (the normal,
    O(1)-ish path already used everywhere else in the game), falling back
    to a linear scan only when it isn't (small test fixtures)."""
    if spatial_grid is not None:
        way = spatial_grid.get_current_road(x, y, car_roads_only=True)
        # SpatialWayGrid.get_current_road only ever returns a way whose
        # half-width already covers (x, y), i.e. the point is already "on"
        # it - callers needing an actual distance only care whether it
        # found anything at all, so 0.0 here is exact enough.
        return way, (0.0 if way is not None else float("inf"))
    best_way, best_dist = None, float("inf")
    for way in ways:
        for (ax, ay), (bx, by) in zip(way.points_m, way.points_m[1:]):
            dx, dy = bx - ax, by - ay
            length_sq = dx * dx + dy * dy
            t = 0.0 if length_sq < 1e-9 else clamp(((x - ax) * dx + (y - ay) * dy) / length_sq, 0.0, 1.0)
            dist = math.hypot(x - (ax + t * dx), y - (ay + t * dy))
            if dist < best_dist:
                best_dist, best_way = dist, way
    return best_way, best_dist


MAX_ROUTE_OFFROAD_TOLERANCE_M = 15.0


def route_stays_on_road(
    points: List[Tuple[float, float]],
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    tolerance_m: float = MAX_ROUTE_OFFROAD_TOLERANCE_M,
) -> bool:
    """Verify every segment of a planned route actually runs along a
    mapped road, rather than a straight-line shortcut across empty land.

    plan_route()'s A* picks among the K nearest graph nodes to the target
    as candidate "last mile" endpoints (see its docstring) - on a very
    small or lopsided graph that can, in principle, let a node close to
    the *start* look like a cheaper stand-in target than actually driving
    the real path, producing a route that quietly cuts across a corner
    instead of following the road through it. NPC-001 section 5 requires
    verifying the route has real road segments before ever spawning a
    vehicle onto it - this is that check.
    """
    for i in range(len(points) - 1):
        (ax, ay), (bx, by) = points[i], points[i + 1]
        _, distance = _way_at_point(spatial_grid, ways, (ax + bx) / 2.0, (ay + by) / 2.0)
        if distance > tolerance_m:
            return False
    return True


def build_driving_path(
    route_points: List[Tuple[float, float]],
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    vehicle_width_m: float = 1.8,
    corner_radius_m: float = CORNER_RADIUS_M,
) -> List[PathPoint]:
    """Turn a raw centerline route (TrafficWorld.plan_route's output) into
    a lane-correct, corner-smoothed path for an NPC to follow.

    Kept as one function for NPC-001 (one vehicle, no need for a generic
    multi-stage pipeline object yet), but route planning (the caller),
    lane offsetting, and corner rounding remain distinct, independently
    testable steps - see build_driving_path's own helpers.
    """
    route_points = _dedupe_points(route_points)
    n = len(route_points)
    if n < 2:
        return [PathPoint(p[0], p[1]) for p in route_points]

    segment_heading = [
        math.atan2(route_points[i + 1][1] - route_points[i][1], route_points[i + 1][0] - route_points[i][0])
        for i in range(n - 1)
    ]
    segment_length = [
        math.hypot(route_points[i + 1][0] - route_points[i][0], route_points[i + 1][1] - route_points[i][1])
        for i in range(n - 1)
    ]
    segment_way = [
        _way_at_point(
            spatial_grid, ways,
            (route_points[i][0] + route_points[i + 1][0]) / 2.0,
            (route_points[i][1] + route_points[i + 1][1]) / 2.0,
        )[0]
        for i in range(n - 1)
    ]

    # Which vertices are real turns and which way, computed once up front
    # so lane offsetting (needs to know a turn is *coming*) and corner
    # rounding (needs to know a vertex *is* one) share one classification
    # instead of two copies of the same angle threshold.
    corner_maneuver: List[Optional[str]] = [None] * n
    for i in range(1, n - 1):
        signed_turn = (segment_heading[i] - segment_heading[i - 1] + math.pi) % (2.0 * math.pi) - math.pi
        if math.degrees(abs(signed_turn)) >= CORNER_ANGLE_THRESHOLD_DEG:
            corner_maneuver[i] = "left" if signed_turn > 0 else "right"

    def _upcoming_maneuver(start: int) -> Optional[str]:
        if corner_maneuver[start] is not None:
            return corner_maneuver[start]
        remaining = 0.0
        for j in range(start, n - 1):
            remaining += segment_length[j]
            if remaining > LANE_BIAS_LOOKAHEAD_M:
                return None
            if corner_maneuver[j + 1] is not None:
                return corner_maneuver[j + 1]
        return None

    lane_points: List[Tuple[float, float, Optional[Way]]] = []
    lane_bias: List[Optional[str]] = []
    for i, (x, y) in enumerate(route_points):
        seg = min(i, n - 2)
        bias = _upcoming_maneuver(i)
        lx, ly = _lane_offset_point(segment_way[seg], x, y, segment_heading[seg], vehicle_width_m, maneuver=bias)
        lane_points.append((lx, ly, segment_way[seg]))
        lane_bias.append(bias)

    path: List[PathPoint] = [PathPoint(*lane_points[0], lane_bias=lane_bias[0])]
    for i in range(1, len(lane_points) - 1):
        maneuver = corner_maneuver[i]
        if maneuver is not None:
            prev_xy = (path[-1].x, path[-1].y)
            corner_xy = (lane_points[i][0], lane_points[i][1])
            next_xy = (lane_points[i + 1][0], lane_points[i + 1][1])
            for ax, ay in _round_corner(prev_xy, corner_xy, next_xy, corner_radius_m):
                path.append(PathPoint(ax, ay, lane_points[i][2], is_turn=True, maneuver=maneuver, lane_bias=maneuver))
        else:
            path.append(PathPoint(*lane_points[i], lane_bias=lane_bias[i]))
    path.append(PathPoint(*lane_points[-1], lane_bias=lane_bias[-1]))
    return path


@dataclass
class Driver:
    """Driving-specific state and decisions (NPC-001 section 4).

    Owns the driving *decisions*; never touches Pygame or rendering.
    """
    resident_id: int
    vehicle_id: int
    path: List[PathPoint]
    destination: Tuple[float, float]
    path_index: int = 1  # path[0] is the spawn point, already "reached"
    current_way: Optional[Way] = None
    target_speed_mps: float = 0.0
    decision: TrafficDecision = field(default_factory=lambda: TrafficDecision(TrafficAction.PROCEED, 0.0))

    @property
    def next_maneuver(self) -> str:
        for point in self.path[self.path_index:]:
            if point.maneuver:
                return point.maneuver
        return "arrive" if self.path_index >= len(self.path) - 1 else "straight"

    @property
    def next_way(self) -> Optional[Way]:
        """The road beyond the upcoming turn, or None if still on/past the
        last one (NPC-002 section 21's debug HUD "next way")."""
        for point in self.path[self.path_index:]:
            if point.way is not None and point.way is not self.current_way:
                return point.way
        return None

    @property
    def current_lane_bias(self) -> Optional[str]:
        """Which lane the vehicle is currently placed in: "left"/"right"
        while easing into or through a turn, None for the default
        right-hand cruising lane."""
        if self.path_index < len(self.path):
            return self.path[self.path_index].lane_bias
        return None

    @property
    def route_progress(self) -> float:
        return self.path_index / max(1, len(self.path) - 1)


@dataclass
class NPCVehicle:
    """Physical NPC vehicle (NPC-001 section 3).

    All physical simulation state lives in `car` (physics.Car, driven by
    the same update_car_physics the player uses - no duplicated physics).
    Everything else here is render/identity metadata physics.Car has no
    business knowing about.

    Shaped to satisfy render.vehicles.draw_npc_cars's existing duck-typed
    NPC interface (x/y/heading/speed/... via the properties below) - that
    renderer already shipped, unused, ahead of this feature.
    """
    vehicle_id: int
    car: Car
    owner_id: Optional[int] = None  # active driver's resident_id; None => must not move
    state: str = NPCState.SPAWNING
    vehicle_type: str = "car"
    color: Tuple[int, int, int] = (150, 155, 165)
    is_taxi: bool = False
    is_police: bool = False
    is_on_foot: bool = False
    fallen: bool = False
    way: Optional[Way] = None
    lod_level: int = 0
    destination: Optional[Tuple[float, float]] = None
    destination_parking_space_id: Optional[int] = None
    travel_route: List[Tuple[float, float]] = field(default_factory=list)
    parking_route: Optional[List] = None
    turn_signal: str = ""
    turn_signal_elapsed: float = 0.0
    debug_waiting_for: str = ""
    crashed_timer: float = 0.0

    @property
    def x(self) -> float:
        return self.car.x

    @property
    def y(self) -> float:
        return self.car.y

    @property
    def heading(self) -> float:
        return self.car.heading

    @property
    def speed(self) -> float:
        return self.car.speed

    @property
    def length_m(self) -> float:
        return self.car.length_m

    @property
    def width_m(self) -> float:
        return self.car.width_m

    @property
    def layer(self) -> int:
        return self.car.layer


def has_active_driver(vehicle: NPCVehicle, resident_manager: ResidentManager) -> bool:
    """The fundamental NPC-001 invariant: moving NPC vehicle == active
    driver Resident. A vehicle whose owning Resident isn't currently
    driving it must never be treated as under power."""
    if vehicle.owner_id is None:
        return False
    resident = resident_manager.get(vehicle.owner_id)
    return resident is not None and resident.active_vehicle_id == vehicle.vehicle_id


def spawn_npc(
    vehicle_id: int,
    resident_manager: ResidentManager,
    traffic_world: TrafficWorld,
    ways: List[Way],
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    spatial_grid: Optional[SpatialWayGrid] = None,
    color: Tuple[int, int, int] = (150, 155, 165),
) -> Optional[Tuple[int, Driver, NPCVehicle]]:
    """Create the Resident -> Driver -> NPCVehicle chain for one NPC
    (NPC-001 sections 5, 11, 12).

    The route is planned and validated BEFORE anything is created; a
    vehicle is never spawned to then go hunting for a route while
    already "driving". Returns None if no valid route exists.
    """
    raw_route = traffic_world.plan_route(origin, destination)
    if raw_route is None:
        return None
    deduped_route = _dedupe_points(raw_route)
    if len(deduped_route) < 3:  # start + >=1 real road node + target
        return None
    if not route_stays_on_road(deduped_route, ways, spatial_grid=spatial_grid):
        return None

    path = build_driving_path(deduped_route, ways, spatial_grid=spatial_grid)
    if len(path) < 2:
        return None

    # 1. create/select the Resident, 2. make it the driver, 3. create the
    # vehicle, 4. associate vehicle<->Driver<->Resident - in that order,
    # per section 11 - never a moving vehicle first with a driver attached
    # after.
    resident = resident_manager.create(mode="driving")
    resident.vehicle_ids.add(vehicle_id)
    resident.active_vehicle_id = vehicle_id

    start, aim = path[0], path[1]
    start_heading = math.atan2(aim.y - start.y, aim.x - start.x)
    car = Car(x=start.x, y=start.y, heading=start_heading, speed=0.0, length_m=4.3, width_m=1.8)
    vehicle = NPCVehicle(
        vehicle_id=vehicle_id,
        car=car,
        owner_id=resident.resident_id,
        way=start.way,
        destination=destination,
        travel_route=[(p.x, p.y) for p in path],
    )
    driver = Driver(
        resident_id=resident.resident_id,
        vehicle_id=vehicle_id,
        path=path,
        destination=destination,
        current_way=start.way,
    )
    return resident.resident_id, driver, vehicle


def update_npc(
    vehicle: NPCVehicle,
    driver: Driver,
    dt: float,
    traffic_world: TrafficWorld,
    resident_manager: ResidentManager,
) -> None:
    """Advance one NPC's driving decision and physics by one frame
    (NPC-001 sections 5-10). Pure simulation, no Pygame.

    Performance (section 16): the route is never recalculated here (only
    once, in spawn_npc); the only per-frame scan is the traffic-light
    lookup, and it reuses TrafficWorld._nearby_traffic_lights - the same
    call the player's own red-light assist already makes every frame.
    """
    if not has_active_driver(vehicle, resident_manager):
        vehicle.car.speed = 0.0
        return

    path = driver.path
    while driver.path_index < len(path) - 1 and math.hypot(
        path[driver.path_index].x - vehicle.car.x, path[driver.path_index].y - vehicle.car.y
    ) < WAYPOINT_REACH_RADIUS_M:
        driver.path_index += 1

    target = path[driver.path_index]
    if target.way is not None:
        driver.current_way = target.way
        vehicle.way = target.way

    approaching_final_waypoint = driver.path_index >= len(path) - 1
    distance_to_target = math.hypot(target.x - vehicle.car.x, target.y - vehicle.car.y)
    at_destination = approaching_final_waypoint and distance_to_target < WAYPOINT_REACH_RADIUS_M

    nearby_lights = traffic_world._nearby_traffic_lights(vehicle.car.x, vehicle.car.y)
    speed_limit_mps = (driver.current_way.speed_limit_kmh / 3.6) if driver.current_way else None
    decision = decide_traffic_action(
        vehicle.car.x, vehicle.car.y, vehicle.car.heading, nearby_lights, traffic_world.sim_time,
        speed_limit_mps=speed_limit_mps,
    )
    driver.decision = decision
    driver.target_speed_mps = decision.target_speed_mps
    if approaching_final_waypoint:
        # Brake for arrival the same comfortable way the traffic rule
        # engine brakes for a stop line, rather than cruising right up to
        # the destination and only then snapping to a stop.
        arrival_cap = math.sqrt(2.0 * ARRIVAL_DECEL_MPS2 * max(0.0, distance_to_target - WAYPOINT_REACH_RADIUS_M))
        driver.target_speed_mps = min(driver.target_speed_mps, arrival_cap)
    if at_destination:
        driver.target_speed_mps = 0.0

    # State machine (section 10) - priority order is what a real driver
    # would report as "what am I doing right now".
    if at_destination:
        vehicle.state = NPCState.ARRIVING
        vehicle.debug_waiting_for = ""
    elif decision.action == TrafficAction.STOP and abs(vehicle.car.speed) < 0.5:
        vehicle.state = NPCState.WAITING
        vehicle.debug_waiting_for = decision.reason
    elif decision.action in (TrafficAction.STOP, TrafficAction.SLOW) and (
        decision.stop_position is None
        or math.hypot(decision.stop_position[0] - vehicle.car.x, decision.stop_position[1] - vehicle.car.y)
        < INTERSECTION_APPROACH_RADIUS_M
    ):
        vehicle.state = NPCState.APPROACHING_INTERSECTION
        vehicle.debug_waiting_for = ""
    elif target.is_turn:
        vehicle.state = NPCState.TURNING
        vehicle.debug_waiting_for = ""
    else:
        vehicle.state = NPCState.CRUISING
        vehicle.debug_waiting_for = ""

    # Vehicle controller (section 8): steer towards the lookahead target;
    # existing physics (update_car_physics, same as the player) ramps
    # heading and speed smoothly - never an instantaneous snap to either.
    # Once at the final waypoint, path_index can't advance any further
    # (there's nothing after it) - chasing that now-fixed point would spin
    # the heading 180 degrees the instant the car coasts past it, so
    # arrival stops steering entirely and just coasts/brakes straight.
    if at_destination:
        steer_left = steer_right = 0.0
    else:
        desired_heading = math.atan2(target.y - vehicle.car.y, target.x - vehicle.car.x)
        heading_error = (desired_heading - vehicle.car.heading + math.pi) % (2.0 * math.pi) - math.pi
        steer_magnitude = clamp(abs(heading_error) / math.radians(STEER_FULL_ANGLE_DEG), 0.0, 1.0)
        steer_left = steer_magnitude if heading_error > 0 else 0.0
        steer_right = steer_magnitude if heading_error < 0 else 0.0

    # speed_limit_mps alone (0 at a stop/arrival) already makes
    # update_car_physics ramp speed down smoothly via its own
    # speed-limiter branch - the same mechanism backing the player's
    # speed-limiter HUD toggle - so throttle just asks for "as fast as
    # currently allowed" rather than needing its own brake/throttle logic.
    update_car_physics(
        vehicle.car, throttle=1.0, brake=0.0, steer_left=steer_left, steer_right=steer_right, dt=dt,
        block_offroad=False, speed_limit_mps=driver.target_speed_mps,
    )


def _largest_route_graph_component(nodes: List[Tuple[float, float, int]], edges: dict) -> List[int]:
    """Return the node indices of TrafficWorld's own route graph's largest
    connected component (plain DFS/union - the graph is at most a few
    thousand nodes, built once at spawn, not a per-frame cost)."""
    visited: set = set()
    best: List[int] = []
    for start in range(len(nodes)):
        if start in visited:
            continue
        component = [start]
        visited.add(start)
        stack = [start]
        while stack:
            current = stack.pop()
            for neighbor, _distance in edges.get(current, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    component.append(neighbor)
                    stack.append(neighbor)
        if len(component) > len(best):
            best = component
    return best


NPC_ROUTE_MAX_HOPS = 30  # how many real intersections the deterministic NPC's trip crosses


def _bfs_destination(nodes, edges, origin_index: int, max_hops: int = NPC_ROUTE_MAX_HOPS) -> int:
    """Walk the route graph breadth-first from origin_index for up to
    max_hops steps and return the last node reached.

    A destination chosen this way is, by construction, connected to the
    origin by a real, moderate-length chain of road edges. Picking
    instead "whichever node is farthest away by straight-line distance"
    (tried first, see NPC-001 dev notes) routinely chose a node at the
    edge of the map whose real road path was a long detour (river,
    one-way streets, ...) - exactly the case where plan_route's
    nearest-node "last mile" heuristic (its own docstring) can end up
    substituting a closer-looking node as a cheaper stand-in and quietly
    stopping short of the real target. A short, ordinary trip through a
    couple dozen intersections doesn't have that gap between straight-
    line and real distance, so it doesn't trigger the same substitution.
    """
    visited = {origin_index}
    frontier = [origin_index]
    last = origin_index
    for _ in range(max_hops):
        if not frontier:
            break
        next_frontier = []
        for current in frontier:
            for neighbor, _distance in edges.get(current, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
                    last = neighbor
        frontier = next_frontier
    return last


def spawn_deterministic_npc(
    resident_manager: ResidentManager,
    traffic_world: TrafficWorld,
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    vehicle_id: int = 1,
) -> Optional[Tuple[int, Driver, NPCVehicle]]:
    """Pick a deterministic origin/destination from the loaded OSM map and
    spawn NPC-001's one NPC there (section 12).

    Both points come from TrafficWorld's OWN route graph - not merely
    from "the largest connected drivable component" by a different
    connectivity definition (connected_drivable_ways' looser join
    tolerance can consider two ways connected that plan_route's exact 3m
    node-snap does not), which would otherwise risk picking two points
    plan_route can't actually route between at all. Deterministic given
    the same map data: origin is the graph's lowest-indexed node in its
    largest connected component, destination is reached by a fixed-length
    breadth-first walk from there (see _bfs_destination) - no hard-coded
    screen coordinates, no randomness.
    """
    nodes = traffic_world._route_nodes
    edges = traffic_world._route_edges
    component = _largest_route_graph_component(nodes, edges)
    if len(component) < 2:
        return None
    origin_index = min(component)
    destination_index = _bfs_destination(nodes, edges, origin_index)
    if destination_index == origin_index:
        return None
    origin = (nodes[origin_index][0], nodes[origin_index][1])
    destination = (nodes[destination_index][0], nodes[destination_index][1])
    return spawn_npc(vehicle_id, resident_manager, traffic_world, ways, origin, destination, spatial_grid=spatial_grid)
