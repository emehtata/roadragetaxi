"""F1 (docs/specs/pr-findings-0.21.0b-0.md): a motorway through-trip stuck or
held mid-route is retired after a bounded number of recovery attempts, even in
view; map expansions replan queued motorway spawns around the current player."""
import random

import theroadragetrip.npc as npc
from theroadragetrip.npc import NPCVehicleManager, spawn_npc
from theroadragetrip.osm import Way
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld

VIEW = (-1000.0, -1000.0, 1000.0, 1000.0)


def _midroute(fast_through=True, stage="STUCK"):
    ways = [Way([(i * 20.0, 0.0), ((i + 1) * 20.0, 0.0)], "residential", 4.5) for i in range(30)]
    world, residents = TrafficWorld(ways), ResidentManager()
    random.seed(1)
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (0.0, 0.0), (500.0, 0.0))
    vehicle.fast_through = fast_through
    driver.recovery_stage = stage
    assert driver.path_index < len(driver.path) - 1
    manager = NPCVehicleManager(target_count=1)
    manager.vehicles.append(vehicle)
    manager.drivers[vehicle.vehicle_id] = driver
    return manager, vehicle, driver, world, residents


def _past_bound(manager):
    manager._population_tick_number += npc.NPC_THROUGH_STUCK_MAX_TICKS


def _recovery_job(manager, vehicle, world):
    manager._enqueue_existing_route_job("recovery", vehicle, (x for x in ()), world)
    return manager._route_jobs.pop()


def test_stuck_midroute_visible_is_retired_after_bound():
    manager, vehicle, _, _, residents = _midroute()
    manager._retire_finished_through_traffic(residents, VIEW)
    assert vehicle in manager.vehicles  # recovery gets its chance first
    _past_bound(manager)
    manager._retire_finished_through_traffic(residents, VIEW)
    assert vehicle not in manager.vehicles
    assert manager.spawn_flow["through_stuck_retired"] == 1
    assert manager.spawn_flow["through_dead_end"] == 0


def test_hold_midroute_visible_is_retired_after_bound():
    manager, vehicle, _, _, residents = _midroute(stage="HOLD")
    manager._retire_finished_through_traffic(residents, VIEW)
    assert vehicle in manager.vehicles
    _past_bound(manager)
    manager._retire_finished_through_traffic(residents, VIEW)
    assert vehicle not in manager.vehicles
    assert manager.spawn_flow["through_stuck_retired"] == 1


def test_failed_recovery_retires_through_vehicle():
    manager, vehicle, driver, world, residents = _midroute()
    for attempt in range(npc.NPC_THROUGH_MAX_RECOVERY_ATTEMPTS):
        manager._retire_finished_through_traffic(residents, VIEW)
        assert vehicle in manager.vehicles
        manager._finish_route_job(_recovery_job(manager, vehicle, world), None, 0.0, 0.0, residents, VIEW)
        assert driver.recovery_stage == "HOLD"
        assert driver.through_recovery_attempts == attempt + 1
    manager._retire_finished_through_traffic(residents, VIEW)
    assert vehicle not in manager.vehicles
    assert manager.spawn_flow["through_stuck_retired"] == 1


def test_successful_recovery_resets_counters_and_keeps_vehicle():
    manager, vehicle, driver, world, residents = _midroute()
    manager._finish_route_job(_recovery_job(manager, vehicle, world), None, 0.0, 0.0, residents, VIEW)
    manager._retire_finished_through_traffic(residents, VIEW)
    assert driver.through_recovery_attempts == 1 and driver.through_stuck_since_tick is not None
    path = list(driver.path)
    manager._finish_route_job(_recovery_job(manager, vehicle, world), (path, driver.destination, None, False),
                              0.0, 0.0, residents, VIEW)
    assert driver.recovery_stage == "NORMAL"
    assert driver.through_recovery_attempts == 0 and driver.through_stuck_since_tick is None
    _past_bound(manager)
    manager._retire_finished_through_traffic(residents, VIEW)
    assert vehicle in manager.vehicles
    assert manager.spawn_flow.get("through_stuck_retired", 0) == 0


