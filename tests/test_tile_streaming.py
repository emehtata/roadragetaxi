from theroadragetrip.tile_streaming import (
    TileCoord,
    active_tiles,
    tile_bbox,
    tile_changes,
    world_to_tile,
)
from theroadragetrip.osm import AutoFetchManager, Way
from theroadragetrip.osm import MapData
from theroadragetrip.world_cache import WorldCacheManager
from theroadragetrip.render import invalidate_static_caches
from theroadragetrip.physics import SpatialWayGrid
from concurrent.futures import Future
import time


def test_world_to_tile_uses_floor_for_negative_coordinates():
    assert world_to_tile(999.9, 1000.0) == TileCoord(0, 1)
    assert world_to_tile(-0.1, -1000.0) == TileCoord(-1, -1)


def test_tile_bbox_is_deterministic_in_world_coordinates():
    assert tile_bbox(TileCoord(-2, 3)) == (-2000.0, 3000.0, -1000.0, 4000.0)


def test_active_tiles_contains_exactly_nine_tiles():
    tiles = active_tiles(TileCoord(10, 20))
    assert len(tiles) == 9
    assert TileCoord(10, 20) in tiles
    assert TileCoord(9, 19) in tiles
    assert TileCoord(11, 21) in tiles


def test_tile_changes_for_cardinal_and_diagonal_moves():
    center = TileCoord(10, 20)
    previous = active_tiles(center)
    for next_center in (
        TileCoord(11, 20),
        TileCoord(9, 20),
        TileCoord(10, 21),
        TileCoord(10, 19),
    ):
        added, removed = tile_changes(previous, active_tiles(next_center))
        assert len(added) == 3
        assert len(removed) == 3
    for next_center in (
        TileCoord(11, 21),
        TileCoord(9, 21),
        TileCoord(11, 19),
        TileCoord(9, 19),
    ):
        added, removed = tile_changes(previous, active_tiles(next_center))
        assert len(added) == 5
        assert len(removed) == 5


def test_tile_changes_initial_load_adds_nine_tiles():
    added, removed = tile_changes(set(), set(active_tiles(TileCoord(0, 0))))
    assert len(added) == 9
    assert removed == set()


def test_auto_fetch_manager_tracks_tile_transitions_without_repeating_same_tile():
    manager = AutoFetchManager(
        [Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0)],
        (0.0, 0.0, 1000.0, 1000.0),
        transformer=None,
    )

    initial = manager.update_player_tile(500.0, 500.0)
    assert initial is not None
    assert initial[0] == TileCoord(0, 0)
    assert len(initial[1]) == 9
    assert initial[2] == set()
    assert manager.update_player_tile(999.0, 999.0) is None

    east = manager.update_player_tile(1000.0, 500.0)
    assert east is not None
    assert east[0] == TileCoord(1, 0)
    assert len(east[1]) == 3
    assert len(east[2]) == 3
    assert manager.get_tile_metrics()["relative_tile"] == TileCoord(1, 0)


def test_start_tile_streaming_does_not_fetch_on_initial_same_tile_check():
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager.initialize_player_tile(500.0, 500.0)

    assert manager.start_tile_streaming(500.0, 500.0) is False
    assert manager.pending_tiles == set()
    assert manager.is_fetching is False
    assert manager.get_tile_metrics()["relative_tile"] == TileCoord(0, 0)


def test_initial_tile_streaming_is_not_repeated_after_full_startup_region():
    class Transformer:
        def transform(self, x, y):
            return x, y

    class TileCache:
        def __init__(self):
            self.calls = []

        def preload_region(self, bbox):
            self.calls.append(bbox)
            future = Future()
            future.set_result(MapData([], [], [], [], [], (0.0, 0.0, 1.0, 1.0)))
            return future

    cache = TileCache()
    manager = AutoFetchManager(
        [], (0.0, 0.0, 1000.0, 1000.0), Transformer(), world_cache_manager=cache,
    )
    manager.initialize_player_tile(500.0, 500.0)
    assert manager.start_initial_tile_streaming() is False
    assert cache.calls == []


def test_world_cache_persists_tiles_by_coordinate(tmp_path):
    tile = TileCoord(10, -4)
    world = MapData(
        [Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0)],
        [], [], [], [], (0.0, 0.0, 10.0, 10.0),
    )
    cache = WorldCacheManager(cache_dir=tmp_path)
    cache.save_tile(tile, world)

    assert cache.path_for_tile(tile) == tmp_path / "tiles" / "tile_10_-4.rwc"
    loaded = cache.load_tile(tile, bbox=(0.0, 0.0, 1.0, 1.0))
    assert len(loaded.ways) == 1
    assert loaded.ways[0].highway == "residential"
    cache.close()


