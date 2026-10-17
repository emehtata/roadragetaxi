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
               "tags": {"building": "commercial", "leisure": "stadium", "name": "Heinäpään jalkapallostadion"}}
    hall = {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1],
            "tags": {"building": "air-supported", "leisure": "sports_centre", "name": "Oulun jalkapallohalli"}}
    world = build_ways(nodes + [stadium, hall])
    assert [b.name for b in world.buildings] == ["Oulun jalkapallohalli"]  # the dome is a building
    assert [s.kind for s in world.sceneries if s.name == "Heinäpään jalkapallostadion"] == ["stadium"]


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
            "tags": {"building": "yes", "leisure": "stadium", "sport": "ice_hockey", "name": "Helsingin jäähalli"}}
    assert [b.name for b in build_ways(nodes + [hall]).buildings] == ["Helsingin jäähalli"]
