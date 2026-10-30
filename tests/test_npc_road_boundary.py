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
    # It stops at the kerb (never leaving the road, checked every step above), then -
    # setting off - plans a manoeuvre (npc._plan_manoeuvre) rather than waiting stuck.
    assert driver.manoeuvre is not None or (vehicle.state == NPCState.WAITING and driver.recovery_stage == "STUCK")


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


def test_replanned_departure_cannot_move_access_permission_across_map():
    way = Way(points_m=[(-100, 0), (300, 0)], highway="residential", half_width_m=4)
    vehicle = NPCVehicle(1, Car(x=100, y=6, heading=0, speed=0))
    driver = Driver(1, 1, [PathPoint(100, 6), PathPoint(110, 0), PathPoint(200, 0)],
                    (200, 0), current_way=way, origin_is_off_road=True, trip_origin=(0, 6))
    assert not _npc_motion_stays_on_road(vehicle, driver, (99.9, 6, 0), [way])


def test_a_turn_may_cut_the_kerb_corner_at_a_junction_but_not_leave_an_open_road():
    """Bug: turning cars crossed the square kerb corner of two straight road
    strips, were stopped ("road boundary") and stood in the road for good."""
    from theroadragetrip.npc import NPCState

    crossing = [Way(points_m=[(-50, 0), (50, 0)], highway="residential", half_width_m=3.0),
                Way(points_m=[(0, -50), (0, 50)], highway="residential", half_width_m=3.0)]
    vehicle = NPCVehicle(1, Car(x=2.6, y=2.6, heading=math.pi / 4, speed=3, length_m=4.3, width_m=1.8))
    driver = Driver(1, 1, [PathPoint(2.0, 2.0), PathPoint(2.6, 2.6)], (0, 50), current_way=crossing[0])
    vehicle.state = NPCState.TURNING  # its body's outer corners hang over the square corner
    assert _npc_motion_stays_on_road(vehicle, driver, (2.0, 2.0, math.pi / 4), crossing)
    open_road = crossing[:1]
    vehicle.car.x, vehicle.car.y = 0.0, 2.6
    assert not _npc_motion_stays_on_road(vehicle, driver, (0.0, 2.0, math.pi / 4), open_road)


def test_town_traffic_spawns_already_cruising_but_can_stop_before_its_turn():
    from theroadragetrip.npc import _transit_initial_speed, place_parked_npc

    street = Way([(0, 0), (500, 0)], "residential", 4.0, speed_limit_kmh=40)
    vehicle = place_parked_npc(1, (0, 2), None)
    path = [PathPoint(float(x), 2.0, way=street) for x in range(0, 401, 20)]
    assert _transit_initial_speed(vehicle, (path, (400, 2), None, False)) == pytest.approx(40 / 3.6 * 0.8)
    short = [PathPoint(0.0, 2.0, way=street), PathPoint(10.0, 2.0, way=street)]  # 10 m to its end: slower, still moving
    speed = _transit_initial_speed(vehicle, (short, (10, 2), None, False))
    assert 0 < speed < 40 / 3.6 * 0.8 and speed * speed / (2 * 3.0) + vehicle.length_m <= 10.0
