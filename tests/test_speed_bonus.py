from theroadragetrip.taxi import speed_bonus_points


def test_speed_bonus_hits_requested_reference_points():
    assert speed_bonus_points(10.0) == 100
    assert speed_bonus_points(50.0) == 1000
    assert speed_bonus_points(100.0) == 10000


def test_speed_bonus_is_nonlinear_and_zero_at_standstill():
    assert speed_bonus_points(0.0) == 0
    assert speed_bonus_points(25.0) < 500
    assert speed_bonus_points(75.0) > 1000