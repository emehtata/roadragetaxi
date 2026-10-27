"""Arcade clearance is deliberately not ordinary NPC steering or lawful parking."""
import math

import pytest

from theroadragetrip.geo import boxes_intersect
from theroadragetrip.npc import NPCState, NPCVehicle, NPCVehicleManager, spawn_npc
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car, SpatialWayGrid
from theroadragetrip.residents import ResidentManager
from theroadragetrip.road_rage import RAGE_SECONDS, corridor
from theroadragetrip.traffic_world import TrafficWorld


def setup(heading=0):
    def rotate(x, y):
        return x * math.cos(heading) - y * math.sin(heading), x * math.sin(heading) + y * math.cos(heading)
    ways = [Way([rotate(0, 0), rotate(2000, 0)], "primary", 7)]
    manager = NPCVehicleManager(target_count=0)
    car = Car(*rotate(0, -2), heading, 210 / 3.6)
    return manager, car, ways, SpatialWayGrid(ways), rotate


def add(manager, point, *, layer=0, level=0, state=NPCState.CRUISING, heading=0, length=4.3):
    car = Car(*point, heading, 10, layer=layer, map_level=level)
    vehicle = NPCVehicle(len(manager.vehicles) + 1, car, state=state)
    vehicle.car.length_m = length
    manager.vehicles.append(vehicle)
    manager.rebuild_spatial_grid()
    return vehicle


@pytest.mark.parametrize("heading", [0, math.pi / 2, math.pi, -math.pi / 2])
def test_shout_moves_every_vehicle_for_ten_seconds_of_210_kmh_travel(heading):
    manager, car, ways, grid, rotate = setup(heading)
    targets = [add(manager, rotate(x, y), heading=heading + h, state=state, length=length)
               for x, y, h, state, length in [(20, -2, 0, NPCState.CRUISING, 4.3),
                                             (150, 2, math.pi, NPCState.CRUISING, 4.3),
                                             (400, -2, 0, NPCState.WAITING, 12),
                                             (580, 2, math.pi, NPCState.CRASHED, 4.3),
                                             (300, 0, math.pi / 2, NPCState.PARKED, 4.3)]]
    untouched = [add(manager, rotate(-30, 0)), add(manager, rotate(900, 0)),
                 add(manager, rotate(30, 0), layer=1), add(manager, rotate(30, 0), level=-1)]
    originals = [(v.x, v.y) for v in untouched]
    manager.trigger_road_rage(0)
    manager.road_rage.update(manager, car, 0, ways, grid, ways[0])
    assert set(manager.road_rage.held) == {v.vehicle_id for v in targets}
    assert [(v.x, v.y) for v in untouched] == originals
    for frame in range(300):
        car.x, car.y = rotate(frame / 30 * car.speed, -2)
        manager.road_rage.update(manager, car, frame / 30, ways, grid, ways[0])
        for vehicle in targets:
            assert not boxes_intersect(car.x, car.y, car.heading, car.length_m, car.width_m,
                                                vehicle.x, vehicle.y, vehicle.heading, vehicle.length_m, vehicle.width_m)
            assert vehicle.car.speed == 0


def test_new_arrivals_are_cleared_and_held_cars_return_only_after_the_taxi_passes():
    manager, car, ways, grid, _ = setup()
    manager.trigger_road_rage(0)
    manager.road_rage.update(manager, car, 0, ways, grid, ways[0])
    vehicle = add(manager, (250, -2))
    manager.road_rage.update(manager, car, 1, ways, grid, ways[0])
    assert vehicle.vehicle_id in manager.road_rage.held
    side = vehicle.x, vehicle.y
    manager.road_rage.update(manager, car, RAGE_SECONDS, ways, grid, ways[0])
    assert (vehicle.x, vehicle.y) == side  # not returned into the taxi's forward path
    car.x = 400
    manager.road_rage.update(manager, car, RAGE_SECONDS + 1, ways, grid, ways[0])
    assert (vehicle.x, vehicle.y) == (250, -2)
    assert not manager.road_rage.held


def test_corridor_follows_bends_and_connected_ways_not_a_crossing_bridge():
    manager, car, _, _, _ = setup()
    bend = Way([(0, 0), (200, 0), (350, 150)], "primary", 5)
    continuation = Way([(350, 150), (550, 250)], "primary", 5)
    crossing = Way([(250, 0), (250, 300)], "primary", 5, layer=1)
    ways = [bend, continuation, crossing]
    grid = SpatialWayGrid(ways)
    near = add(manager, (450, 200), heading=math.atan2(100, 200))
    bridge = add(manager, (250, 50), layer=1)
    bridge_pose = bridge.x, bridge.y
    manager.trigger_road_rage(0)
    manager.road_rage.update(manager, car, 0, ways, grid, bend)
    assert near.vehicle_id in manager.road_rage.held
    assert (bridge.x, bridge.y) == bridge_pose
    assert sum(math.hypot(bx - ax, by - ay) for ax, ay, bx, by, *_ in corridor(car, bend, ways, grid)) >= 580


