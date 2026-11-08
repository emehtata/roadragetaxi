import math
from theroadragetrip.osm import build_ways, parse_speed_limit_kmh


def test_maxspeed_tag_is_primary_speed_limit_source():
    assert parse_speed_limit_kmh("30", "residential") == 30
    assert parse_speed_limit_kmh("30 km/h", "residential") == 30
    assert parse_speed_limit_kmh("20 mph", "residential") == 32
    assert parse_speed_limit_kmh("50;30", "residential") == 50
    assert parse_speed_limit_kmh("invalid", "residential") == 40
import sys
import types

import pytest

# Provide a lightweight fake `pyproj` so tests don't need the real dependency.
fake_pyproj = types.SimpleNamespace()

class FakeTransformer:
    @staticmethod
    def from_crs(a, b, always_xy=True):
        return FakeTransformer()

    def transform(self, lon, lat):
        # Simple, deterministic transform for tests: scale up lon/lat by 1000
        return (lon * 1000.0, lat * 1000.0)

fake_pyproj.Transformer = FakeTransformer


@pytest.fixture(autouse=True)
def _fake_pyproj(monkeypatch):
    """The fake pyproj for this module's tests only, restored after each:
    installed at import, it leaked into every later test (cached
    municipality centres projected with it, e.g. a long fare to nowhere)."""
    monkeypatch.setitem(sys.modules, "pyproj", fake_pyproj)


from theroadragetrip.osm import build_ways


def test_build_ways_transforms():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
    ]

    ways, waters, buildings, sceneries, places, bounds = build_ways(elements)
    assert len(ways) == 1
    assert len(waters) == 0
    assert len(buildings) == 0
    assert len(sceneries) == 0
    assert len(places) == 0
    w = ways[0]
    # With our fake transformer lon*1000,lat*1000
    x1, y1 = 25.0 * 1000.0, 60.0 * 1000.0
    x2, y2 = 25.001 * 1000.0, 60.001 * 1000.0
    assert w.points_m[0] == (x1, y1)
    assert w.points_m[1] == (x2, y2)
    assert w.highway == "residential"


def test_build_ways_parses_osm_yield_sign():
    result = build_ways([
        {"type": "node", "id": 7, "lat": 60.0, "lon": 25.0,
         "tags": {"highway": "give_way", "layer": "1"}},
    ])

    assert len(result.yield_signs) == 1
    assert result.yield_signs[0].x == 25.0 * 1000.0
    assert result.yield_signs[0].layer == 1


def test_build_ways_parses_priority_road_tags():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {"type": "node", "id": 3, "lat": 60.002, "lon": 25.002},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "primary", "priority_road": "yes"}},
        {"type": "way", "id": 11, "nodes": [2, 3], "tags": {"highway": "secondary", "junction": "priority"}},
    ]

    result = build_ways(elements)

    assert [way.priority_road for way in result.ways] == [True, True]


def test_build_ways_parses_building_entrance_nodes():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.01},
        {"type": "node", "id": 3, "lat": 60.01, "lon": 25.01},
        {"type": "node", "id": 4, "lat": 60.01, "lon": 25.0},
        {"type": "node", "id": 5, "lat": 60.0, "lon": 25.005, "tags": {"entrance": "main"}},
        {"type": "way", "id": 10, "nodes": [1, 5, 2, 3, 4, 1], "tags": {"building": "yes"}},
    ]

    result = build_ways(elements)

    assert result.buildings[0].entrances == [(25.005 * 1000.0, 60.0 * 1000.0)]


def test_build_ways_leaves_entrances_empty_without_osm_node():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.01},
        {"type": "node", "id": 3, "lat": 60.01, "lon": 25.01},
        {"type": "node", "id": 4, "lat": 60.01, "lon": 25.0},
        {"type": "node", "id": 5, "lat": 60.005, "lon": 24.999},
        {"type": "node", "id": 6, "lat": 60.005, "lon": 25.0},
        {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1], "tags": {"building": "yes"}},
        {"type": "way", "id": 11, "nodes": [5, 6], "tags": {"highway": "footway"}},
    ]

    result = build_ways(elements)

    assert result.buildings[0].entrances == []


