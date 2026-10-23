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
CYCLIST_ACCEL_MPS2 = 0.8
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
