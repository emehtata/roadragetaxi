"""Calendar events: New Year fireworks, Halloween yards, Christmas Eve Santas."""
from datetime import date, datetime
from types import SimpleNamespace

from theroadragetrip.holiday_events import holiday_events, house_yard_spot, santa_costume
from theroadragetrip.osm import Way
from theroadragetrip.osm.models import Building
from theroadragetrip.physics import is_point_on_road
from theroadragetrip.geo import point_in_polygon


def on(*args):
    return {name for name, active in holiday_events(datetime(*args)).items() if active}


def other(*args):
    """The active events but the window decorations (their own test)."""
    return on(*args) - {"window_decorations", "independence_candles"}


def test_fireworks_from_new_years_eve_18_until_2_at_night():
    assert other(2026, 12, 31, 17, 59) == set()
    assert other(2026, 12, 31, 18, 0) == {"fireworks"}
    assert other(2027, 1, 1, 1, 59) == {"fireworks"}
    assert other(2027, 1, 1, 2, 0) == set()


def test_halloween_season_and_night_ghosts():
    assert on(2026, 10, 23, 23, 59) == set()
    assert on(2026, 10, 24, 12, 0) == {"halloween"}
    assert on(2026, 10, 30, 19, 59) == {"halloween"}
    assert on(2026, 10, 30, 20, 0) == {"halloween", "halloween_ghosts"}
    assert on(2026, 10, 31, 18, 0) == {"halloween"}
    assert on(2026, 11, 1, 5, 59) == {"halloween", "halloween_ghosts"}
    assert on(2026, 11, 1, 6, 0) == set()


def test_christmas_season_and_santas_on_eve():
    assert other(2026, 11, 30, 23, 59) == set()
    assert other(2026, 12, 1, 0, 0) == {"christmas"}
    assert other(2026, 12, 24, 0, 0) == {"christmas", "santas"}
    assert other(2026, 12, 24, 23, 59) == {"christmas", "santas"}
    assert other(2026, 12, 25, 0, 0) == set()


def walker(resident_id, cyclist=False, activity=None):
    return SimpleNamespace(resident_id=resident_id, is_cyclist=cyclist, activity=activity)


def test_some_adult_men_walk_as_santa_and_nobody_else():
    eve = date(2026, 12, 24)
    man = SimpleNamespace(gender="male", birth_date=date(1980, 5, 1))
    assert santa_costume(walker(8), man, eve)
    assert not santa_costume(walker(9), man, eve)  # only some of them
    assert not santa_costume(walker(8), man, None)  # not Christmas Eve
    assert not santa_costume(walker(8), SimpleNamespace(gender="female", birth_date=date(1980, 5, 1)), eve)
    assert not santa_costume(walker(8), SimpleNamespace(gender="male", birth_date=date(2008, 12, 25)), eve)  # 17
    assert santa_costume(walker(8), SimpleNamespace(gender="male", birth_date=date(2008, 12, 24)), eve)  # 18 today
    assert not santa_costume(walker(8, cyclist=True), man, eve)
    assert not santa_costume(walker(8, activity=object()), man, eve)
    assert not santa_costume(walker(8), None, eve)


