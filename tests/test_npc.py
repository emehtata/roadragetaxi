"""Tests for NPC-001: the first autonomous NPC car (theroadragetrip.npc)."""
import math
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
import pytest

from theroadragetrip.render.vehicles import draw_npc_cars
from theroadragetrip.npc import (
    Driver,
    NPCState,
    NPCVehicle,
    _lane_offset_point,
    NPC_BUILDING_YARD_CLEARANCE_M,
    _align_approach_to_parking_orientation,
    _building_yard_point,
    _pick_npc_destination,
    build_driving_path,
    has_active_driver,
    route_crosses_buildings,
    route_crosses_curbs,
    spawn_deterministic_npc,
    spawn_npc,
    update_npc,
)
from theroadragetrip.osm import Building, Curb, ParkingSpace, Scenery, TrafficLight, Way
from theroadragetrip.physics import Car
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_rules import TrafficAction, decide_traffic_action
from theroadragetrip.traffic_world import TrafficWorld


def _straight_chain(count: int = 10, step_m: float = 20.0):
    """A long straight chain of ways - enough real graph nodes that
    TrafficWorld.plan_route's nearest-node search can't mistake the start
    itself for a cheap stand-in target (see npc.spawn_deterministic_npc's
    docstring for why that matters)."""
    return [
        Way(
            points_m=[(i * step_m, 0.0), ((i + 1) * step_m, 0.0)],
            highway="residential", half_width_m=4.5,
        )
        for i in range(count)
    ]


def test_moving_npc_vehicle_has_a_resident_driver():
    ways = _straight_chain()
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    result = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))
    assert result is not None
    resident_id, driver, vehicle = result
    assert vehicle.owner_id == resident_id == driver.resident_id
    resident = residents.get(resident_id)
    assert resident is not None
    assert resident.active_vehicle_id == vehicle.vehicle_id
    assert has_active_driver(vehicle, residents)


def test_vehicle_without_a_driver_never_moves():
    """A vehicle cannot enter the active driving state without a driver -
    update_npc must refuse to move it."""
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    vehicle = NPCVehicle(vehicle_id=1, car=car, owner_id=None)
    driver = Driver(resident_id=1, vehicle_id=1, path=build_driving_path(
        [(0.0, 0.0), (100.0, 0.0)], _straight_chain()
    ), destination=(100.0, 0.0))
    residents = ResidentManager()
    tw = TrafficWorld(_straight_chain())

    for _ in range(120):
        update_npc(vehicle, driver, 1.0 / 60.0, tw, residents)

    assert vehicle.speed == 0.0
    assert vehicle.x == 0.0 and vehicle.y == 0.0


def test_route_is_calculated_before_driving_starts():
    """spawn_npc must plan (and validate) the route before returning a
    vehicle - never a vehicle that then hunts for a route while driving."""
    ways = _straight_chain()
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    result = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))
    assert result is not None
    _, driver, _ = result
    assert len(driver.path) >= 3  # multiple real road segments, not just endpoints


def test_spawn_fails_cleanly_when_no_route_exists():
    """No connected road network at all -> no vehicle, no orphaned Resident."""
    residents = ResidentManager()
    tw = TrafficWorld([])
    result = spawn_npc(1, residents, tw, [], (0.0, 0.0), (200.0, 0.0))
    assert result is None
    assert len(residents.residents) == 0


def test_spawn_rejects_a_route_that_shortcuts_across_empty_land():
    """Regression: plan_route's nearest-node search can, on a small/
    lopsided graph, pick a node close to the START as a cheaper stand-in
    "last mile" target than the real road path - producing a route that
    quietly cuts across a corner instead of following the road through
    it. spawn_npc must reject that route rather than spawn onto it."""
    way1 = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5)
    way2 = Way(points_m=[(100.0, 0.0), (100.0, 100.0)], highway="residential", half_width_m=4.5)
    tw = TrafficWorld([way1, way2])
    residents = ResidentManager()
    result = spawn_npc(1, residents, tw, [way1, way2], (0.0, 0.0), (100.0, 100.0))
    assert result is None
    assert len(residents.residents) == 0


