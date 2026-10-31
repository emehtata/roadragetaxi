"""Digitraffic road data (digitraffic_road.py, docs/digitraffic-road-data.md):
the cached client, roadwork parsing and timing, and matching onto roads.
No network: a recorded Oulu response (2026-10-26) and fake openers."""
import gzip
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pyproj import Transformer

from theroadragetrip import digitraffic_road as dr
from theroadragetrip.calendar import FINLAND_TZ
from theroadragetrip.osm import Way
from theroadragetrip.physics import SpatialWayGrid

FIXTURE = Path(__file__).parent / "fixtures" / "digitraffic_roadworks_oulu.json.gz"
KUUSAMONTIE = "GUID50472677"  # road 20, 30 km/h over 600 m, a lane closed; Wed 10-14 local, liftable
PROJECT = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True).transform


def _collection():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


def _kuusamontie():
    return next(w for w in dr.parse_roadworks(_collection()) if w.situation_id == KUUSAMONTIE)


def _local(year, month, day, hour, minute=0):
    local = datetime(year, month, day, hour, minute, tzinfo=FINLAND_TZ)
    return local.astimezone(timezone.utc), local


class FakeOpener:
    def __init__(self, body=b'{"type": "FeatureCollection", "features": []}', fail=False):
        self.body, self.fail, self.calls = body, fail, []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        if self.fail:
            raise OSError("offline")
        return self.body


@pytest.mark.parametrize("compressed,deprecated", [(True, True), (False, False)])
def test_http_opener_handles_compression_timeout_and_deprecation(monkeypatch, caplog, compressed, deprecated):
    import io
    import logging
    body = b'{"features": []}'
    response = io.BytesIO(gzip.compress(body) if compressed else body)
    response.headers = {}
    if compressed:
        response.headers["Content-Encoding"] = "gzip"
    if deprecated:
        response.headers.update({"Deprecation": "true", "Sunset": "2027-01-01"})
    calls = []

    def urlopen(request, timeout):
        calls.append((request.full_url, dict(request.header_items()), timeout))
        return response

    monkeypatch.setattr(dr.urllib.request, "urlopen", urlopen)
    with caplog.at_level(logging.WARNING, logger=dr.__name__):
        assert dr._default_opener("https://example.invalid/works", {"Accept-Encoding": "gzip"}) == body
    assert calls == [("https://example.invalid/works", {"Accept-encoding": "gzip"}, dr.TIMEOUT_S)]
    assert ("deprecated" in caplog.text) is deprecated
    if deprecated:
        assert "2027-01-01" in caplog.text


# -- parsing and timing ---------------------------------------------------------

def test_a_recorded_roadwork_parses_with_its_real_restrictions():
    works = dr.parse_roadworks(_collection())
    assert len(works) == 8 and all(w.phases for w in works)
    work = _kuusamontie()
    assert work.road == 20 and "Kuusamontie" in work.title
    (phase,) = work.phases
    assert phase.restrictions["speed limit"] == 30.0 and phase.restrictions["speed limit length"] == 600.0
    assert "single lane closed" in phase.restrictions and phase.liftable
    assert phase.working_hours == [(2, 600, 840)]  # Wednesday 10:00-14:00
    assert len(work.lines_ll) == 4 and all(len(line) >= 2 for line in work.lines_ll)


def test_a_liftable_phase_is_in_force_only_in_its_working_hours_on_its_dates():
    phase = _kuusamontie().phases[0]
    assert phase.active(*_local(2026, 10, 28, 11))  # Wednesday 11:00
    assert not phase.active(*_local(2026, 10, 28, 15))  # lifted after 14:00
    assert not phase.active(*_local(2026, 10, 27, 11))  # Tuesday: before its dates
    phase.liftable = False
    assert phase.active(*_local(2026, 10, 28, 15))  # not liftable: in force all day


def test_malformed_features_are_skipped_and_the_newest_version_wins():
    good = _collection()["features"][0]
    older = json.loads(json.dumps(good))
    older["properties"]["version"] = good["properties"]["version"] - 1
    older["properties"]["announcements"][0]["title"] = "old"
    broken = {"type": "Feature", "geometry": None, "properties": {}}
    works = dr.parse_roadworks({"features": [older, broken, good, {"nonsense": 1}]})
    assert len(works) == 1 and works[0].title != "old"
    assert dr.parse_roadworks(None) == [] and dr.parse_roadworks({}) == []


