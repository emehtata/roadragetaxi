"""Tests for OSM traffic signals parsing, light cycle behavior, and NPC traffic stopping."""
import math

from theroadragetrip.osm import (
    TrafficLight,
    SignalGroup,
    Way,
    build_ways,
    complete_traffic_light_approaches,
    build_logical_intersections,
    deduplicate_traffic_lights,
)
from theroadragetrip.physics import Car
from theroadragetrip.traffic import NPCCar, TrafficLightManager, TrafficManager


def test_traffic_light_states():
    tl = TrafficLight(x=100.0, y=100.0, cycle_time=16.0, offset=0.0)
    # 0 - 5.5s -> green
    assert tl.get_state(0.0) == "green"
    assert tl.get_state(5.0) == "green"
    # 5.5 - 7.0s -> yellow
    assert tl.get_state(6.0) == "yellow"
    # 7.0 - 14.5s -> red
    assert tl.get_state(8.0) == "red"
    assert tl.get_state(14.0) == "red"
    # 14.5 - 16.0s -> red+yellow
    assert tl.get_state(15.0) == "red+yellow"
    # wrap around to green
    assert tl.get_state(16.0) == "green"


def test_signal_group_controls_multiple_physical_lights():
    group = SignalGroup(approach_id="north", phase_id=0, offset=0.0)
    first = TrafficLight(x=0.0, y=0.0, signal_group=group)
    second = TrafficLight(x=2.0, y=0.0, signal_group=group)

    assert first.get_state(0.0) == second.get_state(0.0) == "green"
    assert group.allowed_movements == frozenset({"straight", "right"})


def test_traffic_light_manager_updates_cached_groups():
    group = SignalGroup(approach_id="north", phase_id=0, offset=0.0)
    light = TrafficLight(x=0.0, y=0.0, signal_group=group)
    approach = type("Approach", (), {"signal_group": group})()
    manager = TrafficLightManager([])
    manager._groups[group.approach_id] = group

    manager.update(6.0)

    assert manager.get_signal_state(approach, 6.0) == "yellow"
    assert group.state == "yellow"


def test_traffic_light_manager_finds_matching_logical_approach():
    way = Way(points_m=[(-100.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0)
    cross_way = Way(points_m=[(0.0, -100.0), (0.0, 100.0)], highway="primary", half_width_m=4.0)
    intersections = build_logical_intersections(
        [TrafficLight(x=0.0, y=0.0, direction_angle=0.0)], [way, cross_way]
    )
    manager = TrafficLightManager(intersections)
    npc = NPCCar(-20.0, 0.0, 0.0, 5.0, way, 0, 1, 10.0, (20, 20, 20))

    approach = manager.find_approach(npc)

    assert approach is not None
    assert approach.direction_vector[0] > 0.0


def test_traffic_light_orthogonal_phases():
    # Signal A along East-West road (offset 0.0s)
    tl_ew = TrafficLight(x=100.0, y=100.0, cycle_time=16.0, offset=0.0)
    # Signal B along North-South cross road (offset 8.0s)
    tl_ns = TrafficLight(x=100.0, y=100.0, cycle_time=16.0, offset=8.0)

    # When EW is green, NS must be red
    for t in [0.0, 2.0, 4.0, 5.0]:
        assert tl_ew.get_state(t) == "green"
        assert tl_ns.get_state(t) == "red"

    # When NS is green, EW must be red
    for t in [8.0, 10.0, 12.0, 13.0]:
        assert tl_ns.get_state(t) == "green"
        assert tl_ew.get_state(t) == "red"


def test_build_ways_traffic_signals_node():
    elements = [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.001, "lon": 25.0},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "primary"}},
        {"type": "node", "id": 99, "lat": 65.0005, "lon": 25.0, "tags": {"highway": "traffic_signals"}},
    ]

    res = build_ways(elements)
    ways, waters, buildings, sceneries, places, bounds = res
    assert len(ways) == 1
    assert hasattr(res, "traffic_lights")
    assert len(res.traffic_lights) == 1
    assert res.traffic_lights[0].id == 99


def test_deduplicate_traffic_lights_keeps_one_per_nearby_approach():
    lights = [
        TrafficLight(x=0.0, y=0.0, id=1, direction_angle=0.0),
        TrafficLight(x=8.0, y=2.0, id=2, direction_angle=0.15),
        TrafficLight(x=0.0, y=8.0, id=3, direction_angle=math.pi),
        TrafficLight(x=8.0, y=8.0, id=4, direction_angle=math.pi / 2.0),
        TrafficLight(x=100.0, y=0.0, id=5, direction_angle=0.0),
    ]

    result = deduplicate_traffic_lights(lights)

    assert {light.id for light in result} == {1, 3, 4, 5}


