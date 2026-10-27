"""Motorcycles as seasonal NPC road traffic (docs/motorcycles.md)."""
import configparser
from datetime import date, datetime, timedelta

import pytest

from theroadragetrip import motorcycle_season, npc as npc_module
from theroadragetrip.motorcycle_season import MotorcycleSeason
from theroadragetrip.npc import NPCState, NPCVehicleManager, place_parked_npc, spawn_npc
from theroadragetrip.osm import Way
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld

SEASON = MotorcycleSeason()


def _days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def test_no_motorcycles_anywhere_in_the_winter_exclusion():
    for day in list(_days(date(2025, 11, 1), date(2026, 3, 31))) + list(_days(date(2027, 11, 1), date(2028, 3, 31))):
        assert SEASON.factor(day) == 0.0, day  # 2028: a leap February too


def test_spring_rises_summer_peaks_autumn_falls():
    spring = [SEASON.factor(d) for d in _days(date(2026, 4, 1), date(2026, 5, 31))]
    summer = [SEASON.factor(d) for d in _days(date(2026, 6, 1), date(2026, 8, 31))]
    autumn = [SEASON.factor(d) for d in _days(date(2026, 9, 1), date(2026, 10, 31))]
    assert all(a < b for a, b in zip(spring, spring[1:]))  # gradually, day by day
    assert spring[0] < 0.5 * spring[-1]  # early spring: far fewer than late spring
    assert set(summer) == {max(spring + summer + autumn)}  # the peak, all summer
    assert all(a > b for a, b in zip(autumn, autumn[1:]))
    assert autumn[0] > 0.9 and autumn[-1] < 0.25 * summer[0]  # early autumn still busy, late autumn sparse
    # No jump but at the winter boundary: neighbouring days stay close.
    year = [SEASON.factor(d) for d in _days(date(2026, 4, 1), date(2026, 10, 31))]
    assert max(abs(a - b) for a, b in zip(year, year[1:])) < 0.05


def test_config_sets_the_dates_and_multipliers_and_rejects_nonsense():
    config = configparser.ConfigParser()
    config.read_dict({"motorcycles": {"season_start": "04-15", "summer_start": "06-15", "autumn_start": "08-20",
                                      "winter_start": "10-20", "spring_multiplier": "0.2", "summer_multiplier": "0.8",
                                      "autumn_multiplier": "0.05"}})
    season = motorcycle_season.from_config(config)
    assert season.factor(date(2026, 4, 14)) == 0.0 and season.factor(date(2026, 4, 15)) == pytest.approx(0.2)
    assert season.factor(date(2026, 7, 1)) == pytest.approx(0.8)
    assert season.factor(date(2026, 10, 20)) == 0.0
    config["motorcycles"]["summer_start"] = "03-01"  # before the season starts
    assert motorcycle_season.from_config(config) == MotorcycleSeason()
    assert motorcycle_season.from_config(None) == MotorcycleSeason()


def _manager_at(moment):
    manager = NPCVehicleManager(target_count=0, min_count=0, max_count=0)
    manager.clock = moment
    manager._update_motorcycle_season(ResidentManager())
    return manager


def test_the_game_date_decides_not_the_host_date():
    # Whatever today is on this machine, the game clock alone sets the factor.
    assert _manager_at(datetime(2026, 1, 15, 12)).motorcycle_factor == 0.0
    assert _manager_at(datetime(2026, 7, 15, 12)).motorcycle_factor == 1.0
    assert _manager_at(None).motorcycle_factor == 0.0  # no game date yet (loading): none rather than a guess


def _weights(manager, monkeypatch):
    seen = {}
    monkeypatch.setattr(npc_module.random, "choices", lambda ids, weights, k: seen.update(zip(ids, weights)) or [ids[0]])
    manager._pick_vehicle_type()
    return seen


