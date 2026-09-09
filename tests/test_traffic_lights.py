"""Tests for procedural traffic-light and intersection-signal generation
(src/theroadragetrip/osm/traffic_signals.py), per
.github/prompts/TRAFFICLIGHTS_PROMPT.md.

Deliberately does not test NPC AI's interaction with signals - that's out
of scope for this pipeline (see the module's own docstring).
"""
import math

from theroadragetrip.osm import SignalGroup, TrafficLight, Way, build_ways
from theroadragetrip.osm.traffic_signals import (
    MIN_SIGNALIZED_ARMS,
    build_traffic_light_system,
)


def _four_way_ways(center=(0.0, 0.0), arm_length=100.0, **way_kwargs):
    cx, cy = center
    return {
        "north": Way([(cx, cy), (cx, cy + arm_length)], "residential", 4.0, **way_kwargs),
        "south": Way([(cx, cy), (cx, cy - arm_length)], "residential", 4.0, **way_kwargs),
        "east": Way([(cx, cy), (cx + arm_length, cy)], "residential", 4.0, **way_kwargs),
        "west": Way([(cx, cy), (cx - arm_length, cy)], "residential", 4.0, **way_kwargs),
    }


def test_single_signal_node_generates_a_full_four_way_intersection():
    """The core requirement: OSM data with only ONE traffic_signals node
    for the whole junction must still produce a signal for every incoming
    approach, not just a single light at that one node."""
    arms = _four_way_ways()
    lights, intersections = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))

    assert len(lights) == 4
    assert len(intersections) == 1
    intersection = intersections[0]
    assert len(intersection.approaches) == 4


def test_north_south_and_east_west_are_on_separate_phases():
    arms = _four_way_ways()
    lights, _ = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))
    groups_by_direction = {}
    for light in lights:
        # direction_angle points INTO the intersection; north/south lights
        # point roughly +-pi/2, east/west roughly 0/pi.
        axis = light.direction_angle % math.pi
        key = "ns" if math.sin(axis) ** 2 > 0.5 else "ew"
        groups_by_direction.setdefault(key, set()).add(light.signal_group.approach_id)

    assert len(groups_by_direction["ns"]) == 1
    assert len(groups_by_direction["ew"]) == 1
    assert groups_by_direction["ns"] != groups_by_direction["ew"]


def test_conflicting_phases_are_never_green_at_the_same_time():
    arms = _four_way_ways()
    lights, _ = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))
    groups = {light.signal_group.approach_id: light.signal_group for light in lights}
    assert len(groups) == 2
    group_a, group_b = groups.values()

    both_saw_green = [False, False]
    steps = 200
    for i in range(steps):
        t = (group_a.cycle_time * i) / steps
        state_a = group_a.get_state(t)
        state_b = group_b.get_state(t)
        assert not (state_a == "green" and state_b == "green"), f"both phases green at t={t}"
        both_saw_green[0] = both_saw_green[0] or state_a == "green"
        both_saw_green[1] = both_saw_green[1] or state_b == "green"

    assert all(both_saw_green), "each phase should get a green turn somewhere in the cycle"


def test_irregular_five_way_junction_never_shows_conflicting_greens():
    """Regression, from a real production intersection: 5 approaches at
    roughly 111, -120(240), 60, 146, and -35(325) degrees. Two of those
    (111 and 60) are only 51 degrees apart - not opposite - but both used
    to land in the same coarse "axis half" phase bucket and got green at
    the same time, which is exactly the kind of conflict a real traffic
    light must never create. The other four arms *do* form two genuine
    opposite pairs (240<->60 and 146<->325) and should still be able to
    share a phase with their actual opposite."""
    center = (0.0, 0.0)

    def arm(angle_deg):
        angle = math.radians(angle_deg)
        far = (center[0] + math.cos(angle) * 100.0, center[1] + math.sin(angle) * 100.0)
        return Way([center, far], "residential", 4.0)

    angles = [111.1, -120.0, 60.0, 145.9, -34.5]
    ways = [arm(a) for a in angles]
    lights, intersections = build_traffic_light_system([(0.0, 0.0, 0)], ways)

    assert len(lights) == 5
    groups = {light.signal_group.approach_id: light.signal_group for light in lights}
    # The lone 111.1-degree arm has no real opposite among the other four,
    # so it must end up alone in its own phase.
    assert len(groups) == 3

    steps = 400
    cycle = next(iter(groups.values())).cycle_time
    for i in range(steps):
        t = (cycle * i) / steps
        green_lights = [light for light in lights if light.signal_group.get_state(t) == "green"]
        for a in green_lights:
            for b in green_lights:
                if a is b:
                    continue
                diff = abs((a.direction_angle - b.direction_angle + math.pi) % (2.0 * math.pi) - math.pi)
                assert abs(diff - math.pi) <= math.radians(30.0) + 1e-6, (
                    f"non-opposite arms both green at t={t}: {math.degrees(a.direction_angle):.1f} "
                    f"and {math.degrees(b.direction_angle):.1f}"
                )


