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
from typing import List, Optional, Tuple

from .models import IntersectionApproach, LogicalIntersection, SignalGroup, TrafficLight, Way


# --- Tunables -------------------------------------------------------------

# How close together raw OSM signal nodes must be to count as evidence of
# the *same* physical intersection (prompt Section 9: logical intersection
# clustering). Was 30m; a real 4-street junction (Kajaanintie / Heikinkatu
# / Tulliväylä / Rautatienkatu in the Oulu data set) has one node per
# approach spread up to 47.5m apart - a wide junction, but still one
# intersection. At 30m the greedy centroid clustering below split it into
# 3 separate ones, each then finding its own (wrong) mix of nearby roads
# as "arms" - lights scattered across the junction instead of one per
# real approach. 35m merges it back into one without over-merging real,
# separate junctions elsewhere in the same data set (checked: cluster
# count keeps dropping past 35m only for genuinely oversized clusters).
INTERSECTION_CLUSTER_RADIUS_M = 35.0
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

SIGNAL_GREEN_S = 10.0
SIGNAL_YELLOW_S = 2.0
# No separate all-red clearance phase: the sequence is exactly
# red -> red+yellow -> green -> yellow -> red, matching the local
# (Finnish) signal convention this game otherwise follows. render's
# draw_traffic_lights doesn't light anything for an "all-red" state, so a
# non-zero duration here used to show as every lamp going dark for a beat
# every cycle.
SIGNAL_ALL_RED_S = 0.0
SIGNAL_RED_YELLOW_S = 2.0
# Red buffer between one phase's green+yellow ending and the next phase's
# slot starting.
SIGNAL_PHASE_MARGIN_S = 2.0
# How many arms one signal cycle is built for by default - a plain 4-way
# has 2 (see _group_arms_into_phases). Real intersections aren't always a
# clean +, so this is *not* assumed to be the final phase count; it only
# sizes the constants below for the common case.
# Every phase gets an equal slot long enough for its own green+yellow plus
# the margin; the full cycle is however many phases a given intersection
# actually needs times this slot (see build_traffic_light_system) - a
# fixed cycle length would either force too-short green windows on a
# complex junction or waste time on a simple one.
SIGNAL_PHASE_SLOT_S = SIGNAL_GREEN_S + SIGNAL_YELLOW_S + SIGNAL_PHASE_MARGIN_S

# Two arms only ever share a phase (get green at the same time) when
# they're close enough to exactly opposite (a straight through-road) that
# their traffic doesn't cross - anything else gets its own phase. This is
# the actual safety property ("never show green to all directions" /
# never show it to two conflicting ones); it happens to reduce to the
# textbook "N/S green, then E/W green" for a plain 4-way, but - unlike
# picking a phase from which half of 0-180 degrees an arm's axis falls
# into - it doesn't depend on the intersection being close to a perfect
# grid. A real, only-mildly-skewed 5-way junction found in production data
# had two arms just 51 degrees apart bucketed into the same "axis half" by
# that approach and given simultaneous green - this replaces it.
OPPOSITE_ARM_TOLERANCE = math.radians(30.0)


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
        # Vehicle traffic signals only ever control vehicle arms - a
        # footway/cycleway/path crossing near the same node cluster is not
        # one, and counting it as one was inflating real, busy plazas
        # (lots of pedestrian paths threading through) into intersections
        # with far more "arms" - and lights - than actual traffic lanes.
        if not getattr(way, "is_drivable", True):
            continue
        # A service road (driveway, parking-lot aisle, ...) is drivable
        # but not a real signalized approach - a real intersection with a
        # driveway a few meters from it still has only its actual streets
        # on the signal cycle, not the driveway (it yields instead). Real
        # case: a parking_aisle branching off at nearly the same angle as
        # a genuine signalized street (Lävistäjä) was getting counted as
        # its own arm and its own synthesized light.
        if getattr(way, "highway", None) == "service":
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


def _assign_signal_points_to_arms(
    points: List[Tuple[float, float]], center: Tuple[float, float], arm_angles: List[float],
) -> List[Optional[Tuple[float, float]]]:
    """Attribute raw OSM signal-node positions to their nearest incoming arm
    by bearing from `center`, one representative point per arm (the average
    of whatever was attributed to it, or None if nothing was).

    Only called when a cluster has more than one point: a single point
    carries no directional evidence (it's "one signal in the middle of the
    junction") and must be divided across every arm instead of pinned to
    one, which is what build_traffic_light_system falls back to when this
    isn't used. Multiple points are evidence that OSM *does* distinguish
    arrival directions here - real intersections often carry several
    traffic_signals nodes per arm (near/far-side poles, one per lane, a
    pedestrian-crossing signal, ...), and rendering one physical light per
    such node produced a scattered mess of lights rather than a believable
    intersection; per prompt Section 6 this module models at most one
    physical light per approach, so an arm's evidence is collapsed to its
    average position instead of fanned out one-for-one.
    """
    sums: List[List[float]] = [[0.0, 0.0, 0] for _ in arm_angles]
    for point in points:
        bearing = math.atan2(point[1] - center[1], point[0] - center[0])
        nearest = min(
            range(len(arm_angles)),
            key=lambda i: abs((bearing - arm_angles[i] + math.pi) % (2.0 * math.pi) - math.pi),
        )
        sums[nearest][0] += point[0]
        sums[nearest][1] += point[1]
        sums[nearest][2] += 1
    return [(sx / n, sy / n) if n else None for sx, sy, n in sums]


