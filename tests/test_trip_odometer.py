from theroadragetrip.physics import Car, reset_trip, update_car_physics


def test_car_trip_and_odometer_accumulation():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=10.0)
    assert car.trip_m == 0.0
    assert car.odometer_m == 0.0

    # Simulate driving forward for 2.0 seconds at 10.0 m/s -> 20.0 meters
    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=0.0, steer_right=0.0, dt=1.0)
    assert car.trip_m > 0.0
    assert car.odometer_m == car.trip_m

    # Reset trip
    initial_odo = car.odometer_m
    reset_trip(car)
    assert car.trip_m == 0.0
    assert car.odometer_m == initial_odo

    # Drive more
    update_car_physics(car, throttle=1.0, brake=0.0, steer_left=0.0, steer_right=0.0, dt=1.0)
    assert car.trip_m > 0.0
    assert car.odometer_m > initial_odo


def test_stationary_car_cannot_steer_in_place():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)

    # Attempt to steer while vehicle is stopped
    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.5)
    assert car.heading == 0.0

    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=0.0, steer_right=1.0, dt=0.5)
    assert car.heading == 0.0

    # Moving vehicle can steer
    car.speed = 5.0
    update_car_physics(car, throttle=0.0, brake=0.0, steer_left=1.0, steer_right=0.0, dt=0.5)
    assert car.heading > 0.0


def test_full_throttle_reaches_100_kmh_in_about_seven_seconds():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)

    for _ in range(70):
        update_car_physics(car, throttle=1.0, brake=0.0, steer_left=0.0, steer_right=0.0, dt=0.1)

    assert 27.0 <= car.speed <= 28.5


def test_speed_limiter_brakes_smoothly_to_limit():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=20.0)

    update_car_physics(
        car,
        throttle=1.0,
        brake=0.0,
        steer_left=0.0,
        steer_right=0.0,
        dt=0.1,
        speed_limit_mps=10.0,
    )

    assert car.speed == 19.6
    assert car.speed > 10.0


def test_speed_limiter_caps_reverse_speed():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)

    for _ in range(10):
        update_car_physics(
            car,
            throttle=0.0,
            brake=1.0,
            steer_left=0.0,
            steer_right=0.0,
            dt=0.1,
            speed_limit_mps=10.0,
        )

    assert car.speed == -10.0
