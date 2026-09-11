"""Tests for pedestrian simulation, movement, traffic light compliance, and dodging."""
import math
import pytest
from types import SimpleNamespace
from theroadragetrip.geo import point_in_polygon
from theroadragetrip.osm import TrafficLight, Way
from theroadragetrip.osm import TaxiStop
from theroadragetrip.pedestrian import (
    CyclistManager,
    Pedestrian,
    PedestrianAppearance,
    PedestrianManager,
    PedestrianNetwork,
    PedestrianState,
)
from theroadragetrip.physics import Car
from theroadragetrip.residents import ResidentManager


def test_pedestrian_network_routes_across_connected_ways():
    network = PedestrianNetwork([
        Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=2.0),
        Way(points_m=[(10.0, 0.0), (10.0, 10.0)], highway="footway", half_width_m=2.0),
    ])

    route = network.route((0.0, 0.0), (10.0, 10.0))

    assert (10.0, 0.0) in route
    assert network.nearest_point((8.0, 2.0)) == (8.0, 0.0)


def test_sync_map_data_adds_streamed_footway():
    initial_way = Way(
        points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=2.0,
    )
    streamed_way = Way(
        points_m=[(20.0, 0.0), (30.0, 0.0)], highway="footway", half_width_m=2.0,
    )
    manager = PedestrianManager([initial_way], target_count=0)

    manager.sync_map_data([initial_way, streamed_way])

    assert streamed_way in manager.ped_ways
    assert streamed_way in manager._spawn_ways


def test_pedestrian_routes_and_spawns_stay_outside_buildings():
    ways = [Way(
        points_m=[(0.0, 0.0), (10.0, 0.0), (30.0, 0.0), (40.0, 0.0)],
        highway="footway",
        half_width_m=1.5,
    )]
    building = SimpleNamespace(
        points_m=[(18.0, -2.0), (22.0, -2.0), (22.0, 2.0), (18.0, 2.0)],
        bbox=(18.0, -2.0, 22.0, 2.0),
        entrances=[(20.0, 0.0)],
        venue_type=None,
    )
    manager = PedestrianManager(ways, target_count=0, venue_buildings=[building])

    assert manager.spawn_pedestrian_at(20.0, 0.0) is None
    assert all(
        not point_in_polygon(point[0], point[1], building.points_m)
        for way in manager.ped_ways
        for point in way.points_m
    )
    assert manager.spawn_pedestrian_at_door(20.0, 0.0) is not None


def test_pedestrian_state_and_appearance_support_interactions():
    assert PedestrianState.APPROACHING_CROSSING.value == "approaching_crossing"
    appearance = PedestrianAppearance(body=(10, 20, 30))
    assert appearance.body == (10, 20, 30)
    assert appearance.head == (238, 185, 145)


def test_drunk_promille_changes_walking_and_can_cause_a_fall(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0)
    pedestrian = Pedestrian(10.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.is_drunk = True
    pedestrian.blood_alcohol_promille = 3.0
    pedestrian.fall_cooldown = 100.0
    pedestrian.drunk_vomit_cooldown = 100.0
    manager.pedestrians = [pedestrian]

    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 1.0)
    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert 0.5 <= pedestrian.blood_alcohol_promille <= 3.0
    assert pedestrian.speed < pedestrian.base_speed

    pedestrian.fall_cooldown = 0.0
    monkeypatch.setattr("theroadragetrip.pedestrian.random.random", lambda: 0.0)
    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert pedestrian.state == "fallen"
    assert pedestrian.animation_state == "fallen"


