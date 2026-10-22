"""Sunny summer beaches populate land activities and near-shore swimming."""
import random
from datetime import datetime
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, Polygon

from theroadragetrip import protocol
from theroadragetrip.activities.beach import BEACH_ACTIVITIES
from theroadragetrip.osm import Scenery, Water, Way, build_ways
from theroadragetrip.osm.beaches import prepare_beach
from theroadragetrip.pedestrian import PedestrianManager, SPORTS_SPAWNS_PER_CHECK
from theroadragetrip.physics import Car
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def beach_world():
    beach = Scenery([(0, 0), (100, 0), (100, 30), (0, 30)], "beach", bbox=(0, 0, 100, 30))
    water = Water([(0, 30), (100, 30), (100, 100), (0, 100)], "water", True, bbox=(0, 30, 100, 100))
    path = Way([(-10, -4), (110, -4)], "footway", 1.5)
    prepare_beach(beach, [water], [], [path])
    manager = PedestrianManager([path], target_count=0, sceneries=[beach])
    return manager, beach, water, Car(x=50, y=-10, heading=0, speed=0), (-20, -20, 120, 100)


def test_beach_locations_stay_on_dry_land_and_swim_routes_connect_to_water():
    manager, beach, water, car, view = beach_world()
    assert beach.beach_spots and beach.swim_routes
    dry, wet = Polygon(beach.points_m), Polygon(water.points_m)
    assert all(dry.contains(Point(*p)) and not wet.contains(Point(*p)) for p in beach.beach_spots)
    for land, entry, outer in beach.swim_routes:
        assert dry.contains(Point(*land))
        assert wet.covers(LineString([entry, outer]).buffer(.25))
        assert dry.union(wet).buffer(.5).covers(LineString([land, entry, outer]).buffer(.25))
    beach.swim_routes.clear()
    water.kind = "river"
    prepare_beach(beach, [water], [], [])
    assert beach.swim_routes == []


def test_warm_beach_populates_all_activities_and_swimmers_return_when_weather_closes():
    random.seed(12)
    manager, beach, water, car, view = beach_world()
    manager.sim_time = 2
    manager.ensure_sports_players(car, view)
    assert not manager.pedestrians
    manager.beach_open = True
    for _ in range(20):
        before = len(manager.pedestrians)
        manager.sim_time += 2
        manager.ensure_sports_players(car, view)
        assert len(manager.pedestrians)-before <= SPORTS_SPAWNS_PER_CHECK
    assert len(manager.pedestrians) == 16
    assert set(p.activity.plugin_id for p in manager.pedestrians) == set(BEACH_ACTIVITIES)
    assert len(protocol.shown_pedestrians(manager, car.x, car.y)) == 16
    swimmers = [p for p in manager.pedestrians if p.activity.plugin_id == "swimming"]
    states = set()
    balls = set()
    for _ in range(200):
        manager.sim_time += .1
        for player in manager.pedestrians:
            manager._update_activity(player, .1)
            states.add(player.animation_state)
            row = protocol._pedestrian_to_dict(player)
            if "beach_ball" in row:
                balls.add(tuple(round(v, 1) for v in row["beach_ball"]))
    assert {"sunbathing", "swimming"} <= states
    assert len(balls) > 10
    assert any(Polygon(water.points_m).contains(Point(p.x, p.y)) for p in swimmers)
    manager.beach_open = False
    for _ in range(300):
        manager.sim_time += .1
        for player in manager.pedestrians:
            manager._update_activity(player, .1)
    assert all(p.activity is None for p in manager.pedestrians)
    assert all(Polygon(beach.points_m).covers(Point(p.x, p.y)) for p in swimmers)
    assert not manager.activity_manager._reservations


def test_camera_cleanup_removes_beach_groups_and_reservations():
    manager, beach, water, car, view = beach_world()
    manager.beach_open = True
    for i in range(1, 10):
        manager.sim_time = i * 2
        manager.ensure_sports_players(car, view)
    manager.sim_time += 2
    manager.ensure_sports_players(car, (2000, 2000, 2100, 2100))
    assert not manager.pedestrians
    assert not manager.activity_manager._reservations


@pytest.mark.parametrize("month,temp,cloud,kind,altitude,expected", [
    (6, 16, .2, "clear", 30, True), (7, 25, 0, "clear", 30, True),
    (6, 15, .1, "clear", 30, False), (6, 14, .1, "clear", 30, False),
    (6, 20, .8, "clear", 30, False), (6, 20, .1, "rain", 30, False),
    (9, 20, .1, "clear", 30, False), (6, 20, .1, "clear", -5, False),
])
def test_beach_weather_gate_is_summer_sunny_and_strictly_above_15(tmp_path, monkeypatch, month, temp, cloud, kind, altitude, expected):
    from test_server_headless import _build_server
    from theroadragetrip.weather import WeatherType

    server = _build_server(tmp_path, monkeypatch)
    server.calendar.current = datetime(2026, month, 19, 14)
    server.world.weather.outside_temperature_c = temp
    server.world.weather.cloud_cover = cloud
    server.world.weather.weather_type = WeatherType(kind)
    server.world.weather.is_thunderstorm = False
    monkeypatch.setattr(server, "_sun_altitude", lambda: altitude)
    server._update_sports()
    assert server.world.pedestrian_mgr.beach_open is expected
    plugin = server.world.pedestrian_mgr.activity_manager.registry.get("beach_volleyball")
    assert plugin.can_start(SimpleNamespace(pedestrian_manager=server.world.pedestrian_mgr)) is expected


def test_osm_beach_water_metadata_survives_cache(tmp_path):
    nodes = [(60,25), (60,25.001), (60.0003,25.001), (60.0003,25), (60.001,25.001), (60.001,25)]
    elements = [dict(type="node",id=i,lat=lat,lon=lon) for i,(lat,lon) in enumerate(nodes,1)]
    elements += [dict(type="way",id=10,nodes=[1,2,3,4,1],tags={"natural":"beach"}),
                 dict(type="way",id=11,nodes=[4,3,5,6,4],tags={"natural":"water"})]
    world = build_ways(elements)
    beach, = world.sceneries
    assert beach.beach_spots and beach.swim_routes
    path = tmp_path / "beach.rwc"
    BinaryWorldCacheWriter().write(path,world,area_id="beach")
    loaded = BinaryWorldCacheLoader().load(path).sceneries[0]
    assert loaded.beach_spots == beach.beach_spots
    assert loaded.swim_routes == beach.swim_routes


def test_disconnected_water_and_blocked_shore_do_not_create_swim_routes():
    manager, beach, water, car, view = beach_world()
    beach.swim_routes.clear()
    road = Way([(-10, 30), (110, 30)], "residential", 3)
    prepare_beach(beach, [water], [], [road])
    assert not beach.swim_routes
    beach.swim_routes.clear()
    water.points_m = [(0, 50), (100, 50), (100, 100), (0, 100)]
    water.bbox = (0, 50, 100, 100)
    prepare_beach(beach, [water], [], [])
    assert not beach.swim_routes
