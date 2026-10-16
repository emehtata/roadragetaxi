"""Trajectory acceptance cases for docs/finnish-npc-traffic-law.md.

These cover named scenarios, not general Finnish-law certification.
"""
import math
import random

import pytest

from theroadragetrip.npc import NPCState, spawn_npc, update_npc
from theroadragetrip.osm import StopSign, YieldSign, TrafficLight, Way
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld
from theroadragetrip.traffic_rules import TrafficAction, decide_traffic_action


@pytest.fixture(autouse=True)
def fixed_seed():
    previous = random.getstate()
    random.seed(20261017)
    yield
    random.setstate(previous)


@pytest.mark.parametrize("actual,limit,expected", [(0, 13.9, TrafficAction.SLOW),
                                                  (2, 13.9, TrafficAction.SLOW),
                                                  (20, 5, TrafficAction.PROCEED)])
def test_yellow_feasibility_uses_actual_speed_not_the_limit(actual, limit, expected):
    signal = TrafficLight(10, 0, direction_angle=0)
    signal.get_state = lambda now: "yellow"
    decision = decide_traffic_action(0, 0, 0, [signal], 0, speed_limit_mps=limit, actual_speed_mps=actual)
    assert decision.action == expected
    assert decision.target_speed_mps <= actual


def test_yellow_stop_latch_is_specific_to_the_signal_and_clears_on_green():
    signal = TrafficLight(10, 0, direction_angle=0)
    signal.get_state = lambda now: "yellow"
    first = decide_traffic_action(0, 0, 0, [signal], 0, actual_speed_mps=2)
    assert first.action == TrafficAction.SLOW
    # Speed perturbation near the stopping-distance boundary must not cancel braking.
    stopped = decide_traffic_action(5, 0, 0, [signal], 0, actual_speed_mps=3, yellow_stop_light=first.light)
    assert stopped.action == TrafficAction.SLOW
    other = TrafficLight(10, 0, direction_angle=0)
    other.get_state = lambda now: "yellow"
    assert decide_traffic_action(5, 0, 0, [other], 0, actual_speed_mps=3, yellow_stop_light=first.light).action == TrafficAction.PROCEED
    signal.get_state = lambda now: "green"
    assert decide_traffic_action(5, 0, 0, [signal], 0, actual_speed_mps=0, yellow_stop_light=first.light).action == TrafficAction.PROCEED


@pytest.mark.parametrize("heading", [0.0, math.pi / 2, math.pi, -math.pi / 2])
@pytest.mark.parametrize("vehicle_type", ["car", "bus"])
def test_slow_vehicle_stops_on_yellow_waits_on_red_and_resumes_on_green(heading, vehicle_type):
    fx, fy = math.cos(heading), math.sin(heading)
    ways = [Way([(i * 20 * fx, i * 20 * fy), ((i + 1) * 20 * fx, (i + 1) * 20 * fy)],
                "residential", 4.5) for i in range(20)]
    world, residents = TrafficWorld(ways), ResidentManager()
    result = spawn_npc(1, residents, world, ways, (40 * fx, 40 * fy), (360 * fx, 360 * fy), vehicle_type=vehicle_type)
    assert result is not None
    _, driver, vehicle = result
    vehicle.car.speed = 2.0
    signal = TrafficLight(vehicle.x + 10 * fx, vehicle.y + 10 * fy, direction_angle=heading)
    phase = ["yellow"]
    signal.get_state = lambda now: phase[0]
    world.traffic_lights = [signal]

    for state, ticks in [("yellow", 90), ("red", 300)]:
        phase[0] = state
        for _ in range(ticks):
            update_npc(vehicle, driver, 1 / 30, world, residents)
            nose_to_signal = (signal.x - vehicle.x) * fx + (signal.y - vehicle.y) * fy - vehicle.length_m / 2
            assert nose_to_signal >= 0, "whole vehicle must remain behind the signal"
            assert driver.recovery_stage == "NORMAL", "a legal light wait is not stuck recovery"
        if state == "yellow":
            assert vehicle.speed <= 2.1, "do not accelerate to beat yellow"
        else:
            assert abs(vehicle.speed) < .1
            assert vehicle.state == NPCState.WAITING

    stopped = (vehicle.x, vehicle.y)
    phase[0] = "green"
    for _ in range(120):
        update_npc(vehicle, driver, 1 / 30, world, residents)
    assert (vehicle.x - stopped[0]) * fx + (vehicle.y - stopped[1]) * fy > 5
    assert vehicle.speed > 1


@pytest.mark.parametrize("heading", [0.0, math.pi / 2, math.pi, -math.pi / 2])
@pytest.mark.parametrize("vehicle_type", ["car", "bus"])
def test_stop_sign_requires_full_stop_without_traffic_then_releases(heading, vehicle_type):
    fx, fy = math.cos(heading), math.sin(heading)
    ways = [Way([(i * 20 * fx, i * 20 * fy), ((i + 1) * 20 * fx, (i + 1) * 20 * fy)],
                "residential", 4.5) for i in range(20)]
    world, residents = TrafficWorld(ways), ResidentManager()
    result = spawn_npc(1, residents, world, ways, (40 * fx, 40 * fy), (360 * fx, 360 * fy), vehicle_type=vehicle_type)
    assert result is not None
    _, driver, vehicle = result
    vehicle.car.speed = 6.0
    sign = StopSign(vehicle.x + 40 * fx + 3 * fy, vehicle.y + 40 * fy - 3 * fx, id=12, direction_angle=heading)
    world.sync_map_data(ways, stop_signs=[sign])
    stopped = False
    for _ in range(600):
        update_npc(vehicle, driver, 1 / 30, world, residents)
        nose_to_sign = (sign.x - vehicle.x) * fx + (sign.y - vehicle.y) * fy - vehicle.length_m / 2
        if driver.stop_sign_satisfied and not stopped:
            assert abs(vehicle.speed) < .05 and nose_to_sign >= 0
            stopped = True
        assert stopped or nose_to_sign >= 0, "must stop before crossing the sign position"
        assert driver.recovery_stage == "NORMAL"
    assert stopped
    assert (vehicle.x - sign.x) * fx + (vehicle.y - sign.y) * fy > 10


@pytest.mark.parametrize("kind", ["opposite", "upper", "yield", "green"])
def test_irrelevant_stop_or_green_signal_does_not_force_a_stop(kind):
    ways = [Way([(i * 20, 0), ((i + 1) * 20, 0)], "residential", 4.5) for i in range(20)]
    world, residents = TrafficWorld(ways), ResidentManager()
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (40, 0), (360, 0))
    vehicle.car.speed = 6
    sign_type = YieldSign if kind == "yield" else StopSign
    sign = sign_type(vehicle.x + 30, vehicle.y - 3, direction_angle=math.pi if kind == "opposite" else 0,
                     layer=1 if kind == "upper" else 0)
    world.sync_map_data(ways, stop_signs=[] if kind == "yield" else [sign], yield_signs=[sign] if kind == "yield" else [])
    if kind == "green":
        light = TrafficLight(sign.x, vehicle.y, direction_angle=0)
        light.get_state = lambda now: "green"
        world.traffic_lights = [light]
    for _ in range(180):
        update_npc(vehicle, driver, 1 / 30, world, residents)
        assert vehicle.speed > 5
    assert vehicle.x > sign.x
