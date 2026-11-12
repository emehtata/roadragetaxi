"""Law § 37: a motorway through-trip never parks on the motorway."""
import random

from theroadragetrip.npc import NPCState, NPCVehicleManager, spawn_npc, update_npc
from theroadragetrip.osm import Way
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld, run_route_steps

DT = 1.0 / 60.0


def _road(highway="residential"):
    return [Way([(i * 20.0, 0.0), ((i + 1) * 20.0, 0.0)], highway, 4.5) for i in range(30)]


def _finished(fast_through):
    ways = _road()
    world, residents = TrafficWorld(ways), ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (0.0, 0.0), (200.0, 0.0))
    vehicle.fast_through = fast_through
    for _ in range(2400):
        update_npc(vehicle, driver, DT, world, residents)
        if fast_through and driver.path_index >= len(driver.path) - 1:
            break
        if not fast_through and vehicle.state == NPCState.PARKED:
            break
    return vehicle, driver, world, residents


def test_through_trip_at_destination_not_parked():
    vehicle, driver, world, residents = _finished(True)
    for _ in range(600):
        update_npc(vehicle, driver, DT, world, residents)
        assert vehicle.state != NPCState.PARKED
    assert abs(vehicle.car.speed) > 0.05


def _manager_with(vehicle, driver):
    manager = NPCVehicleManager(target_count=1)
    manager.vehicles.append(vehicle)
    manager.drivers[vehicle.vehicle_id] = driver
    return manager


def test_through_trip_retired_out_of_view():
    vehicle, driver, _, residents = _finished(True)
    manager = _manager_with(vehicle, driver)
    manager._route_jobs.append({"vehicle": vehicle, "steps": (x for x in ()), "driver": driver})
    manager._retire_finished_through_traffic(residents, (5000.0, 5000.0, 5100.0, 5100.0))
    assert vehicle not in manager.vehicles
    assert not manager._route_jobs
    assert manager.spawn_flow["through_retired"] == 1


def test_through_trip_kept_in_view():
    vehicle, driver, _, residents = _finished(True)
    manager = _manager_with(vehicle, driver)
    manager._retire_finished_through_traffic(residents, (-1000.0, -1000.0, 1000.0, 1000.0))
    assert vehicle in manager.vehicles
    assert vehicle.state != NPCState.PARKED


def test_local_trip_still_parks():
    vehicle, driver, _, residents = _finished(False)
    assert vehicle.state == NPCState.PARKED
    manager = _manager_with(vehicle, driver)
    manager._retire_finished_through_traffic(residents, None)
    assert vehicle in manager.vehicles


def test_spawn_flags_fast_through():
    ways = [Way([(0.0, 0.0), (3000.0, 0.0)], "motorway", 7, oneway=1, speed_limit_kmh=100)]
    world = TrafficWorld(ways)
    manager = NPCVehicleManager(target_count=1)
    manager._active_bounds = (-100.0, -100.0, 1500.0, 100.0)
    random.seed(3)
    result = run_route_steps(manager._motorway_spawn_steps(
        ResidentManager(), world, ways, None, None, None, None, None, None, 0.0, 0.0, 0.0))
    assert result is not None
    assert result[0].fast_through is True
    _, _, ordinary = spawn_npc(2, ResidentManager(), TrafficWorld(_road()), _road(), (0.0, 0.0), (200.0, 0.0))
    assert ordinary.fast_through is False


def test_through_trip_dead_end_never_stands_in_view():
    ways = [Way([(i * 20.0, 0.0), ((i + 1) * 20.0, 0.0)], "residential", 4.5) for i in range(10)]
    world, residents = TrafficWorld(ways), ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (0.0, 0.0), (200.0, 0.0))
    vehicle.fast_through = True
    manager = _manager_with(vehicle, driver)
    view = (-1000.0, -1000.0, 1000.0, 1000.0)
    for _ in range(1200):
        update_npc(vehicle, driver, DT, world, residents)
        manager._retire_finished_through_traffic(residents, view)
        if vehicle not in manager.vehicles:
            break
        assert vehicle.state != NPCState.PARKED
        if driver.path_index >= len(driver.path) - 1:
            assert abs(vehicle.car.speed) > 0.05  # never stationary on the road in view
    assert vehicle not in manager.vehicles
    assert manager.spawn_flow["through_dead_end"] == 1
