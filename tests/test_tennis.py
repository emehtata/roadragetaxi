"""Outdoor courts, weather gating and a complete two-player rally lifecycle."""
from datetime import datetime
from types import SimpleNamespace

import pytest
from shapely.geometry import Point, Polygon

from theroadragetrip import protocol
from theroadragetrip.activities.plugins.tennis import add_point, landing, point_plan, point_winner, prepare_court, rally_spot
from theroadragetrip.map_chunks import ChunkIndex
from theroadragetrip.osm import Scenery, Way, build_ways
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.physics import Car
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def tennis_world():
    court = Scenery([(0,0),(32,0),(32,16),(0,16)], "pitch", sport="tennis", bbox=(0,0,32,16))
    prepare_court(court)
    way = Way([(-10,-4),(40,-4)], "footway", 1.5)
    manager = PedestrianManager([way], target_count=0, sceneries=[court])
    car = Car(x=16, y=-8, heading=0, speed=0)
    return manager, court, car, (-20,-20,50,40)


def test_court_geometry_and_chunk_markings():
    manager, court, car, view = tennis_world()
    assert court.tennis_frame
    world = SimpleNamespace(ways=[], railways=[], buildings=[], waters=[], sceneries=[court])
    index = ChunkIndex(world)
    assert any(chunk["tennis_courts"] == [court.tennis_frame] for chunk in index._chunks.values())
    court.points_m = [(0,0),(30,0),(30,5),(5,5),(5,15),(0,15)]
    court.tennis_frame = []
    prepare_court(court)
    assert not court.tennis_frame  # enclosing rectangle would put players outside this L-shaped pitch


def test_two_players_rally_bounce_swing_and_leave_when_weather_closes():
    manager, court, car, view = tennis_world()
    manager.sim_time = 2
    manager.ensure_sports_players(car, view)
    assert not manager.pedestrians
    manager.tennis_open = True
    for _ in range(5):
        manager.sim_time += 2
        manager.ensure_sports_players(car, view)
    assert len(manager.pedestrians) == 2
    assert all(p.activity.plugin_id == "tennis" for p in manager.pedestrians)
    assert len(protocol.shown_pedestrians(manager, car.x, car.y)) == 2
    balls, heights, swings, positions = [], [], set(), set()
    for _ in range(320):
        manager.sim_time += .05
        for p in manager.pedestrians:
            manager._update_activity(p, .05)
            assert Polygon(court.points_m).contains(Point(p.x,p.y))
            if p.stick_swing > .1:
                swings.add(p.resident_id)
            positions.add((p.resident_id,round(p.x,1),round(p.y,1)))
        rows = [protocol._pedestrian_to_dict(p) for p in manager.pedestrians]
        ball_rows = [row["tennis_ball"] for row in rows if "tennis_ball" in row]
        assert len(ball_rows) == 1
        x,y,z = ball_rows[0]
        assert Polygon(court.points_m).contains(Point(x,y))
        balls.append((x,y)); heights.append(z)
    assert len(set(balls)) > 100 and len(positions) > 30
    assert min(heights) < .05 and max(heights) > 1
    assert len(swings) == 2
    manager.tennis_open = False
    for p in manager.pedestrians:
        manager._update_activity(p, .1)
    assert all(p.activity is None and p.stick_swing == 0 for p in manager.pedestrians)


def test_camera_cleanup_releases_whole_tennis_group():
    manager, court, car, view = tennis_world()
    manager.tennis_open = True
    manager.sim_time = 2
    manager.ensure_sports_players(car,view)
    group = manager.pedestrians[0].activity.group
    manager.sim_time += 2
    manager.ensure_sports_players(car,(1000,1000,1100,1100))
    assert not manager.pedestrians and not group.member_resident_ids


@pytest.mark.parametrize("tags,eligible", [({},True),({"indoor":"yes"},False),({"layer":"1"},False),({"level":"-1"},False)])
def test_osm_outdoor_courts_only_and_cached_geometry(tmp_path,tags,eligible):
    elements = [dict(type="node",id=i,lat=lat,lon=lon) for i,(lat,lon) in enumerate(
        [(60,25),(60,25.0006),(60.00015,25.0006),(60.00015,25)],1)]
    elements += [dict(type="way",id=10,nodes=[1,2,3,4,1],tags={"leisure":"pitch","sport":"tennis",**tags})]
    world = build_ways(elements)
    assert bool(world.sceneries[0].tennis_frame) is eligible
    path = tmp_path / "tennis.rwc"
    BinaryWorldCacheWriter().write(path,world,area_id="tennis")
    assert BinaryWorldCacheLoader().load(path).sceneries[0].tennis_frame == world.sceneries[0].tennis_frame


@pytest.mark.parametrize("temp,cloud,kind,thunder,altitude,expected", [
    (18,.2,"clear",False,30,True),(12,.5,"clear",False,30,True),(10,.2,"clear",False,30,False),
    (20,.9,"clear",False,30,False),(20,.2,"rain",False,30,False),(20,.2,"clear",True,30,False),
    (20,.2,"clear",False,-5,False),
])
def test_nice_weather_gate(tmp_path,monkeypatch,temp,cloud,kind,thunder,altitude,expected):
    from test_server_headless import _build_server
    from theroadragetrip.weather import WeatherType
    server = _build_server(tmp_path,monkeypatch)
    server.calendar.current = datetime(2026,6,19,14)
    server.world.weather.outside_temperature_c = temp
    server.world.weather.cloud_cover = cloud
    server.world.weather.weather_type = WeatherType(kind)
    server.world.weather.is_thunderstorm = thunder
    server.world.fields_frozen = False
    monkeypatch.setattr(server,"_sun_altitude",lambda:altitude)
    server._update_sports()
    assert server.world.pedestrian_mgr.tennis_open is expected


def test_rally_spots_stay_inside_the_court_and_vary_in_depth():
    for side in (0, 1):
        spots = [rally_spot(side, turn) for turn in range(200)]
        assert all(.29 < abs(u) <= .42 and abs(v) < .3 for u, v in spots)
        assert all((u < 0) == (side == 0) for u, _ in spots)  # each keeps their own half
        depths = [abs(u) for u, _ in spots]
        assert max(depths) - min(depths) > .08


def test_points_end_in_the_net_out_or_as_winners_and_are_scored():
    plans = [point_plan(i) for i in range(300)]
    assert {outcome for _, outcome in plans} == {"net", "out", "winner"}
    assert all(1 <= shots <= 8 for shots, _ in plans)
    assert point_winner(0, 3, "winner") == 0 and point_winner(0, 3, "net") == 1  # server hit shots 0 and 2
    score, games = [0, 0], [0, 0]
    for won in (0, 0, 0, 1, 1, 1, 0):  # 40-40, then advantage
        add_point(score, games, won)
    assert games == [0, 0] and score == [4, 3]
    add_point(score, games, 0)
    assert games == [1, 0] and score == [0, 0]


def test_a_last_shot_lands_at_the_net_past_a_line_or_inside_away_from_the_receiver():
    assert landing("net", 1, .2, 0)[0] == 0
    u, v = landing("out", 1, .2, .2)
    assert u > .42 or abs(v) > .3
    u, v = landing("out", 0, .2, .9)
    assert u < 0 and abs(v) > .3
    u, v = landing("winner", 1, .1, 0)
    assert 0 < u < .42 and abs(v) < .3