def test_route_progression_advances():
    ways = _straight_chain()
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))

    start_index = driver.path_index
    for _ in range(600):
        update_npc(vehicle, driver, 1.0 / 60.0, tw, residents)
    assert driver.path_index > start_index


def test_deterministic_npc_eventually_reaches_its_destination():
    ways = _straight_chain()
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))

    assert vehicle.state == NPCState.SPAWNING
    seen_states = set()
    for _ in range(1800):
        update_npc(vehicle, driver, 1.0 / 60.0, tw, residents)
        seen_states.add(vehicle.state)
        if vehicle.state == NPCState.ARRIVING:
            break
    assert vehicle.state == NPCState.ARRIVING
    assert NPCState.CRUISING in seen_states
    # Confirmed to actually settle, not just touch ARRIVING once and then
    # spin off - a real regression this project already hit once (see
    # update_npc's "at_destination" steering-freeze comment).
    for _ in range(120):
        update_npc(vehicle, driver, 1.0 / 60.0, tw, residents)
    assert vehicle.state == NPCState.ARRIVING
    assert abs(vehicle.speed) < 0.5


def test_red_light_produces_stop():
    tl = TrafficLight(x=100.0, y=0.0, cycle_time=1e9, offset=0.0, direction_angle=0.0)
    decision = decide_traffic_action(96.5, 0.0, 0.0, [tl], sim_time=10.0, speed_limit_mps=13.9)
    assert decision.action == TrafficAction.STOP


def test_green_light_allows_proceed():
    tl = TrafficLight(x=100.0, y=0.0, cycle_time=1e9, offset=0.0, direction_angle=0.0)
    decision = decide_traffic_action(70.0, 0.0, 0.0, [tl], sim_time=2.0, speed_limit_mps=13.9)
    assert decision.action == TrafficAction.PROCEED


def test_yellow_is_a_distinct_decision_not_treated_as_green():
    tl = TrafficLight(x=100.0, y=0.0, cycle_time=1e9, offset=0.0, direction_angle=0.0)
    # Far enough to comfortably stop -> must slow, not proceed as if green.
    far = decide_traffic_action(60.0, 0.0, 0.0, [tl], sim_time=6.0, speed_limit_mps=13.9)
    assert far.action == TrafficAction.SLOW
    # Too close to stop safely -> already committed, proceeds through.
    close = decide_traffic_action(95.0, 0.0, 0.0, [tl], sim_time=6.0, speed_limit_mps=13.9)
    assert close.action == TrafficAction.PROCEED


def test_decision_carries_the_actual_light_it_was_based_on():
    """NPC-002 section 18/21: the decision must expose which physical
    signal it judged relevant, not just a text reason - so a debug HUD (or
    a test) can check the movement it actually allows."""
    tl = TrafficLight(
        x=100.0, y=0.0, cycle_time=1e9, offset=0.0, direction_angle=0.0,
        approach_id="junction:0", allowed_movements=frozenset({"straight", "right"}),
    )
    decision = decide_traffic_action(96.5, 0.0, 0.0, [tl], sim_time=10.0, speed_limit_mps=13.9)
    assert decision.light is tl

    no_light = decide_traffic_action(0.0, 0.0, 0.0, [], sim_time=10.0, speed_limit_mps=13.9)
    assert no_light.light is None


def test_opposite_direction_light_is_ignored():
    """A light facing the opposite/crossing approach must never be
    mistaken for the one governing this lane."""
    tl = TrafficLight(x=100.0, y=0.0, cycle_time=1e9, offset=0.0, direction_angle=math.pi)
    decision = decide_traffic_action(70.0, 0.0, 0.0, [tl], sim_time=10.0, speed_limit_mps=13.9)
    assert decision.action == TrafficAction.PROCEED


def test_stop_position_remains_stable_while_approaching():
    """NPC-002 section 8/11: the stop target must not be recomputed to a
    new arbitrary point every frame - it should stay pinned to the stop
    line regardless of how far away the vehicle currently is."""
    tl = TrafficLight(x=100.0, y=0.0, cycle_time=1e9, offset=0.0, direction_angle=0.0)
    far = decide_traffic_action(60.0, 0.0, 0.0, [tl], sim_time=10.0, speed_limit_mps=13.9)
    near = decide_traffic_action(90.0, 0.0, 0.0, [tl], sim_time=10.0, speed_limit_mps=13.9)
    assert math.isclose(far.stop_position[0], near.stop_position[0], abs_tol=0.01)
    assert math.isclose(far.stop_position[1], near.stop_position[1], abs_tol=0.01)