# -- queries and the permanent cache --------------------------------------------

def test_a_query_is_one_snapped_tile_and_one_window_so_it_repeats_exactly():
    moment = datetime(2026, 10, 28, 9, 7, 30, tzinfo=timezone.utc)
    start = dr.window_start(moment)
    assert start == datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
    tile = dr.tile_of(25.53, 65.03)
    params = dr.roadworks_params(tile, start)
    assert params["xMin"] <= 25.53 < params["xMax"] and params["yMin"] <= 65.03 < params["yMax"]
    assert params["from"] == "2026-10-28T09:00:00Z" and params["to"] == "2026-10-28T09:15:00Z"
    assert dr.roadworks_params(dr.tile_of(25.55, 65.04), dr.window_start(moment.replace(minute=14))) == params


def test_queries_are_cached_forever_and_survive_a_restart(tmp_path):
    opener = FakeOpener(json.dumps(_collection()).encode())
    path = tmp_path / "road.sqlite"
    client = dr.DigitrafficClient(path, opener)
    params = {"xMin": 25.2, "from": "2026-10-28T09:00:00Z"}
    assert len(client.get_json("/api/traffic-message/v2/roadworks", params)["features"]) == 8
    assert client.get_json("/api/traffic-message/v2/roadworks", params) is not None
    assert len(opener.calls) == 1  # the second one came from the cache
    url, headers = opener.calls[0]
    assert headers["Accept-Encoding"] == "gzip" and headers["Digitraffic-User"].startswith("RoadRageTrip")
    assert url.startswith(dr.BASE_URL + "/api/traffic-message/v2/roadworks?")
    again = dr.DigitrafficClient(path, FakeOpener(fail=True))  # a restart, offline
    assert len(again.get_json("/api/traffic-message/v2/roadworks", params)["features"]) == 8


def test_failures_are_not_cached_and_retry_after_a_backoff():
    now = [0.0]
    opener = FakeOpener(fail=True)
    client = dr.DigitrafficClient(None, opener, clock=lambda: now[0])
    assert client.get_json("/x") is None and client.get_json("/x") is None
    assert len(opener.calls) == 1  # backing off
    now[0] = dr.RETRY_S[0] + 1
    opener.fail = False
    assert client.get_json("/x") == {"type": "FeatureCollection", "features": []} and len(opener.calls) == 2


def test_invalid_json_is_never_cached():
    opener = FakeOpener(b"<html>maintenance</html>")
    client = dr.DigitrafficClient(None, opener, clock=lambda: 1e9)
    assert client.get_json("/x") is None and client.cached(client.url("/x")) is None


def test_the_service_fetches_the_tiles_around_the_player_off_the_simulation_thread():
    client = dr.DigitrafficClient(None, FakeOpener(json.dumps(_collection()).encode()))
    unproject = Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True).transform
    service = dr.RoadDataService(client, unproject)
    try:
        x, y = PROJECT(25.53, 65.03)
        service.request(x, y, datetime(2026, 10, 28, 9, 5, tzinfo=timezone.utc))
        service.wait_idle(5.0)
        assert {w.situation_id for w in service.roadworks} >= {KUUSAMONTIE} and service.revision >= 1
        fetched = client.fetched
        service.request(x + 50, y, datetime(2026, 10, 28, 9, 10, tzinfo=timezone.utc))  # same tiles, same window
        service.wait_idle(1.0)
        assert client.fetched == fetched
    finally:
        service.close()


@pytest.mark.parametrize("versions", [(2, 1), (1, 2)])
def test_newest_version_wins_across_neighboring_tiles(monkeypatch, versions):
    monkeypatch.setattr(dr, "tiles_near", lambda *a: [(0, 0), (1, 0)])
    responses = []
    for version in versions:
        feature = _collection()["features"][0]
        feature["properties"]["version"] = version
        responses.append(json.dumps({"features": [feature]}).encode())
    client = dr.DigitrafficClient(None, lambda url, headers: b'{"features":[]}' if 'variable-sign' in url else responses.pop(0))
    service = dr.RoadDataService(client, lambda x, y: (x, y))
    try:
        service.request(0, 0, datetime(2026, 10, 26, tzinfo=timezone.utc))
        service.wait_idle(2)
        assert client.fetched == 3  # two roadwork tiles and the electronic-sign catalogue
        assert [w.version for w in service.roadworks] == [2]
    finally:
        service.close()


