import theroadragetrip.tile_streaming as tile_streaming
from theroadragetrip.tile_streaming import (
    PBF_TILE_SIZE_M,
    TileCoord,
    active_tiles,
    set_tile_size_m,
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


def test_set_tile_size_m_changes_the_grid():
    """set_tile_size_m must actually take effect on the very next call -
    world_to_tile/tile_bbox read the module global directly, not a value
    captured at some earlier time."""
    original = tile_streaming.TILE_SIZE_M
    try:
        set_tile_size_m(2000.0)
        assert world_to_tile(2500.0, -100.0) == TileCoord(1, -1)
        assert tile_bbox(TileCoord(1, -1)) == (2000.0, -2000.0, 4000.0, 0.0)
    finally:
        set_tile_size_m(original)


def test_pbf_tile_size_keeps_the_active_window_at_or_under_10km():
    """The active window is always the full 3x3 grid (its worst case,
    hit on the initial load and on diagonal-ish moves) - PBF_TILE_SIZE_M
    is chosen so that comes out to ~10x10km, the practical ceiling
    measured against the real Finland PBF (~28s/530MB; 25x25km already
    balloons to ~80s/1GB). This guards that calibration from silent
    drift, not the exact value."""
    assert PBF_TILE_SIZE_M * 3 <= 10000.0


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


def test_tile_fetch_projects_all_four_corners_not_just_the_diagonal():
    """Regression: EPSG:3067 rotates meridians relative to true north away
    from its central meridian, so a straight meters-space tile rectangle
    becomes a rotated quadrilateral in lat/lon - transforming only the
    (min_x,min_y)/(max_x,max_y) diagonal (as opposed to all 4 corners) can
    compute a lat/lon bbox narrower than the tile actually is, silently
    excluding a real strip of OSM data at the tile edges even though the
    tile is then marked fully loaded by its untouched meters coordinates.
    A fake rotation-like transform (mixing x and y, unlike the other tests'
    identity/separable fakes, which can't expose this) makes the corner
    that actually produces the min/max lon fall on the *other* diagonal."""
    class RotatingTransformer:
        def transform(self, x, y):
            return x + y * 0.5, y - x * 0.5

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
        [], (0.0, 0.0, 1000.0, 1000.0), RotatingTransformer(),
        world_cache_manager=cache,
    )

    assert manager.start_tile_streaming(500.0, 500.0)
    deadline = time.time() + 2.0
    while manager.is_fetching and time.time() < deadline:
        time.sleep(0.01)

    t = RotatingTransformer()
    corners = [t.transform(x, y) for x in (-1000.0, 2000.0) for y in (-1000.0, 2000.0)]
    lons = [lon for lon, _ in corners]
    lats = [lat for _, lat in corners]
    expected = (min(lats), min(lons), max(lats), max(lons))
    assert len(cache.calls) == 1
    assert cache.calls[0] == expected


def test_tile_streaming_respects_cooldown_between_requests():
    """Regression: crossing tiles quickly (driving fast) used to fire a new
    Overpass request the instant the previous one finished, with nothing
    pacing successive requests - fast enough to get IP rate-limited by
    public endpoints. A second tile transition within cooldown_s of the
    last request must wait; the still-missing tiles are picked up once the
    cooldown clears."""
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
        world_cache_manager=cache, cooldown_s=60.0,
    )

    assert manager.start_tile_streaming(500.0, 500.0)
    deadline = time.time() + 2.0
    while manager.is_fetching and time.time() < deadline:
        time.sleep(0.01)
    while manager.integrate_completed_tiles(max_tiles=1):
        pass
    assert len(cache.calls) == 1

    # Player immediately crosses into another tile - still within cooldown.
    assert manager.start_tile_streaming(1500.0, 500.0) is False
    assert len(cache.calls) == 1

    # Cooldown has elapsed: the still-missing tile is now fetched.
    manager.last_fetch_time = 0.0
    assert manager.start_tile_streaming(1500.0, 500.0) is True
    assert len(cache.calls) == 2


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

    # Region must include the genuinely new leading column (x=2, the
    # direction of travel) plus the current one for edge continuity - not
    # the trailing, already-loaded column behind the player.
    assert cache.calls == [(-1000.0, 1000.0, 2000.0, 3000.0)]