def test_vehicle_stops_before_the_intersection_not_inside_it():
    ways = _straight_chain()
    tl = TrafficLight(x=120.0, y=0.0, cycle_time=1e9, offset=0.0, direction_angle=0.0)
    tw = TrafficWorld(ways, traffic_lights=[tl])
    tw.sim_time = 10.0  # within the huge cycle's "red" window, frozen (never advanced) - permanently red
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))

    min_distance_to_light = math.inf
    reached_waiting = False
    for _ in range(3600):
        update_npc(vehicle, driver, 1.0 / 60.0, tw, residents)
        min_distance_to_light = min(min_distance_to_light, math.hypot(tl.x - vehicle.x, tl.y - vehicle.y))
        if vehicle.state == NPCState.WAITING:
            reached_waiting = True
            break

    assert reached_waiting
    assert min_distance_to_light > 3.0  # never entered the light's own footprint


def test_straight_route_keeps_a_single_lane_no_turn_points():
    way = Way(points_m=[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5)
    path = build_driving_path([(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], [way])
    assert all(not point.is_turn for point in path)
    # Right-hand traffic: offset to the right of travel direction (east -> -y).
    assert all(point.y < 0.0 for point in path)


def test_right_turn_produces_a_smooth_trajectory_aligned_with_outgoing_road():
    way1 = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5)
    way2 = Way(points_m=[(100.0, 0.0), (100.0, -100.0)], highway="residential", half_width_m=4.5)
    path = build_driving_path([(0.0, 0.0), (100.0, 0.0), (100.0, -100.0)], [way1, way2])

    turn_points = [p for p in path if p.is_turn]
    assert len(turn_points) >= 3  # a real sampled arc, not a single pivot vertex
    assert all(p.maneuver == "right" for p in turn_points)
    outgoing_heading = math.degrees(math.atan2(path[-1].y - path[-2].y, path[-1].x - path[-2].x))
    assert math.isclose(outgoing_heading, -90.0, abs_tol=1.0)
    # NPC-002 section 14/17: heading must change continuously through the
    # arc - no single-vertex 90-degree pivot.
    headings = [
        math.degrees(math.atan2(b.y - a.y, b.x - a.x)) for a, b in zip(path, path[1:])
    ]
    deltas = [abs((h2 - h1 + 180.0) % 360.0 - 180.0) for h1, h2 in zip(headings, headings[1:])]
    assert all(delta < 45.0 for delta in deltas)
    # Past the turn, lane placement returns to the default cruising offset.
    assert path[-1].lane_bias is None


def test_left_turn_produces_a_smooth_trajectory_aligned_with_outgoing_road():
    way1 = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5)
    way2 = Way(points_m=[(100.0, 0.0), (100.0, 100.0)], highway="residential", half_width_m=4.5)
    path = build_driving_path([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], [way1, way2])

    turn_points = [p for p in path if p.is_turn]
    assert len(turn_points) >= 3
    assert all(p.maneuver == "left" for p in turn_points)
    outgoing_heading = math.degrees(math.atan2(path[-1].y - path[-2].y, path[-1].x - path[-2].x))
    assert math.isclose(outgoing_heading, 90.0, abs_tol=1.0)


def test_lane_offset_point_hugs_curb_for_right_turn_centerline_for_left():
    """NPC-002 section 5/14/15: lane selection must not just drive the
    geometric center - a turning maneuver should bias within the
    right-hand half of the road: further right (curb) for a right turn,
    closer to the centerline for a left turn, than default cruising."""
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=6.0)
    _, default_y = _lane_offset_point(way, 0.0, 0.0, 0.0)
    _, right_y = _lane_offset_point(way, 0.0, 0.0, 0.0, maneuver="right")
    _, left_y = _lane_offset_point(way, 0.0, 0.0, 0.0, maneuver="left")
    assert abs(right_y) > abs(default_y) > abs(left_y)