def test_tile_streaming_loads_missing_tiles_in_background():
    class Transformer:
        def transform(self, x, y):
            return x, y

    class TileCache:
        def __init__(self):
            self.calls = []

        def preload_region(self, bbox):
            self.calls.append(bbox)
            future = Future()
            future.set_result(MapData([], [], [], [], [], (0.0, 0.0, 1.0, 1.0)))
            return future

    cache = TileCache()
    manager = AutoFetchManager(
        [], (0.0, 0.0, 1000.0, 1000.0), Transformer(),
        world_cache_manager=cache,
    )

    assert manager.start_tile_streaming(500.0, 500.0)
    deadline = time.time() + 2.0
    while manager.is_fetching and time.time() < deadline:
        time.sleep(0.01)

    assert not manager.is_fetching
    integrated = 0
    while True:
        batch_count = manager.integrate_completed_tiles(max_tiles=1)
        if not batch_count:
            break
        integrated += batch_count
    assert integrated == 9
    assert len(cache.calls) == 1
    assert cache.calls[0] == (-1000.0, -1000.0, 2000.0, 2000.0)
    assert len(manager.loaded_tiles) == 9
    assert manager.pending_tiles == set()
    metrics = manager.get_tile_metrics()
    assert metrics["tiles_in_memory"] == 9
    assert metrics["tiles_pending"] == 0
    assert metrics["tile_load_ms"] >= 0.0
    assert metrics["tile_integration_ms"] >= 0.0


def test_cardinal_tile_transition_batches_two_by_three_region():
    class Transformer:
        def transform(self, x, y):
            return x, y

    class TileCache:
        def __init__(self):
            self.calls = []

        def preload_region(self, bbox):
            self.calls.append(bbox)
            future = Future()
            future.set_result(MapData([], [], [], [], [], (0.0, 0.0, 1.0, 1.0)))
            return future

    cache = TileCache()
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), Transformer(), world_cache_manager=cache)
    manager.initialize_player_tile(500.0, 500.0)
    assert manager.start_tile_streaming(1000.0, 500.0)
    deadline = time.time() + 2.0
    while manager.is_fetching and time.time() < deadline:
        time.sleep(0.01)

    assert cache.calls == [(-1000.0, 0.0, 2000.0, 2000.0)]


def test_tile_transition_during_fetch_queues_next_region_request():
    class Transformer:
        def transform(self, x, y):
            return x, y

    class TileCache:
        def __init__(self):
            self.calls = []
            self.futures = []

        def preload_region(self, bbox):
            self.calls.append(bbox)
            future = Future()
            self.futures.append(future)
            return future

    cache = TileCache()
    manager = AutoFetchManager(
        [], (0.0, 0.0, 1000.0, 1000.0), Transformer(), world_cache_manager=cache,
    )
    manager.initialize_player_tile(500.0, 500.0)
    assert manager.start_tile_streaming(1000.0, 500.0)
    assert manager.start_tile_streaming(1000.0, 1500.0) is False

    cache.futures[0].set_result(
        MapData([Way([(1000.0, 500.0), (1100.0, 500.0)], "residential", 4.0)], [], [], [], [], (0.0, 0.0, 1500.0, 1500.0))
    )
    deadline = time.time() + 2.0
    while manager.is_fetching and time.time() < deadline:
        time.sleep(0.01)
    manager.integrate_completed_tiles(max_tiles=1)

    assert manager.start_tile_streaming(1000.0, 1500.0)
    assert len(cache.calls) == 2


def test_tile_object_survives_until_last_tile_owner_is_unloaded():
    shared = Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0, osm_id=42)
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager.active_tiles = {TileCoord(0, 0), TileCoord(1, 0)}
    manager.loaded_tiles = set(manager.active_tiles)
    manager._merge_tile_world_for(TileCoord(0, 0), MapData([shared], [], [], [], [], (0.0, 0.0, 1.0, 1.0)))
    manager._merge_tile_world_for(TileCoord(1, 0), MapData([shared], [], [], [], [], (0.0, 0.0, 1.0, 1.0)))

    manager._unload_tiles({TileCoord(0, 0)})
    assert manager.ways == [shared]
    manager._unload_tiles({TileCoord(1, 0)})
    assert manager.ways == []


def test_combined_region_assigns_crossing_way_to_both_tiles():
    crossing_way = Way(
        [(950.0, 250.0), (1050.0, 250.0)], "residential", 4.0, osm_id=99,
        bbox=(950.0, 250.0, 1050.0, 250.0),
    )
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager._merge_tile_world_for_tiles(
        {TileCoord(0, 0), TileCoord(1, 0)},
        MapData([crossing_way], [], [], [], [], (0.0, 0.0, 1000.0, 1000.0)),
    )

    assert manager.ways == [crossing_way]
    assert manager._tile_objects[TileCoord(0, 0)]["ways"][("Way", "id", 99)] is crossing_way
    assert manager._tile_objects[TileCoord(1, 0)]["ways"][("Way", "id", 99)] is crossing_way


