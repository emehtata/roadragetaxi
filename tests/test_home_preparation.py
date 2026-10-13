"""Background preparation of the Home destination's map (map-loading-01)."""
import json
import threading
import time
from concurrent.futures import Future

import pytest

from theroadragetrip.osm import MapData, build_ways, load_local_sample
from theroadragetrip.osm.autofetch import AutoFetchManager
from theroadragetrip.world_cache import WorldCacheManager


@pytest.fixture
def sample_world():
    return build_ways(load_local_sample())


def test_prepare_builds_an_uncached_area_once_shares_it_with_a_jump_and_keeps_nothing(tmp_path, sample_world):
    release, calls = threading.Event(), []

    def slow_fetch(bbox, **kwargs):
        calls.append(bbox)
        release.wait(5.0)
        return []

    manager = WorldCacheManager(tmp_path, fetch_func=slow_fetch, build_func=lambda elements: sample_world)
    bbox = (65.0, 25.4, 65.03, 25.47)
    prepared = manager.prepare_region(bbox)
    assert prepared is not None
    jumped = manager.preload_region(bbox)  # the player presses H while it still runs
    assert jumped is prepared
    release.set()
    assert jumped.result(5.0) is sample_world and calls == [bbox]  # one build for both
    deadline = time.time() + 2.0
    while manager._futures and time.time() < deadline:
        time.sleep(0.01)
    assert manager._futures == {}  # the prepared world is in the cache file, not kept in memory
    assert manager.prepare_region(bbox) is None  # cached now: preparing again costs nothing
    manager.close()


def test_a_foreground_load_does_not_wait_behind_a_preparation(tmp_path, sample_world):
    release = threading.Event()

    def fetch(bbox, **kwargs):
        if bbox[0] == 64.0:  # the preparation's area: blocks until released
            release.wait(5.0)
        return []

    manager = WorldCacheManager(tmp_path, fetch_func=fetch, build_func=lambda elements: sample_world)
    manager.prepare_region((64.0, 25.0, 64.03, 25.07))
    assert manager.preload_region((65.0, 25.4, 65.03, 25.47)).result(2.0) is sample_world
    release.set()
    manager.close()


def test_prepare_window_asks_for_exactly_the_region_a_jump_there_requests():
    class Transformer:
        def transform(self, x, y):
            return x, y

    class Cache:
        def __init__(self):
            self.prepared, self.loaded = [], []

        def prepare_region(self, bbox):
            self.prepared.append(bbox)
            return Future()

        def preload_region(self, bbox, **kwargs):
            self.loaded.append(bbox)
            future = Future()
            future.set_result(MapData([], [], [], [], [], (0.0, 0.0, 1.0, 1.0)))
            return future

    cache = Cache()
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), Transformer(), world_cache_manager=cache)
    manager.initialize_player_tile(500.0, 500.0)
    assert manager.prepare_window(4500.0, -7500.0) is not None
    manager.start_tile_streaming(4500.0, -7500.0)  # the jump
    deadline = time.time() + 2.0
    while manager.is_fetching and time.time() < deadline:
        time.sleep(0.01)
    assert cache.prepared == cache.loaded  # same bbox: the jump's load is the prepared cache file
    manager.loaded_tiles.update(manager.active_tiles)
    assert manager.prepare_window(4500.0, -7500.0) is None  # loaded already: nothing to prepare


def test_an_interrupted_osm_cache_save_leaves_no_file(tmp_path, monkeypatch):
    from theroadragetrip import osm
    from theroadragetrip.osm import cache

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path))

    dump = json.dump

    def broken_dump(data, f):
        f.write('{"version": ')  # half written...
        raise OSError("disk full")

    monkeypatch.setattr(cache.json, "dump", broken_dump)
    cache.save_osm_cache((65.0, 25.4, 65.03, 25.47), [{"type": "node"}])
    assert list(tmp_path.iterdir()) == []  # neither a truncated cache nor a temporary file
    monkeypatch.setattr(cache.json, "dump", dump)
    cache.save_osm_cache((65.0, 25.4, 65.03, 25.47), [{"type": "node"}])
    assert cache.load_osm_cache((65.0, 25.4, 65.03, 25.47)) == [{"type": "node"}]