def test_right_turn_path_points_are_tagged_with_the_right_lane_bias():
    way1 = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5)
    way2 = Way(points_m=[(100.0, 0.0), (100.0, -100.0)], highway="residential", half_width_m=4.5)
    path = build_driving_path([(0.0, 0.0), (100.0, 0.0), (100.0, -100.0)], [way1, way2])
    turn_points = [p for p in path if p.is_turn]
    assert turn_points and all(p.lane_bias == "right" for p in turn_points)


def test_left_turn_path_points_are_tagged_with_the_left_lane_bias():
    way1 = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5)
    way2 = Way(points_m=[(100.0, 0.0), (100.0, 100.0)], highway="residential", half_width_m=4.5)
    path = build_driving_path([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], [way1, way2])
    turn_points = [p for p in path if p.is_turn]
    assert turn_points and all(p.lane_bias == "left" for p in turn_points)


def test_driver_next_way_reports_the_road_beyond_the_upcoming_turn():
    way1 = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5, name="First St")
    way2 = Way(points_m=[(100.0, 0.0), (100.0, 100.0)], highway="residential", half_width_m=4.5, name="Second St")
    path = build_driving_path([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], [way1, way2])
    driver = Driver(resident_id=1, vehicle_id=1, path=path, destination=(100.0, 100.0), current_way=way1)
    assert driver.next_way is way2


def test_driver_vehicle_resident_ids_stay_consistent():
    ways = _straight_chain()
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    resident_id, driver, vehicle = spawn_npc(7, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))
    assert vehicle.vehicle_id == driver.vehicle_id == 7
    assert vehicle.owner_id == driver.resident_id == resident_id


def test_npc_reports_parking_state_on_final_approach_to_a_dedicated_space():
    """NPC-more.md section 14: the final approach into a dedicated parking
    space should read as a distinct PARKING state, not generic TURNING."""
    ways = _straight_chain(count=20)
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    space = ParkingSpace(
        points_m=[(400.0, 4.0), (401.0, 4.0), (401.0, 10.0), (400.0, 10.0)],
        bbox=(400.0, 4.0, 401.0, 10.0),
        osm_id=101,
    )
    result = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (400.0, 5.0), parking_space=space)
    assert result is not None
    _, driver, vehicle = result
    assert vehicle.destination_parking_space_id == space.osm_id

    seen_states = set()
    for _ in range(1800):
        update_npc(vehicle, driver, 1.0 / 60.0, tw, residents)
        seen_states.add(vehicle.state)
        if vehicle.state == NPCState.ARRIVING:
            break
    assert NPCState.PARKING in seen_states


def test_state_machine_transitions_are_valid():
    ways = _straight_chain()
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))
    assert vehicle.state == NPCState.SPAWNING

    update_npc(vehicle, driver, 1.0 / 60.0, tw, residents)
    # First tick must leave SPAWNING for a real driving state - never stay
    # stuck "spawning" forever.
    assert vehicle.state != NPCState.SPAWNING
    assert vehicle.state in (NPCState.CRUISING, NPCState.TURNING, NPCState.APPROACHING_INTERSECTION)


def test_spawn_deterministic_npc_on_a_city_block_grid():
    """Regression: picking the single farthest point in the whole graph
    by straight-line distance (tried first) routinely chose a destination
    whose real road path was a long detour - tripping plan_route's own
    nearest-node "last mile" substitution (see its docstring) and making
    route_stays_on_road correctly, but uselessly, reject the route, so
    spawn_deterministic_npc would silently find no NPC to spawn on a real
    city map (this is exactly what happened against real cached Oulu OSM
    data during development). A grid of city blocks - short detours
    everywhere, like a real street grid - is what the BFS-hop destination
    (see _bfs_destination_order) is meant to handle reliably."""
    ways = []
    block_count, step_m = 6, 40.0
    for row in range(block_count):
        for i in range(block_count - 1):
            ways.append(Way(points_m=[(i * step_m, row * step_m), ((i + 1) * step_m, row * step_m)], highway="residential", half_width_m=4.5))
    for col in range(block_count):
        for i in range(block_count - 1):
            ways.append(Way(points_m=[(col * step_m, i * step_m), (col * step_m, (i + 1) * step_m)], highway="residential", half_width_m=4.5))

    tw = TrafficWorld(ways)
    residents = ResidentManager()
    # A destination is never a bare road point (see _pick_npc_destination) -
    # one building near the middle of the grid is within NPC_DESTINATION_
    # SEARCH_RADIUS_M of every node the BFS walk could possibly reach here.
    building = Building(points_m=[(90, 90), (110, 90), (110, 110), (90, 110)], entrances=[(100.0, 90.0)], center_m=(100.0, 100.0))
    result = spawn_deterministic_npc(residents, tw, ways, buildings=[building])
    assert result is not None
    _, driver, vehicle = result
    assert len(driver.path) >= 3