def test_generated_signal_never_reaches_the_all_red_state():
    """Regression: draw_traffic_lights doesn't light any lamp for an
    "all-red" state (it isn't part of the normal cycle), so a non-zero
    all_red_duration made every generated light go fully dark for a beat
    every cycle - "no lights shown". Generated signal groups must never
    produce it."""
    arms = _four_way_ways()
    lights, _ = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))
    groups = {light.signal_group.approach_id: light.signal_group for light in lights}

    steps = 240
    for group in groups.values():
        for i in range(steps):
            t = (group.cycle_time * i) / steps
            assert group.get_state(t) != "all-red"


def test_signal_state_sequence_is_red_red_yellow_green_yellow():
    arms = _four_way_ways()
    lights, _ = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))
    group = lights[0].signal_group

    steps = 480
    observed_order = []
    for i in range(steps):
        t = (group.cycle_time * i) / steps
        state = group.get_state(t)
        if not observed_order or observed_order[-1] != state:
            observed_order.append(state)
    # The cycle repeats, so the sampled sequence is some rotation of the
    # 4-state loop - normalize by rotating back to start at "red".
    start = observed_order.index("red")
    normalized = observed_order[start:] + observed_order[:start]
    assert normalized[:4] == ["red", "red+yellow", "green", "yellow"]


def test_t_junction_generates_three_lights_on_two_phases():
    arms = _four_way_ways()
    del arms["north"]
    lights, intersections = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))

    assert len(lights) == 3
    assert len({light.signal_group.approach_id for light in lights}) == 2


def test_two_arms_is_not_signalized():
    """A mid-block pair of opposing arms (effectively a straight road, no
    real junction) shouldn't be turned into a fake intersection."""
    arms = _four_way_ways()
    del arms["north"]
    del arms["west"]
    assert len(arms) < MIN_SIGNALIZED_ARMS
    lights, intersections = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))

    assert lights == []
    assert intersections == []


def test_oneway_exit_only_arm_gets_no_signal():
    """An arm a vehicle can only leave by (not enter) is an exit lane, not
    an approach - it must not receive a traffic light."""
    arms = _four_way_ways()
    # points_m = [center, far]; oneway=1 means legal travel is center->far,
    # i.e. leaving the intersection on this arm.
    arms["west"] = Way([(0.0, 0.0), (-100.0, 0.0)], "residential", 4.0, oneway=1)
    lights, intersections = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))

    assert len(lights) == 3
    assert len(intersections[0].approaches) == 3
    # No light should be facing (pointing into the intersection from) west.
    assert not any(abs(light.direction_angle - 0.0) < 0.1 for light in lights)


def test_oneway_entry_only_arm_still_gets_a_signal():
    arms = _four_way_ways()
    # points_m = [far, center]; oneway=1 means legal travel is far->center,
    # i.e. entering the intersection - this needs a signal.
    arms["west"] = Way([(-100.0, 0.0), (0.0, 0.0)], "residential", 4.0, oneway=1)
    lights, intersections = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))

    assert len(lights) == 4
    assert len(intersections[0].approaches) == 4


def test_divided_carriageway_merges_into_one_signaled_approach():
    """A divided road's two carriageways are usually separate one-way ways
    running parallel to each other. They represent one physical approach
    and must not double up on lights - and specifically the *incoming*
    carriageway must be the one that ends up controlled, regardless of
    which way object happens to be processed first."""
    arms = _four_way_ways()
    # Replace the single west arm with a divided pair: one lane carrying
    # traffic away from the intersection, one carrying it in, offset by a
    # couple of meters (a median) but essentially the same arm direction.
    del arms["west"]
    outbound = Way([(0.0, 1.5), (-100.0, 1.5)], "residential", 4.0, oneway=1)  # leaving
    inbound = Way([(-100.0, -1.5), (0.0, -1.5)], "residential", 4.0, oneway=1)  # entering
    ways = list(arms.values()) + [outbound, inbound]

    for first, second in ((outbound, inbound), (inbound, outbound)):
        lights, intersections = build_traffic_light_system(
            [(0.0, 0.0, 0)], list(arms.values()) + [first, second],
        )
        assert len(lights) == 4, "divided carriageway should still add exactly one west light"
        assert len(intersections[0].approaches) == 4


