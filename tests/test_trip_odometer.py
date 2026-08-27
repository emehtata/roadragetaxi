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
