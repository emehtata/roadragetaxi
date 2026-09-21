from datetime import date, datetime

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
