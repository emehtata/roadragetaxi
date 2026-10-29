"""rrt-019-crash-physics: collisions pass momentum on by mass along the
contact (npc.collision_impulse), knocked NPCs slide and then drive on."""
import math
from datetime import datetime

from theroadragetrip.npc import (KNOCK_MAX_MPS, NPCState, NPCVehicleManager, collision_impulse, place_parked_npc,
                                 spawn_npc, update_knocked)
from theroadragetrip.osm import Way
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.physics import Car
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld


def _npc(residents, vehicle_id, x, y, heading=0.0, speed=0.0, vehicle_type="car"):
    vehicle = place_parked_npc(vehicle_id, (x, y), None, vehicle_type=vehicle_type)
    vehicle.car.heading, vehicle.car.speed = heading, speed
    driver = residents.create(mode="driving")
    vehicle.owner_id, driver.active_vehicle_id = driver.resident_id, vehicle.vehicle_id
    return vehicle


def _hit(vehicle, obstacle, residents=None, previous=None, other_previous=None):
    """One collision check with `vehicle` driving into `obstacle` (an NPC or the taxi)."""
    manager = NPCVehicleManager(target_count=2)
    manager.vehicles.extend(v for v in (vehicle, obstacle) if hasattr(v, "vehicle_id"))
    return manager._check_vehicle_collision(
        vehicle, [obstacle], residents or ResidentManager(), PedestrianManager([], target_count=0), sim_time=10.0,
        previous_vehicle_pose=previous, previous_obstacle_poses=other_previous)


def _velocity(vehicle):
    return (vehicle.knock_vx, vehicle.knock_vy) if (vehicle.knock_vx or vehicle.knock_vy) else (
        math.cos(vehicle.car.heading) * vehicle.car.speed, math.sin(vehicle.car.heading) * vehicle.car.speed)


def test_a_moving_car_shoves_a_stationary_car_forward_and_slows():
    residents = ResidentManager()
    car, parked = _npc(residents, 1, 0.0, 0.0, speed=15.0), _npc(residents, 2, 4.0, 0.0)
    assert _hit(car, parked, residents)
    assert parked.knock_vx > 5.0 and abs(parked.knock_vy) < 1e-9  # forward, along the hit
    assert 0.0 < car.knock_vx < 15.0  # slowed, not stopped dead
    assert car.knock_vx < parked.knock_vx  # the struck car now leads: they part


def test_a_rear_end_hit_speeds_up_the_car_ahead():
    residents = ResidentManager()
    behind, ahead = _npc(residents, 1, 0.0, 0.0, speed=20.0), _npc(residents, 2, 4.0, 0.0, speed=10.0)
    _hit(behind, ahead, residents)
    assert ahead.knock_vx > 10.0 and behind.knock_vx < 20.0
    assert ahead.knock_vx + behind.knock_vx == pytest_approx(30.0)  # equal masses: momentum kept


def test_a_head_on_crash_stops_or_throws_both_back():
    residents = ResidentManager()
    east, west = _npc(residents, 1, 0.0, 0.0, speed=15.0), _npc(residents, 2, 4.0, 0.0, heading=math.pi, speed=15.0)
    _hit(east, west, residents)
    assert east.knock_vx <= 0.0 <= west.knock_vx  # both lose all their forward motion, bounced a little
    assert abs(east.knock_vx) < 5.0 and abs(west.knock_vx) < 5.0


def test_a_side_hit_pushes_the_struck_car_sideways():
    residents = ResidentManager()
    striking = _npc(residents, 1, 0.0, -2.5, heading=math.pi / 2, speed=15.0)  # northwards into its flank
    struck = _npc(residents, 2, 0.0, 0.0, speed=10.0)  # driving east
    _hit(striking, struck, residents)
    assert struck.knock_vy > 5.0  # thrown north, across its heading
    assert struck.knock_vx == pytest_approx(10.0)  # its own forward motion kept
    assert striking.knock_vy < 15.0


def test_distinct_outcomes_for_head_on_rear_end_and_side():
    residents = ResidentManager()
    outcomes = []
    for heading, x, y in ((math.pi, 4.0, 0.0), (0.0, 4.0, 0.0), (math.pi / 2, 0.5, 2.0)):
        car, other = _npc(residents, 1, 0.0, 0.0, speed=15.0), _npc(residents, 2, x, y, heading=heading, speed=8.0)
        _hit(car, other, residents)
        outcomes.append((round(car.knock_vx, 1), round(car.knock_vy, 1)))
    assert len(set(outcomes)) == 3


