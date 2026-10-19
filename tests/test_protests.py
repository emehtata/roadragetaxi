from datetime import datetime
import math
from types import SimpleNamespace
import time

import pytest

from theroadragetrip.osm import Building, Way, Water
from theroadragetrip.physics import Car, SpatialWayGrid
from theroadragetrip.protests import ProtestGroup, ProtestManager, ProtestSettings


def fixture():
    way = Way([(200, 0), (400, 0)], "residential", 4.5, osm_id=1)
    world = SimpleNamespace(ways=[way], buildings=[], waters=[], railways=[], roadworks=[],
                            npc_manager=SimpleNamespace(vehicles=[]), pedestrian_mgr=SimpleNamespace(pedestrians=[]))
    world.spatial_grid = SpatialWayGrid(world.ways)
    car = Car(x=0, y=0, heading=0, speed=0)
    manager = ProtestManager(ProtestSettings(spawn_probability=1.0), "Oulu")
    return manager, world, way, car


def tick(manager, world, car, seconds, sim_time=0):
    for i in range(round(seconds*10)):
        manager.update(0.1, world, car, datetime(2026, 10, 19, 12), sim_time+i/10)


def test_deterministic_daytime_spawn_and_no_night_spawn():
    a, world, way, car = fixture()
    b, _, _, _ = fixture()
    for m in (a, b):
        m.update(0.1, world, car, datetime(2026, 10, 19, 2), 0)
        assert not m.groups
        m.update(0.1, world, car, datetime(2026, 10, 19, 12), 1)
        assert len(m.groups) == 1
    assert a.snapshot(300, 0) == b.snapshot(300, 0)
    assert len(a.snapshot(300, 0)[0]["members"]) == 24
    assert a.groups[0].state == "SITTING"
    assert not a.can_spawn(world, way, 300, 0, 0, car)  # no overlapping events


def test_config_limits_disable_and_overnight_schedule():
    import configparser

    config = configparser.ConfigParser()
    config.read_dict({"protests": {"max_groups": "999", "group_size": "999", "clearing_s": "0",
                                    "enabled": "false", "schedule": "Su 22:00-02:00"}})
    settings = ProtestSettings.from_config(config)
    assert settings.max_groups == 8 and settings.group_size == 80 and settings.clearing_s == 1
    m, world, way, car = fixture()
    m = ProtestManager(settings)
    assert m.scheduled(datetime(2026, 10, 19, 1))
    m.update(1, world, car, datetime(2026, 10, 19, 1), 0)
    assert not m.groups
    m = ProtestManager(ProtestSettings(schedule="unsupported"))
    assert not m.scheduled(datetime(2026, 10, 19, 12))


def test_multiple_spawn_attempts_respect_group_limit():
    m, world, way, car = fixture()
    m.settings.max_groups = 1
    for i in range(10):
        m.update(0.1, world, car, datetime(2026, 10, 19, 12), i*31)
    assert len(m.groups) == 1


@pytest.mark.parametrize("change", [{"highway": "motorway"}, {"is_bridge": True}, {"is_tunnel": True},
                                  {"map_level": -1}, {"layer": 1}, {"speed_limit_kmh": 80}, {"is_drivable": False}, {"is_roundabout": True}])
def test_reject_unsuitable_roads(change):
    m, world, way, car = fixture()
    for key, value in change.items():
        setattr(way, key, value)
    assert not m.can_spawn(world, way, 300, 0, 0, car)


def test_reject_player_junction_building_water_and_occupied_roadside():
    m, world, way, car = fixture()
    assert m.can_spawn(world, way, 300, 0, 0, car)
    assert not m.can_spawn(world, way, 20, 0, 0, car)
    world.ways.append(Way([(300, -100), (300, 100)], "residential", 4))
    world.spatial_grid = SpatialWayGrid(world.ways)
    assert not m.can_spawn(world, way, 300, 0, 0, car)
    world.ways.pop()
    world.spatial_grid = SpatialWayGrid(world.ways)
    polygon = [(290, 4.6), (310, 4.6), (310, 12), (290, 12)]
    world.buildings = [Building(polygon)]
    assert not m.can_spawn(world, way, 300, 0, 0, car)
    world.buildings = []
    world.waters = [Water(polygon, "water", True)]
    assert not m.can_spawn(world, way, 300, 0, 0, car)
    world.waters = []
    world.pedestrian_mgr.pedestrians = [SimpleNamespace(x=300, y=6)]
    assert not m.can_spawn(world, way, 300, 0, 0, car)


