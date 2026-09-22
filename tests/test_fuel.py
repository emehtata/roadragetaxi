import pytest

from theroadragetrip.fuel import (
    FUEL_TANK_CAPACITY_L,
    INITIAL_FUEL_L,
    consume_fuel,
    consumption_l_per_100km,
    fuel_used_liters,
    calculate_fuel_purchase,
    fuel_station_price_cents,
    idle_consumption_l_per_hour,
    nearest_fuel_station,
    update_car_fuel,
)
from theroadragetrip.physics import Car
from theroadragetrip.osm import SceneryObject


def test_reference_consumption_at_90_and_200_kmh():
    assert consumption_l_per_100km(90 / 3.6, 0.35, 0.0) == pytest.approx(10.0)
    assert consumption_l_per_100km(200 / 3.6, 0.35, 0.0) == pytest.approx(20.0)


def test_acceleration_raises_consumption_at_the_same_speed_and_braking_drops_it_near_zero():
    steady = consumption_l_per_100km(90 / 3.6, 0.35, 0.0)
    accelerating = consumption_l_per_100km(90 / 3.6, 0.35, 0.0, acceleration_mps2=4.0)
    braking = consumption_l_per_100km(90 / 3.6, 1.0, 1.0, acceleration_mps2=4.0)
    assert accelerating > steady + 9.0
    assert braking < 0.2


def test_heavy_throttle_has_a_small_immediate_penalty_before_acceleration_is_measured():
    steady = consumption_l_per_100km(50 / 3.6, 0.35, 0.0)
    full_throttle = consumption_l_per_100km(50 / 3.6, 1.0, 0.0)
    assert full_throttle > steady


def test_distance_rate_conversion_uses_liters_per_100km():
    assert fuel_used_liters(100_000, 90 / 3.6, 0.35, 0.0) == pytest.approx(10.0)


def test_consumption_never_makes_tank_negative():
    car = Car(0, 0, 0, 0, fuel_l=0.01)
    used = consume_fuel(car, 100_000, 200 / 3.6, 1.0, 0.0)
    assert used == pytest.approx(0.01)
    assert car.fuel_l == 0.0


def test_player_car_starts_with_half_full_60_liter_tank():
    car = Car(0, 0, 0, 0)
    assert car.fuel_capacity_l == FUEL_TANK_CAPACITY_L
    assert car.fuel_l == INITIAL_FUEL_L == 30.0


def test_empty_tank_stops_car_and_switches_engine_off():
    car = Car(0, 0, 0, 25, fuel_l=0.001)
    became_empty = update_car_fuel(car, 1000, car.speed, 1.0, 0.0)
    assert became_empty is True
    assert car.fuel_l == 0.0
    assert car.speed == 0.0
    assert car.engine_on is False


def test_live_economy_is_zero_when_stopped_and_tracks_consumption_while_moving():
    car = Car(0, 0, 0, 25)
    update_car_fuel(car, 0.0, car.speed, 0.35, 0.0)
    assert car.fuel_consumption_l_per_100km == 0.0
    update_car_fuel(car, 10.0, car.speed, 0.35, 0.0)
    assert car.fuel_consumption_l_per_100km == pytest.approx(10.0)


def test_idling_consumes_one_to_three_liters_per_hour_based_on_temperature():
    assert idle_consumption_l_per_hour(15.0) == pytest.approx(1.0)
    assert idle_consumption_l_per_hour(-20.0) == pytest.approx(3.0)
    assert idle_consumption_l_per_hour(40.0) == pytest.approx(3.0)

    mild_car = Car(0, 0, 0, 0, fuel_l=30.0, engine_on=True)
    cold_car = Car(0, 0, 0, 0, fuel_l=30.0, engine_on=True)
    update_car_fuel(
        mild_car, 0.0, 0.0, 0.0, 0.0,
        elapsed_seconds=3600.0, outside_temperature_c=15.0,
    )
    update_car_fuel(
        cold_car, 0.0, 0.0, 0.0, 0.0,
        elapsed_seconds=3600.0, outside_temperature_c=-20.0,
    )
    assert mild_car.fuel_l == pytest.approx(29.0)
    assert cold_car.fuel_l == pytest.approx(27.0)


def test_engine_off_does_not_consume_idle_fuel():
    car = Car(0, 0, 0, 0, fuel_l=30.0, engine_on=False)
    update_car_fuel(
        car, 0.0, 0.0, 0.0, 0.0,
        elapsed_seconds=3600.0, outside_temperature_c=-20.0,
    )
    assert car.fuel_l == pytest.approx(30.0)


def test_station_price_is_deterministic_and_within_configured_range():
    station = SceneryObject(10.0, 20.0, "fuel", id=1234)
    first = fuel_station_price_cents(station)
    assert first == fuel_station_price_cents(station)
    assert 150 <= first <= 300


def test_nearest_station_only_returns_fuel_pump_in_range():
    bench = SceneryObject(0.0, 0.0, "bench", id=1)
    near = SceneryObject(5.0, 0.0, "fuel", id=2)
    far = SceneryObject(20.0, 0.0, "fuel", id=3)
    assert nearest_fuel_station([bench, far, near], 0.0, 0.0) is near
    assert nearest_fuel_station([far], 0.0, 0.0) is None


def test_refuel_fills_tank_when_balance_covers_the_cost():
    purchase = calculate_fuel_purchase(30.0, 60.0, 10_000, 200)
    assert purchase.liters == pytest.approx(30.0)
    assert purchase.cost_cents == 6_000


def test_refuel_buys_partial_fuel_without_overdrawing_balance():
    purchase = calculate_fuel_purchase(0.0, 60.0, 1_000, 200)
    assert purchase.liters == pytest.approx(5.0)
    assert purchase.cost_cents == 1_000


def test_refuel_buys_nothing_for_full_tank_or_empty_balance():
    assert calculate_fuel_purchase(60.0, 60.0, 10_000, 200).liters == 0.0
    assert calculate_fuel_purchase(30.0, 60.0, 0, 200).liters == 0.0
