"""Predictive tile lookahead, core-first request priority and the soft
streaming boundary (osm-stream-00.md)."""

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


def test_lookahead_traverses_shallow_angle_and_diagonal_tiles():
    assert lookahead_tiles(500, 500, 40, 10, 90, 3) == {
        TileCoord(2, 0), TileCoord(2, 1), TileCoord(3, 1),
    }
    assert lookahead_tiles(500, 500, 40, 40, 90, 3) == {
        TileCoord(2, 2), TileCoord(3, 3),
    }


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


def test_soft_boundary_never_caps_for_a_pending_tile_ahead():
    manager = _manager()
    manager.soft_boundary_enabled = True
    manager.loaded_tiles = {TileCoord(0, 0), TileCoord(1, 0)}
    manager.is_fetching = True  # tile (2, 0) is in flight
    assert manager.streaming_speed_cap_mps(500.0, 500.0, 30.0, 0.0) is None
    assert manager.streaming_speed_cap_mps(1500.0, 500.0, 30.0, 0.0) is None
    assert manager.streaming_speed_cap_mps(1950.0, 500.0, 30.0, 0.0) is None


def test_soft_boundary_hard_limit_only_without_data_under_the_car():
    manager = _manager()
    manager.soft_boundary_enabled = True
    manager.loaded_tiles = {TileCoord(0, 0)}
    assert manager.streaming_speed_cap_mps(1500.0, 500.0, 30.0, 0.0) == (
        autofetch_module.SOFT_BOUNDARY_MIN_SPEED_MPS)
    manager.loaded_tiles.add(TileCoord(1, 0))
    assert manager.streaming_speed_cap_mps(1500.0, 500.0, 30.0, 0.0) is None


def test_soft_boundary_off_without_runtime_streaming():
    manager = _manager()
    manager.loaded_tiles = set()
    assert manager.streaming_speed_cap_mps(500.0, 500.0, 30.0, 0.0) is None




def test_tick_distribution_reports_tail_and_overruns():
    from theroadragetrip.server import tick_distribution
    text = tick_distribution([0.01] * 98 + [0.04, 0.2], 1 / 30)
    assert "max 200.0" in text and "2/100 over 33.3" in text


def test_hard_limit_ticks_counted():
    manager = _manager()
    manager.soft_boundary_enabled = True
    manager.loaded_tiles = set()
    manager.streaming_speed_cap_mps(500.0, 500.0, 30.0, 0.0)
    assert manager.hard_limit_ticks == 1



def test_collector_is_off_in_a_sync_and_unfreezes_for_the_idle_full_pass(monkeypatch):
    import gc

    from theroadragetrip import performance

    calls = []
    monkeypatch.setattr(gc, "freeze", lambda: calls.append("freeze"))
    monkeypatch.setattr(gc, "unfreeze", lambda: calls.append("unfreeze"))
    monkeypatch.setattr(gc, "collect", lambda generation=2: calls.append(generation))
    schedule = performance.CollectorSchedule()
    try:
        schedule.begin_sync()
        assert not gc.isenabled()
        schedule.after_tick(idle=True, now=100.0)  # never during a sync
        schedule.end_sync()
        assert gc.isenabled() and calls == ["freeze"]
        schedule.after_tick(idle=False, now=100.0)  # someone is driving: no full pass
        schedule.after_tick(idle=True, now=100.0)
        schedule.after_tick(idle=True, now=120.0)  # at most once a minute
        assert calls == ["freeze", "unfreeze", 2]
    finally:
        gc.enable()

