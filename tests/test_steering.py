from theroadragetrip import Car


def heading_delta_for_inputs(start_heading: float, left: float, right: float, speed: float, dt: float):
    # replicate steering update logic from main loop
    steer = (left - right)
    STEER_RATE = 2.6
    STEER_SPEED_FACTOR = 0.10
    steer_effective = STEER_RATE / (1.0 + abs(speed) * STEER_SPEED_FACTOR)
    new_heading = start_heading + steer * steer_effective * dt * (1.0 if speed >= 0 else -1.0)
    return new_heading - start_heading


def test_left_turn_increases_heading():
    d = heading_delta_for_inputs(0.0, left=1.0, right=0.0, speed=5.0, dt=0.1)
    assert d > 0, "Left input should increase heading (turn left / counter-clockwise)"


def test_right_turn_decreases_heading():
    d = heading_delta_for_inputs(0.0, left=0.0, right=1.0, speed=5.0, dt=0.1)
    assert d < 0, "Right input should decrease heading (turn right / clockwise)"


def test_reverse_steering_flips_sign():
    # When going in reverse (negative speed), turning left should decrease heading (because steering reverses)
    d = heading_delta_for_inputs(0.0, left=1.0, right=0.0, speed=-5.0, dt=0.1)
    assert d < 0, "In reverse, left input should decrease heading"