def test_building_yard_point_offsets_outward_from_an_entrance_on_the_wall():
    """Regression: an entrance node sits literally ON the building's own
    outline (see osm/build.py) - using it bare put the NPC's own body
    right on top of the building (reported: "the car ended on a
    building"). The yard point must land NPC_BUILDING_YARD_CLEARANCE_M
    outside the wall, away from the building's center."""
    building = Building(points_m=[(0, 0), (10, 0), (10, 10), (0, 10)], entrances=[(10.0, 5.0)], center_m=(5.0, 5.0))
    point = _building_yard_point(building, from_x=100.0, from_y=5.0)
    assert point == (5.0 + 5.0 + NPC_BUILDING_YARD_CLEARANCE_M, 5.0)


def test_building_yard_point_uses_nearest_outline_point_without_an_entrance():
    building = Building(points_m=[(0, 0), (10, 0), (10, 10), (0, 10)], center_m=(5.0, 5.0))
    point = _building_yard_point(building, from_x=5.0, from_y=-100.0)
    # nearest wall point (5,0), pushed the clearance distance further from center.
    assert point == (5.0, 0.0 - NPC_BUILDING_YARD_CLEARANCE_M)


def test_pick_npc_destination_prefers_the_nearest_free_parking_space():
    occupied = ParkingSpace(points_m=[(0, -1), (2, -1), (2, 1), (0, 1)], bbox=(0.0, -1.0, 2.0, 1.0), occupied=True)
    reserved = ParkingSpace(points_m=[(10, -1), (12, -1), (12, 1), (10, 1)], bbox=(10.0, -1.0, 12.0, 1.0), reserved=True)
    free = ParkingSpace(points_m=[(20, -1), (22, -1), (22, 1), (20, 1)], bbox=(20.0, -1.0, 22.0, 1.0))
    point, space = _pick_npc_destination(0.0, 0.0, parking_spaces=[occupied, reserved, free], buildings=None)
    assert point == (21.0, 0.0)
    assert space is free


def test_pick_npc_destination_prefers_a_parking_lot_over_a_building():
    lot = Scenery(points_m=[], kind="parking", bbox=(10.0, -1.0, 12.0, 1.0))
    building = Building(points_m=[(0, 0), (10, 0), (10, 10), (0, 10)], entrances=[(30.0, 0.0)])
    point, space = _pick_npc_destination(0.0, 0.0, sceneries=[lot], buildings=[building])
    assert point == (11.0, 0.0)
    assert space is None  # a parking lot isn't an individually reservable space


def test_pick_npc_destination_falls_back_to_building_entrance_without_parking():
    # Entrance at the midpoint of the right edge, on the wall as real OSM
    # entrance nodes are - offset outward from center_m by the yard
    # clearance: (5,5) + (5,0) normalized * (5+clearance).
    building = Building(points_m=[(0, 0), (10, 0), (10, 10), (0, 10)], entrances=[(10.0, 5.0)], center_m=(5.0, 5.0))
    point, space = _pick_npc_destination(0.0, 0.0, parking_spaces=None, buildings=[building])
    assert point == (5.0 + 5.0 + NPC_BUILDING_YARD_CLEARANCE_M, 5.0)
    assert space is None