def test_build_ways_parses_osm_bus_stop():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"highway": "bus_stop", "name": "Keskusta", "shelter": "yes"}},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.0},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
    ]

    result = build_ways(elements)

    assert len(result.bus_stops) == 1
    assert result.bus_stops[0].name == "Keskusta"
    assert result.bus_stops[0].id == 1
    assert result.bus_stops[0].shelter is True


def test_build_ways_includes_parking_aisles_in_drivable_ways():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "service", "service": "parking_aisle"}},
    ]

    result = build_ways(elements)

    assert len(result.ways) == 1
    assert result.ways[0].highway == "service"
    assert result.ways[0].service == "parking_aisle"


def test_build_ways_parses_public_transport_platform_as_bus_stop():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"public_transport": "platform"}},
    ]

    result = build_ways(elements)

    assert len(result.bus_stops) == 1


def test_build_ways_bus_stops_skip_rail_platforms_stop_positions_and_duplicates():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"highway": "bus_stop", "bench": "yes"}},
        {"type": "node", "id": 2, "lat": 60.0001, "lon": 25.0, "tags": {"public_transport": "platform", "bus": "yes"}},  # the same stop, 11 m
        {"type": "node", "id": 3, "lat": 60.01, "lon": 25.0, "tags": {"public_transport": "stop_position", "bus": "yes"}},
        {"type": "node", "id": 4, "lat": 60.02, "lon": 25.0, "tags": {"public_transport": "platform", "railway": "platform", "train": "yes"}},
        {"type": "node", "id": 5, "lat": 60.03, "lon": 25.0, "tags": {"public_transport": "platform", "tram": "yes"}},
    ]

    result = build_ways(elements)

    assert [(stop.id, stop.bench) for stop in result.bus_stops] == [(1, True)]


def test_build_ways_can_exclude_bus_stops_from_world():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"highway": "bus_stop"}},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
    ]

    result = build_ways(elements, include_bus_stops=False)

    assert result.bus_stops == []


def test_build_ways_parses_platform_way_as_bus_stop():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 20, "nodes": [1, 2, 3], "tags": {"public_transport": "platform", "name": "Laituri"}},
    ]

    result = build_ways(elements)

    assert len(result.bus_stops) == 1
    assert result.bus_stops[0].name == "Laituri"
    assert result.bus_stops[0].id == 20


def test_build_ways_parses_closed_natural_bay_as_water():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.01},
        {"type": "node", "id": 3, "lat": 60.01, "lon": 25.01},
        {"type": "node", "id": 4, "lat": 60.01, "lon": 25.0},
        {"type": "way", "id": 11, "nodes": [1, 2, 3, 4, 1], "tags": {"natural": "bay"}},
    ]

    ways, waters, buildings, sceneries, places, bounds = build_ways(elements)

    assert len(waters) == 1
    assert waters[0].kind == "bay"
    assert waters[0].is_polygon is True


def test_build_ways_parses_closed_natural_strait_as_water():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.01},
        {"type": "node", "id": 3, "lat": 60.01, "lon": 25.01},
        {"type": "node", "id": 4, "lat": 60.01, "lon": 25.0},
        {"type": "way", "id": 12, "nodes": [1, 2, 3, 4, 1], "tags": {"natural": "strait"}},
    ]

    ways, waters, buildings, sceneries, places, bounds = build_ways(elements)

    assert len(waters) == 1
    assert waters[0].kind == "strait"
    assert waters[0].is_polygon is True


def test_build_ways_preserves_water_layer():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.01},
        {"type": "way", "id": 13, "nodes": [1, 2], "tags": {"natural": "water", "water": "river", "layer": "-1"}},
    ]

    ways, waters, buildings, sceneries, places, bounds = build_ways(elements)

    assert len(waters) == 1
    assert waters[0].layer == -1


