from types import SimpleNamespace

from theroadragetrip.population import (
    OUTDOOR_SHARE, building_people, municipality_at, people_within, walkers_within, walking_share,
)


def building(x, y, kind="yes", size=10.0, levels=None):
    return SimpleNamespace(points_m=[(x, y), (x + size, y), (x + size, y + size), (x, y + size)],
                           bbox=(x, y, x + size, y + size), building_type=kind, levels=levels,
                           height_m=8.0, height_is_explicit=False)


def test_a_building_accounts_for_people_by_its_type_and_size():
    assert building_people(building(0, 0, "house")) == 2.5
    assert building_people(building(0, 0, "sauna")) == 0.0
    assert building_people(building(0, 0, "cabin")) < 1.0  # seasonal: mostly empty
    assert building_people(building(0, 0, "yes", 5)) == 0.0  # an untagged shed
    assert building_people(building(0, 0, "apartments", 20, 4)) == 40.0
    assert building_people(building(0, 0, "retail", 50)) == 50.0  # visitors


def test_people_are_counted_once_within_the_disc():
    home, far = building(0, 0, "house"), building(500, 0, "house")
    assert people_within([home, home, far], 0, 0, 100) == 2.5


def test_the_municipality_sets_how_many_walk(kunnat_centres):
    sysma = municipality_at(429772.0, 6819445.0)
    helsinki = municipality_at(385700.0, 6672126.0)
    assert sysma["taajama"] == "Sysmä" and helsinki["taajama"] == "Helsinki"
    assert walking_share(sysma) < walking_share(helsinki) == OUTDOOR_SHARE
    assert walking_share(None) == OUTDOOR_SHARE


def test_an_isolated_cabin_gets_one_walker_at_most(kunnat_centres):
    """Regression (Sysmä): tens of people around a cottage."""
    sysma = municipality_at(429772.0, 6819445.0)
    cabin = [building(0, 0, "cabin"), building(15, 0, "sauna", 4), building(0, 20, "yes", 6)]
    assert walkers_within(cabin, 0, 0, 120, sysma) == 1
    assert walkers_within([], 0, 0, 120, sysma) == 0