def test_vehicle_exit_can_use_explicit_transition_state():
    way = Way(points_m=[(0.0, 0.0), (30.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(x=10.0, y=0.0, heading=0.0, width_m=1.8, state="occupied", current_driver_id=None)
    manager = PedestrianManager([way], target_count=0, traffic_vehicles=[vehicle])
    pedestrian = Pedestrian(10.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.current_vehicle_id = id(vehicle)
    vehicle.current_driver_id = id(pedestrian)
    assert manager.exit_vehicle(pedestrian, vehicle, animate=True)
    assert pedestrian.state == PedestrianState.EXITING_VEHICLE.value


def test_crashed_driver_pedestrian_keeps_resident_identity():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=2.0)
    residents = ResidentManager()
    resident = residents.create("driving")
    manager = PedestrianManager([way], target_count=0, residents=residents)

    pedestrian = manager.spawn_pedestrian_at(20.0, 0.0, resident_id=resident.resident_id)

    assert pedestrian is not None
    assert pedestrian.resident_id == resident.resident_id
    assert list(residents.residents).count(resident.resident_id) == 1


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


def test_population_spawn_does_not_fallback_into_viewport(monkeypatch: pytest.MonkeyPatch):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=1)
    calls = []

    def blocked_spawn(*args, **kwargs):
        calls.append(kwargs.get("viewport_bounds"))
        return None

    monkeypatch.setattr(manager, "spawn_pedestrian", blocked_spawn)
    manager._population_update_elapsed = 5.0
    manager.update(
        Car(x=50.0, y=0.0, heading=0.0, speed=0.0),
        dt=0.1,
        viewport_bounds=(0.0, -10.0, 100.0, 10.0),
    )

    assert calls
    assert all(call == (0.0, -10.0, 100.0, 10.0) for call in calls)
    assert len(calls) > 1
    assert manager.pedestrians == []


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


def test_vehicle_approach_uses_connected_pedestrian_waypoints():
    first_way = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=1.5)
    second_way = Way(points_m=[(10.0, 0.0), (10.0, 10.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([first_way, second_way], target_count=0)
    vehicle = SimpleNamespace(x=10.0, y=10.0, heading=0.0, width_m=1.8)
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 1.0, 1.0, first_way, 0, 1, (1, 1, 1))

    route = manager._vehicle_approach_route(pedestrian, manager._vehicle_entry_position(vehicle))

    assert (10.0, 0.0) in route


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


def test_pedestrian_in_vehicle_is_not_despawned_while_vehicle_is_active():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    vehicle = SimpleNamespace(
        x=200.0,
        y=0.0,
        state="occupied",
        current_driver_id=None,
    )
    manager = PedestrianManager(
        [way], target_count=0, despawn_radius_m=20.0, traffic_vehicles=[vehicle]
    )
    pedestrian = Pedestrian(200.0, 0.0, 0.0, 1.0, 1.0, way, 0, 1, (1, 1, 1))
    pedestrian.current_vehicle_id = id(vehicle)
    pedestrian.state = "in_vehicle"
    vehicle.current_driver_id = id(pedestrian)
    manager.pedestrians = [pedestrian]
    manager._population_update_elapsed = 5.0

    manager.update(Car(0.0, 0.0, 0.0, 0.0), dt=0.1)

    assert manager.pedestrians == [pedestrian]


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


def _grid_of_ways(count: int) -> list:
    """`count` short, disconnected footway segments spread over a wide
    area - enough distinct ways in ped_ways to make an O(len(ped_ways))
    per-call cost show up, while still landing plenty of them within any
    given spawn_radius_m so spawn_pedestrian can actually succeed."""
    ways = []
    for i in range(count):
        x = float(i % 100) * 40.0
        y = float(i // 100) * 40.0
        ways.append(Way(points_m=[(x, y), (x + 20.0, y)], highway="footway", half_width_m=1.5))
    return ways


def test_sync_map_data_keeps_ped_way_ids_cache_in_sync():
    """Regression: spawn_pedestrian() reads self._ped_way_ids (see its
    docstring) instead of rebuilding {id(way) for way in self.ped_ways}
    itself - sync_map_data() (both PedestrianManager's and
    CyclistManager's, which overrides it) must keep that cache exactly
    in sync with ped_ways, on every call, not just the first."""
    way_a = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=1.5)
    way_b = Way(points_m=[(20.0, 0.0), (30.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way_a], target_count=0)
    assert manager._ped_way_ids == {id(w) for w in manager.ped_ways}

    manager.sync_map_data([way_a, way_b])
    assert manager._ped_way_ids == {id(w) for w in manager.ped_ways}
    assert manager._ped_way_ids  # non-empty: actually exercised, not just equal-by-emptiness

    cyclists = CyclistManager([way_a], target_count=0)
    assert cyclists._ped_way_ids == {id(w) for w in cyclists.ped_ways}
    cyclists.sync_map_data([way_a, way_b])
    assert cyclists._ped_way_ids == {id(w) for w in cyclists.ped_ways}


def test_spawn_pedestrian_does_not_rescan_ped_ways_per_attempt():
    """Regression: spawn_pedestrian() used to rebuild
    {id(way) for way in self.ped_ways} from scratch on *every single
    call* - every spawn attempt, not just successful ones, and update()
    can make up to max(50, target_count * 5) attempts per 5-second
    population pass (most of them failing, e.g. at low zoom where the
    whole spawn_radius_m search area already sits inside the viewport -
    see the other regression test below). Against a real city-scale
    ped_ways (tens of thousands of ways after autofetch grows the map)
    this one line dominated the whole pass: ~900ms in a single frame,
    confirmed via profiling against real Oulu OSM data (30949 ways).

    Reproduces that shape directly: a large ped_ways and many calls that
    all fail to place anyone (max_distance_m=0.001 - effectively zero -
    rejects every candidate point, the same "burn the whole retry budget
    with nothing to show for it" shape a real doomed-to-fail attempt has),
    asserting on wall time. A successful placement's own cost would
    otherwise dwarf and hide the one line this covers, so this isolates
    it: fixed, 300 calls against 15000 ped_ways measured ~0.21s;
    unfixed (rebuilding the id() set from scratch each call) measured
    ~0.58s. The threshold is set well clear of both."""
    import time

    ways = _grid_of_ways(15000)
    manager = PedestrianManager(ways, target_count=0)
    assert len(manager.ped_ways) >= 12000

    start = time.perf_counter()
    for _ in range(300):
        result = manager.spawn_pedestrian(20.0, 0.0, max_distance_m=0.001)
        assert result is None  # every candidate point must fail the distance check
    elapsed = time.perf_counter() - start
    assert elapsed < 0.35, (
        f"300 always-failing spawn_pedestrian calls against {len(manager.ped_ways)} "
        f"ped_ways took {elapsed:.2f}s - looks like the per-call ped-way-id-set rebuild regressed"
    )


def test_spawn_pedestrian_gives_up_immediately_when_search_area_is_fully_onscreen(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: at low zoom, the viewport can be wider than
    2 * spawn_radius_m - every candidate point spawn_pedestrian's retry
    loop could generate near `near_x, near_y` is then guaranteed to land
    inside the viewport (and get rejected), yet the old code still ran
    the full retry budget (up to 30 candidate ways x every segment x 8
    points) on every one of the up to max(50, target_count * 5) attempts
    update() makes - confirmed via profiling: ~900ms in a single frame
    against real OSM data (340800 wasted random.uniform() calls alone).
    Must recognize a fully-onscreen search area and return None
    immediately instead of exhausting the retry budget on attempts that
    can never succeed.

    Verified by call count rather than wall time - real Oulu ways carry
    many points each, so the retry loop's cost scales with segments per
    way; this repo's small synthetic ways don't reproduce that volume,
    which makes a timing threshold here either too loose to catch a
    regression or too tight to be reliable. random.shuffle() is called
    exactly once per candidate way inside that retry loop (to randomize
    which segment is tried first) - zero calls is a direct, robust
    signal that the loop never started."""
    ways = _grid_of_ways(6000)
    manager = PedestrianManager(ways, target_count=0)
    near_x, near_y = 20.0, 0.0
    r = manager.spawn_radius_m
    huge_viewport = (near_x - r - 50.0, near_y - r - 50.0, near_x + r + 50.0, near_y + r + 50.0)

    shuffle_calls = []
    real_shuffle = __import__("random").shuffle
    monkeypatch.setattr(
        "theroadragetrip.pedestrian.random.shuffle",
        lambda seq: (shuffle_calls.append(len(seq)), real_shuffle(seq))[-1],
    )

    result = manager.spawn_pedestrian(near_x, near_y, viewport_bounds=huge_viewport)
    assert result is None  # every candidate would be onscreen - never a valid spot
    assert shuffle_calls == [], (
        f"spawn_pedestrian shuffled candidates {len(shuffle_calls)} time(s) despite a "
        f"fully-onscreen search area - looks like the early-exit shortcut regressed"
    )

    # Sanity: a normal, screen-sized viewport (smaller than the search
    # area) must still let a real spawn succeed - the shortcut above must
    # not be so broad it breaks ordinary spawning.
    tight_viewport = (near_x - 10.0, near_y - 10.0, near_x + 10.0, near_y + 10.0)
    assert manager.spawn_pedestrian(near_x, near_y, viewport_bounds=tight_viewport) is not None