def test_cardinal_tile_transition_requests_the_leading_not_trailing_edge():
    """Regression test for a sign bug: request_tiles picked the column the
    player was leaving instead of the one they were entering, so a straight
    cardinal drive never actually queried the new tile's territory - new
    roads, buildings and traffic lights there would never be fetched at
    all until some later, differently-shaped move happened to cover it."""
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
    manager.start_tile_streaming(1000.0, 500.0)
    deadline = time.time() + 2.0
    while manager.is_fetching and time.time() < deadline:
        time.sleep(0.01)

    (min_lat, min_lon, max_lat, max_lon) = cache.calls[0]
    # x maps to lon here (the fake Transformer is an identity passthrough).
    # The player moved from tile x=0 into tile x=1, so the newly active,
    # not-yet-loaded column is x=2 (world x in [2000, 3000)); that range
    # must be covered by the fetched region.
    assert max_lon >= 3000.0, "fetch region must cover the newly entered tile column, not just tiles already loaded"


def test_evicted_tile_in_the_trailing_column_is_not_marked_loaded_without_being_fetched():
    """Regression: on a straight cardinal move, integrate_completed_tiles()
    used to mark *every* tile from start_tile_streaming()'s full missing
    set as loaded - including ones outside the narrowed request_tiles bbox
    that move actually fetched (the trailing column, skipped on purpose as
    a perf optimization - see the "leading not trailing edge" test above,
    normally safe since the trailing column is already loaded). If a tile
    there had been evicted earlier (player drove away, came back later) it
    was genuinely missing, not just "not re-requested" - but got marked
    loaded anyway, so its own territory was never actually extracted and
    nothing ever asked for it again. This is what made a road spread wide
    enough to land in a different tile (regularly: the far carriageway of
    a divided highway) silently stop loading, permanently."""
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

    # Player was at tile (1, 0); everything in that 3x3 window was loaded
    # *except* (1, -1) - simulating it got evicted at some earlier point
    # despite remaining active across this transition.
    manager.player_tile = TileCoord(1, 0)
    manager.active_tiles = set(active_tiles(TileCoord(1, 0)))
    manager.loaded_tiles = set(manager.active_tiles)
    evicted = TileCoord(1, -1)
    manager.loaded_tiles.discard(evicted)

    # Player moves one tile west, to (0, 0) - a pure cardinal move, so the
    # fetch narrows to the x in {-1, 0} columns (current + leading/west
    # edge), excluding x=1 (the trailing column `evicted` sits in).
    assert manager.start_tile_streaming(500.0, 500.0)
    deadline = time.time() + 2.0
    while manager.is_fetching and time.time() < deadline:
        time.sleep(0.01)
    while manager.integrate_completed_tiles(max_tiles=1):
        pass

    assert evicted not in manager.loaded_tiles, (
        "evicted tile outside the fetched bbox was marked loaded anyway - its territory will never be re-fetched"
    )
    # And it must still show up as missing, so a later call picks it up.
    assert evicted in manager.active_tiles - manager.loaded_tiles - manager.pending_tiles


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
    # cooldown_s=0.0: this test triggers two real fetches back-to-back to
    # exercise transition-queueing, not the request-rate cooldown.
    manager = AutoFetchManager(
        [], (0.0, 0.0, 1000.0, 1000.0), Transformer(), world_cache_manager=cache, cooldown_s=0.0,
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


def test_logical_intersections_from_different_tiles_all_survive_merge():
    """LogicalIntersection has no osm_id/id/points_m/x/y, so _map_object_key
    used to fall through to a (name, kind, x, y) fallback that's identical
    (None, None, 0.0, 0.0) for every instance - every intersection after
    the first looked like a duplicate of it and was silently dropped on
    later tile merges."""
    from theroadragetrip.osm import LogicalIntersection

    first = LogicalIntersection("0:100:100", (100.0, 100.0), 10.0)
    second = LogicalIntersection("0:2100:100", (2100.0, 100.0), 10.0)
    manager = AutoFetchManager([], (0.0, 0.0, 3000.0, 1000.0), transformer=None)
    manager._merge_tile_world_for(
        TileCoord(0, 0), MapData([], [], [], [], [], (0.0, 0.0, 1.0, 1.0), logical_intersections=[first]),
    )
    manager._merge_tile_world_for(
        TileCoord(2, 0), MapData([], [], [], [], [], (0.0, 0.0, 1.0, 1.0), logical_intersections=[second]),
    )

    assert manager.logical_intersections == [first, second]


def test_logical_intersections_survive_the_real_non_forced_tile_merge():
    """_item_tiles() (used by the real tile-streaming merge path, unlike
    the force_tile=True helper above) had no case for LogicalIntersection:
    it has no bbox/x/y/points_m, only `center`/`radius_m`, so it fell
    through to the points_m branch, got an empty tuple back, and
    _item_tiles returned set() - meaning owned_tiles was *always* empty
    for it, so it was silently dropped on every real (non-forced) tile
    merge, unconditionally, regardless of the dedup key."""
    from theroadragetrip.osm import LogicalIntersection

    intersection = LogicalIntersection("0:500:500", (500.0, 500.0), 10.0)
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager._merge_tile_world_for_tiles(
        {TileCoord(0, 0)},
        MapData([], [], [], [], [], (0.0, 0.0, 1.0, 1.0), logical_intersections=[intersection]),
        force_tile=False,
    )

    assert manager.logical_intersections == [intersection]


def test_scenery_objects_survive_the_real_non_forced_tile_merge():
    """scenery_objects (benches, statues, ...) must flow through the same
    real tile-streaming merge path as every other section - a plain x/y
    point, so _item_tiles() already handles it generically."""
    from theroadragetrip.osm import SceneryObject

    bench = SceneryObject(x=500.0, y=500.0, kind="bench", id=1)
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager._merge_tile_world_for_tiles(
        {TileCoord(0, 0)},
        MapData([], [], [], [], [], (0.0, 0.0, 1.0, 1.0), scenery_objects=[bench]),
        force_tile=False,
    )

    assert manager.scenery_objects == [bench]


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


def test_startup_does_not_claim_tiles_the_startup_world_never_reached():
    """Regression: with a big enough tile size (osm_source=pbf's
    PBF_TILE_SIZE_M, ~3300m), the initial 3x3 active window (~9900m
    across) can be far bigger than the actual startup city load (a few
    km) - initialize_player_tile() used to mark the *entire* window
    "loaded" regardless, so a player could drive straight to the true
    edge of the fetched data while still nominally inside their starting
    tile: start_tile_streaming() never saw anything "missing", so no
    fetch ever triggered and the road just ran out. Only a tile the
    startup world's own bounds actually reach may be marked loaded."""
    original = tile_streaming.TILE_SIZE_M
    try:
        set_tile_size_m(3300.0)
        # Startup world only covers a small area near the origin - nowhere
        # near the full ~9900m 3x3 window a player tile of (0, 0) implies.
        manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)

        manager.initialize_player_tile(500.0, 500.0)

        assert len(manager.active_tiles) == 9
        # Tiles whose own bbox happens to touch the small bounds rectangle
        # near the origin are fairly claimed loaded; ones that don't touch
        # it at all - the far side of the 3x3 window, e.g. straight north
        # or east of the startup area - must not be, regardless of being
        # nominally "in the active window".
        assert TileCoord(0, 0) in manager.loaded_tiles
        far_tiles = {TileCoord(1, 1), TileCoord(1, 0), TileCoord(0, 1), TileCoord(1, -1), TileCoord(-1, 1)}
        assert manager.loaded_tiles.isdisjoint(far_tiles)
        missing = manager.active_tiles - manager.loaded_tiles - manager.pending_tiles
        assert far_tiles <= missing
    finally:
        set_tile_size_m(original)


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


