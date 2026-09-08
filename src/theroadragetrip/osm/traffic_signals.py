"""Procedural traffic-light and intersection-signal generation.

Builds a believable signal-controlled intersection model from OSM traffic
signal evidence, per .github/prompts/TRAFFICLIGHTS_PROMPT.md. OSM traffic
signal nodes only prove an intersection *is* signal-controlled - not that
every physical light or approach is represented, or that lane/phase data
exists at all. This module follows the prompt's pipeline:

    OSM signal-node evidence
          -> cluster into intersection centers      (_cluster_signal_positions)
          -> detect physical road arms from geometry (_intersection_arms)
          -> generate one signal per incoming arm,
             grouped into non-conflicting phases     (build_traffic_light_system)
          -> assemble LogicalIntersection records     (build_traffic_light_system)

_intersection_arms is the *one* place approach/arm geometry is computed;
both the physical TrafficLight objects and the LogicalIntersection records
are derived from the same arm data, so they can't drift apart the way three
separate ad-hoc arm-detection passes (previously one in build_ways, one in
this module, one more building LogicalIntersections) used to.

NPC AI's actual interaction with signals (the prompt's Phase 7) is
deliberately out of scope here - this module only builds and runs the
signal state machine and the physical/logical intersection model.
"""
import math
from typing import Dict, List, Optional, Tuple

from .models import IntersectionApproach, LogicalIntersection, SignalGroup, TrafficLight, Way


# --- Tunables -------------------------------------------------------------

# How close together raw OSM signal nodes must be to count as evidence of
# the *same* physical intersection (prompt Section 9: logical intersection
# clustering). Real intersections rarely spread signal nodes further than
# this even when OSM maps one node per approach.
INTERSECTION_CLUSTER_RADIUS_M = 30.0
# A way is treated as "ending at" the intersection - the common case, since
# OSM almost always splits ways exactly at junctions - when one of its
# endpoints falls within this distance of the intersection center.
ARM_ENDPOINT_SNAP_M = 20.0
# Fallback for a way that isn't split at this junction (passes near the
# center without ending there): still counted as an arm if it comes this
# close, using the local tangent instead of an endpoint.
ARM_THROUGH_RADIUS_M = 15.0
# Two arms within this angle of each other are the same physical approach
# (e.g. a divided road's two carriageways, or a signal's own node plus a
# road-geometry-derived arm) - see prompt Section 10.
ARM_MERGE_ANGLE = math.radians(25.0)
# A cluster needs at least this many distinct arms to be worth signalizing;
# fewer is usually a mid-block pedestrian signal, not a real junction.
MIN_SIGNALIZED_ARMS = 3

SIGNAL_CYCLE_S = 24.0
SIGNAL_GREEN_S = 10.0
SIGNAL_YELLOW_S = 2.0
SIGNAL_ALL_RED_S = 1.0
SIGNAL_RED_YELLOW_S = 2.0
# Derived so both phase groups' cycles add up to exactly SIGNAL_CYCLE_S.
SIGNAL_RED_S = SIGNAL_CYCLE_S - SIGNAL_GREEN_S - SIGNAL_YELLOW_S - SIGNAL_ALL_RED_S - SIGNAL_RED_YELLOW_S
SIGNAL_PHASE_OFFSET_S = SIGNAL_CYCLE_S / 2.0


def _way_arm_angles(way: Way, center: Tuple[float, float], layer: int) -> Tuple[float, ...]:
    """Return this way's contribution of arm angles (radians, pointing AWAY
    from `center`, outward along the physical road) at an intersection
    centered on `center`.

    Real OSM data almost always splits a way exactly at each junction, so
    the common case is a single arm from whichever endpoint sits at the
    intersection. A way that isn't split there - passes near the center
    without ending - contributes both tangent directions from its nearest
    point instead, so a long unsplit way still gets counted.
    """
    if getattr(way, "layer", 0) != layer:
        return ()
    pts = way.points_m
    if len(pts) < 2:
        return ()
    start, end = pts[0], pts[-1]
    dist_start = math.hypot(start[0] - center[0], start[1] - center[1])
    dist_end = math.hypot(end[0] - center[0], end[1] - center[1])
    if dist_start <= ARM_ENDPOINT_SNAP_M and dist_start <= dist_end:
        return (math.atan2(pts[1][1] - start[1], pts[1][0] - start[0]),)
    if dist_end <= ARM_ENDPOINT_SNAP_M:
        return (math.atan2(pts[-2][1] - end[1], pts[-2][0] - end[0]),)

    nearest_index = min(
        range(len(pts)), key=lambda i: math.hypot(pts[i][0] - center[0], pts[i][1] - center[1])
    )
    if math.hypot(pts[nearest_index][0] - center[0], pts[nearest_index][1] - center[1]) > ARM_THROUGH_RADIUS_M:
        return ()
    prev_index = max(0, nearest_index - 1)
    next_index = min(len(pts) - 1, nearest_index + 1)
    if prev_index == next_index:
        return ()
    prev_point, next_point = pts[prev_index], pts[next_index]
    tangent = math.atan2(next_point[1] - prev_point[1], next_point[0] - prev_point[0])
    return (tangent, tangent + math.pi)