def test_scattered_signal_nodes_around_one_junction_cluster_together():
    """OSM sometimes maps one signal node per approach rather than one for
    the whole junction - these must collapse into a single
    LogicalIntersection, not four separate ones."""
    arms = _four_way_ways()
    scattered_points = [
        (2.0, 0.0, 0), (-2.0, 0.0, 0), (0.0, 2.0, 0), (0.0, -2.0, 0),
    ]
    lights, intersections = build_traffic_light_system(scattered_points, list(arms.values()))

    assert len(intersections) == 1
    assert len(intersections[0].approaches) == 4


def test_three_way_junction_clusters_regardless_of_node_order():
    """Regression: a real 3-street Oulu junction (Uusikatu / Lävistäjä /
    Kajaaninkatu) has one traffic_signals node per street - A=43.5m from
    B, but A=32.5m from C and B=28.7m from C, so all three belong to one
    physical junction via C. The old greedy centroid clustering checked
    each new point against existing cluster centroids one at a time: in
    OSM's actual node order (A, B, C) it saw A alone first, missed the
    A-B merge (43.5m > radius), and only afterwards merged C into A -
    leaving B stranded in its own cluster and getting its own light
    synthesized from the wrong (2-point) center instead of using B's real
    position. Clustering must not depend on the arrival order of nodes
    that are otherwise identical evidence."""
    center = (0.0, 0.0)

    def arm(angle_deg):
        angle = math.radians(angle_deg)
        far = (center[0] + math.cos(angle) * 150.0, center[1] + math.sin(angle) * 150.0)
        return Way([center, far], "primary", 5.0)

    point_a = (32.18, 4.44, 0)   # Lävistäjä
    point_b = (3.78, -28.46, 0)  # Uusikatu
    point_c = (0.0, 0.0, 0)      # Kajaaninkatu
    ways = [arm(31.6), arm(-111.9), arm(146.3)]
    real_positions = {(point_a[0], point_a[1]), (point_b[0], point_b[1]), (point_c[0], point_c[1])}

    for order in ([point_a, point_b, point_c], [point_c, point_b, point_a], [point_b, point_a, point_c]):
        lights, intersections = build_traffic_light_system(order, ways)
        assert len(intersections) == 1, f"order {order} split into {len(intersections)} intersections"
        assert len(lights) == 3
        # Every light must sit at its arm's real OSM position, not a
        # synthesized fallback - the bug this regression targets left one
        # light's position wrong even when the count/intersection count
        # happened to still look right.
        assert {(light.x, light.y) for light in lights} == real_positions, (
            f"order {order} produced wrong light positions: "
            f"{[(light.x, light.y) for light in lights]}"
        )


def test_wide_real_junction_stays_one_intersection():
    """Regression: a real 4-street Oulu junction (Kajaanintie / Heikinkatu
    / Tulliväylä / Rautatienkatu) has one traffic_signals node per
    approach, spread up to ~48m apart - wider than the old 30m clustering
    radius, which split it into 3 separate LogicalIntersections. Each then
    picked its own (wrong) mix of nearby roads as arms, scattering lights
    across the real junction instead of placing one per actual approach."""
    center = (0.0, 0.0)

    def arm(angle_deg):
        angle = math.radians(angle_deg)
        far = (center[0] + math.cos(angle) * 150.0, center[1] + math.sin(angle) * 150.0)
        return Way([center, far], "primary", 5.0)

    # Real relative bearings/positions of the 4 traffic_signals nodes,
    # translated so their centroid sits at the origin (same processing
    # order as the real data).
    signal_points = [
        (17.77, -6.27, 0), (11.34, 20.56, 0), (-20.35, 8.22, 0), (-8.75, -22.51, 0),
    ]
    ways = [arm(-19.4), arm(61.1), arm(158.0), arm(-111.2)]

    lights, intersections = build_traffic_light_system(signal_points, ways)

    assert len(intersections) == 1
    assert len(intersections[0].approaches) == 4
    assert len(lights) == 4


