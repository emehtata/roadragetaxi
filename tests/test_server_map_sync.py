"""Live map expansion on the server (server/map_sync.py): merge streamed
tiles, sync the world when a merge settles, report the growth, hold merges
while the server rebuilds its chunks."""
import threading
from types import SimpleNamespace

from theroadragetrip.server import map_sync


class FakeManager:
    def __init__(self):
        self.revision, self.bounds, self.busy = 1, (0.0, 0.0, 100.0, 100.0), False
        self.loaded_tiles = set()
        self.fetching = False
        self.integrated = self.streamed = 0
        self.lock = threading.Lock()
        self.soft_boundary_enabled = False

    def get_map_revision(self):
        return self.revision

    def get_bounds(self):
        return self.bounds

    def get_tile_merge_metrics(self):
        return {"tile_merge_active": self.busy}

    def get_fetching(self):
        return self.fetching

    def integrate_completed_tiles(self, budget_s=None):
        self.integrated += 1

    def take_dirty_rect(self):
        return (0.0, 0.0, 100.0, 100.0)

    def start_tile_streaming(self, x, y, vx, vy):
        self.streamed += 1
        return False


def test_new_traffic_lights_are_available_when_chunk_rebuild_starts(monkeypatch):
    class Grid:
        def start_rebuild(self, items):
            pass

        def advance_rebuild(self, budget):
            return True

    class TrafficManager:
        traffic_lights = []

        def start_map_sync(self, ways, traffic_lights=None, **kwargs):
            self.traffic_lights = traffic_lights

    manager = FakeManager()
    manager._attempted_endpoints = set()
    traffic = TrafficManager()
    world = SimpleNamespace(
        auto_fetch_manager=manager, ways=[], level_ways=[], level_connectors=[], sceneries=[], buildings=[],
        parking_spaces=[], waters=[], crossings=[], curbs=[], railways=[], railings=[], traffic_lights=[object()],
        logical_intersections=[], stop_signs=[], yield_signs=[], scenery_objects=[], street_lamps=[],
        taxi_mgr=SimpleNamespace(invalidate_tree_collision_index=lambda: None), traffic_mgr=traffic,
        building_grid=Grid(), scenery_grid=Grid(), street_lamp_grid=Grid(), water_grid=Grid(), crossing_grid=Grid(),
        curb_grid=Grid(), railway_grid=Grid(), railing_grid=Grid(), traffic_light_grid=Grid(), spatial_grid=Grid(),
        arena_crowds=None,
    )
    monkeypatch.setattr(map_sync, "remove_trees_under_roads_steps", lambda sceneries, ways: ())

    stages = map_sync.map_sync_steps(world)
    while next(stages) != map_sync.CHUNK_INPUTS_READY:
        pass

    assert traffic.traffic_lights is world.traffic_lights


def test_cold_start_finishes_initial_merge_and_sync_before_gameplay(monkeypatch):
    stages = []

    class InitialManager(FakeManager):
        def __init__(self):
            super().__init__()
            self.dirty_taken = 0

        def start_initial_tile_streaming(self):
            self.fetching = False
            return True

        def integrate_completed_tiles(self, budget_s=None):
            assert budget_s is None
            self.integrated += 1
            return 9

        def take_dirty_rect(self):
            self.dirty_taken += 1
            return (0.0, 0.0, 100.0, 100.0)

    manager = InitialManager()

    def sync_steps(world):
        stages.append("sync")
        yield "done"

    monkeypatch.setattr(map_sync, "map_sync_steps", sync_steps)

    progress = []
    result = map_sync.prepare_initial_window(SimpleNamespace(auto_fetch_manager=manager),
                                            progress=lambda *row: progress.append(row))

    assert result["integrated_tiles"] == 9
    assert stages == ["sync"]
    assert manager.dirty_taken == 1
    assert progress == [("tiles",), ("merging",), ("indexes", "done")]


def test_cold_start_is_a_noop_when_startup_bbox_already_covers_the_window():
    manager = FakeManager()
    manager.start_initial_tile_streaming = lambda: False

    result = map_sync.prepare_initial_window(SimpleNamespace(auto_fetch_manager=manager))

    assert result == {"started": False, "integrated_tiles": 0, "elapsed_s": 0.0}


def test_cold_start_timeout_leaves_runtime_streaming_as_the_fallback(monkeypatch):
    manager = FakeManager()
    manager.fetching = True
    manager.start_initial_tile_streaming = lambda: True
    monkeypatch.setattr(map_sync.time, "sleep", lambda seconds: None)

    result = map_sync.prepare_initial_window(
        SimpleNamespace(auto_fetch_manager=manager), timeout_s=0.0,
    )

    assert result["timed_out"] is True
    assert manager.integrated == 0