def _arm_is_incoming(way: Way, center: Tuple[float, float]) -> bool:
    """Whether a vehicle can legally travel INTO the intersection along
    this arm, honoring the way's oneway restriction. Two-way roads are
    always incoming; a oneway road only gets a signal on the side traffic
    actually approaches from - the other side is an exit lane, not an
    approach.
    """
    oneway = getattr(way, "oneway", 0)
    if oneway == 0:
        return True
    pts = way.points_m
    start, end = pts[0], pts[-1]
    at_start = math.hypot(start[0] - center[0], start[1] - center[1]) <= math.hypot(
        end[0] - center[0], end[1] - center[1]
    )
    # oneway == 1: legal travel is points_m[0] -> points_m[-1] (start -> end).
    # An arm anchored at "start" is where traffic *leaves* along this way,
    # not where it enters, so it isn't incoming; anchored at "end" is where
    # the legal direction arrives, so it is. oneway == -1 mirrors this.
    return (not at_start) if oneway == 1 else at_start


def _intersection_arms(center: Tuple[float, float], layer: int, ways: List[Way]) -> List[Tuple[float, bool, Way]]:
    """Detect every distinct physical road arm meeting near `center` - the
    one place this geometry is computed, shared by both traffic-light
    generation and LogicalIntersection assembly below.

    Returns (arm_angle, is_incoming, way) tuples, one per distinct
    direction. When two ways contribute the same (merged) arm - e.g. a
    divided road's two carriageways - an incoming one always wins over an
    outgoing duplicate regardless of which was seen first, so which
    carriageway actually needs the signal isn't left to iteration order.
    """
    search_radius = max(ARM_ENDPOINT_SNAP_M, ARM_THROUGH_RADIUS_M) + 5.0
    arms: List[dict] = []
    for way in ways:
        if getattr(way, "layer", 0) != layer or len(way.points_m) < 2:
            continue
        bbox = getattr(way, "bbox", None)
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
            if (
                bbox[2] < center[0] - search_radius or bbox[0] > center[0] + search_radius
                or bbox[3] < center[1] - search_radius or bbox[1] > center[1] + search_radius
            ):
                continue
        for arm_angle in _way_arm_angles(way, center, layer):
            incoming = _arm_is_incoming(way, center)
            existing = next(
                (
                    entry for entry in arms
                    if abs((arm_angle - entry["angle"] + math.pi) % (2.0 * math.pi) - math.pi) <= ARM_MERGE_ANGLE
                ),
                None,
            )
            if existing is None:
                arms.append({"angle": arm_angle, "incoming": incoming, "way": way})
            elif incoming and not existing["incoming"]:
                existing.update(angle=arm_angle, incoming=True, way=way)
    return [(entry["angle"], entry["incoming"], entry["way"]) for entry in arms]


def _phase_group_for_angle(angle: float) -> int:
    """Bucket an arm's axis into one of two non-conflicting phase groups.

    A real intersection's arms naturally fall into two roughly-opposite
    pairs (e.g. N/S and E/W); splitting on axis orientation like this
    generalizes beyond a perfect 4-way (T-junctions, staggered crossings,
    5-way junctions) without needing to assume exactly 4 arms.
    """
    axis = angle % math.pi
    return 1 if math.sin(axis) ** 2 > 0.5 else 0


def _movements_for_way(way: Way) -> frozenset:
    """Infer allowed turning movements for one approach from lane data,
    falling back to a simplified model when OSM has none (prompt Section 7)."""
    turn_lanes = getattr(way, "turn_lanes", None)
    if turn_lanes:
        movement_names = {
            movement
            for lane in turn_lanes.split("|")
            for movement in lane.split(";")
            if movement in {"left", "through", "right", "slight_left", "slight_right"}
        }
        movements = frozenset(
            "straight" if movement == "through" else movement for movement in movement_names
        )
        if movements:
            return movements
    if getattr(way, "lanes", 1) >= 3:
        return frozenset({"left", "straight", "right"})
    return frozenset({"straight", "right"})


def _stable_light_id(layer: int, x: float, y: float) -> int:
    """Deterministic synthetic id for a procedurally generated traffic
    light, derived from its physical position rather than processing
    order. Tile streaming re-fetches overlapping regions and rebuilds
    this pipeline independently per fetch, so a sequential counter would
    give the same real-world intersection a different id every time it's
    rebuilt from a different batch - breaking the existing tile-merge
    dedup (which keys objects by this id, since TrafficLight has no
    osm_id). Negative, like every other procedurally-generated id in this
    module, to stay clear of real OSM node ids.
    """
    return -(abs(hash((layer, round(x, 1), round(y, 1)))) % 2_000_000_000 + 1)


