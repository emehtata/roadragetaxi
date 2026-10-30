

def test_a_turning_car_pivots_on_its_rear_axle_not_its_middle():
    """The rear wheels follow the path; the front swings into the turn. The
    rear axle (0.3 of the length behind the centre) never slides sideways."""
    import math
    from theroadragetrip.physics import Car, REAR_AXLE_SHARE, update_car_physics
    car = Car(x=0.0, y=0.0, heading=0.0, speed=6.0)
    behind = car.length_m * REAR_AXLE_SHARE
    worst_slip = 0.0
    for _ in range(60):
        rear_before = (car.x - math.cos(car.heading) * behind, car.y - math.sin(car.heading) * behind)
        heading_before = car.heading
        update_car_physics(car, throttle=0.3, brake=0.0, steer_left=1.0, steer_right=0.0, dt=1 / 30, block_offroad=False)
        rear_after = (car.x - math.cos(car.heading) * behind, car.y - math.sin(car.heading) * behind)
        move = (rear_after[0] - rear_before[0], rear_after[1] - rear_before[1])
        mid = heading_before + (car.heading - heading_before) / 2.0
        sideways = -move[0] * math.sin(mid) + move[1] * math.cos(mid)  # across the axle's own direction
        worst_slip = max(worst_slip, abs(sideways))
    assert car.heading > 0.5  # it did turn left
    assert worst_slip < 0.01  # the rear axle rolled, it did not slide (a centre pivot slid it ~0.1 m a frame)


def test_full_lock_at_a_crawl_turns_no_tighter_than_the_turning_circle():
    """Reviewed: at 0.1 m/s full lock spun the body about its rear axle, the
    nose sweeping sideways at metres a second. The steering lock caps the turn."""
    from theroadragetrip.physics import Car, min_turn_radius, update_car_physics
    for length in (4.0, 11.0):
        car = Car(x=0.0, y=0.0, heading=0.0, speed=0.3, length_m=length)
        travelled = 0.0
        for _ in range(30):
            x, y = car.x, car.y
            update_car_physics(car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=1 / 30, block_offroad=False)
            travelled += abs(car.speed) / 30
        assert abs(car.heading) <= travelled / min_turn_radius(car) + 1e-6, length
