"""Parking garage data layer (garage-00.md): classification, levels,
metadata, geometry, OSM identity, world cache round trip and streaming."""
import pytest

from theroadragetrip.osm import AutoFetchManager, build_ways
from theroadragetrip.osm.parking import (
    PARKING_MULTI_STOREY,
    PARKING_SURFACE,
    PARKING_UNDERGROUND,
    PARKING_UNKNOWN,
    garage_levels,
    make_parking_garage,
    parking_facility_type,
)
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter, WorldCacheManager

SQUARE = [(0, 0), (0.001, 0), (0.001, 0.0005), (0, 0.0005)]


def _square(first_id=1):
    return [
        {"type": "node", "id": first_id + i, "lat": 65.0 + dy, "lon": 25.0 + dx}
        for i, (dx, dy) in enumerate(SQUARE)
    ]


def _area(way_id, tags, first_id=1):
    ids = [first_id + i for i in range(4)]
    return {"type": "way", "id": way_id, "nodes": ids + ids[:1], "tags": tags}


@pytest.mark.parametrize("tags, expected", [
    ({"amenity": "parking", "parking": "underground"}, PARKING_UNDERGROUND),
    ({"amenity": "parking", "parking": "multi-storey"}, PARKING_MULTI_STOREY),
    ({"amenity": "parking", "parking": "surface"}, PARKING_SURFACE),
    ({"amenity": "parking"}, PARKING_SURFACE),  # OSM default
    ({"amenity": "parking", "parking": "rooftop"}, PARKING_SURFACE),
    ({"building": "parking"}, PARKING_MULTI_STOREY),
    ({"building": "parking", "parking": "underground"}, PARKING_UNDERGROUND),
    ({"amenity": "parking", "parking": "something_new"}, PARKING_UNKNOWN),
    ({"building": "yes", "parking": "underground"}, None),  # not a parking element at all
])
def test_classification(tags, expected):
    assert parking_facility_type(tags) == expected


@pytest.mark.parametrize("tags, garage_type, expected", [
    ({"parking:levels": "2"}, PARKING_UNDERGROUND, ((-2, -1), "parking:levels")),
    ({"building:levels:underground": "3"}, PARKING_UNDERGROUND, ((-3, -2, -1), "building:levels:underground")),
    ({}, PARKING_UNDERGROUND, ((), "")),  # unknown stays unknown, no guessed -1
    ({"parking:levels": "3"}, PARKING_MULTI_STOREY, ((0, 1, 2), "parking:levels")),
    ({"building:levels": "5", "building:levels:underground": "1"}, PARKING_MULTI_STOREY,
     ((-1, 0, 1, 2, 3, 4), "building:levels")),
    ({"building:levels": "many"}, PARKING_MULTI_STOREY, ((), "")),
])
def test_levels(tags, garage_type, expected):
    assert garage_levels(tags, garage_type) == expected


@pytest.mark.parametrize("value", ["inf", "Infinity", "1e309"])
def test_non_finite_counts_are_ignored(value):
    assert garage_levels({"parking:levels": value}, PARKING_MULTI_STOREY) == ((), "")
    garage = make_parking_garage(
        {"building": "parking", "capacity": value}, "way", 1, [(0.0, 0.0)],
    )
    assert garage is not None and garage.capacity is None


def test_garage_way_keeps_metadata_identity_and_geometry():
    tags = {
        "amenity": "parking", "parking": "multi-storey", "building:levels": "5",
        "building:levels:underground": "1", "capacity": "420", "name": "P-Torikatu",
        "operator": "Oulun Pysäköinti", "access": "customers", "fee": "yes", "maxheight": "2.1",
    }
    world = build_ways(_square() + [_area(100, tags)])
    (garage,) = world.parking_garages
    assert (garage.osm_type, garage.osm_id, garage.garage_type) == ("way", 100, PARKING_MULTI_STOREY)
    assert (garage.building_levels, garage.underground_levels, garage.parking_levels) == (5, 1, None)
    assert garage.capacity == 420 and garage.name == "P-Torikatu" and garage.maxheight == "2.1"
    assert garage.operator == "Oulun Pysäköinti" and garage.access == "customers" and garage.fee == "yes"
    assert garage.maxweight is None and garage.opening_hours is None
    assert len(garage.points_m) == 5
    minx, miny, maxx, maxy = garage.bbox
    assert minx < garage.center_m[0] < maxx and miny < garage.center_m[1] < maxy
    assert garage.center_m == pytest.approx(((minx + maxx) / 2, (miny + maxy) / 2), abs=1.0)


def test_surface_parking_is_not_a_garage_and_still_draws_as_a_lot():
    world = build_ways(_square() + [_area(100, {"amenity": "parking"})])
    assert world.parking_garages == []
    assert [s.kind for s in world.sceneries] == ["parking"]


def test_garage_node_and_relation_and_malformed_geometry():
    elements = _square() + _square(first_id=11) + [
        {"type": "node", "id": 50, "lat": 65.0, "lon": 25.01,
         "tags": {"amenity": "parking", "parking": "underground"}},
        {"type": "way", "id": 200, "nodes": [11, 12, 13, 14, 11], "tags": {}},
        {"type": "relation", "id": 300, "members": [{"type": "way", "ref": 200, "role": "outer"}],
         "tags": {"type": "multipolygon", "amenity": "parking", "parking": "underground"}},
        # Malformed: an open 2-node way, and a way whose nodes are missing.
        {"type": "way", "id": 400, "nodes": [1, 2], "tags": {"amenity": "parking", "parking": "underground"}},
        {"type": "way", "id": 401, "nodes": [98, 99, 97, 98], "tags": {"building": "parking"}},
    ]
    garages = {(g.osm_type, g.osm_id): g for g in build_ways(elements).parking_garages}
    assert set(garages) == {("node", 50), ("relation", 300)}
    assert len(garages[("node", 50)].points_m) == 1
    assert len(garages[("relation", 300)].points_m) >= 4


def test_garages_survive_the_world_cache_offline(tmp_path):
    tags = {"amenity": "parking", "parking": "underground", "parking:levels": "2", "capacity": "80"}
    world = build_ways(_square() + [_area(100, tags)])
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    (loaded,) = BinaryWorldCacheLoader().load(path).parking_garages
    assert loaded == world.parking_garages[0]
    assert loaded.levels == (-2, -1)

    # The manager serves it from disk without any fetch (no network).
    def no_network(*args, **kwargs):
        raise AssertionError("fetched despite a cached world")
    manager = WorldCacheManager(cache_dir=tmp_path, fetch_func=no_network)
    BinaryWorldCacheWriter().write(manager.path_for("area"), world, area_id="area")
    assert len(manager.load_area("area").parking_garages) == 1


def test_streamed_tile_garages_merge_into_the_runtime_world():
    tags = {"amenity": "parking", "parking": "underground"}
    tile_world = build_ways(_square() + [_area(100, tags)])
    garages = []
    manager = AutoFetchManager([], (0.0, 0.0, 1.0, 1.0), transformer=None, parking_garages=garages)
    tiles = set(manager._item_tiles(tile_world.parking_garages[0]))
    manager.active_tiles = set(tiles)
    manager._completed_tile_batches.append([(tuple(tiles), tuple(tiles), tile_world)])
    while manager._completed_tile_batches or manager._merge_queue:
        manager.integrate_completed_tiles(budget_s=0.004)
    assert [g.osm_id for g in garages] == [100]
    manager._unload_tiles(tiles)
    assert garages == []