def test_build_ways_skips_culverted_waterways():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.01},
        {"type": "way", "id": 14, "nodes": [1, 2], "tags": {"waterway": "stream", "tunnel": "culvert"}},
        {"type": "way", "id": 15, "nodes": [1, 2], "tags": {"waterway": "drain", "location": "underground"}},
        {"type": "way", "id": 16, "nodes": [1, 2], "tags": {"waterway": "stream"}},
    ]

    ways, waters, buildings, sceneries, places, bounds = build_ways(elements)

    assert len(waters) == 1


def test_a_pitch_keeps_its_sport():
    from theroadragetrip.osm.build import build_ways

    nodes = [{"type": "node", "id": i, "lat": lat, "lon": lon}
             for i, (lat, lon) in enumerate([(65.0, 25.4), (65.0, 25.402), (65.001, 25.402), (65.001, 25.4)], start=1)]
    pitch = {"type": "way", "id": 9, "nodes": [1, 2, 3, 4, 1], "tags": {"leisure": "pitch", "sport": "soccer"}}
    (scenery,) = [s for s in build_ways(nodes + [pitch]).sceneries if s.kind == "pitch"]
    assert scenery.sport == "soccer"


def test_a_stadium_outline_is_open_ground_not_a_roof():
    from theroadragetrip.osm.build import build_ways

    nodes = [{"type": "node", "id": i, "lat": lat, "lon": lon}
             for i, (lat, lon) in enumerate([(65.0, 25.4), (65.0, 25.402), (65.001, 25.402), (65.001, 25.4)], start=1)]
    stadium = {"type": "way", "id": 9, "nodes": [1, 2, 3, 4, 1],
               "tags": {"building": "commercial", "leisure": "stadium", "name": "Test Stadium"}}
    hall = {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1],
            "tags": {"building": "air-supported", "leisure": "sports_centre", "name": "Test Dome"}}
    world = build_ways(nodes + [stadium, hall])
    assert [b.name for b in world.buildings] == ["Test Dome"]  # the dome is a building
    assert [s.kind for s in world.sceneries if s.name == "Test Stadium"] == ["stadium"]


def test_a_building_stadium_is_stadium_ground_too():
    from theroadragetrip.osm.build import build_ways

    nodes = [{"type": "node", "id": i, "lat": lat, "lon": lon}
             for i, (lat, lon) in enumerate([(60.18, 24.92), (60.18, 24.922), (60.181, 24.922), (60.181, 24.92)], start=1)]
    arena = {"type": "way", "id": 9, "nodes": [1, 2, 3, 4, 1], "tags": {"building": "stadium", "building:levels": "5"}}
    world = build_ways(nodes + [arena])
    assert not world.buildings and [s.kind for s in world.sceneries] == ["stadium"]


def test_an_indoor_arena_stays_a_roofed_building():
    from theroadragetrip.osm.build import build_ways

    nodes = [{"type": "node", "id": i, "lat": lat, "lon": lon}
             for i, (lat, lon) in enumerate([(60.18, 24.92), (60.18, 24.922), (60.181, 24.922), (60.181, 24.92)], start=1)]
    hall = {"type": "way", "id": 9, "nodes": [1, 2, 3, 4, 1],
            "tags": {"building": "yes", "leisure": "stadium", "sport": "ice_hockey", "name": "Test Ice Hall"}}
    assert [b.name for b in build_ways(nodes + [hall]).buildings] == ["Test Ice Hall"]


