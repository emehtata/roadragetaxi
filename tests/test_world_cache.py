import struct

import pytest

from theroadragetrip.osm import Building, Place, build_ways, load_local_sample
from theroadragetrip.world_cache import (
    BinaryWorldCacheLoader,
    BinaryWorldCacheWriter,
    InvalidWorldCache,
    WorldCacheManager,
)


@pytest.fixture
def sample_world():
    return build_ways(load_local_sample())


def test_rwc_round_trip_preserves_game_data(tmp_path, sample_world):
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, sample_world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)
    assert len(loaded.ways) == len(sample_world.ways)
    assert len(loaded.buildings) == len(sample_world.buildings)
    assert len(loaded.parking_spaces) == len(sample_world.parking_spaces)
    assert loaded.ways[0].points_m == sample_world.ways[0].points_m
    assert loaded.ways[0].speed_limit_kmh == sample_world.ways[0].speed_limit_kmh


def test_rwc_rehydrates_building_place_associations(tmp_path, sample_world):
    place = Place(10.0, 10.0, "K-Market", "poi")
    building = Building(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        name="Shop",
        bbox=(0.0, 0.0, 20.0, 20.0),
        associated_places=[place],
    )
    sample_world.buildings.append(building)
    sample_world.places.append(place)
    path = tmp_path / "associated.rwc"

    BinaryWorldCacheWriter().write(path, sample_world, area_id="associated")
    loaded = BinaryWorldCacheLoader().load(path)

    loaded_building = next(item for item in loaded.buildings if item.name == building.name)
    assert loaded_building.associated_places
    assert loaded_building.associated_places[0] is next(
        item for item in loaded.places if item.name == place.name and item.kind == place.kind
    )


def test_rwc_rejects_corrupt_and_unsupported_files(tmp_path, sample_world):
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, sample_world)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(InvalidWorldCache):
        BinaryWorldCacheLoader().load(path)

    BinaryWorldCacheWriter().write(path, sample_world)
    raw = bytearray(path.read_bytes())
    raw[4:6] = struct.pack("<H", 99)
    path.write_bytes(raw)
    with pytest.raises(InvalidWorldCache, match="unsupported version"):
        BinaryWorldCacheLoader().load(path)


def test_stale_format_version_forces_a_rebuild_even_within_the_ttl(tmp_path, sample_world):
    """A fix to map-generation logic (e.g. the traffic-light phase-grouping
    safety fix) makes an already-written .rwc's *content* wrong even
    though its bytes are still well-formed. load_area()'s TTL check alone
    can't catch that - it only looks at wall-clock age (default 24h) - so
    a cache written minutes before a fix shipped would keep serving the
    old, buggy data for the rest of that day. FORMAT_VERSION exists
    exactly to be bumped for this: an old-version cache must be rebuilt
    on the very next load, regardless of how fresh its mtime is."""
    import struct

    from theroadragetrip.world_cache import FORMAT_VERSION

    calls = []
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: calls.append(bbox) or [],
        build_func=lambda elements: sample_world,
    )
    area_id = "stale-version-area"
    path = manager.path_for(area_id)
    manager.writer.write(path, sample_world, area_id=area_id)

    # Simulate a cache written by an older build: rewrite its format
    # version byte to one less than current, leaving mtime (and therefore
    # TTL freshness) untouched.
    raw = bytearray(path.read_bytes())
    raw[4:6] = struct.pack("<H", FORMAT_VERSION - 1)
    path.write_bytes(bytes(raw))

    loaded = manager.load_area(area_id, (1, 2, 3, 4))
    manager.close()

    assert loaded is sample_world
    assert calls == [(1, 2, 3, 4)], "a stale-format cache must trigger a rebuild, not be reused"


def test_world_cache_manager_hit_avoids_fetch(tmp_path, sample_world):
    calls = []
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: calls.append(bbox),
        build_func=lambda elements: sample_world,
    )
    area_id = "test-area"
    manager.writer.write(manager.path_for(area_id), sample_world, area_id=area_id)
    loaded = manager.load_area(area_id, (1, 2, 3, 4))
    manager.close()
    assert loaded.ways[0].points_m == sample_world.ways[0].points_m
    assert calls == []


def test_world_cache_manager_preload(tmp_path, sample_world):
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: [],
        build_func=lambda elements: sample_world,
    )
    future = manager.preload("preloaded", (1, 2, 3, 4))
    assert future.result().ways
    assert manager.path_for("preloaded").exists()
    manager.close()


def test_world_cache_manager_uses_covering_area_without_fetch(tmp_path, sample_world):
    calls = []
    sample_world.bounds = (0.0, 0.0, 100.0, 100.0)
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: calls.append(bbox),
        build_func=lambda elements: sample_world,
    )
    area_id = "1p000000_2p000000_100p000000_200p000000"
    manager.writer.write(manager.path_for(area_id), sample_world, area_id=area_id)

    loaded = manager.load_area("small-area", (10.0, 10.0, 90.0, 90.0))

    assert loaded.bounds == sample_world.bounds
    assert calls == []
    manager.close()


def test_region_preload_does_not_use_covering_legacy_area(tmp_path, sample_world):
    calls = []
    sample_world.bounds = (0.0, 0.0, 100.0, 100.0)
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox, **kwargs: calls.append(bbox) or [],
        build_func=lambda elements: sample_world,
    )
    legacy_id = "1p000000_2p000000_100p000000_200p000000"
    manager.writer.write(manager.path_for(legacy_id), sample_world, area_id=legacy_id)

    loaded = manager.preload_region((10.0, 10.0, 90.0, 90.0)).result()

    assert loaded.bounds == sample_world.bounds
    assert calls == [(10.0, 10.0, 90.0, 90.0)]
    manager.close()


def test_world_cache_manager_accepts_nearly_identical_tile_bbox(tmp_path, sample_world):
    calls = []
    sample_world.bounds = (0.0, 0.0, 100.0, 100.0)
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox: calls.append(bbox),
        build_func=lambda elements: sample_world,
    )
    area_id = "0p000000_0p000000_100p000000_100p000000"
    manager.writer.write(manager.path_for(area_id), sample_world, area_id=area_id)

    loaded = manager.load_area("nearby-tile", (-0.00005, -0.00005, 99.99995, 99.99995))

    assert loaded.bounds == sample_world.bounds
    assert calls == []
    manager.close()


def test_world_cache_manager_force_refresh_passes_fetch_flag(tmp_path, sample_world):
    calls = []
    manager = WorldCacheManager(
        tmp_path,
        fetch_func=lambda bbox, **kwargs: calls.append(kwargs) or [],
        build_func=lambda elements: sample_world,
    )

    manager.load_area("forced", (1, 2, 3, 4), force_refresh=True)
    manager.close()

    assert calls == [{"force_refresh": True}]


def test_clear_world_cache_removes_entries(tmp_path):
    from theroadragetrip.world_cache import clear_world_cache

    (tmp_path / "area.rwc").write_bytes(b"cache")
    (tmp_path / "nested").mkdir()

    assert clear_world_cache(tmp_path) == 2
    assert list(tmp_path.iterdir()) == []
