"""Finnish taxi fare calculation in integer euro cents."""
from __future__ import annotations

from datetime import datetime


WEEKDAY_DAY_START_CENTS = 800
OTHER_START_CENTS = 1250
PER_KILOMETRE_CENTS = 150
PER_MINUTE_CENTS = 92


def starting_fee_cents(moment: datetime) -> int:
    """Return the starting fee for the local pickup date and time."""
    hour = moment.hour + moment.minute / 60.0 + moment.second / 3600.0
    weekday = moment.weekday()  # Monday=0, Saturday=5, Sunday=6
    daytime = (weekday <= 4 and 6.0 <= hour < 20.0) or (weekday == 5 and 6.0 <= hour < 16.0)
    return WEEKDAY_DAY_START_CENTS if daytime else OTHER_START_CENTS


def calculate_fare_cents(distance_m: float, duration_s: float, started_at: datetime) -> int:
    """Calculate the fare, always rounded upward to the next ten cents."""
    distance_charge = round(max(0.0, distance_m) / 1000.0 * PER_KILOMETRE_CENTS)
    time_charge = round(max(0.0, duration_s) / 60.0 * PER_MINUTE_CENTS)
    unrounded_cents = starting_fee_cents(started_at) + distance_charge + time_charge
    return ((unrounded_cents + 9) // 10) * 10


def format_euros(cents: int, language: str = "fi") -> str:
    separator = "," if language == "fi" else "."
    euros, remainder = divmod(max(0, int(cents)), 100)
    return f"{euros}{separator}{remainder:02d} €"


def tip_cents_from_happiness(happiness: float) -> int:
    """Map clamped 0-100 passenger happiness to a €0-€10 tip."""
    return round(max(0.0, min(100.0, happiness))) * 10
