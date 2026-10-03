from theroadragetrip.physics import Car, update_car_physics
from theroadragetrip.residents import ResidentManager
from theroadragetrip.taxi import TaxiManager, TaxiPassenger, TaxiTarget


def _physics_step(car, throttle=0.0, brake=0.0):
    update_car_physics(
        car,
        throttle=throttle,
        brake=brake,
        steer_left=0.0,
        steer_right=0.0,
        dt=0.1,
    )


def test_taxi_mass_includes_car_driver_and_passenger():
    car = Car(0, 0, 0, 0, passenger_mass_kg=80.0)
    assert car.total_mass_kg == 1400.0 + 90.0 + 80.0


def test_passenger_weight_is_between_50_and_120_kg():
    target = TaxiTarget(0, 0, "Test")
    passengers = [TaxiPassenger("Test", target, target) for _ in range(40)]
    assert all(50.0 <= passenger.weight_kg <= 120.0 for passenger in passengers)


def test_taxi_passenger_reuses_the_residents_stable_weight():
    residents = ResidentManager()
    resident = residents.create()
    taxi = TaxiManager([], resident_manager=residents)

    _name, _gender, resident_id, weight_kg = taxi._new_passenger_identity(resident)

    assert resident_id == resident.resident_id
    assert weight_kg == resident.weight_kg


def test_passenger_mass_reduces_acceleration_from_same_engine_force():
    solo = Car(0, 0, 0, 0)
    loaded = Car(0, 0, 0, 0, passenger_mass_kg=120.0)
    _physics_step(solo, throttle=1.0)
    _physics_step(loaded, throttle=1.0)
    assert loaded.speed < solo.speed


def test_passenger_mass_increases_stopping_distance_for_same_brake_force():
    solo = Car(0, 0, 0, 20.0)
    loaded = Car(0, 0, 0, 20.0, passenger_mass_kg=120.0)
    _physics_step(solo, brake=1.0)
    _physics_step(loaded, brake=1.0)
    assert loaded.speed > solo.speed
