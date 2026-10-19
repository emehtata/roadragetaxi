"""Weekend cruising is ordinary traffic, not just more rival taxis."""
from datetime import datetime
import math
import random

import pytest

from theroadragetrip.npc import NPCState, NPCVehicleManager, PathPoint, place_parked_npc
from theroadragetrip.osm import Way
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.physics import SpatialWayGrid
from theroadragetrip.population import traffic_demand
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld


@pytest.mark.parametrize("day,hour,active", [(16, 17, False), (16, 18, True), (17, 3, True),
                                          (17, 23, True), (18, 4, True), (18, 5, False), (19, 1, False)])
def test_nightlife_window_follows_friday_and_saturday_nights(day, hour, active):
    now = datetime(2026, 10, day, hour)
    assert traffic_demand(1.0, "residential", now)["nightlife"] == (0.5 if active else 0.0)
    assert traffic_demand(0.0, "residential", now)["demand"] == 0.0


def test_night_population_balances_young_adult_cars_and_taxis(monkeypatch):
    import theroadragetrip.npc as npc
    from theroadragetrip.protocol import _npc_to_dict

    monkeypatch.setattr(npc, "people_within", lambda *args: 1500)
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=40, max_count=40)
    manager.clock = datetime(2026, 10, 17, 3)
    manager.set_local_density(0, 0, SpatialWayGrid([]))
    assert manager.target_moving_count == 20
    assert manager._night_cruise_target == manager._night_taxi_target == 10
    road = Way(points_m=[(-100, 0), (200, 0)], highway="residential", half_width_m=5)
    for i in range(20):
        car = place_parked_npc(i, (0, -2.5), None, ways=[road])
        path = [PathPoint(0, -2.5, road), PathPoint(80, -2.5, road)]
        manager._apply_transit_spawn((car, (path, (80, -2.5), None, False)), residents, [])
    assert [v.is_taxi for v in manager.vehicles[:4]] == [True, False, True, False]
    cruisers = [v for v in manager.vehicles if v.vehicle_kind == "night_cruise"]
    assert len(cruisers) == 10 and sum(v.is_taxi for v in manager.vehicles) == 10
    for car in cruisers:
        row = _npc_to_dict(car, residents.residents)
        assert row["vehicle_type"] == "car" and not row["is_taxi"] and not row["is_police"]
        assert all(18 <= residents.age_of(residents.get(rid)) <= 29 for rid in car.trip_group.member_resident_ids)
    manager.max_count = 8
    manager.set_local_density(0, 0, SpatialWayGrid([]))
    assert manager._night_cruise_target + manager._night_taxi_target <= manager.max_count
    assert manager.target_moving_count <= manager.max_count


def test_cruising_group_stays_aboard_and_drives_another_real_trip(monkeypatch):
    import theroadragetrip.npc as npc

    random.seed(4)
    monkeypatch.setattr(npc, "people_within", lambda *args: 1500)
    ways = []
    for row in range(8):
        for col in range(7):
            ways.append(Way(points_m=[(col*60, row*60), ((col+1)*60, row*60)], highway="residential", half_width_m=4.5))
            ways.append(Way(points_m=[(row*60, col*60), (row*60, (col+1)*60)], highway="residential", half_width_m=4.5))
    traffic, residents = TrafficWorld(ways), ResidentManager()
    manager = NPCVehicleManager(target_count=4, max_count=4, vehicle_distribution={"car": 1.0})
    manager.competitor_taxis = 0
    manager.clock = datetime(2026, 10, 17, 3)
    buildings = SpatialWayGrid([])
    manager.set_local_density(210, 210, buildings)
    road = ways[0]
    car = place_parked_npc(manager._next_id(), (30, -2), None, ways=ways)
    path = [PathPoint(30, -2, road), PathPoint(50, -2, road)]
    driver = manager._apply_transit_spawn((car, (path, (50, -2), None, False)), residents, [])
    assert car.vehicle_kind == "night_cruise"
    car.state = NPCState.PARKED
    pedestrians = PedestrianManager(ways, target_count=0, residents=residents, traffic_vehicles=manager.vehicles)
    pedestrians.entrance_locations = [(30, -10)]
    pedestrians._materialize_parked_drivers()
    assert not pedestrians.pedestrians and car.trip_group.all_aboard
    start = (car.x, car.y)
    for _ in range(30*90):
        traffic.advance_time(1/30)
        manager.update(1/30, 210, 210, residents, traffic, ways, building_grid=buildings)
        if math.hypot(car.x-start[0], car.y-start[1]) > 15:
            break
    assert car.state != NPCState.CRASHED and math.hypot(car.x-start[0], car.y-start[1]) > 15
    assert manager.drivers[car.vehicle_id] is driver and car.trip_group.all_aboard
    manager.clock = datetime(2026, 10, 19, 3)
    manager.set_local_density(210, 210, buildings)
    car.state = NPCState.PARKED
    manager._handle_parked_vehicle(car, residents, traffic.sim_time)
    assert car.vehicle_kind == "traffic"