def test_a_car_throws_a_stationary_bicycle_and_barely_slows():
    residents = ResidentManager()
    car, bike = _npc(residents, 1, 0.0, 0.0, speed=14.0), _npc(residents, 2, 3.0, 0.0, vehicle_type="bicycle")
    _hit(car, bike, residents)
    assert bike.knock_vx > 14.0  # light: flung faster than the car came
    assert car.knock_vx > 12.0  # heavy: hardly slowed
    assert bike.state == NPCState.CRASHED and bike.fallen


def test_a_car_hits_a_moving_bicycle_from_behind():
    residents = ResidentManager()
    car, bike = _npc(residents, 1, 0.0, 0.0, speed=14.0), _npc(residents, 2, 3.0, 0.0, vehicle_type="bicycle", speed=5.0)
    _hit(car, bike, residents)
    assert bike.knock_vx > 14.0 and car.knock_vx > 12.0


def test_a_motorcycle_is_thrown_further_than_a_car():
    residents = ResidentManager()
    car, motorcycle = _npc(residents, 1, 0.0, 0.0, speed=14.0), _npc(residents, 2, 3.0, 0.0, vehicle_type="motorcycle")
    _hit(car, motorcycle, residents)
    car2, other_car = _npc(residents, 3, 0.0, 0.0, speed=14.0), _npc(residents, 4, 4.0, 0.0)
    _hit(car2, other_car, residents)
    assert motorcycle.knock_vx > other_car.knock_vx


def test_a_car_hardly_moves_a_stationary_bus_and_bounces_off():
    residents = ResidentManager()
    car, bus = _npc(residents, 1, 0.0, 0.0, speed=15.0), _npc(residents, 2, 7.5, 0.0, vehicle_type="bus")
    _hit(car, bus, residents)
    assert 0.0 < bus.knock_vx < 2.5
    assert car.knock_vx < 0.0  # bounced back off it


def test_the_taxi_slows_and_shoves_a_parked_car():
    residents = ResidentManager()
    parked = _npc(residents, 1, 0.0, 0.0)
    taxi = Car(x=-4.0, y=0.0, heading=0.0, speed=20.0)
    _hit(parked, taxi, residents)
    assert 0.0 < taxi.speed < 20.0 and parked.knock_vx > 5.0


def test_one_contact_never_pushes_twice():
    residents = ResidentManager()
    car, parked = _npc(residents, 1, 0.0, 0.0, speed=15.0), _npc(residents, 2, 4.0, 0.0)
    _hit(car, parked, residents)
    after = (_velocity(car), _velocity(parked))
    _hit(car, parked, residents)  # the same overlap processed again: they part already
    _hit(parked, car, residents)  # and from the other side
    assert (_velocity(car), _velocity(parked)) == after


def test_impulses_stay_finite_and_bounded():
    for mass_a, mass_b, speed in ((1500.0, 95.0, 60.0), (95.0, 14000.0, 40.0), (1500.0, 1500.0, 1e6), (1e-3, 1e6, 50.0)):
        va, vb = collision_impulse((speed, 0.0), (-speed, 0.0), (1.0, 0.0), mass_a, mass_b)
        for v in (*va, *vb):
            assert math.isfinite(v)
        assert math.hypot(*va) <= KNOCK_MAX_MPS + 1e-9 and math.hypot(*vb) <= KNOCK_MAX_MPS + 1e-9
    assert collision_impulse((0.0, 0.0), (0.0, 0.0), (1.0, 0.0), 1500.0, 1500.0) == ((0.0, 0.0), (0.0, 0.0))


def test_a_knocked_vehicle_slides_to_a_stop_and_never_speeds_up():
    vehicle = place_parked_npc(1, (0.0, 0.0), None)
    vehicle.knock_vx, vehicle.knock_vy = 12.0, 5.0
    speeds = []
    for _ in range(200):
        update_knocked(vehicle, 1 / 30)
        speeds.append(math.hypot(vehicle.knock_vx, vehicle.knock_vy))
    assert all(b <= a for a, b in zip(speeds, speeds[1:])) and speeds[-1] == 0.0
    assert vehicle.x > 5.0 and vehicle.y > 2.0  # slid along the knock


def test_a_knocked_vehicle_stops_at_a_wall():
    from theroadragetrip.osm.models import Building
    wall = Building(points_m=[(6.0, -10.0), (8.0, -10.0), (8.0, 10.0), (6.0, 10.0), (6.0, -10.0)])
    vehicle = place_parked_npc(1, (0.0, 0.0), None)
    vehicle.knock_vx = 20.0
    for _ in range(60):
        update_knocked(vehicle, 1 / 30, buildings=[wall])
    assert vehicle.x < 6.0 - vehicle.length_m / 2 + 0.7 and vehicle.knock_vx == 0.0


