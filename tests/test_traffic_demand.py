"""rrt-018-traffic: moving NPC traffic follows the people around, the road
and the clock. Repeated, seeded trials of the moving-traffic target over
one-minute draws (NPC_DEMAND_ROLL_TICKS)."""
from datetime import datetime

import pytest
from types import SimpleNamespace

from theroadragetrip.npc import NPC_DEMAND_ROLL_TICKS, NPCVehicleManager
from theroadragetrip.osm import Way
from theroadragetrip.physics import SpatialWayGrid
from theroadragetrip.population import hour_demand, is_public_holiday

WEEKDAY_DAY = datetime(2026, 10, 14, 16, 0)  # a Wednesday, afternoon peak
WEEKDAY_RUSH = datetime(2026, 10, 14, 7, 30)
LATE_EVENING = datetime(2026, 10, 14, 23, 30)
OCTOBER_NIGHT = datetime(2026, 10, 15, 1, 0)  # 01:00 on a Thursday in October
JULY_DAY = datetime(2026, 7, 15, 14, 0)
OCTOBER_DAY = datetime(2026, 10, 14, 14, 0)


def building(x, y, kind, size=8, levels=None):
    return SimpleNamespace(points_m=[(x, y), (x + size, y), (x + size, y + size), (x, y + size)],
                           bbox=(x, y, x + size, y + size), building_type=kind, levels=levels,
                           height_m=8.0, height_is_explicit=False)


def grid_of(buildings):
    grid = SpatialWayGrid()
    grid.rebuild(buildings)
    return grid


