"""Live NPC motion must not use open ground as a steering shortcut."""
import math

import pytest

from theroadragetrip.npc import (
    Driver, NPCState, NPCVehicle, PathPoint, _npc_motion_stays_on_road,
    spawn_npc, update_npc,
)
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car, SpatialWayGrid, is_point_on_road
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld


@pytest.mark.parametrize("indexed", [False, True])
def test_bad_initial_heading_stops_before_body_leaves_road(indexed):
    ways = [Way(points_m=[(-100, 0), (0, 0), (100, 0)], highway="residential", half_width_m=4.5)]
    world, residents = TrafficWorld(ways), ResidentManager()
    spawned = spawn_npc(1, residents, world, ways, (0, 0), (80, 0))
    assert spawned is not None
    _, driver, vehicle = spawned
    vehicle.car.x, vehicle.car.y, vehicle.car.heading = 0, 0, -math.pi / 2
    vehicle.car.speed = 20
    grid = SpatialWayGrid(ways) if indexed else None
    for _ in range(40):
        update_npc(vehicle, driver, 1 / 30, world, residents, spatial_grid=grid)
        c, s = math.cos(vehicle.car.heading), math.sin(vehicle.car.heading)
        for along in (-vehicle.length_m / 2, vehicle.length_m / 2):
            for across in (-vehicle.width_m / 2, vehicle.width_m / 2):
                assert is_point_on_road(vehicle.x + c * along - s * across,
                                        vehicle.y + s * along + c * across, ways=ways)
    assert vehicle.state == NPCState.WAITING
    assert driver.recovery_stage == "STUCK"
    assert vehicle.car.speed == 0


def test_swept_guard_rejects_hop_between_disconnected_roads():
    ways = [Way(points_m=[(-10, y), (10, y)], highway="residential", half_width_m=2)
            for y in (0, 10)]
    vehicle = NPCVehicle(1, Car(x=0, y=10, heading=math.pi / 2, speed=0, length_m=3, width_m=1.5))
    driver = Driver(1, 1, [PathPoint(0, 0), PathPoint(0, 10)], (0, 10), current_way=ways[0])
    assert not _npc_motion_stays_on_road(vehicle, driver, (0, 0, math.pi / 2), ways)


def test_other_level_and_footway_cannot_authorize_offroad_motion():
    for highway, layer, map_level in (("residential", 1, None), ("footway", 0, None), ("residential", 0, -1)):
        way = Way(points_m=[(-20, 0), (20, 0)], highway=highway, half_width_m=8,
                  layer=layer, map_level=map_level)
        road = Way(points_m=[(-20, -20), (20, -20)], highway="residential", half_width_m=3, layer=0)
        vehicle = NPCVehicle(1, Car(x=0, y=0, heading=0, speed=0))
        driver = Driver(1, 1, [PathPoint(-10, 0), PathPoint(10, 0)], (10, 0), current_way=road)
        assert not _npc_motion_stays_on_road(vehicle, driver, (-0.1, 0, 0), [road, way])


def test_parking_flag_does_not_exempt_middle_of_trip():
    ways = [Way(points_m=[(-100, 0), (100, 0)], highway="residential", half_width_m=4)]
    vehicle = NPCVehicle(1, Car(x=0, y=15, heading=0, speed=0))
    driver = Driver(1, 1, [PathPoint(-80, 0), PathPoint(80, 0), PathPoint(85, 6)],
                    (85, 6), current_way=ways[0], destination_is_off_road=True)
    assert not _npc_motion_stays_on_road(vehicle, driver, (-0.1, 15, 0), ways)


def test_actual_truck_width_not_default_car_width_controls_guard():
    ways = [Way(points_m=[(-50, 0), (50, 0)], highway="residential", half_width_m=1.1)]
    driver = Driver(1, 1, [PathPoint(-20, 0), PathPoint(20, 0)], (20, 0), current_way=ways[0])
    vehicle = NPCVehicle(1, Car(x=0, y=0, heading=0, speed=0, width_m=2.5, length_m=11))
    assert not _npc_motion_stays_on_road(vehicle, driver, (-0.1, 0, 0), ways)
    vehicle.car.width_m = 1.8
    assert _npc_motion_stays_on_road(vehicle, driver, (-0.1, 0, 0), ways)


def test_transit_endpoint_flag_does_not_authorize_body_overhang_offroad():
    way = Way(points_m=[(-100, 0), (100, 0)], highway="residential", half_width_m=4)
    vehicle = NPCVehicle(1, Car(x=78, y=0, heading=math.pi / 2, speed=0, length_m=11))
    driver = Driver(1, 1, [PathPoint(-80, 0), PathPoint(60, 0), PathPoint(80, 0)],
                    (80, 0), current_way=way, destination_is_off_road=True)
    assert not _npc_motion_stays_on_road(vehicle, driver, (77.9, 0, math.pi / 2), [way])


def test_parking_departure_uses_actual_origin_not_lane_offset_first_point():
    way = Way(points_m=[(-100, 0), (100, 0)], highway="residential", half_width_m=4)
    vehicle = NPCVehicle(1, Car(x=1, y=5, heading=-math.pi / 4, speed=0))
    driver = Driver(1, 1, [PathPoint(3, 3), PathPoint(20, 0), PathPoint(80, 0)],
                    (80, 0), current_way=way, origin_is_off_road=True, trip_origin=(0, 6))
    assert _npc_motion_stays_on_road(vehicle, driver, (0.9, 5.1, -math.pi / 4), [way])
    driver.origin_is_off_road = False
    assert not _npc_motion_stays_on_road(vehicle, driver, (0.9, 5.1, -math.pi / 4), [way])


def test_curved_parking_approach_slows_before_final_waypoint():
    ways = [Way(points_m=[(x, 0), (x + 20, 0)], highway="residential", half_width_m=4.5)
            for x in range(0, 120, 20)]
    world, residents = TrafficWorld(ways), ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (0, 0), (100, -5.9),
                                   destination_is_off_road=True)
    vehicle.car.x, vehicle.car.y, vehicle.car.heading = 85, -2, 0
    update_npc(vehicle, driver, 1 / 30, world, residents)
    assert driver.path_index < len(driver.path) - 1
    assert driver.target_speed_mps <= 10 / 3.6


def test_reverse_cannot_leave_end_of_road():
    ways = [Way(points_m=[(x, 0), (x + 20, 0)], highway="residential", half_width_m=4.5)
            for x in range(0, 120, 20)]
    world, residents = TrafficWorld(ways), ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (0, 0), (100, 0))
    vehicle.state = NPCState.REVERSING
    for _ in range(600):
        update_npc(vehicle, driver, 1 / 30, world, residents)
        if vehicle.state != NPCState.REVERSING:
            break
    assert vehicle.state == NPCState.WAITING
    assert vehicle.car.x > -2
    assert vehicle.car.speed == 0
    assert "road boundary" in vehicle.debug_waiting_for
