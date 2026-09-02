import sys
import types

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
sys.modules["pyproj"] = fake_pyproj

from theroadragetrip import build_ways


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


def test_build_ways_generates_entrance_for_building_without_node():
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

    assert len(result.buildings[0].entrances) == 1
    assert result.buildings[0].entrances[0] == (25.0 * 1000.0, 60.005 * 1000.0)


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


def test_build_ways_parses_public_transport_platform_as_bus_stop():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0, "tags": {"public_transport": "platform"}},
    ]

    result = build_ways(elements)

    assert len(result.bus_stops) == 1


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
