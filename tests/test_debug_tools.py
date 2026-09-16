"""Tests for the debug-snapshot JSON writer."""
import json
import types

from theroadragetrip.main.debug_tools import _write_debug_snapshot
from theroadragetrip.npc import spawn_npc
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld
from theroadragetrip import tile_streaming


class FakeAutoFetchManager:
    def __init__(self):
        self.last_fetch_time = 0.0
        self.cooldown_s = 5.0
        self.dead_ends = []
        self.audit_tile_size_m = None

    def get_bounds(self):
        return (0.0, 0.0, 1.0, 1.0)

    def get_fetching(self):
        return False

    def get_progress(self):
        return 1.0

    def get_trigger_reason(self):
        return ""

    def is_known_dead_end(self, x, y, direction):
        return False

    def get_endpoint_fetch_audit(self, car, margin_m, tile_size_m, current_way=None):
        self.audit_tile_size_m = tile_size_m
        return {"status": "no_current_way"}


def _fake_taxi_mgr():
    mgr = types.SimpleNamespace(
        state="PICKUP",
        offers=[],
        tree_effects=[],
        fallen_trees=[],
        vomit_puddles=[],
        current_passenger=None,
    )
    return mgr


def test_debug_snapshot_reports_the_live_tile_streaming_grid_size(tmp_path):
    """Regression: the JSON's auto_fetch.tile_size_m (and the value fed into
    get_endpoint_fetch_audit's lookahead_m calc) used to be args.fetch_tile_size
    - a legacy CLI value that only feeds AutoFetchManager.start_if_needed(), a
    fetch path nothing in the game calls any more - instead of the real live
    tile_streaming.TILE_SIZE_M grid the game actually streams by. That made
    every debug snapshot's tile_size_m (and the endpoint audit's lookahead_m)
    wrong for osm_source=pbf sessions, which run a different TILE_SIZE_M
    (PBF_TILE_SIZE_M) than the CLI default."""
    original = tile_streaming.TILE_SIZE_M
    tile_streaming.set_tile_size_m(3300.0)
    try:
        auto_fetch_manager = FakeAutoFetchManager()
        args = types.SimpleNamespace(
            auto_fetch=True,
            fetch_margin=350.0,
            fetch_tile_size=2500.0,  # deliberately different from TILE_SIZE_M
            build_in_process=True,
            osm_source="pbf",
        )
        pedestrian_mgr = types.SimpleNamespace(pedestrians=[])
        spatial_grid = types.SimpleNamespace(indexed_way_count=0)
        path = tmp_path / "snapshot.json"

        _write_debug_snapshot(
            str(path),
            Car(x=0.0, y=0.0, heading=0.0, speed=0.0),
            _fake_taxi_mgr(),
            auto_fetch_manager,
            args,
            bbox=(0.0, 0.0, 1.0, 1.0),
            viewport_bounds=(0.0, 0.0, 1.0, 1.0),
            camx=0.0,
            camy=0.0,
            px_per_m=1.0,
            current_way=None,
            ways=[],
            waters=[],
            buildings=[],
            sceneries=[],
            places=[],
            taxi_stops=[],
            traffic_lights=[],
            crossings=[],
            elements_count=0,
            traffic_mgr=None,
            pedestrian_mgr=pedestrian_mgr,
            spatial_grid=spatial_grid,
            map_sync_stage=0,
            chosen_city="Oulu",
            camera_city_name="Oulu",
            game_mode="gig_driver",
            on_foot=False,
        )

        data = json.loads(path.read_text())
        assert data["auto_fetch"]["tile_size_m"] == 3300.0
        assert auto_fetch_manager.audit_tile_size_m == 3300.0
    finally:
        tile_streaming.set_tile_size_m(original)


def _write_minimal_snapshot(path, **overrides):
    auto_fetch_manager = FakeAutoFetchManager()
    args = types.SimpleNamespace(
        auto_fetch=True, fetch_margin=350.0, fetch_tile_size=2500.0,
        build_in_process=True, osm_source="overpass",
    )
    pedestrian_mgr = types.SimpleNamespace(pedestrians=[])
    spatial_grid = types.SimpleNamespace(indexed_way_count=0)
    kwargs = dict(
        car=Car(x=0.0, y=0.0, heading=0.0, speed=0.0), taxi_mgr=_fake_taxi_mgr(),
        auto_fetch_manager=auto_fetch_manager, args=args, bbox=(0.0, 0.0, 1.0, 1.0),
        viewport_bounds=(0.0, 0.0, 1.0, 1.0), camx=0.0, camy=0.0, px_per_m=1.0,
        current_way=None, ways=[], waters=[], buildings=[], sceneries=[], places=[],
        taxi_stops=[], traffic_lights=[], crossings=[], elements_count=0, traffic_mgr=None,
        pedestrian_mgr=pedestrian_mgr, spatial_grid=spatial_grid, map_sync_stage=0,
        chosen_city="Oulu", camera_city_name="Oulu", game_mode="gig_driver", on_foot=False,
    )
    kwargs.update(overrides)
    _write_debug_snapshot(str(path), **kwargs)
    return json.loads(path.read_text())


def test_debug_snapshot_includes_npc_state(tmp_path):
    """A screenshot's JSON should carry the same NPC driving/routing state
    the F7 debug overlay shows on screen (draw_npc_debug_panel), so an NPC
    bug (wrong destination, stuck state, ...) can be diagnosed from the
    JSON alone without needing that overlay enabled at capture time."""
    ways = [
        Way(points_m=[(i * 20.0, 0.0), ((i + 1) * 20.0, 0.0)], highway="residential", half_width_m=4.5)
        for i in range(10)
    ]
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    spawned = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (180.0, 0.0))
    assert spawned is not None
    _, driver, vehicle = spawned

    data = _write_minimal_snapshot(
        tmp_path / "snapshot.json", npcs=[vehicle], npc_drivers={vehicle.vehicle_id: driver},
    )

    assert len(data["npcs"]) == 1
    npc = data["npcs"][0]
    assert npc["vehicle_id"] == vehicle.vehicle_id
    assert npc["resident_id"] == vehicle.owner_id
    assert npc["state"] == vehicle.state
    assert npc["destination"] == [180.0, 0.0]
    assert npc["way"]["highway"] == "residential"


def test_debug_snapshot_npcs_empty_without_npcs(tmp_path):
    """No NPCs (or no npc_drivers map) must not crash the snapshot - the
    common case for most of the game before/without any NPC spawned."""
    data = _write_minimal_snapshot(tmp_path / "snapshot.json")
    assert data["npcs"] == []
