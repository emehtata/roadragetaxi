"""Tests for pedestrian crossing (suojatie) extraction and rendering."""
import math
from theroadragetrip.osm import Building, Crossing, Way, build_ways
from theroadragetrip.street_lights import _way_should_have_street_lighting


def test_secondary_street_lighting_defaults_to_built_up_areas():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="secondary", half_width_m=4.0)
    building = Building(
        points_m=[(20.0, 20.0), (30.0, 20.0), (30.0, 30.0), (20.0, 30.0)],
        bbox=(20.0, 20.0, 30.0, 30.0),
    )

    assert _way_should_have_street_lighting(road, [building], (0.0, 0.0))
    assert not _way_should_have_street_lighting(road, [], (0.0, 0.0))


def test_secondary_explicit_lighting_overrides_area_fallback():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="secondary", half_width_m=4.0)

    road.lit = "yes"
    assert _way_should_have_street_lighting(road, [])
    road.lit = "no"
    assert not _way_should_have_street_lighting(road, [Building([], bbox=(0.0, 0.0, 1.0, 1.0))])


def test_explicit_lit_yes_has_priority_without_buildings():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="tertiary", half_width_m=4.0, lit="yes")

    assert _way_should_have_street_lighting(road, [])


def test_explicit_lit_no_has_priority_near_buildings():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="tertiary", half_width_m=4.0, lit="no")
    building = Building([], bbox=(0.0, 0.0, 1.0, 1.0))

    assert not _way_should_have_street_lighting(road, [building], (0.0, 0.0))


def test_building_proximity_lights_urban_unlit_road_types():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="tertiary", half_width_m=4.0)
    building = Building([], bbox=(0.0, 0.0, 1.0, 1.0))

    assert _way_should_have_street_lighting(road, [building], (0.0, 0.0))


def test_building_proximity_does_not_light_motorways():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="motorway", half_width_m=6.0)
    building = Building([], bbox=(0.0, 0.0, 1.0, 1.0))

    assert not _way_should_have_street_lighting(road, [building], (0.0, 0.0))


def test_building_outer_edge_and_neighbor_grid_cell_count_as_near():
    road = Way(points_m=[(99.0, 0.0), (199.0, 0.0)], highway="tertiary", half_width_m=4.0)
    building = Building(
        points_m=[(0.0, 20.0), (10.0, 20.0), (10.0, 30.0), (0.0, 30.0)],
        bbox=(0.0, 20.0, 10.0, 30.0),
    )
    grid = {(0, 0): [building]}

    assert _way_should_have_street_lighting(road, [building], (99.0, 0.0), grid)


def test_taajama_building_distance_reaches_200_metres():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="tertiary", half_width_m=4.0)
    building = Building(
        points_m=[(150.0, 0.0), (160.0, 0.0), (160.0, 10.0), (150.0, 10.0)],
        bbox=(150.0, 0.0, 160.0, 10.0),
    )

    assert _way_should_have_street_lighting(road, [building], (0.0, 0.0))


def test_named_road_does_not_inherit_lighting_into_rural_segment():
    road = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="tertiary",
        half_width_m=4.0,
        name="Rautatienkatu",
    )

    assert not _way_should_have_street_lighting(road, [], (0.0, 0.0))


def test_build_ways_extracts_crossings_and_aligns_with_road():
    elements = [
        # Road going East-West (from x=0, y=100 to x=100, y=100)
        {
            "type": "node",
            "id": 1,
            "lat": 65.0,
            "lon": 25.0,
        },
        {
            "type": "node",
            "id": 2,
            "lat": 65.0,
            "lon": 25.01,
        },
        {
            "type": "way",
            "id": 10,
            "nodes": [1, 2],
            "tags": {"highway": "residential", "name": "Torikatu"},
        },
        # Crossing node located near middle of the road
        {
            "type": "node",
            "id": 3,
            "lat": 65.0,
            "lon": 25.005,
            "tags": {"highway": "crossing", "crossing": "zebra"},
        },
    ]

    res = build_ways(elements)
    assert hasattr(res, "crossings")
    assert len(res.crossings) == 1
    c = res.crossings[0]
    assert isinstance(c, Crossing)
    assert c.id == 3
    assert c.crossing_type == "zebra"
    # Direction angle should be aligned with the road (roughly horizontal / 0 radians)
    assert c.direction_angle is not None
    assert abs(c.direction_angle) < 0.2 or abs(c.direction_angle - math.pi) < 0.2