def test_pick_npc_destination_falls_back_to_building_boundary_without_entrances():
    # No entrance - nearest point on the outline to the search origin
    # (0,0) is the (0,0) corner itself, then pushed outward from center_m
    # (5,5) away from the building: (0,0) + normalize((0,0)-(5,5)) * clearance.
    building = Building(points_m=[(0, 0), (10, 0), (10, 10), (0, 10)], center_m=(5.0, 5.0))
    point, space = _pick_npc_destination(0.0, 0.0, parking_spaces=None, buildings=[building])
    offset = NPC_BUILDING_YARD_CLEARANCE_M / math.hypot(5.0, 5.0)
    assert point == pytest.approx((0.0 - 5.0 * offset, 0.0 - 5.0 * offset))


def test_pick_npc_destination_refuses_the_raw_point_when_nothing_is_nearby():
    """NPC-more.md section 2: a road carriageway (the raw BFS point itself)
    is never a valid place to stop - regression, this used to fall back to
    it and park/stop the NPC in the middle of a driving lane."""
    far_space = ParkingSpace(points_m=[], bbox=(1000.0, 1000.0, 1002.0, 1002.0))
    point, space = _pick_npc_destination(0.0, 0.0, parking_spaces=[far_space], buildings=None)
    assert point is None
    assert space is None


def test_align_approach_to_parking_orientation_is_a_no_op_without_a_space():
    route = [(0.0, 0.0), (100.0, 0.0)]
    assert _align_approach_to_parking_orientation(route, None) == route


def test_align_approach_to_parking_orientation_inserts_a_waypoint_along_the_space_axis():
    """NPC-more.md section 15: approach a parking space along its own
    orientation, not whatever direction the road happened to point.
    No orientation tag here - the fallback derives the axis from the
    space polygon's own longest edge (a 1x6 rectangle -> north-south)."""
    route = [(0.0, 0.0), (100.0, 0.0)]
    space = ParkingSpace(
        points_m=[(100.0, -1.0), (101.0, -1.0), (101.0, 5.0), (100.0, 5.0)],
        bbox=(100.0, -1.0, 101.0, 5.0),
    )
    result = _align_approach_to_parking_orientation(route, space)
    assert result == [(0.0, 0.0), (100.0, -6.0), (100.0, 0.0)]


def test_spawn_npc_final_heading_matches_the_parking_space_orientation():
    """End to end: the actual driven path's last segment must approach
    along the space's own axis, not the road's."""
    ways = _straight_chain(count=20)
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    space = ParkingSpace(
        points_m=[(400.0, 4.0), (401.0, 4.0), (401.0, 10.0), (400.0, 10.0)],
        bbox=(400.0, 4.0, 401.0, 10.0),
    )
    result = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (400.0, 5.0), parking_space=space)
    assert result is not None
    _, driver, _ = result
    final_heading = math.atan2(
        driver.path[-1].y - driver.path[-2].y, driver.path[-1].x - driver.path[-2].x,
    )
    # Space's long axis is north-south (pi/2) - the corner-rounded arrival
    # arc (see _round_corner) means the very last segment isn't pixel-
    # exact, but it must land far closer to north than to the chain's own
    # east-west (0) heading it would have used without this alignment.
    assert abs(final_heading - math.pi / 2.0) < abs(final_heading - 0.0)


def test_spawn_deterministic_npc_routes_to_a_free_parking_space_when_one_exists():
    """The BFS-hop destination alone can land anywhere on the road graph -
    the middle of an intersection, an arbitrary block. Handing
    spawn_deterministic_npc the map's parking spaces must make the NPC's
    actual destination the nearest free one instead."""
    ways = _straight_chain(count=20)
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    # This chain's fixed-hop BFS walk lands at (400.0, 0.0) - see
    # _bfs_destination_order/NPC_ROUTE_MAX_HOPS - so a space placed right next
    # to it is the nearest one and should become the actual destination.
    space = ParkingSpace(points_m=[(398, 4), (402, 4), (402, 6), (398, 6)], bbox=(398.0, 4.0, 402.0, 6.0))

    result = spawn_deterministic_npc(residents, tw, ways, parking_spaces=[space])
    assert result is not None
    _, driver, vehicle = result
    assert vehicle.destination == (400.0, 5.0)
    # The chosen space must come out reserved (NPC-more.md section 4), so a
    # second NPC search doesn't also target it.
    assert space.reserved is True
    assert space.vehicle_id == vehicle.vehicle_id