# -- matching onto the game's roads ----------------------------------------------

def _road_along(lines, ref="20", offset_m=0.0, highway="trunk"):
    """A road through the roadwork's own points (sorted west to east, one
    carriageway's worth), extended 300 m each way and shifted sideways."""
    points = sorted(PROJECT(lon, lat) for line in lines for lon, lat in line)
    dx, dy = points[-1][0] - points[0][0], points[-1][1] - points[0][1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    shifted = [(x - uy * offset_m, y + ux * offset_m) for x, y in points]
    start = (shifted[0][0] - ux * 300, shifted[0][1] - uy * 300)
    end = (shifted[-1][0] + ux * 300, shifted[-1][1] + uy * 300)
    return Way(points_m=[start] + shifted + [end], highway=highway, half_width_m=4.0, ref=ref, speed_limit_kmh=60)


def test_a_live_roadwork_lands_on_its_road_with_its_speed_limit_and_closed_lane():
    work = _kuusamontie()
    road = _road_along(work.lines_ll)
    zones = dr.match_roadwork(work, work.phases[0], PROJECT, SpatialWayGrid([road]))
    assert zones and all(z.way is road for z in zones)
    assert all(z.end_m - z.start_m <= dr.PIECE_M + 1e-6 for z in zones)
    speed = sum(z.end_m - z.start_m for z in zones)
    works = sum(z.end_m - z.start_m for z in zones if z.lane_closed)
    assert speed == pytest.approx(600.0, abs=1.0)  # the stated speed-limit length, around the works
    assert 30.0 < works < 120.0  # the lane is closed only where the work is
    assert all(z.speed_limit_kmh == 30 and not z.blocks and z.source == "digitraffic" for z in zones)


def test_the_road_number_beats_a_closer_parallel_road():
    import dataclasses
    real = _kuusamontie()
    ends = sorted(p for line in real.lines_ll for p in line)
    work = dataclasses.replace(real, lines_ll=[[ends[0], ends[-1]]])  # one clean line between its real ends
    vt20 = _road_along(work.lines_ll, ref="20", offset_m=3.0)
    service_road = _road_along(work.lines_ll, ref=None, offset_m=0.0, highway="service")
    zones = dr.match_roadwork(work, work.phases[0], PROJECT, SpatialWayGrid([vt20, service_road]))
    assert zones and all(z.way is vt20 for z in zones)


def test_a_roadwork_that_does_not_fit_the_loaded_roads_is_not_placed():
    work = _kuusamontie()
    x, y = PROJECT(*work.lines_ll[0][0])
    crossing = Way(points_m=[(x, y - 300), (x, y + 300)], highway="trunk", half_width_m=4.0)  # heading 90 deg off
    far = Way(points_m=[(x + 500, y), (x + 900, y)], highway="trunk", half_width_m=4.0)
    assert dr.match_roadwork(work, work.phases[0], PROJECT, SpatialWayGrid([crossing, far])) == []


def test_a_closed_road_blocks_and_a_closed_lane_only_closes_its_half():
    work = _kuusamontie()
    road = _road_along(work.lines_ll)
    closed = dr.RoadworkPhase(work.phases[0].start, None, restrictions={"road closed": None})
    (zone, *_) = dr.match_roadwork(work, closed, PROJECT, SpatialWayGrid([road]))
    assert zone.blocks and not zone.lane_closed and zone.speed_limit_kmh is None
    lane = next(z for z in dr.match_roadwork(work, work.phases[0], PROJECT, SpatialWayGrid([road])) if z.lane_closed)
    mx, my = (lane.start[0] + lane.end[0]) / 2, (lane.start[1] + lane.end[1]) / 2
    dx, dy = lane.end[0] - lane.start[0], lane.end[1] - lane.start[1]
    length = math.hypot(dx, dy)
    right, left = (mx + dy / length * 2, my - dx / length * 2), (mx - dy / length * 2, my + dx / length * 2)
    assert lane.in_closed_lane(*right) and not lane.in_closed_lane(*left)


def test_live_roadworks_follow_the_game_clock_and_set_the_speed_limit():
    work = _kuusamontie()
    road = _road_along(work.lines_ll)

    class Service:
        roadworks, revision = [work], 1

        def request(self, *a):
            pass

    live = dr.LiveRoadworks(Service(), PROJECT)
    grid = SpatialWayGrid([road])
    live.update(0, 0, *_local(2026, 10, 28, 11), 1, grid)
    zone = live.zones[0]
    mx, my = (zone.start[0] + zone.end[0]) / 2, (zone.start[1] + zone.end[1]) / 2
    assert live.speed_limit_at(mx, my) == 30 and live.speed_limit_at(mx + 500, my + 500) is None
    live.update(0, 0, *_local(2026, 10, 28, 15), 1, grid)  # lifted after the working hours
    assert live.zones == [] and live.speed_limit_at(mx, my) is None


def test_cached_bodies_are_stored_compressed(tmp_path):
    path = tmp_path / "road.sqlite"
    client = dr.DigitrafficClient(path, FakeOpener(json.dumps(_collection()).encode()))
    client.get_json("/a")
    import sqlite3
    (body,) = sqlite3.connect(path).execute("SELECT body FROM responses").fetchone()
    assert json.loads(gzip.decompress(body))["features"]


# -- in the game ----------------------------------------------------------------

def _synthetic_work(lines, **restrictions):
    phase = dr.RoadworkPhase(datetime(2026, 1, 1, tzinfo=timezone.utc), None, restrictions=restrictions)
    return dr.LiveRoadwork("test", 1, "works", None, lines, [phase])


@pytest.mark.parametrize("reverse", [False, True])
def test_disjoint_sections_do_not_close_the_clear_road_between_them(reverse):
    lines = [[(0, 0), (50, 0)], [(950, 0), (1000, 0)]]
    if reverse:
        lines = [list(reversed(line)) for line in reversed(lines)]
    work = _synthetic_work(lines, **{"road closed": None})
    road = Way([(0, 0), (1000, 0)], "primary", 4)
    zones = dr.match_roadwork(work, work.phases[0], lambda x, y: (x, y), SpatialWayGrid([road]))
    assert sum(z.end_m - z.start_m for z in zones) == pytest.approx(100)
    assert any(z.contains(25, 0) and z.blocks for z in zones)
    assert any(z.contains(975, 0) and z.blocks for z in zones)
    assert not any(z.contains(500, 0) for z in zones)


def test_overlapping_and_touching_work_lines_merge_without_duplicate_zones():
    work = _synthetic_work([[(0, 0), (70, 0)], [(50, 0), (100, 0)], [(100, 0), (150, 0)]],
                           **{"road closed": None})
    road = Way([(0, 0), (200, 0)], "primary", 4)
    zones = dr.match_roadwork(work, work.phases[0], lambda x, y: (x, y), SpatialWayGrid([road]))
    assert sum(z.end_m - z.start_m for z in zones) == pytest.approx(150)
    assert len(zones) == 3


def test_point_roadworks_get_an_extent_but_do_not_match_non_drivable_roads():
    work = _synthetic_work([[(100, 0)]], **{"road closed": None})
    road = Way([(0, 0), (200, 0)], "primary", 4)
    grid = SpatialWayGrid([road])
    (zone,) = dr.match_roadwork(work, work.phases[0], lambda x, y: (x, y), grid)
    assert (zone.start_m, zone.end_m) == (80, 120)
    road.is_drivable = False
    assert dr.match_roadwork(work, work.phases[0], lambda x, y: (x, y), grid) == []


def test_a_speed_limit_can_cover_gaps_without_closing_them_or_duplicating_its_length():
    work = _synthetic_work([[(100, 0), (150, 0)], [(200, 0), (250, 0)]],
                           **{"road closed": None, "speed limit": 30, "speed limit length": 300})
    road = Way([(0, 0), (400, 0)], "primary", 4)
    zones = dr.match_roadwork(work, work.phases[0], lambda x, y: (x, y), SpatialWayGrid([road]))
    assert sum(z.end_m - z.start_m for z in zones) == pytest.approx(300)
    assert sum(z.end_m - z.start_m for z in zones if z.blocks) == pytest.approx(100)
    assert any(z.contains(175, 0) and z.speed_limit_kmh == 30 for z in zones)
    assert not any(z.contains(175, 0) and z.blocks for z in zones)


def _straight_zone(**kwargs):
    from theroadragetrip.roadworks import Roadwork
    road = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="trunk", half_width_m=4.0, speed_limit_kmh=80)
    return Roadwork(road, 50.0, 100.0, kwargs.pop("lane_closed", True), (50.0, 0.0), (100.0, 0.0), **kwargs)


