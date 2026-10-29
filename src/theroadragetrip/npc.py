"""autonomous-driving: the first properly architected autonomous NPC car.

One Resident -> one Driver -> one NPCVehicle -> one preplanned OSM route,
driven with real traffic rules. See .github/prompts/autonomous-driving.md.

Layering (section 18 of that spec):

    Resident -> Driver -> route (TrafficWorld.plan_route) -> lane planning
    -> traffic rule engine (traffic_rules.py) -> vehicle controller
    (physics.update_car_physics) -> NPCVehicle (physical + render state)

No rendering in this module: the server sends NPCVehicle's state
(protocol.py) and the Godot client draws it (godot/entity_layer.gd).
"""
from __future__ import annotations

import collections
import itertools
import dataclasses
import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .activities import ActivityInstance, ActivityLocation
from .competitor_taxis import COMPETITOR_TAXIS, CRUISE_DWELL_S, is_competitor, make_competitor, night_taxi_target
from . import bus_lines
from .bus_lines import is_line_bus
from .geo import angle_diff, bbox_distance_sq, box_contact_normal, boxes_intersect, clamp, closest_point_and_dist_to_segment, dist_point_to_segment, point_in_polygon, segment_distance
from .map_level import on_map_level
from .osm import Curb, ParkingSpace, StopSign, Way
from .physics import GRAVITY_MPS2, Car, SpatialWayGrid, min_turn_radius, rear_axle_behind, get_road_layer_at_point, is_point_on_road, update_car_physics
from .population import people_within, traffic_demand
from .road_rage import RoadRageClearance
from .residents import Household, HouseholdManager, ResidentManager
from .traffic_rules import TrafficAction, TrafficDecision, decide_traffic_action, nearest_vehicle_ahead, crossing_yield_decision, stop_sign_decision
from .traffic_world import _ROUTE_NODE_GRID_CELL_M, RouteSteps, TrafficWorld, run_route_steps
from .vehicles.base import VEHICLE_DEFINITIONS, vehicle_definition
from .motorcycle_season import MotorcycleSeason
from . import cycling


class NPCState:
    """Vehicle state machine (autonomous-driving section 10).

    The architecture must support future states without rework, but
    autonomous-driving only implemented a subset originally; collision-avoidance adds the two it
    reserved by name (CRASHED, and REVERSING in place of the more generic
    DISABLED) - DRIVER_EXITED/ABANDONED/DESPAWNING still aren't needed as
    separate states: "driver exited" is NPCVehicle.driver_departed (an
    orthogonal flag, not a motion state - the vehicle can be CRASHED with
    or without a departed driver for one frame), and DESPAWNING is a
    one-shot removal with nothing to observe mid-way, same reasoning
    vehicle-population v2's README already gives for not adding it either.
    """
    SPAWNING = "SPAWNING"
    CRUISING = "CRUISING"
    APPROACHING_INTERSECTION = "APPROACHING_INTERSECTION"
    WAITING = "WAITING"
    TURNING = "TURNING"
    PARKING = "PARKING"  # final approach into a dedicated parking space (NPC-more.md section 14)
    ARRIVING = "ARRIVING"
    PARKED = "PARKED"  # stopped and settled at the destination (multi-passenger-car.md section 17)
    REVERSING = "REVERSING"  # collision-avoidance: controlled backing-up during stuck recovery
    CRASHED = "CRASHED"  # collision-avoidance: stopped after an actual collision, driver may have departed


class NPCAvailability:
    """vehicle-population section 7: whether unrelated logic may claim this vehicle.

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
# vehicle-population: is_vehicle_pose_valid's curb/building scan costs ~1-2ms against
# real dense OSM data (measured: real Oulu data, ~13 nearby curbs/
# buildings per query even with a small grid cell size - candidate count
# is genuine local density, not a grid-tuning artifact). Harmless at the
# single always-on autonomous-driving car; with vehicle-population's real population, several
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

# collision-avoidance section 2: vehicle-following avoidance. Mirrors
# nearest_traffic_light_ahead's own forward-cone shape (detection distance/
# lateral limit), just narrower laterally since a vehicle occupies one lane,
# not a whole intersection approach.
NPC_AVOIDANCE_DETECTION_DISTANCE_M = 30.0
NPC_AVOIDANCE_LATERAL_LIMIT_M = 2.5
NPC_AVOIDANCE_DECEL_MPS2 = 3.0  # comfortable following-distance braking rate, same order as corner/arrival braking
NPC_AVOIDANCE_MIN_GAP_M = 2.0  # bumper-to-bumper gap kept from a stopped vehicle ahead
# Driving around a car that will not move (a wreck, a parked car in the lane):
NPC_PASS_WAIT_S = 3.0  # stopped behind it this long first
NPC_PASS_START_GAP_M = 6.0  # ...and this close to it (bumper to bumper)
NPC_PASS_ONCOMING_CHECK_M = 60.0  # the oncoming lane must be empty this far ahead
NPC_PASS_CLEARANCE_M = 2.0  # back in lane once this far past it
NPC_PASS_SPEED_MPS = 6.0

# collision-avoidance section 3/8: stuck detection. Checked on the same throttled-cache
# cadence as the footprint check (NPC_FOOTPRINT_CHECK_INTERVAL_S) rather
# than every frame - this is a recovery safety net, not a per-frame
# correctness requirement.
NPC_STUCK_CHECK_INTERVAL_S = 1.0
NPC_STUCK_MIN_PROGRESS_M = 2.0  # real displacement expected per check interval when actually driving
NPC_SNOW_TRACTOR_FACTOR = 8.0  # while it snows, tractors (ploughs) are this much more likely to spawn
NPC_SNOW_HOLIDAY_FACTOR = 0.15  # ... and camper vans and caravans this much less (summer holiday traffic)
HOLIDAY_VEHICLES = ("camper_van", "car_caravan")
# Near a camping area (OSM tourism=camp_site/caravan_site/camp_pitch) holiday
# vehicles are this much more likely: about a quarter of new traffic there.
CAMPING_KINDS = ("camp_site", "caravan_site", "camp_pitch")
CAMPING_RADIUS_M = 1500.0
CAMPING_HOLIDAY_FACTOR = 15.0
NPC_CRASH_CLEAR_S = 60.0  # a wreck is towed away after this long, even in view: it blocks the road
NPC_STUCK_TIMEOUT_S = 8.0  # accumulated stuck time before recovery triggers

# collision-avoidance section 6/7: reverse recovery. A short, straight, controlled
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
LANE_BIAS_LOOKAHEAD_M = 20.0  # start easing into a turn lane this far before the corner (intersection-rules section 5)
# vehicle-population v2: the "car" vehicle plugin (vehicles/plugins/car.py) is now the
# canonical source for these three values - derived here, once, at import
# time, so every existing call site in this module and in tests keeps
# working unchanged. vehicles/ never imports npc.py (one-directional, same
# as activities/ never importing pedestrian.py), so this is a safe,
# non-circular import.
_car_plugin_definition = VEHICLE_DEFINITIONS["car"]
NPC_VEHICLE_LENGTH_M = _car_plugin_definition.length_m  # the default NPC car's dimensions - shared so footprint checks always match the spawned Car
NPC_VEHICLE_WIDTH_M = _car_plugin_definition.width_m
NPC_MAX_VEHICLE_HALF_LENGTH_M = max(definition.length_m for definition in VEHICLE_DEFINITIONS.values()) * .5


def following_detection_distance(vehicle) -> float:
    """See a stopped lead before comfortable braking plus a one-second margin."""
    speed = abs(vehicle.speed)
    return max(NPC_AVOIDANCE_DETECTION_DISTANCE_M,
               speed * speed / (2 * NPC_AVOIDANCE_DECEL_MPS2) + speed
               + vehicle.length_m * .5 + NPC_MAX_VEHICLE_HALF_LENGTH_M + NPC_AVOIDANCE_MIN_GAP_M)

# multi-passenger-car.md section 2: capacity lives in one constant, never a
# hardcoded literal in passenger-management logic.
NPC_CAR_CAPACITY = _car_plugin_definition.capacity
# vehicle-population v2: real-world-ish car body color distribution (roughly ordered
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

# vehicle-population: population management (NPCVehicleManager). Mirrors
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
# living-traffic: the flat probability/attempts-cap pair above has no idea how
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
# Moving traffic is planned this far ahead of the taxi: route planning takes
# up to ~2 s, and a spot the taxi reaches first is discarded (it would pop into view).
NPC_TRANSIT_PLAYER_LOOKAHEAD_S = 6.0
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


def transit_spawn_focus(player_x: float, player_y: float, player_car, simulation_radius_m: float) -> Tuple[float, float]:
    """Lead fast players so newly planned traffic is not already behind them."""
    if player_car is None:
        return player_x, player_y
    from .viewport import SIMULATION_LOOKAHEAD_S
    # Within the simulated area, which reaches SIMULATION_LOOKAHEAD_S ahead (viewport.simulation_bounds).
    max_lead = max(0.0, simulation_radius_m - NPC_TRANSIT_SPAWN_MAX_DISTANCE_M - 10.0,
                   abs(player_car.speed) * SIMULATION_LOOKAHEAD_S - 60.0)
    lead = max(-max_lead, min(max_lead, player_car.speed * NPC_TRANSIT_PLAYER_LOOKAHEAD_S))
    return player_x + math.cos(player_car.heading) * lead, player_y + math.sin(player_car.heading) * lead


def through_road_first(nodes, grid, indices, road, spatial_grid, x: float, y: float, reach: float):
    """The player's road's route nodes (same ref, else same highway class)
    within `reach`, then `indices`: a major road's passing traffic drives on
    it, so a LAM station's curve shows up on the road it measures
    (docs/lam-traffic-audit.md). The reach goes past the usual spawn ring:
    a trunk road's vertices can lie hundreds of metres apart."""
    ref, highway = getattr(road, "ref", None), getattr(road, "highway", None)
    if road is None or spatial_grid is None or not ref and highway in _LOW_TRAFFIC_HIGHWAY_TYPES:
        return indices  # a local street has no passing traffic of its own (and matching it would scan the town)
    cells = {(round(px / 3.0), round(py / 3.0))
             for way in spatial_grid.ways_in_rect(x - reach, y - reach, x + reach, y + reach)
             if (getattr(way, "ref", None) == ref if ref else getattr(way, "highway", None) == highway)
             for px, py in way.points_m}
    size = _ROUTE_NODE_GRID_CELL_M
    on_road = [i for cx in range(math.floor((x - reach) / size), math.floor((x + reach) / size) + 1)
               for cy in range(math.floor((y - reach) / size), math.floor((y + reach) / size) + 1)
               for i in grid.get((cx, cy), ())
               if NPC_TRANSIT_SPAWN_MIN_DISTANCE_M <= math.hypot(nodes[i][0] - x, nodes[i][1] - y) <= reach
               and (round(nodes[i][0] / 3.0), round(nodes[i][1] / 3.0)) in cells]
    random.shuffle(on_road)
    chosen = set(on_road)
    return on_road + [i for i in indices if i not in chosen]


def prioritize_transit_spawn_nodes(nodes, indices, x: float, y: float, heading: Optional[float]):
    """Try nodes in the player's forward road corridor before side streets."""
    if heading is None:
        return indices
    forward_x, forward_y = math.cos(heading), math.sin(heading)
    aligned = []
    for index in indices:
        dx, dy = nodes[index][0] - x, nodes[index][1] - y
        forward = dx * forward_x + dy * forward_y
        lateral = abs(dx * -forward_y + dy * forward_x)
        if forward > 0.0 and lateral <= 30.0:
            aligned.append((lateral, forward, index))
    aligned.sort()
    aligned_ids = {item[2] for item in aligned}
    return [item[2] for item in aligned] + [index for index in indices if index not in aligned_ids]
# Default fraction of the vehicle population that should be actively
# driving at any moment, independent of total population size (client-
# server-016.md/living-traffic: moving traffic is a first-class target, not a
# side effect of the total-population target).
NPC_TARGET_MOVING_FRACTION = 0.5
# vehicle-population v2: continue_npc_trip (an already-driving vehicle picking its
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
# collision-avoidance: recovery reroute attempts for STUCK vehicles - same one-
# expensive-plan_route-call-per-tick discipline as the two constants above.
NPC_RECOVERY_ATTEMPTS_PER_TICK = 1
# A car whose recovery found no route holds (stopped, a legal wait) only
# for a while: then it replans to a new destination from where it stands
# (another NPC_HOLD_RETRY_TICKS population ticks later after each failure).
# A hold was permanent, and held cars piled up into a city-wide jam. After
# NPC_HOLD_GIVE_UP_ATTEMPTS failures a held car is removed, even in view:
# explicit jam-cleanup exception, not a timeout for lawful traffic waits.
NPC_HOLD_RETRY_TICKS = 5
NPC_HOLD_GIVE_UP_ATTEMPTS = 3
NPC_RECOVERY_MAX_WITHOUT_PROGRESS = 3
NPC_RECOVERY_PROGRESS_M = 5.0
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
# separate, pre-existing system - see vehicle-population section 1's "do not
# duplicate/rewrite the traffic manager").
NPC_TRIP_START_TIME_BUDGET_S = 0.5
# Section 13: fraction of the population that gets a household (and thus
# a home to return to) rather than being a plain autonomous TRAFFIC_VEHICLE.
NPC_HOUSEHOLD_VEHICLE_FRACTION = 0.3
# vehicle-population v2 section 9: chance a new household-eligible vehicle joins an
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
    centerline for a left turn - intersection-rules section 5's required lane
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


def _is_stalled(obstacle) -> bool:
    """A vehicle that will not move on its own: worth driving around."""
    return getattr(obstacle, "state", None) in (NPCState.CRASHED, NPCState.PARKED)


def _pass_offset_m(way: Optional[Way], vehicle_width_m: float) -> float:
    """From the right-hand lane to the mirrored oncoming one (_lane_offset_point's cruise offset, twice)."""
    half_width = max(0.0, getattr(way, "half_width_m", 4.0))
    return 2.0 * min(max(1.2, half_width * 0.45), max(0.0, half_width - vehicle_width_m * 0.5))


def _oncoming_lane_clear(x: float, y: float, heading: float, offset_m: float, width_m: float, obstacles, skip) -> bool:
    """Nothing in the lane `offset_m` to the left, from just behind to
    NPC_PASS_ONCOMING_CHECK_M ahead - `skip` (the stalled car) included,
    should it lie across the road."""
    hx, hy = math.cos(heading), math.sin(heading)
    turn = getattr(skip, "heading", heading) - heading
    reach = ((skip.y - y) * hx - (skip.x - x) * hy
             + abs(math.sin(turn)) * getattr(skip, "length_m", NPC_VEHICLE_LENGTH_M) * 0.5
             + abs(math.cos(turn)) * getattr(skip, "width_m", NPC_VEHICLE_WIDTH_M) * 0.5)
    if reach > offset_m - width_m * 0.5 - 0.3:
        return False
    for obstacle in obstacles:
        if obstacle is skip:
            continue
        if (getattr(obstacle, "layer", 0) != getattr(skip, "layer", 0)
                or getattr(getattr(obstacle, "car", obstacle), "map_level", 0)
                != getattr(getattr(skip, "car", skip), "map_level", 0)):
            continue
        dx, dy = obstacle.x - x, obstacle.y - y
        along, left = dx * hx + dy * hy, dy * hx - dx * hy
        angle = getattr(obstacle, "heading", heading) - heading
        lateral_reach = (abs(math.sin(angle)) * getattr(obstacle, "length_m", NPC_VEHICLE_LENGTH_M)
                         + abs(math.cos(angle)) * getattr(obstacle, "width_m", NPC_VEHICLE_WIDTH_M)) * 0.5
        if (-3.0 < along < NPC_PASS_ONCOMING_CHECK_M
                and left + lateral_reach > offset_m - width_m * 0.5 - 0.3
                and left - lateral_reach < offset_m + width_m * 0.5 + 0.3):
            return False
    return True


NPC_PULL_OUT_MAX_SPEED_MPS = 1.5  # still setting off: below this a departing vehicle may wait for a gap
NPC_PULL_OUT_GAP_S = 5.0  # traffic arriving within this long has the way
NPC_PULL_OUT_LANE_M = 3.5  # ...when its line passes this close to the departing vehicle


def _traffic_approaching(vehicle, obstacles) -> bool:
    """A moving vehicle heading at `vehicle` that would reach it within NPC_PULL_OUT_GAP_S."""
    for other in obstacles:
        if other is vehicle or _is_stalled(other):
            continue
        speed = getattr(other, "speed", 0.0)
        if abs(speed) < 1.0:
            continue
        heading = getattr(other, "heading", 0.0)
        hx, hy = math.cos(heading) * (1 if speed > 0 else -1), math.sin(heading) * (1 if speed > 0 else -1)
        dx, dy = vehicle.x - other.x, vehicle.y - other.y
        along, across = dx * hx + dy * hy, abs(dy * hx - dx * hy)
        if 0.0 < along <= abs(speed) * NPC_PULL_OUT_GAP_S + vehicle.length_m and across < NPC_PULL_OUT_LANE_M:
            return True
    return False


def _stalled_vehicle_on_route(vehicle, driver, obstacles, reach):
    """See what is on the route around a bend before it enters the straight
    steering cone: wrecks and parked cars, a queue standing still, and
    traffic going the same way (a queue around a bend was only seen a few
    metres short, too late to stop: rear-end pile-ups behind a wreck)."""
    candidates = [o for o in obstacles if o is not vehicle]
    nearest = None
    distance = 0.0
    segment = driver.route_segment_index
    for index in range(segment, min(len(driver.path) - 1, segment + 32)):
        if not candidates or distance > reach:
            break
        a, b = driver.path[index:index + 2]
        t = driver.route_segment_t if index == segment else 0.0
        ax, ay = a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t
        length = math.hypot(b.x - ax, b.y - ay)
        if length < 1e-6:
            continue
        hx, hy = (b.x - ax) / length, (b.y - ay) / length
        heading = math.atan2(hy, hx)
        for other in candidates:
            dx, dy = other.x - ax, other.y - ay
            along, lateral = dx * hx + dy * hy, abs(dy * hx - dx * hy)
            angle = getattr(other, "heading", heading) - heading
            if not (_is_stalled(other) or abs(getattr(other, "speed", 0.0)) < 0.5 or math.cos(angle) > 0.5):
                continue  # oncoming traffic is not in our lane's queue
            width = (abs(math.sin(angle)) * getattr(other, "length_m", NPC_VEHICLE_LENGTH_M)
                     + abs(math.cos(angle)) * getattr(other, "width_m", NPC_VEHICLE_WIDTH_M))
            gap = distance + along
            if (0.0 <= along <= length and 0.0 < gap <= reach
                    and lateral < (vehicle.width_m + width) * 0.5 + 0.3
                    and (nearest is None or gap < nearest[0])):
                nearest = gap, other
        distance += length
    return nearest


