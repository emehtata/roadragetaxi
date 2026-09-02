"""Tests for pedestrian simulation, movement, traffic light compliance, and dodging."""
import math
import pytest
from types import SimpleNamespace
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


def test_repeated_target_count_updates_do_not_delay_population_check():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=1)
    player = Car(x=50.0, y=0.0, heading=0.0, speed=0.0)
    manager._population_update_elapsed = 4.9

    manager.set_target_count(1, player)
    manager.update(player, dt=0.1)

    assert len(manager.pedestrians) == 1


def test_pedestrian_can_reserve_any_nearby_parked_vehicle():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=8.0,
        y=0.0,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))

    assert manager.find_available_parked_vehicle(pedestrian.x, pedestrian.y, 10.0) is vehicle
    assert manager.reserve_parked_vehicle(pedestrian, vehicle)
    assert not manager.reserve_parked_vehicle(pedestrian, vehicle)
    assert vehicle.state == "reserved"
    manager.cancel_vehicle_reservation(pedestrian)
    assert vehicle.state == "parked"


def test_pedestrian_cannot_reserve_vehicle_over_100_meters_away():
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=100.1,
        y=0.0,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))

    assert manager.reserve_parked_vehicle(pedestrian, vehicle) is False
    assert vehicle.reserved_by_pedestrian_id is None
    assert vehicle.state == "parked"


def test_pedestrian_can_reserve_vehicle_at_100_meters():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=100.0,
        y=0.0,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))

    assert manager.reserve_parked_vehicle(pedestrian, vehicle) is True


def test_reserved_pedestrian_walks_to_vehicle_and_enters():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=8.0,
        y=0.0,
        heading=0.0,
        width_m=1.8,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 2.0, 2.0, way, 0, 1, (1, 1, 1))
    manager.pedestrians = [pedestrian]

    assert manager.reserve_parked_vehicle(pedestrian, vehicle)
    assert pedestrian.route is not None
    assert pedestrian.route[0] == (0.0, 0.0)
    assert pedestrian.route[-1] == manager._vehicle_entry_position(vehicle)
    for _ in range(15):
        manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.5)

    assert pedestrian.current_vehicle_id == id(vehicle)
    assert pedestrian.state == "in_vehicle"
    assert vehicle.state == "occupied"


def test_pedestrian_with_vehicle_goal_starts_nearby_vehicle_reservation():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=8.0,
        y=0.0,
        heading=0.0,
        width_m=1.8,
        state="parked",
        reserved_by_pedestrian_id=None,
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 2.0, 2.0, way, 0, 1, (1, 1, 1), wants_vehicle=True)
    manager.pedestrians = [pedestrian]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert pedestrian.state == "approaching_vehicle"
    assert pedestrian.reserved_vehicle_id == id(vehicle)
    assert vehicle.state == "reserved"


