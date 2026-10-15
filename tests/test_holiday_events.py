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


def test_fireworks_from_new_years_eve_18_until_2_at_night():
    assert on(2026, 12, 31, 17, 59) == set()
    assert on(2026, 12, 31, 18, 0) == {"fireworks"}
    assert on(2027, 1, 1, 1, 59) == {"fireworks"}
    assert on(2027, 1, 1, 2, 0) == set()


def test_halloween_yards_from_the_evening_of_31_october_until_morning():
    assert on(2026, 10, 31, 17, 59) == set()
    assert on(2026, 10, 31, 18, 0) == {"halloween"}
    assert on(2026, 11, 1, 5, 59) == {"halloween"}
    assert on(2026, 11, 1, 6, 0) == set()


def test_santas_walk_all_of_christmas_eve_only():
    assert on(2026, 12, 24, 0, 0) == {"santas"} and on(2026, 12, 24, 23, 59) == {"santas"}
    assert on(2026, 12, 23, 23, 59) == set() and on(2026, 12, 25, 0, 0) == set()


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
