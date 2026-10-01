"""Level connectors (garage-07.md): amenity=parking_entrance nodes kept as
data exactly as OSM states them - no invented levels, garages or roads."""
import pytest

from theroadragetrip.osm import AutoFetchManager, build_ways
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter

SQUARE = [(0, 0), (0.001, 0), (0.001, 0.0005), (0, 0.0005)]


def _world(entrance_tags, garage=True, extra=()):
    elements = [{"type": "node", "id": i + 1, "lat": 65.0 + dy, "lon": 25.0 + dx} for i, (dx, dy) in enumerate(SQUARE)]
    elements += [
        {"type": "node", "id": 10, "lat": 65.0, "lon": 25.0005, "tags": {"amenity": "parking_entrance", **entrance_tags}},
        {"type": "node", "id": 11, "lat": 64.999, "lon": 25.0005},
        {"type": "node", "id": 12, "lat": 65.0003, "lon": 25.0005},
        # Outside driveway and covered inside road, both through the entrance.
        {"type": "way", "id": 20, "nodes": [11, 10], "tags": {"highway": "service", "service": "driveway"}},
        {"type": "way", "id": 21, "nodes": [10, 12], "tags": {"highway": "service", "covered": "yes", "level": "0;-1"}},
    ]
    if garage:  # the entrance sits on the garage outline: a shared node
        elements.append({"type": "way", "id": 30, "nodes": [1, 10, 2, 3, 4, 1],
                         "tags": {"amenity": "parking", "parking": "underground"}})
    return build_ways(elements + list(extra))


def test_entrance_keeps_identity_position_and_topology():
    world = _world({"parking": "underground"})
    (connector,) = world.level_connectors
    assert (connector.osm_type, connector.osm_id, connector.connector_type) == ("node", 10, "parking_entrance")
    assert connector.parking == "underground"
    assert connector.garage_osm_id == 30
    assert connector.road_osm_ids == (20, 21)
    assert world.parking_garages[0].osm_id == 30


@pytest.mark.parametrize("level, map_level", [
    ("-1", -1), ("0", 0), ("0;1", None), ("-1;0", None), ("0-1", None), (None, None),
])
def test_level_is_kept_as_tagged_never_guessed(level, map_level):
    tags = {"level": level} if level is not None else {}
    (connector,) = _world(tags).level_connectors
    assert connector.map_level == map_level and connector.level == level  # None = unknown, not surface


def test_layer_is_not_a_level():
    (connector,) = _world({"layer": "-1"}).level_connectors
    assert connector.map_level is None


def test_no_garage_without_a_shared_node():
    """An entrance inside/near a garage outline it isn't part of gets no
    garage and no level from it."""
    inside = [{"type": "way", "id": 31, "nodes": [1, 2, 3, 4, 1],
               "tags": {"amenity": "parking", "parking": "underground", "parking:levels": "2"}}]
    (connector,) = _world({}, garage=False, extra=inside).level_connectors
    assert connector.garage_osm_id is None and connector.map_level is None


def test_connectors_are_never_roads_or_routes():
    world = _world({"parking": "underground"})
    assert {w.osm_id for w in world.ways} | {w.osm_id for w in world.level_ways} <= {20, 21}


def test_cache_round_trip_and_tile_lifecycle(tmp_path):
    world = _world({"parking": "underground", "level": "-1"})
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)
    assert loaded.level_connectors == world.level_connectors

    connectors = []
    manager = AutoFetchManager([], (0.0, 0.0, 1.0, 1.0), transformer=None, level_connectors=connectors)
    tiles = set(manager._item_tiles(loaded.level_connectors[0]))
    manager.active_tiles = set(tiles)
    for _ in range(2):  # the same tile reported twice: deduplicated by OSM id
        manager._completed_tile_batches.append([(tuple(tiles), tuple(tiles), loaded)])
    while manager._completed_tile_batches or manager._merge_queue:
        manager.integrate_completed_tiles(budget_s=0.004)
    assert [c.osm_id for c in connectors] == [10]
    manager._unload_tiles(tiles)
    assert connectors == []
