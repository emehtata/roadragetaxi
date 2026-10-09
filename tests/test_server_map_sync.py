"""Live map expansion on the server (server/map_sync.py): merge streamed
tiles, sync the world when a merge settles, report the growth, hold merges
while the server rebuilds its chunks."""
import threading
from types import SimpleNamespace

from theroadragetrip.server import map_sync


class FakeManager:
    def __init__(self):
        self.revision, self.bounds, self.busy = 1, (0.0, 0.0, 100.0, 100.0), False
        self.integrated = self.streamed = 0
        self.lock = threading.Lock()
        self.soft_boundary_enabled = False

    def get_map_revision(self):
        return self.revision

    def get_bounds(self):
        return self.bounds

    def get_tile_merge_metrics(self):
        return {"tile_merge_active": self.busy}

    def integrate_completed_tiles(self, budget_s=None):
        self.integrated += 1

    def start_tile_streaming(self, x, y, vx, vy):
        self.streamed += 1
        return False


def test_streamer_syncs_once_a_merge_settles_and_reports_the_growth(monkeypatch):
    synced_steps = []

    def steps(world):
        synced_steps.append("start")
        yield
        synced_steps.append("end")

    monkeypatch.setattr(map_sync, "map_sync_steps", steps)
    manager = FakeManager()
    grown = []
    streamer = map_sync.MapStreamer(SimpleNamespace(auto_fetch_manager=manager, ways=[]), lambda old, new: grown.append((old, new)))
    assert manager.soft_boundary_enabled

    streamer.tick(50, 50, 10, 0)
    assert manager.integrated == 1 and manager.streamed == 1 and not streamer.syncing  # nothing new yet
    manager.revision, manager.bounds, manager.busy = 2, (0.0, 0.0, 200.0, 100.0), True
    streamer.tick(50, 50, 10, 0)
    assert not streamer.syncing  # still merging: wait
    manager.busy = False
    streamer.tick(50, 50, 10, 0)
    assert streamer.syncing and synced_steps == []  # started: the stages run from the next tick
    for _ in range(3):
        streamer.tick(50, 50, 10, 0)
    assert synced_steps == ["start", "end"] and not streamer.syncing
    assert grown == [((0.0, 0.0, 100.0, 100.0), (0.0, 0.0, 200.0, 100.0))]

    streamer.hold = True  # the server is rebuilding its chunks
    before = manager.integrated
    streamer.tick(50, 50, 10, 0)
    assert manager.integrated == before


def test_the_status_tells_the_client_what_the_map_is_doing(monkeypatch):
    """For the loading sign: fetching, merging, syncing, building, then ""."""
    monkeypatch.setattr(map_sync, "map_sync_steps", lambda world: iter([None]))
    manager = FakeManager()
    manager.fetching = False
    manager.get_fetching = lambda: manager.fetching
    streamer = map_sync.MapStreamer(SimpleNamespace(auto_fetch_manager=manager, ways=[]), lambda old, new: None)
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
