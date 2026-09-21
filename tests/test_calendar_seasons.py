from datetime import datetime

import pytest

from theroadragetrip.calendar import GameCalendar, Season, season_for_month
from theroadragetrip.render.scenery import seasonal_vegetation_color
from theroadragetrip.weather import WeatherSystem


@pytest.mark.parametrize(
    ("month", "season"),
    [
        (1, Season.WINTER), (2, Season.WINTER), (3, Season.SPRING),
        (5, Season.SPRING), (6, Season.SUMMER), (8, Season.SUMMER),
        (9, Season.AUTUMN), (11, Season.AUTUMN), (12, Season.WINTER),
    ],
)
def test_three_month_seasons(month, season):
    assert season_for_month(month) == season


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
