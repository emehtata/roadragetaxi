from datetime import datetime

import pytest

from theroadragetrip.calendar import GameCalendar, Season
from theroadragetrip.render.scenery import seasonal_vegetation_color
from theroadragetrip.weather import WeatherSystem


@pytest.mark.parametrize(
    ("moment", "season"),
    [
        (datetime(2026, 1, 15), Season.WINTER),
        (datetime(2026, 4, 15), Season.SPRING),
        (datetime(2026, 7, 15), Season.SUMMER),
        (datetime(2026, 10, 15), Season.AUTUMN),
    ],
)
def test_calendar_uses_thermal_seasons(moment, season):
    assert GameCalendar(moment, latitude=60.17).season == season


def test_calendar_season_depends_on_latitude():
    day = datetime(2026, 5, 18)
    assert GameCalendar(day, latitude=60.17).season == Season.SUMMER
    assert GameCalendar(day, latitude=69.9).season == Season.SPRING


def test_calendar_crosses_midnight_and_leap_day():
    calendar = GameCalendar(datetime(2028, 2, 28, 23, 59, 30))
    calendar.advance(90)
    assert calendar.current == datetime(2028, 2, 29, 0, 1)
    assert calendar.season == Season.WINTER


def test_seasonal_palette_keeps_summer_and_changes_other_seasons():
    green = (40, 100, 40)
    assert seasonal_vegetation_color(green, Season.SUMMER) == green
    assert min(seasonal_vegetation_color(green, Season.WINTER)) >= 218
    spring = seasonal_vegetation_color(green, Season.SPRING)
    assert sum(spring) > sum(green)
    autumn = seasonal_vegetation_color(green, Season.AUTUMN)
    assert autumn[0] > autumn[2]


def test_clear_winter_still_uses_slippery_road_grip_value():
    summer = WeatherSystem(season=Season.SUMMER)
    winter = WeatherSystem(season=Season.WINTER)
    assert summer.road_grip_wetness == 0.0
    assert winter.road_grip_wetness == 1.0
