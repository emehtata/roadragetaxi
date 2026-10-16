"""Tests for the tire-slip-driven skidmark model (.github/prompts/SKIDMARK.md).

Covers physics.skidmark_should_mark/skidmark_intensity (the "source of
truth" the spec requires - real tire slip, not brake input) and the
render side's intensity-based darkening and teleport-safety concerns are
covered by test_main_loop.py's broader smoke tests plus the dedicated
checks below.
"""

from theroadragetrip.physics import (
    SKIDMARK_FULL_SLIP_THRESHOLD,
    SKIDMARK_SLIP_THRESHOLD,
    SLIDE_ENTER_THRESHOLD,
    skidmark_intensity,
    skidmark_should_mark,
)


def test_no_mark_below_the_slip_threshold():
    assert skidmark_should_mark(0.0) is False
    assert skidmark_should_mark(SKIDMARK_SLIP_THRESHOLD - 0.01) is False
    assert skidmark_intensity(0.0) == 0.0
    assert skidmark_intensity(SKIDMARK_SLIP_THRESHOLD) == 0.0


def test_mark_appears_before_the_car_counts_as_fully_sliding():
    """A tire can be visibly slipping before is_sliding's hysteresis
    would call the whole car "sliding" (SKIDMARK.md section 22.2)."""
    assert SKIDMARK_SLIP_THRESHOLD < SLIDE_ENTER_THRESHOLD
    midpoint = (SKIDMARK_SLIP_THRESHOLD + SLIDE_ENTER_THRESHOLD) / 2.0
    assert skidmark_should_mark(midpoint) is True


def test_intensity_rises_continuously_not_as_a_binary_switch():
    low = skidmark_intensity(SKIDMARK_SLIP_THRESHOLD + 0.01)
    mid = skidmark_intensity((SKIDMARK_SLIP_THRESHOLD + SKIDMARK_FULL_SLIP_THRESHOLD) / 2.0)
    high = skidmark_intensity(SKIDMARK_FULL_SLIP_THRESHOLD)
    assert 0.0 < low < mid < high == 1.0


def test_intensity_never_exceeds_one_past_full_slip():
    assert skidmark_intensity(1.0) == 1.0


def test_wet_hard_surface_does_not_receive_skidmarks():
    assert skidmark_should_mark(1.0, wetness=0.01, hard_surface=True) is False
    assert skidmark_should_mark(1.0, wetness=1.0, hard_surface=True) is False
    assert skidmark_should_mark(1.0, wetness=0.0, hard_surface=True) is True


def test_wet_soft_ground_can_still_receive_displaced_dirt_tracks():
    assert skidmark_should_mark(1.0, wetness=1.0, hard_surface=False) is True


def test_soft_surface_tracks_always_include_all_four_wheels():
    from theroadragetrip.physics import tire_tracks_include_front_wheels

    assert tire_tracks_include_front_wheels(True, False, False) is True
    assert tire_tracks_include_front_wheels(True, True, False) is True
    assert tire_tracks_include_front_wheels(False, True, False) is False
    assert tire_tracks_include_front_wheels(False, True, True) is True








def test_coasting_corners_do_not_leave_marks_at_ordinary_speed():
    """Binary full-lock steering saturates the grip clamp on most ordinary
    turns; an unpowered corner at ordinary speed must not draw marks (the
    driven case is covered by tests/test_rwd_oversteer.py)."""
    from theroadragetrip.physics import Car, skidmark_should_mark, update_car_physics

    for mode in ("arcade", "simulation"):
        for speed in (5.0, 8.0):
            car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
            marks = 0
            for _ in range(60):
                update_car_physics(car, 0.0, 0.0, 1.0, 0.0, 1 / 60, ways=[], block_offroad=False, physics_mode=mode)
                marks += skidmark_should_mark(car.skid_amount)
            assert marks == 0






def test_excessive_braking_from_high_speed_locks_the_front_tyres_too():
    from theroadragetrip.physics import Car, update_car_physics

    def brake(speed, mode="simulation"):
        car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
        locked = False
        for _ in range(20):
            update_car_physics(car, 0.0, 1.0, 0.0, 0.0, 1 / 60, ways=[], block_offroad=False, physics_mode=mode)
            locked = locked or car.front_lockup
        return locked

    for mode in ("arcade", "simulation"):
        assert brake(30.0, mode)       # ~108 km/h panic stop
        assert not brake(8.0, mode)    # low speed: rears only


