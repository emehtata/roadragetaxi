import struct

import pytest

from theroadragetrip.osm import build_ways, load_local_sample
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