def test_startup_world_is_registered_and_trimmed_to_active_tiles():
    inside = Way([(100.0, 100.0), (200.0, 100.0)], "residential", 4.0, osm_id=1, bbox=(100.0, 100.0, 200.0, 100.0))
    outside = Way([(5000.0, 100.0), (5100.0, 100.0)], "residential", 4.0, osm_id=2, bbox=(5000.0, 100.0, 5100.0, 100.0))
    manager = AutoFetchManager([inside, outside], (0.0, 0.0, 6000.0, 1000.0), transformer=None)

    manager.initialize_player_tile(500.0, 500.0)

    assert manager.ways == [inside]
    assert len(manager.active_tiles) == 9
    assert manager.loaded_tiles == manager.active_tiles


def test_tile_map_revision_changes_when_streamed_map_changes():
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    assert manager.get_map_revision() == 0
    manager._merge_tile_world_for(
        TileCoord(0, 0),
        MapData([Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0)], [], [], [], [], (0.0, 0.0, 1.0, 1.0)),
    )
    manager._unload_tiles({TileCoord(0, 0)})
    assert manager.get_map_revision() == 1


def test_integrated_streamed_road_reaches_live_world_and_stale_tile_is_released():
    road = Way([(1600.0, 100.0), (1700.0, 100.0)], "residential", 4.0, osm_id=123)
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager.active_tiles = {TileCoord(1, 0)}
    manager.pending_tiles = {TileCoord(1, 0), TileCoord(2, 0)}
    manager._completed_tile_batches = [[
        (
            (TileCoord(2, 0),),
            (TileCoord(2, 0),),
            MapData([road], [], [], [], [], (0.0, 0.0, 1.0, 1.0)),
        ),
        (
            (TileCoord(1, 0),),
            (TileCoord(1, 0),),
            MapData([road], [], [], [], [], (0.0, 0.0, 1.0, 1.0)),
        ),
    ]]

    assert manager.integrate_completed_tiles(max_tiles=2) == 1
    assert manager.ways == [road]
    assert manager.pending_tiles == set()


def test_integrated_streamed_road_reaches_spatial_grid():
    road = Way(
        [(1600.0, 100.0), (1700.0, 100.0)], "residential", 4.0, osm_id=124,
        bbox=(1600.0, 100.0, 1700.0, 100.0),
    )
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager.active_tiles = {TileCoord(1, 0)}
    manager.pending_tiles = {TileCoord(1, 0)}
    manager._completed_tile_batches = [[
        (
            (TileCoord(1, 0),),
            (TileCoord(1, 0),),
            MapData([road], [], [], [], [], (0.0, 0.0, 1000.0, 1000.0)),
        ),
    ]]

    assert manager.integrate_completed_tiles(max_tiles=1) == 1
    grid = SpatialWayGrid()
    grid.rebuild(manager.ways)

    assert list(grid.ways_in_rect(1590.0, 90.0, 1710.0, 110.0)) == [road]


def test_static_cache_invalidation_is_available_for_tile_changes():
    invalidate_static_caches()


def test_tile_merge_cost_does_not_scale_with_already_loaded_ways(monkeypatch):
    """Regression: merging one freshly-fetched tile used to rebuild a key set
    from *every* already-loaded way (and every other section) on every call,
    so the main-thread tile-merge stall main.py pays on every completed tile
    got worse the longer a play session ran and more of the map was already
    streamed in. Merging should only do work proportional to the new tile's
    own content."""
    import theroadragetrip.osm.autofetch as autofetch_module

    call_count = 0
    real_key = autofetch_module._map_object_key

    def counting_key(obj):
        nonlocal call_count
        call_count += 1
        return real_key(obj)

    monkeypatch.setattr(autofetch_module, "_map_object_key", counting_key)

    existing_ways = [
        Way([(x, 0.0), (x + 5.0, 0.0)], "residential", 4.0, osm_id=i, bbox=(x, 0.0, x + 5.0, 0.0))
        for i, x in enumerate(float(n) * 20.0 for n in range(2000))
    ]
    manager = AutoFetchManager(list(existing_ways), (0.0, 0.0, 40000.0, 1000.0), transformer=None)
    manager.active_tiles = {TileCoord(0, 0)}
    for way in existing_ways:
        manager._object_tiles.setdefault("ways", {})[("Way", "id", way.osm_id)] = {TileCoord(0, 0)}

    call_count = 0
    new_ways = [
        Way([(x, 500.0), (x + 5.0, 500.0)], "residential", 4.0, osm_id=100000 + i, bbox=(x, 500.0, x + 5.0, 500.0))
        for i, x in enumerate(float(n) * 20.0 for n in range(3))
    ]
    manager._merge_tile_world_for(
        TileCoord(0, 0), MapData(new_ways, [], [], [], [], (0.0, 0.0, 40000.0, 1000.0)),
    )

    assert manager.ways == existing_ways + new_ways
    # One _map_object_key call per new way, not one per new way *plus* one
    # per already-loaded way to rebuild a "what's already known" set.
    assert call_count <= len(new_ways) + 1
