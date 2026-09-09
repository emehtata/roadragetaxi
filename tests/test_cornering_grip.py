import math

from theroadragetrip.osm import Way
from theroadragetrip.physics import (
    Car,
    GRAVITY_MPS2,
    PHYSICS_MODE_GRIP_MULTIPLIER,
    SURFACE_MAX_GRIP_G,
    update_car_physics,
)


def _fast_car(speed=30.0):
    car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
    # Prime the g-force velocity history (see physics._update_g_force): the
    # very first update_car_physics call on a car always reports ~0 g
    # (GFORCE.md section 8 - no previous velocity to diff against yet), so
    # a throwaway warm-up call is needed before a single real call's g
    # reading means anything. Reset position/speed/velocity-history
    # afterward so the warm-up itself has no side effect on the test.
    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=0.0, steer_right=0.0, dt=0.1)
    car.x, car.y, car.speed = 0.0, 0.0, speed
    car._prev_vx, car._prev_vy = speed * math.cos(car.heading), speed * math.sin(car.heading)
    return car


def test_forward_g_reflects_acceleration_and_braking():
    accelerating = _fast_car(speed=10.0)
    update_car_physics(accelerating, throttle=1.0, brake=0.0, steer_left=0.0, steer_right=0.0, dt=0.1)
    assert accelerating.forward_g > 0.0

    braking = _fast_car(speed=10.0)
    update_car_physics(braking, throttle=0.0, brake=1.0, steer_left=0.0, steer_right=0.0, dt=0.1)
    assert braking.forward_g < 0.0


def test_gentle_turn_at_low_speed_does_not_slide():
    car = _fast_car(speed=5.0)
    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1)
    assert car.is_sliding is False
    assert car.drift_angle == 0.0


def test_hard_turn_at_high_speed_exceeds_grip_and_softens_steering():
    """Regression target: sharp steering input at high speed used to turn
    the car exactly as commanded regardless of speed - no grip limit
    existed at all. Once the demanded lateral g exceeds the surface's grip,
    the actual heading rate applied must be capped below what was asked."""
    car = _fast_car(speed=30.0)
    heading_before = car.heading
    update_car_physics(
        car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1,
        physics_mode="arcade",
    )
    applied_heading_rate = (car.heading - heading_before) / 0.1
    uncapped_heading_rate = 2.6 / (1.0 + 30.0 * 0.10)  # STEER_RATE / (1 + |speed| * STEER_SPEED_FACTOR)

    assert car.is_sliding is True
    assert abs(applied_heading_rate) < abs(uncapped_heading_rate)
    # Applied lateral g should sit right at (not past) the arcade grip ceiling.
    arcade_max_grip_g = SURFACE_MAX_GRIP_G["dry_asphalt"] * PHYSICS_MODE_GRIP_MULTIPLIER["arcade"]
    assert abs(car.raw_lateral_g) <= arcade_max_grip_g + 1e-6


def test_simulation_mode_has_a_lower_grip_ceiling_than_arcade():
    """Checks the configured ceiling (car.max_grip_g) directly rather than
    inferring it from measured lateral_g: now that lateral_g is measured
    from the car's actual velocity-vector change (GFORCE.md), a hard-
    oversteering "simulation"-mode car genuinely sliding (drift_angle
    swinging the tail out, on top of the understeer-clamped heading rate)
    can measure a *higher* instantaneous lateral g than arcade's calmer,
    drift-free understeer - that's correct physical behaviour, not a
    lower ceiling, so it's no longer the right proxy for this check."""
    def max_grip_g_for(mode):
        car = _fast_car(speed=30.0)
        update_car_physics(
            car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1,
            physics_mode=mode,
        )
        return car.max_grip_g

    assert max_grip_g_for("simulation") < max_grip_g_for("arcade")


def test_simulation_mode_builds_a_drift_angle_that_recovers():
    car = _fast_car(speed=30.0)
    for _ in range(10):
        update_car_physics(
            car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1,
            physics_mode="simulation",
        )
    assert car.drift_angle != 0.0, "hard sustained oversteer should build a drift angle"

    drift_while_sliding = abs(car.drift_angle)
    # Straighten out: drift should decay once the demanded turn is back
    # within grip.
    for _ in range(20):
        update_car_physics(
            car, throttle=0.0, brake=0.0, steer_left=0.0, steer_right=0.0, dt=0.1,
            physics_mode="simulation",
        )
    assert abs(car.drift_angle) < drift_while_sliding


def test_arcade_mode_never_builds_a_drift_angle():
    car = _fast_car(speed=30.0)
    for _ in range(10):
        update_car_physics(
            car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1,
            physics_mode="arcade",
        )
    assert car.drift_angle == 0.0


def test_ice_road_has_a_much_lower_grip_limit():
    ice_road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=6.0, is_ice_road=True)
    dry_road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=6.0)

    # A turn gentle enough to keep grip on dry asphalt...
    speed = 20.0
    dry_car = _fast_car(speed)
    update_car_physics(
        dry_car, throttle=0.0, brake=0.0, steer_left=0.5, steer_right=0.0, dt=0.1,
        current_way=dry_road, physics_mode="arcade",
    )
    assert dry_car.is_sliding is False

    # ...should still break loose on the same road covered in ice.
    ice_car = _fast_car(speed)
    update_car_physics(
        ice_car, throttle=0.0, brake=0.0, steer_left=0.5, steer_right=0.0, dt=0.1,
        current_way=ice_road, physics_mode="arcade",
    )
    assert ice_car.is_sliding is True
