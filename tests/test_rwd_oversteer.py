"""The taxi is rear-wheel driven: the throttle spends the rear axle's
lateral grip, so heavy throttle in a corner steps the rear out
(oversteer) instead of just pushing wide."""
import math

from theroadragetrip.physics import Car, skidmark_should_mark, update_car_physics


def corner(speed, throttle, mode="simulation", frames=60, steer_left=1.0, steer_right=0.0, car=None):
    car = car or Car(x=0.0, y=0.0, heading=0.0, speed=speed)
    max_drift = 0.0
    marks = 0
    for _ in range(frames):
        update_car_physics(car, throttle, 0.0, steer_left, steer_right, 1 / 60, ways=[], block_offroad=False, physics_mode=mode)
        max_drift = max(max_drift, abs(car.drift_angle))
        marks += skidmark_should_mark(car.skid_amount)
    return car, max_drift, marks


def test_heavy_throttle_in_a_corner_oversteers_but_coasting_does_not():
    _, powered_drift, powered_marks = corner(16.0, 1.0)
    _, coasting_drift, coasting_marks = corner(16.0, 0.0)
    assert math.degrees(powered_drift) > 10.0
    assert powered_marks > 0
    assert math.degrees(coasting_drift) < 1.0
    assert coasting_marks == 0


def test_oversteer_points_the_nose_into_the_corner_of_the_travel_direction():
    car, _, _ = corner(16.0, 1.0)  # steering left
    # Velocity heading is outward (right) of where the nose points.
    assert car.slip_angle < -math.radians(5.0)
    car_r, _, _ = corner(16.0, 1.0, steer_left=0.0, steer_right=1.0)
    assert car_r.slip_angle > math.radians(5.0)


def test_lifting_off_or_steering_straight_recovers_the_slide():
    car, drift, _ = corner(16.0, 1.0, frames=40)
    assert drift > math.radians(10.0)
    corner(0.0, 0.0, frames=30, steer_left=0.0, steer_right=0.0, car=car)
    assert abs(car.drift_angle) < math.radians(2.0)


def test_counter_steering_does_not_deepen_the_slide():
    car, drift, _ = corner(16.0, 1.0, frames=40)
    before = abs(car.drift_angle)
    corner(0.0, 1.0, frames=10, steer_left=0.0, steer_right=1.0, car=car)
    assert abs(car.drift_angle) < before


def test_arcade_mode_stays_far_more_forgiving_than_simulation():
    _, arcade_drift, _ = corner(16.0, 1.0, mode="arcade")
    _, sim_drift, _ = corner(16.0, 1.0, mode="simulation")
    assert arcade_drift < sim_drift / 3.0


def test_slow_full_throttle_crawl_does_not_slide():
    # Steering lock, not the model's very tight binary steering, limits the
    # rear axle's lateral demand at parking-lot speed.
    _, drift, marks = corner(2.0, 1.0, frames=10)
    assert math.degrees(drift) < 1.0 and marks == 0