def test_streamer_syncs_once_a_merge_settles_and_reports_the_growth(monkeypatch):
    synced_steps = []

    def steps(world):
        synced_steps.append("start")
        yield map_sync.CHUNK_INPUTS_READY  # the chunks are rebuilt from here; the graphs continue
        assert grown  # reported before the sync ends
        yield "traffic"
        synced_steps.append("end")

    monkeypatch.setattr(map_sync, "map_sync_steps", steps)
    monkeypatch.setattr(map_sync, "SYNC_SETTLE_S", 0.0)
    manager = FakeManager()
    grown = []
    streamer = map_sync.MapStreamer(SimpleNamespace(auto_fetch_manager=manager, ways=[]), lambda old, new, dirty: grown.append((old, new)))
    assert manager.soft_boundary_enabled

    streamer.tick(50, 50, 10, 0)
    assert manager.integrated == 1 and manager.streamed == 1 and not streamer.syncing  # nothing new yet
    manager.revision, manager.bounds, manager.busy = 2, (0.0, 0.0, 200.0, 100.0), True
    streamer.tick(50, 50, 10, 0)
    assert not streamer.syncing  # still merging: wait
    manager.busy, manager.loaded_tiles = False, {"a", "b"}
    streamer.tick(50, 50, 10, 0)
    assert streamer.syncing and synced_steps == []  # started: the stages run from the next tick
    manager.loaded_tiles = {"a", "b", "c"}  # merged after the start: the next sync's
    for _ in range(3):
        streamer.tick(50, 50, 10, 0)
    assert synced_steps == ["start", "end"] and not streamer.syncing and streamer.sync_tiles == {"a", "b"}
    assert grown == [((0.0, 0.0, 100.0, 100.0), (0.0, 0.0, 200.0, 100.0))]

    streamer.hold = True  # the server is rebuilding its chunks
    before = manager.integrated
    streamer.tick(50, 50, 10, 0)
    assert manager.integrated == before


def test_the_status_tells_the_client_what_the_map_is_doing(monkeypatch):
    """For the loading sign: fetching, merging, syncing, building, then ""."""
    monkeypatch.setattr(map_sync, "map_sync_steps", lambda world: iter([None]))
    monkeypatch.setattr(map_sync, "SYNC_SETTLE_S", 0.0)
    manager = FakeManager()
    manager.fetching = False
    manager.get_fetching = lambda: manager.fetching
    streamer = map_sync.MapStreamer(SimpleNamespace(auto_fetch_manager=manager, ways=[]), lambda old, new, dirty: None)
    assert streamer.status() == ""
    manager.fetching = True
    assert streamer.status() == "fetching"
    manager.fetching, manager.busy = False, True
    assert streamer.status() == "merging"
    manager.busy, manager.revision = False, 2
    assert streamer.status() == "merging"  # merged: the sync starts next tick
    streamer.tick(0, 0, 0, 0)
    assert streamer.status() == "syncing"
    streamer.tick(0, 0, 0, 0)
    streamer.hold = True
    assert streamer.status() == "building"
    streamer.hold = False
    assert streamer.status() == ""


def test_a_settled_merge_waits_briefly_for_a_fetch_in_flight(monkeypatch):
    """The lookahead tile is requested right after the core window, or a
    moment later: one whole-world sync for both, not one each."""
    monkeypatch.setattr(map_sync, "map_sync_steps", lambda world: iter([None]))
    monkeypatch.setattr(map_sync, "SYNC_SETTLE_S", 0.0)

    def merged(fetching=True):
        manager = FakeManager()
        streamer = map_sync.MapStreamer(SimpleNamespace(auto_fetch_manager=manager, ways=[]), lambda old, new, dirty: None)
        manager.revision, manager.fetching = 2, fetching
        return manager, streamer

    manager, streamer = merged()
    streamer.tick(0, 0, 0, 0)
    assert not streamer.syncing
    manager.fetching = False  # loaded (and merged): now one sync
    streamer.tick(0, 0, 0, 0)
    assert streamer.syncing

    _, streamer = merged()
    streamer.tick(0, 0, 0, 0, urgent=True)
    assert streamer.syncing  # the map under the player is missing: no waiting

    monkeypatch.setattr(map_sync, "SYNC_SETTLE_S", 60.0)
    _, streamer = merged(fetching=False)
    streamer.tick(0, 0, 0, 0)
    assert not streamer.syncing  # settling: the lookahead may still be asked for

    monkeypatch.setattr(map_sync, "SYNC_WAIT_FOR_FETCH_S", 0.0)
    _, streamer = merged()
    streamer.tick(0, 0, 0, 0)
    assert streamer.syncing  # waited long enough: a slow fetch gets its own sync