CITY = grid_of([building(25 * (i % 20), 25 * (i // 20), "apartments", 20, 5) for i in range(400)])  # centre at (250, 250)
SUBURB = grid_of([building(30 * (i % 15), 30 * (i // 15), "house") for i in range(225)])  # centre at (225, 225)
VILLAGE = grid_of([building(40 * (i % 5), 40 * (i // 5), "house") for i in range(20)])
REMOTE = grid_of([building(0, 20, "house"), building(20, 30, "sauna", 4), building(200, -40, "cabin")])
CABINS = grid_of([building(30 * (i % 8), 50 * (i // 8), "cabin") for i in range(40)])


def mean_moving(grid, x, y, moment, highway=None, city_target=40, draws=2000, seed=7):
    """Mean moving-traffic target over `draws` one-minute periods."""
    manager = NPCVehicleManager(target_count=city_target)
    manager.demand_rng.seed(seed)
    manager.clock = moment
    way = Way([(x - 50, y), (x + 50, y)], highway, 4.0) if highway else None
    total = 0
    for _ in range(draws):
        manager._population_tick_number += NPC_DEMAND_ROLL_TICKS
        manager.set_local_density(x, y, grid, current_way=way)
        total += manager.target_moving_count
    return total / draws, manager


def test_a_city_centre_is_busy_by_day_and_quiet_at_night():
    day, _ = mean_moving(CITY, 250, 250, WEEKDAY_DAY, "residential")
    night, _ = mean_moving(CITY, 250, 250, OCTOBER_NIGHT, "residential")
    assert day >= 10 and 0.1 < night < day / 15  # occasional cars remain plausible


def test_a_suburb_at_rush_hour_and_late_at_night():
    rush, _ = mean_moving(SUBURB, 225, 225, WEEKDAY_RUSH, "residential")
    late, _ = mean_moving(SUBURB, 225, 225, LATE_EVENING, "residential")
    assert rush > 3 * late > 0


def test_a_village_after_midnight_is_mostly_quiet():
    night, _ = mean_moving(VILLAGE, 80, 80, OCTOBER_NIGHT, "residential")
    assert night < 0.05


def test_a_remote_sysma_road_at_one_in_october_has_hardly_any_traffic():
    """Regression: cars kept appearing on a remote Sysmä road at 01:00."""
    night, manager = mean_moving(REMOTE, 10, 0, OCTOBER_NIGHT, "tertiary", city_target=15)
    # under about one minute in 35 has a moving car wanted: measured rural roads keep ~4 % of their
    # peak at 01:00 (assets/traffic/lam_profiles.json), the old estimate 2.5 %
    assert night < 0.03
    reasons = manager.population_diagnostics["traffic_demand"]
    assert reasons["hour"] < 0.05 and reasons["people"] < 10  # why: night, nobody around
    day, _ = mean_moving(REMOTE, 10, 0, OCTOBER_DAY, "tertiary", city_target=15)
    assert day > 10 * night and day > 0.2  # the same road by day: occasional cars


def test_summer_cottages_bring_traffic_only_in_summer():
    july, _ = mean_moving(CABINS, 100, 100, JULY_DAY, "unclassified")
    october, _ = mean_moving(CABINS, 100, 100, OCTOBER_DAY, "unclassified")
    assert july > 3 * october


def test_a_main_road_through_an_empty_municipality_keeps_passing_traffic():
    trunk, _ = mean_moving(REMOTE, 10, 0, OCTOBER_DAY, "trunk", city_target=15)
    local, _ = mean_moving(REMOTE, 10, 0, OCTOBER_DAY, "unclassified", city_target=15)
    night, _ = mean_moving(REMOTE, 10, 0, OCTOBER_NIGHT, "trunk", city_target=15)
    assert trunk > 5 * local and trunk > 10 * night > 0


def test_the_moving_target_is_not_a_minimum():
    """No traffic is replaced to keep a count: the target is 0 for most of
    a remote night, so no passing car is spawned in those minutes."""
    manager = NPCVehicleManager(target_count=15)
    manager.demand_rng.seed(1)
    manager.clock = OCTOBER_NIGHT
    zeros = 0
    for _ in range(500):
        manager._population_tick_number += NPC_DEMAND_ROLL_TICKS
        manager.set_local_density(10, 0, REMOTE)
        zeros += manager.target_moving_count == 0
    assert zeros > 490


def test_free_days_follow_the_finnish_calendar():
    assert is_public_holiday(datetime(2026, 12, 6)) and is_public_holiday(datetime(2026, 6, 19))  # Midsummer Eve (Fri)
    assert not is_public_holiday(datetime(2026, 6, 18))
    assert hour_demand(datetime(2026, 12, 7, 8)) > 2 * hour_demand(datetime(2026, 12, 6, 8))  # Monday vs Independence Day


def test_demand_follows_the_measured_lam_curves_urban_and_rural():
    """docs/lam-traffic-audit.md: weekday peak at 15 (not the estimate's 16), a
    rural weekend busier than an urban one, rural July above urban July."""
    from theroadragetrip import population

    assert population.MEASURED_CURVES is not None
    weekday, saturday = datetime(2026, 10, 14, 15), datetime(2026, 10, 17, 15)
    assert hour_demand(weekday) > hour_demand(weekday.replace(hour=16)) > hour_demand(weekday.replace(hour=7))
    assert hour_demand(saturday, urban=0.0) > hour_demand(saturday, urban=1.0)
    july, january = datetime(2026, 7, 15, 15), datetime(2026, 1, 14, 15)
    assert hour_demand(july, urban=0.0) > hour_demand(january, urban=0.0) and hour_demand(july) < hour_demand(january)
    half = hour_demand(saturday, urban=0.5)
    assert half == pytest.approx((hour_demand(saturday, urban=0.0) + hour_demand(saturday, urban=1.0)) / 2)


def test_without_the_measured_file_the_estimates_stay(tmp_path, monkeypatch, caplog):
    from theroadragetrip import population

    (tmp_path / "broken.json").write_text("{not json")
    assert population.load_measured_curves(tmp_path / "broken.json") is None
    assert population.load_measured_curves(tmp_path / "missing.json") is None
    monkeypatch.setattr(population, "MEASURED_CURVES", None)
    moment = datetime(2026, 10, 14, 16)
    assert hour_demand(moment) == population.WEEKDAY_HOURLY[16] * population.MONTH_FACTOR[10]