def test_the_taxi_is_stopped_only_by_a_live_zones_closed_lane_but_wholly_by_a_generated_one():
    from theroadragetrip.simulation import _roadwork_bars
    live = _straight_zone(blocks=False, speed_limit_kmh=30, source="digitraffic")
    assert _roadwork_bars(live, 75.0, -2.0)  # right of the way's direction (east): the closed lane
    assert not _roadwork_bars(live, 75.0, 2.0)  # the open lane
    assert not _roadwork_bars(live, 150.0, -2.0)  # past the zone
    generated = _straight_zone()
    assert _roadwork_bars(generated, 75.0, 2.0) and _roadwork_bars(generated, 75.0, -2.0)
    closed = _straight_zone(lane_closed=False, blocks=True, source="digitraffic")
    assert _roadwork_bars(closed, 75.0, 2.0)


@pytest.mark.parametrize("work_layer,car_layer,work_level,car_level,applies", [
    (1, 0, None, 0, False), (0, 1, None, 0, False),
    (1, 1, None, 0, True), (0, 0, None, 0, True),
    (0, 0, None, -1, False), (0, 0, -1, -1, True),
])
def test_roadwork_blocks_and_speed_limits_stay_on_their_layer(work_layer, car_layer, work_level, car_level, applies):
    from types import SimpleNamespace
    from theroadragetrip.protocol import _live_limit
    from theroadragetrip.simulation import _roadwork_bars
    zone = _straight_zone(blocks=True, speed_limit_kmh=30, source="digitraffic")
    zone.way.layer, zone.way.map_level = work_layer, work_level
    live = dr.LiveRoadworks(SimpleNamespace(), lambda x, y: (x, y))
    live.zones = [zone]
    car = SimpleNamespace(x=75.0, y=1.0, layer=car_layer, map_level=car_level)
    assert _roadwork_bars(zone, car.x, car.y, layer=car.layer, map_level=car.map_level) is applies
    assert _live_limit(SimpleNamespace(live_roadworks=live), car) == (30 if applies else None)


