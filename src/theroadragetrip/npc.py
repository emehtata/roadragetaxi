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

import itertools
import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from .geo import clamp, closest_point_and_dist_to_segment, segment_distance
from .osm import Curb, Way
from .physics import GRAVITY_MPS2, Car, SpatialWayGrid, update_car_physics
from .residents import ResidentManager
from .traffic_rules import TrafficAction, TrafficDecision, decide_traffic_action
from .traffic_world import TrafficWorld


class NPCState:
    """Vehicle state machine (NPC-001 section 10).

    The architecture must support future states without rework, but
    NPC-001 only implements these: CRASHED, DISABLED, DRIVER_EXITED,
    ABANDONED, DESPAWNING are deliberately not implemented yet.
    """
    SPAWNING = "SPAWNING"
    CRUISING = "CRUISING"
    APPROACHING_INTERSECTION = "APPROACHING_INTERSECTION"
    WAITING = "WAITING"
    TURNING = "TURNING"
    PARKING = "PARKING"  # final approach into a dedicated parking space (NPC-more.md section 14)
    ARRIVING = "ARRIVING"
    PARKED = "PARKED"  # stopped and settled at the destination (multi-passenger-car.md section 17)


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
ARRIVAL_DECEL_MPS2 = 3.0  # comfortable braking rate approaching the final destination waypoint
NPC_FOOTPRINT_VIOLATION_CRAWL_MPS = 2.0  # never a hard 0 - see update_npc's live footprint check
NPC_LIVE_FOOTPRINT_CLEARANCE_M = 0.05  # a hair's width - only an actual overlap counts live, not lag
NPC_CORNER_COMFORT_LATERAL_G = 0.5  # a comfortable cornering effort, well under GRIP.md's max_grip_g limit
NPC_CORNER_BRAKING_DECEL_MPS2 = 3.0  # comfortable braking rate approaching a corner
NPC_CORNER_LOOKAHEAD_M = 40.0  # how far ahead to start braking for an upcoming turn
LANE_BIAS_LOOKAHEAD_M = 20.0  # start easing into a turn lane this far before the corner (NPC-002 section 5)
NPC_VEHICLE_LENGTH_M = 4.3  # the one NPC car's dimensions - shared so footprint checks always match the spawned Car
NPC_VEHICLE_WIDTH_M = 1.8

# multi-passenger-car.md section 2: capacity is a per-vehicle-type lookup,
# never a hardcoded literal in passenger-management logic - a future
# vehicle_type just needs an entry here, no other code changes.
NPC_VEHICLE_CAPACITY_BY_TYPE = {"car": 5}
DEFAULT_NPC_VEHICLE_CAPACITY = 5
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


NPC_PARKING_ACCESS_TOLERANCE_M = 40.0  # the final hop off-road, into a yard/driveway, gets more slack
NPC_PARKING_APPROACH_DISTANCE_M = 6.0  # how far out the orientation-aligned approach point sits


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
        key=lambda h: abs((h - natural_heading + math.pi) % (2.0 * math.pi) - math.pi),
    )
    approach_point = (
        destination[0] - math.cos(heading) * approach_distance_m,
        destination[1] - math.sin(heading) * approach_distance_m,
    )
    return route_points[:-1] + [approach_point, destination]


