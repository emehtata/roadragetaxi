"""Tests for procedural traffic-light and intersection-signal generation
(src/theroadragetrip/osm/traffic_signals.py), per
.github/prompts/TRAFFICLIGHTS_PROMPT.md.

Deliberately does not test NPC AI's interaction with signals - that's out
of scope for this pipeline (see the module's own docstring).
"""
import math

from theroadragetrip.osm import Way, build_ways
from theroadragetrip.osm.traffic_signals import (
    MIN_SIGNALIZED_ARMS,
    SIGNAL_CYCLE_S,
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
        t = (SIGNAL_CYCLE_S * i) / steps
        state_a = group_a.get_state(t)
        state_b = group_b.get_state(t)
        assert not (state_a == "green" and state_b == "green"), f"both phases green at t={t}"
        both_saw_green[0] = both_saw_green[0] or state_a == "green"
        both_saw_green[1] = both_saw_green[1] or state_b == "green"

    assert all(both_saw_green), "each phase should get a green turn somewhere in the cycle"


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
