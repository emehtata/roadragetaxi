"""Regressions from the four-wreck pile-up on a suburban street, screenshot 1792606300483339008."""
import math

import pytest

from theroadragetrip.npc import (
    Driver, NPCState, NPCVehicleManager, build_driving_path, place_parked_npc,
)
from theroadragetrip.osm import Way
from theroadragetrip.physics import SpatialWayGrid
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld


def _junction(monkeypatch, angle, mirror):
    """The screenshot's cached road centreline, relative to its junction."""
    def point(x, y):
        y *= mirror
        return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)

    east = [point(69.942515, 12.571805), point(59.892589, 10.761264), point(0, 0)]
    north = [point(0, 0), point(-14.914103, 59.922144), point(-26.590811, 98.077940)]
    road = Way(points_m=[point(220, 40)] + east + north[1:] + [point(-65, 250)],
               name="Kotitie", highway="residential", half_width_m=4.5, speed_limit_kmh=30)
    side = Way(points_m=[point(-100, -25), point(-6, -1.35), point(0, 0)],
               name="Kotikuja", highway="residential", half_width_m=4.5, speed_limit_kmh=30)
    ways = [road, side]
    world, residents = TrafficWorld(ways), ResidentManager()
    manager = NPCVehicleManager(target_count=2)
    # Keep the real indexed driving/collision loop; isolate it from unrelated trip demand.
    monkeypatch.setattr(manager, "_run_population_tick", lambda *args, **kwargs: None)
    grid = SpatialWayGrid(ways)
    routes = [
        [north[1], point(0, 0), east[1], east[0], point(220, 40)],
        [east[0], east[1], point(0, 0), north[1], north[2], point(-65, 250)],
    ]
    for vehicle_id, route in enumerate(routes, 1):
        path = build_driving_path(route, ways, spatial_grid=grid)
        vehicle = place_parked_npc(vehicle_id, (path[0].x, path[0].y), None, vehicle_type="car")
        vehicle.car.heading = math.atan2(path[1].y - path[0].y, path[1].x - path[0].x)
        vehicle.car.speed = 30 / 3.6
        resident = residents.create(mode="driving")
        vehicle.owner_id = resident.resident_id
        resident.active_vehicle_id = vehicle_id
        vehicle.state = NPCState.CRUISING
        driver = Driver(resident.resident_id, vehicle_id, path, (path[-1].x, path[-1].y))
        manager.vehicles.append(vehicle)
        manager.drivers[vehicle_id] = driver
    return manager, world, residents, ways, grid, point


def _tick(manager, world, residents, ways, grid):
    manager.update(1 / 30, 0, 0, residents, world, ways, spatial_grid=grid)
    world.sim_time += 1 / 30


@pytest.mark.parametrize("angle", [0, math.pi / 2, math.pi, math.pi * 1.5])
@pytest.mark.parametrize("mirror", [1, -1])
def test_opposing_cars_clear_the_suburban_bend_without_crashing(monkeypatch, angle, mirror):
    manager, world, residents, ways, grid, _ = _junction(monkeypatch, angle, mirror)
    starts = [(v.x, v.y) for v in manager.vehicles]
    for _ in range(30 * 25):
        _tick(manager, world, residents, ways, grid)
        assert all(v.state != NPCState.CRASHED for v in manager.vehicles)
    for vehicle, start in zip(manager.vehicles, starts):
        assert math.dist((vehicle.x, vehicle.y), start) > 100
        assert manager.drivers[vehicle.vehicle_id].recovery_stage == "NORMAL"


@pytest.mark.parametrize("angle", [0, math.pi / 2, math.pi, math.pi * 1.5])
@pytest.mark.parametrize("mirror", [1, -1])
def test_car_brakes_for_wreck_around_bend_and_resumes_when_it_clears(monkeypatch, angle, mirror):
    manager, world, residents, ways, grid, point = _junction(monkeypatch, angle, mirror)
    follower, wreck = manager.vehicles
    driver = manager.drivers[follower.vehicle_id]
    # Reflect the road, then place the wreck on the right-hand travel lane;
    # reflecting its lane offset too would put it in the opposing lane.
    cx, cy = point(9.5, 1.7)
    road_heading = angle + mirror * math.atan2(10.761264, 59.892589)
    wreck.car.x = cx + math.sin(road_heading) * 1.2
    wreck.car.y = cy - math.cos(road_heading) * 1.2
    wreck.car.heading = angle + mirror * 0.13434
    wreck.car.speed = 0
    wreck.state = NPCState.CRASHED
    manager.drivers.pop(wreck.vehicle_id)
    blocker = place_parked_npc(3, (cx - math.sin(road_heading) * 2,
                                   cy + math.cos(road_heading) * 2), None, vehicle_type="car")
    blocker.car.heading = road_heading + math.pi
    blocker.state = NPCState.CRASHED
    manager.vehicles.append(blocker)  # the pile-up also occupies the opposing lane
    for _ in range(30 * 20):  # well beyond the old eight-second stuck timeout
        _tick(manager, world, residents, ways, grid)
        assert follower.state != NPCState.CRASHED
    assert driver.recovery_stage == "NORMAL"
    assert follower.speed < 0.1
    assert math.dist((follower.x, follower.y), (wreck.x, wreck.y)) > (follower.length_m + wreck.length_m) / 2 + 2
    stopped = (follower.x, follower.y)
    manager.vehicles.remove(wreck)  # the existing tow cleanup removes the blockage
    manager.vehicles.remove(blocker)
    for _ in range(30 * 20):
        _tick(manager, world, residents, ways, grid)
        assert follower.state != NPCState.CRASHED
    assert math.dist((follower.x, follower.y), stopped) > 50
    assert driver.recovery_stage == "NORMAL"


@pytest.mark.parametrize("upper_level", [False, True])
def test_passing_checks_the_whole_body_in_the_opposing_lane(monkeypatch, upper_level):
    from theroadragetrip.npc import spawn_npc

    ways = [Way(points_m=[(i * 20, 0), ((i + 1) * 20, 0)], highway="residential",
                half_width_m=4.5, speed_limit_kmh=30) for i in range(20)]
    world, residents = TrafficWorld(ways), ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    monkeypatch.setattr(manager, "_run_population_tick", lambda *args, **kwargs: None)
    grid = SpatialWayGrid(ways)
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (0, 0), (300, 0))
    manager.vehicles.append(vehicle)
    manager.drivers[1] = driver
    wreck = place_parked_npc(2, (vehicle.x + 40, vehicle.y), None, vehicle_type="car")
    wreck.state = NPCState.CRASHED
    manager.vehicles.append(wreck)
    blocker = place_parked_npc(3, (wreck.x + 15, vehicle.y + 2), None, vehicle_type="bus")
    blocker.car.heading = math.pi
    blocker.car.map_level = 1 if upper_level else 0
    manager.vehicles.append(blocker)
    for _ in range(30 * 25):
        _tick(manager, world, residents, ways, grid)
        assert vehicle.state != NPCState.CRASHED
    if upper_level:
        assert vehicle.x > wreck.x + 12  # a vehicle on the bridge must not block passing below
    else:
        assert driver.passing is None and vehicle.x < wreck.x
        assert driver.recovery_stage == "NORMAL"