def test_signal_per_arm_positions_that_arms_light_without_multiplying_it():
    """When OSM maps a separate signal node per arrival direction - and two
    of them for the north arm (e.g. one per lane) - that real evidence
    should position each arm's one light, not multiply it into several
    lights per arm (a real, densely-signalled junction produced exactly
    that mess: many more rendered lights than approaches, scattered off
    the road)."""
    arms = _four_way_ways()
    signal_points = [
        (-1.5, 10.0, 0), (1.5, 10.0, 0),  # north's two lanes
        (0.0, -10.0, 0), (10.0, 0.0, 0), (-10.0, 0.0, 0),  # south, east, west
    ]
    lights, intersections = build_traffic_light_system(signal_points, list(arms.values()))

    assert len(intersections) == 1
    assert len(intersections[0].approaches) == 4
    # Still exactly one light per arm, never more.
    assert len(lights) == 4

    north_lights = [light for light in lights if light.y > 5.0]
    assert len(north_lights) == 1
    # Positioned at the average of the two attributed OSM nodes, not the
    # synthesized fallback.
    assert north_lights[0].x == 0.0 and north_lights[0].y == 10.0


def test_single_central_signal_point_is_divided_not_pinned_to_one_arm():
    """The opposite of the per-lane case: a single OSM node carries no
    directional evidence, so every arm must get its own (synthesized)
    light rather than the one real point being assigned to whichever arm
    it happens to be nearest."""
    arms = _four_way_ways()
    lights, _ = build_traffic_light_system([(1.0, 1.0, 0)], list(arms.values()))

    assert len(lights) == 4
    assert len({(light.x, light.y) for light in lights}) == 4


def test_parking_aisle_arm_doesnt_get_a_traffic_light():
    """Regression: a real 3-street signalized junction (Uusikatu /
    Lävistäjä / Kajaaninkatu in Oulu) had a highway=service,
    service=parking_aisle branching off at nearly the same angle as the
    genuine Lävistäjä approach. It's drivable (unlike a footway) but not a
    real signalized approach - it was still getting counted as a 4th arm
    with its own synthesized light."""
    arms = _four_way_ways()
    arms["driveway"] = Way(
        [(0.0, 0.0), (60.0, 60.0)], "service", 2.0, service="parking_aisle",
    )
    lights, intersections = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))

    assert len(lights) == 4
    assert len(intersections[0].approaches) == 4


def test_service_alley_arm_still_counts_as_a_traffic_light_approach():
    arms = _four_way_ways()
    arms["alley"] = Way([(0.0, 0.0), (60.0, 60.0)], "service", 2.0, service="alley")
    lights, intersections = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))

    assert len(lights) == 5
    assert len(intersections[0].approaches) == 5


def test_footway_arms_dont_get_traffic_lights():
    """A pedestrian path threading through a signal-controlled plaza is not
    a vehicle approach - it must not add its own arm/light, or count
    towards the intersection's phases. Regression: a real, busy plaza with
    several footways near the signal cluster was generating far more
    lights than there were actual vehicle arms."""
    arms = _four_way_ways()
    arms["path"] = Way([(0.0, 0.0), (60.0, 60.0)], "footway", 1.0, is_drivable=False)
    lights, intersections = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))

    assert len(lights) == 4
    assert len(intersections[0].approaches) == 4


def test_stop_line_sits_outside_the_intersection_along_the_approach():
    arms = _four_way_ways()
    _, intersections = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))
    center_x, center_y = intersections[0].center

    for approach in intersections[0].approaches:
        midpoint = (
            (approach.stop_line[0][0] + approach.stop_line[1][0]) / 2.0,
            (approach.stop_line[0][1] + approach.stop_line[1][1]) / 2.0,
        )
        distance_from_center = math.hypot(midpoint[0] - center_x, midpoint[1] - center_y)
        assert 0.0 < distance_from_center < 30.0
        # The stop line should be roughly perpendicular to the approach's
        # own direction vector (a vehicle crosses it moving straight on).
        line_dx = approach.stop_line[1][0] - approach.stop_line[0][0]
        line_dy = approach.stop_line[1][1] - approach.stop_line[0][1]
        line_length = math.hypot(line_dx, line_dy)
        dot = (line_dx * approach.direction_vector[0] + line_dy * approach.direction_vector[1]) / line_length
        assert abs(dot) < 0.1


