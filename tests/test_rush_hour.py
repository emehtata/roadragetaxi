"""rrt-019-rush-hour: the moving-traffic target follows the roads around the taxi
and the hour (LAM curves), and the actual moving cars converge towards it."""
import random
from datetime import datetime

import pytest

from theroadragetrip.npc import NPCState, NPCVehicleManager
from theroadragetrip.population import CLASS_DENSITIES
from theroadragetrip.osm import Way
from theroadragetrip.physics import SpatialWayGrid
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld


def _city_grid(blocks: int = 6, block_m: float = 100.0):
    """A dense centre: a two-way grid of residential streets, a secondary through-road."""
    ways, size = [], blocks * block_m
    for i in range(blocks + 1):
        c = i * block_m - size / 2
        highway = "secondary" if i == blocks // 2 else "residential"
        for k in range(blocks):
            a, b = k * block_m - size / 2, (k + 1) * block_m - size / 2
            ways.append(Way(points_m=[(a, c), (b, c)], highway=highway, half_width_m=5.0))
            ways.append(Way(points_m=[(c, a), (c, b)], highway="residential", half_width_m=5.0))
    return ways


def _manager(moment, ways, people=1500.0):
    """A town centre's people (urban densities and curves) unless `people` says otherwise."""
    manager = NPCVehicleManager(target_count=60, max_count=120, vehicle_distribution={"car": 1.0})
    manager.clock = moment
    manager.set_local_density(0.0, 0.0, SpatialWayGrid([]), road_grid=SpatialWayGrid(ways))
    manager._local_people = people  # no buildings in the synthetic grid; the cell is counted already
    manager.set_local_density(0.0, 0.0, SpatialWayGrid([]), road_grid=SpatialWayGrid(ways))
    return manager


@pytest.mark.parametrize("moment,low,high", [
    (datetime(2026, 10, 14, 7, 30), 0.4, 1.1),  # Wednesday morning rush
    (datetime(2026, 10, 14, 16, 0), 0.7, 1.1),  # Wednesday afternoon peak
    (datetime(2026, 10, 14, 23, 30), 0.03, 0.3),  # late evening
    (datetime(2026, 10, 15, 1, 0), 0.0, 0.1),  # Thursday night, October
])
def test_the_moving_target_is_the_roads_peak_cars_at_the_hours_share(moment, low, high):
    ways = _city_grid()
    manager = _manager(moment, ways)
    roads_km = {"residential": 0.0, "secondary": 0.0}
    for way in ways:
        (ax, ay), (bx, by) = way.points_m
        if ((ax + bx) / 2) ** 2 + ((ay + by) / 2) ** 2 <= 250.0 ** 2:
            roads_km[way.highway] += 0.1
    peak = sum(km * CLASS_DENSITIES["urban"][h] for h, km in roads_km.items())  # LAM-measured, side streets estimated
    assert low * peak <= manager.target_moving_count <= high * peak + 1


def test_a_weekday_afternoon_wants_far_more_cars_than_the_night():
    ways = _city_grid()
    afternoon = _manager(datetime(2026, 10, 14, 16, 0), ways).target_moving_count
    night = _manager(datetime(2026, 10, 15, 1, 0), ways).target_moving_count
    assert afternoon >= 10 * max(1, night)


def test_friday_night_keeps_its_nightlife_on_top_of_the_roads():
    ways = _city_grid()
    friday = _manager(datetime(2026, 10, 16, 23, 0), ways)
    wednesday = _manager(datetime(2026, 10, 14, 23, 0), ways)
    assert friday.target_moving_count >= wednesday.target_moving_count


def test_afternoon_traffic_converges_on_a_dense_grid():
    """Wednesday 16:00 in a dense grid: from no traffic, within a simulated
    minute, most of the target is driving (not parked, not crashed)."""
    random.seed(7)
    ways = _city_grid()
    world, residents = TrafficWorld(ways), ResidentManager()
    manager = _manager(datetime(2026, 10, 14, 16, 0), ways)
    target = manager.target_moving_count
    bounds = (-300.0, -300.0, 300.0, 300.0)
    for _ in range(60 * 30):
        world.advance_time(1 / 30)
        manager.update(1 / 30, 0.0, 0.0, residents, world, ways, spatial_grid=SpatialWayGrid(ways),
                       building_grid=SpatialWayGrid([]), active_bounds=bounds)
    moving = sum(1 for v in manager.vehicles if v.state not in (NPCState.PARKED, NPCState.CRASHED))
    assert target >= 5 and moving >= 0.6 * target
    spawn = manager.population_diagnostics["spawn"]
    assert spawn["activated"] > 0 and spawn["moving_after_10s"] >= spawn["stopped_after_10s"]


def test_a_rural_road_carries_far_less_than_the_same_road_in_town():
    ways = _city_grid()
    town = _manager(datetime(2026, 10, 14, 16, 0), ways).target_moving_count
    country = _manager(datetime(2026, 10, 14, 16, 0), ways, people=0.0).target_moving_count
    assert country * 3 <= town
