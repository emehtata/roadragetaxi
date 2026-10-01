"""OSM level=* / indoor=* import (garage-02.md): level=* becomes map_level
only when it is one clean integer, and layer=* never feeds into it."""
import pytest

from theroadragetrip.map_level import visible_on_level
from theroadragetrip.osm import AutoFetchManager, build_ways
from theroadragetrip.osm.build import parse_map_level
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


@pytest.mark.parametrize("value, expected", [
    ("-1", -1), ("-2", -2), ("0", 0), ("2", 2), (" 1 ", 1), ("+1", 1),
    ("-2;-1", None), ("-1;0", None), ("0-2", None), ("1.5", None), ("foo", None),
    ("", None), (None, None), ("²", None), ("-", None),
])
def test_parse_map_level(value, expected):
    assert parse_map_level(value) == expected


def _road(tags, highway="footway"):
    elements = [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.0, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": highway, **tags}},
    ]
    ways = build_ways(elements).ways
    return ways[0] if ways else None


@pytest.mark.parametrize("tags, map_level, layer", [
    ({"level": "-1"}, -1, 0),  # no containment test: OSM says so
    ({"level": "2"}, 2, 0),
    ({"level": "0"}, 0, 0),
    ({}, None, 0),
    ({"layer": "-1", "tunnel": "yes"}, None, -1),  # tunnel stays surface world
    ({"layer": "1", "bridge": "yes"}, None, 1),
    ({"layer": "-1", "level": "-2"}, -2, -1),
    ({"level": "foo"}, None, 0),
])
def test_road_level_and_layer_stay_separate(tags, map_level, layer):
    way = _road(tags)
    assert (way.map_level, way.layer) == (map_level, layer)
    assert way.level == tags.get("level")


def _build(tags, highway="service"):
    return build_ways([
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.0, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": highway, **tags}},
    ])


@pytest.mark.parametrize("tags, map_level, layer", [
    ({"level": "-1"}, -1, 0),
    ({"level": "-2", "covered": "yes"}, -2, 0),
    ({"level": "-1", "tunnel": "yes"}, -1, -1),
    ({"level": "-1", "parking": "underground"}, -1, 0),
    ({"level": "-2", "layer": "-1", "location": "underground"}, -2, -1),
])
def test_underground_road_with_explicit_level_survives_off_the_surface_network(tags, map_level, layer):
    """garage-03.md: kept as level-aware data in level_ways, never in the
    surface road network (ways) that drawing, traffic and routing read."""
    for highway in ("service", "track"):
        world = _build(tags, highway)
        assert world.ways == []
        (way,) = world.level_ways
        assert (way.map_level, way.layer, way.osm_id) == (map_level, layer, 10)


@pytest.mark.parametrize("tags", [
    {"covered": "yes"}, {"tunnel": "yes"}, {"layer": "-1", "location": "underground"},
    {"parking": "underground"}, {"level": "-1;-2", "covered": "yes"}, {"level": "-0.5"},
])
def test_underground_road_without_a_clean_level_is_still_dropped(tags):
    world = _build(tags)
    assert world.ways == [] and world.level_ways == []


def test_surface_roads_and_parking_aisles_are_unchanged():
    assert _build({"level": "1"}).ways[0].map_level == 1  # not underground: a normal road, as before
    assert _build({}).level_ways == []
    aisle = _build({"service": "parking_aisle", "level": "-1", "location": "underground"})
    assert aisle.level_ways == [] and aisle.ways[0].map_level == -1  # pre-existing exemption


def test_level_ways_survive_cache_and_streaming(tmp_path):
    world = _build({"level": "-1", "covered": "yes"})
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)
    assert loaded.ways == [] and [w.map_level for w in loaded.level_ways] == [-1]

    ways, level_ways = [], []
    manager = AutoFetchManager(ways, (0.0, 0.0, 1.0, 1.0), transformer=None, level_ways=level_ways)
    tiles = set(manager._item_tiles(loaded.level_ways[0]))
    manager.active_tiles = set(tiles)
    manager._completed_tile_batches.append([(tuple(tiles), tuple(tiles), loaded)])
    while manager._completed_tile_batches or manager._merge_queue:
        manager.integrate_completed_tiles(budget_s=0.004)
    assert ways == [] and [w.map_level for w in level_ways] == [-1]


def test_multi_level_keeps_the_raw_tag_and_stays_surface():
    way = _road({"level": "-2;-1"})
    assert way.map_level is None and way.level == "-2;-1"
    assert visible_on_level(way, 0)  # unchanged rendering: still surface world


@pytest.mark.parametrize("indoor", ["yes", "parking", "corridor"])
def test_indoor_is_kept_raw(indoor):
    assert _road({"indoor": indoor, "level": "-1"}).indoor == indoor
    assert _road({}).indoor is None


def test_building_levels_tag_is_not_a_map_level():
    nodes = [{"type": "node", "id": i, "lat": 65.0 + dy, "lon": 25.0 + dx}
             for i, (dx, dy) in enumerate([(0, 0), (0.001, 0), (0.001, 0.001), (0, 0.001)], start=1)]
    building = {"type": "way", "id": 20, "nodes": [1, 2, 3, 4, 1],
                "tags": {"building": "yes", "building:levels": "3", "indoor": "yes"}}
    (b,) = build_ways(nodes + [building]).buildings
    assert b.map_level is None and b.level is None and b.indoor == "yes" and b.levels == 3


def test_level_metadata_survives_cache_and_streaming(tmp_path):
    world = build_ways([
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.0, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2],
         "tags": {"highway": "footway", "level": "-1", "indoor": "corridor"}},
    ])
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)
    (way,) = loaded.ways
    assert (way.map_level, way.level, way.indoor) == (-1, "-1", "corridor")

    ways = []
    manager = AutoFetchManager(ways, (0.0, 0.0, 1.0, 1.0), transformer=None)
    tiles = set(manager._item_tiles(way))
    manager.active_tiles = set(tiles)
    manager._completed_tile_batches.append([(tuple(tiles), tuple(tiles), loaded)])
    while manager._completed_tile_batches or manager._merge_queue:
        manager.integrate_completed_tiles(budget_s=0.004)
    assert [(w.map_level, w.indoor) for w in ways] == [(-1, "corridor")]