def test_single_signal_marker_generates_missing_intersection_approaches():
    ways = [
        Way(points_m=[(-100.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0, layer=0),
        Way(points_m=[(0.0, -100.0), (0.0, 100.0)], highway="primary", half_width_m=4.0, layer=0),
    ]
    result = complete_traffic_light_approaches(
        [TrafficLight(x=0.0, y=0.0, id=1)], ways
    )

    generated = [light for light in result if light.id != 1]
    assert len(generated) == 4
    assert {round(light.direction_angle % math.pi, 4) for light in generated} == {0.0, round(math.pi / 2, 4)}
    assert len({id(light.signal_group) for light in generated}) == 2


def test_logical_intersection_contains_approaches_and_stop_lines():
    ways = [
        Way(points_m=[(-100.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0),
        Way(points_m=[(0.0, -100.0), (0.0, 100.0)], highway="primary", half_width_m=4.0),
    ]
    lights = [TrafficLight(x=0.0, y=0.0, direction_angle=0.0)]

    intersections = build_logical_intersections(lights, ways)

    assert len(intersections) == 1
    assert len(intersections[0].approaches) == 4
    assert all(approach.stop_line[0] != approach.stop_line[1] for approach in intersections[0].approaches)


def test_build_ways_splits_single_signal_at_four_arm_junction():
    elements = [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0, "tags": {"highway": "traffic_signals"}},
        {"type": "node", "id": 2, "lat": 65.0, "lon": 24.999,},
        {"type": "node", "id": 3, "lat": 65.0, "lon": 25.001,},
        {"type": "node", "id": 4, "lat": 64.999, "lon": 25.0,},
        {"type": "node", "id": 5, "lat": 65.001, "lon": 25.0,},
        {"type": "way", "id": 10, "nodes": [2, 1], "tags": {"highway": "primary"}},
        {"type": "way", "id": 11, "nodes": [1, 3], "tags": {"highway": "primary"}},
        {"type": "way", "id": 12, "nodes": [4, 1], "tags": {"highway": "primary"}},
        {"type": "way", "id": 13, "nodes": [1, 5], "tags": {"highway": "primary"}},
    ]

    res = build_ways(elements)
    signals = res.traffic_lights

    assert len(signals) == 4
    assert len({signal.id for signal in signals}) == 4
    assert all((signal.x, signal.y) != (signals[0].x, signals[0].y) for signal in signals[1:])
    assert len({round(signal.direction_angle, 4) for signal in signals}) == 4


def test_build_ways_splits_signal_when_node_is_not_in_road_ways():
    elements = [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0, "tags": {"highway": "traffic_signals"}},
        {"type": "node", "id": 2, "lat": 65.0, "lon": 24.999},
        {"type": "node", "id": 3, "lat": 65.0, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 64.999, "lon": 25.0},
        {"type": "node", "id": 5, "lat": 65.001, "lon": 25.0},
        {"type": "way", "id": 10, "nodes": [2, 3], "tags": {"highway": "primary"}},
        {"type": "way", "id": 11, "nodes": [4, 5], "tags": {"highway": "primary"}},
    ]

    signals = build_ways(elements).traffic_lights

    assert len(signals) == 4


def test_npc_stops_at_red_traffic_light():
    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Signal Road",
        oneway=1,
    )
    # Traffic light at (30.0, 0.0) with phase offset set to red at t=0
    tl = TrafficLight(x=30.0, y=0.0, cycle_time=12.0, offset=8.0)
    assert tl.get_state(0.0) == "red"

    traffic_mgr = TrafficManager([way], target_count=1, spawn_radius_m=200.0, traffic_lights=[tl])
    npc = NPCCar(
        x=15.0,
        y=0.0,
        heading=0.0,
        speed=15.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=15.0,
        color=(200, 200, 200),
    )
    traffic_mgr.npcs = [npc]

    player = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    # Step simulation
    for _ in range(20):
        traffic_mgr.update(player, dt=0.1)

    # NPC slowed down or stopped before the red light
    assert npc.speed < 5.0
    assert npc.x < 30.0
    assert npc.state in {"braking", "waiting"}


def test_npc_continues_through_yellow_when_stopping_is_not_safe():
    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        oneway=1,
    )
    light = TrafficLight(x=30.0, y=0.0, cycle_time=16.0, offset=5.5)
    traffic_mgr = TrafficManager([way], target_count=0, traffic_lights=[light])
    npc = NPCCar(26.0, 0.0, 0.0, 15.0, way, 0, 1, 15.0, (200, 200, 200))
    traffic_mgr.npcs = [npc]

    traffic_mgr.update(Car(x=0.0, y=0.0, heading=0.0, speed=0.0), dt=0.1)

    assert npc.x > 26.0
    assert npc.state == "driving"