def _arms_may_share_a_phase(angle_a: float, angle_b: float) -> bool:
    """Whether two arms are close enough to exactly opposite (a straight
    through-road) that giving them green at the same time is safe."""
    diff = abs((angle_a - angle_b + math.pi) % (2.0 * math.pi) - math.pi)
    return abs(diff - math.pi) <= OPPOSITE_ARM_TOLERANCE


def _group_arms_into_phases(arm_angles: List[float]) -> List[List[int]]:
    """Partition arm indices into phases: an arm only ever joins a phase
    when it's genuinely opposite *every* arm already in it (see
    _arms_may_share_a_phase); everything else gets its own phase.

    A phase never ends up with more than 2 members: three distinct arm
    directions can't be pairwise opposite each other (if A is ~180 degrees
    from B and B is ~180 degrees from C, then A and C are at ~0 degrees
    from each other - and _intersection_arms already merges arms that
    close together into one before this ever runs). For a plain 4-way this
    reduces to exactly the familiar 2 phases (opposite pairs); an
    irregular junction (T-junction, 5-way, a skewed crossing) safely gets
    one phase per arm that has no real opposite instead of being forced
    into a pair it actually conflicts with.
    """
    groups: List[List[int]] = []
    assigned = [False] * len(arm_angles)
    for i, angle_i in enumerate(arm_angles):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, len(arm_angles)):
            if assigned[j]:
                continue
            if all(_arms_may_share_a_phase(arm_angles[member], arm_angles[j]) for member in group):
                group.append(j)
                assigned[j] = True
        groups.append(group)
    return groups


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
        approaches: List[IntersectionApproach] = []
        cluster_lights: List[TrafficLight] = []

        phase_assignment = _group_arms_into_phases([arm[0] for arm in incoming_arms])
        num_phases = len(phase_assignment)
        cycle_s = num_phases * SIGNAL_PHASE_SLOT_S

        # A lone signal point is just "somewhere in the junction" - no
        # evidence for which arm it belongs to, so every arm gets a
        # synthesized light (see _assign_signal_points_to_arms). Two or
        # more points are real per-arm evidence, used to place that arm's
        # one light instead of guessing.
        points_per_arm = (
            _assign_signal_points_to_arms(points, center, [arm[0] for arm in incoming_arms])
            if len(points) > 1 else [None for _ in incoming_arms]
        )

        for phase_id, member_indices in enumerate(phase_assignment):
            group = SignalGroup(
                approach_id=f"{intersection_id}:{phase_id}",
                phase_id=phase_id,
                offset=phase_id * SIGNAL_PHASE_SLOT_S,
                cycle_time=cycle_s,
                green_duration=SIGNAL_GREEN_S,
                yellow_duration=SIGNAL_YELLOW_S,
                all_red_duration=SIGNAL_ALL_RED_S,
                red_duration=cycle_s - SIGNAL_GREEN_S - SIGNAL_YELLOW_S - SIGNAL_ALL_RED_S - SIGNAL_RED_YELLOW_S,
                red_yellow_duration=SIGNAL_RED_YELLOW_S,
            )

            for member_index in member_indices:
                arm_angle, _incoming, way = incoming_arms[member_index]
                # Per-arm movements belong on that arm's own TrafficLight/
                # IntersectionApproach below, not unioned onto the shared
                # SignalGroup: a phase can pair two opposite arms with
                # different turn options (e.g. one has a left-turn lane,
                # the other doesn't), and nothing reads a phase-wide
                # "allowed_movements" - conflating them there would just be
                # a second, wrong, answer to a question already answered
                # correctly per-arm.
                movements = _movements_for_way(way)

                # One physical light per arm (prompt Section 6): use the
                # real OSM evidence attributed to this arm, if any, for its
                # position; otherwise synthesize one a little inside the
                # arm, facing back along the direction approaching traffic
                # travels.
                arm_point = points_per_arm[member_index]
                if arm_point is None:
                    light_x = center[0] + math.cos(arm_angle) * 14.0
                    light_y = center[1] + math.sin(arm_angle) * 14.0
                else:
                    light_x, light_y = arm_point
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
                # Stop line sits just outside the intersection along the
                # arm, perpendicular to the direction of travel (prompt
                # Section 11).
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