def test_pedestrian_in_vehicle_follows_vehicle_position():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=8.0,
        y=0.0,
        state="occupied",
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(8.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    vehicle.current_driver_id = id(pedestrian)
    pedestrian.current_vehicle_id = id(vehicle)
    pedestrian.state = "in_vehicle"
    manager.pedestrians = [pedestrian]

    vehicle.x = 30.0
    vehicle.y = 4.0
    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert (pedestrian.x, pedestrian.y) == (30.0, 4.0)


def test_pedestrian_exits_vehicle_at_vehicle_destination():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    road_way = Way(points_m=[(0.0, 0.0), (30.0, 0.0)], highway="residential", half_width_m=4.0)
    vehicle = SimpleNamespace(
        x=30.0,
        y=0.0,
        heading=0.0,
        width_m=1.8,
        state="occupied",
        current_driver_id=None,
        way=road_way,
        direction=1,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(30.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.current_vehicle_id = id(vehicle)
    pedestrian.vehicle_destination = (30.0, 0.0)
    pedestrian.state = "in_vehicle"
    vehicle.current_driver_id = id(pedestrian)
    manager.pedestrians = [pedestrian]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert pedestrian.state == "walking"
    assert pedestrian.current_vehicle_id is None
    assert vehicle.state == "driving"


def test_pedestrian_can_exit_occupied_vehicle():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=20.0,
        y=5.0,
        heading=0.0,
        width_m=1.8,
        state="occupied",
        current_driver_id=None,
    )
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(20.0, 5.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.current_vehicle_id = id(vehicle)
    vehicle.current_driver_id = id(pedestrian)
    pedestrian.state = "in_vehicle"

    assert manager.exit_vehicle(pedestrian, vehicle)
    assert pedestrian.state == "walking"
    assert pedestrian.current_vehicle_id is None
    assert (pedestrian.x, pedestrian.y) == (20.0, 6.9)
    assert vehicle.state == "driving"
    assert vehicle.current_driver_id is None


def test_pedestrian_can_spawn_at_and_leave_through_building_entrance():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    building = SimpleNamespace(
        points_m=[(18.0, -2.0), (22.0, -2.0), (22.0, 2.0), (18.0, 2.0)],
        entrances=[(20.0, 0.0)],
        venue_type="school",
    )
    manager = PedestrianManager([way], target_count=0, venue_buildings=[building])

    pedestrian = manager.spawn_pedestrian_at_door(20.0, 0.0)
    assert pedestrian is not None
    assert (pedestrian.x, pedestrian.y) == (20.0, 0.0)
    manager.pedestrians.append(pedestrian)
    pedestrian.door_grace_timer = 0.0
    pedestrian.spawned_at_door = False
    manager._population_update_elapsed = 5.0

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert pedestrian not in manager.pedestrians


def test_amenity_door_spawns_pedestrian_every_ten_evening_seconds(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    building = SimpleNamespace(
        points_m=[(18.0, -2.0), (22.0, -2.0), (22.0, 2.0), (18.0, 2.0)],
        entrances=[(20.0, 0.0)],
        venue_type="school",
    )
    manager = PedestrianManager([way], target_count=1, venue_buildings=[building])
    monkeypatch.setattr(manager, "spawn_pedestrian", lambda *args, **kwargs: None)
    random_values = iter((1.0, 1.0, 0.0))
    monkeypatch.setattr(
        "theroadragetrip.pedestrian.random.random",
        lambda: next(random_values),
    )
    player = Car(x=10.0, y=0.0, heading=0.0, speed=0.0)
    manager._amenity_spawn_elapsed = 0.0
    manager._population_update_elapsed = 5.0

    manager.update(player, dt=5.0, game_time_seconds=18.0 * 3600.0)
    assert manager.pedestrians == []

    manager.update(player, dt=5.0, game_time_seconds=18.0 * 3600.0)
    assert len(manager.pedestrians) == 1
    assert manager.pedestrians[0].spawned_at_door is True
    assert manager.pedestrians[0].x > 20.0


def test_pedestrian_despawns_after_remaining_offscreen():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0, despawn_radius_m=200.0)
    pedestrian = Pedestrian(80.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    manager.pedestrians.append(pedestrian)
    viewport = (0.0, -10.0, 50.0, 10.0)

    for _ in range(10):
        manager._population_update_elapsed = 5.0
        manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1, viewport_bounds=viewport)

    assert pedestrian not in manager.pedestrians


def test_taxi_stop_gets_waiting_customer():
    way = Way(points_m=[(0.0, -3.0), (100.0, -3.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0, spawn_radius_m=120.0)
    player = Car(x=10.0, y=0.0, heading=0.0, speed=0.0)

    manager.ensure_taxi_stop_waiter([TaxiStop(20.0, 0.0)], player)

    assert len(manager.pedestrians) == 1
    assert manager.pedestrians[0].is_taxi_stop_waiter is True
    assert (manager.pedestrians[0].x, manager.pedestrians[0].y) == (20.0, -3.0)


def test_taxi_stop_waiter_spawns_when_stop_enters_view(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0, spawn_radius_m=120.0)
    player = Car(x=20.0, y=0.0, heading=0.0, speed=0.0)
    stop = TaxiStop(20.0, 0.0, id=1)
    existing_pedestrian = Pedestrian(10.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    manager.pedestrians.append(existing_pedestrian)

    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)

    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(-10.0, -10.0, 30.0, 10.0))
    assert not existing_pedestrian.is_walking_to_taxi_stop

    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(40.0, -10.0, 80.0, 10.0))
    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(-10.0, -10.0, 30.0, 10.0))

    assert len(manager.pedestrians) == 1
    assert existing_pedestrian.is_walking_to_taxi_stop is True

    for _ in range(500):
        manager.update(player, dt=0.1)
        if existing_pedestrian.is_taxi_stop_waiter:
            break
    assert existing_pedestrian.is_taxi_stop_waiter is True


def test_customer_walks_to_taxi_stop_edge(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, -3.0), (100.0, -3.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0, spawn_radius_m=120.0)
    customer = Pedestrian(10.0, -3.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    manager.pedestrians.append(customer)
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)
    stop = TaxiStop(20.0, 0.0)
    player = Car(10.0, 0.0, 0.0, 0.0)
    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(40.0, -10.0, 60.0, 10.0))
    manager.ensure_taxi_stop_waiter([stop], player, viewport_bounds=(-10.0, -10.0, 30.0, 10.0))

    assert customer.is_walking_to_taxi_stop is True
    assert customer.taxi_stop_target == (20.0, -3.0)

    for _ in range(150):
        manager.update(Car(10.0, 0.0, 0.0, 0.0), dt=0.1)
        if customer.is_taxi_stop_waiter:
            break

    assert customer.is_taxi_stop_waiter is True
    assert (customer.x, customer.y) == (20.0, -3.0)


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


def test_pedestrians_spawn_near_hospitality_venues(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="footway", half_width_m=1.5)
    venue = SimpleNamespace(
        venue_type="restaurant",
        points_m=[(48.0, -4.0), (52.0, -4.0), (52.0, 4.0), (48.0, 4.0)],
    )
    manager = PedestrianManager([way], target_count=3, venue_buildings=[venue])
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)
    monkeypatch.setattr("theroadragetrip.pedestrian.random.choice", lambda values: values[0])

    manager.update(Car(x=50.0, y=0.0, heading=0.0, speed=0.0), dt=0.1)

    assert len(manager.venue_locations) == 1
    assert all(math.hypot(ped.x - 50.0, ped.y) <= 45.0 for ped in manager.pedestrians)