def _round_corner(
    prev_pt: Tuple[float, float],
    corner_pt: Tuple[float, float],
    next_pt: Tuple[float, float],
    radius_m: float = CORNER_RADIUS_M,
    samples: int = CORNER_SAMPLE_COUNT,
) -> List[Tuple[float, float]]:
    """Replace a sharp route vertex with a sampled quadratic-Bezier arc
    (autonomous-driving section 9), so a turn is a smooth curve, never a pivot on a
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
    orientation: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """Insert one waypoint just before the destination so the vehicle's
    final heading approaches along the parking space's own orientation
    axis (NPC-more.md section 15) instead of whatever direction the
    route's last real road segment happened to point.

    Picks whichever of the axis's two directions is closer to the
    route's own natural final approach heading, so this never forces an
    unnecessary U-turn just to face "the other way" along the same line.
    An explicit orientation also aligns roadside parking. Without an
    axis, or with fewer than two route points, leaves the route unchanged.
    """
    if parking_space is not None:
        orientation = _parking_space_axis(parking_space)
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
    instead of following the road through it. autonomous-driving section 5 requires
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
    the *start* (vehicle-population: a vehicle departing from an off-road parked
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


def update_knocked(vehicle, dt: float, buildings=None, building_grid=None, ways=None, spatial_grid=None) -> None:
    """A collision-knocked vehicle slides on, slowing at KNOCK_DECEL_MPS2,
    until it stops, would slide into a building (it stops at the wall) or
    off its bridge or level (map layers stay apart)."""
    speed = math.hypot(vehicle.knock_vx, vehicle.knock_vy)
    slower = speed - KNOCK_DECEL_MPS2 * dt
    if not math.isfinite(speed) or slower <= KNOCK_STOP_MPS:
        vehicle.knock_vx = vehicle.knock_vy = 0.0
        return
    x, y = vehicle.car.x + vehicle.knock_vx * dt, vehicle.car.y + vehicle.knock_vy * dt
    if buildings is not None and not is_vehicle_pose_valid(x, y, vehicle.car.heading, buildings=buildings,
                                                           building_grid=building_grid, length_m=vehicle.length_m,
                                                           width_m=vehicle.width_m, clearance_m=0.05):
        vehicle.knock_vx = vehicle.knock_vy = 0.0
        return
    if vehicle.layer != 0 and (ways or spatial_grid) and get_road_layer_at_point(
            x, y, current_layer=vehicle.layer, ways=ways, spatial_grid=spatial_grid) != vehicle.layer:
        vehicle.knock_vx = vehicle.knock_vy = 0.0
        return
    vehicle.car.x, vehicle.car.y = x, y
    vehicle.knock_vx *= slower / speed
    vehicle.knock_vy *= slower / speed


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
    min_x = min(px for px, py in corners) - clearance_m
    max_x = max(px for px, py in corners) + clearance_m
    min_y = min(py for px, py in corners) - clearance_m
    max_y = max(py for px, py in corners) + clearance_m
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
                # The grid returns whole polylines; only nearby edges can touch the footprint.
                if (max(oa[0], ob[0]) < min_x or min(oa[0], ob[0]) > max_x
                        or max(oa[1], ob[1]) < min_y or min(oa[1], ob[1]) > max_y):
                    continue
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

    skip_leading_m (vehicle-population: departing from an off-road parked position -
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
    aligned_parking_approach: bool = False,
    skip_initial_lane_offset: bool = False,
) -> List[PathPoint]:
    """Turn a raw centerline route (TrafficWorld.plan_route's output) into
    a lane-correct, corner-smoothed path for an NPC to follow.

    Kept as one function for autonomous-driving (one vehicle, no need for a generic
    multi-stage pipeline object yet), but route planning (the caller),
    lane offsetting, and corner rounding remain distinct, independently
    testable steps - see build_driving_path's own helpers.

    aligned_parking_approach preserves the penultimate parking waypoint
    so lane offsets cannot rotate the deliberately aligned final leg.

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
        # A bend on the same road keeps its travel lane, rather than
        # moving to a turning position against the kerb or centre line.
        if corner_maneuver[start] is not None and segment_way[start - 1] is not segment_way[start]:
            return corner_maneuver[start]
        remaining = 0.0
        for j in range(start, n - 1):
            remaining += segment_length[j]
            if remaining > LANE_BIAS_LOOKAHEAD_M:
                return None
            if corner_maneuver[j + 1] is not None and segment_way[j] is not segment_way[j + 1]:
                return corner_maneuver[j + 1]
        return None

    lane_points: List[Tuple[float, float, Optional[Way]]] = []
    lane_bias: List[Optional[str]] = []
    for i, (x, y) in enumerate(route_points):
        seg = min(i, n - 2)
        bias = _upcoming_maneuver(i)
        if (i == 0 and skip_initial_lane_offset) or (i == n - 1 and skip_final_lane_offset) or (i == n - 2 and aligned_parking_approach):
            lx, ly = x, y
        else:
            lx, ly = _lane_offset_point(segment_way[seg], x, y, segment_heading[seg], vehicle_width_m, maneuver=bias)
            if (0 < i < n - 1 and corner_maneuver[i] is not None
                    and segment_way[i - 1] is segment_way[i]):
                incoming, outgoing = segment_heading[i - 1], segment_heading[i]
                cross = math.sin(outgoing - incoming)
                if abs(cross) > 0.1:
                    # Round the intersection of the offset lanes, not a point
                    # shifted only onto the exit lane (which cuts across oncoming cars).
                    ax, ay = _lane_offset_point(segment_way[i - 1], x, y, incoming, vehicle_width_m, maneuver=bias)
                    along = ((lx - ax) * math.sin(outgoing) - (ly - ay) * math.cos(outgoing)) / cross
                    lx, ly = ax + along * math.cos(incoming), ay + along * math.sin(incoming)
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
                path.append(PathPoint(ax, ay, lane_points[i][2], is_turn=True, maneuver=maneuver, lane_bias=lane_bias[i]))
        else:
            path.append(PathPoint(*lane_points[i], lane_bias=lane_bias[i]))
    path.append(PathPoint(*lane_points[-1], lane_bias=lane_bias[-1]))
    return path


@dataclass
class Driver:
    """Driving-specific state and decisions (autonomous-driving section 4).

    Owns the driving *decisions*; never touches rendering.
    """
    resident_id: int
    vehicle_id: int
    path: List[PathPoint]
    destination: Tuple[float, float]
    path_index: int = 1  # path[0] is the spawn point, already "reached"
    current_way: Optional[Way] = None
    target_speed_mps: float = 0.0
    decision: TrafficDecision = field(default_factory=lambda: TrafficDecision(TrafficAction.PROCEED, 0.0))
    stop_sign_key: Optional[tuple] = None
    stop_sign_satisfied: bool = False
    # collision-avoidance stuck detection (section 3/8): sampled every
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
    recovery_anchor: Optional[Tuple[float, float]] = None
    recovery_route_attempts: int = 0
    hold_retry_tick: int = 0  # HOLD: the population tick it replans to a new destination at
    hold_failures: int = 0  # HOLD: replans that found nothing either
    route_job_pending: bool = False
    reverse_start_position: Optional[Tuple[float, float]] = None
    # Cached continuous route progress used by the path follower.  Unlike
    # path_index this is a position along a segment, so steering does not
    # jump merely because a waypoint entered a bookkeeping radius.
    route_segment_index: int = 0
    route_segment_t: float = 0.0
    lookahead_distance_m: float = 0.0
    steering_input: float = 0.0
    destination_is_off_road: bool = False
    origin_is_off_road: bool = False
    trip_origin: Optional[Tuple[float, float]] = None
    passing: Optional[object] = None  # the stalled vehicle being driven around in the oncoming lane
    pass_wait_s: float = 0.0
    cycle: Optional[object] = None  # a cyclist's cycling.CycleRoute (path above unused but for debug)
    replans: int = 0  # a cyclist's new destinations after getting stuck
    manoeuvre: Optional[list] = None  # a multi-point manoeuvre being driven: its runs (manoeuvre.plan)
    manoeuvre_run: int = 0
    manoeuvre_wait_s: float = 0.0  # waiting for the space behind to clear
    manoeuvres_tried: int = 0  # this trip's planned manoeuvres (arriving and departing)
    manoeuvre_zone: Optional[str] = None  # "arriving" / "departing" while one may be needed (else None)
    rack_slot: Optional[Tuple[float, float, float]] = None  # a cyclist's claimed hoop (cycling.rack_slots)
    rack_claim: Optional[tuple] = None  # (rack OSM id, hoop index): survives the rack being rebuilt by a map merge
    stolen: bool = False  # a thief rides this bike: its next trip is a fast getaway

    @property
    def next_maneuver(self) -> str:
        for point in self.path[self.path_index:]:
            if point.maneuver:
                return point.maneuver
        return "arrive" if self.path_index >= len(self.path) - 1 else "straight"

    @property
    def next_way(self) -> Optional[Way]:
        """The road beyond the upcoming turn, or None if still on/past the
        last one (intersection-rules section 21's debug HUD "next way")."""
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
    pedestrian.PedestrianState. `disembarked_resident_ids` prevents a returned
    member being materialized outside again until the next stop.
    """
    group_id: int
    vehicle_id: int
    member_resident_ids: List[int]
    destination_entrance: Optional[Tuple[float, float]] = None
    activity_type: str = ""  # section 13/14/26: "shopping"/"work"/... - shared per group for now
    activity_duration_s: float = 0.0
    boarded_resident_ids: Set[int] = field(default_factory=set)
    wait_deadline_sim_time: Optional[float] = None
    disembarked_resident_ids: Set[int] = field(default_factory=set)  # once per stop, even after reboarding

    @property
    def all_aboard(self) -> bool:
        return self.boarded_resident_ids >= set(self.member_resident_ids)


# Game policy: a bump by the taxi below this closing speed is no crash - the
# NPC's driver curses and drives on slowly instead of wrecking the car.
MINOR_HIT_MPS = 15.0 / 3.6
NPC_SCRAPE_MPS = 5.0 / 3.6  # two NPCs touching slower than this: a scrape, both go on (no wreck)
# Collision response (rrt-019-crash-physics): an impulse along the contact
# normal, by mass. A little bounce; a knocked vehicle then slides, tyres
# scrubbing or wheels locked, until friction stops it.
COLLISION_RESTITUTION = 0.2
KNOCK_DECEL_MPS2 = 7.0
KNOCK_MAX_MPS = 40.0  # no impulse throws anything faster than this
KNOCK_STOP_MPS = 0.2


def collision_mass_kg(body) -> float:
    """An NPC vehicle's laden mass by type (vehicles/base.py), the taxi's own."""
    if isinstance(body, NPCVehicle):
        return vehicle_definition(body.vehicle_type).mass_kg
    return getattr(body, "total_mass_kg", 1500.0)


def collision_velocity(body) -> Tuple[float, float]:
    """World velocity: a knocked NPC's slide, else its speed along its heading."""
    if isinstance(body, NPCVehicle) and (body.knock_vx or body.knock_vy):
        return body.knock_vx, body.knock_vy
    car = getattr(body, "car", body)
    return math.cos(car.heading) * car.speed, math.sin(car.heading) * car.speed


def collision_impulse(va, vb, normal, mass_a: float, mass_b: float):
    """Velocities after a contact along `normal` (unit, from a into b): the
    standard impulse with COLLISION_RESTITUTION, only while they close -
    a pair already parting gets none, so one contact never pushes twice.
    Results are capped at KNOCK_MAX_MPS."""
    nx, ny = normal
    closing = (va[0] - vb[0]) * nx + (va[1] - vb[1]) * ny
    if not closing > 0.0:
        return va, vb
    j = (1.0 + COLLISION_RESTITUTION) * closing / (1.0 / mass_a + 1.0 / mass_b)

    def capped(vx, vy):
        speed = math.hypot(vx, vy)
        return (vx, vy) if speed <= KNOCK_MAX_MPS else (vx * KNOCK_MAX_MPS / speed, vy * KNOCK_MAX_MPS / speed)
    return (capped(va[0] - j * nx / mass_a, va[1] - j * ny / mass_a),
            capped(vb[0] + j * nx / mass_b, vb[1] + j * ny / mass_b))


def apply_collision_velocity(body, velocity) -> None:
    """An NPC slides with `velocity` (its driver waits, update_knocked);
    the taxi keeps the part along its heading."""
    if isinstance(body, NPCVehicle):
        body.knock_vx, body.knock_vy = velocity
        body.car.speed = 0.0
    else:
        body.speed = velocity[0] * math.cos(body.heading) + velocity[1] * math.sin(body.heading)
SHAKEN_S = 8.0
SHAKEN_SPEED_MPS = 20.0 / 3.6
CURSE_S = 2.5


@dataclass
class TrailerBody:
    """A trailer's current body in the same duck type as a Car (x, y,
    heading, length_m, width_m, speed, layer, map_level), so collision and
    following treat it as one more obstacle; `tow` is its vehicle - a hit on
    the trailer is a hit on the combination."""
    x: float
    y: float
    heading: float
    length_m: float
    width_m: float
    speed: float
    layer: int
    map_level: int
    kind: str
    tow: object


@dataclass
class NPCVehicle:
    """Physical NPC vehicle (autonomous-driving section 3).

    All physical simulation state lives in `car` (physics.Car, driven by
    the same update_car_physics the player uses - no duplicated physics).
    Everything else here is display/identity metadata physics.Car has no
    business knowing about.
    """
    vehicle_id: int
    car: Car
    owner_id: Optional[int] = None  # active driver's resident_id; None => must not move
    state: str = NPCState.SPAWNING
    vehicle_type: str = "car"  # a vehicles/ plugin id (see vehicles/README.md) - never branched on here, only looked up
    color: Tuple[int, int, int] = (150, 155, 165)
    is_taxi: bool = False
    taxi_job: object = None  # a competitor taxi's fare (competitor_taxis.TaxiJob), None when free
    taxi_idle_until: float = 0.0
    brawl_id: Optional[int] = None  # its driver is out quarrelling (taxi_brawls.py): the car stays put
    stolen: bool = False  # a thief rides it: nobody can be inspected on it (protocol "thief")
    rage: float = 0.0  # its driver's temporary rage, 0..1, as last provoked (taxi_brawls.npc_rage)
    rage_at: float = 0.0  # sim time of that provocation; it calms from there
    bus_job: object = None  # a line bus's route and next stop (bus_lines.BusJob)
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
    crashed_timer: float = 0.0  # collision-avoidance: seconds since state became CRASHED (debug/despawn timing)
    # collision-avoidance section 12/13: once True, this vehicle's driver has
    # permanently left it (accident response) - every place that would
    # otherwise resume/reassign driving on this vehicle (start a new trip,
    # continue a trip, get claimed by reserve_household_vehicle, get
    # re-entered by a pedestrian) must check this first. Never cleared -
    # a departed driver never returns to the same vehicle, by design.
    driver_departed: bool = False
    capacity: int = NPC_CAR_CAPACITY
    trip_group: Optional[TripGroup] = None
    # vehicle-population sections 6, 13: "traffic" (autonomous, no owner, current
    # behavior) or "household" (has a home to return to, reservable).
    vehicle_kind: str = "traffic"
    household_id: Optional[int] = None
    home_position: Optional[Tuple[float, float]] = None
    home_parking_space: object = None  # same shape as reserved_parking_space
    availability: str = NPCAvailability.AVAILABLE
    # vehicle-population section 12: True while this household vehicle's current trip
    # is "drive home" - once it parks, the manager retires the trip
    # outright (no building-visit detour) instead of calling
    # continue_npc_trip again. False for every other leg (including a
    # traffic vehicle's endless errands, which never sets it).
    returning_home: bool = False
    # vehicle-population perf: is_vehicle_pose_valid's live footprint safety net
    # (see NPC_FOOTPRINT_CHECK_INTERVAL_S) runs at a reduced rate, not
    # every frame - this is its own per-vehicle accumulator/cache so a
    # skipped frame reuses the last real result instead of assuming clear.
    # Starts already at the interval (not 0.0) so the very first update_
    # npc call after a vehicle starts driving always performs a real
    # check rather than trusting the default "clear" cache for up to
    # NPC_FOOTPRINT_CHECK_INTERVAL_S first.
    footprint_check_elapsed_s: float = NPC_FOOTPRINT_CHECK_INTERVAL_S
    footprint_check_cached: bool = True
    curse_timer: float = 0.0  # > 0: the driver's curse bubble shows (a minor bump by the taxi)
    curse_text: str = ""
    knock_vx: float = 0.0  # non-zero: knocked by a collision, sliding (update_knocked); its driver waits
    knock_vy: float = 0.0
    shaken_timer: float = 0.0  # > 0: after a minor bump the driver goes on slowly
    trailer_axle: Optional[Tuple[float, float]] = None  # a towed trailer's axle (trailers.py), None: straight behind

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
    def trailer_spec(self):
        return vehicle_definition(self.vehicle_type).trailer

    def update_trailer(self) -> None:
        """Pull the trailer after the hitch where the vehicle now stands."""
        spec = self.trailer_spec
        if spec is not None:
            from .trailers import follow, hitch_point
            hitch = hitch_point(self.x, self.y, self.heading, self.length_m)
            self.trailer_axle = follow(hitch, self.trailer_axle, self.heading, spec)

    def trailer_body(self) -> Optional["TrailerBody"]:
        """The trailer as a body of its own (collision, avoidance, drawing), or None."""
        spec = self.trailer_spec
        if spec is None:
            return None
        from .trailers import follow, hitch_point, pose
        hitch = hitch_point(self.x, self.y, self.heading, self.length_m)
        axle = follow(hitch, self.trailer_axle, self.heading, spec)
        x, y, heading = pose(hitch, axle, spec)
        return TrailerBody(x, y, heading, spec.length_m, spec.width_m, self.car.speed, self.car.layer,
                           self.car.map_level, spec.kind, self)

    @property
    def passenger_ids(self) -> Tuple[int, ...]:
        """Trip-group members other than the driver (multi-passenger-car.md:
        "who's riding along", alongside the owner)."""
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


def with_trailers(vehicles) -> list:
    """Nearby vehicles plus their trailers' bodies (TrailerBody): followed,
    avoided and collided with like any vehicle."""
    found = list(vehicles)
    found.extend(body for body in (getattr(vehicle, "trailer_body", lambda: None)() for vehicle in list(found)) if body is not None)
    return found


def has_active_driver(vehicle: NPCVehicle, resident_manager: ResidentManager) -> bool:
    """The fundamental autonomous-driving invariant: moving NPC vehicle == active
    driver Resident. A vehicle whose owning Resident isn't currently
    driving it must never be treated as under power."""
    if vehicle.owner_id is None:
        return False
    resident = resident_manager.get(vehicle.owner_id)
    return resident is not None and resident.active_vehicle_id == vehicle.vehicle_id


def reserve_household_vehicle(vehicle: NPCVehicle) -> bool:
    """vehicle-population section 7: claim a household vehicle for an upcoming trip
    (the future Resident shopping/errand system will call this instead of
    searching for "the nearest NPC car"). Returns False - and reserves
    nothing - if the vehicle isn't a household vehicle, isn't currently
    AVAILABLE (already RESERVED/IN_USE by another trip), or isn't
    genuinely idle (mid-trip, still has a trip group out and about).

    collision-avoidance section 12: a vehicle whose driver has permanently departed
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
    vehicle_length_m: float = NPC_VEHICLE_LENGTH_M,
    vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
    preserve_origin: bool = False,
    origin_heading: Optional[float] = None,
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

    origin_is_off_road (vehicle-population: start_npc_trip, an idle vehicle placed by
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
        vehicle_length_m=vehicle_length_m, vehicle_width_m=vehicle_width_m,
        preserve_origin=preserve_origin,
        origin_heading=origin_heading,
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
    vehicle_length_m: float = NPC_VEHICLE_LENGTH_M,
    vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
    preserve_origin: bool = False,
    origin_heading: Optional[float] = None,
    bus_route: Optional[str] = None,
) -> RouteSteps:
    """_plan_and_validate_npc_route as a resumable job: the route search
    and the curb/building sampling both yield per unit of work. Pure -
    reads the world, never mutates it (bin-loader-v12.md)."""
    raw_route = yield from traffic_world.plan_route_steps(origin, destination, bus_route=bus_route)
    if raw_route is None:
        return None
    if preserve_origin and len(raw_route) >= 3 and (
        math.hypot(raw_route[1][0] - origin[0], raw_route[1][1] - origin[1]) <= vehicle_width_m * 2.0
        and is_point_on_road(*origin, ways=ways, spatial_grid=spatial_grid, car_roads_only=True)
    ):
        # An already lane-positioned car must not turn into its lateral graph snap.
        raw_route = [raw_route[0], *raw_route[2:]]
    if origin_is_off_road and len(raw_route) >= 3:
        # Join the first directed road edge, not its junction behind the driveway.
        px, py, _, gap = closest_point_and_dist_to_segment(
            *origin, *raw_route[1], *raw_route[2],
        )
        if gap <= NPC_PARKING_ACCESS_TOLERANCE_M:
            raw_route = [raw_route[0], (px, py), *raw_route[2:]]
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
    roadside_orientation = None
    if parking_space is None and destination_is_off_road:
        spots = _roadside_spots(*destination, ways, spatial_grid)
        if spots is not None and min(math.hypot(spot[0] - destination[0], spot[1] - destination[1]) for spot in spots[:2]) < 0.1:
            # (Either kerb: picked on the arrival's right where it can be;
            # § 36 also allows safe left-side parking in built-up areas.)
            roadside_orientation = _resting_heading(*destination, None, ways, spatial_grid)
    aligned_route = _align_approach_to_parking_orientation(
        deduped_route, parking_space, orientation=roadside_orientation,
    )
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
        aligned_parking_approach=final_segment_count == 2,
        vehicle_width_m=vehicle_width_m,
        skip_initial_lane_offset=origin_is_off_road or preserve_origin,
    )
    yield
    if len(path) < 2:
        return None
    if not origin_is_off_road:
        start_heading = origin_heading if origin_heading is not None else math.atan2(
            path[1].y - path[0].y, path[1].x - path[0].x,
        )
        if not _npc_body_on_road(
            path[0].x, path[0].y, start_heading, vehicle_length_m, vehicle_width_m,
            ways, spatial_grid, getattr(path[0].way, "layer", 0),
            getattr(path[0].way, "map_level", None) or 0,
        ):
            return None
    final_heading = math.atan2(path[-1].y - path[-2].y, path[-1].x - path[-2].x)
    if _parking_overlaps_walkway(path[-1].x, path[-1].y, final_heading, ways, spatial_grid,
                                 length_m=vehicle_length_m, width_m=vehicle_width_m):
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
        path_points, vehicle_length_m, vehicle_width_m, CURB_CLEARANCE_MARGIN_M,
        curbs=curbs or [], curb_grid=curb_grid,
        skip_leading_m=skip_leading_m, skip_trailing_m=driveway_skip_m,
    )):
        return None
    # NPC-more.md section 13: never drive through a building polygon.
    if (yield from _route_crosses_obstacles_steps(
        path_points, vehicle_length_m, vehicle_width_m, BUILDING_CLEARANCE_MARGIN_M,
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
    (autonomous-driving sections 5, 11, 12).

    The route is planned and validated BEFORE anything is created; a
    vehicle is never spawned to then go hunting for a route while
    already "driving". Returns None if no valid route exists.
    """
    destination_is_off_road = destination_is_off_road or parking_space is not None
    definition = vehicle_definition(vehicle_type)
    path = _plan_and_validate_npc_route(
        traffic_world, ways, origin, destination, spatial_grid=spatial_grid,
        curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
        parking_space=parking_space, destination_is_off_road=destination_is_off_road,
        vehicle_length_m=definition.length_m, vehicle_width_m=definition.width_m,
    )
    if path is None:
        return None

    start = path[0]
    car = Car(x=start.x, y=start.y, heading=0.0, speed=0.0,
              length_m=definition.length_m, width_m=definition.width_m)
    vehicle = NPCVehicle(
        vehicle_id=vehicle_id, car=car, vehicle_type=vehicle_type,
        color=color if color is not None else random.choice(NPC_VEHICLE_COLORS), capacity=definition.capacity,
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
    origin_is_off_road: bool = False,
) -> Driver:
    """Create the Resident group -> TripGroup -> Driver for a vehicle
    about to start driving `path` for the first time - shared by
    spawn_npc (a brand-new vehicle) and start_npc_trip (vehicle-population: an
    existing idle parked vehicle beginning its first/next trip). Mutates
    `vehicle` in place (position/heading, owner_id, way, destination,
    travel_route, trip_group, state, parking reservation) and returns the
    new Driver.

    1. create/select the Resident group, 2. designate its first member as
    driver, 3. place the vehicle at the route's start, 4. associate
    vehicle<->Driver<->TripGroup - in that order, per autonomous-driving section 11 -
    never a moving vehicle first with a driver attached after.

    multi-passenger-car.md sections 2, 5: the group is never auto-filled
    to capacity - a lone driver (group size 1) is exactly as valid as a
    full car.

    member_resident_ids (vehicle-population section 6): a household vehicle's trip
    group is drawn from its *own* already-existing household members
    (created once, at population-fill time, and reused across every trip
    that household ever takes) rather than a fresh anonymous group each
    time - "Household -> Vehicle -> Residents" means the same Residents,
    not new strangers every errand. None (the default) keeps the
    original behavior: a brand-new random group, for anonymous
    TRAFFIC_VEHICLE ambient traffic.
    """
    vehicle.taxi_idle_until = 0.0
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
        members = [resident_manager.create(mode="driving" if i == 0 else "riding",
                   age=random.randint(18, 29) if vehicle.vehicle_kind == "night_cruise" else None)
                   for i in range(group_size)]
    driver_resident = members[0]
    for member in members:
        member.vehicle_ids.add(vehicle.vehicle_id)
        member.active_vehicle_id = vehicle.vehicle_id
        member.mode = "driving" if member is driver_resident else "riding"

    start, aim = path[0], path[1]
    origin_requires_access = origin_is_off_road and not is_point_on_road(
        start.x, start.y, ways=[way for way in (vehicle.way, start.way) if way is not None],
        car_roads_only=True,
    )
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
    vehicle.car.layer = get_road_layer_at_point(
        vehicle.x, vehicle.y, current_layer=vehicle.layer,
        ways=[start.way] if start.way is not None else [], heading=vehicle.heading,
    )
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
        origin_is_off_road=origin_requires_access,
        trip_origin=(vehicle.car.x, vehicle.car.y),
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
    """vehicle-population: an existing idle parked vehicle (see place_parked_npc)
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
        vehicle_length_m=vehicle.length_m, vehicle_width_m=vehicle.width_m,
    )
    if path is None:
        return None
    return _apply_npc_trip(
        vehicle, resident_manager, (path, destination, parking_space, destination_is_off_road),
        member_resident_ids=member_resident_ids,
    )


def _transit_initial_speed(vehicle, plan) -> Optional[float]:
    """Seed freeway through traffic already moving, or reject a short/turning start."""
    path = plan[0]
    way = path[0].way
    if way is None:
        return None  # no identified starting road: do not seed a stationary obstacle
    if way.highway not in ("motorway", "motorway_link", "trunk", "trunk_link"):
        # Ordinary roads: already cruising too (a car standing in the road
        # ahead of a fast player read as broken traffic), at 80 % of the limit
        # but no faster than it can still slow down from before its next turn
        # or its trip's end.
        limit = way.speed_limit_kmh / 3.6 * 0.8
        maximum = vehicle_definition(vehicle.vehicle_type).max_speed_kmh
        if maximum is not None:
            limit = min(limit, maximum / 3.6)
        remaining = sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(path, path[1:]))
        turn = _distance_to_next_turn(path, 0, path[0].x, path[0].y, max_lookahead_m=remaining)
        room = max(0.0, min(remaining, turn if turn is not None else remaining) - vehicle.length_m)
        return max(0.0, min(limit, math.sqrt(2.0 * ARRIVAL_DECEL_MPS2 * room)))
    speed = way.speed_limit_kmh / 3.6 * 0.8  # game policy: enter at 80% of the road limit
    definition = vehicle_definition(vehicle.vehicle_type)
    maximum = definition.max_speed_kmh
    if not definition.is_road_vehicle or (maximum is not None and maximum <= 70):
        return None  # ordinary slow traffic cannot be seeded as motorway traffic
    if maximum is not None:
        speed = min(speed, maximum / 3.6)
    horizon = speed * speed / (2 * ARRIVAL_DECEL_MPS2) + speed + vehicle.length_m
    remaining = sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(path, path[1:]))
    if speed <= 0 or remaining < horizon or _distance_to_next_turn(
        path, 0, path[0].x, path[0].y, max_lookahead_m=horizon,
    ) is not None:
        return None
    return speed


def _transit_clearance(vehicle, speed):
    return max(NPC_TRANSIT_SPAWN_CLEARANCE_M,
               speed * speed / (2 * ARRIVAL_DECEL_MPS2) + speed + vehicle.length_m)


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
        origin_is_off_road=True,
    )


# Cyclists (cycling.py): moving cyclists near the player per moving car the
# local demand asks for - game policy, the game has no modal-split data.
# Winter (snow on the roads or November-March) keeps a hardy few.
CYCLING_SHARE = 0.35
CYCLING_WINTER_FACTOR = 0.25
CYCLIST_SPAWN_JOBS = 1  # cycle spawn route jobs queued at once

NPC_TARGET_COUNT_DEFAULT = 40  # when the city's population is unknown
# The city's target is for its built-up parts: around the player it scales
# with the people the buildings within the spawn radius account for
# (population.py) - a town centre (this many or more) gets all of it, a
# remote road with a few houses a car or two, an empty forest road one
# passing car at most.
NPC_FULL_TRAFFIC_PEOPLE = 1500.0
NPC_LOCAL_TARGET_CELL_M = 100.0  # recounted when the player moves into another cell this size
NPC_DEMAND_ROLL_TICKS = 30  # population ticks (1 min): how long one draw of a fractional moving target holds
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
    vehicle-population: where an idle parked vehicle's BFS destination search
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
    """vehicle-population v2: same check pedestrian.py's spawn_pedestrian/population
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
    """vehicle-population: an idle parked vehicle (population tick decided it's time
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
        destination_candidates = yield from _pick_npc_destination_candidates_steps(
            raw_destination[0], raw_destination[1], parking_spaces, sceneries, buildings,
            ways=ways, spatial_grid=spatial_grid, other_vehicle_positions=other_vehicle_positions,
            own_position=origin,
            vehicle_length_m=vehicle.length_m, vehicle_width_m=vehicle.width_m,
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
                vehicle_length_m=vehicle.length_m, vehicle_width_m=vehicle.width_m,
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


def _next_junction_turn(path: List[PathPoint], path_index: int, x: float, y: float, lookahead_m: float = 30.0):
    """(distance to the turn's middle, that point, heading after the turn)
    for the next left/right junction turn within lookahead_m, else None -
    where a turning driver's § 24(2) duty to crossing cyclists applies."""
    total, prev_x, prev_y = 0.0, x, y
    for i in range(path_index, len(path)):
        point = path[i]
        total += math.hypot(point.x - prev_x, point.y - prev_y)
        if total > lookahead_m:
            return None
        if point.maneuver in ("left", "right"):
            j = i
            while j + 1 < len(path) and path[j + 1].maneuver == point.maneuver:
                j += 1
            middle = path[(i + j) // 2]
            if j + 1 < len(path):
                exit_heading = math.atan2(path[j + 1].y - path[j].y, path[j + 1].x - path[j].x)
            else:
                exit_heading = math.atan2(path[j].y - path[max(i, j - 1)].y, path[j].x - path[max(i, j - 1)].x)
            distance = total + sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(path[i:(i + j) // 2], path[i + 1:(i + j) // 2 + 1]))
            return distance, (middle.x, middle.y), exit_heading
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
    if any(point.is_turn for point in path[segment:segment + 4]):
        lookahead = NPC_PATH_LOOKAHEAD_MIN_M
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
    """collision-avoidance section 6/7: a short, controlled, straight-line back-up -
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

    clear = _clear_behind(vehicle, manager, pedestrian_mgr)

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


def _clear_behind(vehicle, manager, pedestrian_mgr) -> bool:
    """No vehicle or person in the space just behind (§§ 34-35: reverse only
    when it is safe and hinders no one)."""
    heading = vehicle.car.heading
    behind_x = vehicle.car.x - math.cos(heading) * NPC_REVERSE_CLEARANCE_CHECK_RADIUS_M
    behind_y = vehicle.car.y - math.sin(heading) * NPC_REVERSE_CLEARANCE_CHECK_RADIUS_M
    clearance_radius_sq = NPC_REVERSE_CLEARANCE_CHECK_RADIUS_M ** 2
    if manager is not None:
        for other in manager.nearby_vehicles_at(behind_x, behind_y, NPC_REVERSE_CLEARANCE_CHECK_RADIUS_M):
            if other is not vehicle and (other.x - behind_x) ** 2 + (other.y - behind_y) ** 2 < clearance_radius_sq:
                return False
    if pedestrian_mgr is not None:
        for ped in getattr(pedestrian_mgr, "pedestrians", ()):
            if (ped.x - behind_x) ** 2 + (ped.y - behind_y) ** 2 < clearance_radius_sq:
                return False
    return True


# Multi-point manoeuvres (manoeuvre.py): a pose the vehicle cannot drive onto
# forwards - arriving, its final point; setting off, the route a little way on -
# is reached by a planned Reeds-Shepp path of forward and reverse runs (a
# three-point turn, a reverse-and-correct). Reversing waits for clear space
# behind (§§ 34-35); a plan the body cannot follow on the road is not used.
NPC_MANOEUVRE_START_M = 20.0  # from the final point, or from where the trip began
NPC_MANOEUVRE_DEPART_AIM_M = 10.0  # setting off: onto the route this far on
NPC_MANOEUVRE_DEPART_AIMS_M = (6.0, 14.0, 18.0)  # ...or this far, when no lawful manoeuvre reaches that
NPC_MANOEUVRE_TRIES = 3  # plans a trip may make
NPC_MANOEUVRE_SPEED_MPS = 1.5
NPC_MANOEUVRE_WAIT_S = 10.0  # for the space behind to clear, then the manoeuvre is given up
NPC_MANOEUVRE_CLOSE_ENOUGH_M = 3.0  # arriving: stopped this near, where a manoeuvre ran out, is there
NPC_MANOEUVRE_NO_PLAN_STOP_M = 8.0  # ...and this near when no lawful manoeuvre exists (a final point on a junction: stop short)
NPC_MANOEUVRE_REVERSE_CLEAR_M = 1.0  # game policy (§§ 34-35): reversing keeps the body this far out of a junction's carriageway or a crossing
NPC_MANOEUVRE_STOP_CLEAR_M = 5.0  # § 37: no stopping within 5 m of a junction's carriageway or a crossing
NPC_MANOEUVRE_CROSSING_HALF_M = 2.0  # a zebra's half width
NPC_MANOEUVRE_NO_TURNING = ("motorway", "motorway_link")  # nor in a tunnel or on a motor-traffic road (guide: no reversing/U-turns)
NPC_MANOEUVRE_DRIFT_M = 1.0  # the rear axle this far off the plan's checked poses: stop and replan
NPC_MANOEUVRE_CORRIDOR_M = 5.0  # of the run ahead, checked clear every tick
NPC_MANOEUVRE_ONCOMING_S = 4.0  # a vehicle reaching that corridor within this blocks it


def _unreachable_forward(car, x: float, y: float, margin: float) -> bool:
    """Whether (x, y) lies behind the rear axle or within `margin` inside one of
    the car's two full-lock turning circles: no forward drive reaches it."""
    behind, radius = rear_axle_behind(car), min_turn_radius(car)
    fx, fy = math.cos(car.heading), math.sin(car.heading)
    rx, ry = car.x - fx * behind, car.y - fy * behind
    if (x - rx) * fx + (y - ry) * fy < 0.0:
        return True
    return any(math.hypot(x - (rx - fy * radius * side), y - (ry + fx * radius * side)) < radius - margin for side in (1.0, -1.0))


def _skip_route_behind(driver, car) -> None:
    """Setting off: route points still behind the car (where the route search
    joined the road) are not driven back to - a driver pulls out forwards and
    follows the route from its first point ahead."""
    path = driver.path
    fx, fy = math.cos(car.heading), math.sin(car.heading)
    index = driver.path_index
    while index < len(path) - 1 and math.hypot(path[index].x - car.x, path[index].y - car.y) < NPC_MANOEUVRE_START_M \
            and (path[index].x - car.x) * fx + (path[index].y - car.y) * fy < 0.0:
        index += 1
    if index != driver.path_index:
        driver.path_index = index
        driver.route_segment_index = max(driver.route_segment_index, index - 1)


def _route_pose_beyond(path, index: int, x: float, y: float, distance_m: float) -> Tuple[float, float, float]:
    """The route's pose (x, y, heading) from `index` on, the first `distance_m`
    from (x, y) - within a long segment, not at its far end - else its last."""
    for k in range(max(1, index), len(path)):
        a, b = path[k - 1], path[k]
        if math.hypot(b.x - x, b.y - y) >= distance_m:
            length = math.hypot(b.x - a.x, b.y - a.y)
            t = next((i * 0.5 / length for i in range(int(length / 0.5) + 1)
                      if math.hypot(a.x + (b.x - a.x) * i * 0.5 / length - x, a.y + (b.y - a.y) * i * 0.5 / length - y) >= distance_m), 1.0) if length > 0 else 1.0
            return a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, math.atan2(b.y - a.y, b.x - a.x)
    return path[-1].x, path[-1].y, _route_heading(path, len(path) - 1)


def _route_heading(path, k: int) -> float:
    a, b = (path[k - 1], path[k]) if k > 0 else (path[0], path[1])
    return math.atan2(b.y - a.y, b.x - a.x)


def _junction_points(ways) -> List[Tuple[float, float, float]]:
    """Road nodes where three or more road ends meet (an interior node counts
    twice): (x, y, the widest meeting road's half width)."""
    count: Dict[Tuple[float, float], List[float]] = {}
    for way in ways:
        if not getattr(way, "is_drivable", True) or len(way.points_m) < 2:
            continue
        for i, point in enumerate(way.points_m):
            entry = count.setdefault((round(point[0], 1), round(point[1], 1)), [0, 0.0])
            entry[0] += 1 if i in (0, len(way.points_m) - 1) else 2
            entry[1] = max(entry[1], way.half_width_m)
    return [(x, y, half) for (x, y), (n, half) in count.items() if n >= 3]


def _manoeuvre_ways(vehicle, x0, y0, x1, y1, ways, spatial_grid):
    """The car's own layer and level's drivable ways in a box."""
    car = vehicle.car
    nearby = spatial_grid.ways_in_rect(x0, y0, x1, y1) if spatial_grid is not None else ways
    level = getattr(car, "map_level", 0) or 0
    return [way for way in nearby if getattr(way, "is_drivable", True) and on_map_level(way, level)
            and getattr(way, "layer", 0) == getattr(car, "layer", 0)]


def _manoeuvre_controls(vehicle, x0, y0, x1, y1, ways, spatial_grid, traffic_world):
    """Junctions and crossings of the car's layer around a manoeuvre, gathered
    once a plan (not a pose): (x, y, the carriageway's half width there)."""
    nearby = _manoeuvre_ways(vehicle, x0 - 30.0, y0 - 30.0, x1 + 30.0, y1 + 30.0, ways, spatial_grid)
    layer = getattr(vehicle.car, "layer", 0)
    return _junction_points(nearby) + [
        (c.x, c.y, NPC_MANOEUVRE_CROSSING_HALF_M) for c in getattr(traffic_world, "crossings", ())
        if x0 - 30.0 <= c.x <= x1 + 30.0 and y0 - 30.0 <= c.y <= y1 + 30.0 and getattr(c, "layer", layer) == layer]


def _clear_of_controls(vehicle, cx, cy, yaw, controls, margin_m) -> bool:
    """The body (its centre line, less half its width) at least `margin_m`
    outside every junction's carriageway and every crossing."""
    half = vehicle.length_m * 0.5
    ax, ay = cx - math.cos(yaw) * half, cy - math.sin(yaw) * half
    bx, by = cx + math.cos(yaw) * half, cy + math.sin(yaw) * half
    return all(dist_point_to_segment(x, y, ax, ay, bx, by) - vehicle.width_m * 0.5 - edge >= margin_m
               for x, y, edge in controls)


def _may_stop_here(vehicle, traffic_world, spatial_grid) -> bool:
    """§ 37: stopping short of a final point only at least 5 m outside a junction's carriageway and a crossing."""
    car = vehicle.car
    controls = _manoeuvre_controls(vehicle, car.x, car.y, car.x, car.y, traffic_world.ways, spatial_grid, traffic_world)
    return _clear_of_controls(vehicle, car.x, car.y, car.heading, controls, NPC_MANOEUVRE_STOP_CLEAR_M)


def _manoeuvre_pose_lawful(vehicle, cx, cy, yaw, direction, near_end, ways, spatial_grid, traffic_world,
                           buildings, building_grid, controls=None) -> bool:
    """A pose of a planned manoeuvre: on the road (near the trip's own off-road
    start or end: its yard access, but never a footway or a building), not on
    a motorway, motor-traffic road or in a tunnel (law), never moving against
    a one-way street (§§ 18-22), and - game policy under §§ 34-35 "safely" -
    never reversing within NPC_MANOEUVRE_REVERSE_CLEAR_M of a junction's
    carriageway or a crossing. Only the car's own layer and level count."""
    reach = math.hypot(vehicle.length_m, vehicle.width_m) * 0.5
    motion = yaw + (math.pi if direction < 0 else 0.0)
    for way in _manoeuvre_ways(vehicle, cx - reach, cy - reach, cx + reach, cy + reach, ways, spatial_grid):
        segment = min(zip(way.points_m, way.points_m[1:]), default=None,
                      key=lambda ab: dist_point_to_segment(cx, cy, ab[0][0], ab[0][1], ab[1][0], ab[1][1]))
        if segment is None or dist_point_to_segment(cx, cy, *segment[0], *segment[1]) > way.half_width_m + reach:
            continue
        if way.highway in NPC_MANOEUVRE_NO_TURNING or getattr(way, "motorroad", False) or getattr(way, "is_tunnel", False):
            return False
        oneway = getattr(way, "oneway", 0) or 0
        if oneway:
            (ax, ay), (bx, by) = segment
            allowed = math.atan2(by - ay, bx - ax) + (math.pi if oneway < 0 else 0.0)
            if math.cos(motion - allowed) < 0.0:
                return False
    if direction < 0:
        if controls is None:
            controls = _manoeuvre_controls(vehicle, cx, cy, cx, cy, ways, spatial_grid, traffic_world)
        if not _clear_of_controls(vehicle, cx, cy, yaw, controls, NPC_MANOEUVRE_REVERSE_CLEAR_M):
            return False
    if near_end:
        return not _parking_overlaps_walkway(cx, cy, yaw, ways, spatial_grid, length_m=vehicle.length_m, width_m=vehicle.width_m) \
            and is_vehicle_pose_valid(cx, cy, yaw, buildings=buildings, building_grid=building_grid,
                                      length_m=vehicle.length_m, width_m=vehicle.width_m)
    car = vehicle.car
    return _npc_body_on_road(cx, cy, yaw, vehicle.length_m, vehicle.width_m, ways, spatial_grid,
                             getattr(car, "layer", 0), getattr(car, "map_level", 0) or 0)


def _plan_manoeuvre(vehicle, driver, goal_x, goal_y, goal_heading, ways, spatial_grid, traffic_world=None,
                    buildings=None, building_grid=None) -> bool:
    """Plan a manoeuvre onto the centre pose (goal_x, goal_y, goal_heading);
    True when the driver now has one, lawful at every pose (_manoeuvre_pose_lawful)."""
    from . import manoeuvre
    car = vehicle.car
    behind = rear_axle_behind(car)
    ends = [end for end, off_road in ((driver.trip_origin, driver.origin_is_off_road), ((goal_x, goal_y), driver.destination_is_off_road))
            if end is not None and off_road]  # yards only: a kerbside end is no licence to leave the road

    x0, x1 = min(car.x, goal_x) - 20.0, max(car.x, goal_x) + 20.0
    y0, y1 = min(car.y, goal_y) - 20.0, max(car.y, goal_y) + 20.0
    controls = _manoeuvre_controls(vehicle, x0, y0, x1, y1, ways, spatial_grid, traffic_world)

    def valid(rx, ry, yaw, direction):
        cx, cy = rx + math.cos(yaw) * behind, ry + math.sin(yaw) * behind
        near_end = any(math.hypot(cx - ex, cy - ey) <= NPC_PARKING_ACCESS_TOLERANCE_M for ex, ey in ends)
        return _manoeuvre_pose_lawful(vehicle, cx, cy, yaw, direction, near_end, ways, spatial_grid, traffic_world,
                                      buildings, building_grid, controls)

    start = (car.x - math.cos(car.heading) * behind, car.y - math.sin(car.heading) * behind, car.heading)
    goals = [(goal_x, goal_y, goal_heading)]
    if driver.manoeuvre_zone == "departing":  # rsplan gives the shortest path only: where it clips a kerb, aim elsewhere on the route
        goals += [_route_pose_beyond(driver.path, driver.path_index, car.x, car.y, aim) for aim in NPC_MANOEUVRE_DEPART_AIMS_M]
    elif driver.manoeuvre_zone == "arriving":  # a stop or a yard spot: any heading the plan reaches it at
        goals.append((goal_x, goal_y, car.heading))
    driver.manoeuvres_tried += 1
    runs = None
    for gx, gy, gh in goals:
        runs = manoeuvre.plan(start, (gx - math.cos(gh) * behind, gy - math.sin(gh) * behind, gh), min_turn_radius(car), valid)
        if runs is not None:
            break
    driver.manoeuvre, driver.manoeuvre_run, driver.manoeuvre_wait_s = runs, 0, 0.0
    return runs is not None


def _manoeuvre_corridor_clear(vehicle, run, behind, manager, pedestrian_mgr) -> bool:
    """The next NPC_MANOEUVRE_CORRIDOR_M of the run - forward or reverse - swept
    by the body is clear: no vehicle or person in it, no vehicle on the same
    map level reaching it within NPC_MANOEUVRE_ONCOMING_S (§§ 34-35: turn
    round and reverse only safely and hindering no one)."""
    car = vehicle.car
    rx, ry = car.x - math.cos(car.heading) * behind, car.y - math.sin(car.heading) * behind
    nearest = min(range(len(run)), key=lambda i: (run[i][0] - rx) ** 2 + (run[i][1] - ry) ** 2)
    poses = [(x + math.cos(yaw) * behind, y + math.sin(yaw) * behind) for x, y, yaw, _ in run[nearest:nearest + int(NPC_MANOEUVRE_CORRIDOR_M / 0.25) + 1:2]]
    if not poses:
        return True
    clearance = vehicle.length_m * 0.5 + 1.0
    xs, ys = [p[0] for p in poses], [p[1] for p in poses]
    level = getattr(car, "map_level", 0) or 0
    if manager is not None:
        reach = clearance + 30.0
        for other in manager.nearby_vehicles_at((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, reach):
            if other is vehicle or (getattr(other.car, "map_level", 0) or 0) != level or getattr(other.car, "layer", 0) != getattr(car, "layer", 0):
                continue
            room = clearance + other.length_m * 0.5
            hx, hy, v = math.cos(other.heading), math.sin(other.heading), max(0.0, other.speed)
            for t in (0.0, 1.0, 2.0, 3.0, NPC_MANOEUVRE_ONCOMING_S):
                ox, oy = other.x + hx * v * t, other.y + hy * v * t
                if any((ox - px) ** 2 + (oy - py) ** 2 < room * room for px, py in poses):
                    return False
                if v == 0.0:
                    break
    if pedestrian_mgr is not None:
        x0, x1, y0, y1 = min(xs) - clearance, max(xs) + clearance, min(ys) - clearance, max(ys) + clearance
        for ped in getattr(pedestrian_mgr, "pedestrians", ()):  # ponytail: one pass a tick per manoeuvring vehicle; a grid if many manoeuvre at once
            if x0 <= ped.x <= x1 and y0 <= ped.y <= y1 and getattr(ped, "state", None) not in ("in_vehicle", "in_building") \
                    and any((ped.x - px) ** 2 + (ped.y - py) ** 2 < clearance * clearance for px, py in poses):
                return False
    return True


def _drive_manoeuvre(vehicle, driver, dt, manager, pedestrian_mgr) -> bool:
    """One tick of the planned manoeuvre; False when it is over (done, or given up)."""
    from . import manoeuvre
    car = vehicle.car
    behind = rear_axle_behind(car)
    run = driver.manoeuvre[driver.manoeuvre_run]
    steer, run_done = manoeuvre.follow(run, car.x - math.cos(car.heading) * behind, car.y - math.sin(car.heading) * behind, car.heading)
    if run_done:
        car.speed = 0.0  # a stop at each change of direction
        driver.manoeuvre_run += 1
        if driver.manoeuvre_run >= len(driver.manoeuvre):
            driver.manoeuvre = None
            return False
        return True
    reverse = run[0][3] < 0
    vehicle.state = NPCState.PARKING if driver.manoeuvre_zone == "arriving" else NPCState.TURNING
    vehicle.debug_waiting_for = ""
    if not _manoeuvre_corridor_clear(vehicle, run, behind, manager, pedestrian_mgr):
        car.speed = 0.0
        driver.manoeuvre_wait_s += dt
        vehicle.debug_waiting_for = "manoeuvring - waiting for a clear way"
        if driver.manoeuvre_wait_s > NPC_MANOEUVRE_WAIT_S:
            driver.manoeuvre = None
            return False
        return True
    previous = (car.x, car.y, car.heading)
    update_car_physics(
        car, throttle=0.0 if reverse else 1.0, brake=1.0 if reverse else 0.0,
        steer_left=max(0.0, steer), steer_right=max(0.0, -steer), dt=dt, block_offroad=False,
        speed_limit_mps=NPC_REVERSE_SPEED_MPS if reverse else NPC_MANOEUVRE_SPEED_MPS,
    )
    rear_x, rear_y = car.x - math.cos(car.heading) * behind, car.y - math.sin(car.heading) * behind
    if min(math.hypot(x - rear_x, y - rear_y) for x, y, _yaw, _d in run) > NPC_MANOEUVRE_DRIFT_M:
        car.x, car.y, car.heading = previous  # off the checked plan: stop, plan afresh
        car.speed = 0.0
        driver.manoeuvre = None
    return True


def _npc_body_on_road(x, y, heading, length_m, width_m, ways, spatial_grid, layer, map_level=0):
    radius = math.hypot(length_m, width_m) * 0.5
    nearby = list(spatial_grid.ways_in_rect(x - radius, y - radius, x + radius, y + radius)) if spatial_grid else ways
    nearby = [way for way in nearby if on_map_level(way, map_level)]
    c, s = math.cos(heading), math.sin(heading)
    return all(is_point_on_road(
        x + c * along - s * across, y + s * along + c * across,
        ways=nearby, car_roads_only=True, layer=layer,
    ) for along in (-length_m * 0.5, 0.0, length_m * 0.5)
      for across in (-width_m * 0.5, 0.0, width_m * 0.5))


def _npc_parking_access(vehicle, driver, x, y, ways, spatial_grid=None, layer=None) -> bool:
    """Recognize the same bounded access corridor in motion and recovery."""
    path = driver.path
    if len(path) < 2:
        return False
    layer = getattr(driver.current_way, "layer", vehicle.car.layer) if layer is None else layer
    reach = NPC_PARKING_ACCESS_TOLERANCE_M * 2.0
    legs = []
    if math.hypot(x - path[-1].x, y - path[-1].y) <= reach and (
        vehicle.reserved_parking_space is not None or (
            driver.destination_is_off_road and not is_point_on_road(
                path[-1].x, path[-1].y, ways=ways, spatial_grid=spatial_grid,
                car_roads_only=True, layer=layer,
            )
        )
    ):
        remaining = reach
        for index in range(len(path) - 2, max(-1, len(path) - 34), -1):
            a, b = path[index], path[index + 1]
            remaining -= math.hypot(b.x - a.x, b.y - a.y)
            if remaining < 0.0:
                break
            legs.append((a, b))
    if driver.origin_is_off_road and driver.trip_origin is not None and (
        math.hypot(x - driver.trip_origin[0], y - driver.trip_origin[1]) <= reach
    ):
        legs.append((PathPoint(*driver.trip_origin), path[0]))
        remaining = reach
        for a, b in zip(path[:32], path[1:33]):
            remaining -= math.hypot(b.x - a.x, b.y - a.y)
            if remaining < 0.0:
                break
            legs.append((a, b))
    for a, b in legs:
        if math.hypot(b.x - a.x, b.y - a.y) > reach:
            continue
        *_, gap = closest_point_and_dist_to_segment(x, y, a.x, a.y, b.x, b.y)
        if gap <= vehicle.width_m * 0.5 + 0.3:
            return True
    return False


def _npc_motion_stays_on_road(vehicle, driver, previous, ways, spatial_grid=None) -> bool:
    """Check the actual-size swept body, allowing only the bounded parking leg."""
    car = vehicle.car
    distance = math.hypot(car.x - previous[0], car.y - previous[1])
    rotation = abs(angle_diff(car.heading, previous[2]))
    if distance < 1e-9 and rotation < 1e-9:
        return True
    samples = max(1, math.ceil((distance + rotation * vehicle.length_m * 0.5) / 1.0))
    if samples > 32:
        return False
    radius = math.hypot(vehicle.length_m, vehicle.width_m) * 0.5
    minx, miny = min(previous[0], car.x) - radius, min(previous[1], car.y) - radius
    maxx, maxy = max(previous[0], car.x) + radius, max(previous[1], car.y) + radius
    nearby = list(spatial_grid.ways_in_rect(minx, miny, maxx, maxy)) if spatial_grid is not None else [
        way for way in ways if not getattr(way, "bbox", None) or way.bbox == (0.0, 0.0, 0.0, 0.0) or (
            way.bbox[2] + way.half_width_m >= minx and way.bbox[0] - way.half_width_m <= maxx
            and way.bbox[3] + way.half_width_m >= miny and way.bbox[1] - way.half_width_m <= maxy
        )
    ]
    layer = getattr(driver.current_way, "layer", car.layer)
    nearby = [way for way in nearby if on_map_level(way, car.map_level)]

    # A turning car crossing the kerb corner was stopped there for good
    # ("road boundary", then "stuck - awaiting recovery", in the road).
    # Only at a junction (two roads within reach): steering back from a bad
    # heading on an open road is "turning" too, and must stay on the road.
    turning = vehicle.state in (NPCState.TURNING, NPCState.APPROACHING_INTERSECTION) and sum(
        1 for way in nearby if way.is_drivable and len(way.points_m) >= 2 and min(
            dist_point_to_segment(car.x, car.y, *a, *b) for a, b in zip(way.points_m, way.points_m[1:])
        ) <= way.half_width_m + vehicle.width_m
    ) >= 2
    for step in range(1, samples + 1):
        t = step / samples
        x = previous[0] + (car.x - previous[0]) * t
        y = previous[1] + (car.y - previous[1]) * t
        heading = previous[2] + angle_diff(car.heading, previous[2]) * t
        if turning:  # a turn may cut over the kerb corner (roads are straight strips): only its centre must stay on
            covered = is_point_on_road(x, y, ways=nearby, car_roads_only=True, layer=layer)
        else:
            covered = _npc_body_on_road(x, y, heading, vehicle.length_m, vehicle.width_m,
                                        nearby, None, layer, car.map_level)
        if not covered and not _npc_parking_access(vehicle, driver, x, y, nearby, None, layer):
            return False
    return True


def _enforce_npc_road_motion(vehicle, driver, previous, traffic_world, spatial_grid, manager, buildings=None, building_grid=None):
    if _npc_motion_stays_on_road(vehicle, driver, previous, traffic_world.ways, spatial_grid):
        # Follow the occupied route road, not an overlapping bridge or a lookahead road not yet reached.
        vehicle.car.layer = get_road_layer_at_point(
            vehicle.x, vehicle.y, current_layer=vehicle.layer,
            ways=[driver.current_way] if driver.current_way is not None else [], heading=vehicle.heading,
        )
        return
    vehicle.car.x, vehicle.car.y, vehicle.car.heading = previous
    vehicle.car.speed = 0.0
    if driver.manoeuvre_zone is not None and driver.manoeuvre is None and driver.manoeuvres_tried < NPC_MANOEUVRE_TRIES:
        # Arriving or setting off: the kerb is where to turn round, not a dead end.
        path = driver.path
        if driver.manoeuvre_zone == "arriving":
            goal = (path[-1].x, path[-1].y, _route_heading(path, len(path) - 1))
        else:
            goal = _route_pose_beyond(path, driver.path_index, vehicle.car.x, vehicle.car.y, NPC_MANOEUVRE_DEPART_AIM_M)
        if _plan_manoeuvre(vehicle, driver, *goal, traffic_world.ways, spatial_grid, traffic_world, buildings, building_grid):
            return
        if driver.manoeuvre_zone == "arriving" and math.hypot(goal[0] - vehicle.car.x, goal[1] - vehicle.car.y) < NPC_MANOEUVRE_NO_PLAN_STOP_M \
                and _may_stop_here(vehicle, traffic_world, spatial_grid):
            driver.path_index = len(path) - 1  # stopped short where no lawful manoeuvre reaches it: arrived
            driver.destination = (vehicle.car.x, vehicle.car.y)
            path[-1] = dataclasses.replace(path[-1], x=vehicle.car.x, y=vehicle.car.y)
            return
    vehicle.state = NPCState.WAITING
    vehicle.debug_waiting_for = "road boundary - awaiting validated route"
    driver.target_speed_mps = 0.0
    driver.recovery_stage = "STUCK"
    if manager is not None:
        diagnostics = manager.population_diagnostics
        diagnostics["road_boundary_blocks"] = diagnostics.get("road_boundary_blocks", 0) + 1


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
    spatial_grid: Optional[SpatialWayGrid] = None,
) -> None:
    """Advance one NPC's driving decision and physics by one frame
    (autonomous-driving sections 5-10). Pure simulation.

    Performance (section 16): the route is never recalculated here (only
    once, in spawn_npc); the per-frame scan is the traffic-light lookup,
    which reuses TrafficWorld._nearby_traffic_lights - the same call the
    player's own red-light assist already makes every frame. The live
    footprint check (below) is *not* cheap against real dense OSM data
    (profiled: ~1-2ms/call, dominated by genuine nearby curb/building
    count, not a spatial-grid tuning issue) - harmless at autonomous-driving's single
    always-on car, but a real per-frame cost multiplied across vehicle-population's
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

    nearby_obstacles = [o for o in nearby_obstacles or ()
                        if getattr(o, "layer", vehicle.layer) == vehicle.layer
                        and getattr(getattr(o, "car", o), "map_level", vehicle.car.map_level)
                        == vehicle.car.map_level]

    # shortcut: displacement can count a large wiggle; use route progress if observed.
    if driver.recovery_anchor is not None and math.hypot(
        vehicle.x - driver.recovery_anchor[0], vehicle.y - driver.recovery_anchor[1],
    ) >= NPC_RECOVERY_PROGRESS_M:
        driver.recovery_anchor = None
        driver.recovery_route_attempts = 0
        driver.hold_failures = 0

    if vehicle.state == NPCState.REVERSING:
        _set_turn_signal(vehicle, "", dt)
        previous = (vehicle.car.x, vehicle.car.y, vehicle.car.heading)
        _update_npc_reversing(vehicle, driver, dt, manager, pedestrian_mgr)
        _enforce_npc_road_motion(vehicle, driver, previous, traffic_world, spatial_grid, manager, buildings, building_grid)
        protests = getattr(manager, "protests", None)
        if protests is not None and protests.blocks_movement(vehicle.car, previous):
            vehicle.car.x, vehicle.car.y, vehicle.car.heading = previous
            vehicle.car.speed = 0.0
        return

    if vehicle.state == NPCState.PARKED:
        _set_turn_signal(vehicle, "", dt)
        # multi-passenger-car.md sections 17-20: a genuinely stationary
        # parked vehicle has no driving decision left to make - no traffic
        # light lookup, no footprint check - just trip-group bookkeeping.
        # The caller's per-tick NPC update checks trip_group.all_
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
                # Passengers may be left behind; the car still needs its actual driver.
                stranded = set(group.member_resident_ids) - group.boarded_resident_ids - {vehicle.owner_id}
                for resident_id in stranded:
                    resident = resident_manager.get(resident_id)
                    if resident is not None:
                        resident.trip_group_id = None
                group.member_resident_ids = [
                    resident_id for resident_id in group.member_resident_ids if resident_id not in stranded
                ]
        return

    path = driver.path
    if (driver.origin_is_off_road or vehicle.car.speed < 1.0) and driver.path_index <= 2 and driver.trip_origin is not None:
        _skip_route_behind(driver, vehicle.car)
    # Pure pursuit tracks the route with the rear axle (physics.rear_axle_shift): the point the car turns about.
    axle_behind = rear_axle_behind(vehicle.car)
    target, _lookahead = _path_follow_target(
        driver, vehicle.car.x - math.cos(vehicle.car.heading) * axle_behind,
        vehicle.car.y - math.sin(vehicle.car.heading) * axle_behind, vehicle.car.speed)
    route_target = path[driver.path_index]
    if route_target.way is not None:
        driver.current_way = route_target.way
        vehicle.way = route_target.way

    approaching_final_waypoint = driver.path_index >= len(path) - 1
    final_point = path[-1]
    distance_to_target = math.hypot(final_point.x - vehicle.car.x, final_point.y - vehicle.car.y)
    at_destination = approaching_final_waypoint and distance_to_target < NPC_ARRIVAL_RADIUS_M
    # Multi-point manoeuvres (_plan_manoeuvre): arriving, onto the final point;
    # setting off (still near where the trip began), onto the route a little way on.
    arriving = (approaching_final_waypoint or driver.path_index >= len(path) - 3) and distance_to_target < NPC_MANOEUVRE_START_M
    departing = (not approaching_final_waypoint and driver.trip_origin is not None
                 and math.hypot(vehicle.x - driver.trip_origin[0], vehicle.y - driver.trip_origin[1]) < NPC_MANOEUVRE_START_M)
    driver.manoeuvre_zone = None if at_destination else "arriving" if arriving else "departing" if departing else None
    if driver.manoeuvre is not None:
        if _drive_manoeuvre(vehicle, driver, dt, manager, pedestrian_mgr):
            return
        if arriving:  # the manoeuvre ran its course: this near is there
            distance_to_target = math.hypot(final_point.x - vehicle.car.x, final_point.y - vehicle.car.y)
            at_destination = distance_to_target < (NPC_MANOEUVRE_CLOSE_ENOUGH_M if driver.manoeuvres_tried >= NPC_MANOEUVRE_TRIES
                                                    else NPC_ARRIVAL_RADIUS_M)  # else creep the rest, or manoeuvre again
    elif driver.manoeuvre_zone is not None and abs(vehicle.car.speed) < 1.0 and driver.manoeuvres_tried < NPC_MANOEUVRE_TRIES:
        if arriving:
            goal = (final_point.x, final_point.y, _route_heading(path, len(path) - 1))
        else:
            goal = _route_pose_beyond(path, driver.path_index, vehicle.car.x, vehicle.car.y, NPC_MANOEUVRE_DEPART_AIM_M)
        if _unreachable_forward(vehicle.car, goal[0], goal[1], 0.3):
            if _plan_manoeuvre(vehicle, driver, *goal, traffic_world.ways, spatial_grid, traffic_world, buildings, building_grid):
                return
            if arriving and distance_to_target < NPC_MANOEUVRE_NO_PLAN_STOP_M and _may_stop_here(vehicle, traffic_world, spatial_grid):
                at_destination = True  # no lawful way onto it: here, short of it
    # A physics-drifted car must clear a curb/building before arrival can stop it.
    vehicle.footprint_check_elapsed_s += dt
    if vehicle.footprint_check_elapsed_s >= NPC_FOOTPRINT_CHECK_INTERVAL_S:
        vehicle.footprint_check_elapsed_s = 0.0
        vehicle.footprint_check_cached = is_vehicle_pose_valid(
            vehicle.car.x, vehicle.car.y, vehicle.car.heading,
            curbs=curbs, buildings=buildings, curb_grid=curb_grid, building_grid=building_grid,
            length_m=vehicle.length_m, width_m=vehicle.width_m, clearance_m=NPC_LIVE_FOOTPRINT_CLEARANCE_M,
        )
    footprint_clear = vehicle.footprint_check_cached
    # Only the actual off-road hop (at most NPC_PARKING_ACCESS_TOLERANCE_M,
    # the most route validation allows) is driven at yard pace - not the
    # whole final leg, which can be a long straight road stretch.
    in_offroad_approach = (
        driver.destination_is_off_road
        and distance_to_target <= NPC_PARKING_ACCESS_TOLERANCE_M * 2.0
    )
    in_offroad_departure = (
        driver.origin_is_off_road and driver.trip_origin is not None
        and math.hypot(vehicle.x - driver.trip_origin[0], vehicle.y - driver.trip_origin[1])
        <= NPC_PARKING_ACCESS_TOLERANCE_M * 2.0
    )

    nearby_lights = traffic_world._nearby_traffic_lights(vehicle.car.x, vehicle.car.y)
    speed_limit_mps = (driver.current_way.speed_limit_kmh / 3.6) if driver.current_way else None
    decision = decide_traffic_action(
        vehicle.car.x, vehicle.car.y, vehicle.car.heading, nearby_lights, traffic_world.sim_time,
        speed_limit_mps=speed_limit_mps,
        actual_speed_mps=vehicle.car.speed,
        stop_buffer_m=max(4.0, vehicle.length_m * 0.5 + 2.0),
        yellow_stop_light=(driver.decision.light if driver.decision.reason == "yellow light, stopping in time" else None),
    )
    crossing_decision = None
    if decision.light is None:
        signs = traffic_world.nearby_signs(vehicle.x, vehicle.y)
        crossing_decision = crossing_yield_decision(
            vehicle, nearby_obstacles or (),
            signs=signs,
            speed_limit_mps=speed_limit_mps,
        )
        if crossing_decision is not None and crossing_decision.target_speed_mps <= decision.target_speed_mps:
            decision = crossing_decision
        # How long it has stood yielding to its right: crossing_yield_decision's gridlock tie-break.
        vehicle.yield_wait_s = (getattr(vehicle, "yield_wait_s", 0.0) + dt
                                if crossing_decision is not None and crossing_decision.reason == "yielding to traffic from right"
                                and abs(vehicle.car.speed) < 0.3 else 0.0)
        stop_decision = stop_sign_decision(vehicle, driver, [sign for sign in signs if isinstance(sign, StopSign)], speed_limit_mps)
        if stop_decision is not None:
            crossing_decision = stop_decision if crossing_decision is None else crossing_decision
            if stop_decision.target_speed_mps <= decision.target_speed_mps:
                decision = stop_decision
    else:
        driver.stop_sign_key, driver.stop_sign_satisfied = None, False
    turn = _next_junction_turn(path, driver.path_index, vehicle.car.x, vehicle.car.y) if any(
        cycling.is_cyclist(o) for o in nearby_obstacles or ()) else None
    if turn is not None:  # § 24(2), also on a green light: yield to cyclists crossing our turn
        cap = cycling.turning_yield_to_cyclists(vehicle, turn[1], turn[2], turn[0], nearby_obstacles)
        if cap is not None and cap <= decision.target_speed_mps:
            decision = TrafficDecision(TrafficAction.STOP if cap < 0.1 else TrafficAction.SLOW, cap,
                                       reason="turning: yielding to a cyclist")
            crossing_decision = crossing_decision or decision  # a lawful wait, not stuck
    protests = getattr(manager, "protests", None)
    protest_cap = protests.speed_cap(vehicle.car) if protests is not None else None
    if protest_cap is not None and protest_cap < decision.target_speed_mps:
        decision = TrafficDecision(TrafficAction.STOP if protest_cap < 0.5 else TrafficAction.SLOW,
                                   protest_cap, reason="Ilokapina sit-in")
    driver.decision = decision
    driver.target_speed_mps = decision.target_speed_mps
    # vehicle-population v2 section 4: a vehicle plugin's own max speed (e.g. a bus/
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
        arrival_cap = math.sqrt(2.0 * ARRIVAL_DECEL_MPS2 * max(0.0, remaining_m - (NPC_ARRIVAL_RADIUS_M if footprint_clear else 0.0)))
        driver.target_speed_mps = min(driver.target_speed_mps, arrival_cap)
    if in_offroad_approach or in_offroad_departure:
        driver.target_speed_mps = min(driver.target_speed_mps, NPC_OFFROAD_APPROACH_SPEED_MPS)

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

    # collision-avoidance section 2: slow/stop for whatever's directly ahead in this
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
    pass_offset = _pass_offset_m(driver.current_way, vehicle.width_m)
    passing = driver.passing
    if passing is not None:
        hx, hy = math.cos(avoidance_heading), math.sin(avoidance_heading)
        passed = (passing.x - vehicle.car.x) * hx + (passing.y - vehicle.car.y) * hy < -(
            vehicle.length_m * 0.5 + getattr(passing, "length_m", NPC_VEHICLE_LENGTH_M) * 0.5 + NPC_PASS_CLEARANCE_M)
        towed = manager is not None and not any(v is passing for v in getattr(manager, "vehicles", ()))
        if passed or towed or not _is_stalled(passing):
            driver.passing = passing = None
        else:  # steer for the oncoming lane until past it
            target = PathPoint(target.x - hy * pass_offset, target.y + hx * pass_offset,
                               target.way, target.is_turn, target.maneuver, target.lane_bias)
            driver.target_speed_mps = min(driver.target_speed_mps, NPC_PASS_SPEED_MPS)
    avoidance_blocked = False
    lead = nearest_vehicle_ahead(
        vehicle.car.x, vehicle.car.y, avoidance_heading, [o for o in nearby_obstacles or () if o is not passing],
        self_id=id(vehicle),
        detection_distance_m=following_detection_distance(vehicle),
        lateral_limit_m=NPC_AVOIDANCE_LATERAL_LIMIT_M,
    )
    route_lead = _stalled_vehicle_on_route(
        vehicle, driver, [o for o in nearby_obstacles or () if o is not passing], following_detection_distance(vehicle))
    if route_lead is not None and (lead is None or route_lead[0] < lead[0]):
        lead = route_lead
    if lead is not None:
        gap, obstacle = lead
        lead_length_m = getattr(obstacle, "length_m", NPC_VEHICLE_LENGTH_M)
        lead_speed_mps = max(0.0, getattr(obstacle, "speed", 0.0))
        # Behind a vehicle that will not move: room for this one's nose to swing out
        # past it (a bus stopped car-length close never could, and waited for good).
        stop_gap = (max(NPC_PASS_START_GAP_M, vehicle.length_m * 0.5 + NPC_AVOIDANCE_MIN_GAP_M + 0.5)
                    if _is_stalled(obstacle) else NPC_AVOIDANCE_MIN_GAP_M)
        following_gap = max(0.0, gap - lead_length_m * 0.5 - vehicle.length_m * 0.5 - stop_gap)
        avoidance_cap = math.sqrt(
            lead_speed_mps * lead_speed_mps + 2.0 * NPC_AVOIDANCE_DECEL_MPS2 * following_gap
        )
        driver.target_speed_mps = min(driver.target_speed_mps, avoidance_cap)
        avoidance_blocked = following_gap <= 0.1 and lead_speed_mps < 0.5
    if (passing is None and lead is not None and _is_stalled(lead[1]) and abs(vehicle.car.speed) < 0.5
            and following_gap < stop_gap
            # Leave room for the nose to swing aside before ignoring the wreck.
            and math.hypot(lead[1].x - vehicle.x, lead[1].y - vehicle.y)
            >= lead_length_m * 0.5 + vehicle.length_m + NPC_AVOIDANCE_MIN_GAP_M):
        driver.pass_wait_s += dt
        if driver.pass_wait_s >= NPC_PASS_WAIT_S:
            oncoming = list(nearby_obstacles or ())
            if manager is not None:
                oncoming += manager.nearby_vehicles_at(vehicle.car.x, vehicle.car.y, NPC_PASS_ONCOMING_CHECK_M)
            if _oncoming_lane_clear(vehicle.car.x, vehicle.car.y, avoidance_heading, pass_offset, vehicle.width_m, oncoming, lead[1]):
                driver.passing, driver.pass_wait_s = lead[1], 0.0
    else:
        driver.pass_wait_s = 0.0

    # § 25 / §§ 3-5: setting off from a parking spot or a stop, yield to traffic
    # coming from either direction (a taxi pulled out in front of a truck at 36 km/h).
    pull_out_wait = departing and abs(vehicle.car.speed) < NPC_PULL_OUT_MAX_SPEED_MPS and _traffic_approaching(
        vehicle, nearby_obstacles or ())
    if pull_out_wait:
        driver.target_speed_mps = 0.0

    if at_destination and footprint_clear:
        driver.target_speed_mps = 0.0
        if vehicle.reserved_parking_space is not None:
            # RESERVED -> OCCUPIED (NPC-more.md section 4's state trio) -
            # the vehicle has actually arrived, not merely en route.
            vehicle.reserved_parking_space.occupied = True

    if not footprint_clear:
        # A slow crawl, never a hard 0 - update_car_physics refuses to
        # turn the vehicle at all below 0.05 m/s ("cars cannot steer in
        # place while stationary"), so a full stop here would deadlock:
        # the only way off an actually-overlapping pose is to keep
        # moving, and a genuine zero-speed floor can never move again on
        # its own (reported: NPC stuck oscillating in place forever).
        driver.target_speed_mps = min(driver.target_speed_mps, NPC_FOOTPRINT_VIOLATION_CRAWL_MPS)

    # collision-avoidance section 3/8: stuck/oscillation/spin detection - a single
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
    waiting_in_queue = (avoidance_blocked and lead is not None
                        and gap >= (lead_length_m + vehicle.length_m) * 0.5)
    if protest_cap is not None or pull_out_wait or waiting_for_light or crossing_decision is not None or waiting_in_queue or ((at_destination or finishing_approach) and footprint_clear) or driver.recovery_stage != "NORMAL":
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

    if driver.route_job_pending or driver.recovery_stage in ("STUCK", "HOLD"):
        driver.target_speed_mps = 0.0

    # State machine (section 10) - priority order is what a real driver
    # would report as "what am I doing right now".
    if not footprint_clear:
        vehicle.state = NPCState.PARKING if approaching_final_waypoint and abs(vehicle.car.speed) > 0.05 else NPCState.WAITING
        vehicle.debug_waiting_for = "footprint blocked (curb/building)"
    elif driver.recovery_stage in ("STUCK", "HOLD") or driver.route_job_pending:
        vehicle.state = NPCState.WAITING
        vehicle.debug_waiting_for = (
            "recovery failed - no validated route" if driver.recovery_stage == "HOLD"
            else "awaiting route job" if driver.route_job_pending else "stuck - awaiting recovery"
        )
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
    if at_destination and footprint_clear:
        steer_left = steer_right = 0.0
    else:
        target_x, target_y = target.x, target.y
        # Pure pursuit from the rear axle, the point the car turns about (physics.rear_axle_shift).
        behind = rear_axle_behind(vehicle.car)
        rear_x = vehicle.car.x - math.cos(vehicle.car.heading) * behind
        rear_y = vehicle.car.y - math.sin(vehicle.car.heading) * behind
        desired_heading = math.atan2(target_y - rear_y, target_x - rear_x)
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
    previous_pose = (vehicle.car.x, vehicle.car.y, vehicle.car.heading)
    speed_limit_mps = driver.target_speed_mps
    vehicle.curse_timer = max(0.0, vehicle.curse_timer - dt)
    if vehicle.shaken_timer > 0.0:  # shaken by a minor bump: slowly onward
        vehicle.shaken_timer = max(0.0, vehicle.shaken_timer - dt)
        speed_limit_mps = min(speed_limit_mps, SHAKEN_SPEED_MPS)
    update_car_physics(
        vehicle.car, throttle=1.0, brake=0.0, steer_left=steer_left, steer_right=steer_right, dt=dt,
        block_offroad=False, speed_limit_mps=speed_limit_mps,
        turning_circle=True,
    )
    _enforce_npc_road_motion(vehicle, driver, previous_pose, traffic_world, spatial_grid, manager, buildings, building_grid)
    if protests is not None and protests.blocks_movement(vehicle.car, previous_pose):
        vehicle.car.x, vehicle.car.y, vehicle.car.heading = previous_pose
        vehicle.car.speed = 0.0


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


NPC_BUILDING_YARD_REACH_M = 10.0  # a building's yard point lies at most this far outside its bbox


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
ROADSIDE_SHOULDER_MARGIN_M = 0.5
ROADSIDE_JUNCTION_CLEARANCE_M = 10.0


def _roadside_parking_point(
    x: float, y: float, ways: Optional[List[Way]], spatial_grid: Optional[SpatialWayGrid],
    arrive_from: Optional[Tuple[float, float]] = None,
) -> Optional[Tuple[float, float]]:
    """The kerb on the right for a vehicle arriving from `arrive_from` (§ 36:
    right-side parking, the game's policy) - without it, the right of the
    map way's own direction. See _roadside_spots."""
    spots = _roadside_spots(x, y, ways, spatial_grid)
    if spots is None:
        return None
    right, left, heading, oneway, _half_width = spots
    if oneway < 0:
        return left  # one-way against the way's direction: travel's right is the way's left
    if oneway == 0 and arrive_from is not None and (
            math.cos(heading) * (right[0] - arrive_from[0]) + math.sin(heading) * (right[1] - arrive_from[1])) < 0.0:
        return left  # arriving against the way's direction
    return right


ROADSIDE_KERB_RUN_M = 3.5  # a roadside spot's last straight run along the kerb


def _roadside_pull_in(route: list, destination: Tuple[float, float], ways, spatial_grid) -> list:
    """A roadside destination's route ending in a pull-in: along the
    right-hand lane until NPC_PARKING_APPROACH_DISTANCE_M before the spot,
    then over to the kerb - not one long diagonal to it, which crossed the
    oncoming lane or ran off the road edge long before the spot."""
    spots = _roadside_spots(*destination, ways, spatial_grid)
    if spots is None or len(route) < 2:
        return route
    right, left, heading, _, _half_width = spots
    lane = ((right[0] + left[0]) / 2.0, (right[1] + left[1]) / 2.0)  # on the centre line: the path builder offsets it into the lane
    travel = (math.cos(heading), math.sin(heading))  # the way's direction ... or against it, as the vehicle comes
    prev = route[-2]
    if travel[0] * (destination[0] - prev[0]) + travel[1] * (destination[1] - prev[1]) < 0.0:
        travel = (-travel[0], -travel[1])
    pull_in = (lane[0] - travel[0] * NPC_PARKING_APPROACH_DISTANCE_M, lane[1] - travel[1] * NPC_PARKING_APPROACH_DISTANCE_M)
    # Then along the kerb for the last metres: parked parallel to the edge (§ 36). Arriving
    # on the diagonal left it 20-30 degrees across, its rear in the lane (riders and cars hit it).
    kerb = (destination[0] - travel[0] * ROADSIDE_KERB_RUN_M, destination[1] - travel[1] * ROADSIDE_KERB_RUN_M)
    return list(route[:-1]) + [pull_in, kerb, tuple(destination)]


def _arrives_on_right(route: list, destination: Tuple[float, float]) -> bool:
    """Whether a roadside destination lies on the right of the route's last
    road leg (never parking against traffic, across the oncoming lane)."""
    points = [(p.x, p.y) if hasattr(p, "x") else (p[0], p[1]) for p in route]  # path points or (x, y)
    points = [p for p in points if math.hypot(p[0] - destination[0], p[1] - destination[1]) > 0.5]
    if len(points) < 2:
        return True
    (ax, ay), (bx, by) = points[-2], points[-1]
    dx, dy = bx - ax, by - ay
    if math.hypot(dx, dy) < 1e-6:
        return True
    return dy * (destination[0] - bx) - dx * (destination[1] - by) >= 0.0  # right of the travel direction


def _roadside_spots(
    x: float, y: float, ways: Optional[List[Way]], spatial_grid: Optional[SpatialWayGrid],
) -> Optional[Tuple[Tuple[float, float], Tuple[float, float], float, int]]:
    """NPC-more.md section 2 tier 5, the last resort: legal roadside
    parking on a quiet street - never a busy/arterial road or roundabout.
    Return a point beyond the carriageway edge, not the route node itself:
    a car left in the travel lane traps following traffic in recovery.
    Route and footprint validation reject this shoulder if a curb or
    building makes it inaccessible. Only used when better parking fails."""
    if ways is None:
        return None
    nearby_ways = list(spatial_grid.ways_in_rect(x - 20.0, y - 20.0, x + 20.0, y + 20.0)) if spatial_grid is not None else ways
    way, distance = _way_at_point(None, [w for w in nearby_ways if getattr(w, "is_drivable", True)], x, y)
    # A point on the shoulder itself (a car parked there, its home) is
    # beyond the carriageway: reach that far too, or it never finds its
    # way back to the road.
    shoulder = getattr(way, "half_width_m", 0.0) + NPC_VEHICLE_WIDTH_M * 0.5 + ROADSIDE_SHOULDER_MARGIN_M if way is not None else 0.0
    if way is None or distance > max(ROADSIDE_PARKING_MAX_ROAD_DISTANCE_M, shoulder + 0.5):
        return None
    if getattr(way, "is_roundabout", False) or not getattr(way, "is_drivable", True):
        return None
    if str(getattr(way, "highway", "") or "").lower() not in _LOW_TRAFFIC_HIGHWAY_TYPES:
        return None
    if len(way.points_m) < 2:
        return None
    (ax, ay), (bx, by) = min(
        zip(way.points_m, way.points_m[1:]),
        key=lambda segment: closest_point_and_dist_to_segment(x, y, *segment[0], *segment[1])[3],
    )
    _, _, t, _ = closest_point_and_dist_to_segment(x, y, ax, ay, bx, by)
    # Short map segments cannot fit a parking spot clear of both ends.
    segment_length = math.hypot(bx - ax, by - ay)
    if segment_length < 2.0 * ROADSIDE_JUNCTION_CLEARANCE_M:
        return None
    margin = ROADSIDE_JUNCTION_CLEARANCE_M / segment_length
    t = max(margin, min(1.0 - margin, t))
    cx, cy = ax + (bx - ax) * t, ay + (by - ay) * t
    heading = math.atan2(by - ay, bx - ax)
    offset = way.half_width_m + NPC_VEHICLE_WIDTH_M * 0.5 + ROADSIDE_SHOULDER_MARGIN_M
    right = (cx + math.sin(heading) * offset, cy - math.cos(heading) * offset)
    left = (cx - math.sin(heading) * offset, cy + math.cos(heading) * offset)
    return right, left, heading, int(getattr(way, "oneway", 0) or 0), way.half_width_m


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
    None. collision-avoidance section 4/5: identifies which parking area a vehicle is
    currently sitting in, purely by point-in-polygon against the map's own
    already-loaded lot outlines - no persistent parking-area id needed on
    ParkingSpace/Scenery, since this only ever runs at destination-search
    time (infrequent, never per-frame), not as a per-frame lookup."""
    if point is None or not sceneries:
        return None
    x, y = point
    for scenery in sceneries:
        if getattr(scenery, "kind", None) != "parking":
            continue
        points = getattr(scenery, "points_m", None)
        if not points or len(points) < 3:
            continue
        bbox = getattr(scenery, "bbox", None)  # every lot of the map is a candidate: most are far away
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0) and not (bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]):
            continue
        if point_in_polygon(x, y, points):
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
    deadline: Optional[float] = None,
    vehicle_length_m: float = NPC_VEHICLE_LENGTH_M,
    vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
) -> List[Tuple[Tuple[float, float], object]]:
    """Run parking selection synchronously, discarding incomplete searches on timeout."""
    return run_route_steps(_pick_npc_destination_candidates_steps(
        x, y, parking_spaces, sceneries, buildings, ways, spatial_grid,
        search_radius_m, limit, other_vehicle_positions, own_position,
        vehicle_length_m, vehicle_width_m,
    ), deadline=deadline) or []


def _pick_npc_destination_candidates_steps(
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
    vehicle_length_m: float = NPC_VEHICLE_LENGTH_M,
    vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
) -> RouteSteps:
    """Every acceptable place to stop near (x, y), in NPC-more.md section
    2's tier order (dedicated space > parking lot > building yard >
    roadside shoulder on a quiet street as an explicit last resort),
    nearest first within each tier. A carriageway/lane/roundabout is
    never a parking candidate.

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

    own_position (collision-avoidance section 4/5): the vehicle's own actual current
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
    if limit <= 0:
        return []
    yield
    radius_sq = search_radius_m * search_radius_m
    own_parking_area = _parking_area_containing(own_position, sceneries)

    # Each tier is only ever scanned if every higher tier came up empty
    # (section 20: no need to walk thousands of buildings when a parking
    # space already covers this point) - "retry the next-nearest option"
    # only matters *within* whichever single tier actually has anything.
    space_candidates = []
    for _idx, space, cx, cy in _parking_spaces_near(parking_spaces, x, y, search_radius_m):
        yield
        if getattr(space, "occupied", False) or getattr(space, "reserved", False):
            continue
        dist_sq = (cx - x) ** 2 + (cy - y) ** 2
        if dist_sq > radius_sq:
            continue
        if not _parking_space_fits_vehicle(space, vehicle_length_m, vehicle_width_m):
            continue
        if own_parking_area is not None and _parking_area_containing((cx, cy), [own_parking_area]) is not None:
            continue
        space_candidates.append((dist_sq, (cx, cy), space))

    if space_candidates:
        ordered = space_candidates
    else:
        lot_candidates = []
        for scenery in sceneries or ():
            yield
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
            reach_sq = (search_radius_m + NPC_BUILDING_YARD_REACH_M) ** 2
            for building in buildings or ():
                yield
                if bbox_distance_sq(getattr(building, "bbox", None), x, y) > reach_sq:
                    continue  # its yard can't be in range: skip the outline walk (a whole city of them, per pick)
                point = _building_yard_point(building, x, y)
                if point is None:
                    continue
                dist_sq = (point[0] - x) ** 2 + (point[1] - y) ** 2
                if dist_sq <= radius_sq and _point_is_clear_of_vehicles(point, other_vehicle_positions):
                    building_candidates.append((dist_sq, point, None))
            ordered = building_candidates

    ordered.sort(key=lambda c: c[0])
    if not ordered:
        roadside = _roadside_parking_point(x, y, ways, spatial_grid, arrive_from=own_position)
        if roadside is not None and _point_is_clear_of_vehicles(roadside, other_vehicle_positions):
            ordered = [(0.0, roadside, None)]

    candidates = []
    for _, point, space in ordered:
        yield
        if _parking_overlaps_walkway(
            *point, _resting_heading(*point, space, ways, spatial_grid), ways, spatial_grid,
            vehicle_length_m, vehicle_width_m,
        ):
            continue
        candidates.append((point, space))
        if len(candidates) >= limit:
            break
    return candidates


def _resting_heading(
    x: float, y: float, parking_space, ways: Optional[List[Way]], spatial_grid: Optional[SpatialWayGrid],
) -> float:
    """A reasonable heading for a vehicle sitting at rest at (x, y) - the
    parking space's own long axis (_parking_space_axis - an explicit
    orientation tag if one resolved to a real angle, otherwise the space
    polygon's own longest-edge axis, which the painted bay outline is drawn along), or
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
    nearby_ways = list(spatial_grid.ways_in_rect(x - 20.0, y - 20.0, x + 20.0, y + 20.0)) if spatial_grid is not None else ways or []
    way, distance = _way_at_point(None, [w for w in nearby_ways if getattr(w, "is_drivable", True)], x, y)
    if way is not None and distance < 20.0 and len(way.points_m) >= 2:
        closest_segment = min(
            zip(way.points_m, way.points_m[1:]),
            key=lambda segment: closest_point_and_dist_to_segment(x, y, *segment[0], *segment[1])[3],
        )
        (ax, ay), (bx, by) = closest_segment
        return math.atan2(by - ay, bx - ax)
    return 0.0


def _parking_overlaps_walkway(x, y, heading, ways, spatial_grid=None,
                             length_m=NPC_VEHICLE_LENGTH_M, width_m=NPC_VEHICLE_WIDTH_M):
    """Parking must leave the whole mapped pedestrian corridor unobstructed."""
    radius = math.hypot(length_m, width_m) * 0.5 + 10.0
    nearby = list(spatial_grid.ways_in_rect(x - radius, y - radius, x + radius, y + radius)) if spatial_grid is not None else ways or []
    road, _ = _way_at_point(None, [w for w in nearby if getattr(w, "is_drivable", True)
                                  and w.highway not in ("footway", "pedestrian", "path", "steps", "cycleway")], x, y)
    layer = getattr(road, "layer", 0)
    for way in nearby:
        if way.highway not in ("footway", "pedestrian", "path", "steps", "cycleway") or way.layer != layer:
            continue
        for a, b in zip(way.points_m, way.points_m[1:]):
            segment_length = math.hypot(b[0] - a[0], b[1] - a[1])
            if segment_length > 0.0 and boxes_intersect(
                x, y, heading, length_m, width_m,
                (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5,
                math.atan2(b[1] - a[1], b[0] - a[0]), segment_length, 2.0 * way.half_width_m,
            ):
                return True
    return False


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
    """vehicle-population sections 5, 20: place a vehicle already at rest at a valid
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
    # vehicle-population v2: vehicle_type is a vehicles/ plugin id - dimensions and
    # capacity are plugin data, not a branch here (falls back to "car" for
    # an unknown/unregistered id, the same defensive default spawn_npc's
    # own Car construction implicitly used before plugins existed).
    definition = vehicle_definition(vehicle_type)
    length_m, width_m = definition.length_m, definition.width_m
    if parking_space is not None and not _parking_space_fits_vehicle(parking_space, length_m, width_m):
        return None
    heading = _resting_heading(point[0], point[1], parking_space, ways, spatial_grid)
    if _parking_overlaps_walkway(*point, heading, ways, spatial_grid, length_m, width_m):
        return None
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
    (tried first, see autonomous-driving dev notes) routinely chose a node at the
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
    spawn autonomous-driving's one NPC there (section 12).

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
            # Every parking tier may be off the road; the raw point only
            # stays unchanged for a destination already on its road node.
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

    destination_query_point (vehicle-population section 12): a household vehicle
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
    plan = run_route_steps(_continue_npc_trip_steps(
        vehicle, traffic_world, ways, spatial_grid, parking_spaces, sceneries,
        buildings, curbs, curb_grid, building_grid, destination_query_point,
        other_vehicle_positions,
    ), time.perf_counter() + time_budget_s)
    if plan is None:
        return False
    _apply_npc_continuation(vehicle, driver, plan)
    return True


def _continue_npc_trip_steps(
    vehicle, traffic_world, ways, spatial_grid=None, parking_spaces=None,
    sceneries=None, buildings=None, curbs=None, curb_grid=None, building_grid=None,
    destination_query_point=None, other_vehicle_positions=None,
) -> RouteSteps:
    """Plan without changing occupants, reservations or the current route."""
    group = vehicle.trip_group
    if group is not None and (not group.all_aboard or vehicle.owner_id not in group.boarded_resident_ids):
        return None
    if destination_query_point is None:
        return (yield from _find_npc_trip_steps(
            vehicle, traffic_world, ways, spatial_grid, parking_spaces, sceneries,
            buildings, curbs, curb_grid, building_grid, other_vehicle_positions,
        ))
    origin = (vehicle.car.x, vehicle.car.y)
    for query_point in [destination_query_point]:
        yield
        destination_candidates = yield from _pick_npc_destination_candidates_steps(
            query_point[0], query_point[1], parking_spaces, sceneries, buildings,
            ways=ways, spatial_grid=spatial_grid, other_vehicle_positions=other_vehicle_positions,
            own_position=origin,
            vehicle_length_m=vehicle.length_m, vehicle_width_m=vehicle.width_m,
        )
        for destination, target_space in destination_candidates:
            # Unlike a road node, the query point (a household's home spot)
            # can itself be off the road: kept unchanged, it still needs the
            # parking leg, or the car stalls at the road edge beside home.
            destination_is_off_road = destination != query_point or not is_point_on_road(
                destination[0], destination[1], ways=ways, spatial_grid=spatial_grid, car_roads_only=True,
            )
            path = yield from _plan_and_validate_npc_route_steps(
                traffic_world, ways, origin, destination, spatial_grid=spatial_grid,
                curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
                parking_space=target_space, destination_is_off_road=destination_is_off_road,
                origin_is_off_road=True,
                vehicle_length_m=vehicle.length_m, vehicle_width_m=vehicle.width_m,
            )
            if path is None:
                continue
            return path, destination, target_space, destination_is_off_road
    return None


BUS_STOP_ROAD_SEARCH_M = 50.0  # the roads near a stop searched for the one it stands beside
BUS_BAY_PULL_IN_M = 20.0  # from its lane into the bay over this distance
BUS_BAY_STRAIGHT_M = 4.0  # ...then straight along the bay to its middle
BUS_BAY_KERB_SHARE = 0.65  # at this share of the pull-in it is beside the kerb: the step into the bay spread over the rest
# (turning about its rear axle, physics.rear_axle_shift, an 11 m bus cannot jog sideways in a couple of metres)
BUS_STOP_REACHED_M = 6.0  # a path segment this near the stop's lane point passes it (either lane of the road)
BUS_AT_BAY_M = 15.0  # this near the stop it last served, a bus leaves from its bay (_pull_out_of_bay)
BUS_STOP_OVERSHOOT_M = 30.0  # a path point this near a stop, past it, is a detour beyond it (_end_at_stop)


def _bus_leg_steps(vehicle, job, traffic_world, ways, spatial_grid, curbs, curb_grid,
                   buildings, building_grid) -> RouteSteps:
    """A line bus's route to its next stop: into the stop's bay, beside the
    road on the stop's side - an end point of its own, wherever the route's
    last road node lies (left to the planner, a route reaching a node past
    the stop and back put the bus in the opposite lane). A bus stops at its
    stop, it never parks (docs/bus-lines.md)."""
    from .static_world import BUS_BAY_DEPTH_M, bus_stop_point
    yield
    stop = job.target_stop
    r = BUS_STOP_ROAD_SEARCH_M
    near = spatial_grid.ways_in_rect(stop.x - r, stop.y - r, stop.x + r, stop.y + r) if spatial_grid is not None else ways
    road = bus_stop_point(stop, near)
    if road is None:
        return None
    (px, py), (nx, ny), way = road
    lane = _lane_offset_point(way, px, py, math.atan2(nx, -ny), vehicle.width_m)  # (travelling with the stop on its right)
    out = way.half_width_m + BUS_BAY_DEPTH_M * 0.5  # the middle of the bay (static_world.bus_stop_shapes)
    bay = (px + nx * out, py + ny * out)
    path = yield from _plan_and_validate_npc_route_steps(
        traffic_world, ways, (vehicle.car.x, vehicle.car.y), lane, spatial_grid=spatial_grid,
        curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
        origin_is_off_road=True,  # (as every continuation: it joins the road from where it stands)
        destination_is_off_road=True,  # the exact end point: no lane offset of the planner's own
        vehicle_length_m=vehicle.length_m, vehicle_width_m=vehicle.width_m,
        bus_route=job.line.key,  # along its OSM route's own streets, not just the shortest way
    )
    if path is None:
        return None
    # Validated to the lane beside the stop; the pull-in to the bay is ours:
    # the bay is drawn by the game, the map's roads (and the route checks) end at the kerb.
    direction = (-ny, nx)  # the way the bus travels
    if not _arrives_along(path, lane, direction):
        return None  # it would reach the stop from the far side, across the oncoming lane
    path = _end_at_stop(path, lane, direction)
    along = lambda q: (q.x - lane[0]) * direction[0] + (q.y - lane[1]) * direction[1]
    keep = [q for q in path[:-1] if along(q) < -BUS_BAY_PULL_IN_M or math.hypot(q.x - lane[0], q.y - lane[1]) > BUS_STOP_OVERSHOOT_M]
    # The pull-in: along its lane, eased to just inside the kerb (the body
    # still on the road until the driver's off-road access stretch near the
    # end), then into the bay and straight along it to the middle.
    kerb_side = way.half_width_m - vehicle.width_m * 0.5 - 0.2
    at = lambda along_m, out_m: dataclasses.replace(
        path[-1], x=px + direction[0] * along_m + nx * out_m, y=py + direction[1] * along_m + ny * out_m)
    lane_out = (lane[0] - px) * nx + (lane[1] - py) * ny
    path = keep + [at(-BUS_BAY_PULL_IN_M, lane_out), at(-BUS_BAY_PULL_IN_M * BUS_BAY_KERB_SHARE, kerb_side),
                   at(-BUS_BAY_STRAIGHT_M, out), at(0.0, out)]
    left = job.stopped_at
    if left is not None and math.hypot(vehicle.car.x - left.x, vehicle.car.y - left.y) < BUS_AT_BAY_M:
        r = BUS_STOP_ROAD_SEARCH_M
        path = _pull_out_of_bay(path, left, spatial_grid.ways_in_rect(left.x - r, left.y - r, left.x + r, left.y + r)
                                if spatial_grid is not None else ways, vehicle.width_m)
    return path, bay, None, True


def _pull_out_of_bay(path, stop, ways, vehicle_width_m) -> list:
    """Leaving a stop's bay as it came in, mirrored: straight along the bay,
    eased out to just inside the kerb, into its lane - not the planner's
    turn straight out from where it stands (an 11 m bus swung across the
    road). The path's own first stretch beside the stop gives way to it."""
    from .static_world import BUS_BAY_DEPTH_M, bus_stop_point
    road = bus_stop_point(stop, ways)
    if road is None or len(path) < 2:
        return path
    (px, py), (nx, ny), way = road
    direction = (-ny, nx)
    lane_out = min(max(1.2, way.half_width_m * 0.45), way.half_width_m - vehicle_width_m * 0.5)  # (_lane_offset_point's cruise lane)
    kerb_side = way.half_width_m - vehicle_width_m * 0.5 - 0.2
    out = way.half_width_m + BUS_BAY_DEPTH_M * 0.5
    at = lambda along_m, out_m: dataclasses.replace(
        path[1], x=px + direction[0] * along_m + nx * out_m, y=py + direction[1] * along_m + ny * out_m)
    along = lambda q: (q.x - px) * direction[0] + (q.y - py) * direction[1]
    rest = [q for q in path[1:] if along(q) > BUS_BAY_PULL_IN_M or math.hypot(q.x - px, q.y - py) > BUS_STOP_OVERSHOOT_M]
    return [path[0], at(BUS_BAY_STRAIGHT_M, out), at(BUS_BAY_PULL_IN_M * BUS_BAY_KERB_SHARE, kerb_side), at(BUS_BAY_PULL_IN_M, lane_out)] + rest


def _arrives_along(path, point, direction) -> bool:
    """The path first reaches `point` travelling along `direction`, not
    against it (a later pass, coming back from a node past it, is the
    detour _end_at_stop cuts)."""
    for a, b in zip(path, path[1:]):
        if dist_point_to_segment(*point, a.x, a.y, b.x, b.y) < BUS_STOP_REACHED_M:
            return (b.x - a.x) * direction[0] + (b.y - a.y) * direction[1] > 0.0
    return False


def _end_at_stop(path, point, direction) -> list:
    """The route searches to the road node nearest the stop, often just past
    it: the path drove on, crossed into the oncoming lane and came back.
    Cut it where it first reaches the stop (near it, at or past it along
    `direction`, the way the bus travels) and end it there."""
    for k, q in enumerate(path[:-1]):
        if k > 0 and math.hypot(q.x - point[0], q.y - point[1]) < BUS_STOP_OVERSHOOT_M \
                and (q.x - point[0]) * direction[0] + (q.y - point[1]) * direction[1] > -1.0:
            return path[:k] + [path[-1]]
    return path


def _recover_npc_trip_steps(vehicle, driver, traffic_world, ways, spatial_grid,
                            curbs, curb_grid, buildings, building_grid) -> RouteSteps:
    in_access = _npc_parking_access(vehicle, driver, vehicle.x, vehicle.y, ways, spatial_grid)
    path = yield from _plan_and_validate_npc_route_steps(
        traffic_world, ways, (vehicle.x, vehicle.y), driver.destination,
        spatial_grid=spatial_grid, curbs=curbs, curb_grid=curb_grid,
        buildings=buildings, building_grid=building_grid,
        parking_space=vehicle.reserved_parking_space, destination_is_off_road=True,
        vehicle_length_m=vehicle.length_m, vehicle_width_m=vehicle.width_m,
        preserve_origin=True,
        origin_is_off_road=in_access,
        origin_heading=vehicle.heading,
    )
    if path is None:
        return None
    return path, driver.destination, vehicle.reserved_parking_space, True


def _apply_npc_continuation(vehicle, driver, plan) -> None:
    vehicle.taxi_idle_until = 0.0
    path, destination, target_space, _ = plan
    driver.origin_is_off_road = vehicle.state == NPCState.PARKED and not is_point_on_road(
        vehicle.x, vehicle.y, ways=[way for way in (vehicle.way, path[0].way) if way is not None],
        car_roads_only=True,
    )
    driver.trip_origin = (vehicle.x, vehicle.y)
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
    driver.recovery_stage = "NORMAL"
    driver.destination_is_off_road = plan[3]
    if vehicle.trip_group is not None:
        vehicle.trip_group.activity_duration_s = random.uniform(
            NPC_BUILDING_VISIT_MIN_S, NPC_BUILDING_VISIT_MAX_S
        )
        vehicle.trip_group.activity_type = random.choice(NPC_TRIP_ACTIVITY_TYPES)
        vehicle.trip_group.destination_entrance = None
        vehicle.trip_group.wait_deadline_sim_time = None
        vehicle.trip_group.disembarked_resident_ids.clear()


class NPCVehicleManager:
    """vehicle-population: owns the whole NPC vehicle population - the same role
    pedestrian.PedestrianManager plays for pedestrians. Replaces
    main.py's old "spawn exactly one NPC, retry forever if it fails"
    logic with a real, persistent, gradually-filled population of
    parked/driving/household/traffic vehicles.

    Vehicles never disappear just because they're far from the player
    (section 18) - only a genuinely idle, currently-parked vehicle far
    beyond despawn_radius_m is ever removed (section 19: never mid-trip,
    never with passengers out), and even then it's replaced by fresh
    population fill elsewhere, not left permanently below target.
    Explicit cleanup exceptions: timed-out wrecks and repeatedly failed
    HOLD routes may be removed even in view and below the minimum count.
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
        motorcycle_season: Optional[MotorcycleSeason] = None,
    ) -> bool:
        self.vehicles: List[NPCVehicle] = []
        self.road_rage = RoadRageClearance()
        self.drivers: Dict[int, Driver] = {}
        self.accidents: List[Tuple[float, float]] = []  # crash positions for the sound, drained by the simulation
        self.curses: List[Tuple[float, float]] = []  # where a bumped NPC driver cursed; drained by the simulation
        self.taxi_bumps: List[int] = []  # competitor taxis the player bumped (taxi_brawls trigger); drained by the simulation
        self.bus_brakes: List[Tuple[float, float]] = []
        self.bicycle_bells: List[Tuple[float, float]] = []  # riders ringing at someone in their way (simulation.py plays them)
        self.household_manager = HouseholdManager()
        self.target_count = target_count
        self.min_count = min_count if min_count is not None else max(1, int(target_count * 0.6))
        self.competitor_taxis = COMPETITOR_TAXIS  # of the moving-traffic spawns (competitor_taxis.py)
        self._night_taxi_target = 0
        self._night_cruise_target = 0
        self.line_buses = bus_lines.LINE_BUSES  # of the moving-traffic spawns (bus_lines.py)
        self.bus_stops = ()  # the world's BusStops, set by the simulation each frame
        self._bus_lines_for = None  # (id, len) of the bus_stops the cached lines came from
        self._bus_lines = {}
        self.scenery_objects = ()  # the world's SceneryObjects, set by the simulation each frame
        self._racks_for = None  # (id, len) of the scenery_objects the cached racks came from
        self._thefts = {}  # vehicle_id -> [thief Pedestrian, seconds running]
        self._racks = []
        self.max_count = max_count if max_count is not None else max(self.min_count, int(target_count * 1.5))
        self.household_fraction = household_fraction
        # living-traffic: a *stable* target (target_count's own steady-state
        # size), not derived from the momentarily-fluctuating current
        # vehicle count - see _run_population_tick's trip-start step.
        self.target_moving_count = max(1, int(target_count * target_moving_fraction))
        # The city-wide figures; target_count/min_count/target_moving_count
        # follow the local building density (set_local_density).
        self.city_target_count, self.city_min_count = self.target_count, self.min_count
        self.target_moving_fraction = target_moving_fraction
        self._local_density_cell = None
        self._local_people = 0.0
        self._collision_buildings, self._collision_building_grid = None, None  # this update's, for collision pushes
        self._through_way, self._through_share = None, 0.0  # the player's road and its passing traffic's share of demand
        self.clock = None  # the game clock (a datetime), set by the simulation; None: demand ignores time
        self.motorcycle_season = motorcycle_season or MotorcycleSeason()
        self.motorcycle_factor = 0.0  # this game day's (motorcycle_season); 0 until the date is known
        self._motorcycle_day = None
        self.demand_rng = random.Random()  # seeded by tests
        self._demand_draw: Optional[float] = None
        self._demand_draw_tick = 0
        self.trip_start_probability = NPC_TRIP_START_PROBABILITY_PER_TICK
        self.spawn_radius_m = spawn_radius_m
        self.despawn_radius_m = despawn_radius_m
        self.simulation_radius_m = simulation_radius_m
        self._active_bounds = None
        self._trip_start_failures: Dict[int, int] = {}
        self._trip_retry_after_tick: Dict[int, int] = {}
        self._population_tick_number = 0
        self._route_jobs: List[dict] = []
        self._route_job_cursor = 0
        self._route_job_frame = 0
        self._existing_route_last_frame: Dict[int, int] = {}
        self.route_job_stats = {
            "queued": 0, "ready": 0, "failed": 0, "stale": 0, "discarded": 0,
            "max_frame_ms": 0.0, "waits_frames": collections.deque(maxlen=2000),
            "continued": 0, "recovered": 0, "safe_holds": 0,
        }
        self.population_diagnostics = {
            "trip_start_attempts": 0, "successful_trip_starts": 0,
            "route_generation_failures": 0, "route_validation_failures": 0,
            "vehicles_waiting_for_trips": 0, "population_update_duration_s": 0.0,
            "motorcycle_season_factor": 0.0, "motorcycles_spawned": 0, "motorcycles_retired_for_winter": 0,
        }
        self._previous_player_pose: Optional[Tuple[float, float, float]] = None
        self.include_experimental = include_experimental
        # vehicle-population v2 section 14: vehicle_type is picked from the registered
        # road-vehicle plugins' own traffic_weight, not a hardcoded "always
        # car" - a caller (main.py) may override with its own {id: weight}
        # (e.g. config's vehicle_distribution), defaulting to None here to
        # mean "use each plugin's own default weight". An explicit override
        # always wins - include_experimental only gates the *default*
        # distribution (e.g. motorcycle, off unless [experimental]
        # enable_two_wheelers is set - see _default_vehicle_distribution).
        self.snowy = False  # set by the simulation from the weather: more tractors out ploughing
        self.target_cycling_count = 0  # moving cyclists near the player (set_local_density)
        self.camping_sites: List[Tuple[float, float]] = []  # camping area centres (update(): from the sceneries)
        self._camping_from = (None, 0)
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
        # already indexes anything with .bbox or .x/.y) - available for spawn-time overlap checks.
        self.spatial_grid = SpatialWayGrid(cell_size=100.0)

    def _default_vehicle_distribution(self) -> Dict[str, float]:
        return {
            definition.id: definition.traffic_weight
            for definition in VEHICLE_DEFINITIONS.values()
            if definition.is_road_vehicle and (self.include_experimental or not definition.experimental)
        }

    def bus_lines(self) -> dict:
        """The loaded bus lines (bus_lines.lines), rebuilt when the stops change."""
        key = (id(self.bus_stops), len(self.bus_stops))
        if key != self._bus_lines_for:
            self._bus_lines_for, self._bus_lines = key, bus_lines.lines(self.bus_stops)
        return self._bus_lines

    def _retire_finished_line_buses(self, resident_manager, viewport_bounds) -> None:
        """A line bus at its terminus (no job left) is removed once out of
        sight: buses never turn round (an 11 m bus cannot U-turn on a city
        street); new ones join the lines near the player (bus_lines.py)."""
        for vehicle in [v for v in self.vehicles if is_line_bus(v) and v.bus_job is None and v.state == NPCState.PARKED]:
            if viewport_bounds is None or not _point_in_viewport(vehicle.x, vehicle.y, viewport_bounds):
                self._retire_trip(vehicle, resident_manager)
                self.vehicles.remove(vehicle)

    def _wants_line_bus(self) -> bool:
        return bool(self.bus_lines()) and sum(map(is_line_bus, self.vehicles)) < self.line_buses

    def _near_camping(self, at: Optional[Tuple[float, float]]) -> bool:
        return at is not None and any(
            (x - at[0]) ** 2 + (y - at[1]) ** 2 <= CAMPING_RADIUS_M ** 2 for x, y in self.camping_sites)

    def _note_camping_sites(self, sceneries) -> None:
        """The camping areas' centres, again only when the sceneries change
        (the streamed map appends to the same list)."""
        key = (id(sceneries), len(sceneries or ()))
        if key == self._camping_from:
            return
        self._camping_from = key
        self.camping_sites = [
            ((s.bbox[0] + s.bbox[2]) / 2, (s.bbox[1] + s.bbox[3]) / 2) for s in (sceneries or ())
            if getattr(s, "kind", None) in CAMPING_KINDS and getattr(s, "bbox", None)]

    def _pick_vehicle_type(self, at: Optional[Tuple[float, float]] = None) -> str:
        """Weighted choice among road-vehicle plugins with a positive
        weight (vehicle-population v2 section 14) - falls back to "car" if every
        weight is zero (e.g. an all-zero override) so population fill
        never silently stalls."""
        if (self.snowy and self.vehicle_distribution.get("tractor", 0.0) > 0.0
                and not any(v.vehicle_type == "tractor" and v.state != NPCState.CRASHED for v in self.vehicles)):
            return "tractor"
        ids = [vehicle_id for vehicle_id, weight in self.vehicle_distribution.items()
               if weight > 0.0 and vehicle_definition(vehicle_id).movement == "road"]  # cyclists: _top_up_cyclists
        camping = CAMPING_HOLIDAY_FACTOR if self._near_camping(at) else 1.0  # spawning by a camping area
        weights = [self.vehicle_distribution[vehicle_id] * (
                       NPC_SNOW_TRACTOR_FACTOR if self.snowy and vehicle_id == "tractor"
                       else (NPC_SNOW_HOLIDAY_FACTOR if self.snowy else 1.0) * camping if vehicle_id in HOLIDAY_VEHICLES
                       else self.motorcycle_factor if vehicle_id == "motorcycle" else 1.0)  # the riding season
                   for vehicle_id in ids]
        if not ids or not any(weights):
            return "car"
        picked = random.choices(ids, weights=weights, k=1)[0]
        if picked == "motorcycle":
            self.population_diagnostics["motorcycles_spawned"] += 1
        return picked

    def _update_motorcycle_season(self, resident_manager) -> None:
        """Once per game day: the riding season's factor; in the winter exclusion
        every motorcycle leaves the world (the ordinary retirement)."""
        day = self.clock.date() if self.clock is not None else None
        if day == self._motorcycle_day:
            return
        self._motorcycle_day = day
        self.motorcycle_factor = self.motorcycle_season.factor(day) if day is not None else 0.0
        self.population_diagnostics["motorcycle_season_factor"] = self.motorcycle_factor
        if day is not None and self.motorcycle_factor == 0.0:
            for vehicle in [v for v in self.vehicles if v.vehicle_type == "motorcycle"]:
                self.retire_vehicle(vehicle, resident_manager)
                self.population_diagnostics["motorcycles_retired_for_winter"] += 1

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
            # living-traffic: the *target*, not just the current count, so "roads
            # full of parked cars" is a diagnosable number. getattr-guarded:
            # population_counts() must stay safe against a manager built via
            # __new__ with only .vehicles set.
            "moving_target": getattr(self, "target_moving_count", 0),
            "road_rage": 0,
            "trip_start_attempts": getattr(self, "population_diagnostics", {}).get("trip_start_attempts", 0),
            "successful_trip_starts": getattr(self, "population_diagnostics", {}).get("successful_trip_starts", 0),
            "route_failures": getattr(self, "population_diagnostics", {}).get("route_generation_failures", 0),
            "waiting_for_trips": getattr(self, "population_diagnostics", {}).get("vehicles_waiting_for_trips", 0),
        }
        rage_held = getattr(getattr(self, "road_rage", None), "held", {})
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
            if vehicle.vehicle_id in rage_held:
                counts["road_rage"] += 1
        return counts

    def population_counts_by_type(self) -> Dict[str, int]:
        """vehicle-population v2 section 22's debug "vehicles by plugin type" line."""
        counts: Dict[str, int] = {}
        for vehicle in self.vehicles:
            counts[vehicle.vehicle_type] = counts.get(vehicle.vehicle_type, 0) + 1
        return counts

    def trigger_road_rage(self, sim_time: float) -> None:
        """Activate the explicit ten-second arcade road-clearance exception."""
        self.road_rage.activate(sim_time)

    def request_vehicle(
        self, household: Household, passengers: int = 1, purpose: Optional[str] = None,
    ) -> Optional[NPCVehicle]:
        """vehicle-population v2 section 10: the one generic entry point a future
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
        player_position: Optional[Tuple[float, float]] = None,
    ) -> Optional[NPCVehicle]:
        """Place one new parked vehicle - a thin wrapper around
        place_parked_npc that also rejects a spot too close to a vehicle
        already placed earlier in this same population batch (see
        NPC_MIN_VEHICLE_SPACING_M, also used by _pick_npc_destination_
        candidates for the same reason)."""
        claimed = [pos for _, pos in self._claimed_vehicle_points()]
        if not _point_is_clear_of_vehicles(point, claimed):
            return None
        kind = vehicle_type or self._pick_vehicle_type(point)
        if player_position is not None:
            definition = vehicle_definition(kind)
            # Bounding circles protect the taxi at any heading, including long NPC vehicles and door clearance.
            clearance = max(NPC_MIN_VEHICLE_SPACING_M,
                            math.hypot(definition.length_m, definition.width_m) * 0.5
                            + math.hypot(NPC_VEHICLE_LENGTH_M, NPC_VEHICLE_WIDTH_M) * 0.5 + 1.0)
            if not _point_is_clear_of_vehicles(point, [player_position], min_spacing_m=clearance):
                return None
        return place_parked_npc(
            self._next_id(), point, parking_space, ways=ways, spatial_grid=spatial_grid,
            curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
            vehicle_type=kind,
        )

    def _make_household(self, vehicle: NPCVehicle, resident_manager: ResidentManager) -> None:
        # vehicle-population v2 section 14: not every vehicle plugin is eligible for
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

    def set_local_density(self, player_x: float, player_y: float, building_grid, current_way=None) -> None:
        """Scale the population to the people the buildings within the spawn
        radius account for (NPC_FULL_TRAFFIC_PEOPLE: the city's whole
        target), and moving traffic to the traffic demand at the game clock
        (population.traffic_demand). People are recounted only when the
        player enters another NPC_LOCAL_TARGET_CELL_M cell.

        Moving traffic is an expectation, not a minimum: below one car the
        target is 1 for a share of the NPC_DEMAND_ROLL_TICKS periods, so a
        remote road at night stays empty for long stretches."""
        if building_grid is None:
            return
        highway = getattr(current_way, "highway", None)
        month = self.clock.month if self.clock is not None else None
        cell = (math.floor(player_x / NPC_LOCAL_TARGET_CELL_M), math.floor(player_y / NPC_LOCAL_TARGET_CELL_M), month)
        if cell != self._local_density_cell:
            self._local_density_cell = cell
            r = self.spawn_radius_m
            self._local_people = people_within(
                building_grid.ways_in_rect(player_x - r, player_y - r, player_x + r, player_y + r),
                player_x, player_y, r, month,
            )
        fraction = min(1.0, self._local_people / NPC_FULL_TRAFFIC_PEOPLE)
        demand = traffic_demand(fraction, highway, self.clock, current_way)  # a LAM station's own curves on its road
        self._through_way = current_way
        self._through_share = demand["through"] / max(1e-9, demand["local"], demand["through"])
        if self._demand_draw is None or self._population_tick_number >= self._demand_draw_tick + NPC_DEMAND_ROLL_TICKS:
            self._demand_draw = self.demand_rng.random()
            self._demand_draw_tick = self._population_tick_number
        expected_moving = self.city_target_count * self.target_moving_fraction * demand["demand"]
        self._night_taxi_target = night_taxi_target(self.clock, fraction, min(self.city_target_count, self.max_count)) if self.competitor_taxis > 0 else 0
        self._night_cruise_target = min(max(0, self.max_count - self._night_taxi_target), math.floor(
            self.city_target_count * self.target_moving_fraction * demand["nightlife"]))
        self.target_moving_count = math.floor(expected_moving) + (self._demand_draw < expected_moving % 1.0)
        winter = self.snowy or (month is not None and (month >= 11 or month <= 3))
        expected_cycling = expected_moving * CYCLING_SHARE * (CYCLING_WINTER_FACTOR if winter else 1.0)
        self.target_cycling_count = math.floor(expected_cycling) + (self._demand_draw < expected_cycling % 1.0)
        self.target_moving_count = min(self.max_count, self.target_moving_count + self._night_taxi_target)
        # Parked cars belong to the households around, whatever the hour;
        # passing traffic needs room on top of them.
        households = 1 if self._local_people > 0 else 0  # anyone living here has a car parked
        self.target_count = max(round(self.city_target_count * fraction), households, self.target_moving_count)
        # Cyclists ride on top of the car population: they never take a car's place.
        self.target_count += sum(1 for v in self.vehicles if vehicle_definition(v.vehicle_type).movement == "cycle")
        self.min_count = min(self.city_min_count, round(self.city_min_count * fraction))
        self.trip_start_probability = NPC_TRIP_START_PROBABILITY_PER_TICK * demand["hour"]
        self.population_diagnostics["traffic_demand"] = {
            **demand, "people": round(self._local_people), "highway": highway,
            "expected_moving": round(expected_moving, 3), "moving_target": self.target_moving_count,
            "night_taxi_target": self._night_taxi_target,
            "night_cruise_target": self._night_cruise_target,
        }

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
        self._note_camping_sites(sceneries)
        self.set_local_density(player_x, player_y, building_grid)
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
            if self._active_bounds is not None:
                from .viewport import in_bounds
                if not in_bounds(self._active_bounds, point[0], point[1]):
                    continue
            if (point[0] - player_x) ** 2 + (point[1] - player_y) ** 2 > (self.spawn_radius_m + NPC_SPAWN_RADIUS_SLACK_M) ** 2:
                # The nearest parking to a random query point can be far
                # away in a sparse area - a car spawned beyond the
                # simulation radius is inert and just gets despawned.
                continue
            vehicle = self._place_one(
                point, parking_space, ways, spatial_grid, curbs, curb_grid, buildings, building_grid,
                player_position=(player_x, player_y),
            )
            if vehicle is None:
                continue
            if random.random() < self.household_fraction:
                self._make_household(vehicle, resident_manager)
            self.vehicles.append(vehicle)
            if progress_callback is not None:
                progress_callback(len(self.vehicles) / self.target_count)
        self.rebuild_spatial_grid()

    def _retire_trip(self, vehicle: NPCVehicle, resident_manager: ResidentManager) -> None:
        """A trip is fully over (a household vehicle just arrived home, or
        - defensively - a vehicle with no group somehow still had a
        driver): release the driver and let it sit idle until the next
        population-tick roll (or a future Resident-trip reservation)
        sends it out again. Clear only this trip's occupancy links; persistent
        resident identities, households and vehicle ownership remain intact."""
        group = vehicle.trip_group
        member_ids = set(group.member_resident_ids) if group is not None else set()
        if vehicle.owner_id is not None:
            member_ids.add(vehicle.owner_id)
        for resident_id in member_ids:
            member = resident_manager.get(resident_id)
            if member is None or member.trip_group_id not in (None, group.group_id if group else None):
                continue  # a stale roster cannot unlink a resident's newer trip
            member.trip_group_id = None
            if member.active_vehicle_id in (None, vehicle.vehicle_id):
                member.active_vehicle_id = None
                member.mode = "household" if member.household_id is not None else "walking"
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
        """collision-avoidance section 9/10/11: pairwise oriented-box overlap test
        against `nearby_obstacles` (already spatially bounded by the
        caller - never all-to-all). `nearby_obstacles` may hold other
        `NPCVehicle`s and/or the player's own `Car` (same x/y/heading/
        length_m/width_m duck type either way, so one test handles both
        NPC-NPC and NPC-taxi). A CRASHED vehicle remains solid: another NPC
        hitting the wreck must stop and crash as well. Only a pair in which
        both vehicles are already crashed is skipped, preventing repeated
        accident/occupant processing without turning wrecks into ghosts."""
        vehicle_already_crashed = vehicle.state == NPCState.CRASHED
        own_trailer = vehicle.trailer_body()  # a towed trailer is a body of its own, hit like the vehicle
        for obstacle in nearby_obstacles:
            if obstacle is vehicle:
                continue
            body = obstacle  # what was hit; `obstacle` below: who responds (a trailer's vehicle)
            tow = getattr(obstacle, "tow", None)
            if tow is not None:
                if tow is vehicle:
                    continue  # its own trailer
                obstacle = tow
            other_car = getattr(obstacle, "car", obstacle)
            if (vehicle.layer != getattr(other_car, "layer", 0)
                    or vehicle.car.map_level != getattr(other_car, "map_level", 0)):
                continue  # Overlapping screen footprints on separate road/floor levels cannot collide.
            obstacle_is_npc = isinstance(obstacle, NPCVehicle)
            obstacle_already_crashed = obstacle_is_npc and obstacle.state == NPCState.CRASHED
            if vehicle_already_crashed and obstacle_already_crashed:
                continue  # the already-resolved wreck pair needs no response
            other_previous = (previous_obstacle_poses or {}).get(id(obstacle)) if body is obstacle else None
            body_length = getattr(body, "length_m", NPC_VEHICLE_LENGTH_M)
            body_width = getattr(body, "width_m", NPC_VEHICLE_WIDTH_M)
            hit = boxes_intersect(
                vehicle.x, vehicle.y, vehicle.heading, vehicle.length_m, vehicle.width_m,
                body.x, body.y, body.heading, body_length, body_width,
            ) or (own_trailer is not None and boxes_intersect(
                own_trailer.x, own_trailer.y, own_trailer.heading, own_trailer.length_m, own_trailer.width_m,
                body.x, body.y, body.heading, body_length, body_width,
            ))
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
            if (not obstacle_is_npc and other_previous is not None and boxes_intersect(
                    vehicle.x, vehicle.y, vehicle.heading, vehicle.length_m, vehicle.width_m,
                    other_previous[0], other_previous[1], other_previous[2], body_length, body_width)
                    and math.hypot(obstacle.x - vehicle.x, obstacle.y - vehicle.y)
                    >= math.hypot(other_previous[0] - vehicle.x, other_previous[1] - vehicle.y) - 1e-6):
                # The taxi was already in it and is not going deeper (as at buildings and
                # posts): let it. Restoring the pose every frame kept it stuck inside
                # a wreck for good (reported: stuck in a rival taxi on a bridge).
                continue
            velocity, other_velocity = collision_velocity(vehicle), collision_velocity(obstacle)
            closing_speed = math.hypot(velocity[0] - other_velocity[0], velocity[1] - other_velocity[1])
            # The contact's normal at the overlapping poses, before they are undone;
            # a swept-only hit (passed through within the frame): along the closing motion.
            contact = box_contact_normal(vehicle.x, vehicle.y, vehicle.heading, vehicle.length_m, vehicle.width_m,
                                         body.x, body.y, body.heading, body_length, body_width)
            normal = contact[0] if contact else None
            if normal is None:
                normal = ((velocity[0] - other_velocity[0]) / closing_speed, (velocity[1] - other_velocity[1]) / closing_speed) \
                    if closing_speed > 1e-6 else (math.cos(vehicle.heading), math.sin(vehicle.heading))

            # Resolve at the last known non-penetrating frame pose. Detection
            # without response merely marks an NPC crashed while the taxi
            # continues through it; keeping crashed vehicles collidable with
            # the player also prevents passage on following frames.
            if previous_vehicle_pose is not None:
                vehicle.car.x, vehicle.car.y, vehicle.car.heading = previous_vehicle_pose
            if other_previous is not None:
                if obstacle_is_npc:
                    obstacle.car.x, obstacle.car.y, obstacle.car.heading = other_previous
                else:
                    obstacle.x, obstacle.y, obstacle.heading = other_previous
                    # The taxi's pose is back where it was clear: that is its
                    # previous pose now. The undone (penetrating) one stored
                    # at this update's start would put it back into the wreck
                    # on the next hit - colliding every tick, stuck until it
                    # reversed far enough away.
                    self._previous_player_pose = other_previous
            # Still overlapping where they were (embedded, e.g. one spawned or shoved into the
            # other): push them apart along the contact, the lighter one further.
            embedded = box_contact_normal(vehicle.x, vehicle.y, vehicle.heading, vehicle.length_m, vehicle.width_m,
                                          body.x, body.y, body.heading, body_length, body_width)
            if embedded is not None and (obstacle_is_npc or hasattr(obstacle, "speed")):
                (ex, ey), depth = embedded
                mass, other_mass = collision_mass_kg(vehicle), collision_mass_kg(obstacle)
                share = (depth + 0.05) / (mass + other_mass)
                other_body = obstacle.car if obstacle_is_npc else obstacle
                for moved, sign, weight in ((vehicle.car, -1.0, other_mass), (other_body, 1.0, mass)):
                    x, y = moved.x + sign * ex * share * weight, moved.y + sign * ey * share * weight
                    if is_vehicle_pose_valid(x, y, moved.heading, buildings=self._collision_buildings,
                                             building_grid=self._collision_building_grid, length_m=moved.length_m,
                                             width_m=moved.width_m, clearance_m=0.05):  # never into a wall
                        moved.x, moved.y = x, y
                if not obstacle_is_npc:
                    self._previous_player_pose = (other_body.x, other_body.y, other_body.heading)
            # Momentum by mass, along the contact: a bicycle flies off a car, a bus barely moves.
            velocity, other_velocity = collision_impulse(velocity, other_velocity, normal, collision_mass_kg(vehicle),
                                                         collision_mass_kg(obstacle))
            apply_collision_velocity(vehicle, velocity)
            if obstacle_is_npc or hasattr(obstacle, "speed"):
                apply_collision_velocity(obstacle, other_velocity)

            if (not obstacle_is_npc and not vehicle_already_crashed
                    and closing_speed < MINOR_HIT_MPS):
                # A minor bump by the taxi: both stop apart, the NPC driver
                # curses and goes on slowly - no wreck.
                from .pedestrian import CURSE_SYMBOLS  # lazy: pedestrian imports npc
                if vehicle.state == NPCState.PARKED:
                    vehicle.knock_vx = vehicle.knock_vy = 0.0  # a nudge leaves a parked car in its bay (and its claim)
                vehicle.curse_timer = CURSE_S
                vehicle.curse_text = random.choice(CURSE_SYMBOLS)
                vehicle.shaken_timer = SHAKEN_S
                self.curses.append((vehicle.car.x, vehicle.car.y))
                from .taxi_brawls import PROVOKE_BUMP, provoke
                provoke(vehicle, PROVOKE_BUMP, sim_time)
                if is_competitor(vehicle) and len(self.taxi_bumps) < 8:
                    self.taxi_bumps.append(vehicle.vehicle_id)
                return True
            if obstacle_is_npc and not vehicle_already_crashed and obstacle.state != NPCState.CRASHED \
                    and closing_speed < NPC_SCRAPE_MPS:
                # Two NPCs touching at walking pace (a crawl past a parking car): both stop
                # apart and go on - a scrape, not a wreck blocking the road for minutes.
                for scraped in (vehicle, obstacle):
                    if scraped.state == NPCState.PARKED:
                        scraped.knock_vx = scraped.knock_vy = 0.0  # stays in its bay
                return True
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
        """collision-avoidance sections 10-19: stop the vehicle, sever its driver link
        permanently (driver_departed - checked by reserve_household_vehicle
        and the idle/ready-vehicle filters above so nothing ever resumes or
        reassigns this vehicle), and turn every Resident actually aboard at
        the moment of impact (driver and any passengers) into ordinary
        pedestrians who walk away from the wreck; only the driver calls for help.
        A vehicle with no active driver (e.g. rear-ended while genuinely
        idle-parked) still becomes a stopped obstacle, just without anyone
        to eject - nobody was aboard.

        living-traffic: this is also where a live trip_group gets resolved before
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
        vehicle.fallen = vehicle_definition(vehicle.vehicle_type).movement == "cycle"  # the bike lies on its side
        vehicle.driver_departed = True
        vehicle.debug_waiting_for = "accident"
        vehicle.crashed_timer = 0.0
        _set_turn_signal(vehicle, "hazard", 0.0)
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
            # collision-avoidance section 15: the same passenger-side offset
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

    def _handle_parked_vehicle(self, vehicle: NPCVehicle, resident_manager: ResidentManager,
                               sim_time: float = 0.0, pedestrian_mgr=None) -> None:
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
            self._retire_trip(vehicle, resident_manager)
            return
        if is_competitor(vehicle) and vehicle.taxi_job is not None:
            if vehicle.taxi_job.at_stop(sim_time):  # the passenger has left: free for the next fare
                vehicle.taxi_job = None
            return
        if is_competitor(vehicle):
            if vehicle.taxi_idle_until == 0.0:
                vehicle.taxi_idle_until = sim_time + CRUISE_DWELL_S
            return  # keep its driver aboard, whether waiting or about to cruise
        if vehicle.vehicle_kind == "night_cruise":
            if self._night_cruise_target > 0:
                return  # a cruising group stays aboard for its next budgeted trip
            vehicle.vehicle_kind = "traffic"
        if is_line_bus(vehicle):
            job = vehicle.bus_job
            previous_state = job.state if job is not None else None
            if job is not None and job.at_stop(sim_time, vehicle.x, vehicle.y):
                vehicle.bus_job = None  # the terminus: it waits there until retired out of sight
            if job is not None and previous_state != "stopped" and job.state == "stopped":
                self.bus_brakes.append((vehicle.x, vehicle.y))
                if pedestrian_mgr is not None:
                    pedestrian_mgr.exchange_bus_passengers(vehicle, job.stopped_at)
            return
        if vehicle.vehicle_kind == "household" and vehicle.returning_home:
            # Arrived home (section 12) - the trip is simply over, no
            # building-visit detour the way an ordinary errand stop gets;
            # the household's residents are already accounted for, they
            # don't need to "visit" their own home as a timed activity.
            self._retire_trip(vehicle, resident_manager)

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
        past: bool = False,
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
        if past and through_point is not None:  # passing traffic: on beyond the player, not parked before it
            reach += math.hypot(origin[0] - through_point[0], origin[1] - through_point[1])
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
            if past:
                ahead_x, ahead_y = through_point[0] - origin[0], through_point[1] - origin[1]
                beyond = [index for index in near
                          if (nodes[index][0] - through_point[0]) * ahead_x + (nodes[index][1] - through_point[1]) * ahead_y > 0.0]
                beyond_ids = set(beyond)
                near = beyond + [index for index in near if index not in beyond_ids]
        edges = traffic_world._route_edges
        other_positions = [pos for _, pos in claimed_points]
        for index in near:
            yield
            # Midway along an edge (not an intersection centre): roadside
            # shoulder parking when the off-road lot/space tiers fail
            # validation almost every time on real maps.
            neighbors = [n for n, length in edges.get(index, ()) if length >= 20.0]
            if not neighbors:
                continue
            other = nodes[random.choice(neighbors)]
            road_point = ((nodes[index][0] + other[0]) / 2.0, (nodes[index][1] + other[1]) / 2.0)
            destination = _roadside_parking_point(road_point[0], road_point[1], ways, spatial_grid,
                                                  arrive_from=(vehicle.car.x, vehicle.car.y))
            if destination is None:
                continue
            if not _point_is_clear_of_vehicles(destination, other_positions):
                continue
            raw_route = yield from traffic_world.plan_route_steps(
                (vehicle.car.x, vehicle.car.y), destination,
            )
            if raw_route is None or not _arrives_on_right(raw_route, destination):  # never park against traffic
                continue
            raw_route = _roadside_pull_in(raw_route, destination, ways, spatial_grid)
            # A* endpoint connectors can cross open ground. Check their whole
            # corridor before spawning, rather than stopping sideways in-lane.
            if not (yield from _route_stays_on_road_steps(
                _densify_path(raw_route), ways, spatial_grid,
                MAX_ROUTE_OFFROAD_TOLERANCE_M, NPC_PARKING_ACCESS_TOLERANCE_M, 1,
                None, 1,
            )):
                continue
            path = build_driving_path(
                raw_route, ways, spatial_grid=spatial_grid, skip_final_lane_offset=True,
                vehicle_width_m=vehicle.width_m,
            )
            yield
            if len(path) >= 2:
                return path, destination, None, True
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
            "world": traffic_world,
        })
        self.route_job_stats["queued"] += 1
        if kind in ("trip", "transit"):
            self.population_diagnostics["trip_start_attempts"] += 1

    def _enqueue_existing_route_job(self, kind, vehicle, steps, traffic_world) -> None:
        driver = self.drivers[vehicle.vehicle_id]
        group = vehicle.trip_group
        self._enqueue_route_job(kind, vehicle, steps, traffic_world)
        self._route_jobs[-1].update(
            driver=driver, group=group,
            occupants=None if group is None else (
                tuple(group.member_resident_ids), frozenset(group.boarded_resident_ids), vehicle.owner_id,
            ),
            origin=(vehicle.x, vehicle.y), destination=driver.destination,
            state=vehicle.state, reservation=vehicle.reserved_parking_space,
            reservation_state=None if vehicle.reserved_parking_space is None else (
                vehicle.reserved_parking_space.reserved, vehicle.reserved_parking_space.occupied,
                vehicle.reserved_parking_space.vehicle_id,
            ),
            returning_home=vehicle.returning_home,
        )
        self._existing_route_last_frame[vehicle.vehicle_id] = self._route_job_frame
        driver.route_job_pending = True

    def _existing_route_job_valid(self, job) -> bool:
        from .viewport import in_bounds
        vehicle, driver = job["vehicle"], job["driver"]
        group = vehicle.trip_group
        return (
            vehicle in self.vehicles and self.drivers.get(vehicle.vehicle_id) is driver
            and (self._active_bounds is None or in_bounds(self._active_bounds, vehicle.x, vehicle.y))
            and group is job["group"] and vehicle.state == job["state"]
            and driver.destination == job["destination"]
            and vehicle.reserved_parking_space is job["reservation"]
            and (vehicle.reserved_parking_space is None or (
                (vehicle.reserved_parking_space.reserved, vehicle.reserved_parking_space.occupied,
                 vehicle.reserved_parking_space.vehicle_id) == job["reservation_state"]
            ))
            and vehicle.returning_home == job["returning_home"]
            and math.hypot(vehicle.x - job["origin"][0], vehicle.y - job["origin"][1]) < 0.5
            and (group is None or (
                (tuple(group.member_resident_ids), frozenset(group.boarded_resident_ids), vehicle.owner_id)
                == job["occupants"] and group.all_aboard
                and vehicle.owner_id in group.boarded_resident_ids
            ))
        )

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
            ) or (
                "driver" in job and not self._existing_route_job_valid(job)
            ):
                job["steps"].close()
                if "driver" in job:
                    job["driver"].route_job_pending = False
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
        if job["kind"] == "cycle":
            self._finish_cycle_job(job, result, player_x, player_y, viewport_bounds, resident_manager)
            return
        claimed_points = self._claimed_vehicle_points()
        if "driver" in job:
            valid = self._existing_route_job_valid(job)
            vehicle, driver = job["vehicle"], job["driver"]
            driver.route_job_pending = False
            if not valid:
                stats["discarded"] += 1
                return
            if job["kind"] == "recovery" and result is not None:
                if driver.recovery_route_attempts >= NPC_RECOVERY_MAX_WITHOUT_PROGRESS:
                    result = None  # another valid-looking path is not evidence of physical progress
            if result is None:
                stats["failed"] += 1
                if is_competitor(vehicle) and vehicle.taxi_job is not None and job["kind"] == "continue":
                    if vehicle.taxi_job.route_failed():
                        vehicle.taxi_job = None  # no way there: the fare is lost
                if is_line_bus(vehicle) and vehicle.bus_job is not None and job["kind"] in ("continue", "unhold"):
                    if vehicle.bus_job.route_failed():  # (no way to the rest of the line either)
                        vehicle.bus_job = None
                if job["kind"] == "unhold":  # no new destination from here either: hold longer
                    driver.hold_failures += 1
                    driver.hold_retry_tick = self._population_tick_number + NPC_HOLD_RETRY_TICKS * (driver.hold_failures + 1)
                if job["kind"] == "recovery":
                    driver.hold_retry_tick = self._population_tick_number + NPC_HOLD_RETRY_TICKS
                    # A failed search is not evidence that reversing is safe.
                    driver.recovery_stage = "HOLD"
                    vehicle.state = NPCState.WAITING
                    vehicle.debug_waiting_for = ("recovery exhausted - no driving progress"
                                                 if driver.recovery_route_attempts >= NPC_RECOVERY_MAX_WITHOUT_PROGRESS
                                                 else "recovery failed - no validated route")
                    stats["safe_holds"] += 1
                return
            space = result[2]
            if (
                (space is not None and space is not vehicle.reserved_parking_space and (
                    getattr(space, "reserved", False) or getattr(space, "occupied", False)
                ))
                or not _point_is_clear_of_vehicles(
                    result[1], [pos for vid, pos in claimed_points if vid != vehicle.vehicle_id],
                )
            ):
                stats["discarded"] += 1
                return
            if job["kind"] == "recovery":
                if driver.recovery_anchor is None:
                    driver.recovery_anchor = (vehicle.x, vehicle.y)
                driver.recovery_route_attempts += 1
                path = result[0]
                driver.path = path
                driver.path_index = 1
                driver.route_segment_index = 0
                driver.route_segment_t = 0.0
                driver.steering_input = 0.0
                driver.current_way = path[0].way
                driver.recovery_stage = "NORMAL"
                vehicle.travel_route = [(p.x, p.y) for p in path]
                vehicle.state = NPCState.CRUISING
                vehicle.debug_waiting_for = ""
                stats["recovered"] += 1
            else:
                _apply_npc_continuation(vehicle, driver, result)
                if job["kind"] == "unhold" and driver.recovery_route_attempts >= NPC_RECOVERY_MAX_WITHOUT_PROGRESS:
                    driver.hold_failures += 1  # reset only after this new route actually moves the vehicle
                else:
                    driver.hold_failures = 0
                if vehicle.vehicle_kind == "household":
                    vehicle.returning_home = job["kind"] in ("continue", "unhold")
                if is_competitor(vehicle) and vehicle.taxi_job is not None and job["kind"] == "continue":
                    vehicle.taxi_job.departing()
                if is_line_bus(vehicle) and vehicle.bus_job is not None and job["kind"] in ("continue", "unhold"):
                    vehicle.bus_job.departing()
                stats["continued"] += 1
            stats["ready"] += 1
            return
        if job["kind"] == "transit":
            if result is None:
                stats["failed"] += 1
                self.population_diagnostics["route_generation_failures"] += 1
                return
            vehicle, _plan = result
            if self._active_bounds is not None:
                from .viewport import in_bounds
                if not in_bounds(self._active_bounds, vehicle.x, vehicle.y):
                    release_npc_parking_reservation(vehicle)
                    stats["discarded"] += 1
                    self._count_discard("left_area")
                    return
            initial_speed = _transit_initial_speed(vehicle, _plan)
            clearance = _transit_clearance(vehicle, initial_speed or 0.0)
            distance_sq = (vehicle.x - player_x) ** 2 + (vehicle.y - player_y) ** 2
            victim = self._replaceable_parked_vehicle(player_x, player_y, viewport_bounds)
            if victim is not None and len(self.vehicles) < self.target_count:
                far = (victim.x - player_x) ** 2 + (victim.y - player_y) ** 2 > self.despawn_radius_m ** 2
                if not far:
                    victim = None
            reason = (
                "no_speed" if initial_speed is None
                else "near_taxi" if initial_speed > 0 and distance_sq < clearance ** 2
                else "full" if len(self.vehicles) >= self.target_count and victim is None
                else "far" if self._active_bounds is None and distance_sq > self.simulation_radius_m ** 2
                else "in_view" if viewport_bounds is not None and _point_in_viewport(
                    vehicle.x, vehicle.y, viewport_bounds, margin_m=NPC_PARKING_ACCESS_TOLERANCE_M)
                else "crowded" if not _point_is_clear_of_vehicles(
                    (vehicle.x, vehicle.y), [(other.x, other.y) for other in self.vehicles], clearance)
                else "controls" if initial_speed > 0 and job.get("world") is not None and (
                    job["world"]._nearby_traffic_lights(vehicle.x, vehicle.y, radius_m=clearance)
                    or job["world"].nearby_signs(vehicle.x, vehicle.y))
                # A line bus may share its stop: buses queue there like at any stop.
                else "destination_taken" if result[1][2] is None and vehicle.vehicle_kind != "bus_line" and not _point_is_clear_of_vehicles(
                    result[1][1], [pos for _, pos in claimed_points])
                else ""
            )
            if reason:
                release_npc_parking_reservation(vehicle)
                stats["discarded"] += 1
                self._count_discard(reason)
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
            or (parking_space is None and not _point_is_clear_of_vehicles(
                result[1], [pos for vid, pos in claimed_points if vid != vehicle.vehicle_id]
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
        """living-traffic: create a moving vehicle on a real road node near (but
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

    def _apply_transit_spawn(self, result, resident_manager: ResidentManager, claimed_points) -> Optional[Driver]:
        vehicle, plan = result
        speed = _transit_initial_speed(vehicle, plan)
        if speed is None:
            release_npc_parking_reservation(vehicle)
            return None
        taxis = sum(is_competitor(v) and v.state != NPCState.CRASHED for v in self.vehicles)
        cruisers = sum(v.vehicle_kind == "night_cruise" and v.state != NPCState.CRASHED for v in self.vehicles)
        if (vehicle.vehicle_type in ("car", "van") and taxis < max(self.competitor_taxis, self._night_taxi_target)
                and (self._night_cruise_target == 0 or taxis <= cruisers)):
            make_competitor(vehicle)
        elif vehicle.vehicle_type == "car" and cruisers < self._night_cruise_target:
            vehicle.vehicle_kind = "night_cruise"
        driver = _apply_npc_trip(vehicle, resident_manager, plan)
        if speed > 0:
            vehicle.car.speed = speed  # parked-trip setup deliberately reset it to zero
            driver.target_speed_mps = speed
        self.vehicles.append(vehicle)
        self.drivers[vehicle.vehicle_id] = driver
        if vehicle.destination is not None:
            claimed_points.append((vehicle.vehicle_id, vehicle.destination))
        return driver

    def _count_discard(self, reason: str) -> None:
        """Why planned moving traffic was dropped (route_job_stats, F12 JSON)."""
        reasons = self.route_job_stats.setdefault("discard_reasons", {})
        reasons[reason] = reasons.get(reason, 0) + 1

    def _transit_spawn_steps(
        self,
        focus_x: float,
        focus_y: float,
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
        preferred_heading: Optional[float] = None,
        player_position: Optional[Tuple[float, float]] = None,
    ) -> RouteSteps:
        """_spawn_transit_vehicle's search as a resumable job: returns
        (placed vehicle, plan) - the vehicle is not yet in self.vehicles -
        or None."""
        player_x, player_y = player_position or (focus_x, focus_y)
        cell_size = _ROUTE_NODE_GRID_CELL_M
        nodes = traffic_world._route_nodes
        grid = traffic_world._route_node_grid
        low_x = math.floor((focus_x - NPC_TRANSIT_SPAWN_MAX_DISTANCE_M) / cell_size)
        high_x = math.floor((focus_x + NPC_TRANSIT_SPAWN_MAX_DISTANCE_M) / cell_size)
        low_y = math.floor((focus_y - NPC_TRANSIT_SPAWN_MAX_DISTANCE_M) / cell_size)
        high_y = math.floor((focus_y + NPC_TRANSIT_SPAWN_MAX_DISTANCE_M) / cell_size)
        if self._active_bounds is not None:
            low_x, low_y = math.floor(self._active_bounds[0] / cell_size), math.floor(self._active_bounds[1] / cell_size)
            high_x, high_y = math.floor(self._active_bounds[2] / cell_size), math.floor(self._active_bounds[3] / cell_size)
        min_sq = NPC_TRANSIT_SPAWN_MIN_DISTANCE_M ** 2
        max_sq = NPC_TRANSIT_SPAWN_MAX_DISTANCE_M ** 2
        from .viewport import in_bounds
        ring = []
        for cell_x in range(low_x, high_x + 1):
            for cell_y in range(low_y, high_y + 1):
                yield  # a wide/panned view still respects the route-job frame budget
                for index in grid.get((cell_x, cell_y), ()):
                    distance_sq = (nodes[index][0] - focus_x) ** 2 + (nodes[index][1] - focus_y) ** 2
                    # A zoomed-in view's active band can be narrower than the old
                    # 110m ring; the viewport rejection below prevents visible spawns.
                    if ((self._active_bounds is None and min_sq <= distance_sq <= max_sq)
                            or (self._active_bounds is not None
                                and in_bounds(self._active_bounds, *nodes[index]))):
                        ring.append(index)
        random.shuffle(ring)
        ring = prioritize_transit_spawn_nodes(nodes, ring, focus_x, focus_y, preferred_heading)
        through_roll = self._through_share > 0.0 and random.random() < self._through_share
        if through_roll:
            ring = through_road_first(nodes, grid, ring, self._through_way, spatial_grid, player_x, player_y,
                                      max(NPC_TRANSIT_SPAWN_MAX_DISTANCE_M, self.simulation_radius_m - 20.0))
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
            line_job = bus_lines.start_job(self.bus_lines(), *point) if self._wants_line_bus() else None
            vehicle = self._place_one(point, None, ways, spatial_grid, curbs, curb_grid, buildings, building_grid,
                                      vehicle_type="bus" if line_job is not None else None,
                                      player_position=(player_x, player_y))
            if vehicle is None:
                continue
            tries += 1
            if line_job is not None:  # a line bus: straight to the line's nearest stop (bus_lines.py)
                vehicle.vehicle_kind, vehicle.bus_job = "bus_line", line_job
                plan = yield from _bus_leg_steps(vehicle, line_job, traffic_world, ways, spatial_grid,
                                                 curbs, curb_grid, buildings, building_grid)
            else:
                plan = yield from self._short_transit_trip_steps(
                    vehicle, point, resident_manager, traffic_world, ways, spatial_grid,
                    parking_spaces, sceneries, buildings, curbs, curb_grid, building_grid,
                    claimed_points, through_point=(player_x, player_y), past=through_roll,
                )
            if plan is not None:
                start, aim = plan[0][:2]
                heading = math.atan2(aim.y - start.y, aim.x - start.x)
                if not _npc_body_on_road(
                    start.x, start.y, heading, vehicle.length_m, vehicle.width_m, ways,
                    spatial_grid, getattr(start.way, "layer", 0),
                    getattr(start.way, "map_level", None) or 0,
                ) or not is_vehicle_pose_valid(
                    start.x, start.y, heading, length_m=vehicle.length_m, width_m=vehicle.width_m,
                    curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
                ):
                    release_npc_parking_reservation(vehicle)
                    if tries >= NPC_TRANSIT_SPAWN_NODE_TRIES:
                        break
                    continue
                vehicle.car.x, vehicle.car.y, vehicle.car.heading = start.x, start.y, heading
                speed = _transit_initial_speed(vehicle, plan)
                freeway = getattr(start.way, "highway", None) in ("motorway", "motorway_link", "trunk", "trunk_link")
                if speed and not freeway:  # near the player: slower, so its stopping distance fits the gap
                    gap = math.hypot(vehicle.x - player_x, vehicle.y - player_y) - vehicle.length_m - 1.0
                    speed = min(speed, math.sqrt(2.0 * ARRIVAL_DECEL_MPS2 * max(0.0, gap)) * 0.5)
                clearance = _transit_clearance(vehicle, speed or 0.0)
                if speed is None or (speed > 0 and (
                    math.hypot(vehicle.x - player_x, vehicle.y - player_y) < (
                        clearance if freeway else speed * speed / (2 * ARRIVAL_DECEL_MPS2) + vehicle.length_m)
                    or any(True for _ in self.nearby_vehicles_at(vehicle.x, vehicle.y, clearance))
                    # town streets: lights and signs everywhere - a car already driving brakes for them as usual
                    or freeway and traffic_world._nearby_traffic_lights(vehicle.x, vehicle.y, radius_m=clearance)
                    or freeway and traffic_world.nearby_signs(vehicle.x, vehicle.y)
                )):
                    release_npc_parking_reservation(vehicle)
                    if tries >= NPC_TRANSIT_SPAWN_NODE_TRIES:
                        break
                    continue
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
        transit_focus: Optional[Tuple[float, float]] = None,
        transit_heading: Optional[float] = None,
        current_way=None,
    ) -> None:
        population_tick_started = time.perf_counter()
        population_deadline = population_tick_started + NPC_TRIP_START_TICK_BUDGET_S
        self.set_local_density(player_x, player_y, building_grid, current_way=current_way)
        self._population_tick_number += 1
        # 1. Despawn only genuinely idle, currently-parked vehicles beyond
        # despawn_radius_m (section 19) - never mid-trip, never with a
        # driver/passengers. Also never a vehicle the player could
        # currently see (pedestrian.py's PedestrianManager uses the same
        # viewport check) - despawn_radius_m normally already guarantees
        # this, but a heavily zoomed-out viewport can exceed it (reported:
        # "cars spawn/despawn in viewport"). Repeated routing failures
        # are the explicit jam-cleanup exception below.
        despawn_radius_sq = self.despawn_radius_m * self.despawn_radius_m
        kept = []
        remaining = len(self.vehicles)
        for vehicle in self.vehicles:
            far = (vehicle.x - player_x) ** 2 + (vehicle.y - player_y) ** 2 > despawn_radius_sq
            # collision-avoidance section 18: a CRASHED vehicle is also despawn-eligible
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
                and (vehicle.state not in (NPCState.PARKED, NPCState.CRASHED) or is_competitor(vehicle))
                and self.drivers.get(vehicle.vehicle_id) is not None
            )  # (a competitor waits parked with its driver aboard: released when far all the same)
            held_driver = self.drivers.get(vehicle.vehicle_id)
            given_up = (getattr(held_driver, "recovery_stage", None) == "HOLD"
                        and held_driver.hold_failures >= NPC_HOLD_GIVE_UP_ATTEMPTS)
            if given_up or (far_moving and not visible and remaining > self.min_count):
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
                self._trip_start_failures.pop(vehicle.vehicle_id, None)
                self._trip_retry_after_tick.pop(vehicle.vehicle_id, None)
                remaining -= 1
                continue
            if vehicle.state == NPCState.CRASHED and vehicle.crashed_timer >= NPC_CRASH_CLEAR_S:
                release_npc_parking_reservation(vehicle)
                self.drivers.pop(vehicle.vehicle_id, None)
                remaining -= 1
                continue
            if idle_parked and not visible and far and remaining > self.min_count:
                release_npc_parking_reservation(vehicle)
                self.drivers.pop(vehicle.vehicle_id, None)
                self._trip_start_failures.pop(vehicle.vehicle_id, None)
                self._trip_retry_after_tick.pop(vehicle.vehicle_id, None)
                remaining -= 1
                continue
            kept.append(vehicle)
        # In place, not self.vehicles = kept: callers (the simulation's
        # npcs = npc_manager.vehicles) hold a reference
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
            and time.perf_counter() < population_deadline
        ):
            attempts += 1
            angle = random.uniform(0.0, 2.0 * math.pi)
            radius = random.uniform(0.0, self.spawn_radius_m)
            qx = player_x + math.cos(angle) * radius
            qy = player_y + math.sin(angle) * radius
            candidates = _pick_npc_destination_candidates(
                qx, qy, parking_spaces, sceneries, buildings, ways=ways, spatial_grid=spatial_grid,
                limit=1, deadline=population_deadline,
            )
            if not candidates:
                continue
            point, parking_space = candidates[0]
            if self._active_bounds is not None:
                from .viewport import in_bounds
                if not in_bounds(self._active_bounds, point[0], point[1]):
                    continue
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
                player_position=(player_x, player_y),
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

        # Async jobs can have claimed the same unreserved roadside spot before
        # either finished; free an already-waiting car before starting more trips.
        vehicles_by_id = {vehicle.vehicle_id: vehicle for vehicle in self.vehicles}
        for vehicle in self.vehicles:
            driver = self.drivers.get(vehicle.vehicle_id)
            if (vehicle.vehicle_id in self.road_rage.held or driver is None
                    or vehicle.state != NPCState.WAITING or vehicle.destination is None
                    or vehicle.reserved_parking_space is not None):
                continue
            taken = not _point_is_clear_of_vehicles(vehicle.destination, [
                pos for vid, pos in claimed_points
                if vid != vehicle.vehicle_id and vid in vehicles_by_id
                and (vehicles_by_id[vid].state == NPCState.PARKED or vid < vehicle.vehicle_id)
            ])
            if not taken:
                continue
            if any(job["vehicle"] is vehicle for job in self._route_jobs):
                continue
            if len(self._route_jobs) >= NPC_MAX_ROUTE_JOBS:
                break
            self._enqueue_existing_route_job("reroute", vehicle, _continue_npc_trip_steps(
                vehicle, traffic_world, ways, spatial_grid=spatial_grid,
                parking_spaces=parking_spaces, sceneries=sceneries, buildings=buildings,
                curbs=curbs, curb_grid=curb_grid, building_grid=building_grid,
                other_vehicle_positions=[pos for vid, pos in claimed_points if vid != vehicle.vehicle_id],
            ), traffic_world)
            break  # at most one reroute per tick

        # 3. Roll idle parked vehicles for "start a new trip now" (section
        # 9's parked/driving mixture), bounded to
        # NPC_TRIP_START_ATTEMPTS_PER_TICK actual attempts regardless of
        # how many roll true - find_and_start_npc_trip's own search cost
        # varies a lot against real map data (see its own docstring), so
        # capping *attempts*, not just candidates, is what actually bounds
        # this tick's worst case.
        trip_starts_this_tick = 0
        # living-traffic: moving traffic is a first-class target, independent of
        # total population - "driving" here matches population_counts()'s
        # own definition (state != PARKED) for consistency with the debug
        # panel's numbers.
        # Only vehicles inside simulation_radius_m count: update() never
        # ticks anything farther out, so a far "driving" car is not traffic
        # the player can ever meet (and used to satisfy the target while
        # nothing near the player moved).
        simulation_radius_sq = self.simulation_radius_m * self.simulation_radius_m

        def _near_player(vehicle: NPCVehicle) -> bool:
            if self._active_bounds is not None:
                from .viewport import in_bounds
                return in_bounds(self._active_bounds, vehicle.x, vehicle.y)
            return (vehicle.x - player_x) ** 2 + (vehicle.y - player_y) ** 2 <= simulation_radius_sq

        currently_moving = sum(
            1 for vehicle in self.vehicles
            if vehicle.state not in (NPCState.PARKED, NPCState.CRASHED) and _near_player(vehicle)
            and vehicle_definition(vehicle.vehicle_type).movement == "road"  # cyclists: their own target
        )
        self._top_up_cyclists(player_x, player_y, traffic_world, resident_manager, spatial_grid, viewport_bounds, _near_player)
        below_moving_target = currently_moving < self.target_moving_count
        nearby_taxis = sum(1 for v in self.vehicles if is_competitor(v) and v.state != NPCState.CRASHED and _near_player(v))
        below_taxi_target = nearby_taxis < self._night_taxi_target
        nearby_cruisers = sum(1 for v in self.vehicles if v.vehicle_kind == "night_cruise"
                              and v.state != NPCState.CRASHED and _near_player(v))
        below_cruise_target = nearby_cruisers < self._night_cruise_target
        trip_start_attempt_cap = (
            NPC_TRIP_START_ATTEMPTS_PER_TICK_WHEN_BELOW_MOVING_TARGET
            if below_moving_target or below_taxi_target or below_cruise_target
            else NPC_TRIP_START_ATTEMPTS_PER_TICK
        )
        idle_candidates = [
            vehicle for vehicle in self.vehicles
            if vehicle.state == NPCState.PARKED
            and vehicle.vehicle_id not in self.road_rage.held
            and self.drivers.get(vehicle.vehicle_id) is None
            # Section 7: a RESERVED vehicle (e.g. reserve_household_vehicle,
            # for a future Resident-initiated trip) must not be grabbed by
            # this unrelated "start a random trip" roll.
            and vehicle.availability == NPCAvailability.AVAILABLE
            # collision-avoidance section 12: state != PARKED already excludes a CRASHED
            # vehicle, but this makes the "never resumes" invariant explicit
            # rather than incidental.
            and not vehicle.driver_departed
            # Short on nearby traffic: pulling out a car the player will
            # never simulate/see is wasted (and expensive) route search.
            and (not below_moving_target or _near_player(vehicle))
            and self._trip_retry_after_tick.get(vehicle.vehicle_id, 0) <= self._population_tick_number
        ]
        self.population_diagnostics["vehicles_waiting_for_trips"] = len(idle_candidates)
        if below_moving_target or below_taxi_target or below_cruise_target:
            transit_x, transit_y = transit_focus or (player_x, player_y)
            transit_spawns = sum(1 for job in self._route_jobs if job["kind"] == "transit")
            while (
                trip_starts_this_tick < trip_start_attempt_cap
                and transit_spawns < NPC_TRANSIT_SPAWNS_PER_TICK
                and (currently_moving + transit_spawns < self.target_moving_count
                     or nearby_taxis + transit_spawns < self._night_taxi_target
                     or nearby_cruisers + transit_spawns < self._night_cruise_target)
                and len(self._route_jobs) < NPC_MAX_ROUTE_JOBS // 2
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
                    transit_x, transit_y, resident_manager, traffic_world, ways, spatial_grid,
                    parking_spaces, sceneries, buildings, curbs, curb_grid, building_grid,
                    viewport_bounds, list(claimed_points), preferred_heading=transit_heading,
                    player_position=(player_x, player_y),
                ), traffic_world)
        random.shuffle(idle_candidates)
        # living-traffic occupancy invariant: a household's members are shared
        # across its (up to NPC_MAX_VEHICLES_PER_HOUSEHOLD) vehicles, so a
        # member already riding in one must never also be folded into a
        # trip starting on another. Use membership in a live trip group,
        # not occupancy links: a member visiting a building still belongs
        # to the unfinished journey even while outside its vehicle.
        # The reliable "currently mid-trip" signal is membership in some
        # vehicle's still-live trip_group (None once that vehicle's trip
        # actually retires) - collected once per tick, not per household.
        currently_busy_resident_ids = {
            resident_id
            for other_vehicle in self.vehicles
            if other_vehicle.trip_group is not None
            for resident_id in other_vehicle.trip_group.member_resident_ids
        }
        for vehicle in idle_candidates:
            if self._active_bounds is not None and not _near_player(vehicle):
                continue
            if trip_starts_this_tick >= trip_start_attempt_cap or len(self._route_jobs) >= NPC_MAX_ROUTE_JOBS // 2:
                break
            if any(job["vehicle"] is vehicle for job in self._route_jobs):
                continue
            # Below the moving target the random roll is skipped: it only
            # exists to pace an already-satisfied population, and at 8% per
            # candidate it left the player alone on the road.
            if not below_moving_target and random.random() >= self.trip_start_probability:
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

        # Existing trips use reserved job slots; fresh population work cannot
        # fill the queue before a ready passenger group or stuck car is served.
        ready = [
            vehicle for vehicle in self.vehicles
            if vehicle.state == NPCState.PARKED
            and vehicle.vehicle_id not in self.road_rage.held
            and vehicle.brawl_id is None
            and vehicle.trip_group is not None and vehicle.trip_group.all_aboard
            and self.drivers.get(vehicle.vehicle_id) is not None
            and not (vehicle.vehicle_kind == "household" and vehicle.returning_home)
            # Free rivals cruise during the nightlife peak, after a short dispatch stop.
            and (not is_competitor(vehicle) or (vehicle.taxi_job is not None and vehicle.taxi_job.state == "await_departure")
                 or (vehicle.taxi_job is None and self._night_taxi_target > 0 and vehicle.taxi_idle_until > 0
                     and traffic_world.sim_time >= vehicle.taxi_idle_until))
            and (not is_line_bus(vehicle) or (vehicle.bus_job is not None and vehicle.bus_job.state == "await_departure"))
            and not any(job["vehicle"] is vehicle for job in self._route_jobs)
        ]
        self._existing_route_last_frame = {
            vid: frame for vid, frame in self._existing_route_last_frame.items() if vid in vehicles_by_id
        }
        def last_served(vehicle):
            return self._existing_route_last_frame.get(vehicle.vehicle_id, -1)

        ready.sort(key=last_served)
        stuck = [
            vehicle for vehicle in self.vehicles
            if getattr(self.drivers.get(vehicle.vehicle_id), "recovery_stage", None) == "STUCK"
            and vehicle.vehicle_id not in self.road_rage.held and vehicle.brawl_id is None
            and abs(vehicle.car.speed) < 0.05
            and not any(job["vehicle"] is vehicle for job in self._route_jobs)
        ]
        stuck.sort(key=last_served)
        held = [
            vehicle for vehicle in self.vehicles
            if getattr(driver := self.drivers.get(vehicle.vehicle_id), "recovery_stage", None) == "HOLD"
            and vehicle.vehicle_id not in self.road_rage.held and vehicle.brawl_id is None
            and driver.hold_failures < NPC_HOLD_GIVE_UP_ATTEMPTS
            and driver.hold_retry_tick <= self._population_tick_number
            and not any(job["vehicle"] is vehicle for job in self._route_jobs)
        ]
        held.sort(key=last_served)
        existing = (
            [("continue", vehicle) for vehicle in ready[:NPC_CONTINUE_TRIP_ATTEMPTS_PER_TICK]]
            + [("recovery", vehicle) for vehicle in stuck[:NPC_RECOVERY_ATTEMPTS_PER_TICK]]
            + [("unhold", vehicle) for vehicle in held[:NPC_RECOVERY_ATTEMPTS_PER_TICK]]
        )
        existing.sort(key=lambda item: last_served(item[1]))
        for kind, vehicle in existing:
            if self._active_bounds is not None and not _near_player(vehicle):
                continue
            if len(self._route_jobs) >= NPC_MAX_ROUTE_JOBS:
                break
            if kind in ("continue", "unhold") and is_line_bus(vehicle) and vehicle.bus_job is not None:
                steps = _bus_leg_steps(vehicle, vehicle.bus_job, traffic_world, ways, spatial_grid,
                                       curbs, curb_grid, buildings, building_grid)
            elif kind in ("continue", "unhold"):  # (unhold: a held car, a new destination from where it stands)
                query = (vehicle.home_position if vehicle.vehicle_kind == "household"
                         else vehicle.taxi_job.target if is_competitor(vehicle) and vehicle.taxi_job is not None else None)
                if vehicle.vehicle_kind == "night_cruise":
                    # Local laps, not a city-wide errand search that ties up route slots.
                    angle = random.uniform(-math.pi, math.pi)
                    query = (vehicle.x + math.cos(angle) * 150.0, vehicle.y + math.sin(angle) * 150.0)
                steps = _continue_npc_trip_steps(
                    vehicle, traffic_world, ways, spatial_grid, parking_spaces, sceneries,
                    buildings, curbs, curb_grid, building_grid,
                    query,
                    [pos for vid, pos in claimed_points if vid != vehicle.vehicle_id],
                )
            else:
                vehicle.state = NPCState.WAITING
                steps = _recover_npc_trip_steps(
                    vehicle, self.drivers[vehicle.vehicle_id], traffic_world, ways,
                    spatial_grid, curbs, curb_grid, buildings, building_grid,
                )
            self._enqueue_existing_route_job(kind, vehicle, steps, traffic_world)

        self.rebuild_spatial_grid()
        self.population_diagnostics["population_update_duration_s"] = time.perf_counter() - population_tick_started

    # --- cyclists (cycling.py) ------------------------------------------------

    def _top_up_cyclists(self, player_x, player_y, traffic_world, resident_manager, spatial_grid, viewport_bounds,
                         near_player) -> None:
        """Population tick: queue a cyclist spawn job while fewer cyclists
        ride near the player than target_cycling_count, and retire bikes
        whose rider has arrived once nobody sees them."""
        from .viewport import in_bounds
        cyclists = [v for v in self.vehicles if vehicle_definition(v.vehicle_type).movement == "cycle"]
        for vehicle in cyclists:
            if vehicle.state == NPCState.PARKED and (
                    viewport_bounds is None or not in_bounds(viewport_bounds, vehicle.x, vehicle.y, 2.0)):
                self.retire_vehicle(vehicle, resident_manager)
        riding = sum(1 for v in cyclists if v.state not in (NPCState.PARKED, NPCState.CRASHED) and near_player(v))
        queued = sum(1 for job in self._route_jobs if job["kind"] == "cycle" and job["vehicle"] is None)
        if (riding + queued >= self.target_cycling_count or queued >= CYCLIST_SPAWN_JOBS
                or len(self._route_jobs) >= NPC_MAX_ROUTE_JOBS // 2 or not traffic_world.cycle_graph.nodes):
            return
        definition = vehicle_definition("bicycle")
        to_rack = None
        if viewport_bounds is not None and random.random() < cycling.RACK_TRIP_SHARE:
            taken = {}
            for d in self.drivers.values():
                if d.rack_claim is not None:
                    taken[d.rack_claim[0]] = taken.get(d.rack_claim[0], 0) + 1
            seen = [r for r in self.bicycle_racks() if in_bounds(viewport_bounds, r.x, r.y, cycling.RACK_VIEW_MARGIN_M)
                    and taken.get(cycling.rack_key(r), 0) < len(cycling.RACK_HOOPS_M)]
            to_rack = random.choice(seen) if seen else None
        self._enqueue_route_job("cycle", None, cycling.cycle_spawn_steps(
            traffic_world.cycle_graph, (player_x, player_y), self._active_bounds, viewport_bounds,
            lambda point: any(True for _ in self.nearby_vehicles_at(point[0], point[1], cycling.CYCLIST_SPAWN_CLEARANCE_M)),
            spatial_grid, definition.width_m, racks=self.bicycle_racks(), to_rack=to_rack,
        ), traffic_world)

    def bicycle_racks(self) -> list:
        """The world's bicycle_parking objects, refiltered only when the scenery list changes."""
        key = (id(self.scenery_objects), len(self.scenery_objects))
        if key != self._racks_for:
            self._racks_for = key
            self._racks = [obj for obj in self.scenery_objects if getattr(obj, "kind", None) == "bicycle_parking"]
        return self._racks

    def _claim_rack_slot(self, driver, rack) -> None:
        """Claim a free hoop of `rack` for `driver`; none when every hoop has a bike."""
        taken = {d.rack_claim for d in self.drivers.values() if d.rack_claim is not None}
        key = cycling.rack_key(rack)
        for index, slot in enumerate(cycling.rack_slots(rack)):
            if (key, index) not in taken:
                driver.rack_slot, driver.rack_claim = slot, (key, index)
                return

    def _update_bike_thefts(self, dt, pedestrian_mgr, viewport_bounds, traffic_world, spatial_grid, rng=random) -> None:
        """Now and then a thief runs to a bike parked in a rack in view and rides it away."""
        if pedestrian_mgr is None or viewport_bounds is None or not hasattr(pedestrian_mgr, "spawn_pedestrian_at"):
            return
        from .viewport import in_bounds
        for vehicle_id, theft in list(self._thefts.items()):
            thief = theft[0]
            theft[1] += dt
            vehicle = next((v for v in self.vehicles if v.vehicle_id == vehicle_id), None)
            driver = self.drivers.get(vehicle_id)
            if (vehicle is None or driver is None or vehicle.state != NPCState.PARKED or theft[1] > cycling.THIEF_GIVE_UP_S
                    or thief not in pedestrian_mgr.pedestrians):
                thief.thief_target = None  # the bike is gone, or the run took too long: an ordinary walker again
                del self._thefts[vehicle_id]
            elif math.hypot(thief.x - vehicle.x, thief.y - vehicle.y) <= cycling.THIEF_REACH_M:
                thief.state = "despawning"  # on the bike now
                del self._thefts[vehicle_id]
                self._ride_stolen_bike(vehicle, driver, traffic_world, spatial_grid)
        if self._thefts or rng.random() >= cycling.BIKE_THEFT_PER_S * dt:
            return
        racked = [v for v in self.vehicles if v.state == NPCState.PARKED and in_bounds(viewport_bounds, v.x, v.y)
                  and getattr(self.drivers.get(v.vehicle_id), "rack_claim", None) is not None]
        if not racked:
            return
        bike = rng.choice(racked)
        for _ in range(4):  # a walkable spot a little way off
            angle, distance = rng.uniform(0.0, 2.0 * math.pi), rng.uniform(*cycling.THIEF_START_M)
            thief = pedestrian_mgr.spawn_pedestrian_at(bike.x + math.cos(angle) * distance, bike.y + math.sin(angle) * distance)
            if thief is not None and pedestrian_mgr.add_pedestrian(thief):
                thief.speed = thief.base_speed = cycling.THIEF_RUN_MPS
                thief.route = None
                thief.thief_target = (bike.x, bike.y)
                self._thefts[bike.vehicle_id] = [thief, 0.0]
                return

    def _ride_stolen_bike(self, vehicle, driver, traffic_world, spatial_grid) -> None:
        """The thief rides off: out of the hoop onto a new trip, fast."""
        driver.rack_slot = driver.rack_claim = None
        driver.stolen = vehicle.stolen = True
        vehicle.state = NPCState.CRUISING
        nearest = self._nearest_cycle_node(traffic_world, (vehicle.x, vehicle.y))
        if nearest is None:
            vehicle.state = NPCState.PARKED
            return
        graph = traffic_world.cycle_graph
        low, high = cycling.THIEF_GETAWAY_M
        far = [graph.nodes[i][:2] for cell in cycling._graph_nodes_in(
            graph, (vehicle.x - high, vehicle.y - high, vehicle.x + high, vehicle.y + high)) for i in cell
            if low <= math.hypot(graph.nodes[i][0] - vehicle.x, graph.nodes[i][1] - vehicle.y) <= high]
        driver.route_job_pending = True
        self._enqueue_route_job("cycle", vehicle, cycling.cycle_trip_steps(
            graph, nearest, spatial_grid, vehicle.width_m, destination=random.choice(far) if far else None), traffic_world)

    @staticmethod
    def _walk_bike_to_rack(vehicle, driver, dt) -> None:
        """The rider, off the bike, walks it in front of its hoop, then straight
        in (never across the bikes already in the next hoops); parked there."""
        x, y, heading = driver.rack_slot
        car = vehicle.car
        nx, ny = math.cos(heading), math.sin(heading)
        along = (car.x - x) * nx + (car.y - y) * ny
        if along > 0.0:  # in from whichever end the rider is at
            nx, ny, along = -nx, -ny, -along
        if math.hypot(car.x - x - along * nx, car.y - y - along * ny) > 0.05:  # not yet lined up
            x, y = x - nx * vehicle.car.length_m, y - ny * vehicle.car.length_m
        dx, dy = x - car.x, y - car.y
        distance = math.hypot(dx, dy)
        step = cycling.RACK_WALK_MPS * dt
        if distance <= step:
            car.x, car.y = x, y
            if (x, y) == driver.rack_slot[:2]:
                car.heading, car.speed = heading, 0.0
                vehicle.state = NPCState.PARKED
            return
        car.x += dx / distance * step
        car.y += dy / distance * step
        car.heading = math.atan2(dy, dx)
        car.speed = cycling.RACK_WALK_MPS

    def _finish_cycle_job(self, job, route, player_x, player_y, viewport_bounds, resident_manager) -> None:
        """A cycle job's plan: a new cyclist, or a stuck one's new trip."""
        from .viewport import in_bounds
        stats = self.route_job_stats
        vehicle = job["vehicle"]
        if route is None:
            stats["failed"] += 1
            if vehicle is not None:
                driver = self.drivers.get(vehicle.vehicle_id)
                if driver is not None:
                    driver.route_job_pending = False
            return
        if vehicle is not None:  # a replan (update(): "stuck")
            driver = self.drivers.get(vehicle.vehicle_id)
            if driver is None or vehicle not in self.vehicles:
                stats["discarded"] += 1
                return
            driver.route_job_pending = False
            if driver.stolen:  # a getaway
                route.cruise_mps = min(route.cruise_mps * cycling.THIEF_CRUISE_FACTOR, cycling.THIEF_MAX_CRUISE_MPS)
                driver.target_speed_mps = route.cruise_mps
            driver.cycle, driver.path_index, driver.destination = route, 1, route.points[-1]
            vehicle.destination = route.points[-1]
            stats["recovered"] += 1
            return
        start = route.points[0]
        if ((self._active_bounds is not None and not in_bounds(self._active_bounds, *start))
                or (viewport_bounds is not None and in_bounds(viewport_bounds, start[0], start[1], 3.0))
                or any(True for _ in self.nearby_vehicles_at(start[0], start[1], cycling.CYCLIST_SPAWN_CLEARANCE_M))
                or math.hypot(start[0] - player_x, start[1] - player_y) < 15.0):
            stats["discarded"] += 1
            self._count_discard("cyclist_spawn_unsafe")
            return
        definition = vehicle_definition("bicycle")
        heading = math.atan2(route.points[1][1] - start[1], route.points[1][0] - start[0])
        vehicle = NPCVehicle(
            vehicle_id=self._next_id(),
            car=Car(x=start[0], y=start[1], heading=heading, speed=0.0, length_m=definition.length_m,
                    width_m=definition.width_m),
            state=NPCState.CRUISING, vehicle_type="bicycle", color=random.choice(NPC_VEHICLE_COLORS),
            capacity=definition.capacity,
        )
        path = [PathPoint(x, y, way) for (x, y), way in zip(route.points, route.ways + route.ways[-1:])]
        driver = _begin_trip_on_vehicle(vehicle, path, resident_manager, route.points[-1])
        driver.cycle = route
        vehicle.car.layer = getattr(route.ways[0], "layer", 0)
        vehicle.car.speed = driver.target_speed_mps = route.cruise_mps * 0.8  # rides in from out of view
        self.vehicles.append(vehicle)
        self.drivers[vehicle.vehicle_id] = driver
        stats["ready"] += 1

    def _update_cyclist(self, vehicle, driver, dt, traffic_world, resident_manager, nearby_obstacles,
                        pedestrians, spatial_grid, viewport_bounds) -> None:
        if vehicle.state == NPCState.PARKED:
            return  # arrived, the rider off it: retired once out of view (_top_up_cyclists)
        if driver.rack_slot is not None:
            self._walk_bike_to_rack(vehicle, driver, dt)
            return
        if driver.route_job_pending:
            vehicle.car.speed = 0.0
            return
        event = cycling.update_cyclist(vehicle, driver, dt, traffic_world, nearby_obstacles, pedestrians)
        driver.bell_cooldown_s = max(0.0, getattr(driver, "bell_cooldown_s", 0.0) - dt)
        if driver.bell_cooldown_s <= 0.0 and getattr(driver.decision, "reason", "") in cycling.BELL_REASONS:
            self.bicycle_bells.append((vehicle.x, vehicle.y))  # sound only: the ride's decision is unchanged
            driver.bell_cooldown_s = cycling.BELL_COOLDOWN_S
        end = driver.cycle.points[-1]
        if (event is None and driver.cycle.rack is not None and abs(vehicle.car.speed) < 0.3
                and math.hypot(end[0] - vehicle.x, end[1] - vehicle.y) <= cycling.RACK_DISMOUNT_M):
            event = "arrived"  # held up by whoever stands at the end: off the bike, the rest on foot
        if event == "arrived":
            vehicle.debug_waiting_for = ""
            if driver.cycle.rack is not None:
                self._claim_rack_slot(driver, driver.cycle.rack)
            if driver.rack_slot is None:
                vehicle.state = NPCState.PARKED  # no rack, or a full one: where the ride ended
        elif event == "stuck":
            from .viewport import in_bounds
            # Game cleanup (guide: jam cleanup after failed recovery): a new
            # destination from here twice, then the cyclist goes.
            if driver.replans >= 2 or viewport_bounds is None or not in_bounds(viewport_bounds, vehicle.x, vehicle.y, 2.0):
                self.retire_vehicle(vehicle, resident_manager)
                return
            route = driver.cycle
            node = min(range(driver.path_index, len(route.points)),
                       key=lambda i: math.hypot(route.points[i][0] - vehicle.x, route.points[i][1] - vehicle.y))
            nearest = self._nearest_cycle_node(traffic_world, route.points[node])
            if nearest is None:
                self.retire_vehicle(vehicle, resident_manager)
                return
            driver.replans += 1
            driver.route_job_pending = True
            self._enqueue_route_job("cycle", vehicle, cycling.cycle_trip_steps(
                traffic_world.cycle_graph, nearest, spatial_grid, vehicle.width_m, racks=self.bicycle_racks()), traffic_world)

    @staticmethod
    def _pedestrian_lookup(pedestrian_mgr, active):
        """Walkers near a point, from a 10 m grid built once per tick - only
        when a cyclist is being simulated (cars use their own checks)."""
        if pedestrian_mgr is None or not any(v.vehicle_type == "bicycle" for v in active):
            return lambda x, y: ()
        grid: dict = {}
        for ped in pedestrian_mgr.pedestrians:
            if getattr(ped, "state", None) in ("in_vehicle", "in_building"):
                continue
            grid.setdefault((math.floor(ped.x / 10.0), math.floor(ped.y / 10.0)), []).append(ped)

        def near(x, y):
            cx, cy = math.floor(x / 10.0), math.floor(y / 10.0)
            return [p for dx in (-1, 0, 1) for dy in (-1, 0, 1) for p in grid.get((cx + dx, cy + dy), ())]
        return near

    @staticmethod
    def _nearest_cycle_node(traffic_world, point):
        graph = traffic_world.cycle_graph
        found = [graph.nodes[i] for cell in cycling._graph_nodes_in(graph, (point[0] - 30, point[1] - 30, point[0] + 30, point[1] + 30))
                 for i in cell]
        if not found:
            return None
        node = min(found, key=lambda n: (n[0] - point[0]) ** 2 + (n[1] - point[1]) ** 2)
        return (node[0], node[1])

    def discard_outside(self, bounds, residents, pedestrian_mgr, protected_resident_ids=()):
        """Retire whole unseen ambient groups, including their queued work."""
        from .viewport import in_bounds

        protected = set(protected_resident_ids)
        linked = {}
        for ped in pedestrian_mgr.pedestrians:
            for key in {ped.linked_vehicle_id, ped.current_vehicle_id, ped.reserved_vehicle_id} - {None}:
                linked.setdefault(key, []).append(ped)
        dropped = set()
        for vehicle in self.vehicles:
            people = linked.get(id(vehicle), [])
            group = vehicle.trip_group
            members = set(group.member_resident_ids) if group is not None else set()
            radius = math.hypot(vehicle.length_m, vehicle.width_m) * 0.5
            if (in_bounds(bounds, vehicle.x, vehicle.y, radius) or members & protected
                    or any(in_bounds(bounds, p.x, p.y, p.radius_m) or p.resident_id in protected
                           or getattr(p, "held_by", None) is not None for p in people)):
                continue
            dropped.add(id(vehicle))
            self._release_vehicle_links(vehicle, residents)
        self._drop_vehicles(dropped)

    def _release_vehicle_links(self, vehicle, residents) -> None:
        """Everything that ties a retiring vehicle to residents, households,
        parking and the manager's bookkeeping (the residents stay)."""
        group = vehicle.trip_group
        members = set(group.member_resident_ids) if group is not None else set()
        household = self.household_manager.get(vehicle.household_id)
        if household is not None:
            household.vehicle_ids.discard(vehicle.vehicle_id)
        owners = members | (household.member_resident_ids if household is not None else set())
        owners.add(vehicle.owner_id)
        for resident_id in owners:
            resident = residents.get(resident_id)
            if resident is not None:
                resident.vehicle_ids.discard(vehicle.vehicle_id)
                if group is not None and resident.trip_group_id == group.group_id:
                    resident.trip_group_id = None
                if resident.active_vehicle_id in (vehicle.vehicle_id, id(vehicle)):
                    resident.active_vehicle_id = None
        vehicle.trip_group = None
        release_npc_parking_reservation(vehicle)
        self.drivers.pop(vehicle.vehicle_id, None)
        self.road_rage.held.pop(vehicle.vehicle_id, None)
        self._trip_start_failures.pop(vehicle.vehicle_id, None)
        self._trip_retry_after_tick.pop(vehicle.vehicle_id, None)
        self._existing_route_last_frame.pop(vehicle.vehicle_id, None)

    def retire_vehicle(self, vehicle, residents) -> None:
        """Remove one vehicle through the same cleanup as discard_outside."""
        self._release_vehicle_links(vehicle, residents)
        self._drop_vehicles({id(vehicle)})

    def _drop_vehicles(self, dropped) -> None:
        if not dropped:
            return
        self.vehicles[:] = [v for v in self.vehicles if id(v) not in dropped]
        kept_jobs = []
        for job in self._route_jobs:
            if id(job["vehicle"]) not in dropped:
                kept_jobs.append(job)
                continue
            job["steps"].close()
            if "driver" in job:
                job["driver"].route_job_pending = False
            self.route_job_stats["discarded"] += 1
        self._route_jobs[:] = kept_jobs

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
        current_way=None,
        active_bounds=None,
    ) -> None:
        self._active_bounds = active_bounds
        self._update_motorcycle_season(resident_manager)
        self._note_camping_sites(sceneries)
        self._retire_finished_line_buses(resident_manager, viewport_bounds)
        # collision-avoidance: nearby_vehicles_at (avoidance/collision) reads
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
        self._update_bike_thefts(dt, pedestrian_mgr, viewport_bounds, traffic_world, spatial_grid)
        if player_car is not None:
            self.road_rage.update(self, player_car, traffic_world.sim_time, ways, spatial_grid, current_way)
        from .viewport import in_bounds
        active = self.vehicles if active_bounds is None else [
            v for v in self.vehicles if in_bounds(active_bounds, v.x, v.y, math.hypot(v.length_m, v.width_m) * 0.5)]
        previous_poses = {id(v): (v.x, v.y, v.heading) for v in active}
        self._collision_buildings, self._collision_building_grid = buildings, building_grid
        active_ids = {id(v) for v in active}
        for vehicle in self.vehicles:
            if vehicle.knock_vx or vehicle.knock_vy:
                if id(vehicle) in active_ids:
                    update_knocked(vehicle, dt, buildings, building_grid, ways, spatial_grid)
                else:  # left the simulated area mid-slide: it has come to rest, its driver goes on later
                    vehicle.knock_vx = vehicle.knock_vy = 0.0
        for vehicle in self.vehicles:
            if vehicle.state == NPCState.CRASHED:
                vehicle.car.speed = 0.0
                vehicle.crashed_timer += dt
                vehicle.turn_signal_elapsed += dt
        previous_player_pose = self._previous_player_pose
        if player_car is not None:
            self._previous_player_pose = (player_car.x, player_car.y, player_car.heading)
        pedestrians_near = self._pedestrian_lookup(pedestrian_mgr, active)
        for vehicle in list(self.vehicles):  # a copy: a stuck cyclist may retire mid-loop
            if vehicle.vehicle_id in self.road_rage.held or vehicle.brawl_id is not None:
                continue  # held aside by rage clearance, or its driver is out brawling: it stays put
            if vehicle.knock_vx or vehicle.knock_vy:
                continue  # knocked, sliding: the driver takes over again once it has stopped
            driver = self.drivers.get(vehicle.vehicle_id)
            if driver is None:
                continue  # idle, parked - nothing to simulate until it starts a trip
            distance_sq = (vehicle.x - player_x) ** 2 + (vehicle.y - player_y) ** 2
            if ((active_bounds is not None and id(vehicle) not in previous_poses)
                    or (active_bounds is None and distance_sq > self.simulation_radius_m * self.simulation_radius_m)):
                # Section 17/18: still exists, keeps its full state, just
                # doesn't tick physics/decisions while this far away - not
                # "outside camera = nonexistent".
                continue
            # collision-avoidance section 2: only vehicles actually near this one need
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
            nearby_obstacles = with_trailers(self.nearby_vehicles_at(
                vehicle.x, vehicle.y, max(65.0, following_detection_distance(vehicle))))
            if player_car is not None:
                nearby_obstacles.append(player_car)
            if vehicle_definition(vehicle.vehicle_type).movement == "cycle":
                self._update_cyclist(vehicle, driver, dt, traffic_world, resident_manager, nearby_obstacles,
                                     pedestrians_near(vehicle.x, vehicle.y), spatial_grid, viewport_bounds)
                continue
            update_npc(
                vehicle, driver, dt, traffic_world, resident_manager,
                curbs=curbs, buildings=buildings, curb_grid=curb_grid, building_grid=building_grid,
                nearby_obstacles=nearby_obstacles, manager=self, pedestrian_mgr=pedestrian_mgr,
                spatial_grid=spatial_grid,
            )
            if vehicle.state == NPCState.PARKED:
                self._handle_parked_vehicle(vehicle, resident_manager, traffic_world.sim_time, pedestrian_mgr)

        for vehicle in active:  # trailers swing after where their vehicles drove (trailers.py)
            if vehicle.trailer_spec is not None:
                vehicle.update_trailer()

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
        for vehicle in active:
            previous = previous_poses.get(id(vehicle))
            if previous is None:
                continue
            travel = math.hypot(vehicle.x - previous[0], vehicle.y - previous[1])
            mid_x, mid_y = (vehicle.x + previous[0]) * 0.5, (vehicle.y + previous[1]) * 0.5
            radius = travel * 0.5 + max_frame_travel + max(vehicle.length_m, vehicle.width_m) + 3.0
            collision_candidates = with_trailers(self.nearby_vehicles_at(mid_x, mid_y, radius))
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
            transit_focus = transit_spawn_focus(player_x, player_y, player_car, self.simulation_radius_m)
            self._run_population_tick(
                player_x, player_y, resident_manager, traffic_world, ways, spatial_grid,
                parking_spaces, sceneries, buildings, curbs, curb_grid, building_grid,
                viewport_bounds=viewport_bounds, transit_focus=transit_focus,
                transit_heading=getattr(player_car, "heading", None),
                current_way=current_way,
            )
