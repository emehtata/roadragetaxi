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

import collections
import itertools
import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .activities import ActivityInstance, ActivityLocation
from .geo import angle_diff, boxes_intersect, clamp, closest_point_and_dist_to_segment, point_in_polygon, segment_distance
from .osm import Curb, ParkingSpace, Way
from .physics import GRAVITY_MPS2, Car, SpatialWayGrid, update_car_physics
from .residents import Household, HouseholdManager, ResidentManager
from .traffic_rules import TrafficAction, TrafficDecision, decide_traffic_action, nearest_vehicle_ahead
from .traffic_world import _ROUTE_NODE_GRID_CELL_M, RouteSteps, TrafficWorld, run_route_steps
from .vehicles.base import VEHICLE_DEFINITIONS, vehicle_definition


class NPCState:
    """Vehicle state machine (NPC-001 section 10).

    The architecture must support future states without rework, but
    NPC-001 only implemented a subset originally; NPC-004 adds the two it
    reserved by name (CRASHED, and REVERSING in place of the more generic
    DISABLED) - DRIVER_EXITED/ABANDONED/DESPAWNING still aren't needed as
    separate states: "driver exited" is NPCVehicle.driver_departed (an
    orthogonal flag, not a motion state - the vehicle can be CRASHED with
    or without a departed driver for one frame), and DESPAWNING is a
    one-shot removal with nothing to observe mid-way, same reasoning
    NPC-003 v2's README already gives for not adding it either.
    """
    SPAWNING = "SPAWNING"
    CRUISING = "CRUISING"
    APPROACHING_INTERSECTION = "APPROACHING_INTERSECTION"
    WAITING = "WAITING"
    TURNING = "TURNING"
    PARKING = "PARKING"  # final approach into a dedicated parking space (NPC-more.md section 14)
    ARRIVING = "ARRIVING"
    PARKED = "PARKED"  # stopped and settled at the destination (multi-passenger-car.md section 17)
    REVERSING = "REVERSING"  # NPC-004: controlled backing-up during stuck recovery
    CRASHED = "CRASHED"  # NPC-004: stopped after an actual collision, driver may have departed


class NPCAvailability:
    """NPC-003 section 7: whether unrelated logic may claim this vehicle.

    Orthogonal to NPCState (which describes physical motion - parked vs
    driving vs turning). Only meaningful for a household vehicle
    (`NPCVehicle.vehicle_kind == "household"`) - a generic traffic vehicle
    has no owner to reserve it for, so it stays AVAILABLE by convention
    even while driving. "A vehicle reserved for a household trip must not
    be selected by unrelated traffic logic" (section 7) becomes a real,
    checkable field a future Resident-trip system can test, not a name
    search - see reserve_household_vehicle/release_household_vehicle.
    """
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"


WAYPOINT_REACH_RADIUS_M = 4.0
# Tighter than WAYPOINT_REACH_RADIUS_M (used for cruising through an
# ordinary mid-route waypoint, where a few meters of slack doesn't
# matter): reported bug - considering the NPC "arrived" from up to
# WAYPOINT_REACH_RADIUS_M away let it settle anywhere within that whole
# circle, bigger than the yard/building clearance offset itself
# (NPC_BUILDING_YARD_CLEARANCE_M), so it could stop still partly on the
# service road/driveway instead of actually reaching the yard point.
NPC_ARRIVAL_RADIUS_M = 1.5
INTERSECTION_APPROACH_RADIUS_M = 25.0
CORNER_ANGLE_THRESHOLD_DEG = 20.0
CORNER_RADIUS_M = 6.0
CORNER_SAMPLE_COUNT = 5
STEER_FULL_ANGLE_DEG = 25.0  # heading error at/beyond which steering saturates at full lock
NPC_PATH_LOOKAHEAD_BASE_M = 4.0
NPC_PATH_LOOKAHEAD_TIME_S = 0.65
NPC_PATH_LOOKAHEAD_MIN_M = 4.0
NPC_PATH_LOOKAHEAD_MAX_M = 18.0
NPC_STEERING_RESPONSE_PER_S = 5.0
ARRIVAL_DECEL_MPS2 = 3.0  # comfortable braking rate approaching the final destination waypoint
# Start arrival braking once the destination is this close (straight line):
# covers the braking distance from any NPC road speed (~70 m at 20 m/s).
NPC_ARRIVAL_BRAKING_HORIZON_M = 80.0
NPC_FOOTPRINT_VIOLATION_CRAWL_MPS = 2.0  # never a hard 0 - see update_npc's live footprint check
NPC_LIVE_FOOTPRINT_CLEARANCE_M = 0.05  # a hair's width - only an actual overlap counts live, not lag
# NPC-003: is_vehicle_pose_valid's curb/building scan costs ~1-2ms against
# real dense OSM data (measured: real Oulu data, ~13 nearby curbs/
# buildings per query even with a small grid cell size - candidate count
# is genuine local density, not a grid-tuning artifact). Harmless at the
# single always-on NPC-001 car; with NPC-003's real population, several
# vehicles can be driving at once and this was the dominant per-frame
# cost (profiled: 5 concurrently-driving vehicles added ~9ms/frame, this
# check alone accounting for ~98% of it). It's a rare-trip physics-drift
# safety net, not a per-frame correctness requirement, so it runs at a
# reduced rate instead of every frame; a stale WAITING/crawl decision for
# up to this long is invisible in practice.
NPC_FOOTPRINT_CHECK_INTERVAL_S = 0.2
# A parking-lot/building-yard/roadside candidate is a single fixed point
# derived purely from the target building/lot/road geometry (unlike a
# dedicated ParkingSpace, which is its own distinct polygon and gets
# marked occupied) - two different vehicles independently routed toward
# the same lot/yard/road point land on the exact same coordinates and
# park on top of each other (reported: cars parking on each other after
# driving a real multi-hop trip, not just during initial population
# fill - _pick_npc_destination_candidates never checked candidates
# against currently-parked vehicles, only dedicated spaces' own occupied/
# reserved flags). Applied to every tier (not just lot/yard) for the same
# reason NPCVehicleManager._place_one already checks it for initial
# population placement - roughly a car's length.
NPC_MIN_VEHICLE_SPACING_M = 7.0

# NPC-004 section 2: vehicle-following avoidance. Mirrors
# nearest_traffic_light_ahead's own forward-cone shape (detection distance/
# lateral limit), just narrower laterally since a vehicle occupies one lane,
# not a whole intersection approach.
NPC_AVOIDANCE_DETECTION_DISTANCE_M = 30.0
NPC_AVOIDANCE_LATERAL_LIMIT_M = 2.5
NPC_AVOIDANCE_DECEL_MPS2 = 3.0  # comfortable following-distance braking rate, same order as corner/arrival braking
NPC_AVOIDANCE_MIN_GAP_M = 2.0  # bumper-to-bumper gap kept from a stopped vehicle ahead

# NPC-005: Road Rage. Wider than NPC_AVOIDANCE_*'s own strict single-lane
# cone (a horn should plausibly affect a car slightly off to the side,
# not just one dead ahead in exactly the same lane) but the same
# nearest_vehicle_ahead forward-cone projection - only the single
# nearest driving vehicle ahead reacts; any queue behind it is the
# existing NPC-004 avoidance logic reacting to *that* vehicle slowing
# down, not scripted - see trigger_road_rage's docstring.
NPC_ROAD_RAGE_DETECTION_DISTANCE_M = 40.0
NPC_ROAD_RAGE_LATERAL_LIMIT_M = 6.0
NPC_ROAD_RAGE_REACTION_DURATION_S = 8.0
NPC_ROAD_RAGE_YIELD_SPEED_MPS = 1.5  # a slow, visible crawl - not a hard stop (see update_npc's own footprint-crawl precedent for why never 0)

# NPC-004 section 3/8: stuck detection. Checked on the same throttled-cache
# cadence as the footprint check (NPC_FOOTPRINT_CHECK_INTERVAL_S) rather
# than every frame - this is a recovery safety net, not a per-frame
# correctness requirement.
NPC_STUCK_CHECK_INTERVAL_S = 1.0
NPC_STUCK_MIN_PROGRESS_M = 2.0  # real displacement expected per check interval when actually driving
NPC_STUCK_TIMEOUT_S = 8.0  # accumulated stuck time before recovery triggers

# NPC-004 section 6/7: reverse recovery. A short, straight, controlled
# back-up - not a reverse-parking maneuver - just enough to clear whatever
# was blocking forward progress before re-routing.
NPC_REVERSE_DISTANCE_M = 6.0
NPC_REVERSE_SPEED_MPS = 2.5
NPC_REVERSE_CLEARANCE_CHECK_RADIUS_M = 6.0

NPC_CORNER_COMFORT_LATERAL_G = 0.5  # a comfortable cornering effort, well under GRIP.md's max_grip_g limit
NPC_CORNER_BRAKING_DECEL_MPS2 = 3.0  # comfortable braking rate approaching a corner
NPC_TURN_SIGNAL_MIN_DISTANCE_M = 30.0  # start blinking at least this far before a turn...
NPC_TURN_SIGNAL_LEAD_S = 3.0  # ...or this many seconds of travel ahead, whichever is farther
NPC_CORNER_LOOKAHEAD_M = 40.0  # how far ahead to start braking for an upcoming turn
LANE_BIAS_LOOKAHEAD_M = 20.0  # start easing into a turn lane this far before the corner (NPC-002 section 5)
# NPC-003 v2: the "car" vehicle plugin (vehicles/plugins/car.py) is now the
# canonical source for these three values - derived here, once, at import
# time, so every existing call site in this module and in tests keeps
# working unchanged. vehicles/ never imports npc.py (one-directional, same
# as activities/ never importing pedestrian.py), so this is a safe,
# non-circular import.
_car_plugin_definition = VEHICLE_DEFINITIONS["car"]
NPC_VEHICLE_LENGTH_M = _car_plugin_definition.length_m  # the default NPC car's dimensions - shared so footprint checks always match the spawned Car
NPC_VEHICLE_WIDTH_M = _car_plugin_definition.width_m

# multi-passenger-car.md section 2: capacity lives in one constant, never a
# hardcoded literal in passenger-management logic.
NPC_CAR_CAPACITY = _car_plugin_definition.capacity
# NPC-003 v2: real-world-ish car body color distribution (roughly ordered
# by actual new-car popularity - white/black/gray/silver dominate, with a
# handful of real accent colors) - every NPC vehicle used to be the exact
# same flat gray (reported: "cars must have variety of colors").
NPC_VEHICLE_COLORS = [
    (245, 245, 245),  # white
    (30, 30, 32),  # black
    (120, 122, 126),  # gray
    (188, 190, 194),  # silver
    (150, 155, 165),  # the old flat default, kept in the mix
    (60, 65, 110),  # dark blue
    (130, 20, 25),  # dark red
    (35, 70, 45),  # dark green
    (90, 55, 25),  # brown
    (205, 60, 50),  # red
]
# How long a trip group spends inside a building (section 13) - randomized
# per group, using the simulation clock (sim_time), not wall-clock time.
NPC_BUILDING_VISIT_MIN_S = 20.0
NPC_BUILDING_VISIT_MAX_S = 90.0
# Section 20: once parked, how much extra time beyond the group's own
# activity_duration_s a straggler gets before the vehicle leaves without
# them - generous enough to cover a slower walk back, not infinite.
NPC_GROUP_RETURN_GRACE_S = 60.0
# Section 13/14: what a trip group is doing inside the building - shared
# by the whole group for now (section 14 explicitly allows this), not
# yet an individual per-passenger choice.
NPC_TRIP_ACTIVITY_TYPES = ("shopping", "work", "visit", "service", "errand", "other")

# NPC-003: population management (NPCVehicleManager). Mirrors
# pedestrian.py's PedestrianManager population-tick constants (same
# staggered spawn/despawn pattern, just car-scale radii - a car is
# relevant to the player from farther away than a pedestrian is).
NPC_VEHICLE_SPAWN_RADIUS_M = 250.0
NPC_VEHICLE_DESPAWN_RADIUS_M = 350.0
NPC_SPAWN_RADIUS_SLACK_M = 50.0
# LOD cutoff (section 17): only vehicles this close get update_npc called
# at all each frame. A parked vehicle already needs zero physics until it
# decides to move, so this mostly matters for a driving vehicle that
# wanders far from the player - not a multi-tier LOD system (section 17
# itself says avoid one unless necessary).
NPC_VEHICLE_SIMULATION_RADIUS_M = 400.0
NPC_POPULATION_TICK_S = 2.0  # traffic must replenish before a moving player outruns the spawn ring
NPC_POPULATION_SPAWN_LIMIT_PER_TICK = 3  # staggered, never a burst (section 19, 23)
# Section 9: fraction of currently-idle-parked vehicles that roll to start
# a new trip on each population tick - a tunable rate standing in for a
# hardcoded parked/driving ratio.
NPC_TRIP_START_PROBABILITY_PER_TICK = 0.08
# At most this many vehicles actually attempt to start a trip per tick,
# regardless of how many rolled true above - find_and_start_npc_trip's own
# search (TrafficWorld.plan_route + curb/building footprint validation
# across several candidates) measured up to several *seconds* for a single
# vehicle against a real, dense city extract (Oulu) - occasional outliers
# past 30s, not a cost this project's own plan_route was ever exercised at
# repeatedly before (every prior caller ran it once, at game/tile-load
# time). Capping attempts per tick - not just per-vehicle search width
# below - bounds the worst-case per-frame spike regardless of how any one
# attempt happens to cost; a vehicle that doesn't get a turn this tick
# simply tries again next tick, no different from any other "don't get
# stuck on one candidate" fallback in this module.
NPC_TRIP_START_ATTEMPTS_PER_TICK = 1
# NPC-005: the flat probability/attempts-cap pair above has no idea how
# many vehicles are *currently driving* - with the default 8%-per-idle-
# vehicle roll and only 1 real attempt per 5s tick, the steady-state
# driving count settles far below target_count regardless of population
# size, which is exactly the reported "roads full of parked cars" bug.
# When the population is under its moving-traffic target, double (not
# more - see NPC_TRIP_START_ATTEMPTS_PER_TICK's own comment above about
# a single attempt occasionally costing seconds against real dense OSM
# data) the attempts allowed this tick, so idle vehicles actually get
# pulled out onto the road instead of the cap silently discarding
# everyone but the first one that rolled true.
NPC_TRIP_START_ATTEMPTS_PER_TICK_WHEN_BELOW_MOVING_TARGET = 4
# Failed candidates are temporarily skipped so an impossible driveway cannot
# consume every population tick. They remain eligible later: a streamed map or
# changed parking occupancy can make a formerly impossible trip valid.
NPC_TRIP_RETRY_MAX_TICKS = 4
# Moving traffic ("transit") spawns on a road node in this annulus around
# the player - inside the simulation radius so it actually runs, outside the
# spawn/visible area so it drives into view instead of popping into it.
NPC_TRANSIT_SPAWN_MIN_DISTANCE_M = 110.0
NPC_TRANSIT_SPAWN_MAX_DISTANCE_M = 220.0
NPC_TRANSIT_SPAWN_NODE_TRIES = 6
NPC_TRANSIT_TRIP_MIN_DISTANCE_M = 60.0
NPC_TRANSIT_TRIP_MAX_DISTANCE_M = 220.0
NPC_TRANSIT_SPAWNS_PER_TICK = 2
# Route validation is ~45ms per candidate on dense real data: keep one
# spawn attempt to a few candidates so it cannot stall a frame for seconds.
NPC_TRANSIT_SPAWN_TIME_BUDGET_S = 0.1
# One wall-clock budget for ALL trip-start/transit-spawn route searching in a
# single population tick (each attempt alone may run several validations).
# ponytail: too small for a typical Oulu route plan+validation (~25 ms
# median, A* up to ~120 ms), so trip starts mostly fail; raising it causes
# 100-280 ms frame spikes. Needs incremental/background route planning.
NPC_TRIP_START_TICK_BUDGET_S = 0.008
# bin-loader-v12: trip starts and transit spawns are route *jobs* - queued by
# the population tick, advanced every frame round-robin within this budget,
# each job getting up to NPC_ROUTE_JOB_SLICE_S before the next one's turn.
# Time, not a step count: a search step costs microseconds but one footprint
# validation sample can cost milliseconds (a 64-step slice measured ~9 ms
# per frame); a perf_counter() read per step is negligible next to either.
NPC_ROUTE_JOB_BUDGET_S = 0.002
NPC_ROUTE_JOB_SLICE_S = 0.0005
NPC_MAX_ROUTE_JOBS = 8
# Open road required around a spawn point so a new car is never dropped onto
# (or right behind) existing traffic.
NPC_TRANSIT_SPAWN_CLEARANCE_M = 30.0
# Default fraction of the vehicle population that should be actively
# driving at any moment, independent of total population size (client-
# server-016.md/NPC-005: moving traffic is a first-class target, not a
# side effect of the total-population target).
NPC_TARGET_MOVING_FRACTION = 0.5
# NPC-003 v2: continue_npc_trip (an already-driving vehicle picking its
# *next* destination once its passengers have reboarded) shares
# find_and_start_npc_trip's exact same plan_route cost profile - measured
# over a second per call against real dense OSM data even to succeed once.
# Deliberately called only from here, never from the per-frame update()
# loop the instant a vehicle parks (see _handle_parked_vehicle's own
# docstring) - same "bound attempts per tick, not just search width"
# discipline as NPC_TRIP_START_ATTEMPTS_PER_TICK, so several vehicles
# reboarding in the same tick can't stack into one multi-second frame.
NPC_CONTINUE_TRIP_ATTEMPTS_PER_TICK = 1
NPC_CONTINUE_TRIP_TIME_BUDGET_S = 0.1
# NPC-004: recovery reroute attempts for STUCK vehicles - same one-
# expensive-plan_route-call-per-tick discipline as the two constants above.
NPC_RECOVERY_ATTEMPTS_PER_TICK = 1
# find_and_start_npc_trip's own BFS search width - deliberately much
# smaller than spawn_deterministic_npc's NPC_DESTINATION_CANDIDATE_LIMIT
# (40), which is a one-time, loading-screen-time cost for the game's
# original single vehicle, not a recurring per-tick one across a whole
# population.
NPC_TRIP_START_CANDIDATE_POINTS = 4
# Hard wall-clock ceiling on one find_and_start_npc_trip call, on top of
# the candidate-count cap above - TrafficWorld.plan_route's own A* search
# measured highly variable per-call cost against a real, dense city graph
# (Oulu: most calls under 0.5s, occasional outliers past several seconds
# even at the smaller NPC_TRIP_START_CANDIDATE_POINTS width). A count cap
# alone doesn't bound a single unusually expensive plan_route call; this
# does. Rewriting plan_route's own performance is out of scope here (a
# separate, pre-existing system - see NPC-003 section 1's "do not
# duplicate/rewrite the traffic manager").
NPC_TRIP_START_TIME_BUDGET_S = 0.5
# Section 13: fraction of the population that gets a household (and thus
# a home to return to) rather than being a plain autonomous TRAFFIC_VEHICLE.
NPC_HOUSEHOLD_VEHICLE_FRACTION = 0.3
# NPC-003 v2 section 9: chance a new household-eligible vehicle joins an
# existing household that still owns fewer than 2 vehicles, instead of
# always founding a brand new one-vehicle household. Not spatial (a real
# household's second car isn't always parked next to the first either) -
# deliberately simple, per the spec's own "the exact ownership model can
# initially be simple".
NPC_SECOND_HOUSEHOLD_VEHICLE_PROBABILITY = 0.15
NPC_MAX_VEHICLES_PER_HOUSEHOLD = 2

_trip_group_id_counter = itertools.count(1)


@dataclass
class PathPoint:
    x: float
    y: float
    way: Optional[Way] = None
    is_turn: bool = False
    maneuver: Optional[str] = None  # "left" | "right", set on a turn's sampled points
    lane_bias: Optional[str] = None  # "left" | "right" | None, which lane this point was placed in