def test_crossing_node_off_road_centerline_snaps_onto_the_road():
    """OSM often digitizes a crossing node a few meters off the road it
    belongs to. Regression: build_ways used to keep the raw OSM node
    position, so the rendered zebra stripes floated beside the road
    instead of sitting flush on it - snap onto the nearest point of the
    matched road instead."""
    elements = [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.0, "lon": 25.01},
        {
            "type": "way",
            "id": 10,
            "nodes": [1, 2],
            "tags": {"highway": "residential", "name": "Torikatu"},
        },
        # Crossing node ~3m off the (flat, east-west) road's latitude.
        {
            "type": "node",
            "id": 3,
            "lat": 65.00003,
            "lon": 25.005,
            "tags": {"highway": "crossing", "crossing": "zebra"},
        },
    ]

    res = build_ways(elements)
    c = res.crossings[0]
    (ax, ay), (bx, by) = res.ways[0].points_m
    from theroadragetrip.geo import dist_point_to_segment

    offset_from_road_m = dist_point_to_segment(c.x, c.y, ax, ay, bx, by)
    assert offset_from_road_m < 0.5, (
        f"crossing not snapped onto its road: {offset_from_road_m:.2f}m off centerline"
    )


def test_nearby_crossings_at_a_compact_junction_dont_overlap():
    """Regression: a real, compact junction mapped one highway=crossing
    node per leg a few meters apart (Torikatu/Pakkahuoneenkatu in Oulu).
    Each crossing sized to its own road's full width rendered as an
    ~8m-wide zebra field regardless of how close the next crossing was,
    so two crossings on roughly perpendicular roads overlapped into an
    hourglass/X pattern in the middle of the junction instead of two
    separate, non-overlapping crossings."""
    elements = [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.0, "lon": 25.01},
        {
            "type": "way", "id": 10, "nodes": [1, 2],
            "tags": {"highway": "residential", "name": "Torikatu"},
        },
        {"type": "node", "id": 3, "lat": 64.998, "lon": 25.005},
        {"type": "node", "id": 4, "lat": 65.002, "lon": 25.005},
        {
            "type": "way", "id": 11, "nodes": [3, 4],
            "tags": {"highway": "residential", "name": "Pakkahuoneenkatu"},
        },
        # Two crossings close to each other (~4m apart) near the junction -
        # one on each road.
        {"type": "node", "id": 5, "lat": 65.0, "lon": 25.00505, "tags": {"highway": "crossing"}},
        {"type": "node", "id": 6, "lat": 65.00003, "lon": 25.005, "tags": {"highway": "crossing"}},
        # A third, isolated crossing far from the cluster, on the same road.
        {"type": "node", "id": 7, "lat": 65.0, "lon": 25.008, "tags": {"highway": "crossing"}},
    ]

    res = build_ways(elements)
    by_id = {c.id: c for c in res.crossings}
    assert set(by_id) == {5, 6, 7}

    close_pair_distance = math.hypot(by_id[5].x - by_id[6].x, by_id[5].y - by_id[6].y)
    assert close_pair_distance < 5.0, "test setup: the pair should actually be close together"
    assert by_id[5].width_m <= close_pair_distance + 1e-6
    assert by_id[6].width_m <= close_pair_distance + 1e-6

    # The isolated crossing is unaffected by clipping.
    assert by_id[7].width_m > close_pair_distance