def test_the_hud_limit_and_state_carry_the_live_roadwork():
    from types import SimpleNamespace
    from theroadragetrip import protocol
    zone = _straight_zone(blocks=False, speed_limit_kmh=30, source="digitraffic", situation_id="GUID1")
    live = dr.LiveRoadworks(SimpleNamespace(), lambda x, y: (x, y))
    live.zones = [zone]
    world = SimpleNamespace(live_roadworks=live)
    assert protocol._road_to_dict(zone.way, protocol._live_limit(world, SimpleNamespace(x=75.0, y=1.0)))["speed_limit_kmh"] == 30
    assert protocol._road_to_dict(zone.way, protocol._live_limit(world, SimpleNamespace(x=150.0, y=1.0)))["speed_limit_kmh"] == 80
    (row,) = protocol._live_roadworks(world, 75.0, 0.0)
    assert row["speed_limit_kmh"] == 30 and row["lane_closed"] and not row["closed"] and row["id"] == "GUID1"
    assert protocol._live_roadworks(world, 75.0 + 5000.0, 0.0) == []  # far from the camera: not sent
    assert protocol._live_roadworks(SimpleNamespace(), 0.0, 0.0) == []  # the setting off


def test_realtime_road_data_is_opt_in(monkeypatch):
    import configparser
    import sys
    from theroadragetrip.config import DEFAULT_CONFIG
    from theroadragetrip.game_args import parse_args
    config = configparser.ConfigParser()
    config.read_dict(DEFAULT_CONFIG)
    monkeypatch.setattr(sys, "argv", ["server"])
    assert not parse_args(config).road_digitraffic
    monkeypatch.setattr(sys, "argv", ["server", "--road-digitraffic"])
    assert parse_args(config).road_digitraffic
    config.set("game", "road_digitraffic", "true")
    monkeypatch.setattr(sys, "argv", ["server", "--no-road-digitraffic"])
    assert not parse_args(config).road_digitraffic


