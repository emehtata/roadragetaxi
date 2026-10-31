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


def test_a_moved_home_cancels_the_old_preparation_and_prepares_the_new_one_once():
    from types import SimpleNamespace

    from theroadragetrip.server import SimulationServer

    prepared = []

    def prepare_window(x, y):
        prepared.append((x, y))
        return Future()

    streamer = SimpleNamespace(status=lambda: "", manager=SimpleNamespace(prepare_window=prepare_window))
    server = SimpleNamespace(_map_streamer=streamer, _home=(100.0, 200.0, 0.0), _prepared_home=None, _home_preparation=None)
    SimulationServer._prepare_home_map(server)
    SimulationServer._prepare_home_map(server)  # every tick: still once
    first = server._home_preparation
    server._home = (900.0, 200.0, 0.0)  # the player chose a new home
    SimulationServer._prepare_home_map(server)
    assert prepared == [(100.0, 200.0), (900.0, 200.0)] and first.cancelled()


def test_changed_chunks_are_resent_nearest_the_player_first():
    from types import SimpleNamespace

    from theroadragetrip.server import SimulationServer

    class Connection:
        def __init__(self):
            self.sent = []

        def send(self, data):
            self.sent.append(data)

    connection = Connection()
    index = SimpleNamespace(encoded=lambda cid: cid, is_encoded=lambda cid: True)
    server = SimpleNamespace(
        _map_growth=[([], index, {"9_0", "1_0", "4_0"}, None, None, 0.0, True, {"tile"})], _chunks_index=None,
        world=SimpleNamespace(street_light_points=[]), _map_streamer=SimpleNamespace(hold=True), _on_foot=False,
        car=SimpleNamespace(x=250.0, y=250.0), _clients_lock=threading.Lock(), _indexed_tiles=set(),
        _client_chunks={connection: ({"9_0", "1_0", "4_0", "2_0"}, (0, 0))},
    )
    SimulationServer._apply_map_growth(server)
    assert connection.sent == ["1_0", "4_0", "9_0"]  # no unload messages: the client swaps each in place
    assert server._map_streamer.hold is False and server._client_chunks[connection] == ({"9_0", "1_0", "4_0", "2_0"}, None)
    assert server._indexed_tiles == {"tile"}  # the final pass: its tiles' chunks can be sent now


def test_chunks_beyond_the_players_own_wait_until_the_index_has_their_tile():
    from types import SimpleNamespace

    from theroadragetrip.server import SimulationServer
    from theroadragetrip.tile_streaming import TileCoord

    sent = []

    class Connection:
        def send(self, data):
            sent.append(data)

    connection = Connection()
    server = SimpleNamespace(
        _clients_lock=threading.Lock(), _clients=[connection], _client_chunks={connection: (set(), None)},
        _on_foot=False, car=SimpleNamespace(x=250.0, y=250.0), _chunks_index=SimpleNamespace(encoded=lambda cid: cid, is_encoded=lambda cid: True),
        _indexed_tiles={TileCoord(0, 0), TileCoord(1, 0)},
    )
    SimulationServer._stream_map_chunks(server)
    own = {f"{x}_{y}" for x in (-1, 0, 1) for y in (-1, 0, 1)}  # the player's own 3x3, whatever is indexed
    assert set(sent) == own | {"2_0", "3_0", "2_1", "3_1"}  # beyond it, only tile (1, 0)'s chunks
    sent.clear()
    server._indexed_tiles.add(TileCoord(0, 1))
    server._client_chunks[connection] = (server._client_chunks[connection][0], None)  # a growth replans
    SimulationServer._stream_map_chunks(server)
    assert set(sent) == {"0_2", "1_2", "0_3", "1_3"}


def test_a_changed_far_chunk_not_yet_encoded_waits_for_the_streaming_budget():
    import threading
    from types import SimpleNamespace

    from theroadragetrip.server import SimulationServer

    sent = []

    class Connection:
        send = staticmethod(sent.append)

    connection = Connection()
    index = SimpleNamespace(encoded=lambda cid: cid, is_encoded=lambda cid: False)
    server = SimpleNamespace(
        _map_growth=[([], index, {"1_0", "4_0"}, None, None, 0.0, True, {"tile"})], _chunks_index=None,
        world=SimpleNamespace(street_light_points=[]), _map_streamer=SimpleNamespace(hold=True), _on_foot=False,
        car=SimpleNamespace(x=250.0, y=250.0), _clients_lock=threading.Lock(), _indexed_tiles=set(),
        _client_chunks={connection: ({"1_0", "4_0"}, (0, 0))},
    )
    SimulationServer._apply_map_growth(server)
    assert sent == ["1_0"]  # the player's own neighbour at once
    assert server._client_chunks[connection] == ({"1_0"}, None)  # 4_0 is streamed again, within budget
