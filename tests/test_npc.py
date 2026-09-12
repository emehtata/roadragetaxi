"""Tests for NPC-001: the first autonomous NPC car (theroadragetrip.npc)."""
import math
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from theroadragetrip.render.vehicles import draw_npc_cars
from theroadragetrip.npc import (
    Driver,
    NPCState,
    NPCVehicle,
    _lane_offset_point,
    build_driving_path,
    has_active_driver,
    spawn_deterministic_npc,
    spawn_npc,
    update_npc,
)
from theroadragetrip.osm import TrafficLight, Way
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
    (see _bfs_destination) is meant to handle reliably."""
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
    result = spawn_deterministic_npc(residents, tw, ways)
    assert result is not None
    _, driver, vehicle = result
    assert len(driver.path) >= 3


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
