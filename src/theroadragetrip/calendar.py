"""In-game calendar and Finnish thermal seasons."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from enum import Enum
from typing import Optional, Tuple


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
        """On Finnish local time: the clock skips 03:00-04:00 in spring
        and runs it twice in autumn (the second time with fold=1)."""
        self.current = finnish_local_time(finnish_utc(self.current) + timedelta(seconds=game_seconds))


def _last_sunday(year: int, month: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def _summer_time_utc(year: int) -> Tuple[datetime, datetime]:
    """Finnish summer time, as naive UTC: from the last Sunday of March to the
    last Sunday of October, both at 04:00 summer time (01:00 UTC)."""
    one_utc = datetime.min.time().replace(hour=1)
    return datetime.combine(_last_sunday(year, 3), one_utc), datetime.combine(_last_sunday(year, 10), one_utc)


class FinnishRuleTime(tzinfo):
    """Finnish time without a time-zone database: UTC+2, and UTC+3 in
    summer time. The repeated autumn hour (03:00-04:00) is summer time
    unless fold=1; the skipped spring hour counts as winter."""

    def utcoffset(self, dt: Optional[datetime]) -> timedelta:
        if dt is None:
            return timedelta(hours=2)
        local = dt.replace(tzinfo=None)
        start, end = _summer_time_utc(local.year)
        if start + timedelta(hours=3) <= local < end + timedelta(hours=3):
            return timedelta(hours=2 if dt.fold and local >= end + timedelta(hours=2) else 3)
        return timedelta(hours=2)

    def dst(self, dt: Optional[datetime]) -> timedelta:
        return self.utcoffset(dt) - timedelta(hours=2)

    def tzname(self, dt: Optional[datetime]) -> str:
        return "EEST" if self.dst(dt) else "EET"

    def fromutc(self, dt: datetime) -> datetime:
        utc = dt.replace(tzinfo=None)
        start, end = _summer_time_utc(utc.year)
        if start <= utc < end:
            return (utc + timedelta(hours=3)).replace(tzinfo=self)
        return (utc + timedelta(hours=2)).replace(tzinfo=self, fold=int(end <= utc < end + timedelta(hours=1)))


try:  # the system's time-zone database, else the rule above
    from zoneinfo import ZoneInfo
    FINLAND_TZ: tzinfo = ZoneInfo("Europe/Helsinki")
except Exception:  # tzdata missing (e.g. bare Windows)
    FINLAND_TZ = FinnishRuleTime()


def finnish_utc_offset_hours(local: datetime) -> float:
    """3 in summer time, 2 otherwise, for a naive Finnish local time."""
    return local.replace(tzinfo=FINLAND_TZ).utcoffset().total_seconds() / 3600.0


def finnish_utc(local: datetime) -> datetime:
    return local.replace(tzinfo=FINLAND_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def finnish_local_time(utc: datetime) -> datetime:
    return utc.replace(tzinfo=timezone.utc).astimezone(FINLAND_TZ).replace(tzinfo=None)


def solar_altitude_and_events_on(
    game_date: date, game_time_seconds: float, latitude: float, longitude: float, utc_offset_hours: Optional[float] = None,
) -> Tuple[float, float, float]:
    """(sun altitude in degrees, sunrise and sunset in local minutes) for a
    date and time of day - the solar model the server sends (godot-14). Sunrise/sunset: 0 and 1440 under the midnight sun, NaN in
    the polar night."""
    if utc_offset_hours is None:  # the day's offset at noon
        utc_offset_hours = finnish_utc_offset_hours(datetime.combine(game_date, datetime.min.time().replace(hour=12)))
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
    solar_minutes = game_time_seconds / 60.0 + equation_of_time + 4.0 * longitude - 60.0 * utc_offset_hours
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
        solar_noon = 720.0 - 4.0 * longitude - equation_of_time + 60.0 * utc_offset_hours
        hour_angle_minutes = 4.0 * math.degrees(math.acos(sunrise_cosine))
        sunrise_minutes = solar_noon - hour_angle_minutes
        sunset_minutes = solar_noon + hour_angle_minutes
    return altitude, sunrise_minutes, sunset_minutes


SPORTS_LIGHTS_HOURS = (7, 22)  # local time: Finnish sports fields' floodlights


def sports_lights_hours(moment) -> bool:
    """Whether sports places' floodlights may burn now (07-22 local); the
    client lights them only when its street lights are on too."""
    return SPORTS_LIGHTS_HOURS[0] <= moment.hour < SPORTS_LIGHTS_HOURS[1]


def darkness_for_sun_altitude(altitude_deg: float) -> float:
    """0 in daylight, 1 at night: full day with the sun 6 degrees up, full
    night 12 degrees below the horizon (astronomical-ish dusk), linear
    between - the night tint, street lights and ambience "twilight"."""
    return 1.0 - max(0.0, min(1.0, (altitude_deg + 12.0) / 18.0))


def _one_calendar_year_ago(day: date) -> date:
    """Return the same date last year, clamping leap day to February 28."""
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def clamp_start_datetime(value: datetime, today: date) -> datetime:
    earliest = _one_calendar_year_ago(today)
    if value.date() < earliest:
        return value.replace(year=earliest.year, month=earliest.month, day=earliest.day)
    if value.date() > today:
        return value.replace(year=today.year, month=today.month, day=today.day)
    return value