def test_real_manager_updates_do_not_steer_held_drivers_back_into_the_road():
    manager, car, ways, grid, _ = setup()
    world = TrafficWorld(ways)
    residents = ResidentManager()
    spawned = spawn_npc(1, residents, world, ways, (150, 0), (1800, 0))
    assert spawned is not None
    _, driver, vehicle = spawned
    manager.vehicles.append(vehicle)
    manager.drivers[vehicle.vehicle_id] = driver
    manager.trigger_road_rage(0)
    for frame in range(300):
        car.x = frame / 30 * car.speed
        manager.update(1 / 30, car.x, car.y, residents, world, ways, spatial_grid=grid,
                       player_car=car, current_way=ways[0])
        world.advance_time(1 / 30)
        assert abs(vehicle.y) > ways[0].half_width_m
        assert vehicle.state != NPCState.CRASHED
        assert vehicle.car.speed == 0


def test_dense_jam_and_occupied_return_position_never_overlap():
    manager, car, ways, grid, _ = setup()
    vehicles = [add(manager, (50, -2)) for _ in range(25)]
    manager.trigger_road_rage(0)
    manager.road_rage.update(manager, car, 0, ways, grid, ways[0])
    assert len(manager.road_rage.held) == 25
    for i, vehicle in enumerate(vehicles):
        for other in vehicles[i + 1:]:
            assert not boxes_intersect(vehicle.x, vehicle.y, vehicle.heading, vehicle.length_m, vehicle.width_m,
                                       other.x, other.y, other.heading, other.length_m, other.width_m)
    blocker = add(manager, (50, -2))
    car.x = 400
    manager.road_rage.update(manager, car, 11, ways, grid, ways[0])
    assert len(manager.road_rage.held) == 25
    blocker.car.x = -500
    manager.rebuild_spatial_grid()
    manager.road_rage.update(manager, car, 12, ways, grid, ways[0])
    assert len(manager.road_rage.held) == 24  # only one may occupy the original slot


def test_dense_way_points_still_clear_a_full_ten_second_distance():
    manager, car, _, _, _ = setup()
    way = Way([(i / 4, 0) for i in range(4001)], "primary", 7)
    segments = corridor(car, way, [way], SpatialWayGrid([way]))
    assert sum(math.hypot(bx - ax, by - ay) for ax, ay, bx, by, *_ in segments) >= car.speed * 10


def test_a_second_shout_extends_the_window_but_updates_do_not():
    manager, car, ways, grid, _ = setup()
    manager.trigger_road_rage(0)
    manager.road_rage.update(manager, car, 5, ways, grid, ways[0])
    assert manager.road_rage.until == 10
    manager.trigger_road_rage(8)
    manager.road_rage.update(manager, car, 9, ways, grid, ways[0])
    assert manager.road_rage.until == 18


def test_population_does_not_queue_recovery_for_displaced_cars(monkeypatch):
    manager, car, ways, grid, _ = setup()
    world, residents = TrafficWorld(ways), ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (150, 0), (1800, 0))
    manager.vehicles.append(vehicle)
    manager.drivers[vehicle.vehicle_id] = driver
    manager.min_count = 0
    manager.rebuild_spatial_grid()
    manager.trigger_road_rage(0)
    manager.road_rage.update(manager, car, 0, ways, grid, ways[0])
    driver.recovery_stage = "STUCK"
    queued = []
    monkeypatch.setattr(manager, "_enqueue_existing_route_job", lambda kind, *a, **k: queued.append(kind))
    manager._run_population_tick(car.x, car.y, residents, world, ways, grid, [], [], [], [], None, None)
    assert queued == []
    assert vehicle.vehicle_id in manager.road_rage.held


def test_minimal_manager_population_diagnostics_stay_compatible():
    manager = NPCVehicleManager.__new__(NPCVehicleManager)
    manager.vehicles = [NPCVehicle(1, Car(0, 0, 0, 0))]
    assert manager.population_counts()["road_rage"] == 0


def test_clearance_indexes_a_late_spawn_before_choosing_a_slot():
    manager, car, ways, grid, _ = setup()
    vehicle = add(manager, (50, -2))
    radius = math.hypot(vehicle.length_m, vehicle.width_m) * 0.5
    slot = -(ways[0].half_width_m + radius + car.width_m + 3)
    late = NPCVehicle(2, Car(50, slot, 0, 0), state=NPCState.PARKED)
    manager.vehicles.append(late)  # deliberately not indexed yet
    manager.trigger_road_rage(0)
    manager.road_rage.update(manager, car, 0, ways, grid, ways[0])
    from theroadragetrip.taxi_brawls import PROVOKE_CLEARANCE, npc_rage
    assert npc_rage(vehicle, 0) == PROVOKE_CLEARANCE  # shoved aside: its driver is angry
    assert not boxes_intersect(vehicle.x, vehicle.y, vehicle.heading, vehicle.length_m, vehicle.width_m,
                               late.x, late.y, late.heading, late.length_m, late.width_m)
