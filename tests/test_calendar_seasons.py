from datetime import datetime

import pytest

from theroadragetrip.calendar import GameCalendar, Season
from theroadragetrip.climate import SeasonalAppearance
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






def test_clear_winter_still_uses_slippery_road_grip_value():
    summer = WeatherSystem(season=Season.SUMMER)
    winter = WeatherSystem(season=Season.WINTER)
    assert summer.road_grip_wetness == 0.0
    assert winter.road_grip_wetness == 1.0


def test_the_clock_follows_finnish_summer_time():
    from theroadragetrip.calendar import finnish_utc_offset_hours, solar_altitude_and_events_on
    assert finnish_utc_offset_hours(datetime(2026, 1, 15, 12)) == 2.0
    assert finnish_utc_offset_hours(datetime(2026, 7, 15, 12)) == 3.0
    spring = GameCalendar(datetime(2026, 3, 29, 2, 59, 30))  # last Sunday of March
    spring.advance(60)
    assert spring.current == datetime(2026, 3, 29, 4, 0, 30)  # 03:00 never comes
    autumn = GameCalendar(datetime(2026, 10, 25, 3, 59, 30))  # last Sunday of October
    autumn.advance(60)
    assert autumn.current == datetime(2026, 10, 25, 3, 0, 30) and autumn.current.fold == 1
    assert finnish_utc_offset_hours(autumn.current) == 2.0
    autumn.advance(3600)
    assert autumn.current == datetime(2026, 10, 25, 4, 0, 30)
    # the sun: winter's 12:00 is an hour later in solar time than summer time would make it
    _, winter_rise, _ = solar_altitude_and_events_on(datetime(2026, 12, 1).date(), 43200, 65.0, 25.5)
    _, summer_clock_rise, _ = solar_altitude_and_events_on(datetime(2026, 12, 1).date(), 43200, 65.0, 25.5, 3.0)
    assert abs((summer_clock_rise - winter_rise) - 60.0) < 0.01