def route_stays_on_road(
    points: List[Tuple[float, float]],
    ways: List[Way],
    spatial_grid: Optional[SpatialWayGrid] = None,
    tolerance_m: float = MAX_ROUTE_OFFROAD_TOLERANCE_M,
    final_segment_tolerance_m: Optional[float] = None,
    final_segment_count: int = 1,
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
    the road than the 15m that would flag a mid-route shortcut as
    suspicious (NPC-more.md section 6's "safe driveway or building
    courtyard").
    """
    segment_count = len(points) - 1
    for i in range(segment_count):
        (ax, ay), (bx, by) = points[i], points[i + 1]
        _, distance = _way_at_point(spatial_grid, ways, (ax + bx) / 2.0, (ay + by) / 2.0)
        segment_tolerance = (
            tolerance_m
            if final_segment_tolerance_m is None or i < segment_count - final_segment_count
            else final_segment_tolerance_m
        )
        if distance > segment_tolerance:
            return False
    return True


CURB_CLEARANCE_MARGIN_M = 0.3  # a little slack beyond the bare vehicle body
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
) -> bool:
    """Sample is_vehicle_pose_valid densely along a whole path (see
    _densify_path/_path_headings) - the shared engine behind
    route_crosses_curbs and route_crosses_buildings."""
    if len(path_points) < 2 or (not curbs and not buildings):
        return False
    dense = _densify_path(path_points)
    headings = _path_headings(dense)
    for (x, y), heading in zip(dense, headings):
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
    )


def route_crosses_buildings(
    path_points: List[Tuple[float, float]],
    buildings: List,
    vehicle_width_m: float = NPC_VEHICLE_WIDTH_M,
    vehicle_length_m: float = NPC_VEHICLE_LENGTH_M,
    building_grid: Optional[SpatialWayGrid] = None,
    clearance_m: float = BUILDING_CLEARANCE_MARGIN_M,
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
    crashed_timer: float = 0.0
    capacity: int = DEFAULT_NPC_VEHICLE_CAPACITY
    trip_group: Optional[TripGroup] = None

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

    `parking_space`, when given, is the ParkingSpace `destination` was
    chosen for (see _pick_npc_destination_candidates) - the caller reserves
    it only once this returns a real path, never optimistically before, so
    a rejected route never leaves a phantom reservation to clean up.
    """
    raw_route = traffic_world.plan_route(origin, destination)
    if raw_route is None:
        return None
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
    drivable_ways = [way for way in ways if getattr(way, "is_drivable", True)]
    if not route_stays_on_road(
        deduped_route, drivable_ways, spatial_grid=spatial_grid,
        final_segment_tolerance_m=NPC_PARKING_ACCESS_TOLERANCE_M,
        final_segment_count=final_segment_count,
    ):
        return None

    path = build_driving_path(
        deduped_route, ways, spatial_grid=spatial_grid, skip_final_lane_offset=destination_is_off_road,
    )
    if len(path) < 2:
        return None
    path_points = [(p.x, p.y) for p in path]
    # NPC-more.md section 7: never drive on curbs - checked against the
    # actual lane-offset/corner-rounded trajectory, not the raw centerline,
    # since a wide vehicle clips a curb at a corner or roundabout island,
    # not at the road's own centerline.
    if route_crosses_curbs(path_points, curbs or [], curb_grid=curb_grid):
        return None
    # NPC-more.md section 13: never drive through a building polygon.
    if route_crosses_buildings(path_points, buildings or [], building_grid=building_grid):
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
    color: Tuple[int, int, int] = (150, 155, 165),
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

    # 1. create/select the Resident group, 2. designate its first member
    # as driver, 3. create the vehicle, 4. associate vehicle<->Driver<->
    # TripGroup - in that order, per section 11 - never a moving vehicle
    # first with a driver attached after.
    #
    # multi-passenger-car.md sections 2, 5: capacity is a per-vehicle-type
    # lookup, and the group is never auto-filled to capacity - a lone
    # driver (group size 1) is exactly as valid as a full car.
    capacity = NPC_VEHICLE_CAPACITY_BY_TYPE.get(vehicle_type, DEFAULT_NPC_VEHICLE_CAPACITY)
    group_size = random.randint(1, max(1, capacity))
    members = [resident_manager.create(mode="driving" if i == 0 else "riding") for i in range(group_size)]
    driver_resident = members[0]
    for member in members:
        member.vehicle_ids.add(vehicle_id)
    driver_resident.active_vehicle_id = vehicle_id

    start, aim = path[0], path[1]
    start_heading = math.atan2(aim.y - start.y, aim.x - start.x)
    car = Car(x=start.x, y=start.y, heading=start_heading, speed=0.0, length_m=NPC_VEHICLE_LENGTH_M, width_m=NPC_VEHICLE_WIDTH_M)
    member_ids = [member.resident_id for member in members]
    trip_group = TripGroup(
        group_id=next(_trip_group_id_counter),
        vehicle_id=vehicle_id,
        member_resident_ids=member_ids,
        boarded_resident_ids=set(member_ids),
        activity_type=random.choice(NPC_TRIP_ACTIVITY_TYPES),
        activity_duration_s=random.uniform(NPC_BUILDING_VISIT_MIN_S, NPC_BUILDING_VISIT_MAX_S),
    )
    for member in members:
        member.trip_group_id = trip_group.group_id
    vehicle = NPCVehicle(
        vehicle_id=vehicle_id,
        car=car,
        owner_id=driver_resident.resident_id,
        way=start.way,
        destination=destination,
        travel_route=[(p.x, p.y) for p in path],
        vehicle_type=vehicle_type,
        capacity=capacity,
        trip_group=trip_group,
    )
    driver = Driver(
        resident_id=driver_resident.resident_id,
        vehicle_id=vehicle_id,
        path=path,
        destination=destination,
        current_way=start.way,
    )
    if parking_space is not None:
        parking_space.reserved = True
        parking_space.vehicle_id = vehicle_id
        vehicle.destination_parking_space_id = getattr(parking_space, "osm_id", None)
        vehicle.reserved_parking_space = parking_space
    return driver_resident.resident_id, driver, vehicle


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
) -> None:
    """Advance one NPC's driving decision and physics by one frame
    (NPC-001 sections 5-10). Pure simulation, no Pygame.

    Performance (section 16): the route is never recalculated here (only
    once, in spawn_npc); the only per-frame scan is the traffic-light
    lookup, and it reuses TrafficWorld._nearby_traffic_lights - the same
    call the player's own red-light assist already makes every frame.
    Checking the live pose (below) is the same kind of cheap, spatial-
    grid-bounded lookup, not a full route re-validation.

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
        return

    if vehicle.state == NPCState.PARKED:
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
    at_destination = approaching_final_waypoint and distance_to_target < NPC_ARRIVAL_RADIUS_M

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
        arrival_cap = math.sqrt(2.0 * ARRIVAL_DECEL_MPS2 * max(0.0, distance_to_target - NPC_ARRIVAL_RADIUS_M))
        driver.target_speed_mps = min(driver.target_speed_mps, arrival_cap)

    # Brake for a sharp corner the same comfortable way, well before
    # reaching it - nothing else here ever slows the vehicle down for the
    # geometry of a turn itself (only traffic rules and final arrival do),
    # so a corner used to always get taken at full cruising speed, well
    # past what the tires can actually deliver at that radius
    # (physics.py's own understeer clamp then pushes the car wide -
    # reported: NPC repeatedly understeering into a curb/building at a
    # sharp turn, retriggering the live footprint check every time).
    corner_distance = _distance_to_next_turn(path, driver.path_index, vehicle.car.x, vehicle.car.y)
    if corner_distance is not None:
        corner_speed = _corner_safe_speed_mps()
        corner_cap = math.sqrt(corner_speed * corner_speed + 2.0 * NPC_CORNER_BRAKING_DECEL_MPS2 * corner_distance)
        driver.target_speed_mps = min(driver.target_speed_mps, corner_cap)
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
    footprint_clear = is_vehicle_pose_valid(
        vehicle.car.x, vehicle.car.y, vehicle.car.heading,
        curbs=curbs, buildings=buildings, curb_grid=curb_grid, building_grid=building_grid,
        length_m=vehicle.length_m, width_m=vehicle.width_m, clearance_m=NPC_LIVE_FOOTPRINT_CLEARANCE_M,
    )
    if not footprint_clear:
        # A slow crawl, never a hard 0 - update_car_physics refuses to
        # turn the vehicle at all below 0.05 m/s ("cars cannot steer in
        # place while stationary"), so a full stop here would deadlock:
        # the only way off an actually-overlapping pose is to keep
        # moving, and a genuine zero-speed floor can never move again on
        # its own (reported: NPC stuck oscillating in place forever).
        driver.target_speed_mps = min(driver.target_speed_mps, NPC_FOOTPRINT_VIOLATION_CRAWL_MPS)

    # State machine (section 10) - priority order is what a real driver
    # would report as "what am I doing right now".
    if not footprint_clear:
        vehicle.state = NPCState.WAITING
        vehicle.debug_waiting_for = "footprint blocked (curb/building)"
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
    """
    radius_sq = search_radius_m * search_radius_m

    # Each tier is only ever scanned if every higher tier came up empty
    # (section 20: no need to walk thousands of buildings when a parking
    # space already covers this point) - "retry the next-nearest option"
    # only matters *within* whichever single tier actually has anything.
    space_candidates = []
    for space in parking_spaces or ():
        if getattr(space, "occupied", False) or getattr(space, "reserved", False):
            continue
        if not _parking_space_fits_vehicle(space):
            continue
        bbox = getattr(space, "bbox", None)
        if not bbox:
            continue
        cx, cy = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
        dist_sq = (cx - x) ** 2 + (cy - y) ** 2
        if dist_sq <= radius_sq:
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
            if dist_sq <= radius_sq:
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
                if dist_sq <= radius_sq:
                    building_candidates.append((dist_sq, point, None))
            ordered = building_candidates

    ordered.sort(key=lambda c: c[0])
    if not ordered:
        roadside = _roadside_parking_point(x, y, ways, spatial_grid)
        if roadside is not None:
            ordered = [(0.0, roadside, None)]

    return [(point, space) for _, point, space in ordered[:limit]]


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
) -> bool:
    """multi-passenger-car.md section 21: once a trip group's passengers
    have all reboarded (or update_npc's return-timeout left a straggler
    behind), release this vehicle's parking spot and send it to a new
    destination in place - reusing the exact same destination-selection/
    validation machinery as a brand-new spawn (_pick_npc_destination_
    candidates, _plan_and_validate_npc_route), never a second, parallel
    routing implementation.

    Mutates `driver`/`vehicle` in place (same Resident group, same vehicle
    identity - only the route changes) and returns whether a next
    destination was actually found. False leaves the vehicle parked to
    try again on a later call, the same "don't get stuck on one bad
    candidate forever" fallback spawn_deterministic_npc already uses for
    a brand-new trip.
    """
    origin = (vehicle.car.x, vehicle.car.y)
    destination_candidates = _pick_npc_destination_candidates(
        origin[0], origin[1], parking_spaces, sceneries, buildings,
        ways=ways, spatial_grid=spatial_grid,
    )
    for destination, target_space in destination_candidates:
        destination_is_off_road = destination != origin
        path = _plan_and_validate_npc_route(
            traffic_world, ways, origin, destination, spatial_grid=spatial_grid,
            curbs=curbs, curb_grid=curb_grid, buildings=buildings, building_grid=building_grid,
            parking_space=target_space, destination_is_off_road=destination_is_off_road,
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