def test_build_ways_keeps_cycling_metadata():
    """cycling.py's network needs bicycle access, cycle lanes, contraflow and motorroad (rrt-019 cyclists)."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {
            "highway": "residential", "oneway": "yes", "oneway:bicycle": "no", "cycleway:right": "lane"}},
        {"type": "way", "id": 11, "nodes": [1, 2], "tags": {"highway": "footway", "bicycle": "designated"}},
        {"type": "way", "id": 12, "nodes": [1, 2], "tags": {"highway": "trunk", "motorroad": "yes"}},
        {"type": "way", "id": 13, "nodes": [1, 2], "tags": {"highway": "secondary", "oneway": "yes"}},
    ]
    ways = {way.osm_id: way for way in build_ways(elements)[0]}
    assert (ways[10].oneway, ways[10].oneway_bicycle, ways[10].cycleway) == (1, 0, "lane")
    assert ways[11].bicycle == "designated"
    assert ways[12].motorroad is True
    assert (ways[13].oneway_bicycle, ways[13].bicycle, ways[13].cycleway, ways[13].motorroad) == (None, None, None, False)


def test_power_man_made_tree_row_stone_level_crossing_are_read():
    def node(nid, lon, **tags):
        return {"type": "node", "id": nid, "lat": 60.0, "lon": 25.0 + lon, "tags": tags}
    elements = [
        node(1, 0.0, power="pole"), node(2, 0.05, power="pole"), node(3, 0.3, power="tower"),
        {"type": "way", "id": 100, "nodes": [1, 2, 3], "tags": {"power": "minor_line"}},
        node(4, 0.4, man_made="chimney"), node(5, 0.41, man_made="mast", height="120"),
        node(6, 0.42, man_made="water_tower", height="31.5"),
        node(10, 0.5), node(11, 0.51), node(12, 0.51), node(13, 0.5),
        {"type": "way", "id": 101, "nodes": [10, 11, 12, 13, 10], "tags": {"man_made": "tower"}},
        node(20, 0.6), node(21, 0.64),
        {"type": "way", "id": 102, "nodes": [20, 21], "tags": {"natural": "tree_row"}},
        node(30, 0.7, natural="stone"), node(31, 0.71, natural="rock"),
        node(40, 0.8, railway="level_crossing"), node(41, 0.81, railway="level_crossing", **{"crossing:barrier": "half"}),
    ]
    elements[11]["lat"] = elements[12]["lat"] = 60.01  # the tower area's far side
    result = build_ways(elements)
    kinds = {}
    for obj in result.scenery_objects:
        kinds.setdefault(obj.kind, []).append(obj)
    assert len(kinds["power_pole"]) == 2 and len(kinds["power_tower"]) == 1
    assert [len(line.points_m) for line in kinds["power_line"]] == [3]
    assert [o.height_m for o in kinds["chimney"]] == [25.0]
    assert [o.height_m for o in kinds["mast"]] == [80.0]  # capped
    assert [o.height_m for o in kinds["water_tower"]] == [31.5]
    assert [(o.height_m, round(o.x, 1)) for o in kinds["tower"]] == [(30.0, 25505.0)]  # an area: once, at its centre
    assert len(kinds["boulder"]) == 2
    assert [o.kind for o in result.scenery_objects if o.kind.startswith("level_crossing")] == ["level_crossing", "level_crossing_barrier"]
    row_trees = [p for s in result.sceneries for p in s.trees if 25600 <= p[0] <= 25640]
    assert len(row_trees) >= 6  # 40 m at <= 8 m spacing


def test_bare_rock_is_a_grey_ground_fill():
    from theroadragetrip.map_style import SCENERY_COLORS
    from theroadragetrip.osm.constants import NATURAL_SCENERY_KINDS

    assert "bare_rock" in NATURAL_SCENERY_KINDS
    r, g, b = SCENERY_COLORS["bare_rock"]
    assert abs(r - g) < 12 and abs(g - b) < 12


def test_skyline_height_is_capped_at_80_m_with_a_default_per_kind():
    from theroadragetrip.osm.build import _skyline_height

    assert _skyline_height("chimney", {"height": "300"}) == 80.0
    assert _skyline_height("communications_tower", {"height": "81 m"}) == 80.0
    assert _skyline_height("water_tower", {"height": "42,5"}) == 42.5
    assert [_skyline_height(k, {}) for k in ("chimney", "mast", "tower", "water_tower")] == [25.0, 30.0, 30.0, 20.0]
    assert _skyline_height("mast", {"height": "tall"}) == 30.0  # not a number: the default


def test_man_made_area_is_drawn_once_at_its_centroid():
    corners = [(1, 0.0, 0.0), (2, 0.0, 0.02), (3, 0.01, 0.02), (4, 0.01, 0.0)]  # 20 x 10 m (fake transform: 0.001 deg = 1 m)
    elements = [{"type": "node", "id": nid, "lat": 60.0 + lat, "lon": 25.0 + lon} for nid, lat, lon in corners]
    elements.append({"type": "way", "id": 7, "nodes": [1, 2, 3, 4, 1], "tags": {"man_made": "water_tower", "height": "33"}})
    towers = [o for o in build_ways(elements).scenery_objects if o.kind == "water_tower"]
    assert [(round(o.x, 1), round(o.y, 1), o.height_m, o.id) for o in towers] == [(25010.0, 60005.0, 33.0, -7)]


def test_tree_row_trees_are_at_most_8_m_apart_through_the_tree_kinds_and_chunk_lod_list():
    from theroadragetrip import map_chunks

    elements = [{"type": "node", "id": 1, "lat": 60.0, "lon": 25.0}, {"type": "node", "id": 2, "lat": 60.0, "lon": 25.05},
                {"type": "node", "id": 3, "lat": 60.03, "lon": 25.05},
                {"type": "way", "id": 9, "nodes": [1, 2, 3], "tags": {"natural": "tree_row"}}]
    world = build_ways(elements)
    trees = sorted((p, kind) for s in world.sceneries for p, kind in zip(s.trees, s.tree_kinds))
    points = [p for p, _ in trees]
    assert points[0] == (25000.0, 60000.0) and (25050.0, 60030.0) in points  # both ends
    path = sorted(points, key=lambda p: (p[0], p[1]))
    assert max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(path, path[1:])) <= 8.0  # 50 m + 30 m legs, no gap over 8 m
    assert len(points) == len(set(points)) >= 80 // 8
    assert all(kind for _, kind in trees)  # each a regular tree kind (trees.py classify_tree_kind)
    streamed = [row for cid in map_chunks.ChunkIndex(world)._chunks for row in map_chunks.ChunkIndex(world).message(cid)["trees"]]
    assert len(streamed) == len(points)  # in the chunks' "trees" list: the client's existing tree LOD draws them


def test_level_crossing_takes_its_road_direction_and_barrier_or_crossbuck():
    elements = [{"type": "node", "id": 1, "lat": 60.0, "lon": 25.0}, {"type": "node", "id": 2, "lat": 60.1, "lon": 25.1},
                {"type": "way", "id": 5, "nodes": [1, 2], "tags": {"highway": "residential"}}]
    barriers = {10: "yes", 11: "full", 12: "half", 13: "no", 14: None}
    for nid, value in barriers.items():
        tags = {"railway": "level_crossing", **({"crossing:barrier": value} if value else {})}
        elements.append({"type": "node", "id": nid, "lat": 60.0 + (nid - 9) * 0.01, "lon": 25.0 + (nid - 9) * 0.01, "tags": tags})
    crossings = {o.id: o for o in build_ways(elements).scenery_objects if o.kind.startswith("level_crossing")}
    assert {nid: o.kind for nid, o in crossings.items()} == {10: "level_crossing_barrier", 11: "level_crossing_barrier",
                                                            12: "level_crossing_barrier", 13: "level_crossing", 14: "level_crossing"}
    for o in crossings.values():  # along the road (45 degrees), and left where it is mapped (on the road)
        assert abs(math.sin(o.direction_angle - math.pi / 4)) < 1e-6
        assert abs(o.x - 25000.0 - (o.id - 9) * 10) < 1e-6