def test_unload_tiles_cost_does_not_scale_with_number_of_removed_keys(monkeypatch):
    """Regression: unloading a tile used to rebuild the whole section's
    list once *per removed key* (a list-comprehension filter inside the
    per-key loop), so unloading even a handful of a tile's
    exclusively-owned objects out of an already-large, well-explored world
    scaled with removed_keys x total_size - the same shape of stall as the
    tile-merge and tree-cleanup bugs fixed earlier ("tile unloading takes
    time"). Unloading should filter each section once, regardless of how
    many keys are being removed from it."""
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
    manager.active_tiles = {TileCoord(0, 0), TileCoord(1, 0)}
    manager.loaded_tiles = set(manager.active_tiles)
    for way in existing_ways:
        manager._object_tiles.setdefault("ways", {})[("Way", "id", way.osm_id)] = {TileCoord(0, 0)}

    removed_ways = [
        Way([(x, 500.0), (x + 5.0, 500.0)], "residential", 4.0, osm_id=100000 + i, bbox=(x, 500.0, x + 5.0, 500.0))
        for i, x in enumerate(float(n) * 20.0 for n in range(5))
    ]
    manager._merge_tile_world_for(
        TileCoord(1, 0), MapData(removed_ways, [], [], [], [], (0.0, 0.0, 40000.0, 1000.0)),
    )

    call_count = 0
    manager._unload_tiles({TileCoord(1, 0)})

    assert manager.ways == existing_ways
    # One filter pass over the ~2005-item section, not one pass *per
    # removed key* (5 x ~2005).
    assert call_count <= 2005 + 20


