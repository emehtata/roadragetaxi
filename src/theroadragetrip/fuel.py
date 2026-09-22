"""Player-taxi fuel consumption, independent of rendering and Pygame."""
from __future__ import annotations

from dataclasses import dataclass
import math


FUEL_TANK_CAPACITY_L = 60.0
INITIAL_FUEL_L = 30.0
FUEL_STATION_RANGE_M = 8.0
MIN_FUEL_PRICE_CENTS = 150
MAX_FUEL_PRICE_CENTS = 300


@dataclass(frozen=True)
class FuelPurchase:
    liters: float
    cost_cents: int


def fuel_station_price_cents(station) -> int:
    """Return a deterministic €1.50–€3.00 per-liter price for a station."""
    station_id = getattr(station, "id", None)
    if station_id is None:
        x_key = int(round(getattr(station, "x", 0.0) * 10.0))
        y_key = int(round(getattr(station, "y", 0.0) * 10.0))
        station_id = x_key * 73_856_093 ^ y_key * 19_349_663
    span = MAX_FUEL_PRICE_CENTS - MIN_FUEL_PRICE_CENTS + 1
    return MIN_FUEL_PRICE_CENTS + (abs(int(station_id)) * 2_654_435_761) % span


def nearest_fuel_station(scenery_objects, x: float, y: float, max_distance_m: float = FUEL_STATION_RANGE_M):
    """Return the closest mapped fuel pump in range, or ``None``."""
    stations = (obj for obj in scenery_objects if getattr(obj, "kind", None) == "fuel")
    nearest = None
    nearest_distance = max_distance_m
    for station in stations:
        distance = math.hypot(station.x - x, station.y - y)
        if distance <= nearest_distance:
            nearest = station
            nearest_distance = distance
    return nearest


def calculate_fuel_purchase(
    fuel_l: float, capacity_l: float, balance_cents: int, price_cents_per_liter: int
) -> FuelPurchase:
    """Calculate a full or balance-limited fill without overdrawing money."""
    needed_l = max(0.0, capacity_l - max(0.0, fuel_l))
    balance_cents = max(0, int(balance_cents))
    if needed_l <= 1e-9 or balance_cents <= 0 or price_cents_per_liter <= 0:
        return FuelPurchase(0.0, 0)
    full_cost = math.ceil(needed_l * price_cents_per_liter)
    if full_cost <= balance_cents:
        return FuelPurchase(needed_l, full_cost)
    return FuelPurchase(balance_cents / price_cents_per_liter, balance_cents)


def consumption_l_per_100km(
    speed_mps: float,
    throttle: float,
    brake: float,
    acceleration_mps2: float = 0.0,
) -> float:
    """Return instantaneous distance-based consumption for the driving state.

    The baseline is 10 L/100 km at 90 km/h and 20 L/100 km at 200 km/h.
    Actual forward acceleration adds an aggressive-driving penalty; braking
    represents overrun fuel cut and therefore consumes only a negligible
    amount. A small throttle penalty still distinguishes full-power demand
    before measured acceleration has caught up on the first physics frame.
    """
    if brake > 0.05:
        return 0.1

    speed_kmh = abs(speed_mps) * 3.6
    if speed_kmh <= 90.0:
        baseline = 7.0 + 3.0 * (speed_kmh / 90.0) ** 2
    else:
        baseline = 10.0 + 10.0 * min(1.0, (speed_kmh - 90.0) / 110.0)
    aggressive_throttle = max(0.0, min(1.0, throttle) - 0.35)
    acceleration_penalty = 2.5 * max(0.0, min(6.0, acceleration_mps2))
    return baseline + 2.0 * aggressive_throttle ** 2 + acceleration_penalty


def fuel_used_liters(
    distance_m: float,
    speed_mps: float,
    throttle: float,
    brake: float,
    acceleration_mps2: float = 0.0,
) -> float:
    """Return fuel used over a traveled distance in liters."""
    if distance_m <= 0.0:
        return 0.0
    rate = consumption_l_per_100km(
        speed_mps, throttle, brake, acceleration_mps2
    )
    return max(0.0, distance_m) * rate / 100_000.0


def consume_fuel(
    car,
    distance_m: float,
    speed_mps: float,
    throttle: float,
    brake: float,
    acceleration_mps2: float = 0.0,
) -> float:
    """Consume and clamp a car's fuel, returning the liters used."""
    available = max(0.0, min(car.fuel_capacity_l, car.fuel_l))
    used = min(
        available,
        fuel_used_liters(
            distance_m, speed_mps, throttle, brake, acceleration_mps2
        ),
    )
    car.fuel_l = max(0.0, available - used)
    return used


def update_car_fuel(
    car,
    distance_m: float,
    speed_mps: float,
    throttle: float,
    brake: float,
    acceleration_mps2: float = 0.0,
) -> bool:
    """Consume fuel and enforce starvation; return whether fuel just ran out."""
    had_fuel = car.fuel_l > 0.0
    car.fuel_consumption_l_per_100km = (
        consumption_l_per_100km(
            speed_mps, throttle, brake, acceleration_mps2
        )
        if distance_m > 0.0 and car.engine_on
        else 0.0
    )
    consume_fuel(
        car, distance_m, speed_mps, throttle, brake, acceleration_mps2
    )
    if car.fuel_l <= 0.0:
        car.speed = 0.0
        car.engine_on = False
        car.fuel_consumption_l_per_100km = 0.0
    return had_fuel and car.fuel_l <= 0.0
