"""Typical Finnish temperatures and temperature-defined thermal seasons.

This is a deterministic climatology, not a live forecast. It provides a
plausible baseline for the selected game date, time and latitude.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import math

from .calendar import Season


REFERENCE_LATITUDE = 60.17  # Helsinki
ANNUAL_MEAN_AT_REFERENCE_C = 6.5
MEAN_LATITUDE_LAPSE_C_PER_DEGREE = 0.65
ANNUAL_AMPLITUDE_AT_REFERENCE_C = 11.5
AMPLITUDE_INCREASE_PER_DEGREE = 0.22
WARMEST_DAY_OF_YEAR = 205  # late July; seasonal temperature lags daylight


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
    """Classify the seven-day mean using Finnish thermal-season limits.

    Below 0 °C is winter and above 10 °C is summer. Between the thresholds,
    a warming climatology is spring and a cooling climatology is autumn.
    Seven consecutive modeled daily means are averaged to represent the
    Finnish Meteorological Institute's permanence criterion.
    """
    current_mean = sum(
        typical_daily_mean_temperature(day - timedelta(days=offset), latitude)
        for offset in range(7)
    ) / 7.0
    if current_mean < 0.0:
        return Season.WINTER
    if current_mean > 10.0:
        return Season.SUMMER
    previous_mean = sum(
        typical_daily_mean_temperature(day - timedelta(days=7 + offset), latitude)
        for offset in range(7)
    ) / 7.0
    return Season.SPRING if current_mean >= previous_mean else Season.AUTUMN