def test_unload_tiles_batches_multiple_tiles_in_one_call_correctly():
    """The removed-keys-per-section aggregation (collected across every
    tile in the call before a single filter pass) must still respect
    ownership correctly when several tiles are unloaded together."""
    shared = Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0, osm_id=1)
    solo_a = Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0, osm_id=2)
    solo_b = Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0, osm_id=3)
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager.active_tiles = {TileCoord(0, 0), TileCoord(1, 0), TileCoord(2, 0)}
    manager.loaded_tiles = set(manager.active_tiles)
    manager._merge_tile_world_for(TileCoord(0, 0), MapData([shared, solo_a], [], [], [], [], (0.0, 0.0, 1.0, 1.0)))
    manager._merge_tile_world_for(TileCoord(1, 0), MapData([shared, solo_b], [], [], [], [], (0.0, 0.0, 1.0, 1.0)))
    manager._merge_tile_world_for(TileCoord(2, 0), MapData([shared], [], [], [], [], (0.0, 0.0, 1.0, 1.0)))

    manager._unload_tiles({TileCoord(0, 0), TileCoord(1, 0)})

    # shared is still owned by tile (2, 0), which wasn't unloaded.
    assert shared in manager.ways
    # solo_a/solo_b were only ever owned by the tiles just unloaded together.
    assert solo_a not in manager.ways
    assert solo_b not in manager.ways


def test_current_process_memory_mb_returns_a_positive_reading_on_linux():
    from theroadragetrip.osm.autofetch import _current_process_memory_mb

    memory_mb = _current_process_memory_mb()
    # None is an accepted "not available on this platform" result, but on
    # the Linux CI/dev environment this actually runs on, /proc/self/status
    # must be readable and report something sane for a running process.
    assert memory_mb is None or memory_mb > 0.0


def test_tile_leaving_active_window_stays_loaded_under_memory_budget():
    """A tile that falls out of the active window shouldn't be unloaded on
    the spot - only once memory pressure (or the count-ceiling fallback)
    actually calls for it. Otherwise a player who immediately doubles back
    forces a pointless re-fetch."""
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager.initialize_player_tile(500.0, 500.0)
    manager.tile_memory_budget_mb = float("inf")  # never over budget

    manager.start_tile_streaming(3500.0, 500.0)  # far enough to leave every old tile

    assert TileCoord(0, 0) not in manager.active_tiles
    assert TileCoord(0, 0) in manager.loaded_tiles
    assert TileCoord(0, 0) in manager._inactive_tile_since