@pytest.mark.parametrize("heading", [0, math.pi/2, math.pi, -math.pi/4])
def test_swept_vehicle_collision_covers_width_and_keeps_bridge_layers_separate(heading):
    m, world, way, car = fixture()
    m.groups = [ProtestGroup(1, way, 300, 0, heading, 24, 0)]
    ux, uy = math.cos(heading), math.sin(heading)
    for lane in (-4.0, 0, 4.0):
        before = (300-ux*20-uy*lane, -uy*20+ux*lane)
        car.x, car.y = 300+ux*20-uy*lane, uy*20+ux*lane
        assert m.blocks_movement(car, before)
        car.layer = 1
        assert not m.blocks_movement(car, before)
        car.layer = 0
        car.map_level = -1
        assert not m.blocks_movement(car, before)
        car.map_level = 0


def test_rage_alarm_then_clear_safe_passage_and_safe_return():
    m, world, way, car = fixture()
    m.groups = [ProtestGroup(1, way, 300, 0, 0, 24, 0)]
    m._next_spawn = 10000
    car.x = 280
    group = m.groups[0]
    tick(m, world, car, 5)
    assert group.state == "SITTING"  # proximity does not clear people
    m.intimidate(car)
    assert group.state == "ALARMED" and group.blocking
    tick(m, world, car, 0.5, 5)
    assert group.state == "ALARMED"
    tick(m, world, car, 4, 6)
    assert group.state == "CLEARED" and group.progress == 1
    car.x = 320
    assert not m.blocks_movement(car, (280, 0))
    tick(m, world, car, 35, 10)
    assert group.state == "CLEARED"  # never return into taxi's safety envelope
    car.x = 0
    tick(m, world, car, 5, 50)
    assert group.state == "SITTING" and group.progress == 0


def test_pedestrians_stop_and_block_unsafe_clearance_and_return():
    m, world, way, car = fixture()
    group = ProtestGroup(1, way, 300, 0, 0, 24, 0)
    m.groups = [group]
    m._next_spawn = 10000
    person = SimpleNamespace(x=310, y=0, radius_m=0.45, speed=1.5)
    m.block_walkers([person], {id(person): (290, 0)})
    assert (person.x, person.y, person.speed) == (290, 0, 0)
    person.x, person.y = next(group.members(1))
    world.pedestrian_mgr.pedestrians = [person]
    car.x = 280
    m.intimidate(car)
    tick(m, world, car, 2)
    assert group.state == "ALARMED"  # occupied shoulder must not be trampled
    world.pedestrian_mgr.pedestrians.clear()
    tick(m, world, car, 5, 2)
    assert group.state == "CLEARED"


def test_unload_expiry_and_out_of_view_lifecycle():
    m, world, way, car = fixture()
    m.groups = [ProtestGroup(1, way, 300, 0, 0, 24, 0)]
    m._next_spawn = 10000
    car.x = 3000
    tick(m, world, car, 1)
    assert len(m.groups) == 1 and not m.snapshot(car.x, car.y)
    world.ways.clear()
    world.spatial_grid = SpatialWayGrid([])
    tick(m, world, car, 1, 6)
    assert not m.groups
    m.groups = [ProtestGroup(1, way, 300, 0, 0, 24, 0)]
    tick(m, world, car, 1, 1201)
    assert not m.groups


def test_npc_waits_without_recovery_then_resumes_when_rage_clears_group():
    from theroadragetrip.npc import spawn_npc, update_npc
    from theroadragetrip.residents import ResidentManager
    from theroadragetrip.traffic_world import TrafficWorld

    ways = [Way([(i*20, 0), ((i+1)*20, 0)], "residential", 4.5) for i in range(20)]
    traffic = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, traffic, ways, (0, 0), (400, 0))
    m = ProtestManager(ProtestSettings(enabled=False))
    m.groups = [ProtestGroup(1, ways[7], 150, 0, 0, 24, 0)]
    manager = SimpleNamespace(protests=m)
    for _ in range(1800):
        update_npc(vehicle, driver, 1/60, traffic, residents, manager=manager)
    assert vehicle.car.x < 145 and abs(vehicle.car.speed) < 0.5
    assert vehicle.state == "WAITING"
    assert driver.stuck_timer_s == 0
    assert vehicle.debug_waiting_for == "Ilokapina sit-in"
    m.groups[0].state = "CLEARED"
    for _ in range(1200):
        update_npc(vehicle, driver, 1/60, traffic, residents, manager=manager)
    assert vehicle.car.x > 160


def test_several_groups_use_only_group_level_updates():
    m, world, way, car = fixture()
    world.ways = [Way([(200+i*400, 0), (400+i*400, 0)], "residential", 4.5) for i in range(8)]
    world.spatial_grid = SpatialWayGrid(world.ways)
    m.groups = [ProtestGroup(i, w, 300+i*400, 0, 0, 80, 0) for i, w in enumerate(world.ways)]
    m._next_spawn = 10000
    start = time.perf_counter()
    for i in range(1000):
        m.update(1/60, world, car, datetime(2026, 10, 19, 12), i/60)
    assert len(m.groups) == 8
    assert time.perf_counter()-start < 2.0