def test_the_season_changes_the_motorcycle_weight_only(monkeypatch):
    winter = _weights(_manager_at(datetime(2026, 1, 15, 12)), monkeypatch)
    summer = _weights(_manager_at(datetime(2026, 7, 15, 12)), monkeypatch)
    assert winter["motorcycle"] == 0.0 and summer["motorcycle"] > 0.0
    assert {k: v for k, v in winter.items() if k != "motorcycle"} == {k: v for k, v in summer.items() if k != "motorcycle"}
    assert "bicycle" not in summer  # cyclists have their own demand


def test_crossing_into_winter_retires_every_motorcycle_and_spawns_none(monkeypatch):
    residents = ResidentManager()
    manager = _manager_at(datetime(2026, 10, 31, 23, 59))
    bikes = [place_parked_npc(i, (i * 10.0, 0.0), None, vehicle_type="motorcycle") for i in range(1, 4)]
    car = place_parked_npc(9, (100.0, 0.0), None, vehicle_type="car")
    manager.vehicles.extend(bikes + [car])
    manager._update_motorcycle_season(residents)
    assert manager.motorcycle_factor > 0.0 and len(manager.vehicles) == 4  # still autumn
    manager.clock = datetime(2026, 11, 1, 0, 0)
    manager._update_motorcycle_season(residents)
    assert manager.vehicles == [car]
    assert manager.population_diagnostics["motorcycles_retired_for_winter"] == 3
    monkeypatch.setattr(npc_module.random, "choices", lambda ids, weights, k: [ids[max(range(len(ids)), key=weights.__getitem__)]])
    assert all(manager._pick_vehicle_type() != "motorcycle" for _ in range(20))
    manager.clock = datetime(2027, 4, 1, 8, 0)  # spring again
    manager._update_motorcycle_season(residents)
    assert manager.motorcycle_factor == pytest.approx(SEASON.spring_multiplier)


def _road():
    return [Way(points_m=[(x, 0), (x + 40, 0)], highway="residential", half_width_m=4.5) for x in range(0, 400, 40)]


def test_a_motorcycle_drives_its_route_like_other_road_traffic():
    ways, residents = _road(), ResidentManager()
    world = TrafficWorld(ways)
    manager = NPCVehicleManager(target_count=0, min_count=0, max_count=0)
    manager._population_elapsed = -1e9  # no population ticks: only this vehicle
    manager.clock = datetime(2026, 7, 1, 12)
    spawned = spawn_npc(1, residents, world, ways, (40, 0), (360, 0), vehicle_type="motorcycle")
    assert spawned is not None
    _, driver, bike = spawned
    manager.vehicles.append(bike)
    manager.drivers[bike.vehicle_id] = driver
    start = bike.x
    for _ in range(300):
        manager.update(1 / 30, 200.0, 0.0, residents, world, ways)
    assert bike.vehicle_type == "motorcycle" and bike.x > start + 30.0
    assert abs(bike.y) < 4.5  # on the road


def test_a_motorcycle_collides_by_its_own_small_footprint():
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=2)
    pedestrians = PedestrianManager([], target_count=0)
    bike = place_parked_npc(1, (0.0, 0.0), None, vehicle_type="motorcycle")
    beside = place_parked_npc(2, (0.0, 1.6), None, vehicle_type="car")  # a car's width away: clear of a bike
    touching = place_parked_npc(3, (2.0, 0.0), None, vehicle_type="car")  # its rear overlaps the bike's front
    for vehicle in (bike, beside, touching):
        rider = residents.create(mode="driving")
        vehicle.owner_id, rider.active_vehicle_id = rider.resident_id, vehicle.vehicle_id
    manager.vehicles.extend([bike, beside, touching])
    manager._check_vehicle_collision(bike, [beside], residents, pedestrians, sim_time=10.0)
    assert bike.state != NPCState.CRASHED and beside.state != NPCState.CRASHED
    manager._check_vehicle_collision(bike, [touching], residents, pedestrians, sim_time=10.0)
    assert bike.state == NPCState.CRASHED and touching.state == NPCState.CRASHED
