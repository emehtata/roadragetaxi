"""In-game calendar and Finnish thermal seasons."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Tuple


class Season(str, Enum):
    WINTER = "winter"
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"


def season_for_month(month: int) -> Season:
    """Return the legacy fixed season for callers that only have a month."""
    if not 1 <= month <= 12:
        raise ValueError(f"month must be in 1..12, got {month}")
    if month in (12, 1, 2):
        return Season.WINTER
    if month <= 5:
        return Season.SPRING
    if month <= 8:
        return Season.SUMMER
    return Season.AUTUMN


@dataclass
class GameCalendar:
    """Mutable local game datetime advanced in game seconds."""

    current: datetime
    latitude: float = 60.17

    @classmethod
    def from_date_and_seconds(cls, day: date, seconds: float) -> "GameCalendar":
        midnight = datetime.combine(day, datetime.min.time())
        return cls(midnight + timedelta(seconds=seconds))

    @property
    def date(self) -> date:
        return self.current.date()

    @property
    def time_seconds(self) -> float:
        midnight = datetime.combine(self.date, datetime.min.time())
        return (self.current - midnight).total_seconds()

    @property
    def season(self) -> Season:
        # Local import avoids a module cycle: climate imports the shared enum.
        from .climate import thermal_season_for_date

        return thermal_season_for_date(self.date, self.latitude)

    @property
    def seasonal_appearance(self):
        from .climate import seasonal_appearance_for_date

        return seasonal_appearance_for_date(self.date, self.latitude)

    def advance(self, game_seconds: float) -> None:
        self.current += timedelta(seconds=game_seconds)


FINLAND_SUMMER_TIME_OFFSET = 3.0  # hours: the game clock is Finnish summer time all year


def solar_altitude_and_events_on(
    game_date: date, game_time_seconds: float, latitude: float, longitude: float,
) -> Tuple[float, float, float]:
    """(sun altitude in degrees, sunrise and sunset in local minutes) for a
    date and time of day - the solar model render/common.py's
    solar_altitude_and_events caches for Pygame, and the server sends
    (godot-14). Sunrise/sunset: 0 and 1440 under the midnight sun, NaN in
    the polar night."""
    day_of_year = game_date.timetuple().tm_yday
    declination = math.radians(23.45 * math.sin(math.radians(360.0 * (284.0 + day_of_year) / 365.0)))
    latitude_radians = math.radians(latitude)
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1.0)
    equation_of_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2.0 * gamma)
        - 0.040849 * math.sin(2.0 * gamma)
    )
    solar_minutes = game_time_seconds / 60.0 + equation_of_time + 4.0 * longitude - 60.0 * FINLAND_SUMMER_TIME_OFFSET
    hour_angle = math.radians(solar_minutes / 4.0 - 180.0)
    altitude = math.degrees(math.asin(
        math.sin(latitude_radians) * math.sin(declination)
        + math.cos(latitude_radians) * math.cos(declination) * math.cos(hour_angle)
    ))
    sunrise_cosine = (
        math.cos(math.radians(90.833)) / (math.cos(latitude_radians) * math.cos(declination))
        - math.tan(latitude_radians) * math.tan(declination)
    )
    if sunrise_cosine <= -1.0:
        sunrise_minutes, sunset_minutes = 0.0, 1440.0
    elif sunrise_cosine >= 1.0:
        sunrise_minutes = sunset_minutes = float("nan")
    else:
        solar_noon = 720.0 - 4.0 * longitude - equation_of_time + 60.0 * FINLAND_SUMMER_TIME_OFFSET
        hour_angle_minutes = 4.0 * math.degrees(math.acos(sunrise_cosine))
        sunrise_minutes = solar_noon - hour_angle_minutes
        sunset_minutes = solar_noon + hour_angle_minutes
    return altitude, sunrise_minutes, sunset_minutes


def darkness_for_sun_altitude(altitude_deg: float) -> float:
    """0 in daylight, 1 at night: full day with the sun 6 degrees up, full
    night 12 degrees below the horizon (astronomical-ish dusk), linear
    between - Pygame's night tint, street-light and ambience "twilight"."""
    return 1.0 - max(0.0, min(1.0, (altitude_deg + 12.0) / 18.0))
