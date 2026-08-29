"""Tests for pedestrian simulation, movement, traffic light compliance, and dodging."""
import math
from theroadragetrip.osm import TrafficLight, Way
from theroadragetrip.osm import TaxiStop
from theroadragetrip.pedestrian import CyclistManager, Pedestrian, PedestrianManager
from theroadragetrip.physics import Car


def test_pedestrian_target_count_keeps_nearest_characters():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=3)
    manager.pedestrians = [
        Pedestrian(1.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1)),
        Pedestrian(10.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1)),
        Pedestrian(30.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1)),
    ]

    manager.set_target_count(2, Car(x=0.0, y=0.0, heading=0.0, speed=0.0))

    assert [ped.x for ped in manager.pedestrians] == [1.0, 10.0]


def test_taxi_stop_gets_waiting_customer():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0, spawn_radius_m=120.0)
    player = Car(x=10.0, y=0.0, heading=0.0, speed=0.0)

    manager.ensure_taxi_stop_waiter([TaxiStop(20.0, 0.0)], player)

    assert len(manager.pedestrians) == 1
    assert manager.pedestrians[0].is_taxi_stop_waiter is True
    assert (manager.pedestrians[0].x, manager.pedestrians[0].y) == (20.0, 0.0)


def test_pedestrian_spawning_and_movement():
    footway1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
        name="Walkway 1",
    )
    footway2 = Way(
        points_m=[(100.0, 0.0), (200.0, 0.0)],
        highway="path",
        half_width_m=1.5,
        name="Walkway 2",
    )
    ways = [footway1, footway2]

    ped_mgr = PedestrianManager(ways, target_count=5, spawn_radius_m=150.0, despawn_radius_m=250.0)
    player = Car(x=50.0, y=10.0, heading=0.0, speed=0.0)

    # Initial update spawns pedestrians
    ped_mgr.update(player, dt=0.1)
    assert len(ped_mgr.pedestrians) == 5

    for ped in ped_mgr.pedestrians:
        assert isinstance(ped, Pedestrian)
        assert 0.0 <= ped.x <= 200.0
        assert len(ped.color) == 3
        assert ped.speed > 0.0

    # Step simulation frames
    initial_positions = [(p.x, p.y) for p in ped_mgr.pedestrians]
    for _ in range(10):
        ped_mgr.update(player, dt=0.1)

    # At least some pedestrians moved
    moved = sum(
        1 for i, p in enumerate(ped_mgr.pedestrians)
        if (p.x, p.y) != initial_positions[i]
    )
    assert moved > 0


def test_cyclist_spawn_assigns_body_color():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="cycleway", half_width_m=1.5)
    manager = CyclistManager([way], target_count=0, spawn_radius_m=120.0)

    cyclist = manager.spawn_pedestrian(50.0, 0.0)

    assert cyclist is not None
    assert cyclist.is_cyclist is True
    assert cyclist.color != (230, 80, 80)


def test_pedestrian_speed_and_natural_distribution():
    footway = Way(
        points_m=[(0.0, 0.0), (300.0, 0.0)],
        highway="footway",
        half_width_m=2.0,
    )
    ped_mgr = PedestrianManager([footway], target_count=30, spawn_radius_m=300.0)
    player = Car(x=150.0, y=0.0, heading=0.0, speed=0.0)
    ped_mgr.update(player, dt=0.1)

    assert len(ped_mgr.pedestrians) == 30
    speeds = [p.base_speed for p in ped_mgr.pedestrians]
    # Check speed variety across profiles (from ~0.8m/s to ~3.0m/s)
    assert min(speeds) < 1.3
    assert max(speeds) > 1.3
    # Check natural lateral offset distribution across sidewalk width
    lat_offsets = [p.lateral_offset_m for p in ped_mgr.pedestrians]
    assert any(lat > 0.1 for lat in lat_offsets)
    assert any(lat < -0.1 for lat in lat_offsets)


def test_pedestrian_dodging_and_cursing_when_car_approaches():
    footway = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
    )
    ped_mgr = PedestrianManager([footway], target_count=1)
    ped = Pedestrian(
        x=20.0,
        y=0.0,
        heading=0.0,
        speed=1.4,
        base_speed=1.4,
        way=footway,
        segment_idx=0,
        direction=1,
        color=(255, 0, 0),
    )
    ped_mgr.pedestrians = [ped]

    # Car moving directly towards pedestrian (at x=17.0, heading east towards x=20.0, long_dist=3.0m)
    player = Car(x=17.0, y=0.0, heading=0.0, speed=10.0)
    ped_mgr.check_player_avoidance(player, dt=0.05)

    assert ped.curse_timer > 0.0
    assert ped.curse_text in ["@#*!%", "#$@&!", "!%#&*", "%$!#@", "@!*#$"]
    assert ped.dodge_timer > 0.0
    assert (ped.dodge_vx != 0.0 or ped.dodge_vy != 0.0)


def test_pedestrian_does_not_dodge_when_car_drives_parallel_or_away():
    footway = Way(
        points_m=[(0.0, 5.0), (100.0, 5.0)],
        highway="footway",
        half_width_m=1.5,
    )
    ped_mgr = PedestrianManager([footway], target_count=1)
    ped = Pedestrian(
        x=20.0,
        y=5.0,
        heading=0.0,
        speed=1.4,
        base_speed=1.4,
        way=footway,
        segment_idx=0,
        direction=1,
        color=(255, 0, 0),
    )
    ped_mgr.pedestrians = [ped]

    # Car driving on road at y=0.0 (lateral offset 5.0m > 1.8m corridor)
    player = Car(x=18.0, y=0.0, heading=0.0, speed=10.0)
    ped_mgr.check_player_avoidance(player, dt=0.05)

    # Should not trigger dodge
    assert ped.curse_timer == 0.0
    assert ped.dodge_timer == 0.0


def test_pedestrian_does_not_dodge_until_car_is_close():
    footway = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
    )
    ped_mgr = PedestrianManager([footway], target_count=1)
    ped = Pedestrian(20.0, 0.0, 0.0, 1.4, 1.4, footway, 0, 1, (255, 0, 0))
    ped_mgr.pedestrians = [ped]

    player = Car(x=16.0, y=0.0, heading=0.0, speed=10.0)
    ped_mgr.check_player_avoidance(player, dt=0.05)

    assert ped.curse_timer == 0.0
    assert ped.dodge_timer == 0.0


def test_pedestrian_traffic_light_crossing_stop():
    crossing = Way(
        points_m=[(0.0, 0.0), (20.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
    )
    tl = TrafficLight(x=10.0, y=0.0, cycle_time=16.0, offset=0.0)
    # At sim_time=0.0: state is 'green' for vehicular road -> pedestrian crossing is red (must stop)
    ped_mgr = PedestrianManager([crossing], target_count=1, traffic_lights=[tl])
    ped = Pedestrian(
        x=8.0,
        y=0.0,
        heading=0.0,
        speed=1.4,
        base_speed=1.4,
        way=crossing,
        segment_idx=0,
        direction=1,
        color=(255, 0, 0),
    )
    ped_mgr.pedestrians = [ped]
    player = Car(x=100.0, y=100.0, heading=0.0, speed=0.0)

    ped_mgr.update(player, dt=0.1)
    # Pedestrian stopped at red light
    assert ped.speed == 0.0
