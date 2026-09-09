import math

from theroadragetrip.osm import Way
from theroadragetrip.physics import (
    Car,
    GRAVITY_MPS2,
    GRIP_LIMIT_G,
    update_car_physics,
)


def _fast_car(speed=30.0):
    return Car(x=0.0, y=0.0, heading=0.0, speed=speed)


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
    assert abs(car.lateral_g) <= GRIP_LIMIT_G["arcade"] + 1e-6


def test_simulation_mode_has_a_lower_grip_ceiling_than_arcade():
    def lateral_g_at_limit(mode):
        car = _fast_car(speed=30.0)
        update_car_physics(
            car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.1,
            physics_mode=mode,
        )
        return abs(car.lateral_g)

    assert lateral_g_at_limit("simulation") < lateral_g_at_limit("arcade")


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
    dry_car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
    update_car_physics(
        dry_car, throttle=0.0, brake=0.0, steer_left=0.5, steer_right=0.0, dt=0.1,
        current_way=dry_road, physics_mode="arcade",
    )
    assert dry_car.is_sliding is False

    # ...should still break loose on the same road covered in ice.
    ice_car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
    update_car_physics(
        ice_car, throttle=0.0, brake=0.0, steer_left=0.5, steer_right=0.0, dt=0.1,
        current_way=ice_road, physics_mode="arcade",
    )
    assert ice_car.is_sliding is True