def test_pedestrian_spawn_area_is_limited_to_building_radius():
    way = Way(points_m=[(0.0, 0.0), (500.0, 0.0)], highway="footway", half_width_m=1.5)
    building = SimpleNamespace(bbox=(100.0, 100.0, 110.0, 110.0))
    manager = PedestrianManager([way], target_count=0, venue_buildings=[building])

    assert manager._point_near_building(0.0, 105.0)
    assert not manager._point_near_building(400.0, 0.0)


def test_drunk_pedestrian_walks_unevenly_and_may_vomit(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0)
    drunk = Pedestrian(20.0, 0.0, 0.0, 1.3, 1.3, way, 0, 1, (230, 80, 80), is_drunk=True)
    drunk.drunk_vomit_cooldown = 0.0
    manager.pedestrians = [drunk]
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert drunk.y != 0.0
    assert manager.vomit_puddles == [(20.0, 0.0)]


def test_cyclist_spawn_assigns_body_color():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="cycleway", half_width_m=1.5)
    manager = CyclistManager([way], target_count=0, spawn_radius_m=120.0)

    cyclist = manager.spawn_pedestrian(50.0, 0.0)

    assert cyclist is not None
    assert cyclist.is_cyclist is True
    assert cyclist.color != (230, 80, 80)


def test_cyclist_spawn_uses_synced_ways_outside_local_grid():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="cycleway", half_width_m=1.5)
    manager = CyclistManager([way], target_count=0, spawn_radius_m=10.0)

    cyclist = manager.spawn_pedestrian(500.0, 500.0)

    assert cyclist is not None


def test_cyclists_use_right_edge_for_both_directions(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    manager = CyclistManager([way], target_count=0, spawn_radius_m=120.0)

    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)
    forward = manager.spawn_pedestrian(50.0, 0.0)
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 1.0)
    reverse = manager.spawn_pedestrian(50.0, 0.0)

    assert forward is not None and reverse is not None
    assert forward.direction == 1
    assert reverse.direction == -1
    assert forward.lateral_offset_m == pytest.approx(3.0)
    assert reverse.lateral_offset_m == pytest.approx(3.0)


def test_all_cyclists_continue_moving():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="cycleway", half_width_m=1.5)
    manager = CyclistManager([way], target_count=0, spawn_radius_m=120.0)
    cyclists = [manager.spawn_pedestrian(50.0, 0.0) for _ in range(2)]
    manager.pedestrians = [cyclist for cyclist in cyclists if cyclist is not None]
    initial_positions = [(cyclist.x, cyclist.y) for cyclist in manager.pedestrians]

    manager.update(Car(x=-100.0, y=50.0, heading=0.0, speed=0.0), dt=0.1)

    assert all((cyclist.x, cyclist.y) != initial for cyclist, initial in zip(manager.pedestrians, initial_positions))


def test_spawn_pedestrian_at_creates_walking_passenger():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0)

    passenger = manager.spawn_pedestrian_at(20.0, 1.0, heading=0.0)

    assert passenger is not None
    assert passenger.speed == passenger.base_speed == 1.3
    assert passenger.way is way


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


def test_cyclist_avoidance_is_reported_but_parallel_traffic_is_not():
    cycleway = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="cycleway",
        half_width_m=1.5,
    )
    manager = CyclistManager([cycleway], target_count=0)
    cyclist = Pedestrian(20.0, 0.0, 0.0, 4.0, 4.0, cycleway, 0, 1, (50, 120, 220))
    cyclist.is_cyclist = True
    manager.pedestrians = [cyclist]

    assert manager.check_player_avoidance(Car(x=17.0, y=0.0, heading=0.0, speed=10.0), 0.05) is True
    assert manager.check_player_avoidance(Car(x=17.0, y=0.0, heading=0.0, speed=10.0), 0.05) is False

    cyclist.x = 20.0
    cyclist.y = 2.0
    cyclist.dodge_timer = 0.0
    assert manager.check_player_avoidance(Car(x=17.0, y=0.0, heading=0.0, speed=10.0), 0.05) is False


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