def _cluster_signal_positions(
    signal_points: List[Tuple[float, float, int]],
    cluster_radius_m: float = INTERSECTION_CLUSTER_RADIUS_M,
) -> List[dict]:
    """Group raw OSM signal-node positions into intersection clusters.

    OSM commonly maps one traffic_signals node per approach - sometimes
    just one for the entire junction. Nodes belonging to the same physical
    intersection are rarely more than a lane width or two apart, so a
    simple greedy nearest-cluster-centroid grouping is enough (prompt
    Section 9 calls for "a configurable clustering distance", not a
    general-purpose clustering algorithm).
    """
    clusters: List[dict] = []
    for x, y, layer in signal_points:
        target = None
        for cluster in clusters:
            if cluster["layer"] != layer:
                continue
            cx = sum(point[0] for point in cluster["points"]) / len(cluster["points"])
            cy = sum(point[1] for point in cluster["points"]) / len(cluster["points"])
            if math.hypot(x - cx, y - cy) <= cluster_radius_m:
                target = cluster
                break
        if target is None:
            clusters.append({"layer": layer, "points": [(x, y)]})
        else:
            target["points"].append((x, y))
    return clusters


def build_traffic_light_system(
    signal_points: List[Tuple[float, float, int]], ways: List[Way],
) -> Tuple[List[TrafficLight], List[LogicalIntersection]]:
    """Single entry point for procedural traffic-light generation (see
    module docstring for the full pipeline).

    `signal_points` are raw OSM highway=traffic_signals node positions as
    (x, y, layer) - evidence that an intersection is signal-controlled.
    Everything else - which roads actually meet there, how many approaches
    exist, which lights and signal groups to create - is derived from road
    geometry, not assumed to already be fully described by those points.
    """
    traffic_lights: List[TrafficLight] = []
    logical_intersections: List[LogicalIntersection] = []

    for cluster in _cluster_signal_positions(signal_points):
        layer = cluster["layer"]
        points = cluster["points"]
        center = (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
        arms = _intersection_arms(center, layer, ways)
        if len(arms) < MIN_SIGNALIZED_ARMS:
            continue
        incoming_arms = [arm for arm in arms if arm[1]]
        if not incoming_arms:
            continue

        intersection_id = f"{layer}:{center[0]:.0f}:{center[1]:.0f}"
        phase_groups: Dict[int, SignalGroup] = {}
        approaches: List[IntersectionApproach] = []
        cluster_lights: List[TrafficLight] = []

        for arm_angle, _incoming, way in incoming_arms:
            phase_id = _phase_group_for_angle(arm_angle)
            group = phase_groups.get(phase_id)
            if group is None:
                group = SignalGroup(
                    approach_id=f"{intersection_id}:{phase_id}",
                    phase_id=phase_id,
                    offset=SIGNAL_PHASE_OFFSET_S if phase_id else 0.0,
                    cycle_time=SIGNAL_CYCLE_S,
                    green_duration=SIGNAL_GREEN_S,
                    yellow_duration=SIGNAL_YELLOW_S,
                    all_red_duration=SIGNAL_ALL_RED_S,
                    red_duration=SIGNAL_RED_S,
                    red_yellow_duration=SIGNAL_RED_YELLOW_S,
                )
                phase_groups[phase_id] = group

            movements = _movements_for_way(way)
            group.allowed_movements = group.allowed_movements | movements

            # The physical light sits a little inside the arm, facing back
            # along the direction approaching traffic travels.
            light_x = center[0] + math.cos(arm_angle) * 14.0
            light_y = center[1] + math.sin(arm_angle) * 14.0
            light = TrafficLight(
                x=light_x,
                y=light_y,
                cycle_time=group.cycle_time,
                offset=group.offset,
                layer=layer,
                id=_stable_light_id(layer, light_x, light_y),
                direction_angle=(arm_angle + math.pi) % (2.0 * math.pi),
                signal_group=group,
                approach_id=group.approach_id,
                allowed_movements=movements,
            )
            traffic_lights.append(light)
            cluster_lights.append(light)

            half_width = getattr(way, "half_width_m", 4.0)
            # Stop line sits just outside the intersection along the arm,
            # perpendicular to the direction of travel (prompt Section 11).
            stop_center = (center[0] + math.cos(arm_angle) * 12.0, center[1] + math.sin(arm_angle) * 12.0)
            perp_x, perp_y = -math.sin(arm_angle), math.cos(arm_angle)
            approaches.append(
                IntersectionApproach(
                    approach_id=f"{intersection_id}:{round(arm_angle, 2)}",
                    road_segments=[way],
                    direction_vector=(math.cos(arm_angle), math.sin(arm_angle)),
                    stop_line=(
                        (stop_center[0] - perp_x * half_width, stop_center[1] - perp_y * half_width),
                        (stop_center[0] + perp_x * half_width, stop_center[1] + perp_y * half_width),
                    ),
                    allowed_movements=movements,
                    signal_group=group,
                )
            )

        logical_intersections.append(
            LogicalIntersection(
                intersection_id=intersection_id,
                center=center,
                radius_m=INTERSECTION_CLUSTER_RADIUS_M,
                layer=layer,
                approaches=approaches,
                traffic_lights=cluster_lights,
            )
        )

    return traffic_lights, logical_intersections
