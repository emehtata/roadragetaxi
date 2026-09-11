"""Tests for the debug-snapshot JSON writer."""
import json
import types

from theroadragetrip.main.debug_tools import _write_debug_snapshot
from theroadragetrip.physics import Car
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
