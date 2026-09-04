from types import SimpleNamespace

from theroadragetrip.osm import Way
from theroadragetrip.osm import TrafficLight
from theroadragetrip.traffic import NPCCar, TrafficManager
from utils.autoplay_audit import (
    _has_lane_exception,
    _lane_offset_from_way,
    _red_light_violation,
    _turning_loop_violation,
    run_audit,
)


def test_headless_autoplay_traffic_audit():
    failures = run_audit(steps=600, dt=0.1, seed=7)

    assert failures == [], "\n".join(
        f"step={failure.step} rule={failure.rule} npc={failure.npc_id}: {failure.detail}"
        for failure in failures
    )


def test_headless_autoplay_regression_seeds():
    for seed in (1, 42):
        failures = run_audit(steps=1200, dt=0.1, seed=seed)
        assert failures == [], f"seed={seed}: " + "\n".join(
            f"step={failure.step} rule={failure.rule} npc={failure.npc_id}: {failure.detail}"
            for failure in failures
        )


def _lane_npc(y=-2.0, **overrides):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.0)
    values = {
        "way": way,
        "segment_idx": 0,
        "direction": 1,
        "x": 20.0,
        "y": y,
        "lane_offset": 2.0,
        "target_lane_offset": 2.0,
        "overtaking": False,
        "state": "driving",
        "debug_waiting_for": "",
        "blocked_timer": 0.0,
        "escape_timer": 0.0,
        "crashed_timer": 0.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_lane_audit_uses_actual_right_lane_position():
    npc = _lane_npc()

    assert _lane_offset_from_way(npc) == 2.0
    assert _has_lane_exception(npc) is False


def test_lane_audit_allows_only_explicit_lane_deviation_reasons():
    wrong_lane = _lane_npc(y=2.0)
    overtaking = _lane_npc(y=2.0, overtaking=True)
    collision_recovery = _lane_npc(y=2.0, escape_timer=1.0)
    separation_recovery = _lane_npc(y=2.0, crashed_timer=1.0)

    assert _has_lane_exception(wrong_lane) is False
    assert _has_lane_exception(overtaking) is True
    assert _has_lane_exception(collision_recovery) is True
    assert _has_lane_exception(separation_recovery) is True


def test_red_light_audit_reports_forward_crossing():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0, oneway=1)
    light = TrafficLight(x=10.0, y=0.0, cycle_time=16.0, offset=8.0, direction_angle=0.0)
    manager = TrafficManager([way], target_count=0, traffic_lights=[light])
    npc = NPCCar(12.0, 0.0, 0.0, 10.0, way, 0, 1, 10.0, (20, 20, 20))
    manager.npcs = [npc]

    assert _red_light_violation(manager, npc, (8.0, 0.0)) is not None


def test_red_light_audit_ignores_stopped_car():
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0, oneway=1)
    light = TrafficLight(x=10.0, y=0.0, cycle_time=16.0, offset=8.0, direction_angle=0.0)
    manager = TrafficManager([way], target_count=0, traffic_lights=[light])
    npc = NPCCar(12.0, 0.0, 0.0, 0.0, way, 0, 1, 10.0, (20, 20, 20))
    manager.npcs = [npc]

    assert _red_light_violation(manager, npc, (8.0, 0.0)) is None


def test_turning_audit_detects_stuck_turn_signal():
    npc = _lane_npc(state="turning", turn_signal="left", turn_signal_elapsed=4.0, next_route=None)

    assert _turning_loop_violation(npc) == "turn_signal='left' elapsed=4.0s"