def test_dead_end_retired_immediately():
    manager, vehicle, driver, _, residents = _midroute()
    driver.path_index = len(driver.path) - 1
    manager._retire_finished_through_traffic(residents, VIEW)
    assert vehicle not in manager.vehicles
    assert manager.spawn_flow["through_dead_end"] == 1
    assert manager.spawn_flow.get("through_stuck_retired", 0) == 0


def test_retire_clears_all_registries():
    manager, vehicle, driver, world, residents = _midroute()
    manager._enqueue_existing_route_job("recovery", vehicle, (x for x in ()), world)
    manager.rebuild_spatial_grid()
    assert vehicle in manager.nearby_vehicles_at(vehicle.x, vehicle.y)
    manager._retire_finished_through_traffic(residents, VIEW)  # the bound starts when it is first seen stuck
    _past_bound(manager)
    manager._retire_finished_through_traffic(residents, VIEW)
    assert vehicle not in manager.vehicles
    assert vehicle.vehicle_id not in manager.drivers
    assert not any(job["vehicle"] is vehicle for job in manager._route_jobs)
    assert driver.route_job_pending is False
    assert vehicle not in manager.nearby_vehicles_at(vehicle.x, vehicle.y)


def test_non_through_stuck_vehicle_unchanged():
    manager, vehicle, driver, _, residents = _midroute(fast_through=False)
    _past_bound(manager)
    for _ in range(3):
        manager._retire_finished_through_traffic(residents, VIEW)
    assert vehicle in manager.vehicles
    assert driver.recovery_stage == "STUCK"
    assert driver.through_recovery_attempts == 0 and driver.through_stuck_since_tick is None


def _motorway_manager():
    ways = [Way([(i * 500.0, 0.0), ((i + 1) * 500.0, 0.0)], "motorway", 7, oneway=1, speed_limit_kmh=100)
            for i in range(12)]
    world, residents = TrafficWorld(ways), ResidentManager()
    manager = NPCVehicleManager(target_count=20)
    manager.target_moving_count = 4
    manager._active_bounds = (-100.0, -300.0, 6000.0, 300.0)
    manager._player_heading = 0.0
    random.seed(5)
    manager._run_population_tick(0.0, 0.0, residents, world, ways, None, None, None, None, None, None, None,
                                 viewport_bounds=(-150.0, -100.0, 150.0, 100.0), transit_heading=0.0,
                                 motorway_spawns=True)
    return manager, world, residents


def _view(x):
    return (x - 150.0, -100.0, x + 150.0, 100.0)


def test_map_expansion_keeps_pending_motorway_spawn():
    manager, world, residents = _motorway_manager()
    queued = sum(1 for job in manager._route_jobs if job["kind"] == "transit")
    assert queued > 0
    world.route_graph_revision += 1  # a map expansion while the taxi drove on
    player_x = 3000.0
    for _ in range(400):
        manager._advance_route_jobs(player_x, 0.0, residents, world, _view(player_x), budget_s=1.0)
        if not manager._route_jobs:
            break
    assert manager.route_job_stats["replanned"] >= queued
    assert manager.route_job_stats.get("discard_reasons", {}).get("job_stale", 0) == 0
    assert manager.vehicles and all(v.fast_through for v in manager.vehicles)  # still motorway spawns
    assert all(v.x > player_x for v in manager.vehicles), [round(v.x) for v in manager.vehicles]


def test_repeated_map_expansion_preserves_demand():
    manager, world, residents = _motorway_manager()
    queued = len(manager._route_jobs)
    assert queued > 0
    player_x = 0.0
    for _ in range(3):
        world.route_graph_revision += 1
        player_x += 800.0
        manager._advance_route_jobs(player_x, 0.0, residents, world, _view(player_x), budget_s=0.0)
        assert len(manager._route_jobs) + len(manager.vehicles) == queued
    for _ in range(400):
        manager._advance_route_jobs(player_x, 0.0, residents, world, _view(player_x), budget_s=1.0)
        if not manager._route_jobs:
            break
    assert not manager._route_jobs
    assert manager.route_job_stats.get("discard_reasons", {}).get("job_stale", 0) == 0
    assert manager.vehicles and all(v.fast_through and v.x > player_x for v in manager.vehicles)