def test_player_red_light_violation_penalty():
    from theroadragetrip.taxi import TaxiManager

    # Traffic light at (50, 0) with red state at sim_time=0.0
    tl = TrafficLight(x=50.0, y=0.0, cycle_time=16.0, offset=8.0, id=101, direction_angle=0.0)
    assert tl.get_state(0.0) == "red"

    taxi_mgr = TaxiManager(ways=[])
    taxi_mgr.total_score = 500

    # 1. Car stopped/slow at red light -> no violation
    car = Car(x=50.0, y=0.0, heading=0.0, speed=0.5)
    taxi_mgr.check_red_light_violation(car, [tl], sim_time=0.0, penalty=100)
    assert taxi_mgr.total_score == 500

    # 2. Car drives through red light at speed -> penalty applied
    car.speed = 10.0  # 36 km/h
    taxi_mgr.check_red_light_violation(car, [tl], sim_time=0.1, penalty=100)
    assert taxi_mgr.total_score == 400
    assert "Punaisen valon rikkomus" in taxi_mgr.notification_msg

    # 3. Cooldown prevents multi-triggering for the same signal passing
    taxi_mgr.check_red_light_violation(car, [tl], sim_time=0.2, penalty=100)
    assert taxi_mgr.total_score == 400

    # 4. Passing on yellow light is not a violation
    tl_yellow = TrafficLight(x=50.0, y=0.0, cycle_time=16.0, offset=0.0, id=102, direction_angle=0.0)
    assert tl_yellow.get_state(6.0) == "yellow"
    car2 = Car(x=50.0, y=0.0, heading=0.0, speed=10.0)
    taxi_mgr.check_red_light_violation(car2, [tl_yellow], sim_time=6.0, penalty=100)
    assert taxi_mgr.total_score == 400  # Score unchanged


def test_turning_at_intersection_does_not_trigger_red_light_violation():
    from theroadragetrip.taxi import TaxiManager

    tl = TrafficLight(x=10.0, y=0.0, cycle_time=16.0, offset=8.0, id=103)
    taxi_mgr = TaxiManager(ways=[])
    car = Car(x=0.0, y=0.0, heading=0.0, speed=8.0)

    taxi_mgr.check_red_light_violation(car, [tl], sim_time=0.0)
    car.x, car.y, car.heading = 10.0, 1.0, 1.5708
    taxi_mgr.check_red_light_violation(car, [tl], sim_time=0.1)

    assert taxi_mgr.total_score == 0


def test_ninety_degree_turn_at_red_light_does_not_trigger_violation():
    from theroadragetrip.taxi import TaxiManager

    tl = TrafficLight(x=10.0, y=0.0, cycle_time=16.0, offset=8.0, id=104, direction_angle=0.0)
    taxi_mgr = TaxiManager(ways=[])
    car = Car(x=0.0, y=0.0, heading=0.0, speed=8.0)

    taxi_mgr.check_red_light_violation(car, [tl], sim_time=0.0)
    car.x, car.y, car.heading = 10.0, 1.0, math.pi / 2
    taxi_mgr.check_red_light_violation(car, [tl], sim_time=0.1)

    assert taxi_mgr.total_score == 0


def test_red_light_assist_slows_before_red_signal():
    from theroadragetrip.taxi import TaxiManager

    tl = TrafficLight(x=30.0, y=0.0, cycle_time=16.0, offset=8.0, direction_angle=0.0)
    car = Car(x=0.0, y=0.0, heading=0.0, speed=10.0)
    taxi_mgr = TaxiManager(ways=[])

    target = taxi_mgr.get_red_light_assist_speed_limit(car, [tl], sim_time=0.0)

    assert target is not None
    assert 14.0 < target < 15.0


def test_red_light_assist_uses_only_first_signal_ahead():
    from theroadragetrip.taxi import TaxiManager

    green_light = TrafficLight(x=10.0, y=0.0, cycle_time=16.0, offset=0.0, direction_angle=0.0)
    red_light = TrafficLight(x=30.0, y=0.0, cycle_time=16.0, offset=8.0, direction_angle=0.0)
    taxi_mgr = TaxiManager(ways=[])
    car = Car(x=0.0, y=0.0, heading=0.0, speed=10.0)

    assert taxi_mgr.get_red_light_assist_speed_limit(car, [red_light, green_light], sim_time=0.0) is None


def test_seeing_red_light_builds_rage_meter_rate():
    from theroadragetrip.taxi import TaxiManager

    red_light = TrafficLight(x=30.0, y=0.0, cycle_time=16.0, offset=8.0, direction_angle=0.0)
    taxi_mgr = TaxiManager(ways=[])
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)

    assert taxi_mgr.sees_red_light(car, [red_light], sim_time=0.0) is True
    assert taxi_mgr.sees_red_light(car, [red_light], sim_time=8.0) is False
    assert taxi_mgr.sees_red_light(car, [red_light], sim_time=0.0, detection_distance_m=20.0) is False

