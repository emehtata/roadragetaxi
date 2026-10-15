"""Planning and publication must use the vehicle that will actually drive."""
import pytest

from theroadragetrip.npc import (
    NPCVehicleManager, PathPoint, _pick_npc_destination_candidates, _recover_npc_trip_steps,
    find_and_start_npc_trip, place_parked_npc, spawn_npc,
)
from theroadragetrip.osm import Curb, ParkingSpace, Way
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld, run_route_steps
from theroadragetrip.vehicles.base import vehicle_definition


def roads(width=4.5):
    return [Way(points_m=[(x, 0), (x + 40, 0)], highway="residential", half_width_m=width)
            for x in range(0, 400, 40)]


@pytest.mark.parametrize("kind", ["car", "van", "truck", "bus", "tractor"])
def test_direct_spawn_uses_plugin_dimensions_and_capacity(kind):
    ways, residents = roads(), ResidentManager()
    spawned = spawn_npc(1, residents, TrafficWorld(ways), ways, (40, 0), (200, 0), vehicle_type=kind)
    assert spawned is not None
    vehicle = spawned[2]
    definition = vehicle_definition(kind)
    assert (vehicle.length_m, vehicle.width_m, vehicle.capacity) == (
        definition.length_m, definition.width_m, definition.capacity,
    )
    assert 1 <= len(vehicle.trip_group.member_resident_ids) <= definition.capacity


def test_bus_cannot_spawn_on_car_sized_road():
    ways, residents = roads(1.1), ResidentManager()
    world = TrafficWorld(ways)
    assert spawn_npc(1, residents, world, ways, (40, 0), (200, 0)) is not None
    before = len(residents.residents)
    assert spawn_npc(2, residents, world, ways, (40, 0), (200, 0), vehicle_type="bus") is None
    assert len(residents.residents) == before


def test_bus_route_rejects_curb_that_car_body_clears():
    ways, residents = roads(), ResidentManager()
    world = TrafficWorld(ways)
    curb = Curb(points_m=[(0, -3.5), (400, -3.5)])
    assert spawn_npc(1, residents, world, ways, (40, 0), (200, 0), curbs=[curb]) is not None
    assert spawn_npc(2, residents, world, ways, (40, 0), (200, 0), curbs=[curb], vehicle_type="bus") is None


def test_car_bay_not_offered_to_bus():
    space = ParkingSpace(points_m=[(-1.5, -3), (1.5, -3), (1.5, 3), (-1.5, 3)],
                         bbox=(-1.5, -3, 1.5, 3))
    assert _pick_npc_destination_candidates(0, 0, parking_spaces=[space])
    assert not _pick_npc_destination_candidates(0, 0, parking_spaces=[space],
                                               vehicle_length_m=11, vehicle_width_m=2.5)
    assert place_parked_npc(1, (0, 0), space, vehicle_type="bus") is None
    assert not space.reserved and not space.occupied


def test_transit_rejects_offroad_planned_start_before_publication(monkeypatch):
    ways, residents = roads(), ResidentManager()
    world, manager = TrafficWorld(ways), NPCVehicleManager(target_count=1)
    attempts = []

    def bad_plan(*args, **kwargs):
        attempts.append(True)
        yield
        return ([PathPoint(120, 20, ways[0]), PathPoint(160, 20, ways[0])], (160, 20), None, True)

    monkeypatch.setattr(manager, "_short_transit_trip_steps", bad_plan)
    result = run_route_steps(manager._transit_spawn_steps(
        0, 0, residents, world, ways, None, None, None, None, None, None, None, None, [],
    ))
    assert attempts
    assert result is None
    assert not manager.vehicles and not manager.drivers and not residents.residents


def test_recovery_keeps_already_lane_positioned_origin():
    ways, residents = roads(), ResidentManager()
    world = TrafficWorld(ways)
    _, driver, vehicle = spawn_npc(1, residents, world, ways, (40, 0), (200, 0), vehicle_type="truck")
    plan = run_route_steps(_recover_npc_trip_steps(
        vehicle, driver, world, ways, None, None, None, None, None,
    ))
    assert plan is not None
    assert (plan[0][0].x, plan[0][0].y) == (vehicle.x, vehicle.y)


def test_parked_trip_starts_at_actual_position_without_lane_offset_snap():
    ways, residents = roads(), ResidentManager()
    world = TrafficWorld(ways)
    vehicle = place_parked_npc(1, (40, -5.9), None, ways=ways)
    origin = (vehicle.x, vehicle.y)
    driver = find_and_start_npc_trip(vehicle, residents, world, ways)
    assert driver is not None
    assert (vehicle.x, vehicle.y) == origin
    assert (driver.path[0].x, driver.path[0].y) == origin