def test_a_streaming_map_does_not_rematch_every_tick(caplog):
    """The loaded roads change almost every tick while the map streams in:
    matching reruns for them at most every REMATCH_ON_MAP_GROWTH_S, the
    geometry is projected once per version, and the log line only changes
    with the placement (a user's log once had it 30 times a second)."""
    import logging
    work = _kuusamontie()
    road = _road_along(work.lines_ll)
    projections = []

    def project(lon, lat):
        projections.append((lon, lat))
        return PROJECT(lon, lat)

    class Service:
        roadworks, revision = [work], 1

        def request(self, *a):
            pass

    now = [0.0]
    live = dr.LiveRoadworks(Service(), project, clock=lambda: now[0])
    grid = SpatialWayGrid([road])
    moment = _local(2026, 10, 28, 11)
    with caplog.at_level(logging.INFO, logger="theroadragetrip.digitraffic_road"):
        for tick in range(300):  # 10 s at 30 Hz, a new road loaded every tick
            now[0] = tick / 30
            live.update(0, 0, *moment, 1000 + tick, grid)
    assert live.matches == 2  # the first tick, then once after REMATCH_ON_MAP_GROWTH_S (not 300 times)
    assert len(projections) == sum(len(line) for line in work.lines_ll)  # projected once
    assert len([r for r in caplog.records if "zones placed" in r.message]) == 1
    Service.revision = 2  # new data is matched at once, map growth or not
    live.update(0, 0, *moment, 1300, grid)
    assert live.matches == 3


def test_the_permanent_cache_is_outside_the_map_cache_that_clear_cache_empties(tmp_path, monkeypatch):
    from pathlib import Path
    from theroadragetrip import osm
    from theroadragetrip.osm.cache import clear_osm_cache, default_cache_root
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    root = Path(default_cache_root())
    map_cache = root / "osm_cache"
    map_cache.mkdir(parents=True)
    (map_cache / "tile.osm").write_text("x")
    road_cache = root / "digitraffic_road.sqlite"  # where the server keeps it
    dr.DigitrafficClient(road_cache, FakeOpener()).get_json("/x")
    monkeypatch.setattr(osm, "CACHE_DIR", str(map_cache))
    assert clear_osm_cache() == 1 and road_cache.exists()
    assert dr.DigitrafficClient(road_cache, FakeOpener(fail=True)).get_json("/x") is not None


def test_console_debug_locates_loaded_and_placed_roadworks_without_logging_each_tick(caplog):
    import logging
    from types import SimpleNamespace

    work = _kuusamontie()
    service = SimpleNamespace(roadworks=[work], revision=1, request=lambda *a: None)
    live = dr.LiveRoadworks(service, PROJECT)
    moment = _local(2026, 10, 28, 11)
    grid = SpatialWayGrid([_road_along(work.lines_ll)])
    with caplog.at_level(logging.DEBUG, logger='theroadragetrip.digitraffic_road'):
        live.update(0, 0, *moment, 1, grid)
        messages = [r.getMessage() for r in caplog.records]
        loaded = next(m for m in messages if 'lines_lon_lat=' in m)
        assert work.situation_id in loaded and repr(work.title) in loaded and 'road=20' in loaded
        assert str(work.lines_ll) in loaded and 'active=True' in loaded
        assert f'placed_zones={len(live.zones)}' in loaded
        zone = live.zones[0]
        assert any(f'start_xy_m=({zone.start[0]:.2f}, {zone.start[1]:.2f})' in m
                   and f'end_xy_m=({zone.end[0]:.2f}, {zone.end[1]:.2f})' in m for m in messages)
        count = len(caplog.records)
        for _ in range(30):
            live.update(0, 0, *moment, 1, grid)
        assert len(caplog.records) == count
        # Source positions remain visible even when no loaded road matches them.
        service.revision += 1
        live.update(0, 0, *moment, 2, SpatialWayGrid([]))
        assert 'active=True placed_zones=0' in caplog.records[-1].getMessage()
        assert str(work.lines_ll) in caplog.records[-1].getMessage()
        live.update(0, 0, *_local(2026, 10, 28, 15), 2, grid)
        assert 'active=False placed_zones=0' in caplog.records[-1].getMessage()