def test_spawn_deterministic_npc_recovers_when_the_farthest_candidates_building_is_unreachable():
    """Regression: an NPC's fixed-hop BFS destination landing somewhere
    with no usable parking/building (a roundabout, a random stretch of
    road, or - here - a building whose only access crosses a curb) used
    to either retry that exact same rejected node forever ("no valid
    route found yet" logged every second, no NPC ever spawning) or fall
    back to stopping the NPC in the middle of the road (also reported).
    It must instead fall through to the next-closest candidate the same
    BFS walk reached, where a real, reachable building exists."""
    ways = _straight_chain(count=20)
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    # Nearest building to the farthest node (400.0, 0.0) - but a curb
    # sits squarely across its only access from the road.
    unreachable = Building(points_m=[(398, 4), (402, 4), (402, 8), (398, 8)], entrances=[(400.0, 4.0)], center_m=(400.0, 6.0))
    blocking_curb = Curb(points_m=[(399.0, -2.0), (399.0, 10.0)])
    # Nearest building to the *second*-farthest node (380.0, 0.0) instead,
    # with clear access - the one recovery should actually reach.
    reachable = Building(points_m=[(378, 4), (382, 4), (382, 8), (378, 8)], entrances=[(380.0, 4.0)], center_m=(380.0, 6.0))

    result = spawn_deterministic_npc(
        residents, tw, ways, buildings=[unreachable, reachable], curbs=[blocking_curb],
    )
    assert result is not None
    _, _, vehicle = result
    # (380, 4) pushed the yard clearance outward from center (380, 6).
    assert vehicle.destination == (380.0, 6.0 - 2.0 - NPC_BUILDING_YARD_CLEARANCE_M)


def test_spawn_deterministic_npc_gives_up_when_nothing_anywhere_has_a_place_to_stop():
    """With truly no parking or building anywhere the BFS walk reached,
    spawning must fail cleanly rather than ever stop an NPC on the road."""
    ways = _straight_chain(count=20)
    tw = TrafficWorld(ways)
    residents = ResidentManager()

    result = spawn_deterministic_npc(residents, tw, ways)
    assert result is None


def test_route_crosses_curbs_rejects_a_path_clipping_a_mapped_curb():
    curb = Curb(points_m=[(50.0, 3.0), (50.0, -3.0)])
    clean_path = [(0.0, 0.0), (20.0, 0.0), (40.0, 0.0)]
    crossing_path = [(0.0, 0.0), (40.0, 0.0), (60.0, 0.0)]
    assert route_crosses_curbs(clean_path, [curb]) is False
    assert route_crosses_curbs(crossing_path, [curb]) is True


def test_spawn_npc_rejects_a_route_that_clips_a_curb():
    """NPC-more.md section 7: never drive on curbs, as a hard constraint
    enforced before a vehicle is ever created - not fixed up afterwards."""
    ways = _straight_chain(count=20)
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    # A curb line planted squarely across the whole chain's driving path.
    blocking_curb = Curb(points_m=[(200.0, 10.0), (200.0, -10.0)])

    result = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (400.0, 0.0), curbs=[blocking_curb])
    assert result is None


def test_route_crosses_buildings_rejects_a_path_cutting_through_a_footprint():
    building = Building(points_m=[(40.0, -5.0), (60.0, -5.0), (60.0, 5.0), (40.0, 5.0)])
    clean_path = [(0.0, 0.0), (20.0, 0.0)]
    cutting_path = [(0.0, 0.0), (100.0, 0.0)]  # straight through the building's footprint
    assert route_crosses_buildings(clean_path, [building]) is False
    assert route_crosses_buildings(cutting_path, [building]) is True