def test_light_ids_are_stable_across_independent_rebuilds():
    """Tile streaming re-fetches overlapping regions and rebuilds this
    pipeline independently per fetch batch - the same physical intersection
    can end up processed alongside different other intersections, in a
    different order, each time. It must still get the same TrafficLight
    ids, or the existing tile-merge dedup (which keys objects by id, since
    TrafficLight has no osm_id) can't tell they're the same lights and
    duplicates them."""
    arms = _four_way_ways(center=(0.0, 0.0))
    other_arms = _four_way_ways(center=(500.0, 500.0))

    # First fetch batch: just this intersection, on its own.
    first_lights, _ = build_traffic_light_system([(0.0, 0.0, 0)], list(arms.values()))

    # Second, independent fetch batch: the same intersection now shares the
    # call with an unrelated one processed *first*, changing iteration
    # order/cluster index for the intersection under test.
    combined_points = [(500.0, 500.0, 0), (0.0, 0.0, 0)]
    combined_ways = list(other_arms.values()) + list(arms.values())
    second_lights, _ = build_traffic_light_system(combined_points, combined_ways)
    second_lights_at_origin = [light for light in second_lights if abs(light.x) < 50 and abs(light.y) < 50]

    assert {light.id for light in first_lights} == {light.id for light in second_lights_at_origin}
    assert len({light.id for light in first_lights}) == 4


def test_build_ways_end_to_end_generates_logical_intersections():
    """Full pipeline: raw OSM elements with a single traffic_signals node
    on a 4-way junction should reach build_ways()'s output as a complete
    LogicalIntersection, not just a lone TrafficLight at that node."""
    def node(nid, lat, lon, tags=None):
        element = {"type": "node", "id": nid, "lat": lat, "lon": lon}
        if tags:
            element["tags"] = tags
        return element

    # Roughly a 4-way junction at node 5, ~100m arms, each road split into
    # its own way (matching how real OSM extracts are structured).
    elements = [
        node(1, 60.0, 25.0),
        node(5, 60.001, 25.0, {"highway": "traffic_signals"}),
        node(2, 60.002, 25.0),
        node(3, 60.001, 24.998),
        node(4, 60.001, 25.002),
        {"type": "way", "id": 10, "nodes": [1, 5], "tags": {"highway": "residential"}},
        {"type": "way", "id": 11, "nodes": [5, 2], "tags": {"highway": "residential"}},
        {"type": "way", "id": 12, "nodes": [3, 5], "tags": {"highway": "residential"}},
        {"type": "way", "id": 13, "nodes": [5, 4], "tags": {"highway": "residential"}},
    ]

    result = build_ways(elements)

    assert len(result.logical_intersections) == 1
    intersection = result.logical_intersections[0]
    assert len(intersection.approaches) == 4
    assert len(result.traffic_lights) == 4


def test_traffic_light_always_lights_at_least_one_lamp():
    """Regression: an "all-red" state (which the generator itself never
    produces any more, but the dataclass still allows) lit no lamp at all
    - every color rendered dim, reading as a broken/off light rather than
    a red one. Every reachable state must light at least one lamp bright."""
    import pygame

    from theroadragetrip.render import draw_traffic_lights

    pygame.init()
    try:
        screen = pygame.Surface((100, 100))
        bright_colors = {(255, 30, 30), (255, 210, 0), (40, 240, 60)}

        for state in ("red", "red+yellow", "green", "yellow", "all-red"):
            group = SignalGroup(
                approach_id="test",
                cycle_time=10.0,
                green_duration=10.0 if state == "green" else 0.0,
                yellow_duration=10.0 if state == "yellow" else 0.0,
                all_red_duration=10.0 if state == "all-red" else 0.0,
                red_duration=10.0 if state == "red" else 0.0,
                red_yellow_duration=10.0 if state == "red+yellow" else 0.0,
            )
            assert group.get_state(0.0) == state
            light = TrafficLight(x=0.0, y=0.0, signal_group=group, direction_angle=0.0)

            screen.fill((0, 0, 0))
            draw_traffic_lights(screen, [light], 0.0, 0.0, 0.0, px_per_m=10.0, screen_w=100, screen_h=100)

            colors_seen = {
                tuple(screen.get_at((x, y)))[:3] for x in range(100) for y in range(100)
            }
            assert colors_seen & bright_colors, f"state {state!r} lit no lamp"
    finally:
        pygame.quit()
