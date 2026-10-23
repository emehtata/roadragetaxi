"""Cyclists as NPC traffic (rrt-019-cyclists): which ways bicycles may use,
how a cyclist rides its route, and the cycling-specific traffic duties.

A cyclist is an ordinary NPCVehicle (vehicle_type "bicycle") with a resident
Driver, in NPCVehicleManager's vehicle list, spatial grid, collision phase,
route jobs and visibility cleanup. Only its network (TrafficWorld's cycle
graph, built by RouteGraphBuild with the filters below) and its per-tick
movement (update_cyclist, in place of the car's update_npc) differ.

Finnish law (docs/finnish-npc-traffic-law.md, Tieliikennelaki 729/2018):
- A bicycle is a vehicle: at an unsignalled junction on the carriageway it
  yields to traffic from the right like any vehicle (§ 24(1)), and obeys
  lights (§ 74, annex 2) and STOP/give-way signs (annex 3.2).
- Entering or crossing the carriageway from a cycle path is "entry from a
  path" (§ 24(3)): the cyclist yields to carriageway traffic from both
  sides. A mounted cyclist gains no pedestrian priority from a zebra.
- Turning drivers yield to cyclists crossing the road they turn into
  (§ 24(2)) - npc.py's turning_yield_to_cyclists.
- §§ 3-5 care: slow for and never ride into pedestrians, also on a shared
  path, whatever the priority.
Game policies here are marked as such.
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

from .geo import angle_diff
from .map_level import SURFACE_LEVEL, on_map_level
from .physics import is_car_road

# Carriageways a bicycle may share with motor traffic (unless bicycle=no).
CYCLE_CARRIAGEWAYS = frozenset({
    "residential", "living_street", "service", "unclassified", "road",
    "tertiary", "tertiary_link", "secondary", "secondary_link", "primary", "primary_link",
})
# Light-traffic ways open to bicycles without an explicit tag.
CYCLE_PATHS = frozenset({"cycleway", "path", "track"})
# Ways bicycles may use only when tagged bicycle=yes/designated/permissive.
CYCLE_IF_TAGGED = frozenset({"footway", "pedestrian", "bridleway", "trunk", "trunk_link"})
CYCLE_ALLOWED_TAGS = frozenset({"yes", "designated", "permissive"})

# Game policy: route cost per metre relative to a cycle path, so cyclists keep
# to cycling infrastructure where the network connects (law only requires
# lawful ways; the guide does not cover the duty to use a cycle path).
COST_CYCLE_PATH = 1.0
COST_ROAD_WITH_CYCLE_LANE = 1.15
COST_QUIET_STREET = 1.4  # residential, living street, service
COST_SHARED_FOOTWAY = 1.6  # a footway open to bicycles: pedestrians first
COST_BUSY_ROAD = 2.2  # tertiary and up without a cycle lane
QUIET_STREETS = frozenset({"residential", "living_street", "service", "unclassified", "road"})

# Riding (game tuning, not law).
CYCLIST_SPEED_MPS = (4.2, 6.4)  # 15-23 km/h, drawn per rider
CYCLIST_ACCEL_MPS2 = 1.2
CYCLIST_BRAKE_MPS2 = 2.5  # comfortable; 4.0 in an emergency
CYCLIST_EMERGENCY_BRAKE_MPS2 = 4.0
CYCLIST_LATERAL_ACCEL_MPS2 = 2.0  # corner speed sqrt(a * r)
CYCLIST_MIN_TURN_RADIUS_M = 2.5
CYCLIST_STOP_BUFFER_M = 1.5  # front wheel behind a stop line / conflict point
CYCLIST_FOLLOW_GAP_M = 1.5
CYCLIST_PEDESTRIAN_CLEARANCE_M = 1.2  # lateral room needed to pass a walker
CYCLIST_PEDESTRIAN_PASS_MPS = 2.0  # passing a walker on a shared path
CYCLIST_PATH_ENTRY_LOOKAHEAD_M = 14.0
CYCLIST_PATH_ENTRY_GAP_S = 4.0  # a car this close in time to the crossing point has priority
CYCLIST_STUCK_TIMEOUT_S = 20.0
CYCLIST_ARRIVAL_RADIUS_M = 1.5
CYCLIST_TRIP_DISTANCE_M = (180.0, 900.0)


def is_cyclable_way(way) -> bool:
    """May a bicycle ride this way? Surface level only, never motorways,
    motor-traffic roads or steps; footways only when signed for bicycles."""
    if not on_map_level(way, SURFACE_LEVEL) or getattr(way, "is_ice_road", False):
        return False
    highway = getattr(way, "highway", "")
    access = getattr(way, "bicycle", None)
    if access in ("no", "dismount") or (access == "use_sidepath" and highway not in CYCLE_PATHS):
        return False  # use_sidepath: the parallel cycle path, not this road
    if getattr(way, "motorroad", False) or highway in ("motorway", "motorway_link", "steps", "corridor"):
        return False
    if highway in CYCLE_PATHS or highway in CYCLE_CARRIAGEWAYS:
        return True
    return highway in CYCLE_IF_TAGGED and access in CYCLE_ALLOWED_TAGS


def cycle_oneway(way) -> int:
    """The way's direction for bicycles: oneway:bicycle=no (or contraflow
    cycleway=opposite*) opens a one-way street both ways."""
    override = getattr(way, "oneway_bicycle", None)
    return getattr(way, "oneway", 0) if override is None else override


def cycle_cost_factor(way) -> float:
    highway = getattr(way, "highway", "")
    if highway in CYCLE_PATHS:
        return COST_CYCLE_PATH
    if highway in ("footway", "pedestrian", "bridleway"):
        return COST_CYCLE_PATH if getattr(way, "bicycle", None) == "designated" else COST_SHARED_FOOTWAY
    if getattr(way, "cycleway", None):
        return COST_ROAD_WITH_CYCLE_LANE
    return COST_QUIET_STREET if highway in QUIET_STREETS else COST_BUSY_ROAD


def on_carriageway(way) -> bool:
    """Riding among motor traffic (not on a cycle path or footway)."""
    return way is not None and is_car_road(way) and getattr(way, "highway", "") not in CYCLE_PATHS


def lateral_offset_m(way, width_m: float) -> float:
    """Where across the way a cyclist rides, right of the centreline: near
    the right edge of a carriageway (§ 18: the right side of the road), in
    the right half of a cycle path so oncoming riders pass (game policy)."""
    half = max(0.0, getattr(way, "half_width_m", 1.5))
    if on_carriageway(way):
        return max(0.0, half - width_m * 0.5 - 0.6)
    return min(half * 0.45, max(0.0, half - width_m * 0.5 - 0.2))


def draw_cruise_speed(rng=random) -> float:
    return rng.uniform(*CYCLIST_SPEED_MPS)


def corner_speed_mps(turn_angle: float, cruise: float) -> float:
    """Speed for a bend of `turn_angle` radians at a path vertex, from a
    radius that tightens as the angle grows."""
    if turn_angle < math.radians(15.0):
        return cruise
    radius = max(CYCLIST_MIN_TURN_RADIUS_M, 12.0 * (math.pi - turn_angle) / math.pi)
    return min(cruise, math.sqrt(CYCLIST_LATERAL_ACCEL_MPS2 * radius))


def approach_cap(speed_target: float, distance_m: float, decel: float = CYCLIST_BRAKE_MPS2) -> float:
    """Highest speed now that still slows to `speed_target` within `distance_m`."""
    return math.sqrt(max(0.0, speed_target * speed_target + 2.0 * decel * max(0.0, distance_m)))


def offset_route(points: List[Tuple[float, float]], ways: List, width_m: float):
    """Route points shifted to the riding line of each leg's way. Returns
    [(x, y, way)] with way[i] the way from point i to i+1."""
    out = []
    for index, (x, y) in enumerate(points):
        prev_way = ways[index - 1] if index > 0 else None
        next_way = ways[index] if index < len(ways) else None
        heading_in = math.atan2(y - points[index - 1][1], x - points[index - 1][0]) if index > 0 else None
        heading_out = (math.atan2(points[index + 1][1] - y, points[index + 1][0] - x)
                       if index + 1 < len(points) else None)
        heading = heading_out if heading_in is None else heading_in if heading_out is None else (
            heading_in + angle_diff(heading_out, heading_in) * 0.5)
        way = next_way or prev_way
        offset = lateral_offset_m(way, width_m) if way is not None else 0.0
        out.append((x + math.sin(heading) * offset, y - math.cos(heading) * offset, next_way or prev_way))
    return out


def route_legs(graph, points) -> Optional[Tuple[List[Tuple[float, float]], List]]:
    """A planned cycle route's points and the way of each leg, or None when
    a leg is not a network edge longer than a snap tolerance: graph_route_
    steps joins start/target with straight connectors, and a cyclist never
    rides an off-network shortcut."""
    if not points:
        return None
    clean = [points[0]]
    for point in points[1:]:
        if math.hypot(point[0] - clean[-1][0], point[1] - clean[-1][1]) > 0.05:
            clean.append(point)
    if len(clean) < 2:
        return None
    ways = []
    for a, b in zip(clean, clean[1:]):
        way = graph.edge_ways.get((a[0], a[1], b[0], b[1]))
        if way is None:
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 1.0:
                return None
            way = ways[-1] if ways else None
        ways.append(way)
    if ways and ways[0] is None:
        ways[0] = next((way for way in ways if way is not None), None)
    if any(way is None for way in ways):
        return None
    return clean, ways


class CycleRoute:
    """A cyclist's ridden line: offset points, the way of each leg, the
    cumulative distance at each point and the § 24(3) path-entry points
    (distance along the route, point) where it joins or crosses the
    carriageway from a cycle path - found once, when the route is planned.
    An entry is (distance along the route of the road's centreline, that
    point, the road's half width): the cyclist waits short of its edge."""

    __slots__ = ("points", "ways", "cum", "entries", "cruise_mps")

    def __init__(self, points, ways, entries, cruise_mps: float) -> None:
        self.points = points
        self.ways = ways
        self.cum = [0.0]
        for a, b in zip(points, points[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.entries = entries
        self.cruise_mps = cruise_mps

    @property
    def length_m(self) -> float:
        return self.cum[-1]


def _segment_intersection(p, p2, q, q2):
    rx, ry = p2[0] - p[0], p2[1] - p[1]
    sx, sy = q2[0] - q[0], q2[1] - q[1]
    denom = rx * sy - ry * sx
    if abs(denom) < 1e-9:
        return None
    t = ((q[0] - p[0]) * sy - (q[1] - p[1]) * sx) / denom
    u = ((q[0] - p[0]) * ry - (q[1] - p[1]) * rx) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t
    return None


def path_entry_points_steps(points, ways, cum, spatial_grid):
    """Where a route ridden off the carriageway meets it: a leg on a cycle
    path/footway that crosses a car road, or the leg where the route moves
    from a path onto a car road. Resumable (yields per leg), spatially
    bounded by `spatial_grid` (the world road grid)."""
    entries = []
    for index, (a, b) in enumerate(zip(points, points[1:])):
        yield
        way = ways[index]
        previous = ways[index - 1] if index > 0 else None
        if on_carriageway(way):
            if previous is not None and not on_carriageway(previous):
                entries.append((cum[index] + getattr(way, "half_width_m", 3.0), a, getattr(way, "half_width_m", 3.0)))
            continue
        if spatial_grid is None:
            continue
        layer = getattr(way, "layer", 0)
        for road in spatial_grid.ways_in_rect(min(a[0], b[0]) - 1, min(a[1], b[1]) - 1,
                                              max(a[0], b[0]) + 1, max(a[1], b[1]) + 1):
            if road is way or not on_carriageway(road) or getattr(road, "layer", 0) != layer:
                continue
            for q, q2 in zip(road.points_m, road.points_m[1:]):
                t = _segment_intersection(a, b, q, q2)
                if t is not None:
                    entries.append((cum[index] + t * (cum[index + 1] - cum[index]),
                                    (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                                    getattr(road, "half_width_m", 3.0)))
    entries.sort(key=lambda entry: entry[0])
    merged = []
    for entry in entries:  # one crossing of a dual carriageway or a road's two segments: one duty
        if not merged or entry[0] - merged[-1][0] > 3.0:
            merged.append(entry)
    return merged


def _progress(route: CycleRoute, index: int, x: float, y: float) -> float:
    """Distance along the route of (x, y), projected on leg index-1 -> index."""
    a, b = route.points[index - 1], route.points[index]
    length = route.cum[index] - route.cum[index - 1]
    if length <= 0.0:
        return route.cum[index]
    t = ((x - a[0]) * (b[0] - a[0]) + (y - a[1]) * (b[1] - a[1])) / (length * length)
    return route.cum[index - 1] + max(0.0, min(1.0, t)) * length


def point_at(route: CycleRoute, s: float) -> Tuple[float, float]:
    s = max(0.0, min(route.length_m, s))
    import bisect
    index = max(1, min(len(route.points) - 1, bisect.bisect_left(route.cum, s)))
    a, b = route.points[index - 1], route.points[index]
    length = route.cum[index] - route.cum[index - 1]
    t = 0.0 if length <= 0.0 else (s - route.cum[index - 1]) / length
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _turn_angle_at(route: CycleRoute, index: int) -> float:
    if index <= 0 or index >= len(route.points) - 1:
        return 0.0
    a, b, c = route.points[index - 1], route.points[index], route.points[index + 1]
    return abs(angle_diff(math.atan2(c[1] - b[1], c[0] - b[0]), math.atan2(b[1] - a[1], b[0] - a[0])))


def is_cyclist(obj) -> bool:
    return getattr(obj, "vehicle_type", None) == "bicycle"


def _motor_traffic(obj) -> bool:
    state = getattr(obj, "state", None)
    return (not is_cyclist(obj) and getattr(state, "value", state) not in ("PARKED", "CRASHED")
            and abs(getattr(obj, "speed", 0.0)) > 0.3)


def path_entry_cap(x, y, s_now, route: CycleRoute, obstacles, speed: float):
    """§ 24(3): before joining or crossing the carriageway from a cycle path,
    yield to motor traffic from both sides. Returns (cap, reason) or None."""
    for s_entry, point, half_width in route.entries:
        to_edge = s_entry - half_width - s_now  # to the near edge of the carriageway
        if s_entry - s_now < -half_width:
            continue  # crossed it
        if to_edge > CYCLIST_PATH_ENTRY_LOOKAHEAD_M:
            break
        if to_edge < 0.6 and speed > 1.0:
            return None  # already on it: clear it, don't stop in the lane
        for other in obstacles:
            if not _motor_traffic(other):
                continue
            dx, dy = point[0] - other.x, point[1] - other.y
            distance = math.hypot(dx, dy)
            if distance > 70.0:
                continue
            closing = (dx * math.cos(other.heading) + dy * math.sin(other.heading)) / max(distance, 0.1)
            if distance > 6.0 and closing < 0.5:
                continue  # driving away or past
            if distance / max(abs(other.speed), 0.5) < CYCLIST_PATH_ENTRY_GAP_S or distance < 6.0:
                return (approach_cap(0.0, to_edge - CYCLIST_STOP_BUFFER_M), "yielding: entering carriageway from cycle path")
        return None
    return None


def pedestrian_cap(x, y, heading, pedestrians):
    """§§ 3-5 care: pass a walker ahead slowly with room, or stop short of one in the way."""
    fx, fy = math.cos(heading), math.sin(heading)
    best = None
    for ped in pedestrians:
        dx, dy = ped.x - x, ped.y - y
        longitudinal = dx * fx + dy * fy
        if longitudinal <= 0.0 or longitudinal > 10.0:
            continue
        lateral = abs(-dx * fy + dy * fx) - getattr(ped, "radius_m", 0.3)
        if lateral > CYCLIST_PEDESTRIAN_CLEARANCE_M + 0.5:
            continue
        if lateral < CYCLIST_PEDESTRIAN_CLEARANCE_M * 0.6:
            cap, reason = approach_cap(0.0, longitudinal - CYCLIST_STOP_BUFFER_M - 0.5), "pedestrian in the way"
        else:
            cap, reason = approach_cap(CYCLIST_PEDESTRIAN_PASS_MPS, longitudinal - 2.0), "passing a pedestrian"
        if best is None or cap < best[0]:
            best = (cap, reason)
    return best


def turning_yield_to_cyclists(vehicle, turn_point, exit_heading, distance_to_turn, obstacles):
    """§ 24(2): a turning driver yields to cyclists crossing the road it
    turns into - also one riding straight on beside it on a cycle lane or
    path. A cyclist whose ride passes near the turn point within a few
    seconds, not riding the exit road with or against the car, holds the
    car short of the turn. Returns a target speed cap or None."""
    if distance_to_turn is None or distance_to_turn < vehicle.length_m * 0.5:
        return None  # already turning: clear the junction
    tx, ty = turn_point
    stop_room = distance_to_turn - vehicle.length_m * 0.5 - 2.0
    for other in obstacles:
        if not is_cyclist(other) or getattr(other, "state", None) in ("PARKED", "CRASHED"):
            continue
        dx, dy = tx - other.x, ty - other.y
        distance = math.hypot(dx, dy)
        if distance > 25.0:
            continue
        relative = abs(angle_diff(other.heading, exit_heading))
        if relative < math.radians(30.0) or relative > math.radians(150.0):
            continue  # riding the exit road: following or oncoming, not crossing
        fx, fy = math.cos(other.heading), math.sin(other.heading)
        along = dx * fx + dy * fy
        miss = abs(-dx * fy + dy * fx)
        if along < -2.0 or miss > 6.0:
            continue  # already past, or its line misses the turn
        if along / max(abs(other.speed), 0.5) > 5.0:
            continue
        return 0.0 if stop_room <= 0.1 else math.sqrt(2.0 * 3.0 * stop_room)
    return None


def update_cyclist(vehicle, driver, dt: float, traffic_world, obstacles, pedestrians) -> Optional[str]:
    """One tick of a cyclist riding its CycleRoute. Returns "arrived",
    "stuck" (no progress outside a lawful wait for CYCLIST_STUCK_TIMEOUT_S)
    or None. Movement is kinematic with bicycle limits: acceleration,
    braking, a minimum turning radius - no instant stops, no pivoting."""
    from .npc import NPCState
    from .traffic_rules import TrafficAction, TrafficDecision, crossing_yield_decision, decide_traffic_action
    from .traffic_rules import nearest_vehicle_ahead, stop_sign_decision
    from .osm import StopSign

    route: CycleRoute = driver.cycle
    car = vehicle.car
    index = max(1, min(len(route.points) - 1, driver.path_index))
    s_now = _progress(route, index, car.x, car.y)
    while index < len(route.points) - 1 and s_now >= route.cum[index] - 0.3:
        index += 1
        s_now = _progress(route, index, car.x, car.y)
    driver.path_index = index
    way = route.ways[index - 1]
    driver.current_way = vehicle.way = way
    remaining = route.length_m - s_now
    if remaining <= CYCLIST_ARRIVAL_RADIUS_M and abs(car.speed) < 0.3:
        car.speed = 0.0
        return "arrived"

    look = point_at(route, s_now + max(2.0, abs(car.speed) * 0.9))
    aim = math.atan2(look[1] - car.y, look[0] - car.x)
    target, reason, lawful_wait = route.cruise_mps, "", False
    if way is not None and way.highway == "living_street":
        target = min(target, 20.0 / 3.6)  # § 43
    elif way is not None and way.highway == "pedestrian":
        target = min(target, 3.0)  # § 44: walking pace among pedestrians (game value)
    for k in range(index, len(route.points) - 1):  # corners within braking reach
        ahead = route.cum[k] - s_now
        if ahead > 20.0:
            break
        target = min(target, approach_cap(corner_speed_mps(_turn_angle_at(route, k), route.cruise_mps), ahead))
    target = min(target, approach_cap(0.0, remaining - 0.5))

    def apply(cap, why, wait=True):
        nonlocal target, reason, lawful_wait
        if cap is not None and cap < target:
            target, reason = cap, why
            lawful_wait = lawful_wait or wait

    lights = traffic_world._nearby_traffic_lights(car.x, car.y, 45.0)
    decision = decide_traffic_action(
        car.x, car.y, aim, lights, traffic_world.sim_time, speed_limit_mps=route.cruise_mps,
        stop_buffer_m=CYCLIST_STOP_BUFFER_M, deceleration_mps2=CYCLIST_BRAKE_MPS2, actual_speed_mps=car.speed,
        yellow_stop_light=(driver.decision.light if driver.decision.reason == "yellow light, stopping in time" else None),
    )
    if decision.light is not None:
        apply(decision.target_speed_mps, decision.reason, decision.action != TrafficAction.PROCEED)
    else:
        signs = traffic_world.nearby_signs(car.x, car.y) if on_carriageway(way) else ()
        if on_carriageway(way):  # § 24(1): a bicycle on the carriageway is a vehicle at the junction
            crossing = crossing_yield_decision(vehicle, obstacles, signs=signs, speed_limit_mps=route.cruise_mps)
            if crossing is not None:
                apply(crossing.target_speed_mps, crossing.reason)
            stop = stop_sign_decision(vehicle, driver, [sign for sign in signs if isinstance(sign, StopSign)])
            if stop is not None:
                apply(stop.target_speed_mps, stop.reason)
        entry = path_entry_cap(car.x, car.y, s_now, route, obstacles, abs(car.speed))
        if entry is not None:
            apply(*entry)
    ped = pedestrian_cap(car.x, car.y, aim, pedestrians)
    if ped is not None:
        apply(ped[0], ped[1])
    lead = nearest_vehicle_ahead(car.x, car.y, aim, obstacles, self_id=id(vehicle),
                                 detection_distance_m=25.0, lateral_limit_m=max(0.9, vehicle.width_m + 0.3))
    if lead is not None:
        gap, other = lead
        room = gap - getattr(other, "length_m", 4.3) * 0.5 - vehicle.length_m * 0.5 - CYCLIST_FOLLOW_GAP_M
        stalled = abs(getattr(other, "speed", 0.0)) < 0.3 and getattr(other, "state", None) not in ("WAITING", "CRUISING")
        # A queue is a lawful wait; a wreck or parked car across the path is not.
        apply(approach_cap(max(0.0, getattr(other, "speed", 0.0)), room), "blocked" if stalled else "following",
              wait=not stalled)
    driver.target_speed_mps = target
    driver.decision = TrafficDecision(TrafficAction.STOP if target < 0.1 else TrafficAction.PROCEED, target,
                                      reason=reason or "riding", light=decision.light)

    if target > car.speed:
        car.speed = min(target, car.speed + CYCLIST_ACCEL_MPS2 * dt)
    else:
        need = (car.speed - target) / dt
        car.speed = max(target, car.speed - min(CYCLIST_EMERGENCY_BRAKE_MPS2, max(CYCLIST_BRAKE_MPS2, need)) * dt)
    max_yaw = (abs(car.speed) / CYCLIST_MIN_TURN_RADIUS_M if car.speed > 0.5 else 0.8) * dt
    car.heading += max(-max_yaw, min(max_yaw, angle_diff(aim, car.heading)))
    car.x += math.cos(car.heading) * car.speed * dt
    car.y += math.sin(car.heading) * car.speed * dt
    car.layer = getattr(way, "layer", 0)
    vehicle.state = NPCState.WAITING if car.speed < 0.2 and target < 0.2 else NPCState.CRUISING
    vehicle.debug_waiting_for = reason if vehicle.state == NPCState.WAITING else ""

    if lawful_wait or car.speed > 0.5:
        driver.stuck_timer_s = 0.0
    else:
        driver.stuck_timer_s += dt
        if driver.stuck_timer_s >= CYCLIST_STUCK_TIMEOUT_S:
            driver.stuck_timer_s = 0.0
            return "stuck"
    return None


CYCLIST_SPAWN_NODE_TRIES = 4
CYCLIST_DESTINATION_TRIES = 4
CYCLIST_SPAWN_CLEARANCE_M = 6.0
CYCLIST_SPAWN_RING_M = (60.0, 250.0)  # around the taxi when there is no active area (headless/legacy)


def _graph_nodes_in(graph, bounds):
    from .traffic_world import _ROUTE_NODE_GRID_CELL_M as cell
    for cx in range(math.floor(bounds[0] / cell), math.floor(bounds[2] / cell) + 1):
        for cy in range(math.floor(bounds[1] / cell), math.floor(bounds[3] / cell) + 1):
            yield graph.node_grid.get((cx, cy), ())


def cycle_trip_steps(graph, start, spatial_grid, width_m: float, rng=random, destination=None):
    """Plan a cyclist's trip from `start` (a cycle-graph node point) to
    `destination` or a random reachable node CYCLIST_TRIP_DISTANCE_M away,
    as a resumable job: returns a CycleRoute or None. Rides only network
    edges (route_legs), each leg on its riding line (offset_route)."""
    from .traffic_world import _component_root, graph_route_steps
    nodes = graph.nodes
    start_index = next((i for cell in _graph_nodes_in(graph, (start[0], start[1], start[0], start[1])) for i in cell
                        if math.hypot(nodes[i][0] - start[0], nodes[i][1] - start[1]) < 0.5), None)
    if start_index is None:
        return None
    root = _component_root(graph.component_parent, start_index)
    low, high = CYCLIST_TRIP_DISTANCE_M
    for _ in range(CYCLIST_DESTINATION_TRIES if destination is None else 1):
        target = destination
        if target is None:
            angle, distance = rng.uniform(0, 2 * math.pi), rng.uniform(low, high)
            px, py = start[0] + math.cos(angle) * distance, start[1] + math.sin(angle) * distance
            candidates = [i for cell in _graph_nodes_in(graph, (px - 60, py - 60, px + 60, py + 60)) for i in cell
                          if _component_root(graph.component_parent, i) == root]
            yield
            if not candidates:
                continue
            target = nodes[min(candidates, key=lambda i: (nodes[i][0] - px) ** 2 + (nodes[i][1] - py) ** 2)][:2]
        points = yield from graph_route_steps(graph, start, target)
        legs = route_legs(graph, points) if points is not None else None
        if legs is None:
            continue
        clean, ways = legs
        line = offset_route(clean, ways, width_m)
        ride_points = [(x, y) for x, y, _ in line]
        cum = [0.0]
        for a, b in zip(ride_points, ride_points[1:]):
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        if cum[-1] < 30.0:
            continue
        entries = yield from path_entry_points_steps(ride_points, ways, cum, spatial_grid)
        return CycleRoute(ride_points, ways, entries, draw_cruise_speed(rng))
    return None


def cycle_spawn_steps(graph, focus, active_bounds, viewport_bounds, occupied, spatial_grid, width_m: float, rng=random):
    """Where a new cyclist enters: a cycle-graph node in the active area but
    out of view and clear of other traffic, with a planned trip. Resumable;
    returns CycleRoute or None (nothing created yet)."""
    from .viewport import in_bounds
    if not graph.nodes:
        return None
    nodes = graph.nodes
    if active_bounds is not None:
        area = active_bounds
    else:
        reach = CYCLIST_SPAWN_RING_M[1]
        area = (focus[0] - reach, focus[1] - reach, focus[0] + reach, focus[1] + reach)
    ring = []
    for cell in _graph_nodes_in(graph, area):
        yield
        for index in cell:
            x, y = nodes[index][0], nodes[index][1]
            if active_bounds is not None:
                if in_bounds(active_bounds, x, y):
                    ring.append(index)
            elif CYCLIST_SPAWN_RING_M[0] ** 2 <= (x - focus[0]) ** 2 + (y - focus[1]) ** 2 <= CYCLIST_SPAWN_RING_M[1] ** 2:
                ring.append(index)
    rng.shuffle(ring)
    tries = 0
    for index in ring:
        yield
        x, y = nodes[index][0], nodes[index][1]
        if viewport_bounds is not None and in_bounds(viewport_bounds, x, y, 3.0):
            continue
        if occupied((x, y)):
            continue
        tries += 1
        route = yield from cycle_trip_steps(graph, (x, y), spatial_grid, width_m, rng)
        if route is not None:
            return route
        if tries >= CYCLIST_SPAWN_NODE_TRIES:
            break
    return None