def test_spawn_npc_rejects_a_route_that_drives_through_a_building():
    """NPC-more.md section 13: never drive through a building polygon, as
    a hard constraint enforced before a vehicle is ever created."""
    ways = _straight_chain(count=20)
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    # A building footprint squarely straddling the chain's driving path.
    blocking_building = Building(points_m=[(190.0, -10.0), (210.0, -10.0), (210.0, 10.0), (190.0, 10.0)])

    result = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (400.0, 0.0), buildings=[blocking_building])
    assert result is None


def test_spawn_npc_rejects_a_destination_only_reachable_via_a_sidewalk():
    """NPC-more.md section 12: a sidewalk/footway must never satisfy the
    off-road tolerance check just because it happens to sit near the
    destination - only a real drivable road counts. A footway planted
    right at the destination's midpoint, with the nearest real road just
    past the (widened, final-hop) tolerance, would incorrectly validate
    the route if sidewalks still counted as "a road" here."""
    drivable = Way(points_m=[(-10.0, 0.0), (0.0, 0.0)], highway="residential", half_width_m=4.5)
    footway = Way(points_m=[(40.0, -1.0), (60.0, -1.0)], highway="footway", half_width_m=1.0, is_drivable=False)
    tw = TrafficWorld([drivable, footway])
    residents = ResidentManager()

    result = spawn_npc(1, residents, tw, [drivable, footway], (-10.0, 0.0), (100.0, 0.0))
    assert result is None


def test_draw_npc_cars_renders_an_npc_vehicle_without_crashing():
    """Regression: draw_npc_cars' debug overlay (F7) crashed on any NPC
    without a `segment_idx` attribute - its steering-target-line fallback
    getattr-guarded the *condition* ("segment_idx", 0) but then indexed
    with the raw `npc.segment_idx` in the body, which npc.NPCVehicle (it
    tracks route progress on the Driver, not the vehicle) doesn't have."""
    pygame.init()
    screen = pygame.display.set_mode((400, 300))
    ways = _straight_chain()
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))
    update_npc(vehicle, driver, 1.0 / 60.0, tw, residents)  # leaves SPAWNING, sets vehicle.way

    draw_npc_cars(screen, [vehicle], vehicle.x, vehicle.y, ways=ways, show_debug=True, residents=residents)


def test_draw_npc_debug_overlay_renders_without_crashing():
    """NPC-002 section 22: stop-position/target-point debug geometry."""
    from theroadragetrip.render.hud import draw_npc_debug_overlay

    pygame.init()
    screen = pygame.display.set_mode((400, 300))
    ways = _straight_chain()
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))
    update_npc(vehicle, driver, 1.0 / 60.0, tw, residents)
    driver.decision.stop_position = (50.0, 0.0)  # exercise the stop-marker branch too

    draw_npc_debug_overlay(screen, vehicle, driver, vehicle.x, vehicle.y)


def test_draw_npc_debug_panel_shows_parking_target():
    """NPC-more.md section 21: the F7 panel must surface which parking
    space (if any) the NPC is actually headed for, not just its raw
    destination coordinates."""
    from theroadragetrip.render.hud import draw_npc_debug_panel

    pygame.init()
    screen = pygame.display.set_mode((400, 300))
    font = pygame.font.SysFont(None, 16)
    ways = _straight_chain()
    tw = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, tw, ways, (0.0, 0.0), (200.0, 0.0))

    draw_npc_debug_panel(screen, vehicle, driver, font)  # no dedicated space - must not crash

    vehicle.destination_parking_space_id = 42
    draw_npc_debug_panel(screen, vehicle, driver, font)  # with one - must not crash either


def test_draw_npc_cars_debug_fallback_still_works_without_a_travel_route():
    """The segment_idx/direction fallback this bug lived in must still
    work for whatever NPC kind actually relies on it (no travel_route,
    but a `way` + `segment_idx` to walk)."""
    pygame.init()
    screen = pygame.display.set_mode((400, 300))
    way = Way(points_m=[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5)
    parked_like_npc = SimpleNamespace(
        x=10.0, y=0.0, heading=0.0, speed=0.0, length_m=4.0, width_m=1.8, layer=0,
        color=(150, 150, 150), way=way, segment_idx=0, direction=1, lod_level=0,
        travel_route=None,
    )
    draw_npc_cars(screen, [parked_like_npc], 10.0, 0.0, ways=[way], show_debug=True)
