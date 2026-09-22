from datetime import date, datetime, timedelta

import pytest

from theroadragetrip.calendar import Season
from theroadragetrip.climate import (
    thermal_season_for_date,
    typical_daily_mean_temperature,
    typical_temperature,
)


def test_typical_temperature_is_lower_at_higher_latitude():
    day = date(2026, 1, 15)
    helsinki = typical_daily_mean_temperature(day, 60.17)
    oulu = typical_daily_mean_temperature(day, 65.0)
    utsjoki = typical_daily_mean_temperature(day, 69.9)
    assert utsjoki < oulu < helsinki


def test_typical_finnish_summer_is_warmer_than_winter():
    latitude = 65.0
    assert typical_daily_mean_temperature(date(2026, 7, 15), latitude) > 10.0
    assert typical_daily_mean_temperature(date(2026, 1, 15), latitude) < 0.0


def test_diurnal_cycle_is_warmer_in_afternoon_than_before_dawn():
    afternoon = typical_temperature(datetime(2026, 7, 20, 15), 60.17)
    before_dawn = typical_temperature(datetime(2026, 7, 20, 3), 60.17)
    assert afternoon > before_dawn


def test_thermal_seasons_follow_seven_day_zero_and_ten_degree_limits():
    latitude = 60.17
    assert thermal_season_for_date(date(2026, 1, 15), latitude) == Season.WINTER
    assert thermal_season_for_date(date(2026, 4, 15), latitude) == Season.SPRING
    assert thermal_season_for_date(date(2026, 7, 15), latitude) == Season.SUMMER
    assert thermal_season_for_date(date(2026, 10, 15), latitude) == Season.AUTUMN


@pytest.mark.parametrize(
    ("warming", "means", "expected"),
    [
        (True, [-0.1, 1, 1, 1, 1, 1, 1], Season.WINTER),
        (True, [0.1, 1, 1, 1, 1, 1, 1], Season.SPRING),
        (True, [9.9, 11, 11, 11, 11, 11, 11], Season.SPRING),
        (True, [10.1, 11, 11, 11, 11, 11, 11], Season.SUMMER),
        (False, [10.1, 9, 9, 9, 9, 9, 9], Season.SUMMER),
        (False, [9.9, 9, 9, 9, 9, 9, 9], Season.AUTUMN),
        (False, [0.1, -1, -1, -1, -1, -1, -1], Season.AUTUMN),
        (False, [-0.1, -1, -1, -1, -1, -1, -1], Season.WINTER),
    ],
)
def test_thermal_transition_requires_seven_consecutive_days(
    monkeypatch, warming, means, expected
):
    anchor = date(2026, 6, 1)
    by_day = {
        anchor - timedelta(days=offset): value
        for offset, value in enumerate(means)
    }
    by_day[anchor - timedelta(days=7)] = means[0] - (1 if warming else -1)
    monkeypatch.setattr(
        "theroadragetrip.climate.typical_daily_mean_temperature",
        lambda day, latitude: by_day[day],
    )
    assert thermal_season_for_date(anchor, 60.17) == expected