def _road():
    return [Way(points_m=[(x, 0), (x + 40, 0)], highway="residential", half_width_m=4.5) for x in range(0, 400, 40)]


def test_a_nudged_npc_slides_first_then_drives_on():
    """Its driving does not overwrite the knock; after the slide it resumes its trip."""
    ways, residents = _road(), ResidentManager()
    world = TrafficWorld(ways)
    manager = NPCVehicleManager(target_count=0, min_count=0, max_count=0)
    manager._population_elapsed = -1e9
    manager.clock = datetime(2026, 7, 1, 12)
    _, driver, car = spawn_npc(1, residents, world, ways, (40, 0), (360, 0))
    manager.vehicles.append(car)
    manager.drivers[car.vehicle_id] = driver
    car.knock_vx, car.knock_vy = 0.0, 3.0  # nudged sideways, gently: no wreck
    manager.update(1 / 30, 200.0, 0.0, residents, world, ways)
    assert car.knock_vy > 0.0 and car.car.speed == 0.0  # sliding, the driver waits
    start = car.x
    for _ in range(300):
        manager.update(1 / 30, 200.0, 0.0, residents, world, ways)
    assert car.knock_vx == car.knock_vy == 0.0
    assert car.state != NPCState.CRASHED and car.x > start + 20.0  # not stuck: driving its route again


def pytest_approx(value):
    import pytest
    return pytest.approx(value, abs=1e-6)


def test_a_knocked_vehicle_does_not_slide_off_its_bridge():
    deck = Way(points_m=[(-50.0, 0.0), (50.0, 0.0)], highway="primary", half_width_m=4.0, layer=1)
    below = Way(points_m=[(0.0, -50.0), (0.0, 50.0)], highway="primary", half_width_m=4.0)
    vehicle = place_parked_npc(1, (0.0, 0.0), None)
    vehicle.car.layer, vehicle.knock_vy = 1, 15.0  # thrown across the deck
    for _ in range(60):
        update_knocked(vehicle, 1 / 30, ways=[deck, below])
    assert vehicle.knock_vy == 0.0 and abs(vehicle.y) <= 4.0 + 0.6  # stopped at the deck's edge


def test_pushing_an_embedded_pair_apart_never_puts_one_in_a_wall():
    from theroadragetrip.geo import point_in_polygon
    from theroadragetrip.osm.models import Building
    residents = ResidentManager()
    wall = Building(points_m=[(-10.0, 1.3), (10.0, 1.3), (10.0, 5.0), (-10.0, 5.0), (-10.0, 1.3)])
    truck, bike = _npc(residents, 1, 0.0, -0.5, vehicle_type="truck"), _npc(residents, 2, 0.0, 0.6, vehicle_type="bicycle", speed=4.0)
    manager = NPCVehicleManager(target_count=2)
    manager.vehicles.extend([truck, bike])
    manager._collision_buildings = [wall]
    manager._check_vehicle_collision(bike, [truck], residents, PedestrianManager([], target_count=0), sim_time=1.0,
                                     previous_vehicle_pose=(bike.x, bike.y, bike.heading),
                                     previous_obstacle_poses={id(truck): (truck.x, truck.y, truck.heading)})
    assert bike.y + bike.width_m / 2 < 1.3 and not point_in_polygon(bike.x, bike.y, wall.points_m)


def test_a_knock_ends_when_the_vehicle_leaves_the_simulated_area():
    ways, residents = _road(), ResidentManager()
    world = TrafficWorld(ways)
    manager = NPCVehicleManager(target_count=0, min_count=0, max_count=0)
    manager._population_elapsed = -1e9
    _, driver, car = spawn_npc(1, residents, world, ways, (40, 0), (360, 0))
    manager.vehicles.append(car)
    manager.drivers[car.vehicle_id] = driver
    car.knock_vx = 5.0
    manager.update(1 / 30, 200.0, 0.0, residents, world, ways, active_bounds=(5000.0, 5000.0, 6000.0, 6000.0))
    assert car.knock_vx == car.knock_vy == 0.0


def test_a_minor_bump_leaves_a_parked_car_in_its_bay():
    residents = ResidentManager()
    parked = place_parked_npc(1, (0.0, 0.0), None)
    taxi = Car(x=-4.0, y=0.0, heading=0.0, speed=2.5)  # 9 km/h
    _hit(parked, taxi, residents)
    assert parked.state == NPCState.PARKED and parked.knock_vx == parked.knock_vy == 0.0
    assert parked.curse_timer > 0.0 and taxi.speed < 2.5