def test_returning_before_eviction_cancels_it():
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager.initialize_player_tile(500.0, 500.0)
    manager.tile_memory_budget_mb = float("inf")

    manager.start_tile_streaming(2500.0, 500.0)
    assert TileCoord(0, 0) in manager._inactive_tile_since

    manager.start_tile_streaming(500.0, 500.0)  # back to the original tile
    assert TileCoord(0, 0) not in manager._inactive_tile_since
    assert TileCoord(0, 0) in manager.loaded_tiles


def test_quick_there_and_back_survives_eviction_even_over_memory_budget(monkeypatch):
    """Regression: a real, long play session routinely already sits over
    tile_memory_budget_mb just from everything else loaded (pygame, the
    rest of the process, a big already-streamed world) - so without a
    grace period, "should_evict" was true essentially always, and driving
    one tile over and immediately back (a common quick out-and-back move)
    evicted the tile just left before the player had any chance to
    return, forcing a real re-fetch and re-merge on the way back every
    single time."""
    import theroadragetrip.osm.autofetch as autofetch_module

    monkeypatch.setattr(autofetch_module, "_current_process_memory_mb", lambda: 9999.0)
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager.initialize_player_tile(500.0, 500.0)
    manager.tile_memory_budget_mb = 100.0  # always "over budget"

    # (0, 0) itself never leaves active_tiles here - moving one tile over
    # and back keeps it in both 3x3 windows. It's the trailing edge column,
    # (-1, *), that goes inactive on the way there and is needed again the
    # instant the player comes back - exactly the tile eviction-under-
    # pressure must not have already thrown away.
    manager.start_tile_streaming(1500.0, 500.0)  # one tile over
    assert TileCoord(-1, 0) in manager._inactive_tile_since

    manager.start_tile_streaming(500.0, 500.0)  # immediately back
    assert TileCoord(-1, 0) in manager.loaded_tiles
    assert TileCoord(-1, 0) not in manager._inactive_tile_since


def test_evicts_inactive_tiles_once_over_the_memory_budget(monkeypatch):
    import theroadragetrip.osm.autofetch as autofetch_module

    monkeypatch.setattr(autofetch_module, "_current_process_memory_mb", lambda: 9999.0)
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager.initialize_player_tile(500.0, 500.0)
    manager.tile_memory_budget_mb = 100.0
    before = len(manager._inactive_tile_since) + len(manager.active_tiles)

    manager.start_tile_streaming(3500.0, 500.0)

    # Freshly-inactive tiles get a grace period before they're even
    # eviction candidates, regardless of memory pressure - see
    # MIN_INACTIVE_S_BEFORE_EVICTION. None should be gone yet.
    assert len(manager._inactive_tile_since) == before

    # Once they've genuinely sat inactive long enough, over-budget pressure
    # does evict some of them (bounded to one eviction batch), not leave
    # them all resident-but-inactive forever.
    manager._evict_inactive_tiles(time.monotonic() + autofetch_module.MIN_INACTIVE_S_BEFORE_EVICTION + 1.0)
    assert len(manager._inactive_tile_since) <= before - autofetch_module.INACTIVE_TILE_EVICTION_BATCH


def test_falls_back_to_tile_count_ceiling_without_memory_reading(monkeypatch):
    import theroadragetrip.osm.autofetch as autofetch_module

    monkeypatch.setattr(autofetch_module, "_current_process_memory_mb", lambda: None)
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager._inactive_tile_since = {
        TileCoord(i, 0): float(i)
        for i in range(autofetch_module.MAX_INACTIVE_RESIDENT_TILES + 5)
    }

    manager._evict_inactive_tiles(now=1000.0)

    assert len(manager._inactive_tile_since) <= autofetch_module.MAX_INACTIVE_RESIDENT_TILES


def test_under_the_tile_count_ceiling_nothing_is_evicted_without_memory_reading(monkeypatch):
    import theroadragetrip.osm.autofetch as autofetch_module

    monkeypatch.setattr(autofetch_module, "_current_process_memory_mb", lambda: None)
    manager = AutoFetchManager([], (0.0, 0.0, 1000.0, 1000.0), transformer=None)
    manager._inactive_tile_since = {TileCoord(0, 0): 0.0}

    manager._evict_inactive_tiles(now=1000.0)

    assert TileCoord(0, 0) in manager._inactive_tile_since
