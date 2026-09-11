"""Tests for the physically-derived g-force measurement (see
.github/prompts/GFORCE.md and physics._update_g_force).

These drive _update_g_force directly with hand-placed positions/headings
representing exact circular arcs, rather than going through the arcade
steering model - the point is to verify the *measurement* is a correct
function of actual speed/curvature, independent of whatever heading-rate
formula the steering input happens to produce.
"""
import math

from theroadragetrip.physics import (
    Car,
    GRAVITY_MPS2,
    MIN_SPEED_FOR_LATERAL_G_MPS,
    _update_g_force,
)


def _primed_car(x=0.0, y=0.0, heading=0.0, speed=0.0) -> Car:
    """A car whose g-force velocity history is already initialized, moving
    in a straight line at `speed`/`heading` - so the first real
    _update_g_force call after this reports an actual measurement instead
    of GFORCE.md section 8's "first call reads 0"."""
    car = Car(x=x, y=y, heading=heading, speed=speed)
    car._prev_vx = speed * math.cos(heading)
    car._prev_vy = speed * math.sin(heading)
    car._g_force_initialized = True
    return car


def _drive_arc(speed: float, radius: float, dt: float, steps: int) -> Car:
    """Place a car through `steps` frames of an exact circular arc of the
    given radius at constant speed, turning left (positive radius) or
    right (negative radius), calling _update_g_force each frame."""
    omega = speed / radius
    car = _primed_car(speed=speed)
    for step in range(1, steps + 1):
        entry_x, entry_y = car.x, car.y
        theta0 = omega * (step - 1) * dt
        theta1 = omega * step * dt
        # Exact position on a circle of `radius`, center at (0, radius),
        # starting at the origin heading +x.
        car.x = radius * math.sin(theta1)
        car.y = radius * (1 - math.cos(theta1))
        car.heading = theta1
        car.speed = speed
        _update_g_force(car, entry_x, entry_y, theta0, dt)
    return car


def test_stationary_car_has_zero_g():
    car = _primed_car(speed=0.0)
    _update_g_force(car, car.x, car.y, car.heading, 0.1)
    assert car.raw_forward_g == 0.0
    assert car.raw_lateral_g == 0.0


def test_straight_constant_speed_is_approximately_zero_g():
    car = _primed_car(speed=20.0)
    entry_x, entry_y = car.x, car.y
    car.x += 20.0 * 0.1  # moved exactly speed*dt along heading 0: no accel
    _update_g_force(car, entry_x, entry_y, car.heading, 0.1)
    assert abs(car.raw_forward_g) < 1e-9
    assert abs(car.raw_lateral_g) < 1e-9


def test_straight_acceleration_is_positive_forward_g_only():
    car = _primed_car(speed=20.0)
    entry_x, entry_y = car.x, car.y
    car.speed = 24.0  # sped up during this frame
    car.x += 24.0 * 0.1
    _update_g_force(car, entry_x, entry_y, car.heading, 0.1)
    assert car.raw_forward_g > 0.0
    assert abs(car.raw_lateral_g) < 1e-9


def test_straight_braking_is_negative_forward_g():
    car = _primed_car(speed=20.0)
    entry_x, entry_y = car.x, car.y
    car.speed = 15.0
    car.x += 15.0 * 0.1
    _update_g_force(car, entry_x, entry_y, car.heading, 0.1)
    assert car.raw_forward_g < 0.0
    assert abs(car.raw_lateral_g) < 1e-9


def test_doubling_speed_at_the_same_turn_radius_quadruples_lateral_g():
    """The core physical property this whole module exists to get right:
    lateral g is centripetal (v^2/r), not linear in speed."""
    slow = _drive_arc(speed=10.0, radius=50.0, dt=0.02, steps=5)
    fast = _drive_arc(speed=20.0, radius=50.0, dt=0.02, steps=5)

    expected_slow = 10.0 ** 2 / 50.0 / GRAVITY_MPS2
    expected_fast = 20.0 ** 2 / 50.0 / GRAVITY_MPS2
    assert math.isclose(abs(slow.raw_lateral_g), expected_slow, rel_tol=0.05)
    assert math.isclose(abs(fast.raw_lateral_g), expected_fast, rel_tol=0.05)
    assert math.isclose(abs(fast.raw_lateral_g) / abs(slow.raw_lateral_g), 4.0, rel_tol=0.05)


def test_tighter_turn_at_the_same_speed_has_more_lateral_g():
    gentle = _drive_arc(speed=15.0, radius=80.0, dt=0.02, steps=5)
    tight = _drive_arc(speed=15.0, radius=20.0, dt=0.02, steps=5)
    assert abs(tight.raw_lateral_g) > abs(gentle.raw_lateral_g)


def test_left_and_right_turns_have_opposite_signed_lateral_g():
    left = _drive_arc(speed=15.0, radius=40.0, dt=0.02, steps=5)
    right = _drive_arc(speed=15.0, radius=-40.0, dt=0.02, steps=5)
    assert left.raw_lateral_g > 0.0
    assert right.raw_lateral_g < 0.0


def test_steering_while_stationary_gives_zero_lateral_g():
    """A heading change with negligible speed must not read as a real
    turn (GFORCE.md section 3)."""
    car = _primed_car(speed=0.0)
    entry_x, entry_y = car.x, car.y
    car.heading = math.radians(30.0)  # spun in place, didn't actually move
    assert abs(car.speed) < MIN_SPEED_FOR_LATERAL_G_MPS
    _update_g_force(car, entry_x, entry_y, car.heading, 0.1)
    assert car.raw_lateral_g == 0.0


def test_first_measurement_reads_zero_and_primes_history():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=25.0)
    assert car._g_force_initialized is False
    _update_g_force(car, car.x - 2.5, car.y, car.heading, 0.1)  # implies a 25 m/s entry velocity
    assert car.raw_forward_g == 0.0
    assert car.raw_lateral_g == 0.0
    assert car._g_force_initialized is True


def test_teleport_does_not_spike_g_force():
    """A respawn/relocation is a discontinuous position jump, not a real
    impact - it must not read as an extreme g-force (GFORCE.md section 9)."""
    car = _primed_car(speed=10.0)
    entry_x, entry_y = car.x, car.y
    car.x += 500.0  # a teleport, not a 0.1s drive
    car.speed = 10.0
    _update_g_force(car, entry_x, entry_y, car.heading, 0.1)
    assert car.raw_forward_g == 0.0  # discarded outright, not just capped

    # And the car keeps reporting sane values on the next real frame.
    entry_x2, entry_y2 = car.x, car.y
    car.x += 1.0  # 10 m/s * 0.1s
    _update_g_force(car, entry_x2, entry_y2, car.heading, 0.1)
    assert abs(car.raw_forward_g) < 1e-6


def test_smoothed_g_lags_but_matches_sign_of_raw():
    car = _primed_car(speed=20.0)
    entry_x, entry_y = car.x, car.y
    car.speed = 30.0
    car.x += 30.0 * 0.1
    _update_g_force(car, entry_x, entry_y, car.heading, 0.1)
    assert 0.0 < car.forward_g < car.raw_forward_g
    assert car.total_g == math.hypot(car.forward_g, car.lateral_g)
    assert car.raw_total_g == math.hypot(car.raw_forward_g, car.raw_lateral_g)
