import sys
from types import SimpleNamespace


from theroadragetrip.simulation import RAGE_DISTANCE_TO_FULL_M, RAGE_GAIN_SCALE, _rage_from_speeding




def test_speeding_builds_rage():
    limit_mps = 50.0 / 3.6  # 50 km/h
    rage = _rage_from_speeding(0.0, speed_mps=70.0 / 3.6, road_limit_mps=limit_mps, driven_distance_m=100.0)
    assert rage == 100.0 / RAGE_DISTANCE_TO_FULL_M * RAGE_GAIN_SCALE


def test_driving_under_the_limit_reduces_rage():
    limit_mps = 50.0 / 3.6
    rage = _rage_from_speeding(0.5, speed_mps=30.0 / 3.6, road_limit_mps=limit_mps, driven_distance_m=100.0)
    assert rage < 0.5


def test_rage_from_speeding_is_clamped_to_0_1():
    limit_mps = 50.0 / 3.6
    assert _rage_from_speeding(0.99, speed_mps=90.0 / 3.6, road_limit_mps=limit_mps, driven_distance_m=1000.0) == 1.0
    assert _rage_from_speeding(0.01, speed_mps=10.0 / 3.6, road_limit_mps=limit_mps, driven_distance_m=1000.0) == 0.0


def test_rage_unaffected_without_a_known_speed_limit():
    assert _rage_from_speeding(0.4, speed_mps=100.0, road_limit_mps=None, driven_distance_m=100.0) == 0.4
