def square(x, y, size, building_type):
    points = [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
    return Building(points_m=points, bbox=(x, y, x + size, y + size), building_type=building_type)


def test_a_house_gets_one_yard_spot_outside_it_off_the_road():
    house = square(0.0, 0.0, 10.0, "house")
    road = Way([(-50.0, -5.0), (50.0, -5.0)], "residential", 3.0)  # along the south wall
    world = SimpleNamespace(buildings=[house], waters=[], ways=[road])
    x, y = house_yard_spot(house, world)
    assert not point_in_polygon(x, y, house.points_m)
    assert not is_point_on_road(x, y, ways=[road])
    assert house_yard_spot(square(0.0, 0.0, 10.0, "apartments"), world) is None  # houses only


def test_midsummer_bonfires_burn_from_eve_21_until_3():
    assert "midsummer_bonfires" not in on(2026, 6, 19, 20, 59)  # Midsummer Eve 2026 is Friday 19 June
    assert "midsummer_bonfires" in on(2026, 6, 19, 21, 0)
    assert "midsummer_bonfires" in on(2026, 6, 20, 2, 59)
    assert "midsummer_bonfires" not in on(2026, 6, 20, 3, 0)
    assert "midsummer_bonfires" not in on(2026, 6, 26, 22, 0)  # a Friday, but not the Eve
    assert "midsummer_bonfires" in on(2027, 6, 25, 22, 0)  # Saturday 26 June 2027


def test_window_decorations_from_the_first_advent_until_epiphany():
    assert "window_decorations" not in on(2026, 11, 28, 12, 0)  # Saturday; the first Advent is Sunday 29 November 2026
    assert "window_decorations" in on(2026, 11, 29, 0, 0)
    assert "window_decorations" in on(2026, 12, 15, 12, 0)
    assert "window_decorations" in on(2026, 12, 25, 12, 0)
    assert "christmas" not in on(2026, 12, 25, 12, 0)
    assert "window_decorations" in on(2027, 1, 6, 23, 59)
    assert "window_decorations" not in on(2027, 1, 7, 0, 0)
    assert "window_decorations" in on(2027, 11, 28, 12, 0)  # 2027: the first Advent is 28 November


def test_flags_fly_on_flag_days_by_the_official_hours():
    from theroadragetrip.holiday_events import flag_state, is_flag_day
    sun, night = 30.0, -10.0
    assert is_flag_day(datetime(2026, 2, 28)) and not is_flag_day(datetime(2026, 3, 1))
    assert flag_state(datetime(2026, 5, 1, 7, 59), sun, sun) == ""
    assert flag_state(datetime(2026, 5, 1, 8, 0), sun, sun) == "full"
    assert flag_state(datetime(2026, 5, 1, 20, 59), sun, sun) == "full"
    assert flag_state(datetime(2026, 5, 1, 21, 0), sun, sun) == ""  # summer: 21:00 at the latest
    assert flag_state(datetime(2026, 2, 28, 16, 30), night, 5.0) == ""  # winter: down at sunset
    assert flag_state(datetime(2026, 2, 28, 8, 30), night, 5.0) == "full"  # up at 8 before sunrise
    assert flag_state(datetime(2026, 12, 6, 19, 30), night, 1.0) == "full"  # Independence Day until 20
    assert flag_state(datetime(2026, 12, 6, 20, 0), night, 1.0) == ""
    assert flag_state(datetime(2026, 12, 8, 15, 0), night, -2.0) == "full"  # polar night: 8-16
    assert flag_state(datetime(2026, 12, 8, 16, 0), night, -2.0) == ""
    assert flag_state(datetime(2026, 6, 19, 17, 59), sun, sun) == ""  # Midsummer Eve from 18
    assert flag_state(datetime(2026, 6, 19, 23, 30), night, sun) == "full"
    assert flag_state(datetime(2026, 6, 20, 3, 0), night, sun) == "full"  # through the night
    assert flag_state(datetime(2026, 6, 20, 21, 0), sun, sun) == ""
    assert flag_state(datetime(2026, 5, 17, 10, 0), sun, sun) == "half"  # Fallen Soldiers: half-mast until noon
    assert flag_state(datetime(2026, 5, 17, 12, 0), sun, sun) == "full"
    assert flag_state(datetime(2026, 5, 10, 9, 0), sun, sun) == "full"  # Mother's Day 2026
    assert flag_state(datetime(2026, 11, 8, 9, 0), sun, sun) == "full"  # Father's Day 2026
    assert flag_state(datetime(2026, 8, 29, 9, 0), sun, sun) == "full"  # Nature Day: last Saturday of August
    assert flag_state(datetime(2026, 8, 28, 9, 0), sun, sun) == ""


def test_independence_day_candles_from_18_until_midnight():
    assert "independence_candles" not in on(2026, 12, 6, 17, 59)
    assert "independence_candles" in on(2026, 12, 6, 18, 0)
    assert "independence_candles" in on(2026, 12, 6, 23, 59)
    assert "independence_candles" not in on(2026, 12, 7, 0, 0)
