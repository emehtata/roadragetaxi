"""Typical Finnish temperatures and temperature-defined thermal seasons.

This is a deterministic climatology, not a live forecast. It provides a
plausible baseline for the selected game date, time and latitude.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from dataclasses import dataclass
import math

from .calendar import Season


REFERENCE_LATITUDE = 60.17  # Helsinki
ANNUAL_MEAN_AT_REFERENCE_C = 6.5
MEAN_LATITUDE_LAPSE_C_PER_DEGREE = 0.65
ANNUAL_AMPLITUDE_AT_REFERENCE_C = 11.5
AMPLITUDE_INCREASE_PER_DEGREE = 0.22
WARMEST_DAY_OF_YEAR = 205  # late July; seasonal temperature lags daylight


@dataclass(frozen=True)
class SeasonalAppearance:
    """Continuous visual weights, separate from the thermal-season label."""

    winter: float = 0.0
    spring: float = 0.0
    summer: float = 0.0
    autumn: float = 0.0


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def seasonal_appearance_for_date(day: date, latitude: float) -> SeasonalAppearance:
    """Return gradual, latitude-aware vegetation and snow-cover weights.

    Thermal seasons deliberately remain strict seven-day classifications.
    Visual nature is not: autumn color begins while mean temperatures are
    still above +10 C, and spring snow fades across a broad warming range.
    """
    mean = typical_daily_mean_temperature(day, latitude)
    warming = mean >= typical_daily_mean_temperature(day - timedelta(days=7), latitude)
    if warming:
        spring_progress = _smoothstep((mean + 3.0) / 8.0)
        if spring_progress < 1.0:
            return SeasonalAppearance(winter=1.0 - spring_progress, spring=spring_progress)
        summer_progress = _smoothstep((mean - 5.0) / 9.0)
        return SeasonalAppearance(spring=1.0 - summer_progress, summer=summer_progress)

    autumn_progress = _smoothstep((15.0 - mean) / 10.0)
    if autumn_progress < 1.0:
        return SeasonalAppearance(summer=1.0 - autumn_progress, autumn=autumn_progress)
    winter_progress = _smoothstep((3.0 - mean) / 6.0)
    return SeasonalAppearance(autumn=1.0 - winter_progress, winter=winter_progress)


FULL_SNOW_COVER_DEPTH_CM = 10.0  # observed snow depth at which the ground reads fully white


def appearance_with_snow_depth(appearance: SeasonalAppearance, snow_depth_cm: float) -> SeasonalAppearance:
    """Replace the date-based snow weight with an observed snow depth.

    Snow cover (the `winter` weight) follows the real depth; the vegetation
    weights keep their date-based proportions in the remainder. A snowless
    winter date reads as late autumn (bare ground). Snow is rounded to 0.1
    steps so hourly depth changes don't rebuild every static render cache.
    """
    snow = round(_smoothstep(snow_depth_cm / FULL_SNOW_COVER_DEPTH_CM) * 10.0) / 10.0
    others = (appearance.spring, appearance.summer, appearance.autumn)
    total = sum(others)
    spring, summer, autumn = (value / total for value in others) if total > 1e-9 else (0.0, 0.0, 1.0)
    rest = 1.0 - snow
    return SeasonalAppearance(winter=snow, spring=spring * rest, summer=summer * rest, autumn=autumn * rest)


def typical_daily_mean_temperature(day: date, latitude: float) -> float:
    """Return a smooth climatological daily mean for Finland in °C."""
    latitude_delta = max(0.0, min(12.0, latitude - REFERENCE_LATITUDE))
    annual_mean = ANNUAL_MEAN_AT_REFERENCE_C - latitude_delta * MEAN_LATITUDE_LAPSE_C_PER_DEGREE
    amplitude = ANNUAL_AMPLITUDE_AT_REFERENCE_C + latitude_delta * AMPLITUDE_INCREASE_PER_DEGREE
    phase = 2.0 * math.pi * (day.timetuple().tm_yday - WARMEST_DAY_OF_YEAR) / 365.2425
    return annual_mean + amplitude * math.cos(phase)


def typical_temperature(moment: datetime, latitude: float) -> float:
    """Return typical temperature including a modest local-time cycle."""
    daily_mean = typical_daily_mean_temperature(moment.date(), latitude)
    # Diurnal range is smallest in dark winter and largest in summer.
    seasonal_warmth = (math.cos(
        2.0 * math.pi * (moment.timetuple().tm_yday - WARMEST_DAY_OF_YEAR) / 365.2425
    ) + 1.0) / 2.0
    diurnal_amplitude = 1.2 + 2.3 * seasonal_warmth
    local_hour = moment.hour + moment.minute / 60.0 + moment.second / 3600.0
    # Daily maximum around 15:00, minimum around 03:00.
    return daily_mean + diurnal_amplitude * math.cos(2.0 * math.pi * (local_hour - 15.0) / 24.0)


def thermal_season_for_date(day: date, latitude: float) -> Season:
    """Classify a date using Finnish thermal-season limits.

    A threshold takes effect only after seven consecutive modeled daily means
    remain on its new side. Until then the preceding season continues. The
    direction of the annual temperature curve distinguishes spring from autumn.
    """
    daily_means = [
        typical_daily_mean_temperature(day - timedelta(days=offset), latitude)
        for offset in range(7)
    ]
    warming = daily_means[0] >= typical_daily_mean_temperature(
        day - timedelta(days=7), latitude
    )

    if warming:
        if all(value > 10.0 for value in daily_means):
            return Season.SUMMER
        if all(value > 0.0 for value in daily_means):
            return Season.SPRING
        return Season.WINTER

    if all(value < 0.0 for value in daily_means):
        return Season.WINTER
    if all(value < 10.0 for value in daily_means):
        return Season.AUTUMN
    return Season.SUMMER
