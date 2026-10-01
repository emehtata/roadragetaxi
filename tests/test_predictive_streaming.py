"""Predictive tile lookahead, core-first request priority and the soft
streaming boundary (osm-stream-00.md)."""
import inspect

import theroadragetrip.main as main_module
from theroadragetrip.osm import AutoFetchManager
from theroadragetrip.osm import autofetch as autofetch_module
from theroadragetrip.tile_streaming import TileCoord, active_tiles, lookahead_tiles


def _manager():
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None, cooldown_s=0.0)
    manager.initialize_player_tile(500.0, 500.0)
    return manager


def _no_thread(monkeypatch, requests):
    class _Thread:
        def __init__(self, target, args, daemon):
            requests.append(args)

        def start(self):
            pass
    monkeypatch.setattr(autofetch_module.threading, "Thread", _Thread)


def test_lookahead_grows_with_speed_and_follows_direction():
    assert lookahead_tiles(500, 500, 0, 0, 90, 3) == frozenset()
    assert lookahead_tiles(500, 500, 5, 0, 90, 3) == frozenset()  # slow: 3x3 is enough
    assert lookahead_tiles(500, 500, 15, 0, 90, 3) == {TileCoord(2, 0)}
    assert lookahead_tiles(500, 500, 40, 0, 90, 3) == {TileCoord(2, 0), TileCoord(3, 0), TileCoord(4, 0)}
    assert lookahead_tiles(500, 500, 0, -40, 90, 3) == {TileCoord(0, -2), TileCoord(0, -3), TileCoord(0, -4)}


def test_core_tiles_are_requested_before_lookahead(monkeypatch):
    requests = []
    _no_thread(monkeypatch, requests)
    manager = _manager()
    manager.loaded_tiles = set()

    assert manager.start_tile_streaming(500.0, 500.0, 40.0, 0.0)
    missing, _ = requests[0]
    assert set(missing) == set(active_tiles(TileCoord(0, 0)))

    manager.loaded_tiles = set(missing)
    manager.pending_tiles = set()
    manager.is_fetching = False
    assert manager.start_tile_streaming(500.0, 500.0, 40.0, 0.0)
    missing, request = requests[1]
    assert set(missing) == set(request) == {TileCoord(2, 0), TileCoord(3, 0), TileCoord(4, 0)}


def test_lookahead_tiles_stay_active_while_steering_within_a_tile():
    manager = _manager()
    manager.update_player_tile(500.0, 500.0, 40.0, 0.0)
    manager.update_player_tile(500.0, 500.0, 0.0, 40.0)  # turned north, same tile
    assert {TileCoord(2, 0), TileCoord(0, 2)} <= manager.active_tiles


def test_soft_boundary_caps_speed_only_near_unloaded_tiles():
    manager = _manager()
    manager.soft_boundary_enabled = True
    manager.loaded_tiles = {TileCoord(0, 0), TileCoord(1, 0)}
    assert manager.streaming_speed_cap_mps(500.0, 500.0, 30.0, 0.0) is None  # 600m ahead all loaded
    far = manager.streaming_speed_cap_mps(1500.0, 500.0, 30.0, 0.0)
    near = manager.streaming_speed_cap_mps(1950.0, 500.0, 30.0, 0.0)
    assert far is not None and near is not None and near < far
    assert near >= autofetch_module.SOFT_BOUNDARY_MIN_SPEED_MPS
    assert manager.streaming_speed_cap_mps(1950.0, 500.0, -30.0, 0.0) is None  # driving away
    manager.loaded_tiles.add(TileCoord(2, 0))
    manager.loaded_tiles.add(TileCoord(3, 0))
    assert manager.streaming_speed_cap_mps(1950.0, 500.0, 30.0, 0.0) is None  # data arrived


def test_soft_boundary_off_without_runtime_streaming():
    manager = _manager()
    manager.loaded_tiles = set()
    assert manager.streaming_speed_cap_mps(500.0, 500.0, 30.0, 0.0) is None


def test_runtime_streaming_never_blocks_behind_a_loading_screen():
    assert not hasattr(main_module, "_wait_for_active_tile_fetch")
    assert "_wait_for_active_tile_fetch" not in inspect.getsource(main_module)