def _lane_offset_point(
    way: Optional[Way], x: float, y: float, heading: float, vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
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
    cruise_offset = min(max(1.2, half_width * 0.45), max_offset)
    if maneuver == "right":
        # Toward the curb, but never onto it: the body used to touch the
        # road edge exactly, so wherever a kerb is mapped there every
        # route with a right turn failed route_crosses_curbs (measured on
        # Oulu: 98% of otherwise valid trips rejected - no moving traffic).
        lane_offset = max(cruise_offset, max_offset - NPC_RIGHT_TURN_EDGE_MARGIN_M)
    elif maneuver == "left":
        lane_offset = min(1.0, max_offset)
    else:
        lane_offset = cruise_offset
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


NPC_PARKING_ACCESS_TOLERANCE_M = MAX_ROUTE_OFFROAD_TOLERANCE_M
NPC_PARKING_APPROACH_DISTANCE_M = 6.0  # how far out the orientation-aligned approach point sits
NPC_OFFROAD_APPROACH_SPEED_MPS = 10.0 / 3.6  # walking-area/yard pace, never road speed


def _parking_space_axis(parking_space) -> Optional[float]:
    """The direction a car parked in this space should point along: the
    explicit orientation tag if one resolved to a real angle, otherwise
    the space polygon's own longest-edge axis - NPC-more.md section 15's
    own fallback ("choose a sensible heading based on... parking-area
    geometry") for the common case, since most real OSM parking spaces
    carry no orientation tag at all (ParkingSpace.orientation then stays
    None - see its own __post_init__, which only derives this axis when
    an orientation tag was actually present to resolve)."""
    orientation = getattr(parking_space, "orientation", None)
    if isinstance(orientation, (int, float)):
        return float(orientation)
    points = getattr(parking_space, "points_m", None) or []
    if len(points) < 2:
        return None
    longest_edge = max(
        zip(points, points[1:] + points[:1]),
        key=lambda edge: (edge[1][0] - edge[0][0]) ** 2 + (edge[1][1] - edge[0][1]) ** 2,
    )
    return math.atan2(longest_edge[1][1] - longest_edge[0][1], longest_edge[1][0] - longest_edge[0][0])


def _align_approach_to_parking_orientation(
    route_points: List[Tuple[float, float]],
    parking_space,
    approach_distance_m: float = NPC_PARKING_APPROACH_DISTANCE_M,
) -> List[Tuple[float, float]]:
    """Insert one waypoint just before the destination so the vehicle's
    final heading approaches along the parking space's own orientation
    axis (NPC-more.md section 15) instead of whatever direction the
    route's last real road segment happened to point.

    Picks whichever of the axis's two directions is closer to the
    route's own natural final approach heading, so this never forces an
    unnecessary U-turn just to face "the other way" along the same line.
    A no-op (returns route_points unchanged) when there's no parking
    space, no usable geometry to derive an axis from, or the route is too
    short to have a "final approach" at all.
    """
    orientation = _parking_space_axis(parking_space) if parking_space is not None else None
    if orientation is None or len(route_points) < 2:
        return route_points
    destination = route_points[-1]
    prev = route_points[-2]
    natural_heading = math.atan2(destination[1] - prev[1], destination[0] - prev[0])
    heading = min(
        (orientation, orientation + math.pi),
        key=lambda h: abs(angle_diff(h, natural_heading)),
    )
    approach_point = (
        destination[0] - math.cos(heading) * approach_distance_m,
        destination[1] - math.sin(heading) * approach_distance_m,
    )
    return route_points[:-1] + [approach_point, destination]


def _distance_to_nearest_road(
    spatial_grid: SpatialWayGrid, x: float, y: float, radius_m: float,
) -> float:
    """Distance from (x, y) to the nearest drivable way centerline within
    radius_m, or inf if none - the bounded, grid-backed counterpart of
    _way_at_point's linear-scan distance."""
    best = float("inf")
    for way in spatial_grid.ways_in_rect(x - radius_m, y - radius_m, x + radius_m, y + radius_m):
        if not getattr(way, "is_drivable", True):
            continue
        for (ax, ay), (bx, by) in zip(way.points_m, way.points_m[1:]):
            dx, dy = bx - ax, by - ay
            length_sq = dx * dx + dy * dy
            t = 0.0 if length_sq < 1e-9 else clamp(((x - ax) * dx + (y - ay) * dy) / length_sq, 0.0, 1.0)
            best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best


def route_stays_on_road(
    points: List[Tuple[float, float]],
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    tolerance_m: float = MAX_ROUTE_OFFROAD_TOLERANCE_M,
    final_segment_tolerance_m: Optional[float] = None,
    final_segment_count: int = 1,
    initial_segment_tolerance_m: Optional[float] = None,
    initial_segment_count: int = 1,
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

    final_segment_tolerance_m, when given, applies to the last
    final_segment_count segments (road -> the actual destination, or
    road -> an inserted parking-orientation approach point -> the
    destination - see _align_approach_to_parking_orientation) instead of
    `tolerance_m` - a real yard/driveway can legitimately sit farther from
    the road, but must remain tightly bounded so it cannot become a
    cross-lawn shortcut (NPC-more.md section 6's "safe driveway or
    building courtyard"). initial_segment_tolerance_m is the same idea mirrored at
    the *start* (NPC-003: a vehicle departing from an off-road parked
    position - see start_npc_trip's origin_is_off_road).
    """
    return run_route_steps(_route_stays_on_road_steps(
        points, ways, spatial_grid, tolerance_m, final_segment_tolerance_m, final_segment_count,
        initial_segment_tolerance_m, initial_segment_count,
    ))


def _route_stays_on_road_steps(
    points, ways, spatial_grid, tolerance_m, final_segment_tolerance_m, final_segment_count,
    initial_segment_tolerance_m, initial_segment_count,
) -> RouteSteps:
    """route_stays_on_road as a resumable job (yields per segment)."""
    segment_count = len(points) - 1
    for i in range(segment_count):
        yield
        (ax, ay), (bx, by) = points[i], points[i + 1]
        mid_x, mid_y = (ax + bx) / 2.0, (ay + by) / 2.0
        _, distance = _way_at_point(spatial_grid, ways, mid_x, mid_y)
        if initial_segment_tolerance_m is not None and i < initial_segment_count:
            segment_tolerance = initial_segment_tolerance_m
        elif final_segment_tolerance_m is not None and i >= segment_count - final_segment_count:
            segment_tolerance = final_segment_tolerance_m
        else:
            segment_tolerance = tolerance_m
        if distance == float("inf") and spatial_grid is not None:
            # _way_at_point's grid path only says "on a road or not"; the
            # tolerances above (a lot/yard hop legitimately sits well off
            # any road) need a real distance, or every off-road first/last
            # hop is rejected no matter how generous the tolerance is.
            distance = _distance_to_nearest_road(spatial_grid, mid_x, mid_y, segment_tolerance)
        if distance > segment_tolerance:
            return False
    return True


CURB_CLEARANCE_MARGIN_M = 0.3  # a little slack beyond the bare vehicle body
NPC_RIGHT_TURN_EDGE_MARGIN_M = CURB_CLEARANCE_MARGIN_M + 0.5  # right-turn lane bias stops this far from the road edge
BUILDING_CLEARANCE_MARGIN_M = 0.3  # a little slack beyond the bare vehicle body
FOOTPRINT_SAMPLE_SPACING_M = 5.0  # densify straight stretches this finely before sampling


def _vehicle_footprint_corners(
    cx: float, cy: float, heading: float, length_m: float, width_m: float,
) -> List[Tuple[float, float]]:
    """The four corners of the vehicle's actual oriented rectangle
    centered at (cx, cy) facing `heading` - NPC-more.md section 8: a
    footprint check must account for length, heading and front/rear
    overhang, not only width."""
    fx, fy = math.cos(heading), math.sin(heading)
    rx, ry = -fy, fx
    half_length, half_width = length_m * 0.5, width_m * 0.5
    return [
        (cx + fx * half_length + rx * half_width, cy + fy * half_length + ry * half_width),
        (cx + fx * half_length - rx * half_width, cy + fy * half_length - ry * half_width),
        (cx - fx * half_length - rx * half_width, cy - fy * half_length - ry * half_width),
        (cx - fx * half_length + rx * half_width, cy - fy * half_length + ry * half_width),
    ]


def is_vehicle_pose_valid(
    x: float,
    y: float,
    heading: float,
    curbs: Optional[List[Curb]] = None,
    buildings: Optional[List] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    length_m: float = NPC_VEHICLE_LENGTH_M,
    width_m: float = NPC_VEHICLE_WIDTH_M,
    clearance_m: float = CURB_CLEARANCE_MARGIN_M,
) -> bool:
    """NPC-more.md section 19: the one central validator - "is the
    vehicle's complete oriented footprint here clear of curbs and
    buildings" - reused both to validate a whole planned route before
    ever spawning (route_crosses_curbs/route_crosses_buildings sample a
    path through this) and, every frame, the vehicle's actual live pose
    (update_npc) - so drift between the one-time route validation and
    where the vehicle's physics actually puts it (steering smoothing/lag)
    can't silently plow through a wall or curb unnoticed.

    Curbs are open lines (checked edge to edge); buildings are closed
    polygons (the edge closing the last point back to the first is
    checked too, since a route entering or leaving a footprint has to
    cross that boundary somewhere).
    """
    if not curbs and not buildings:
        return True
    corners = _vehicle_footprint_corners(x, y, heading, length_m, width_m)
    corner_edges = list(zip(corners, corners[1:] + corners[:1]))
    half_diag = math.hypot(length_m, width_m) * 0.5 + clearance_m
    for obstacles, grid, closed in ((curbs, curb_grid, False), (buildings, building_grid, True)):
        if not obstacles:
            continue
        candidates = (
            grid.ways_in_rect(x - half_diag, y - half_diag, x + half_diag, y + half_diag)
            if grid is not None
            else obstacles
        )
        for obstacle in candidates:
            points = obstacle.points_m
            obstacle_edges = zip(points, points[1:] + points[:1]) if closed else zip(points, points[1:])
            for oa, ob in obstacle_edges:
                for ca, cb in corner_edges:
                    if segment_distance(ca, cb, oa, ob) < clearance_m:
                        return False
    return True


def _path_headings(points: List[Tuple[float, float]]) -> List[float]:
    """Heading at each point of a polyline: the incoming segment's own
    heading at the ends, the circular mean of the incoming and outgoing
    segments' headings (via vector sum, so it never mishandles the
    wraparound a plain angle average would) at every interior point."""
    n = len(points)
    if n < 2:
        return [0.0] * n
    segment_heading = [
        math.atan2(points[i + 1][1] - points[i][1], points[i + 1][0] - points[i][0]) for i in range(n - 1)
    ]
    headings = [segment_heading[0]]
    for i in range(1, n - 1):
        h1, h2 = segment_heading[i - 1], segment_heading[i]
        headings.append(math.atan2(math.sin(h1) + math.sin(h2), math.cos(h1) + math.cos(h2)))
    headings.append(segment_heading[-1])
    return headings


def _densify_path(
    points: List[Tuple[float, float]], max_spacing_m: float = FOOTPRINT_SAMPLE_SPACING_M,
) -> List[Tuple[float, float]]:
    """Insert extra points along any stretch longer than max_spacing_m so
    a per-point footprint sample (see is_vehicle_pose_valid) can't skip
    over an obstacle sitting between two widely-spaced path points - a
    corner's own points (_round_corner) are already dense near turns,
    this only matters for long straight segments."""
    if len(points) < 2:
        return list(points)
    dense = [points[0]]
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        length = math.hypot(bx - ax, by - ay)
        steps = max(1, int(length // max_spacing_m))
        for step in range(1, steps + 1):
            t = step / steps
            dense.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return dense


def _route_crosses_obstacles(
    path_points: List[Tuple[float, float]],
    length_m: float,
    width_m: float,
    clearance_m: float,
    curbs: Optional[List[Curb]] = None,
    buildings: Optional[List] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    skip_leading_m: float = 0.0,
    skip_trailing_m: float = 0.0,
) -> bool:
    """Sample is_vehicle_pose_valid densely along a whole path (see
    _densify_path/_path_headings) - the shared engine behind
    route_crosses_curbs and route_crosses_buildings.

    skip_leading_m (NPC-003: departing from an off-road parked position -
    see start_npc_trip's origin_is_off_road) skips this much distance from
    the very start of the path before sampling begins - the same
    reasoning _align_approach_to_parking_orientation/destination_is_off_
    road already applies at the *destination* end (a real yard/driveway
    can legitimately sit close to/cross a curb cut that a normal mid-route
    straight line never would), mirrored at the origin: a vehicle that
    starts parked in a yard/lot has to cross its own curb cut to leave.
    skip_trailing_m is the matching arrival allowance: generated house
    parking records its driveway mouth, so only that final access leg may
    cross the roadside curb into the yard.
    """
    return run_route_steps(_route_crosses_obstacles_steps(
        path_points, length_m, width_m, clearance_m, curbs=curbs, buildings=buildings,
        curb_grid=curb_grid, building_grid=building_grid,
        skip_leading_m=skip_leading_m, skip_trailing_m=skip_trailing_m,
    ))


def _route_crosses_obstacles_steps(
    path_points: List[Tuple[float, float]],
    length_m: float,
    width_m: float,
    clearance_m: float,
    curbs: Optional[List[Curb]] = None,
    buildings: Optional[List] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    skip_leading_m: float = 0.0,
    skip_trailing_m: float = 0.0,
) -> RouteSteps:
    """_route_crosses_obstacles as a resumable job (yields per sample)."""
    if len(path_points) < 2 or (not curbs and not buildings):
        return False
    dense = _densify_path(path_points)
    headings = _path_headings(dense)
    total_length = sum(
        math.hypot(bx - ax, by - ay)
        for (ax, ay), (bx, by) in zip(dense, dense[1:])
    )
    traveled = 0.0
    prev_x, prev_y = dense[0]
    for (x, y), heading in zip(dense, headings):
        traveled += math.hypot(x - prev_x, y - prev_y)
        prev_x, prev_y = x, y
        if traveled < skip_leading_m:
            continue
        if total_length - traveled < skip_trailing_m:
            continue
        yield
        if not is_vehicle_pose_valid(
            x, y, heading, curbs=curbs, buildings=buildings, curb_grid=curb_grid, building_grid=building_grid,
            length_m=length_m, width_m=width_m, clearance_m=clearance_m,
        ):
            return True
    return False


def route_crosses_curbs(
    path_points: List[Tuple[float, float]],
    curbs: List[Curb],
    vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
    vehicle_length_m: float = NPC_VEHICLE_LENGTH_M,
    curb_grid: Optional[SpatialWayGrid] = None,
    clearance_m: float = CURB_CLEARANCE_MARGIN_M,
    skip_leading_m: float = 0.0,
    skip_trailing_m: float = 0.0,
) -> bool:
    """Return whether the built (lane-offset, corner-rounded) driving path
    ever brings the vehicle's own oriented footprint within clearance_m
    of a mapped curb line - NPC-more.md section 7's hard rule: never
    drive on curbs.

    Checked against the actual lane-offset/corner-rounded path (the real
    trajectory build_driving_path produces), not the raw centerline
    route - a corner's rounded arc is exactly where a wide vehicle most
    plausibly clips the curb of a tight turn or a roundabout island, and
    the raw centerline wouldn't show that at all.
    """
    return _route_crosses_obstacles(
        path_points, vehicle_length_m, vehicle_width_m, clearance_m, curbs=curbs, curb_grid=curb_grid,
        skip_leading_m=skip_leading_m,
        skip_trailing_m=skip_trailing_m,
    )


def route_crosses_buildings(
    path_points: List[Tuple[float, float]],
    buildings: List,
    vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
    vehicle_length_m: float = NPC_VEHICLE_LENGTH_M,
    building_grid: Optional[SpatialWayGrid] = None,
    clearance_m: float = BUILDING_CLEARANCE_MARGIN_M,
    skip_leading_m: float = 0.0,
    skip_trailing_m: float = 0.0,
) -> bool:
    """Return whether the driving path ever brings the vehicle's own
    oriented footprint within clearance_m of a building's wall -
    NPC-more.md section 13's hard rule: never drive through building
    polygons. Same mechanism as route_crosses_curbs (see
    is_vehicle_pose_valid), just against a closed polygon boundary
    instead of an open curb line - a route that enters or exits a
    building's footprint has to cross that boundary somewhere, so this
    catches "drives across the middle of the lot" too, not only "clips
    the corner"."""
    return _route_crosses_obstacles(
        path_points, vehicle_length_m, vehicle_width_m, clearance_m, buildings=buildings, building_grid=building_grid,
        skip_leading_m=skip_leading_m,
        skip_trailing_m=skip_trailing_m,
    )


def build_driving_path(
    route_points: List[Tuple[float, float]],
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
    corner_radius_m: float = CORNER_RADIUS_M,
    skip_final_lane_offset: bool = False,
) -> List[PathPoint]:
    """Turn a raw centerline route (TrafficWorld.plan_route's output) into
    a lane-correct, corner-smoothed path for an NPC to follow.

    Kept as one function for NPC-001 (one vehicle, no need for a generic
    multi-stage pipeline object yet), but route planning (the caller),
    lane offsetting, and corner rounding remain distinct, independently
    testable steps - see build_driving_path's own helpers.

    skip_final_lane_offset, when set, reaches the very last point exactly
    as given instead of nudging it sideways by lane-offset math meant for
    through-traffic staying in its lane - for a destination that's a
    parking space/lot/building yard point (_pick_npc_destination already
    chose it deliberately, off any road), lane-offsetting it again by an
    unrelated amount in an unrelated direction pushed the NPC's actual
    resting point away from the intended one, in the reported case back
    toward the service road/driveway it approached from. Left False (the
    default) for a destination that's still meant to be reached in-lane -
    a plain point on a road, or the deliberate roadside-parking fallback
    that relies on exactly this offset to hug the curb.
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
        signed_turn = angle_diff(segment_heading[i], segment_heading[i - 1])
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
        if i == n - 1 and skip_final_lane_offset:
            lx, ly = x, y
        else:
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
    # NPC-004 stuck detection (section 3/8): sampled every
    # NPC_STUCK_CHECK_INTERVAL_S: if displacement since the last sample is
    # under NPC_STUCK_MIN_PROGRESS_M, stuck_timer_s accumulates instead of
    # resetting - covers "not moving", "oscillating", and "spinning without
    # progress" alike, since all three fail this same real-displacement
    # test (see update_npc's own comment for why one check suffices).
    stuck_check_position: Optional[Tuple[float, float]] = None
    stuck_check_elapsed_s: float = 0.0
    stuck_timer_s: float = 0.0
    # NORMAL -> REVERSING -> REROUTING -> NORMAL (section 8's recovery
    # sequence) - a plain string, matching every other loosely-typed state
    # field in this module (NPCState/NPCAvailability are the only "real"
    # enums here).
    recovery_stage: str = "NORMAL"
    reverse_start_position: Optional[Tuple[float, float]] = None
    # NPC-005: an orthogonal timed flag, not a new NPCState - matches
    # this module's existing convention of keeping reactive/temporary
    # conditions (driver_departed, recovery_stage) separate from the
    # vehicle's core physical state, since the vehicle keeps being
    # whatever NPCState its speed/position naturally imply while yielding
    # (CRUISING at a crawl, or WAITING if fully stopped) - it never stops
    # being simulated or disappears. None = not currently reacting.
    road_rage_until_sim_time: Optional[float] = None
    # Cached continuous route progress used by the path follower.  Unlike
    # path_index this is a position along a segment, so steering does not
    # jump merely because a waypoint entered a bookkeeping radius.
    route_segment_index: int = 0
    route_segment_t: float = 0.0
    lookahead_distance_m: float = 0.0
    steering_input: float = 0.0
    destination_is_off_road: bool = False

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
class TripGroup:
    """A Resident group travelling together in one NPC vehicle
    (multi-passenger-car.md sections 3-6). Each member remains an
    independent Resident/Pedestrian entity - this only holds what the
    group shares: the vehicle, the destination building entrance, the
    activity, and who is currently aboard.

    `boarded_resident_ids` starts as a full copy of `member_resident_ids`
    (a group in transit is trivially "all aboard"); pedestrian.py removes
    an id when that member disembarks and re-adds it on reboarding, so
    `boarded_resident_ids == set(member_resident_ids)` is exactly the
    section 19 "everyone's back" check - no separate group-state enum is
    needed on top of it, since per-member granularity already lives in
    pedestrian.PedestrianState.
    """
    group_id: int
    vehicle_id: int
    member_resident_ids: List[int]
    destination_entrance: Optional[Tuple[float, float]] = None
    activity_type: str = ""  # section 13/14/26: "shopping"/"work"/... - shared per group for now
    activity_duration_s: float = 0.0
    boarded_resident_ids: Set[int] = field(default_factory=set)
    wait_deadline_sim_time: Optional[float] = None

    @property
    def all_aboard(self) -> bool:
        return self.boarded_resident_ids >= set(self.member_resident_ids)


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
    vehicle_type: str = "car"  # a vehicles/ plugin id (see vehicles/README.md) - never branched on here, only looked up
    color: Tuple[int, int, int] = (150, 155, 165)
    is_taxi: bool = False
    is_police: bool = False
    is_on_foot: bool = False
    fallen: bool = False
    way: Optional[Way] = None
    lod_level: int = 0
    destination: Optional[Tuple[float, float]] = None
    destination_parking_space_id: Optional[int] = None
    reserved_parking_space: object = None  # the actual ParkingSpace object (see spawn_npc) - released in update_npc
    # once this vehicle loses its driver (NPC-more.md section 4: "if the
    # vehicle leaves: release the occupied space"), keyed off the object
    # itself rather than destination_parking_space_id so release never
    # needs a parking_spaces list to search back through.
    travel_route: List[Tuple[float, float]] = field(default_factory=list)
    parking_route: Optional[List] = None
    turn_signal: str = ""
    turn_signal_elapsed: float = 0.0
    debug_waiting_for: str = ""
    crashed_timer: float = 0.0  # NPC-004: seconds since state became CRASHED (debug/despawn timing)
    # NPC-004 section 12/13: once True, this vehicle's driver has
    # permanently left it (accident response) - every place that would
    # otherwise resume/reassign driving on this vehicle (start a new trip,
    # continue a trip, get claimed by reserve_household_vehicle, get
    # re-entered by a pedestrian) must check this first. Never cleared -
    # a departed driver never returns to the same vehicle, by design.
    driver_departed: bool = False
    capacity: int = NPC_CAR_CAPACITY
    trip_group: Optional[TripGroup] = None
    # NPC-003 sections 6, 13: "traffic" (autonomous, no owner, current
    # behavior) or "household" (has a home to return to, reservable).
    vehicle_kind: str = "traffic"
    household_id: Optional[int] = None
    home_position: Optional[Tuple[float, float]] = None
    home_parking_space: object = None  # same shape as reserved_parking_space
    availability: str = NPCAvailability.AVAILABLE
    # NPC-003 section 12: True while this household vehicle's current trip
    # is "drive home" - once it parks, the manager retires the trip
    # outright (no building-visit detour) instead of calling
    # continue_npc_trip again. False for every other leg (including a
    # traffic vehicle's endless errands, which never sets it).
    returning_home: bool = False
    # NPC-003 perf: is_vehicle_pose_valid's live footprint safety net
    # (see NPC_FOOTPRINT_CHECK_INTERVAL_S) runs at a reduced rate, not
    # every frame - this is its own per-vehicle accumulator/cache so a
    # skipped frame reuses the last real result instead of assuming clear.
    # Starts already at the interval (not 0.0) so the very first update_
    # npc call after a vehicle starts driving always performs a real
    # check rather than trusting the default "clear" cache for up to
    # NPC_FOOTPRINT_CHECK_INTERVAL_S first.
    footprint_check_elapsed_s: float = NPC_FOOTPRINT_CHECK_INTERVAL_S
    footprint_check_cached: bool = True

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

    @property
    def passenger_ids(self) -> Tuple[int, ...]:
        """Trip-group members other than the driver (render/pedestrians.py's
        draw_npc_popup already reads this attribute name, built ahead of
        multi-passenger-car.md - "who's riding along" alongside the owner
        it already shows separately)."""
        if self.trip_group is None:
            return ()
        return tuple(rid for rid in self.trip_group.member_resident_ids if rid != self.owner_id)

    @property
    def available_seats(self) -> int:
        """multi-passenger-car.md section 4: capacity minus who's
        currently actually aboard (not the group's full roster, which
        may be partly out visiting a building) - "how many more could
        board this vehicle right now"."""
        occupied = len(self.trip_group.boarded_resident_ids) if self.trip_group is not None else 0
        return max(0, self.capacity - occupied)


def has_active_driver(vehicle: NPCVehicle, resident_manager: ResidentManager) -> bool:
    """The fundamental NPC-001 invariant: moving NPC vehicle == active
    driver Resident. A vehicle whose owning Resident isn't currently
    driving it must never be treated as under power."""
    if vehicle.owner_id is None:
        return False
    resident = resident_manager.get(vehicle.owner_id)
    return resident is not None and resident.active_vehicle_id == vehicle.vehicle_id


def reserve_household_vehicle(vehicle: NPCVehicle) -> bool:
    """NPC-003 section 7: claim a household vehicle for an upcoming trip
    (the future Resident shopping/errand system will call this instead of
    searching for "the nearest NPC car"). Returns False - and reserves
    nothing - if the vehicle isn't a household vehicle, isn't currently
    AVAILABLE (already RESERVED/IN_USE by another trip), or isn't
    genuinely idle (mid-trip, still has a trip group out and about).

    NPC-004 section 12: a vehicle whose driver has permanently departed
    (accident response) must never be reassigned another trip, even if it
    otherwise looks idle/available."""
    if vehicle.vehicle_kind != "household":
        return False
    if vehicle.driver_departed:
        return False
    if vehicle.availability != NPCAvailability.AVAILABLE:
        return False
    if vehicle.trip_group is not None:
        return False
    vehicle.availability = NPCAvailability.RESERVED
    return True


def release_household_vehicle(vehicle: NPCVehicle) -> None:
    """Idempotent - safe to call even if the vehicle was never reserved."""
    if vehicle.availability != NPCAvailability.AVAILABLE:
        vehicle.availability = NPCAvailability.AVAILABLE


def _plan_and_validate_npc_route(
    traffic_world: TrafficWorld,
    ways: List[Way],
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    spatial_grid: Optional[SpatialWayGrid] = None,
    curbs: Optional[List[Curb]] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    buildings: Optional[List] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    parking_space=None,
    destination_is_off_road: bool = False,
    origin_is_off_road: bool = False,
    deadline: Optional[float] = None,
) -> Optional[List[PathPoint]]:
    """Plan and fully validate a drivable path from origin to destination -
    the shared "never move a vehicle onto an unchecked route" core of both
    spawn_npc (a brand-new vehicle) and continue_npc_trip (an existing one
    picking its next destination - multi-passenger-car.md section 21).
    Returns None if no valid route exists.

    destination_is_off_road (see build_driving_path's own
    skip_final_lane_offset) should be set whenever `destination` is a
    parking space/lot/building yard point _pick_npc_destination_candidates
    chose deliberately, off any road - never for a plain on-road point or
    the roadside-parking fallback, which relies on the normal lane-offset
    to hug the curb.

    origin_is_off_road (NPC-003: start_npc_trip, an idle vehicle placed by
    place_parked_npc departing from a lot/yard/off-road parking spot for
    the first time) is the same idea mirrored at the *start* - the first
    leg out of a real parking lot or yard legitimately crosses its own
    curb cut and passes close to the lot's own boundary, which the normal
    strict curb/building clearance would otherwise flag as "drove through
    a wall/curb" (never needed before this, since every existing caller's
    origin was already a point the vehicle had just finished a fully-
    validated drive to).

    `parking_space`, when given, is the ParkingSpace `destination` was
    chosen for (see _pick_npc_destination_candidates) - the caller reserves
    it only once this returns a real path, never optimistically before, so
    a rejected route never leaves a phantom reservation to clean up.
    """
    return run_route_steps(_plan_and_validate_npc_route_steps(
        traffic_world, ways, origin, destination, spatial_grid=spatial_grid,
        curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
        parking_space=parking_space, destination_is_off_road=destination_is_off_road,
        origin_is_off_road=origin_is_off_road,
    ), deadline)


def _plan_and_validate_npc_route_steps(
    traffic_world: TrafficWorld,
    ways: List[Way],
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    spatial_grid: Optional[SpatialWayGrid] = None,
    curbs: Optional[List[Curb]] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    buildings: Optional[List] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    parking_space=None,
    destination_is_off_road: bool = False,
    origin_is_off_road: bool = False,
) -> RouteSteps:
    """_plan_and_validate_npc_route as a resumable job: the route search
    and the curb/building sampling both yield per unit of work. Pure -
    reads the world, never mutates it (bin-loader-v12.md)."""
    raw_route = yield from traffic_world.plan_route_steps(origin, destination)
    if raw_route is None:
        return None
    access_path = getattr(parking_space, "access_path", ()) if parking_space is not None else ()
    if len(access_path) >= 2:
        # Route through the generated driveway's road-edge mouth rather
        # than letting A* draw an arbitrary last-hop line across the yard.
        raw_route = [*raw_route[:-1], access_path[-1], destination]
    deduped_route = _dedupe_points(raw_route)
    if len(deduped_route) < 3:  # start + >=1 real road node + target
        return None
    # NPC-more.md section 15: align the final approach heading with the
    # parking space's own orientation, when known - a no-op (route
    # unchanged) without one. Done before validation so the inserted
    # approach point is itself checked like any other route point.
    final_segment_count = 1
    aligned_route = _align_approach_to_parking_orientation(deduped_route, parking_space)
    if len(aligned_route) > len(deduped_route):
        deduped_route = _dedupe_points(aligned_route)
        final_segment_count = 2
    # Only a drivable way counts as "on a real road" here (NPC-more.md
    # section 12: never treat a sidewalk/footway as a road) - build_driving_
    # path below still gets the full `ways` list, since its own mid-route
    # lookups only ever land on the route graph's already-drivable-only
    # roads (see TrafficWorld._build_route_graph) and it needs the same
    # list for the final destination hop's lane-offset way lookup.
    # (Only the no-grid fallback scans this list - with a spatial grid,
    # filtering every loaded way per route was pure overhead.)
    drivable_ways = ways if spatial_grid is not None else [
        way for way in ways if getattr(way, "is_drivable", True)
    ]
    if not (yield from _route_stays_on_road_steps(
        deduped_route, drivable_ways, spatial_grid, MAX_ROUTE_OFFROAD_TOLERANCE_M,
        NPC_PARKING_ACCESS_TOLERANCE_M, final_segment_count,
        NPC_PARKING_ACCESS_TOLERANCE_M if origin_is_off_road else None, 1,
    )):
        return None
    yield

    path = build_driving_path(
        deduped_route, ways, spatial_grid=spatial_grid, skip_final_lane_offset=destination_is_off_road,
    )
    yield
    if len(path) < 2:
        return None
    path_points = [(p.x, p.y) for p in path]
    skip_leading_m = NPC_PARKING_ACCESS_TOLERANCE_M if origin_is_off_road else 0.0
    driveway_skip_m = (
        math.hypot(access_path[-1][0] - destination[0], access_path[-1][1] - destination[1]) + 1.0
        if len(access_path) >= 2 else 0.0
    )
    # NPC-more.md section 7: never drive on curbs - checked against the
    # actual lane-offset/corner-rounded trajectory, not the raw centerline,
    # since a wide vehicle clips a curb at a corner or roundabout island,
    # not at the road's own centerline.
    if (yield from _route_crosses_obstacles_steps(
        path_points, NPC_VEHICLE_LENGTH_M, NPC_VEHICLE_WIDTH_M, CURB_CLEARANCE_MARGIN_M,
        curbs=curbs or [], curb_grid=curb_grid,
        skip_leading_m=skip_leading_m, skip_trailing_m=driveway_skip_m,
    )):
        return None
    # NPC-more.md section 13: never drive through a building polygon.
    if (yield from _route_crosses_obstacles_steps(
        path_points, NPC_VEHICLE_LENGTH_M, NPC_VEHICLE_WIDTH_M, BUILDING_CLEARANCE_MARGIN_M,
        buildings=buildings or [], building_grid=building_grid, skip_leading_m=skip_leading_m,
    )):
        return None
    return path


def spawn_npc(
    vehicle_id: int,
    resident_manager: ResidentManager,
    traffic_world: TrafficWorld,
    ways: List[Way],
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    spatial_grid: Optional[SpatialWayGrid] = None,
    color: Optional[Tuple[int, int, int]] = None,
    curbs: Optional[List[Curb]] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    buildings: Optional[List] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    parking_space=None,
    destination_is_off_road: bool = False,
    vehicle_type: str = "car",
) -> Optional[Tuple[int, Driver, NPCVehicle]]:
    """Create the Resident -> Driver -> NPCVehicle chain for one NPC
    (NPC-001 sections 5, 11, 12).

    The route is planned and validated BEFORE anything is created; a
    vehicle is never spawned to then go hunting for a route while
    already "driving". Returns None if no valid route exists.
    """
    path = _plan_and_validate_npc_route(
        traffic_world, ways, origin, destination, spatial_grid=spatial_grid,
        curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
        parking_space=parking_space, destination_is_off_road=destination_is_off_road,
    )
    if path is None:
        return None

    start = path[0]
    car = Car(x=start.x, y=start.y, heading=0.0, speed=0.0, length_m=NPC_VEHICLE_LENGTH_M, width_m=NPC_VEHICLE_WIDTH_M)
    vehicle = NPCVehicle(
        vehicle_id=vehicle_id, car=car, vehicle_type=vehicle_type,
        color=color if color is not None else random.choice(NPC_VEHICLE_COLORS), capacity=NPC_CAR_CAPACITY,
    )
    driver = _begin_trip_on_vehicle(
        vehicle,
        path,
        resident_manager,
        destination,
        parking_space,
        destination_is_off_road=destination_is_off_road,
    )
    return vehicle.owner_id, driver, vehicle


def _begin_trip_on_vehicle(
    vehicle: NPCVehicle,
    path: List[PathPoint],
    resident_manager: ResidentManager,
    destination: Tuple[float, float],
    parking_space=None,
    member_resident_ids: Optional[List[int]] = None,
    destination_is_off_road: bool = False,
) -> Driver:
    """Create the Resident group -> TripGroup -> Driver for a vehicle
    about to start driving `path` for the first time - shared by
    spawn_npc (a brand-new vehicle) and start_npc_trip (NPC-003: an
    existing idle parked vehicle beginning its first/next trip). Mutates
    `vehicle` in place (position/heading, owner_id, way, destination,
    travel_route, trip_group, state, parking reservation) and returns the
    new Driver.

    1. create/select the Resident group, 2. designate its first member as
    driver, 3. place the vehicle at the route's start, 4. associate
    vehicle<->Driver<->TripGroup - in that order, per NPC-001 section 11 -
    never a moving vehicle first with a driver attached after.

    multi-passenger-car.md sections 2, 5: the group is never auto-filled
    to capacity - a lone driver (group size 1) is exactly as valid as a
    full car.

    member_resident_ids (NPC-003 section 6): a household vehicle's trip
    group is drawn from its *own* already-existing household members
    (created once, at population-fill time, and reused across every trip
    that household ever takes) rather than a fresh anonymous group each
    time - "Household -> Vehicle -> Residents" means the same Residents,
    not new strangers every errand. None (the default) keeps the
    original behavior: a brand-new random group, for anonymous
    TRAFFIC_VEHICLE ambient traffic.
    """
    if member_resident_ids is not None:
        # The vehicle definition's capacity includes the driver.  Treat it
        # as a hard invariant here, at the point where a roster becomes
        # physical occupants, rather than trusting every caller to have
        # sampled a small enough and duplicate-free group.
        members = []
        seen_resident_ids: Set[int] = set()
        for resident_id in member_resident_ids:
            if resident_id in seen_resident_ids:
                continue
            member = resident_manager.get(resident_id)
            if member is None:
                continue
            seen_resident_ids.add(resident_id)
            members.append(member)
            if len(members) >= max(1, vehicle.capacity):
                break
    else:
        members = []
    if not members:
        group_size = random.randint(1, max(1, vehicle.capacity))
        members = [resident_manager.create(mode="driving" if i == 0 else "riding") for i in range(group_size)]
    driver_resident = members[0]
    for member in members:
        member.vehicle_ids.add(vehicle.vehicle_id)
    driver_resident.active_vehicle_id = vehicle.vehicle_id

    start, aim = path[0], path[1]
    vehicle.car.x, vehicle.car.y = start.x, start.y
    vehicle.car.heading = math.atan2(aim.y - start.y, aim.x - start.x)
    vehicle.car.speed = 0.0
    member_ids = [member.resident_id for member in members]
    trip_group = TripGroup(
        group_id=next(_trip_group_id_counter),
        vehicle_id=vehicle.vehicle_id,
        member_resident_ids=member_ids,
        boarded_resident_ids=set(member_ids),
        activity_type=random.choice(NPC_TRIP_ACTIVITY_TYPES),
        activity_duration_s=random.uniform(NPC_BUILDING_VISIT_MIN_S, NPC_BUILDING_VISIT_MAX_S),
    )
    for member in members:
        member.trip_group_id = trip_group.group_id
    vehicle.owner_id = driver_resident.resident_id
    vehicle.way = start.way
    vehicle.destination = destination
    vehicle.travel_route = [(p.x, p.y) for p in path]
    vehicle.trip_group = trip_group
    if vehicle.state == NPCState.PARKED:
        # An idle parked vehicle (start_npc_trip) must leave PARKED before
        # update_npc runs again - otherwise its early-return branch there
        # (see update_npc's own docstring) sees a freshly all-aboard trip
        # group and never advances it to actually driving. A brand-new
        # vehicle (spawn_npc) is untouched here, same as before this was
        # factored out - it keeps dataclass-default SPAWNING until its
        # first update_npc call assigns a real state.
        vehicle.state = NPCState.CRUISING
    driver = Driver(
        resident_id=driver_resident.resident_id,
        vehicle_id=vehicle.vehicle_id,
        path=path,
        destination=destination,
        destination_is_off_road=destination_is_off_road,
        current_way=start.way,
    )
    if parking_space is not None:
        parking_space.reserved = True
        parking_space.vehicle_id = vehicle.vehicle_id
        vehicle.destination_parking_space_id = getattr(parking_space, "osm_id", None)
        vehicle.reserved_parking_space = parking_space
    return driver


def start_npc_trip(
    vehicle: NPCVehicle,
    resident_manager: ResidentManager,
    traffic_world: TrafficWorld,
    ways: List[Way],
    destination: Tuple[float, float],
    spatial_grid: Optional[SpatialWayGrid] = None,
    curbs: Optional[List[Curb]] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    buildings: Optional[List] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    parking_space=None,
    destination_is_off_road: bool = False,
    member_resident_ids: Optional[List[int]] = None,
    deadline: Optional[float] = None,
) -> Optional[Driver]:
    """NPC-003: an existing idle parked vehicle (see place_parked_npc)
    starts its first/next trip - the population-fill counterpart of
    spawn_npc, reusing the exact same route planning/validation
    (_plan_and_validate_npc_route) and trip-group creation
    (_begin_trip_on_vehicle). The only difference from spawn_npc is that
    the NPCVehicle already exists (created empty, parked, no group).

    member_resident_ids: see _begin_trip_on_vehicle - a household
    vehicle's own existing members, or None for a fresh anonymous group.

    Returns None (vehicle untouched) if no valid route exists - the
    caller should leave it parked and try again later, same as every
    other "don't get stuck on one bad candidate" fallback in this module.
    """
    origin = (vehicle.car.x, vehicle.car.y)
    path = _plan_and_validate_npc_route(
        traffic_world, ways, origin, destination, spatial_grid=spatial_grid,
        curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
        parking_space=parking_space, destination_is_off_road=destination_is_off_road,
        # Every start_npc_trip origin comes from place_parked_npc - always
        # a parked position (lot/yard/dedicated space/roadside), never a
        # point the vehicle just finished driving to. Safe even when the
        # origin happens to already be right on a road (the roadside
        # tier): it only loosens validation, never a correctness risk.
        origin_is_off_road=True,
        deadline=deadline,
    )
    if path is None:
        return None
    return _apply_npc_trip(
        vehicle, resident_manager, (path, destination, parking_space, destination_is_off_road),
        member_resident_ids=member_resident_ids,
    )


def _apply_npc_trip(
    vehicle: NPCVehicle,
    resident_manager: ResidentManager,
    plan: Tuple[List[PathPoint], Tuple[float, float], object, bool],
    member_resident_ids: Optional[List[int]] = None,
) -> Driver:
    """Put an idle vehicle on a planned, validated trip: plan is
    (path, destination, parking_space, destination_is_off_road)."""
    path, destination, parking_space, destination_is_off_road = plan
    release_npc_parking_reservation(vehicle)
    return _begin_trip_on_vehicle(
        vehicle,
        path,
        resident_manager,
        destination,
        parking_space,
        member_resident_ids=member_resident_ids,
        destination_is_off_road=destination_is_off_road,
    )


NPC_TARGET_COUNT_DEFAULT = 40  # when the city's population is unknown
NPC_TARGET_COUNT_MIN = 15
NPC_TARGET_COUNT_MAX = 100


def npc_target_count_for_population(population: Optional[int]) -> int:
    """NPC vehicle target scaled sub-linearly with the city's population
    (traffic near the player grows with city size, but not 1:1): about 42
    for Rovaniemi (65k), 78 for Oulu (217k), capped at 100 (Helsinki)."""
    if not population:
        return NPC_TARGET_COUNT_DEFAULT
    return max(NPC_TARGET_COUNT_MIN, min(NPC_TARGET_COUNT_MAX, round(math.sqrt(population) / 6.0)))


def _nearest_route_node_index(traffic_world: TrafficWorld, x: float, y: float) -> Optional[int]:
    """The route graph node nearest (x, y), or None if the graph is empty -
    NPC-003: where an idle parked vehicle's BFS destination search
    (find_and_start_npc_trip) should start from, mirroring how
    spawn_deterministic_npc's own origin_index is just a node index into
    this same graph."""
    nodes = traffic_world._route_nodes
    if not nodes:
        return None
    # Same answer as min(range(len(nodes)), key=squared distance) - lowest
    # index on ties - via TrafficWorld's own node grid (the brute-force
    # scan cost ~24 ms per trip-start attempt on Oulu).
    grid = getattr(traffic_world, "_route_node_grid", None)
    if not grid:
        return min(range(len(nodes)), key=lambda idx: (nodes[idx][0] - x) ** 2 + (nodes[idx][1] - y) ** 2)
    cell_size = _ROUTE_NODE_GRID_CELL_M
    cell_x, cell_y = math.floor(x / cell_size), math.floor(y / cell_size)
    best = None
    remaining = len(grid)
    ring = 0
    while remaining > 0:
        cells = [(cell_x, cell_y)] if ring == 0 else [
            (cell_x + dx, cell_y + dy) for dx in range(-ring, ring + 1) for dy in (-ring, ring)
        ] + [(cell_x + dx, cell_y + dy) for dx in (-ring, ring) for dy in range(-ring + 1, ring)]
        for cell in cells:
            indices = grid.get(cell)
            if indices is None:
                continue
            remaining -= 1
            for idx in indices:
                key = ((nodes[idx][0] - x) ** 2 + (nodes[idx][1] - y) ** 2, idx)
                if best is None or key < best:
                    best = key
        # Everything outside rings 0..ring is farther than ring cells away.
        if best is not None and best[0] < (ring * cell_size) ** 2:
            break
        ring += 1
    return best[1]


def _point_in_viewport(
    x: float, y: float, viewport_bounds: Tuple[float, float, float, float], margin_m: float = 0.0,
) -> bool:
    """NPC-003 v2: same check pedestrian.py's spawn_pedestrian/population
    culling already use to avoid the player ever seeing a spawn/despawn
    pop - viewport_bounds is (minx, miny, maxx, maxy) in world meters.

    margin_m inflates the checked rectangle outward - used at spawn time
    (NPC_PARKING_ACCESS_TOLERANCE_M) because a vehicle placed just
    outside the raw viewport can still end up a real number of meters
    closer to it the moment it starts a trip: _begin_trip_on_vehicle
    snaps a newly-departing vehicle from its exact off-road resting spot
    to the route's actual start point on the road graph, which can be
    that far away for an off-road parking/lot/yard space. Without this
    margin, a vehicle spawned right at the viewport's edge could still
    visibly snap into view the instant the very same population tick
    also happens to roll it to start a trip.
    """
    vminx, vminy, vmaxx, vmaxy = viewport_bounds
    return (vminx - margin_m) <= x <= (vmaxx + margin_m) and (vminy - margin_m) <= y <= (vmaxy + margin_m)


def find_and_start_npc_trip(
    vehicle: NPCVehicle,
    resident_manager: ResidentManager,
    traffic_world: TrafficWorld,
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    parking_spaces: Optional[List] = None,
    sceneries: Optional[List] = None,
    buildings: Optional[List] = None,
    curbs: Optional[List[Curb]] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    member_resident_ids: Optional[List[int]] = None,
    other_vehicle_positions: Optional[List[Tuple[float, float]]] = None,
    time_budget_s: float = NPC_TRIP_START_TIME_BUDGET_S,
) -> Optional[Driver]:
    """NPC-003: an idle parked vehicle (population tick decided it's time
    for its next errand) picks *some* reachable destination and starts a
    trip - the population-management counterpart of spawn_deterministic_
    npc, reusing its exact same "BFS out from a graph node, try every
    tiered candidate at each reached point before giving up" retry
    strategy (confirmed against real Oulu data: an individual candidate
    pair often fails route validation in a dense real city - a route
    threading a couple hundred meters of real streets, buildings and curbs
    routinely clips one somewhere - so a single nearby guess is not
    enough; this BFS walk is what actually makes spawn_deterministic_npc
    reliable, not a looser check).

    Starts the BFS from the road graph node nearest the vehicle's own
    current position (spawn_deterministic_npc's origin_index is a fixed
    node picked once for the game's one demo vehicle; here every vehicle
    has its own starting point). Returns None (vehicle left parked,
    caller tries again on a later population tick) if nothing reachable
    validates within the search budget.

    Also bounded by NPC_TRIP_START_TIME_BUDGET_S, checked between
    candidates (not something that can interrupt a single already-running
    plan_route call - Python has no preemption here) - stops trying
    *further* candidates once several slow ones have already piled up in
    this one call, rather than working all the way through the full
    candidate width regardless of how expensive it's turning out to be.
    A single unusually expensive plan_route call can still occasionally
    exceed the budget by itself (a known, currently-unresolved limitation
    - see NPC_TRIP_START_TIME_BUDGET_S's own comment; fixing plan_route's
    own worst-case cost, or moving this search off the main thread, is
    future work outside this task's scope).
    """
    plan = run_route_steps(_find_npc_trip_steps(
        vehicle, traffic_world, ways, spatial_grid=spatial_grid, parking_spaces=parking_spaces,
        sceneries=sceneries, buildings=buildings, curbs=curbs, curb_grid=curb_grid,
        building_grid=building_grid, other_vehicle_positions=other_vehicle_positions,
    ), time.perf_counter() + time_budget_s)
    if plan is None:
        return None
    return _apply_npc_trip(vehicle, resident_manager, plan, member_resident_ids=member_resident_ids)


def _find_npc_trip_steps(
    vehicle: NPCVehicle,
    traffic_world: TrafficWorld,
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    parking_spaces: Optional[List] = None,
    sceneries: Optional[List] = None,
    buildings: Optional[List] = None,
    curbs: Optional[List[Curb]] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    other_vehicle_positions: Optional[List[Tuple[float, float]]] = None,
) -> RouteSteps:
    """find_and_start_npc_trip's search as a resumable job: returns the
    first validated plan (see _apply_npc_trip) or None, mutating nothing."""
    origin_index = _nearest_route_node_index(traffic_world, vehicle.car.x, vehicle.car.y)
    if origin_index is None:
        return None
    nodes = traffic_world._route_nodes
    edges = traffic_world._route_edges
    # A much smaller search width than spawn_deterministic_npc's one-time
    # NPC_DESTINATION_CANDIDATE_LIMIT (40) - see NPC_TRIP_START_CANDIDATE_
    # POINTS's own comment for why: this runs recurringly, per idle
    # vehicle, per population tick, not once at load time.
    road_points = _bfs_destination_order(nodes, edges, origin_index)[:NPC_TRIP_START_CANDIDATE_POINTS]
    origin = (vehicle.car.x, vehicle.car.y)
    for destination_index in road_points:
        yield
        raw_destination = (nodes[destination_index][0], nodes[destination_index][1])
        destination_candidates = _pick_npc_destination_candidates(
            raw_destination[0], raw_destination[1], parking_spaces, sceneries, buildings,
            ways=ways, spatial_grid=spatial_grid, other_vehicle_positions=other_vehicle_positions,
            own_position=origin,
        )
        for destination, target_space in destination_candidates:
            yield
            destination_is_off_road = destination != raw_destination
            # Every trip start departs from a parked position (lot/yard/
            # dedicated space/roadside) - see start_npc_trip.
            path = yield from _plan_and_validate_npc_route_steps(
                traffic_world, ways, origin, destination, spatial_grid=spatial_grid,
                curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
                parking_space=target_space, destination_is_off_road=destination_is_off_road,
                origin_is_off_road=True,
            )
            if path is not None:
                return path, destination, target_space, destination_is_off_road
    return None


def release_npc_parking_reservation(vehicle: NPCVehicle) -> None:
    """Release this vehicle's parking-space reservation, if it holds one
    (NPC-more.md section 4: "if the vehicle leaves: release the occupied
    space"). Idempotent - safe to call repeatedly once already released."""
    space = vehicle.reserved_parking_space
    if space is None:
        return
    if getattr(space, "vehicle_id", None) == vehicle.vehicle_id:
        space.reserved = False
        space.occupied = False
        space.vehicle_id = None
    vehicle.reserved_parking_space = None


def _corner_safe_speed_mps(
    radius_m: float = CORNER_RADIUS_M, lateral_g: float = NPC_CORNER_COMFORT_LATERAL_G,
) -> float:
    """A comfortable speed to actually drive a CORNER_RADIUS_M turn at -
    well under the tires' real grip ceiling (physics.py's max_grip_g /
    the "understeer, push wide" clamp GRIP.md describes), the same way a
    real driver slows for a tight corner long before they'd actually lose
    grip. v = sqrt(lateral_g * g * r), the standard circular-motion
    relation between cornering speed, lateral acceleration and radius."""
    return math.sqrt(lateral_g * GRAVITY_MPS2 * radius_m)


def _distance_to_next_turn(
    path: List[PathPoint], path_index: int, x: float, y: float, max_lookahead_m: float = NPC_CORNER_LOOKAHEAD_M,
) -> Optional[float]:
    """Distance from (x, y) to the start of the next is_turn stretch of
    the path, walking forward from path_index (0.0 if already there), or
    None if no turn starts within max_lookahead_m - so update_npc can
    brake for a sharp corner in the middle of a route the same
    comfortable way it already brakes for arrival, instead of taking
    every turn at full cruising speed regardless of how tight it is
    (reported: NPC understeering wide into a curb/building at a sharp
    turn, repeatedly re-triggering the live footprint check)."""
    if path_index >= len(path):
        return None
    total = 0.0
    prev_x, prev_y = x, y
    for i in range(path_index, len(path)):
        point = path[i]
        total += math.hypot(point.x - prev_x, point.y - prev_y)
        if total > max_lookahead_m:
            return None
        if point.is_turn:
            return total
        prev_x, prev_y = point.x, point.y
    return None


def _next_turn_signal(path: List[PathPoint], path_index: int, x: float, y: float, lookahead_m: float) -> str:
    """"left"/"right" when the path's next junction turn starts within
    lookahead_m - including while driving through it - else "".

    Corner points are tagged by angle alone (CORNER_ANGLE_THRESHOLD_DEG),
    so a bend that stays on the same road would also count; only a turn
    onto a different way is signalled."""
    total = 0.0
    prev_x, prev_y = x, y
    # The road being left: the last non-turn point behind us (mid-turn the
    # previous point is itself a turn point already on the new road).
    incoming_way = next(
        (point.way for point in reversed(path[:path_index]) if not point.maneuver), None,
    )
    for point in path[path_index:]:
        total += math.hypot(point.x - prev_x, point.y - prev_y)
        if total > lookahead_m:
            return ""
        if point.maneuver in ("left", "right"):
            if point.way is not incoming_way or incoming_way is None:
                return point.maneuver
        elif point.way is not None:
            incoming_way = point.way
        prev_x, prev_y = point.x, point.y
    return ""


def _set_turn_signal(vehicle: "NPCVehicle", signal: str, dt: float) -> None:
    """Blink phase restarts whenever the signal changes."""
    if signal != vehicle.turn_signal:
        vehicle.turn_signal = signal
        vehicle.turn_signal_elapsed = 0.0
    elif signal:
        vehicle.turn_signal_elapsed += dt


def _path_follow_target(driver: Driver, x: float, y: float, speed_mps: float) -> Tuple[PathPoint, float]:
    """Project onto the cached route and return a speed-scaled lookahead point.

    Search begins at the previous segment and only looks a few segments
    backward, preventing noisy GPS-like projection jumps at intersections
    while still allowing recovery after overshooting a short waypoint.
    """
    path = driver.path
    if len(path) < 2:
        return path[-1], 0.0
    first = max(0, min(driver.route_segment_index, len(path) - 2) - 2)
    last = min(len(path) - 2, max(driver.path_index + 8, first + 8))
    best = (float("inf"), first, 0.0, path[first].x, path[first].y)
    for index in range(first, last + 1):
        a, b = path[index], path[index + 1]
        dx, dy = b.x - a.x, b.y - a.y
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq < 1e-9 else clamp(((x - a.x) * dx + (y - a.y) * dy) / length_sq, 0.0, 1.0)
        px, py = a.x + dx * t, a.y + dy * t
        distance_sq = (x - px) ** 2 + (y - py) ** 2
        if distance_sq < best[0]:
            best = (distance_sq, index, t, px, py)
    _, segment, t, px, py = best
    driver.route_segment_index = segment
    driver.route_segment_t = t
    # Bookkeeping follows projection progress; it no longer chooses the
    # steering point. Never move it backwards at crossings.
    driver.path_index = max(driver.path_index, min(len(path) - 1, segment + 1))
    lookahead = clamp(
        NPC_PATH_LOOKAHEAD_BASE_M + abs(speed_mps) * NPC_PATH_LOOKAHEAD_TIME_S,
        NPC_PATH_LOOKAHEAD_MIN_M, NPC_PATH_LOOKAHEAD_MAX_M,
    )
    driver.lookahead_distance_m = lookahead
    remaining = lookahead
    index = segment
    cx, cy = px, py
    while index < len(path) - 1:
        endpoint = path[index + 1]
        length = math.hypot(endpoint.x - cx, endpoint.y - cy)
        if length >= remaining and length > 1e-9:
            ratio = remaining / length
            return PathPoint(
                cx + (endpoint.x - cx) * ratio,
                cy + (endpoint.y - cy) * ratio,
                endpoint.way, endpoint.is_turn, endpoint.maneuver, endpoint.lane_bias,
            ), lookahead
        remaining -= length
        index += 1
        cx, cy = path[index].x, path[index].y
    return path[-1], lookahead


def _update_npc_reversing(
    vehicle: NPCVehicle,
    driver: Driver,
    dt: float,
    manager: object,
    pedestrian_mgr: object,
) -> None:
    """NPC-004 section 6/7: a short, controlled, straight-line back-up -
    entered by _run_population_tick's recovery scan once a plain reroute
    from the current position failed to clear a stuck vehicle. Never plans
    a route itself (that stays on the throttled population tick, never
    per-frame - see that function's own comment on why) - this only ever
    physically moves the vehicle backward a bounded distance, checking
    clearance every call, and hands back to the population tick (via
    recovery_stage="STUCK") to try routing again from the new position.
    """
    if driver.reverse_start_position is None:
        driver.reverse_start_position = (vehicle.car.x, vehicle.car.y)

    heading = vehicle.car.heading
    behind_x = vehicle.car.x - math.cos(heading) * NPC_REVERSE_CLEARANCE_CHECK_RADIUS_M
    behind_y = vehicle.car.y - math.sin(heading) * NPC_REVERSE_CLEARANCE_CHECK_RADIUS_M
    clearance_radius_sq = NPC_REVERSE_CLEARANCE_CHECK_RADIUS_M ** 2
    clear = True
    if manager is not None:
        for other in manager.nearby_vehicles_at(behind_x, behind_y, NPC_REVERSE_CLEARANCE_CHECK_RADIUS_M):
            if other is vehicle:
                continue
            if (other.x - behind_x) ** 2 + (other.y - behind_y) ** 2 < clearance_radius_sq:
                clear = False
                break
    if clear and pedestrian_mgr is not None:
        for ped in getattr(pedestrian_mgr, "pedestrians", ()):
            if (ped.x - behind_x) ** 2 + (ped.y - behind_y) ** 2 < clearance_radius_sq:
                clear = False
                break

    distance_reversed = math.hypot(
        vehicle.car.x - driver.reverse_start_position[0], vehicle.car.y - driver.reverse_start_position[1]
    )
    if not clear or distance_reversed >= NPC_REVERSE_DISTANCE_M:
        # Done (or blocked) - stop and hand back to the population tick's
        # recovery scan to try a fresh route from wherever this landed.
        vehicle.car.speed = 0.0
        vehicle.state = NPCState.WAITING
        vehicle.debug_waiting_for = "reversed - awaiting reroute"
        driver.recovery_stage = "STUCK"
        driver.reverse_start_position = None
        driver.stuck_timer_s = 0.0
        driver.stuck_check_position = None
        return

    update_car_physics(
        vehicle.car, throttle=0.0, brake=1.0, steer_left=0.0, steer_right=0.0, dt=dt,
        block_offroad=False, speed_limit_mps=NPC_REVERSE_SPEED_MPS,
    )


def update_npc(
    vehicle: NPCVehicle,
    driver: Driver,
    dt: float,
    traffic_world: TrafficWorld,
    resident_manager: ResidentManager,
    curbs: Optional[List[Curb]] = None,
    buildings: Optional[List] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    nearby_obstacles: Optional[List] = None,
    manager: object = None,
    pedestrian_mgr: object = None,
) -> None:
    """Advance one NPC's driving decision and physics by one frame
    (NPC-001 sections 5-10). Pure simulation, no Pygame.

    Performance (section 16): the route is never recalculated here (only
    once, in spawn_npc); the per-frame scan is the traffic-light lookup,
    which reuses TrafficWorld._nearby_traffic_lights - the same call the
    player's own red-light assist already makes every frame. The live
    footprint check (below) is *not* cheap against real dense OSM data
    (profiled: ~1-2ms/call, dominated by genuine nearby curb/building
    count, not a spatial-grid tuning issue) - harmless at NPC-001's single
    always-on car, but a real per-frame cost multiplied across NPC-003's
    whole population, so it runs at a reduced rate (see
    NPC_FOOTPRINT_CHECK_INTERVAL_S) rather than every frame.

    curbs/buildings, when given, enable NPC-more.md section 12/13's
    "enforced at the movement level, not only during route generation":
    the planned path is already fully validated once at spawn time (see
    spawn_npc), but physics smoothing/lag could in principle still drift
    the vehicle's actual pose off of it between waypoints - this is the
    live safety net for that gap, not the primary defense.
    """
    if not has_active_driver(vehicle, resident_manager):
        vehicle.car.speed = 0.0
        release_npc_parking_reservation(vehicle)
        _set_turn_signal(vehicle, "", dt)
        return

    if vehicle.state == NPCState.REVERSING:
        _set_turn_signal(vehicle, "", dt)
        _update_npc_reversing(vehicle, driver, dt, manager, pedestrian_mgr)
        return

    if vehicle.state == NPCState.PARKED:
        _set_turn_signal(vehicle, "", dt)
        # multi-passenger-car.md sections 17-20: a genuinely stationary
        # parked vehicle has no driving decision left to make - no traffic
        # light lookup, no footprint check - just trip-group bookkeeping.
        # main/__init__.py's per-frame NPC update checks trip_group.all_
        # aboard immediately after this call and calls continue_npc_trip
        # (which needs destination/parking/curb/building lookups this
        # function otherwise has no reason to take as parameters) once
        # ready; this function only ever decides *when* that becomes true.
        vehicle.car.speed = 0.0
        group = vehicle.trip_group
        if group is not None and not group.all_aboard:
            if group.wait_deadline_sim_time is None:
                group.wait_deadline_sim_time = traffic_world.sim_time + group.activity_duration_s + NPC_GROUP_RETURN_GRACE_S
            elif traffic_world.sim_time >= group.wait_deadline_sim_time:
                # Section 20: never wait forever - leave stragglers behind
                # rather than block the vehicle (and every other trip
                # group's parking turnover) indefinitely. A resident still
                # out there keeps existing as an ordinary Resident/
                # Pedestrian, just no longer tied to this vehicle/group -
                # dropped from member_resident_ids entirely (not marked
                # boarded) so OCCUPANTS/debug reporting never overcounts
                # a passenger who was actually left behind.
                stranded = set(group.member_resident_ids) - group.boarded_resident_ids
                for resident_id in stranded:
                    resident = resident_manager.get(resident_id)
                    if resident is not None:
                        resident.trip_group_id = None
                group.member_resident_ids = [
                    resident_id for resident_id in group.member_resident_ids if resident_id not in stranded
                ]
        return

    path = driver.path
    target, _lookahead = _path_follow_target(driver, vehicle.car.x, vehicle.car.y, vehicle.car.speed)
    route_target = path[driver.path_index]
    if route_target.way is not None:
        driver.current_way = route_target.way
        vehicle.way = route_target.way

    approaching_final_waypoint = driver.path_index >= len(path) - 1
    final_point = path[-1]
    distance_to_target = math.hypot(final_point.x - vehicle.car.x, final_point.y - vehicle.car.y)
    at_destination = approaching_final_waypoint and distance_to_target < NPC_ARRIVAL_RADIUS_M
    # Only the actual off-road hop (at most NPC_PARKING_ACCESS_TOLERANCE_M,
    # the most route validation allows) is driven at yard pace - not the
    # whole final leg, which can be a long straight road stretch.
    in_offroad_approach = (
        driver.destination_is_off_road and approaching_final_waypoint
        and distance_to_target <= NPC_PARKING_ACCESS_TOLERANCE_M
    )

    nearby_lights = traffic_world._nearby_traffic_lights(vehicle.car.x, vehicle.car.y)
    speed_limit_mps = (driver.current_way.speed_limit_kmh / 3.6) if driver.current_way else None
    decision = decide_traffic_action(
        vehicle.car.x, vehicle.car.y, vehicle.car.heading, nearby_lights, traffic_world.sim_time,
        speed_limit_mps=speed_limit_mps,
    )
    driver.decision = decision
    driver.target_speed_mps = decision.target_speed_mps
    # NPC-003 v2 section 4: a vehicle plugin's own max speed (e.g. a bus/
    # truck slower than ordinary traffic) - a cheap clamp on top of the
    # road's own speed limit, not a new physics/acceleration model.
    max_speed_kmh = vehicle_definition(vehicle.vehicle_type).max_speed_kmh
    if max_speed_kmh is not None:
        driver.target_speed_mps = min(driver.target_speed_mps, max_speed_kmh / 3.6)
    if approaching_final_waypoint or distance_to_target < NPC_ARRIVAL_BRAKING_HORIZON_M:
        # Brake for arrival the same comfortable way the traffic rule
        # engine brakes for a stop line, rather than cruising right up to
        # the destination and only then snapping to a stop - against the
        # distance still to drive along the path: the final path segment
        # alone can be shorter than the braking distance (a road-following
        # route has a node every ~20 m), which used to overshoot the stop.
        remaining_m = math.hypot(route_target.x - vehicle.car.x, route_target.y - vehicle.car.y) + sum(
            math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(path[driver.path_index:], path[driver.path_index + 1:])
        )
        arrival_cap = math.sqrt(2.0 * ARRIVAL_DECEL_MPS2 * max(0.0, remaining_m - NPC_ARRIVAL_RADIUS_M))
        driver.target_speed_mps = min(driver.target_speed_mps, arrival_cap)
    if approaching_final_waypoint:
        if in_offroad_approach:
            # The last segment into a yard, lot or dedicated parking space
            # is deliberately allowed to leave the mapped road.  It is not,
            # however, still a 40/50 km/h road: enter it at a cautious pace.
            driver.target_speed_mps = min(
                driver.target_speed_mps, NPC_OFFROAD_APPROACH_SPEED_MPS
            )

    # Brake for a sharp corner the same comfortable way, well before
    # reaching it - nothing else here ever slows the vehicle down for the
    # geometry of a turn itself (only traffic rules and final arrival do),
    # so a corner used to always get taken at full cruising speed, well
    # past what the tires can actually deliver at that radius
    # (physics.py's own understeer clamp then pushes the car wide -
    # reported: NPC repeatedly understeering into a curb/building at a
    # sharp turn, retriggering the live footprint check every time).
    corner_distance = _distance_to_next_turn(path, driver.path_index, vehicle.car.x, vehicle.car.y)
    _set_turn_signal(vehicle, _next_turn_signal(
        path, driver.path_index, vehicle.car.x, vehicle.car.y,
        max(NPC_TURN_SIGNAL_MIN_DISTANCE_M, NPC_TURN_SIGNAL_LEAD_S * abs(vehicle.car.speed)),
    ), dt)
    if corner_distance is not None:
        corner_speed = _corner_safe_speed_mps()
        corner_cap = math.sqrt(corner_speed * corner_speed + 2.0 * NPC_CORNER_BRAKING_DECEL_MPS2 * corner_distance)
        driver.target_speed_mps = min(driver.target_speed_mps, corner_cap)

    # NPC-004 section 2: slow/stop for whatever's directly ahead in this
    # lane (another NPC, the player's car, a crashed vehicle - all satisfy
    # the same x/y duck type) - the exact same safe-follow-distance
    # braking math already used for corner_cap/arrival_cap above, just with
    # the lead obstacle's own speed as the target instead of 0.
    #
    # The cone points toward the current *steering target* (same point the
    # controller steers toward at the bottom of this function), not the
    # car's raw current heading - the physical heading lags behind mid-turn
    # (the car hasn't finished rotating into the corner yet), so a cone
    # anchored on it can miss an obstacle sitting just around that corner
    # until the turn is nearly finished and too little distance is left to
    # brake for it (reproduced: a vehicle rear-ended a parked car right
    # after a turn, having never detected it at all mid-turn).
    avoidance_heading = math.atan2(target.y - vehicle.car.y, target.x - vehicle.car.x)
    avoidance_blocked = False
    lead = nearest_vehicle_ahead(
        vehicle.car.x, vehicle.car.y, avoidance_heading, nearby_obstacles or (),
        self_id=id(vehicle),
        detection_distance_m=NPC_AVOIDANCE_DETECTION_DISTANCE_M,
        lateral_limit_m=NPC_AVOIDANCE_LATERAL_LIMIT_M,
    )
    if lead is not None:
        gap, obstacle = lead
        lead_length_m = getattr(obstacle, "length_m", NPC_VEHICLE_LENGTH_M)
        lead_speed_mps = max(0.0, getattr(obstacle, "speed", 0.0))
        following_gap = max(0.0, gap - lead_length_m * 0.5 - vehicle.length_m * 0.5 - NPC_AVOIDANCE_MIN_GAP_M)
        avoidance_cap = math.sqrt(
            lead_speed_mps * lead_speed_mps + 2.0 * NPC_AVOIDANCE_DECEL_MPS2 * following_gap
        )
        driver.target_speed_mps = min(driver.target_speed_mps, avoidance_cap)
        avoidance_blocked = following_gap <= 0.1 and lead_speed_mps < 0.5

    # NPC-005: Road Rage. A timed clamp, not a state change - the vehicle
    # keeps obeying every other rule above it (traffic lights, corners,
    # the vehicle ahead of *it*) at a reduced ceiling, exactly like the
    # footprint-violation crawl below already does for a different
    # reason, so it can never fight those into an unsafe combination.
    if driver.road_rage_until_sim_time is not None:
        if traffic_world.sim_time >= driver.road_rage_until_sim_time:
            driver.road_rage_until_sim_time = None
        else:
            driver.target_speed_mps = min(driver.target_speed_mps, NPC_ROAD_RAGE_YIELD_SPEED_MPS)

    if at_destination:
        driver.target_speed_mps = 0.0
        if vehicle.reserved_parking_space is not None:
            # RESERVED -> OCCUPIED (NPC-more.md section 4's state trio) -
            # the vehicle has actually arrived, not merely en route.
            vehicle.reserved_parking_space.occupied = True

    # NPC-more.md sections 12/13/19: the live safety net (see this
    # function's own docstring) - spawn_npc already fully validated this
    # exact path once, so this should in practice never actually trip;
    # it exists for physics drift, not as the primary defense.
    # NPC_LIVE_FOOTPRINT_CLEARANCE_M (a bare few cm, not
    # CURB/BUILDING_CLEARANCE_MARGIN_M's stricter validate-before-spawning
    # margin) - the live pose is expected to run right up against that
    # margin near a legitimately tight final approach (a parking yard
    # sits just outside a wall on purpose), so requiring the same safety
    # cushion live would flag ordinary steering lag as a "violation"
    # every single frame near any such approach.
    vehicle.footprint_check_elapsed_s += dt
    if vehicle.footprint_check_elapsed_s >= NPC_FOOTPRINT_CHECK_INTERVAL_S:
        vehicle.footprint_check_elapsed_s = 0.0
        vehicle.footprint_check_cached = is_vehicle_pose_valid(
            vehicle.car.x, vehicle.car.y, vehicle.car.heading,
            curbs=curbs, buildings=buildings, curb_grid=curb_grid, building_grid=building_grid,
            length_m=vehicle.length_m, width_m=vehicle.width_m, clearance_m=NPC_LIVE_FOOTPRINT_CLEARANCE_M,
        )
    footprint_clear = vehicle.footprint_check_cached
    if not footprint_clear:
        # A slow crawl, never a hard 0 - update_car_physics refuses to
        # turn the vehicle at all below 0.05 m/s ("cars cannot steer in
        # place while stationary"), so a full stop here would deadlock:
        # the only way off an actually-overlapping pose is to keep
        # moving, and a genuine zero-speed floor can never move again on
        # its own (reported: NPC stuck oscillating in place forever).
        driver.target_speed_mps = min(driver.target_speed_mps, NPC_FOOTPRINT_VIOLATION_CRAWL_MPS)

    # NPC-004 section 3/8: stuck/oscillation/spin detection - a single
    # "did this vehicle actually displace since the last check" test covers
    # all three failure modes the spec lists (no progress, oscillating,
    # spinning in place), since each of them fails this same test. Excludes
    # a legitimate traffic-light wait (decision.light is set) - that's not
    # "stuck", it's correctly obeying a light that will eventually change -
    # excludes genuine arrival, which has nothing left to recover from, and
    # excludes the final approach/parking maneuver in general: arrival_cap
    # deliberately ramps target_speed_mps toward 0 well before at_destination
    # actually flips True (and PARKING's own aligned approach arc is
    # slower still), so a vehicle correctly crawling the last couple of
    # meters into a space would otherwise look identical to one genuinely
    # blocked - both show near-zero real displacement over one check
    # interval (regression: legitimate final approaches were getting
    # kicked into REVERSING mid-parking).
    waiting_for_light = decision.light is not None and decision.action != TrafficAction.PROCEED
    finishing_approach = approaching_final_waypoint or vehicle.state in (NPCState.PARKING, NPCState.ARRIVING)
    if at_destination or waiting_for_light or finishing_approach or driver.recovery_stage != "NORMAL":
        driver.stuck_timer_s = 0.0
        driver.stuck_check_position = None
        driver.stuck_check_elapsed_s = 0.0
    else:
        driver.stuck_check_elapsed_s += dt
        if driver.stuck_check_elapsed_s >= NPC_STUCK_CHECK_INTERVAL_S:
            driver.stuck_check_elapsed_s = 0.0
            if driver.stuck_check_position is not None:
                moved = math.hypot(
                    vehicle.car.x - driver.stuck_check_position[0], vehicle.car.y - driver.stuck_check_position[1]
                )
                if moved < NPC_STUCK_MIN_PROGRESS_M:
                    driver.stuck_timer_s += NPC_STUCK_CHECK_INTERVAL_S
                else:
                    driver.stuck_timer_s = 0.0
            driver.stuck_check_position = (vehicle.car.x, vehicle.car.y)
        if driver.stuck_timer_s >= NPC_STUCK_TIMEOUT_S:
            # Handed to _run_population_tick's recovery scan - never
            # replans a route here (see that function's own comment on why
            # this must stay off the per-frame hot path).
            driver.recovery_stage = "STUCK"
            driver.stuck_timer_s = 0.0

    # State machine (section 10) - priority order is what a real driver
    # would report as "what am I doing right now".
    if not footprint_clear:
        vehicle.state = NPCState.WAITING
        vehicle.debug_waiting_for = "footprint blocked (curb/building)"
    elif driver.recovery_stage == "STUCK":
        vehicle.state = NPCState.WAITING
        vehicle.debug_waiting_for = "stuck - awaiting recovery"
    elif driver.road_rage_until_sim_time is not None:
        # NPC-005: still whatever state its actual speed implies (a crawl
        # is CRUISING, a full stop behind something is WAITING) - this
        # only overrides the *label*, matching every other reason here
        # being a specific string rather than a dedicated NPCState.
        vehicle.state = NPCState.CRUISING if abs(vehicle.car.speed) > 0.3 else NPCState.WAITING
        vehicle.debug_waiting_for = "yielding to road rage"
    elif at_destination:
        # ARRIVING while still coasting to a stop; PARKED (multi-passenger-
        # car.md section 17) once genuinely stationary - the same 0.05 m/s
        # "stopped" threshold physics.py itself uses ("cars cannot steer
        # in place while stationary" below it).
        vehicle.state = NPCState.PARKED if abs(vehicle.car.speed) < 0.05 else NPCState.ARRIVING
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
    elif avoidance_blocked:
        vehicle.state = NPCState.WAITING
        vehicle.debug_waiting_for = "waiting for vehicle ahead"
    elif in_offroad_approach:
        vehicle.state = NPCState.PARKING
        vehicle.debug_waiting_for = ""
    elif (
        vehicle.destination_parking_space_id is not None
        and math.hypot(driver.destination[0] - vehicle.car.x, driver.destination[1] - vehicle.car.y)
        <= NPC_PARKING_APPROACH_DISTANCE_M * 2.0
    ):
        # Final approach into a dedicated parking space (within the
        # orientation-aligned leg _align_approach_to_parking_orientation
        # inserted, corner-rounded arc included) - a more specific label
        # than TURNING for what's still visually a turn. Distance-based,
        # not path-index-based, since a corner's own sampled points (see
        # _round_corner) make "how many path points is this leg" fragile.
        vehicle.state = NPCState.PARKING
        vehicle.debug_waiting_for = ""
    elif route_target.is_turn:
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
        heading_error = angle_diff(desired_heading, vehicle.car.heading)
        requested_steer = clamp(heading_error / math.radians(STEER_FULL_ANGLE_DEG), -1.0, 1.0)
        # A first-order steering actuator avoids alternating full-lock input
        # around dense or closely spaced route points.
        blend = clamp(NPC_STEERING_RESPONSE_PER_S * dt, 0.0, 1.0)
        driver.steering_input += (requested_steer - driver.steering_input) * blend
        steer_left = max(0.0, driver.steering_input)
        steer_right = max(0.0, -driver.steering_input)

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


NPC_DESTINATION_SEARCH_RADIUS_M = 400.0  # how far from the BFS-reached area to look for a place to actually stop
# ponytail: a fixed push-away-from-center_m distance is a rough stand-in
# for "the yard/driveway just outside the door" - real buildings often
# sit only a few meters off the road, so too large a value can overshoot
# clear across a narrow street. 3m clears a car's own body without
# usually punching through a typical building-to-road setback; tune
# this (or compute a real driveway point from OSM) if that stops holding.
NPC_BUILDING_YARD_CLEARANCE_M = 3.0  # how far outside the wall an NPC actually stops


def _building_yard_point(building, from_x: float, from_y: float) -> Optional[Tuple[float, float]]:
    """The point where an NPC should actually stop for this building: its
    nearest entrance to (from_x, from_y), or - lacking one - the nearest
    point on its own outline, nudged NPC_BUILDING_YARD_CLEARANCE_M outside
    the wall.

    Entrance nodes are literally ON the building's outline (build.py reads
    them straight off the polygon's own boundary nodes), and building.
    center_m sits well inside the footprint - using either bare put the
    vehicle's own body right on top of the building (reported: "the car
    ended on a building"). Pushing away from center_m, along the vector
    from it to the wall point, reliably lands just outside for any
    reasonably-convex building shape without needing real driveway/yard
    geometry this game doesn't have.
    """
    entrances = getattr(building, "entrances", None) or []
    points = getattr(building, "points_m", None) or []
    if entrances:
        wall_point = min(entrances, key=lambda p: (p[0] - from_x) ** 2 + (p[1] - from_y) ** 2)
    elif len(points) >= 2:
        wall_point = min(
            (
                closest_point_and_dist_to_segment(from_x, from_y, ax, ay, bx, by)[:2]
                for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1])
            ),
            key=lambda p: (p[0] - from_x) ** 2 + (p[1] - from_y) ** 2,
        )
    else:
        return getattr(building, "center_m", None)

    center = getattr(building, "center_m", None)
    if center is None:
        return wall_point
    dx, dy = wall_point[0] - center[0], wall_point[1] - center[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return wall_point
    scale = (length + NPC_BUILDING_YARD_CLEARANCE_M) / length
    return center[0] + dx * scale, center[1] + dy * scale


def _parking_space_dimensions(parking_space) -> Optional[Tuple[float, float]]:
    """(long_side_m, short_side_m) of a parking space's own oriented
    rectangle, from its polygon's own edges - not the axis-aligned bbox,
    which overestimates a diagonally-oriented space's real footprint."""
    points = getattr(parking_space, "points_m", None) or []
    if len(points) < 3:
        return None
    edges = list(zip(points, points[1:] + points[:1]))
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in edges]
    if len(lengths) < 2:
        return None
    long_side = max(lengths)
    short_side = lengths[(lengths.index(long_side) + 1) % len(lengths)]
    return long_side, short_side


def _parking_space_fits_vehicle(
    parking_space,
    vehicle_length_m: float = NPC_VEHICLE_LENGTH_M,
    vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
    length_margin_m: float = 0.2,
) -> bool:
    """NPC-more.md sections 3/16: "vehicle size" and "whether the vehicle
    can physically enter/leave it" as a selection criterion - a space too
    short or narrow for this vehicle is never a candidate, regardless of
    how close or otherwise attractive it is. No geometry to judge by (a
    degenerate polygon) doesn't block on missing data."""
    dims = _parking_space_dimensions(parking_space)
    if dims is None:
        return True
    long_side, short_side = dims
    return long_side >= vehicle_length_m + length_margin_m and short_side >= vehicle_width_m


_LOW_TRAFFIC_HIGHWAY_TYPES = {"residential", "living_street", "service", "unclassified", "track"}
ROADSIDE_PARKING_MAX_ROAD_DISTANCE_M = 5.0


def _roadside_parking_point(
    x: float, y: float, ways: Optional[List[Way]], spatial_grid: Optional[SpatialWayGrid],
) -> Optional[Tuple[float, float]]:
    """NPC-more.md section 2 tier 5, the last resort: legal roadside
    parking on a quiet street - never a busy/arterial road (only
    residential/living_street/service/unclassified/track) and never a
    roundabout - relying on the existing lane-offset step
    (build_driving_path/_lane_offset_point) to place the actual resting
    point at the curb side of the lane, not its center, once this point
    becomes the route's destination. Only used when nothing better
    (dedicated space, lot, building yard) exists anywhere nearby."""
    if ways is None:
        return None
    way, distance = _way_at_point(spatial_grid, ways, x, y)
    if way is None or distance > ROADSIDE_PARKING_MAX_ROAD_DISTANCE_M:
        return None
    if getattr(way, "is_roundabout", False) or not getattr(way, "is_drivable", True):
        return None
    if str(getattr(way, "highway", "") or "").lower() not in _LOW_TRAFFIC_HIGHWAY_TYPES:
        return None
    return x, y


NPC_PARKING_CANDIDATE_LIMIT = 8  # try at most this many destination candidates per road point


def _point_is_clear_of_vehicles(
    point: Tuple[float, float],
    other_vehicle_positions: Optional[List[Tuple[float, float]]],
    min_spacing_m: float = NPC_MIN_VEHICLE_SPACING_M,
) -> bool:
    """Whether `point` is far enough from every position in
    other_vehicle_positions to park a new vehicle there without landing on
    top of one already resting nearby - see NPC_MIN_VEHICLE_SPACING_M."""
    if not other_vehicle_positions:
        return True
    spacing_sq = min_spacing_m * min_spacing_m
    return all(
        (point[0] - ox) ** 2 + (point[1] - oy) ** 2 >= spacing_sq
        for ox, oy in other_vehicle_positions
    )


def _parking_area_containing(point: Optional[Tuple[float, float]], sceneries: Optional[List]):
    """Return the Scenery(kind="parking") polygon containing `point`, or
    None. NPC-004 section 4/5: identifies which parking area a vehicle is
    currently sitting in, purely by point-in-polygon against the map's own
    already-loaded lot outlines - no persistent parking-area id needed on
    ParkingSpace/Scenery, since this only ever runs at destination-search
    time (infrequent, never per-frame), not as a per-frame lookup."""
    if point is None or not sceneries:
        return None
    for scenery in sceneries:
        if getattr(scenery, "kind", None) != "parking":
            continue
        points = getattr(scenery, "points_m", None)
        if not points or len(points) < 3:
            continue
        if point_in_polygon(point[0], point[1], points):
            return scenery
    return None


_PARKING_INDEX_CELL_M = 100.0
_PARKING_INDEX_MIN_SPACES = 64  # below this a linear scan is as cheap as the index
_parking_index = {"ref": None, "count": 0, "grid": {}}


def _parking_spaces_near(parking_spaces, x: float, y: float, radius_m: float):
    """Yield (list_index, space, center_x, center_y) for every parking
    space whose bbox center lies in a grid cell overlapping the search
    circle's bounding square, in original list order.

    _pick_npc_destination_candidates used to walk every parking space in
    the whole loaded map per call (thousands, on a real city) to keep the
    few within a few hundred meters - a profiled ~6ms per call, 18 calls
    per population tick. This indexes the list once by center cell and
    only extends it incrementally when the list grows (autofetch only
    appends, same guarantee taxi.py's collision grids rely on); a
    different list object or a shrunk one rebuilds. Callers still apply
    the exact distance test, so results are identical to a full scan."""
    spaces = parking_spaces or ()
    if len(spaces) < _PARKING_INDEX_MIN_SPACES:
        for idx, space in enumerate(spaces):
            bbox = getattr(space, "bbox", None)
            if bbox:
                yield idx, space, (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
        return
    index = _parking_index
    if index["ref"] is not spaces or len(spaces) < index["count"]:
        index["ref"], index["count"], index["grid"] = spaces, 0, {}
    grid = index["grid"]
    if len(spaces) > index["count"]:
        for idx in range(index["count"], len(spaces)):
            space = spaces[idx]
            bbox = getattr(space, "bbox", None)
            if not bbox:
                continue
            cx, cy = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
            cell = (math.floor(cx / _PARKING_INDEX_CELL_M), math.floor(cy / _PARKING_INDEX_CELL_M))
            grid.setdefault(cell, []).append((idx, space, cx, cy))
        index["count"] = len(spaces)
    found = []
    for cell_x in range(math.floor((x - radius_m) / _PARKING_INDEX_CELL_M), math.floor((x + radius_m) / _PARKING_INDEX_CELL_M) + 1):
        for cell_y in range(math.floor((y - radius_m) / _PARKING_INDEX_CELL_M), math.floor((y + radius_m) / _PARKING_INDEX_CELL_M) + 1):
            found.extend(grid.get((cell_x, cell_y), ()))
    found.sort(key=lambda entry: entry[0])
    yield from found


def _pick_npc_destination_candidates(
    x: float,
    y: float,
    parking_spaces: Optional[List] = None,
    sceneries: Optional[List] = None,
    buildings: Optional[List] = None,
    ways: Optional[List[Way]] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
    search_radius_m: float = NPC_DESTINATION_SEARCH_RADIUS_M,
    limit: int = NPC_PARKING_CANDIDATE_LIMIT,
    other_vehicle_positions: Optional[List[Tuple[float, float]]] = None,
    own_position: Optional[Tuple[float, float]] = None,
) -> List[Tuple[Tuple[float, float], object]]:
    """Every acceptable place to stop near (x, y), in NPC-more.md section
    2's tier order (dedicated space > parking lot > building yard >
    roadside on a quiet street as an explicit last resort), nearest first
    within each tier. A road carriageway/lane/roundabout itself is never
    a candidate at all (section 2's "do NOT treat road carriageways as
    valid parking locations") - roadside parking (tier 5) still returns
    an actual curb-side stopping point, not the bare lane center.

    Returns a *list* rather than a single best guess so a caller can try
    the next-nearest option when the nearest turns out unroutable
    (section 3: "prefer a slightly farther valid parking space over a
    nearby invalid or dangerous location") instead of immediately falling
    back to a lower tier or abandoning this road point altogether.

    Each entry is (point, parking_space) - parking_space is the
    ParkingSpace `point` came from (for the caller to reserve), or None
    for a lot/building yard/roadside point.

    other_vehicle_positions (positions of currently parked/resting
    vehicles): a lot/yard/roadside point is a single fixed coordinate
    derived purely from the target geometry, not its own distinct slot
    like a dedicated ParkingSpace - reused verbatim by every vehicle that
    asks for parking near the same spot unless filtered out here (reported:
    multiple vehicles driving a real trip and parking exactly on top of
    each other). Not applied to the dedicated-space tier, whose entries
    are already individually exclusive via occupied/reserved and can
    legitimately sit closer together than min_spacing_m (adjacent painted
    bays in the same lot).

    own_position (NPC-004 section 4/5): the vehicle's own actual current
    position, used only to identify which parking area (if any) it's
    currently sitting in - a dedicated-space candidate inside that *same*
    area is excluded, so an ordinary errand search never proposes "drive
    across the same parking lot to a different space" as its destination
    (the spec's explicit "must not leave a parking area simply to reach
    another space in the same area" - generating that trip in the first
    place is the actual bug, stronger than merely tolerating it once
    routed). Not applied to the lot/yard/roadside tiers, which already have
    their own vehicle-spacing exclusion above for a different reason.
    """
    radius_sq = search_radius_m * search_radius_m
    own_parking_area = _parking_area_containing(own_position, sceneries)

    # Each tier is only ever scanned if every higher tier came up empty
    # (section 20: no need to walk thousands of buildings when a parking
    # space already covers this point) - "retry the next-nearest option"
    # only matters *within* whichever single tier actually has anything.
    space_candidates = []
    for _idx, space, cx, cy in _parking_spaces_near(parking_spaces, x, y, search_radius_m):
        if getattr(space, "occupied", False) or getattr(space, "reserved", False):
            continue
        dist_sq = (cx - x) ** 2 + (cy - y) ** 2
        if dist_sq > radius_sq:
            continue
        if not _parking_space_fits_vehicle(space):
            continue
        if own_parking_area is not None and _parking_area_containing((cx, cy), [own_parking_area]) is not None:
            continue
        space_candidates.append((dist_sq, (cx, cy), space))

    if space_candidates:
        ordered = space_candidates
    else:
        lot_candidates = []
        for scenery in sceneries or ():
            if getattr(scenery, "kind", None) != "parking":
                continue
            bbox = getattr(scenery, "bbox", None)
            if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
                continue
            cx, cy = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
            dist_sq = (cx - x) ** 2 + (cy - y) ** 2
            if dist_sq <= radius_sq and _point_is_clear_of_vehicles((cx, cy), other_vehicle_positions):
                lot_candidates.append((dist_sq, (cx, cy), None))

        if lot_candidates:
            ordered = lot_candidates
        else:
            building_candidates = []
            for building in buildings or ():
                point = _building_yard_point(building, x, y)
                if point is None:
                    continue
                dist_sq = (point[0] - x) ** 2 + (point[1] - y) ** 2
                if dist_sq <= radius_sq and _point_is_clear_of_vehicles(point, other_vehicle_positions):
                    building_candidates.append((dist_sq, point, None))
            ordered = building_candidates

    ordered.sort(key=lambda c: c[0])
    if not ordered:
        roadside = _roadside_parking_point(x, y, ways, spatial_grid)
        if roadside is not None and _point_is_clear_of_vehicles(roadside, other_vehicle_positions):
            ordered = [(0.0, roadside, None)]

    return [(point, space) for _, point, space in ordered[:limit]]


def _resting_heading(
    x: float, y: float, parking_space, ways: Optional[List[Way]], spatial_grid: Optional[SpatialWayGrid],
) -> float:
    """A reasonable heading for a vehicle sitting at rest at (x, y) - the
    parking space's own long axis (_parking_space_axis - an explicit
    orientation tag if one resolved to a real angle, otherwise the space
    polygon's own longest-edge axis, which is what render/scenery.py's
    draw_parking_spaces actually draws the painted bay outline along), or
    the nearest road's tangent when there's no space at all (a roadside/
    lot/yard point is rarely far from one), or 0.0. Cosmetic only - a
    resting vehicle's footprint is still validated at its actual heading
    (see place_parked_npc), this just picks which valid heading to check.

    Bug fix: this used to check parking_space.orientation directly, which
    stays None for the overwhelming majority of real OSM parking spaces
    (no orientation tag) - reported as "cars not aligning the painted
    lines on the ground when parked", since it then fell through to the
    nearest road's tangent instead of the space's own drawn rectangle.
    _parking_space_axis already has the correct fallback (used for the
    driving approach heading via _align_approach_to_parking_orientation);
    the resting heading just wasn't calling it.
    """
    axis = _parking_space_axis(parking_space)
    if axis is not None:
        return axis
    way, distance = _way_at_point(spatial_grid, ways or [], x, y)
    if way is not None and distance < 20.0 and len(way.points_m) >= 2:
        closest_segment = min(
            zip(way.points_m, way.points_m[1:]),
            key=lambda segment: closest_point_and_dist_to_segment(x, y, *segment[0], *segment[1])[3],
        )
        (ax, ay), (bx, by) = closest_segment
        return math.atan2(by - ay, bx - ax)
    return 0.0


def place_parked_npc(
    vehicle_id: int,
    point: Tuple[float, float],
    parking_space,
    ways: Optional[List[Way]] = None,
    spatial_grid: Optional[SpatialWayGrid] = None,
    curbs: Optional[List[Curb]] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    buildings: Optional[List] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    vehicle_type: str = "car",
    color: Optional[Tuple[int, int, int]] = None,
) -> Optional[NPCVehicle]:
    """NPC-003 sections 5, 20: place a vehicle already at rest at a valid
    parking location - the cheap population-fill path, unlike spawn_npc
    (which plans and validates a whole route to get there). No Driver/
    TripGroup/Resident is created here - an empty parked car doesn't need
    passengers any more than a real one does; spawn_npc creates them once
    this vehicle actually starts a trip (see NPCVehicleManager).

    Returns None if the resting pose fails the same oriented-footprint
    validation spawn_npc's route ultimately checks against (section 20:
    never spawn into an impossible position and hope collision resolves
    it) - the caller tries the next candidate.
    """
    # NPC-003 v2: vehicle_type is a vehicles/ plugin id - dimensions and
    # capacity are plugin data, not a branch here (falls back to "car" for
    # an unknown/unregistered id, the same defensive default spawn_npc's
    # own Car construction implicitly used before plugins existed).
    definition = vehicle_definition(vehicle_type)
    length_m, width_m = definition.length_m, definition.width_m
    heading = _resting_heading(point[0], point[1], parking_space, ways, spatial_grid)
    if not is_vehicle_pose_valid(
        point[0], point[1], heading, curbs=curbs, buildings=buildings,
        curb_grid=curb_grid, building_grid=building_grid,
        length_m=length_m, width_m=width_m,
    ):
        return None
    car = Car(x=point[0], y=point[1], heading=heading, speed=0.0, length_m=length_m, width_m=width_m)
    vehicle = NPCVehicle(
        vehicle_id=vehicle_id,
        car=car,
        state=NPCState.PARKED,
        vehicle_type=vehicle_type,
        color=color if color is not None else random.choice(NPC_VEHICLE_COLORS),
        capacity=definition.capacity,
    )
    if parking_space is not None:
        parking_space.occupied = True
        parking_space.vehicle_id = vehicle_id
        vehicle.destination_parking_space_id = getattr(parking_space, "osm_id", None)
        vehicle.reserved_parking_space = parking_space
    return vehicle


def _pick_npc_destination(
    x: float,
    y: float,
    parking_spaces: Optional[List] = None,
    sceneries: Optional[List] = None,
    buildings: Optional[List] = None,
    search_radius_m: float = NPC_DESTINATION_SEARCH_RADIUS_M,
) -> Tuple[Optional[Tuple[float, float]], object]:
    """The single nearest/best candidate from _pick_npc_destination_candidates
    - a thin convenience wrapper for callers (and tests) that only want
    one answer, not the full fallback list. Returns (None, None) when
    nothing acceptable exists nearby at all."""
    candidates = _pick_npc_destination_candidates(
        x, y, parking_spaces=parking_spaces, sceneries=sceneries, buildings=buildings,
        search_radius_m=search_radius_m, limit=1,
    )
    return candidates[0] if candidates else (None, None)


NPC_ROUTE_MAX_HOPS = 30  # how many real intersections the deterministic NPC's trip crosses
NPC_DESTINATION_CANDIDATE_LIMIT = 40  # cap how many BFS nodes a single spawn attempt will try


def _bfs_destination_order(nodes, edges, origin_index: int, max_hops: int = NPC_ROUTE_MAX_HOPS) -> List[int]:
    """Walk the route graph breadth-first from origin_index for up to
    max_hops steps and return every node reached, farthest-hop first.

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

    Returns every reached node, not just the last one: a single fixed
    destination that turns out invalid (inside a roundabout, a route
    that clips a curb, no parking anywhere nearby) used to make
    spawn_deterministic_npc retry that exact same rejected point forever
    (reported: "no valid route found yet" logged every second, forever).
    The caller tries these candidates in order until one actually spawns.
    """
    visited = {origin_index}
    frontier = [origin_index]
    order: List[int] = []
    for _ in range(max_hops):
        if not frontier:
            break
        next_frontier = []
        for current in frontier:
            for neighbor, _distance in edges.get(current, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
        order.extend(next_frontier)
        frontier = next_frontier
    order.reverse()
    return order


def spawn_deterministic_npc(
    resident_manager: ResidentManager,
    traffic_world: TrafficWorld,
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    vehicle_id: int = 1,
    parking_spaces: Optional[List] = None,
    sceneries: Optional[List] = None,
    buildings: Optional[List] = None,
    curbs: Optional[List[Curb]] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    building_grid: Optional[SpatialWayGrid] = None,
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
    breadth-first walk from there (see _bfs_destination_order) - no
    hard-coded screen coordinates, no randomness.

    The BFS walk only ever lands on a road-graph node - the middle of an
    intersection, a driving lane, possibly a roundabout - never actually a
    place to stop, so _pick_npc_destination_candidates refines it into an
    ordered list of real ones: nearest free parking space, then parking
    lot, then building yard, then (last resort) a roadside spot on a
    quiet street (NPC-more.md section 2) - never the raw point itself.
    Every candidate at this road point is tried, nearest first, before
    moving on to the next BFS-reached node (section 3: prefer a slightly
    farther valid option over a nearby invalid one) - a route turning out
    unroutable (too far off any real road, clips a curb, drives through a
    building) skips to the next candidate rather than giving up the whole
    spawn over one bad one (previously: retried the exact same rejected
    point forever, logging "no valid route found" every second - reported
    bug - or settled for stopping the NPC in the middle of the road, also
    reported).
    """
    nodes = traffic_world._route_nodes
    edges = traffic_world._route_edges
    component = _largest_route_graph_component(nodes, edges)
    if len(component) < 2:
        return None
    origin_index = min(component)
    road_points = _bfs_destination_order(nodes, edges, origin_index)[:NPC_DESTINATION_CANDIDATE_LIMIT]
    if not road_points:
        return None
    origin = (nodes[origin_index][0], nodes[origin_index][1])

    for destination_index in road_points:
        raw_destination = (nodes[destination_index][0], nodes[destination_index][1])
        destination_candidates = _pick_npc_destination_candidates(
            raw_destination[0], raw_destination[1], parking_spaces, sceneries, buildings,
            ways=ways, spatial_grid=spatial_grid,
        )
        for destination, target_space in destination_candidates:
            # The roadside-parking fallback (see _pick_npc_destination_
            # candidates) returns the raw road point completely unchanged -
            # every other tier (space/lot/building yard) always offsets it
            # off the road by construction, so an exact match here can
            # only be that fallback, still meant to be reached in-lane.
            destination_is_off_road = destination != raw_destination
            spawned = spawn_npc(
                vehicle_id, resident_manager, traffic_world, ways, origin, destination,
                spatial_grid=spatial_grid, curbs=curbs, curb_grid=curb_grid,
                buildings=buildings, building_grid=building_grid, parking_space=target_space,
                destination_is_off_road=destination_is_off_road,
            )
            if spawned is not None:
                return spawned
    return None


def continue_npc_trip(
    vehicle: NPCVehicle,
    driver: Driver,
    traffic_world: TrafficWorld,
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    parking_spaces: Optional[List] = None,
    sceneries: Optional[List] = None,
    buildings: Optional[List] = None,
    curbs: Optional[List[Curb]] = None,
    curb_grid: Optional[SpatialWayGrid] = None,
    building_grid: Optional[SpatialWayGrid] = None,
    destination_query_point: Optional[Tuple[float, float]] = None,
    other_vehicle_positions: Optional[List[Tuple[float, float]]] = None,
    time_budget_s: float = NPC_TRIP_START_TIME_BUDGET_S,
) -> bool:
    """multi-passenger-car.md section 21: once a trip group's passengers
    have all reboarded (or update_npc's return-timeout left a straggler
    behind), release this vehicle's parking spot and send it to a new
    destination in place - reusing the exact same destination-selection/
    validation machinery as a brand-new spawn (_pick_npc_destination_
    candidates, _plan_and_validate_npc_route), never a second, parallel
    routing implementation.

    destination_query_point (NPC-003 section 12): a household vehicle
    returning home searches for candidates *around its home position*
    directly - a single well-defined target, not a BFS walk. Every other
    caller (the default, no destination_query_point) BFS-walks the real
    road graph outward from the vehicle's current position first, exactly
    like find_and_start_npc_trip's brand-new-trip search, and only then
    runs the tiered space > lot > yard > roadside search around each
    reached point in turn.

    That BFS walk matters: searching "nearest available parking" directly
    around wherever the vehicle just parked routinely finds another empty
    space in that exact same lot (lots have many close-together spaces,
    far closer than any other real destination) - reported as "cars
    driving from spot to spot within one parking area". Walking the road
    graph out a few real intersections first guarantees the next errand
    is a genuinely separate trip, the same way a brand-new spawn already
    is.

    Mutates `driver`/`vehicle` in place (same Resident group, same vehicle
    identity - only the route changes) and returns whether a next
    destination was actually found. False leaves the vehicle parked to
    try again on a later call, the same "don't get stuck on one bad
    candidate forever" fallback spawn_deterministic_npc already uses for
    a brand-new trip.
    """
    origin = (vehicle.car.x, vehicle.car.y)
    if destination_query_point is not None:
        query_points = [destination_query_point]
    else:
        origin_index = _nearest_route_node_index(traffic_world, origin[0], origin[1])
        if origin_index is None:
            return False
        nodes = traffic_world._route_nodes
        edges = traffic_world._route_edges
        road_points = _bfs_destination_order(nodes, edges, origin_index)[:NPC_TRIP_START_CANDIDATE_POINTS]
        query_points = [(nodes[index][0], nodes[index][1]) for index in road_points]
        if not query_points:
            return False

    # NPC-003 v2: plan_route's own cost against real dense OSM data is
    # highly variable and can genuinely run past a second for a real,
    # multi-hop-away destination (the whole point of the BFS walk above -
    # see this session's find_and_start_npc_trip, which faces the exact
    # same cost and already budgets it the same way). Checked between
    # candidates only (Python has no preemption for a single already-
    # running plan_route call) - a single unusually expensive call can
    # still occasionally exceed this, a known limitation shared with
    # find_and_start_npc_trip.
    deadline = time.perf_counter() + time_budget_s
    for query_point in query_points:
        if time.perf_counter() > deadline:
            break
        destination_candidates = _pick_npc_destination_candidates(
            query_point[0], query_point[1], parking_spaces, sceneries, buildings,
            ways=ways, spatial_grid=spatial_grid, other_vehicle_positions=other_vehicle_positions,
            own_position=origin,
        )
        for destination, target_space in destination_candidates:
            if time.perf_counter() > deadline:
                break
            destination_is_off_road = destination != query_point
            path = _plan_and_validate_npc_route(
                traffic_world, ways, origin, destination, spatial_grid=spatial_grid,
                curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
                parking_space=target_space, destination_is_off_road=destination_is_off_road,
                deadline=deadline,
            )
            if path is None:
                continue
            release_npc_parking_reservation(vehicle)
            vehicle.destination = destination
            vehicle.travel_route = [(p.x, p.y) for p in path]
            vehicle.destination_parking_space_id = None
            vehicle.state = NPCState.CRUISING
            vehicle.debug_waiting_for = ""
            if target_space is not None:
                target_space.reserved = True
                target_space.vehicle_id = vehicle.vehicle_id
                vehicle.destination_parking_space_id = getattr(target_space, "osm_id", None)
                vehicle.reserved_parking_space = target_space
            driver.path = path
            driver.path_index = 1
            driver.route_segment_index = 0
            driver.route_segment_t = 0.0
            driver.steering_input = 0.0
            driver.destination = destination
            driver.current_way = path[0].way
            if vehicle.trip_group is not None:
                # Reset per-stop bookkeeping for the next park-visit-return
                # cycle (section 21's Destination A -> B -> C loop) - a fresh
                # activity duration and destination entrance, a fresh wait
                # deadline once parked again.
                vehicle.trip_group.activity_duration_s = random.uniform(
                    NPC_BUILDING_VISIT_MIN_S, NPC_BUILDING_VISIT_MAX_S
                )
                vehicle.trip_group.activity_type = random.choice(NPC_TRIP_ACTIVITY_TYPES)
                vehicle.trip_group.destination_entrance = None
                vehicle.trip_group.wait_deadline_sim_time = None
            return True
    return False


class NPCVehicleManager:
    """NPC-003: owns the whole NPC vehicle population - the same role
    pedestrian.PedestrianManager plays for pedestrians. Replaces
    main.py's old "spawn exactly one NPC, retry forever if it fails"
    logic with a real, persistent, gradually-filled population of
    parked/driving/household/traffic vehicles.

    Vehicles never disappear just because they're far from the player
    (section 18) - only a genuinely idle, currently-parked vehicle far
    beyond despawn_radius_m is ever removed (section 19: never mid-trip,
    never with passengers out), and even then it's replaced by fresh
    population fill elsewhere, not left permanently below target.
    """

    def __init__(
        self,
        target_count: int = 40,
        min_count: Optional[int] = None,
        max_count: Optional[int] = None,
        household_fraction: float = NPC_HOUSEHOLD_VEHICLE_FRACTION,
        spawn_radius_m: float = NPC_VEHICLE_SPAWN_RADIUS_M,
        despawn_radius_m: float = NPC_VEHICLE_DESPAWN_RADIUS_M,
        simulation_radius_m: float = NPC_VEHICLE_SIMULATION_RADIUS_M,
        vehicle_distribution: Optional[Dict[str, float]] = None,
        include_experimental: bool = False,
        target_moving_fraction: float = NPC_TARGET_MOVING_FRACTION,
    ) -> bool:
        self.vehicles: List[NPCVehicle] = []
        self.drivers: Dict[int, Driver] = {}
        self.accidents: List[Tuple[float, float]] = []  # crash positions for the sound, drained by the simulation
        self.household_manager = HouseholdManager()
        self.target_count = target_count
        self.min_count = min_count if min_count is not None else max(1, int(target_count * 0.6))
        self.max_count = max_count if max_count is not None else max(self.min_count, int(target_count * 1.5))
        self.household_fraction = household_fraction
        # NPC-005: a *stable* target (target_count's own steady-state
        # size), not derived from the momentarily-fluctuating current
        # vehicle count - see _run_population_tick's trip-start step.
        self.target_moving_count = max(1, int(target_count * target_moving_fraction))
        self.spawn_radius_m = spawn_radius_m
        self.despawn_radius_m = despawn_radius_m
        self.simulation_radius_m = simulation_radius_m
        self._trip_start_failures: Dict[int, int] = {}
        self._trip_retry_after_tick: Dict[int, int] = {}
        self._population_tick_number = 0
        self._route_jobs: List[dict] = []
        self._route_job_cursor = 0
        self._route_job_frame = 0
        self.route_job_stats = {
            "queued": 0, "ready": 0, "failed": 0, "stale": 0, "discarded": 0,
            "max_frame_ms": 0.0, "waits_frames": collections.deque(maxlen=2000),
        }
        self.population_diagnostics = {
            "trip_start_attempts": 0, "successful_trip_starts": 0,
            "route_generation_failures": 0, "route_validation_failures": 0,
            "vehicles_waiting_for_trips": 0, "population_update_duration_s": 0.0,
        }
        self._previous_player_pose: Optional[Tuple[float, float, float]] = None
        self.include_experimental = include_experimental
        # NPC-003 v2 section 14: vehicle_type is picked from the registered
        # road-vehicle plugins' own traffic_weight, not a hardcoded "always
        # car" - a caller (main.py) may override with its own {id: weight}
        # (e.g. config's vehicle_distribution), defaulting to None here to
        # mean "use each plugin's own default weight". An explicit override
        # always wins - include_experimental only gates the *default*
        # distribution (e.g. motorcycle, off unless [experimental]
        # enable_two_wheelers is set - see _default_vehicle_distribution).
        self.vehicle_distribution = (
            vehicle_distribution if vehicle_distribution is not None else self._default_vehicle_distribution()
        )
        self._next_vehicle_id = 1
        # Fires on the very first update() rather than waiting a full
        # NPC_POPULATION_TICK_S - main.py's loading screen already gets an
        # initial fill (see populate_initial), this only matters for
        # topping up afterwards.
        self._population_elapsed = NPC_POPULATION_TICK_S
        # Reused (not reimplemented) spatial index (physics.SpatialWayGrid
        # already indexes anything with .bbox or .x/.y) - lights up
        # render/vehicles.py's existing draw_npc_spatial_grid debug view,
        # and is available for spawn-time overlap checks.
        self.spatial_grid = SpatialWayGrid(cell_size=100.0)

    def _default_vehicle_distribution(self) -> Dict[str, float]:
        return {
            definition.id: definition.traffic_weight
            for definition in VEHICLE_DEFINITIONS.values()
            if definition.is_road_vehicle and (self.include_experimental or not definition.experimental)
        }

    def _pick_vehicle_type(self) -> str:
        """Weighted choice among road-vehicle plugins with a positive
        weight (NPC-003 v2 section 14) - falls back to "car" if every
        weight is zero (e.g. an all-zero override) so population fill
        never silently stalls."""
        ids = [vehicle_id for vehicle_id, weight in self.vehicle_distribution.items() if weight > 0.0]
        weights = [self.vehicle_distribution[vehicle_id] for vehicle_id in ids]
        if not ids:
            return "car"
        return random.choices(ids, weights=weights, k=1)[0]

    def _next_id(self) -> int:
        vehicle_id = self._next_vehicle_id
        self._next_vehicle_id += 1
        return vehicle_id

    def rebuild_spatial_grid(self) -> None:
        # SpatialWayGrid gives point-like objects a synthetic ``bbox`` the
        # first time they are inserted.  NPC vehicles move, so that cached
        # point must be refreshed before every rebuild; otherwise avoidance
        # and collision queries keep looking near the car's old position.
        # This was visible in captures as two CRUISING cars only 0.81 m
        # apart while neither appeared in the other's candidate query.
        for vehicle in self.vehicles:
            vehicle.bbox = (vehicle.x, vehicle.y, vehicle.x, vehicle.y)
        self.spatial_grid.rebuild(self.vehicles)

    def nearby_vehicles_at(self, x: float, y: float, radius_m: float = 30.0) -> List[NPCVehicle]:
        return self.spatial_grid.ways_in_rect(x - radius_m, y - radius_m, x + radius_m, y + radius_m)

    def population_counts(self) -> Dict[str, int]:
        """Section 25/26's population statistics panel."""
        counts = {
            "total": len(self.vehicles),
            "parked": 0,
            "driving": 0,
            "reserved": 0,
            "household": 0,
            "autonomous": 0,
            # NPC-005: the *target*, not just the current count - the F7
            # panel showing both side by side is what makes "roads full
            # of parked cars" a visible, diagnosable number instead of a
            # vibe. getattr-guarded: population_counts() must stay safe
            # against a manager built via __new__ with only .vehicles set
            # (test_shadow_entities_render.py's shadow-object pattern).
            "moving_target": getattr(self, "target_moving_count", 0),
            "road_rage": 0,
            "trip_start_attempts": getattr(self, "population_diagnostics", {}).get("trip_start_attempts", 0),
            "successful_trip_starts": getattr(self, "population_diagnostics", {}).get("successful_trip_starts", 0),
            "route_failures": getattr(self, "population_diagnostics", {}).get("route_generation_failures", 0),
            "waiting_for_trips": getattr(self, "population_diagnostics", {}).get("vehicles_waiting_for_trips", 0),
        }
        for vehicle in self.vehicles:
            if vehicle.vehicle_kind == "household":
                counts["household"] += 1
            else:
                counts["autonomous"] += 1
            if vehicle.availability == NPCAvailability.RESERVED:
                counts["reserved"] += 1
            if vehicle.state == NPCState.PARKED:
                counts["parked"] += 1
            elif vehicle.state != NPCState.CRASHED:
                counts["driving"] += 1
            driver = getattr(self, "drivers", {}).get(vehicle.vehicle_id)
            if driver is not None and driver.road_rage_until_sim_time is not None:
                counts["road_rage"] += 1
        return counts

    def population_counts_by_type(self) -> Dict[str, int]:
        """NPC-003 v2 section 22's debug "vehicles by plugin type" line."""
        counts: Dict[str, int] = {}
        for vehicle in self.vehicles:
            counts[vehicle.vehicle_type] = counts.get(vehicle.vehicle_type, 0) + 1
        return counts

    def trigger_road_rage(self, x: float, y: float, heading: float, sim_time: float) -> Optional[int]:
        """NPC-005: the player's rage-shout/horn action reaches exactly
        one real driver - the single nearest currently-driving vehicle
        ahead (nearest_vehicle_ahead's same forward-cone projection
        NPC-004's own following-distance avoidance already uses, just
        wider - see the NPC_ROAD_RAGE_* constants' comment). That driver
        yields (update_npc clamps its speed while road_rage_until_sim_time
        is in the future); any queue that forms behind it is the existing
        avoidance logic reacting to *that* vehicle slowing down, not
        anything scripted here - this function only ever touches the one
        vehicle it finds, never a whole area.

        Returns the reacting vehicle's id, or None if nothing was ahead
        to react."""
        driving_vehicles = [
            vehicle for vehicle in self.vehicles
            if vehicle.state not in (NPCState.PARKED, NPCState.CRASHED)
            and self.drivers.get(vehicle.vehicle_id) is not None
        ]
        lead = nearest_vehicle_ahead(
            x, y, heading, driving_vehicles,
            detection_distance_m=NPC_ROAD_RAGE_DETECTION_DISTANCE_M,
            lateral_limit_m=NPC_ROAD_RAGE_LATERAL_LIMIT_M,
        )
        if lead is None:
            return None
        _, vehicle = lead
        driver = self.drivers[vehicle.vehicle_id]
        driver.road_rage_until_sim_time = sim_time + NPC_ROAD_RAGE_REACTION_DURATION_S
        return vehicle.vehicle_id

    def request_vehicle(
        self, household: Household, passengers: int = 1, purpose: Optional[str] = None,
    ) -> Optional[NPCVehicle]:
        """NPC-003 v2 section 10: the one generic entry point a future
        Resident shopping/errand system calls - "find a vehicle that can
        carry N Residents [and is suitable for `purpose`], reserve it
        atomically". Does not implement the shopping system itself (see
        the spec's own closing line), only the vehicle-selection/
        reservation half of it.

        Selection is plugin-capability-driven (can_carry_passengers,
        get_passenger_capacity, can_be_used_for_errands), never a branch
        on vehicle_type - the caller never needs to know whether the
        winning vehicle is a car or a van."""
        for vehicle_id in household.vehicle_ids:
            vehicle = next((v for v in self.vehicles if v.vehicle_id == vehicle_id), None)
            if vehicle is None or vehicle.availability != NPCAvailability.AVAILABLE:
                continue
            definition = vehicle_definition(vehicle.vehicle_type)
            if not definition.passenger_eligible:
                continue
            if definition.capacity < passengers:
                continue
            if purpose is not None and not definition.errand_eligible:
                continue
            if reserve_household_vehicle(vehicle):
                return vehicle
        return None

    def _claimed_vehicle_points(self) -> List[Tuple[int, Tuple[float, float]]]:
        """Every position a vehicle currently occupies, is already headed
        for, or calls home - see _run_population_tick's own comment (right
        before its identically-built claimed_points) for the full
        rationale. Shared with _place_one: population growth placing a
        brand-new vehicle must not use a vehicle's own *current position*
        as "is this spot free" - a spot another vehicle just drove away
        from (mid-trip, .destination pointing back at it, e.g. a plain
        errand that happens to return where it started, or any household
        vehicle's home) looks completely vacant by that measure alone, and
        used to get a brand-new car placed directly into it (reported: a
        car returning to a yard found another car had, in the meantime,
        been spawned right into its spot)."""
        claimed = []
        for v in self.vehicles:
            if v.state == NPCState.PARKED:
                claimed.append((v.vehicle_id, (v.x, v.y)))
            elif v.destination is not None:
                claimed.append((v.vehicle_id, v.destination))
            if v.home_position is not None:
                claimed.append((v.vehicle_id, v.home_position))
        return claimed

    def _place_one(
        self,
        point: Tuple[float, float],
        parking_space,
        ways: List[Way],
        spatial_grid: Optional[SpatialWayGrid],
        curbs: Optional[List[Curb]],
        curb_grid: Optional[SpatialWayGrid],
        buildings: Optional[List],
        building_grid: Optional[SpatialWayGrid],
        vehicle_type: Optional[str] = None,
    ) -> Optional[NPCVehicle]:
        """Place one new parked vehicle - a thin wrapper around
        place_parked_npc that also rejects a spot too close to a vehicle
        already placed earlier in this same population batch (see
        NPC_MIN_VEHICLE_SPACING_M, also used by _pick_npc_destination_
        candidates for the same reason)."""
        claimed = [pos for _, pos in self._claimed_vehicle_points()]
        if not _point_is_clear_of_vehicles(point, claimed):
            return None
        return place_parked_npc(
            self._next_id(), point, parking_space, ways=ways, spatial_grid=spatial_grid,
            curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
            vehicle_type=vehicle_type or self._pick_vehicle_type(),
        )

    def _make_household(self, vehicle: NPCVehicle, resident_manager: ResidentManager) -> None:
        # NPC-003 v2 section 14: not every vehicle plugin is eligible for
        # household ownership (a truck/bus rolled into the household
        # fraction just stays a plain traffic vehicle instead).
        if not vehicle_definition(vehicle.vehicle_type).household_eligible:
            return
        # Section 9: a household can own two vehicles, not only one - most
        # of the time this vehicle founds a brand new household, but it
        # may instead join an existing one that still has room.
        joinable = [
            household for household in self.household_manager.households.values()
            if len(household.vehicle_ids) < NPC_MAX_VEHICLES_PER_HOUSEHOLD
        ]
        if joinable and random.random() < NPC_SECOND_HOUSEHOLD_VEHICLE_PROBABILITY:
            household = random.choice(joinable)
        else:
            household = self.household_manager.create(home_position=(vehicle.x, vehicle.y))
            household_size = random.randint(1, min(4, vehicle.capacity))
            members = [resident_manager.create(mode="household") for _ in range(household_size)]
            for member in members:
                member.household_id = household.household_id
                household.member_resident_ids.add(member.resident_id)
        household.vehicle_ids.add(vehicle.vehicle_id)
        vehicle.vehicle_kind = "household"
        vehicle.household_id = household.household_id
        # A joined second vehicle keeps its own actual parked position as
        # its home, not the household's first vehicle's spot - a real
        # second car isn't necessarily parked in the same place either.
        vehicle.home_position = (vehicle.x, vehicle.y)
        vehicle.home_parking_space = vehicle.reserved_parking_space

    def populate_initial(
        self,
        player_x: float,
        player_y: float,
        resident_manager: ResidentManager,
        ways: List[Way],
        spatial_grid: Optional[SpatialWayGrid] = None,
        parking_spaces: Optional[List] = None,
        sceneries: Optional[List] = None,
        buildings: Optional[List] = None,
        curbs: Optional[List[Curb]] = None,
        curb_grid: Optional[SpatialWayGrid] = None,
        building_grid: Optional[SpatialWayGrid] = None,
        progress_callback=None,
    ) -> None:
        """Fill the population up to target_count once, at load time (main.
        py calls this from _load_world, the same place the game's other
        slow one-time init steps already report loading-screen progress)-
        not a per-frame concern, so a plain loop here is fine; ongoing
        top-up during play still goes through the small per-tick budget in
        update() (section 23: never spawn a large number in one frame of
        actual gameplay)."""
        attempts = 0
        max_attempts = self.target_count * 6
        while len(self.vehicles) < self.target_count and attempts < max_attempts:
            attempts += 1
            angle = random.uniform(0.0, 2.0 * math.pi)
            radius = random.uniform(0.0, self.spawn_radius_m)
            qx = player_x + math.cos(angle) * radius
            qy = player_y + math.sin(angle) * radius
            candidates = _pick_npc_destination_candidates(
                qx, qy, parking_spaces, sceneries, buildings, ways=ways, spatial_grid=spatial_grid,
            )
            if not candidates:
                continue
            point, parking_space = candidates[0]
            if (point[0] - player_x) ** 2 + (point[1] - player_y) ** 2 > (self.spawn_radius_m + NPC_SPAWN_RADIUS_SLACK_M) ** 2:
                # The nearest parking to a random query point can be far
                # away in a sparse area - a car spawned beyond the
                # simulation radius is inert and just gets despawned.
                continue
            vehicle = self._place_one(
                point, parking_space, ways, spatial_grid, curbs, curb_grid, buildings, building_grid,
            )
            if vehicle is None:
                continue
            if random.random() < self.household_fraction:
                self._make_household(vehicle, resident_manager)
            self.vehicles.append(vehicle)
            if progress_callback is not None:
                progress_callback(len(self.vehicles) / self.target_count)
        self.rebuild_spatial_grid()

    def _retire_trip(self, vehicle: NPCVehicle) -> None:
        """A trip is fully over (a household vehicle just arrived home, or
        - defensively - a vehicle with no group somehow still had a
        driver): release the driver and let it sit idle until the next
        population-tick roll (or a future Resident-trip reservation)
        sends it out again. The Residents themselves are untouched -
        still real, still remembering their household/trip_group_id -
        only the vehicle's own bookkeeping resets."""
        self.drivers.pop(vehicle.vehicle_id, None)
        vehicle.trip_group = None
        vehicle.returning_home = False
        vehicle.availability = NPCAvailability.AVAILABLE
        vehicle.owner_id = None
        vehicle.destination = None

    def _check_vehicle_collision(
        self,
        vehicle: NPCVehicle,
        nearby_obstacles: List,
        resident_manager: ResidentManager,
        pedestrian_mgr: object,
        sim_time: float,
        previous_vehicle_pose: Optional[Tuple[float, float, float]] = None,
        previous_obstacle_poses: Optional[Dict[int, Tuple[float, float, float]]] = None,
    ) -> None:
        """NPC-004 section 9/10/11: pairwise oriented-box overlap test
        against `nearby_obstacles` (already spatially bounded by the
        caller - never all-to-all). `nearby_obstacles` may hold other
        `NPCVehicle`s and/or the player's own `Car` (same x/y/heading/
        length_m/width_m duck type either way, so one test handles both
        NPC-NPC and NPC-taxi). A CRASHED vehicle remains solid: another NPC
        hitting the wreck must stop and crash as well. Only a pair in which
        both vehicles are already crashed is skipped, preventing repeated
        accident/occupant processing without turning wrecks into ghosts."""
        vehicle_already_crashed = vehicle.state == NPCState.CRASHED
        for obstacle in nearby_obstacles:
            if obstacle is vehicle:
                continue
            obstacle_is_npc = isinstance(obstacle, NPCVehicle)
            obstacle_already_crashed = obstacle_is_npc and obstacle.state == NPCState.CRASHED
            if vehicle_already_crashed and obstacle_already_crashed:
                continue  # the already-resolved wreck pair needs no response
            other_previous = (previous_obstacle_poses or {}).get(id(obstacle))
            hit = boxes_intersect(
                vehicle.x, vehicle.y, vehicle.heading, vehicle.length_m, vehicle.width_m,
                obstacle.x, obstacle.y, obstacle.heading,
                getattr(obstacle, "length_m", NPC_VEHICLE_LENGTH_M), getattr(obstacle, "width_m", NPC_VEHICLE_WIDTH_M),
            )
            if not hit and previous_vehicle_pose is not None and other_previous is not None:
                # Cheap swept narrow phase: interpolate both oriented boxes
                # together. Candidate selection is still spatially bounded;
                # sampling count grows only with this frame's displacement.
                travel = max(
                    math.hypot(vehicle.x - previous_vehicle_pose[0], vehicle.y - previous_vehicle_pose[1]),
                    math.hypot(obstacle.x - other_previous[0], obstacle.y - other_previous[1]),
                )
                steps = min(12, max(1, math.ceil(travel / max(0.5, min(vehicle.width_m, getattr(obstacle, "width_m", 1.8)) * 0.5))))
                for step in range(1, steps):
                    t = step / steps
                    ax = previous_vehicle_pose[0] + (vehicle.x - previous_vehicle_pose[0]) * t
                    ay = previous_vehicle_pose[1] + (vehicle.y - previous_vehicle_pose[1]) * t
                    ah = previous_vehicle_pose[2] + (angle_diff(vehicle.heading, previous_vehicle_pose[2])) * t
                    bx = other_previous[0] + (obstacle.x - other_previous[0]) * t
                    by = other_previous[1] + (obstacle.y - other_previous[1]) * t
                    bh = other_previous[2] + (angle_diff(obstacle.heading, other_previous[2])) * t
                    if boxes_intersect(ax, ay, ah, vehicle.length_m, vehicle.width_m, bx, by, bh,
                                       getattr(obstacle, "length_m", NPC_VEHICLE_LENGTH_M),
                                       getattr(obstacle, "width_m", NPC_VEHICLE_WIDTH_M)):
                        hit = True
                        break
            if not hit:
                continue

            # Resolve at the last known non-penetrating frame pose. Detection
            # without response merely marks an NPC crashed while the taxi
            # continues through it; keeping crashed vehicles collidable with
            # the player also prevents passage on following frames.
            if previous_vehicle_pose is not None:
                vehicle.car.x, vehicle.car.y, vehicle.car.heading = previous_vehicle_pose
            vehicle.car.speed = 0.0
            if other_previous is not None:
                if obstacle_is_npc:
                    obstacle.car.x, obstacle.car.y, obstacle.car.heading = other_previous
                else:
                    obstacle.x, obstacle.y, obstacle.heading = other_previous
            if obstacle_is_npc:
                obstacle.car.speed = 0.0
            elif hasattr(obstacle, "speed"):
                obstacle.speed = 0.0

            self.accidents.append((vehicle.car.x, vehicle.car.y))
            if not vehicle_already_crashed:
                self._trigger_vehicle_accident(vehicle, resident_manager, pedestrian_mgr, sim_time)
            if obstacle_is_npc and obstacle.state != NPCState.CRASHED:
                self._trigger_vehicle_accident(obstacle, resident_manager, pedestrian_mgr, sim_time)
            return True
        return False

    def _trigger_vehicle_accident(
        self,
        vehicle: NPCVehicle,
        resident_manager: ResidentManager,
        pedestrian_mgr: object,
        sim_time: float,
    ) -> None:
        """NPC-004 sections 10-19: stop the vehicle, sever its driver link
        permanently (driver_departed - checked by reserve_household_vehicle
        and the idle/ready-vehicle filters above so nothing ever resumes or
        reassigns this vehicle), and turn every Resident actually aboard at
        the moment of impact (driver and any passengers) into ordinary
        pedestrians who walk away from the wreck; only the driver calls for help.
        A vehicle with no active driver (e.g. rear-ended while genuinely
        idle-parked) still becomes a stopped obstacle, just without anyone
        to eject - nobody was aboard.

        NPC-005: this is also where a live trip_group gets resolved before
        the vehicle can ever despawn - despawn only requires "no driver in
        self.drivers", so leaving passengers dangling in vehicle.trip_group
        here would let a later despawn silently discard them (Definition of
        Done: "Vehicle removal cannot orphan occupants")."""
        if vehicle.state == NPCState.CRASHED:
            return  # already an accident - never re-triggers (section 18)
        was_driving = has_active_driver(vehicle, resident_manager)
        driver_resident_id = vehicle.owner_id
        trip_group = vehicle.trip_group
        group_member_ids = list(trip_group.member_resident_ids) if trip_group is not None else []
        boarded_ids = set(trip_group.boarded_resident_ids) if trip_group is not None else set()

        # Only people physically aboard may be materialized beside the wreck.
        # A trip's full member roster can also contain people who are already
        # outside visiting a building; spawning that roster duplicated those
        # pedestrians.  Keep the active driver first, deduplicate corrupt or
        # legacy rosters, and enforce the vehicle's seat count defensively.
        occupant_candidates: List[int] = []
        if was_driving and driver_resident_id is not None:
            occupant_candidates.append(driver_resident_id)
        occupant_candidates.extend(
            resident_id for resident_id in group_member_ids if resident_id in boarded_ids
        )
        occupant_candidates.extend(
            resident_id for resident_id in boarded_ids if resident_id not in group_member_ids
        )
        occupant_ids: List[int] = []
        seen_occupant_ids: Set[int] = set()
        for resident_id in occupant_candidates:
            if resident_id in seen_occupant_ids:
                continue
            seen_occupant_ids.add(resident_id)
            occupant_ids.append(resident_id)
            if len(occupant_ids) >= max(1, vehicle.capacity):
                break

        vehicle.car.speed = 0.0
        vehicle.state = NPCState.CRASHED
        vehicle.driver_departed = True
        vehicle.debug_waiting_for = "accident"
        vehicle.crashed_timer = 0.0
        release_npc_parking_reservation(vehicle)
        self.drivers.pop(vehicle.vehicle_id, None)
        vehicle.trip_group = None

        # Resolve every roster link even when no pedestrian manager is
        # available.  Non-boarded members already exist outside the car and
        # must not be cloned; over-capacity legacy members are detached too.
        linked_resident_ids = set(group_member_ids) | boarded_ids
        if driver_resident_id is not None:
            linked_resident_ids.add(driver_resident_id)
        for resident_id in linked_resident_ids:
            resident = resident_manager.get(resident_id)
            if resident is not None:
                resident.trip_group_id = None
                if resident.active_vehicle_id == vehicle.vehicle_id:
                    resident.active_vehicle_id = None

        if pedestrian_mgr is None:
            return
        family_walks = {}
        for index, resident_id in enumerate(occupant_ids):
            # NPC-004 section 15: the same passenger-side offset
            # PedestrianManager._vehicle_entry_position already uses for
            # boarding/alighting - a walkable point beside the car, never
            # inside it or in the lane it's blocking. Staggered per occupant
            # so a multi-passenger crash doesn't spawn everyone on top of
            # each other.
            exit_offset = vehicle.width_m * 0.5 + 1.0 + index * 0.6
            exit_x = vehicle.x - math.sin(vehicle.heading) * exit_offset
            exit_y = vehicle.y + math.cos(vehicle.heading) * exit_offset
            is_driver = resident_id == driver_resident_id
            exit_heading = vehicle.heading if is_driver else random.uniform(-math.pi, math.pi)
            pedestrian = pedestrian_mgr.spawn_pedestrian_at(
                exit_x, exit_y, heading=exit_heading, resident_id=resident_id,
            )
            if pedestrian is None:
                continue
            pedestrian_mgr.add_pedestrian(pedestrian)
            pedestrian.mood = "annoyed"
            resident = resident_manager.get(resident_id)
            household_id = resident.household_id if resident is not None else None
            family_leader = family_walks.get(household_id) if household_id is not None else None
            if family_leader is not None:
                pedestrian.heading = family_leader.heading
                pedestrian.direction = family_leader.direction
                pedestrian.route = list(family_leader.route) if family_leader.route is not None else None
                pedestrian.current_route_segment = family_leader.current_route_segment
                pedestrian.destination = family_leader.destination
            elif household_id is not None:
                family_walks[household_id] = pedestrian

            # Only the driver calls for help. Passengers remain ordinary
            # pedestrians; unrelated passengers keep independently chosen
            # directions, while household members copied their family route.
            if is_driver:
                destination = pedestrian.destination
                pedestrian.activity = ActivityInstance(
                    plugin_id="phone_usage",
                    location=ActivityLocation(x=destination[0], y=destination[1]) if destination is not None else None,
                    started_sim_time=sim_time,
                )
                pedestrian.state = "walking_to_activity"

    def _handle_parked_vehicle(self, vehicle: NPCVehicle) -> None:
        """Per-frame, cheap only: retirement checks that need to happen
        the instant a vehicle parks. Deciding and routing to the *next*
        destination is deliberately NOT done here - continue_npc_trip's
        BFS-walk-then-plan_route search costs well over a second against
        real dense OSM data (measured), so calling it the instant every
        frame a parked, all-aboard vehicle is seen would be exactly the
        kind of per-frame cost this project has already had to fix once
        (see is_vehicle_pose_valid's own throttling). Instead,
        _run_population_tick's own staggered, budget-capped tick (already
        the pattern this whole population system uses for every other
        expensive, occasional decision) picks up "parked, all aboard,
        ready to continue" vehicles a few at a time (its own step 4,
        bounded by NPC_CONTINUE_TRIP_ATTEMPTS_PER_TICK)."""
        if vehicle.trip_group is None:
            self._retire_trip(vehicle)
            return
        if vehicle.vehicle_kind == "household" and vehicle.returning_home:
            # Arrived home (section 12) - the trip is simply over, no
            # building-visit detour the way an ordinary errand stop gets;
            # the household's residents are already accounted for, they
            # don't need to "visit" their own home as a timed activity.
            self._retire_trip(vehicle)

    def _replaceable_parked_vehicle(
        self, player_x: float, player_y: float, viewport_bounds: Optional[Tuple[float, float, float, float]],
    ) -> Optional[NPCVehicle]:
        """The idle, driverless, unseen parked vehicle farthest from the
        player - safe to drop to make room for moving traffic (no occupants:
        nothing is aboard a parked vehicle with no driver/trip_group)."""
        best, best_distance = None, -1.0
        for vehicle in self.vehicles:
            if (
                vehicle.state != NPCState.PARKED
                or self.drivers.get(vehicle.vehicle_id) is not None
                or vehicle.trip_group is not None
                or vehicle.vehicle_kind == "household"
            ):
                continue
            if viewport_bounds is not None and _point_in_viewport(vehicle.x, vehicle.y, viewport_bounds):
                continue
            distance = (vehicle.x - player_x) ** 2 + (vehicle.y - player_y) ** 2
            if distance > best_distance:
                best, best_distance = vehicle, distance
        return best

    def _short_transit_trip_steps(
        self,
        vehicle: NPCVehicle,
        origin: Tuple[float, float],
        resident_manager: ResidentManager,
        traffic_world: TrafficWorld,
        ways: List[Way],
        spatial_grid: Optional[SpatialWayGrid],
        parking_spaces: Optional[List],
        sceneries: Optional[List],
        buildings: Optional[List],
        curbs: Optional[List[Curb]],
        curb_grid: Optional[SpatialWayGrid],
        building_grid: Optional[SpatialWayGrid],
        claimed_points: List[Tuple[int, Tuple[float, float]]],
        through_point: Optional[Tuple[float, float]] = None,
    ) -> RouteSteps:
        """Start `vehicle` on a validated trip to a real parking spot 80-200m
        from `origin`. Route validation cost and failure rate both grow
        with route length on dense real maps (measured: ~15ms/35% pass at
        100m vs ~70ms/5% at 800m), so a spawn that must succeed inside a
        frame budget picks near destinations - find_and_start_npc_trip's
        BFS walk deliberately picks *far* ones."""
        nodes = traffic_world._route_nodes
        grid = traffic_world._route_node_grid
        cell_size = _ROUTE_NODE_GRID_CELL_M
        reach = NPC_TRANSIT_TRIP_MAX_DISTANCE_M
        near = []
        for cell_x in range(math.floor((origin[0] - reach) / cell_size), math.floor((origin[0] + reach) / cell_size) + 1):
            for cell_y in range(math.floor((origin[1] - reach) / cell_size), math.floor((origin[1] + reach) / cell_size) + 1):
                for index in grid.get((cell_x, cell_y), ()):
                    distance = math.hypot(nodes[index][0] - origin[0], nodes[index][1] - origin[1])
                    if NPC_TRANSIT_TRIP_MIN_DISTANCE_M <= distance <= reach:
                        near.append(index)
        # Transit exists to become traffic the player can encounter. The old
        # random ordering frequently selected a destination sideways from or
        # behind the off-screen origin, so a successfully spawned car drove
        # farther away and still satisfied the global moving count. Prefer
        # reachable nodes nearer the player; validation below remains exactly
        # the same and a random fallback preserves operation on sparse graphs.
        random.shuffle(near)
        if through_point is not None:
            origin_distance = math.hypot(origin[0] - through_point[0], origin[1] - through_point[1])
            approaching = [
                index for index in near
                if math.hypot(nodes[index][0] - through_point[0], nodes[index][1] - through_point[1])
                < origin_distance - 20.0
            ]
            if approaching:
                approaching.sort(key=lambda index: math.hypot(
                    nodes[index][0] - through_point[0], nodes[index][1] - through_point[1],
                ))
                approaching_ids = set(approaching)
                near = approaching + [index for index in near if index not in approaching_ids]
        edges = traffic_world._route_edges
        other_positions = [pos for _, pos in claimed_points]
        for index in near:
            yield
            # Midway along an edge (not the node itself, an intersection
            # centre) on a quiet street: legal roadside parking, an on-road
            # destination - the off-road lot/space tiers are what fail
            # validation almost every time on real maps.
            neighbors = [n for n, length in edges.get(index, ()) if length >= 20.0]
            if not neighbors:
                continue
            other = nodes[random.choice(neighbors)]
            destination = ((nodes[index][0] + other[0]) / 2.0, (nodes[index][1] + other[1]) / 2.0)
            if _roadside_parking_point(destination[0], destination[1], ways, spatial_grid) is None:
                continue
            if not _point_is_clear_of_vehicles(destination, other_positions):
                continue
            path = yield from _plan_and_validate_npc_route_steps(
                traffic_world, ways, (vehicle.car.x, vehicle.car.y), destination,
                spatial_grid=spatial_grid, curbs=curbs, curb_grid=curb_grid,
                buildings=buildings, building_grid=building_grid, origin_is_off_road=True,
            )
            if path is not None:
                return path, destination, None, False
        return None

    def _start_short_transit_trip(
        self,
        vehicle: NPCVehicle,
        origin: Tuple[float, float],
        resident_manager: ResidentManager,
        traffic_world: TrafficWorld,
        ways: List[Way],
        spatial_grid: Optional[SpatialWayGrid],
        parking_spaces: Optional[List],
        sceneries: Optional[List],
        buildings: Optional[List],
        curbs: Optional[List[Curb]],
        curb_grid: Optional[SpatialWayGrid],
        building_grid: Optional[SpatialWayGrid],
        claimed_points: List[Tuple[int, Tuple[float, float]]],
        deadline: float,
        through_point: Optional[Tuple[float, float]] = None,
    ) -> Optional[Driver]:
        """Synchronous form of _short_transit_trip_steps (plan, then apply)."""
        plan = run_route_steps(self._short_transit_trip_steps(
            vehicle, origin, resident_manager, traffic_world, ways, spatial_grid,
            parking_spaces, sceneries, buildings, curbs, curb_grid, building_grid,
            claimed_points, through_point=through_point,
        ), deadline)
        return None if plan is None else _apply_npc_trip(vehicle, resident_manager, plan)

    def _enqueue_route_job(self, kind: str, vehicle, steps: RouteSteps, traffic_world: TrafficWorld,
                           member_resident_ids: Optional[List[int]] = None) -> None:
        """Queue a trip-start ("trip", an idle parked vehicle) or transit
        spawn ("transit") route job, tied to the current road graph
        revision - its result is dropped if the graph is rebuilt first."""
        self._route_jobs.append({
            "kind": kind, "vehicle": vehicle, "steps": steps, "members": member_resident_ids,
            "revision": traffic_world.route_graph_revision, "queued_frame": self._route_job_frame,
        })
        self.route_job_stats["queued"] += 1
        self.population_diagnostics["trip_start_attempts"] += 1

    def _advance_route_jobs(
        self, player_x: float, player_y: float, resident_manager: ResidentManager,
        traffic_world: TrafficWorld, viewport_bounds, budget_s: float = NPC_ROUTE_JOB_BUDGET_S,
    ) -> None:
        """Advance queued route jobs round-robin, NPC_ROUTE_JOB_SLICE_S at a
        time, until budget_s is spent this frame (at least one step per
        frame) - one expensive search can never starve the others."""
        self._route_job_frame += 1
        if not self._route_jobs:
            return
        started = time.perf_counter()
        deadline = started + budget_s
        index = self._route_job_cursor
        first_slice = True  # always make some progress, like advance_chunked
        while self._route_jobs and (first_slice or time.perf_counter() < deadline):
            first_slice = False
            index %= len(self._route_jobs)
            job = self._route_jobs[index]
            if job["revision"] != traffic_world.route_graph_revision or (
                job["kind"] == "trip" and job["vehicle"] not in self.vehicles
            ):
                job["steps"].close()
                del self._route_jobs[index]
                self.route_job_stats["stale" if job["revision"] != traffic_world.route_graph_revision else "discarded"] += 1
                continue
            finished, result = False, None
            slice_end = min(deadline, time.perf_counter() + NPC_ROUTE_JOB_SLICE_S)
            try:
                while True:
                    next(job["steps"])
                    if time.perf_counter() >= slice_end:
                        break
            except StopIteration as done:
                finished, result = True, done.value
            if not finished:
                index += 1
                continue
            del self._route_jobs[index]
            self.route_job_stats["waits_frames"].append(self._route_job_frame - job["queued_frame"])
            self._finish_route_job(job, result, player_x, player_y, resident_manager, viewport_bounds)
        self._route_job_cursor = index
        self.route_job_stats["max_frame_ms"] = max(
            self.route_job_stats["max_frame_ms"], (time.perf_counter() - started) * 1000.0,
        )

    def _finish_route_job(self, job: dict, result, player_x: float, player_y: float,
                          resident_manager: ResidentManager, viewport_bounds) -> None:
        """Apply a finished job's plan only if the world still matches it:
        the vehicle is still idle and parked, the chosen parking space is
        still free, household members are not already riding elsewhere, and
        a transit spawn point is still out of view and clear."""
        stats = self.route_job_stats
        claimed_points = self._claimed_vehicle_points()
        if job["kind"] == "transit":
            if result is None:
                stats["failed"] += 1
                self.population_diagnostics["route_generation_failures"] += 1
                return
            vehicle, _plan = result
            victim = None
            if len(self.vehicles) >= self.target_count:
                victim = self._replaceable_parked_vehicle(player_x, player_y, viewport_bounds)
            if (
                (len(self.vehicles) >= self.target_count and victim is None)
                or (viewport_bounds is not None and _point_in_viewport(
                    vehicle.x, vehicle.y, viewport_bounds, margin_m=NPC_PARKING_ACCESS_TOLERANCE_M,
                ))
                or any(True for _ in self.nearby_vehicles_at(vehicle.x, vehicle.y, NPC_TRANSIT_SPAWN_CLEARANCE_M))
            ):
                release_npc_parking_reservation(vehicle)
                stats["discarded"] += 1
                return
            if victim is not None:
                release_npc_parking_reservation(victim)
                self.vehicles.remove(victim)
                self._trip_start_failures.pop(victim.vehicle_id, None)
            self._apply_transit_spawn(result, resident_manager, claimed_points)
            stats["ready"] += 1
            self.population_diagnostics["successful_trip_starts"] += 1
            return
        vehicle = job["vehicle"]
        if result is None:
            failures = self._trip_start_failures.get(vehicle.vehicle_id, 0) + 1
            self._trip_start_failures[vehicle.vehicle_id] = failures
            self._trip_retry_after_tick[vehicle.vehicle_id] = (
                self._population_tick_number + min(NPC_TRIP_RETRY_MAX_TICKS, 2 ** min(failures - 1, 2))
            )
            stats["failed"] += 1
            self.population_diagnostics["route_generation_failures"] += 1
            return
        parking_space = result[2]
        busy = {
            resident_id for other in self.vehicles if other.trip_group is not None
            for resident_id in other.trip_group.member_resident_ids
        }
        if (
            vehicle.state != NPCState.PARKED
            or self.drivers.get(vehicle.vehicle_id) is not None
            or vehicle.availability != NPCAvailability.AVAILABLE
            or vehicle.driver_departed
            or (parking_space is not None and (
                getattr(parking_space, "reserved", False) or getattr(parking_space, "occupied", False)
            ))
            or any(resident_id in busy for resident_id in job["members"] or ())
        ):
            stats["discarded"] += 1
            return
        driver = _apply_npc_trip(vehicle, resident_manager, result, member_resident_ids=job["members"])
        self._trip_start_failures.pop(vehicle.vehicle_id, None)
        self._trip_retry_after_tick.pop(vehicle.vehicle_id, None)
        stats["ready"] += 1
        self.population_diagnostics["successful_trip_starts"] += 1
        self.drivers[vehicle.vehicle_id] = driver

    def _spawn_transit_vehicle(
        self,
        player_x: float,
        player_y: float,
        resident_manager: ResidentManager,
        traffic_world: TrafficWorld,
        ways: List[Way],
        spatial_grid: Optional[SpatialWayGrid],
        parking_spaces: Optional[List],
        sceneries: Optional[List],
        buildings: Optional[List],
        curbs: Optional[List[Curb]],
        curb_grid: Optional[SpatialWayGrid],
        building_grid: Optional[SpatialWayGrid],
        viewport_bounds: Optional[Tuple[float, float, float, float]],
        claimed_points: List[Tuple[int, Tuple[float, float]]],
        deadline: float,
    ) -> Optional[Driver]:
        """NPC-005: create a moving vehicle on a real road node near (but
        not in view of) the player and start its validated trip at once -
        the same place_parked_npc -> find_and_start_npc_trip -> real
        Resident group/TripGroup/Driver chain every other trip uses, so a
        transit vehicle is not a special kind of NPC. Parked cars near the
        player are not a reliable source of moving traffic (a lot whose
        only exit clips a curb never produces a trip), so this seeds it
        directly. Returns the Driver, or None (nothing added) on failure."""
        result = run_route_steps(self._transit_spawn_steps(
            player_x, player_y, resident_manager, traffic_world, ways, spatial_grid,
            parking_spaces, sceneries, buildings, curbs, curb_grid, building_grid,
            viewport_bounds, claimed_points,
        ), deadline)
        return None if result is None else self._apply_transit_spawn(result, resident_manager, claimed_points)

    def _apply_transit_spawn(self, result, resident_manager: ResidentManager, claimed_points) -> Driver:
        vehicle, plan = result
        driver = _apply_npc_trip(vehicle, resident_manager, plan)
        self.vehicles.append(vehicle)
        self.drivers[vehicle.vehicle_id] = driver
        if vehicle.destination is not None:
            claimed_points.append((vehicle.vehicle_id, vehicle.destination))
        return driver

    def _transit_spawn_steps(
        self,
        player_x: float,
        player_y: float,
        resident_manager: ResidentManager,
        traffic_world: TrafficWorld,
        ways: List[Way],
        spatial_grid: Optional[SpatialWayGrid],
        parking_spaces: Optional[List],
        sceneries: Optional[List],
        buildings: Optional[List],
        curbs: Optional[List[Curb]],
        curb_grid: Optional[SpatialWayGrid],
        building_grid: Optional[SpatialWayGrid],
        viewport_bounds: Optional[Tuple[float, float, float, float]],
        claimed_points: List[Tuple[int, Tuple[float, float]]],
    ) -> RouteSteps:
        """_spawn_transit_vehicle's search as a resumable job: returns
        (placed vehicle, plan) - the vehicle is not yet in self.vehicles -
        or None."""
        cell_size = _ROUTE_NODE_GRID_CELL_M
        nodes = traffic_world._route_nodes
        grid = traffic_world._route_node_grid
        low_x = math.floor((player_x - NPC_TRANSIT_SPAWN_MAX_DISTANCE_M) / cell_size)
        high_x = math.floor((player_x + NPC_TRANSIT_SPAWN_MAX_DISTANCE_M) / cell_size)
        low_y = math.floor((player_y - NPC_TRANSIT_SPAWN_MAX_DISTANCE_M) / cell_size)
        high_y = math.floor((player_y + NPC_TRANSIT_SPAWN_MAX_DISTANCE_M) / cell_size)
        min_sq = NPC_TRANSIT_SPAWN_MIN_DISTANCE_M ** 2
        max_sq = NPC_TRANSIT_SPAWN_MAX_DISTANCE_M ** 2
        ring = []
        for cell_x in range(low_x, high_x + 1):
            for cell_y in range(low_y, high_y + 1):
                for index in grid.get((cell_x, cell_y), ()):
                    distance_sq = (nodes[index][0] - player_x) ** 2 + (nodes[index][1] - player_y) ** 2
                    if min_sq <= distance_sq <= max_sq:
                        ring.append(index)
        random.shuffle(ring)
        tries = 0
        for index in ring:
            yield
            point = (nodes[index][0], nodes[index][1])
            if viewport_bounds is not None and _point_in_viewport(
                point[0], point[1], viewport_bounds, margin_m=NPC_PARKING_ACCESS_TOLERANCE_M,
            ):
                continue
            if any(True for _ in self.nearby_vehicles_at(point[0], point[1], NPC_TRANSIT_SPAWN_CLEARANCE_M)):
                continue
            vehicle = self._place_one(point, None, ways, spatial_grid, curbs, curb_grid, buildings, building_grid)
            if vehicle is None:
                continue
            tries += 1
            plan = yield from self._short_transit_trip_steps(
                vehicle, point, resident_manager, traffic_world, ways, spatial_grid,
                parking_spaces, sceneries, buildings, curbs, curb_grid, building_grid,
                claimed_points, through_point=(player_x, player_y),
            )
            if plan is not None:
                return vehicle, plan
            release_npc_parking_reservation(vehicle)
            if tries >= NPC_TRANSIT_SPAWN_NODE_TRIES:
                break
        return None

    def _run_population_tick(
        self,
        player_x: float,
        player_y: float,
        resident_manager: ResidentManager,
        traffic_world: TrafficWorld,
        ways: List[Way],
        spatial_grid: Optional[SpatialWayGrid],
        parking_spaces: Optional[List],
        sceneries: Optional[List],
        buildings: Optional[List],
        curbs: Optional[List[Curb]],
        curb_grid: Optional[SpatialWayGrid],
        building_grid: Optional[SpatialWayGrid],
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> None:
        population_tick_started = time.perf_counter()
        population_deadline = population_tick_started + NPC_TRIP_START_TICK_BUDGET_S
        self._population_tick_number += 1
        # 1. Despawn only genuinely idle, currently-parked vehicles beyond
        # despawn_radius_m (section 19) - never mid-trip, never with a
        # driver/passengers. Also never a vehicle the player could
        # currently see (pedestrian.py's PedestrianManager uses the same
        # viewport check) - despawn_radius_m normally already guarantees
        # this, but a heavily zoomed-out viewport can exceed it (reported:
        # "cars spawn/despawn in viewport").
        despawn_radius_sq = self.despawn_radius_m * self.despawn_radius_m
        kept = []
        remaining = len(self.vehicles)
        for vehicle in self.vehicles:
            far = (vehicle.x - player_x) ** 2 + (vehicle.y - player_y) ** 2 > despawn_radius_sq
            # NPC-004 section 18: a CRASHED vehicle is also despawn-eligible
            # once far and out of view - its driver (if any) already left
            # via _trigger_vehicle_accident (self.drivers.pop), so the
            # "no driver" half of this check is trivially satisfied; the
            # departed pedestrian despawns independently, gated by its own
            # equivalent far+offscreen+not-mid-activity check in
            # pedestrian.py - no cross-system rendezvous needed since both
            # sit at the same spot and become far/invisible together.
            idle_parked = (
                vehicle.state in (NPCState.PARKED, NPCState.CRASHED)
                and self.drivers.get(vehicle.vehicle_id) is None
            )
            visible = viewport_bounds is not None and _point_in_viewport(vehicle.x, vehicle.y, viewport_bounds)
            # A driving vehicle the player left behind: update() stops
            # simulating it beyond simulation_radius_m (> despawn radius), so
            # it would freeze mid-road as "CRUISING" forever, blocking the
            # road and counting toward the moving-traffic target. Everyone
            # aboard a moving vehicle is still inside it (people only walk
            # out once it parks), so releasing the group is a complete
            # resolution of its occupants.
            far_moving = (
                far
                and vehicle.state not in (NPCState.PARKED, NPCState.CRASHED)
                and self.drivers.get(vehicle.vehicle_id) is not None
            )
            if far_moving and not visible and remaining > self.min_count:
                if vehicle.trip_group is not None:
                    for resident_id in vehicle.trip_group.member_resident_ids:
                        member = resident_manager.get(resident_id)
                        if member is not None:
                            member.trip_group_id = None
                            if member.active_vehicle_id == vehicle.vehicle_id:
                                member.active_vehicle_id = None
                    vehicle.trip_group = None
                release_npc_parking_reservation(vehicle)
                self.drivers.pop(vehicle.vehicle_id, None)
                remaining -= 1
                continue
            # Never below min_count (section 9's configurable population
            # floor), even if more vehicles than that are simultaneously
            # eligible - despawning is a nice-to-have cleanup, not worth
            # briefly starving the population under its configured floor.
            if idle_parked and not visible and far and remaining > self.min_count:
                release_npc_parking_reservation(vehicle)
                self.drivers.pop(vehicle.vehicle_id, None)
                self._trip_start_failures.pop(vehicle.vehicle_id, None)
                remaining -= 1
                continue
            kept.append(vehicle)
        # In place, not self.vehicles = kept: callers (main/__init__.py's
        # npcs = npc_manager.vehicles, traffic_mgr.npcs) hold a reference
        # to this same list object and must keep seeing despawns/spawns
        # without re-fetching it every frame.
        self.vehicles[:] = kept

        # 2. Gradual, staggered top-up towards target_count (sections 4,
        # 19, 23) - never a burst.
        spawned_this_tick = 0
        attempts = 0
        max_attempts = NPC_POPULATION_SPAWN_LIMIT_PER_TICK * 6
        while (
            len(self.vehicles) < self.target_count
            and spawned_this_tick < NPC_POPULATION_SPAWN_LIMIT_PER_TICK
            and attempts < max_attempts
        ):
            attempts += 1
            angle = random.uniform(0.0, 2.0 * math.pi)
            radius = random.uniform(0.0, self.spawn_radius_m)
            qx = player_x + math.cos(angle) * radius
            qy = player_y + math.sin(angle) * radius
            candidates = _pick_npc_destination_candidates(
                qx, qy, parking_spaces, sceneries, buildings, ways=ways, spatial_grid=spatial_grid,
            )
            if not candidates:
                continue
            point, parking_space = candidates[0]
            if (point[0] - player_x) ** 2 + (point[1] - player_y) ** 2 > (self.spawn_radius_m + NPC_SPAWN_RADIUS_SLACK_M) ** 2:
                # The nearest parking to a random query point can be far
                # away in a sparse area - a car spawned beyond the
                # simulation radius is inert and just gets despawned.
                continue
            if viewport_bounds is not None and _point_in_viewport(
                point[0], point[1], viewport_bounds, margin_m=NPC_PARKING_ACCESS_TOLERANCE_M,
            ):
                # Never spawn a vehicle where the player could see it pop
                # into existence (same rule pedestrian.py's spawn_pedestrian
                # already follows) - try a different random point instead.
                # The margin accounts for _begin_trip_on_vehicle's later
                # snap to the route's actual start point if this same
                # vehicle gets rolled to depart this same tick (see
                # _point_in_viewport's own docstring).
                continue
            vehicle = self._place_one(
                point, parking_space, ways, spatial_grid, curbs, curb_grid, buildings, building_grid,
            )
            if vehicle is None:
                continue
            if random.random() < self.household_fraction:
                self._make_household(vehicle, resident_manager)
            self.vehicles.append(vehicle)
            spawned_this_tick += 1

        # Every position a vehicle currently occupies, is already headed
        # for, or calls home, so _pick_npc_destination_candidates can
        # reject a lot/yard/roadside point someone else has already
        # claimed (see NPC_MIN_VEHICLE_SPACING_M's own comment):
        #   - a resting vehicle contributes its own (x, y).
        #   - a vehicle mid-trip contributes its .destination, not its
        #     current position, since that's the point about to become
        #     occupied. Without this half, two vehicles processed in the
        #     same tick (or one already en route from an earlier tick, not
        #     yet arrived) both see the target spot as "free" and both
        #     commit to it - reported: a car seen driving toward the exact
        #     spot another car had already been sent to and was still
        #     approaching, not yet parked.
        #   - a household vehicle's home_position, ALWAYS, even while it's
        #     off on an errand and physically nowhere near it. A home yard
        #     point is a fixed spot re-used by that vehicle's every future
        #     "return home" trip (continue_npc_trip's destination_query_
        #     point) - unlike a dedicated ParkingSpace, nothing else marks
        #     it reserved while its owner is temporarily away, so a plain
        #     currently-occupied/en-route check alone lets a *different*
        #     vehicle's ordinary errand search land exactly on it in the
        #     gap between the owner leaving and returning (reported: two
        #     cars converging on the same yard - one was a car legitimately
        #     coming home to a spot another car had, in the meantime,
        #     wandered into).
        #
        # A vehicle can contribute more than one entry (its home AND a
        # separate current destination while away), so this is a flat list
        # of (vehicle_id, point) pairs, not a dict (see _claimed_vehicle_
        # points, shared with _place_one) - built once per tick, extended
        # immediately after each successful commit below (both loops share
        # it) since a snapshot taken once at the top would still miss a
        # destination chosen earlier in this same tick.
        claimed_points: List[Tuple[int, Tuple[float, float]]] = self._claimed_vehicle_points()

        # 3. Roll idle parked vehicles for "start a new trip now" (section
        # 9's parked/driving mixture), bounded to
        # NPC_TRIP_START_ATTEMPTS_PER_TICK actual attempts regardless of
        # how many roll true - find_and_start_npc_trip's own search cost
        # varies a lot against real map data (see its own docstring), so
        # capping *attempts*, not just candidates, is what actually bounds
        # this tick's worst case.
        trip_starts_this_tick = 0
        # NPC-005: moving traffic is a first-class target, independent of
        # total population - "driving" here matches population_counts()'s
        # own definition (state != PARKED) for consistency with the debug
        # panel's numbers.
        # Only vehicles inside simulation_radius_m count: update() never
        # ticks anything farther out, so a far "driving" car is not traffic
        # the player can ever meet (and used to satisfy the target while
        # nothing near the player moved).
        simulation_radius_sq = self.simulation_radius_m * self.simulation_radius_m

        def _near_player(vehicle: NPCVehicle) -> bool:
            return (vehicle.x - player_x) ** 2 + (vehicle.y - player_y) ** 2 <= simulation_radius_sq

        currently_moving = sum(
            1 for vehicle in self.vehicles
            if vehicle.state not in (NPCState.PARKED, NPCState.CRASHED) and _near_player(vehicle)
        )
        below_moving_target = currently_moving < self.target_moving_count
        trip_start_attempt_cap = (
            NPC_TRIP_START_ATTEMPTS_PER_TICK_WHEN_BELOW_MOVING_TARGET
            if below_moving_target
            else NPC_TRIP_START_ATTEMPTS_PER_TICK
        )
        idle_candidates = [
            vehicle for vehicle in self.vehicles
            if vehicle.state == NPCState.PARKED
            and self.drivers.get(vehicle.vehicle_id) is None
            # Section 7: a RESERVED vehicle (e.g. reserve_household_vehicle,
            # for a future Resident-initiated trip) must not be grabbed by
            # this unrelated "start a random trip" roll.
            and vehicle.availability == NPCAvailability.AVAILABLE
            # NPC-004 section 12: state != PARKED already excludes a CRASHED
            # vehicle, but this makes the "never resumes" invariant explicit
            # rather than incidental.
            and not vehicle.driver_departed
            # Short on nearby traffic: pulling out a car the player will
            # never simulate/see is wasted (and expensive) route search.
            and (not below_moving_target or _near_player(vehicle))
            and self._trip_retry_after_tick.get(vehicle.vehicle_id, 0) <= self._population_tick_number
        ]
        self.population_diagnostics["vehicles_waiting_for_trips"] = len(idle_candidates)
        if below_moving_target:
            transit_spawns = sum(1 for job in self._route_jobs if job["kind"] == "transit")
            while (
                trip_starts_this_tick < trip_start_attempt_cap
                and transit_spawns < NPC_TRANSIT_SPAWNS_PER_TICK
                and currently_moving + transit_spawns < self.target_moving_count
                and len(self._route_jobs) < NPC_MAX_ROUTE_JOBS
            ):
                trip_starts_this_tick += 1
                # At the population target, moving traffic replaces an idle
                # parked car the player can't see rather than growing the
                # population past target_count (re-checked when applied).
                if len(self.vehicles) >= self.target_count and self._replaceable_parked_vehicle(
                    player_x, player_y, viewport_bounds,
                ) is None:
                    break
                transit_spawns += 1
                self._enqueue_route_job("transit", None, self._transit_spawn_steps(
                    player_x, player_y, resident_manager, traffic_world, ways, spatial_grid,
                    parking_spaces, sceneries, buildings, curbs, curb_grid, building_grid,
                    viewport_bounds, list(claimed_points),
                ), traffic_world)
        random.shuffle(idle_candidates)
        # NPC-005 occupancy invariant: a household's members are shared
        # across its (up to NPC_MAX_VEHICLES_PER_HOUSEHOLD) vehicles, so a
        # member already riding in one must never also be folded into a
        # trip starting on another. Resident.active_vehicle_id/
        # trip_group_id are NOT this signal - both are left deliberately
        # stale after a normal trip retires (see _retire_trip's own
        # docstring: "Residents themselves are untouched"). The only
        # reliable "currently mid-trip" signal is membership in some
        # vehicle's still-live trip_group (None once that vehicle's trip
        # actually retires) - collected once per tick, not per household.
        currently_busy_resident_ids = {
            resident_id
            for other_vehicle in self.vehicles
            if other_vehicle.trip_group is not None
            for resident_id in other_vehicle.trip_group.member_resident_ids
        }
        for vehicle in idle_candidates:
            if trip_starts_this_tick >= trip_start_attempt_cap or len(self._route_jobs) >= NPC_MAX_ROUTE_JOBS:
                break
            if any(job["vehicle"] is vehicle for job in self._route_jobs):
                continue
            # Below the moving target the random roll is skipped: it only
            # exists to pace an already-satisfied population, and at 8% per
            # candidate it left the player alone on the road.
            if not below_moving_target and random.random() >= NPC_TRIP_START_PROBABILITY_PER_TICK:
                continue
            trip_starts_this_tick += 1
            member_resident_ids = None
            if vehicle.vehicle_kind == "household":
                household = self.household_manager.get(vehicle.household_id)
                if household is None or not household.member_resident_ids:
                    continue
                available_ids = [
                    rid for rid in household.member_resident_ids
                    if rid not in currently_busy_resident_ids
                ]
                if not available_ids:
                    continue
                take = random.randint(1, len(available_ids))
                member_resident_ids = random.sample(sorted(available_ids), take)
            self._enqueue_route_job("trip", vehicle, _find_npc_trip_steps(
                vehicle, traffic_world, ways, spatial_grid=spatial_grid,
                parking_spaces=parking_spaces, sceneries=sceneries, buildings=buildings,
                curbs=curbs, curb_grid=curb_grid, building_grid=building_grid,
                other_vehicle_positions=[
                    pos for vid, pos in claimed_points if vid != vehicle.vehicle_id
                ],
            ), traffic_world, member_resident_ids=member_resident_ids)

        # 4. Continue already-driving vehicles that are parked, all
        # aboard, and waiting for their next destination (deferred out of
        # the per-frame update() loop - see _handle_parked_vehicle and
        # NPC_CONTINUE_TRIP_ATTEMPTS_PER_TICK's own comments for why).
        # Retirement (trip_group is None, or a household vehicle that just
        # arrived home) is already handled per-frame in
        # _handle_parked_vehicle - this only ever sees vehicles that
        # genuinely need a next destination.
        continue_attempts_this_tick = 0
        ready_vehicles = [
            vehicle for vehicle in self.vehicles
            if vehicle.state == NPCState.PARKED
            and self.drivers.get(vehicle.vehicle_id) is not None
            and vehicle.trip_group is not None
            and vehicle.trip_group.all_aboard
            and not (vehicle.vehicle_kind == "household" and vehicle.returning_home)
        ]
        random.shuffle(ready_vehicles)
        for vehicle in ready_vehicles:
            if continue_attempts_this_tick >= NPC_CONTINUE_TRIP_ATTEMPTS_PER_TICK:
                break
            continue_attempts_this_tick += 1
            driver = self.drivers[vehicle.vehicle_id]
            other_positions = [
                pos for vid, pos in claimed_points if vid != vehicle.vehicle_id
            ]
            if vehicle.vehicle_kind == "household":
                departed = continue_npc_trip(
                    vehicle, driver, traffic_world, ways, spatial_grid=spatial_grid,
                    parking_spaces=parking_spaces, sceneries=sceneries, buildings=buildings,
                    curbs=curbs, curb_grid=curb_grid, building_grid=building_grid,
                    destination_query_point=vehicle.home_position,
                    other_vehicle_positions=other_positions,
                    time_budget_s=max(0.0, population_deadline - time.perf_counter()),
                )
                if departed:
                    vehicle.returning_home = True
            else:
                departed = continue_npc_trip(
                    vehicle, driver, traffic_world, ways, spatial_grid=spatial_grid,
                    parking_spaces=parking_spaces, sceneries=sceneries, buildings=buildings,
                    curbs=curbs, curb_grid=curb_grid, building_grid=building_grid,
                    other_vehicle_positions=other_positions,
                    time_budget_s=max(0.0, population_deadline - time.perf_counter()),
                )
            # Same same-tick claim as section 3 above - a later vehicle in
            # this loop (or section 3, if it runs after this in a future
            # refactor) must see this new destination immediately.
            if departed and vehicle.destination is not None:
                claimed_points.append((vehicle.vehicle_id, vehicle.destination))

        # 5. Recovery (NPC-004 section 3/6/8): a vehicle update_npc marked
        # STUCK either gets a fresh route from wherever it currently sits,
        # or - if none validates - backs up in a controlled way and tries
        # again on a later tick (see NPCState.REVERSING/
        # _update_npc_reversing). plan_route is exactly the "over a second
        # against real dense OSM data" cost find_and_start_npc_trip's own
        # docstring already warns about, so this stays off the per-frame
        # path (update_npc only ever flags "STUCK", never replans) and
        # bounded the same way every other occasional/expensive step in
        # this tick already is.
        recovery_attempts_this_tick = 0
        stuck_vehicles = [
            vehicle for vehicle in self.vehicles
            if getattr(self.drivers.get(vehicle.vehicle_id), "recovery_stage", None) == "STUCK"
        ]
        random.shuffle(stuck_vehicles)
        for vehicle in stuck_vehicles:
            if recovery_attempts_this_tick >= NPC_RECOVERY_ATTEMPTS_PER_TICK:
                break
            recovery_attempts_this_tick += 1
            driver = self.drivers[vehicle.vehicle_id]
            origin = (vehicle.car.x, vehicle.car.y)
            path = _plan_and_validate_npc_route(
                traffic_world, ways, origin, driver.destination, spatial_grid=spatial_grid,
                curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
                parking_space=vehicle.reserved_parking_space, destination_is_off_road=True,
                deadline=population_deadline,
            )
            if path is not None:
                driver.path = path
                driver.path_index = 1
                driver.route_segment_index = 0
                driver.route_segment_t = 0.0
                driver.steering_input = 0.0
                driver.current_way = path[0].way
                driver.recovery_stage = "NORMAL"
                vehicle.state = NPCState.CRUISING
                vehicle.debug_waiting_for = ""
            else:
                # No route validates from here - back up a bounded amount
                # before trying again, rather than retrying the identical
                # failing plan forever from the identical stuck position.
                vehicle.state = NPCState.REVERSING
                driver.recovery_stage = "REVERSING"
                driver.reverse_start_position = None

        self.rebuild_spatial_grid()
        self.population_diagnostics["population_update_duration_s"] = time.perf_counter() - population_tick_started

    def update(
        self,
        dt: float,
        player_x: float,
        player_y: float,
        resident_manager: ResidentManager,
        traffic_world: TrafficWorld,
        ways: List[Way],
        spatial_grid: Optional[SpatialWayGrid] = None,
        parking_spaces: Optional[List] = None,
        sceneries: Optional[List] = None,
        buildings: Optional[List] = None,
        curbs: Optional[List[Curb]] = None,
        curb_grid: Optional[SpatialWayGrid] = None,
        building_grid: Optional[SpatialWayGrid] = None,
        viewport_bounds: Optional[Tuple[float, float, float, float]] = None,
        player_car: object = None,
        pedestrian_mgr: object = None,
    ) -> None:
        # NPC-004: nearby_vehicles_at (avoidance/collision) reads
        # self.spatial_grid, which used to only get rebuilt at population-
        # tick cadence (every NPC_POPULATION_TICK_S=5s) or on initial
        # fill - fine when nothing ever queried it, but every vehicle
        # moves every single frame, so a stale-by-seconds grid could put a
        # vehicle nowhere near where it actually is (reproduced: a fast
        # vehicle drove straight through a stopped one that avoidance
        # should have caught, because the grid still held its position
        # from several seconds earlier). Cheap - O(population size), a
        # dict clear + re-insert per vehicle, trivial next to the per-
        # vehicle decision/physics work below.
        self.rebuild_spatial_grid()
        previous_poses = {id(v): (v.x, v.y, v.heading) for v in self.vehicles}
        for vehicle in self.vehicles:
            if vehicle.state == NPCState.CRASHED:
                vehicle.car.speed = 0.0
                vehicle.crashed_timer += dt
        previous_player_pose = self._previous_player_pose
        if player_car is not None:
            self._previous_player_pose = (player_car.x, player_car.y, player_car.heading)
        for vehicle in self.vehicles:
            driver = self.drivers.get(vehicle.vehicle_id)
            if driver is None:
                continue  # idle, parked - nothing to simulate until it starts a trip
            distance_sq = (vehicle.x - player_x) ** 2 + (vehicle.y - player_y) ** 2
            if distance_sq > self.simulation_radius_m * self.simulation_radius_m:
                # Section 17/18: still exists, keeps its full state, just
                # doesn't tick physics/decisions while this far away - not
                # "outside camera = nonexistent".
                continue
            # NPC-004 section 2: only vehicles actually near this one need
            # to be considered for avoidance (never all-to-all) - the same
            # spatial-grid-bounded query pattern every other proximity check
            # in this module already uses. The player's own car is a cheap
            # unconditional append (one object, cone-projection in
            # nearest_vehicle_ahead already discards it if it's too far or
            # off to the side).
            # ways_in_rect (nearby_vehicles_at's own query) yields, it
            # doesn't return a list - materializing it once here (not
            # inside the `if player_car` branch) matters because this same
            # object gets consumed twice below (collision check, then
            # avoidance inside update_npc); a generator can only be
            # iterated once, so the second consumer would otherwise
            # silently see nothing at all whenever player_car is None.
            nearby_obstacles = list(self.nearby_vehicles_at(vehicle.x, vehicle.y, NPC_AVOIDANCE_DETECTION_DISTANCE_M))
            if player_car is not None:
                nearby_obstacles.append(player_car)
            update_npc(
                vehicle, driver, dt, traffic_world, resident_manager,
                curbs=curbs, buildings=buildings, curb_grid=curb_grid, building_grid=building_grid,
                nearby_obstacles=nearby_obstacles, manager=self, pedestrian_mgr=pedestrian_mgr,
            )
            if vehicle.state == NPCState.PARKED:
                self._handle_parked_vehicle(vehicle)

        # Collision is a post-physics phase. Reindex moved vehicles, query a
        # swept local area, then test current and interpolated poses. This
        # makes update order irrelevant and prevents fast vehicles tunnelling
        # between two non-overlapping frame samples.
        self.rebuild_spatial_grid()
        obstacle_previous = dict(previous_poses)
        if player_car is not None and previous_player_pose is not None:
            obstacle_previous[id(player_car)] = previous_player_pose
        max_frame_travel = max((
            math.hypot(v.x - previous_poses[id(v)][0], v.y - previous_poses[id(v)][1])
            for v in self.vehicles if id(v) in previous_poses
        ), default=0.0)
        for vehicle in self.vehicles:
            previous = previous_poses.get(id(vehicle))
            if previous is None:
                continue
            travel = math.hypot(vehicle.x - previous[0], vehicle.y - previous[1])
            mid_x, mid_y = (vehicle.x + previous[0]) * 0.5, (vehicle.y + previous[1]) * 0.5
            radius = travel * 0.5 + max_frame_travel + max(vehicle.length_m, vehicle.width_m) + 3.0
            collision_candidates = list(self.nearby_vehicles_at(mid_x, mid_y, radius))
            if player_car is not None:
                collision_candidates.append(player_car)
            self._check_vehicle_collision(
                vehicle, collision_candidates, resident_manager, pedestrian_mgr, traffic_world.sim_time,
                previous_vehicle_pose=previous, previous_obstacle_poses=obstacle_previous,
            )

        self._advance_route_jobs(player_x, player_y, resident_manager, traffic_world, viewport_bounds)

        self._population_elapsed += dt
        if self._population_elapsed >= NPC_POPULATION_TICK_S:
            self._population_elapsed = 0.0
            self._run_population_tick(
                player_x, player_y, resident_manager, traffic_world, ways, spatial_grid,
                parking_spaces, sceneries, buildings, curbs, curb_grid, building_grid,
                viewport_bounds=viewport_bounds,
            )
