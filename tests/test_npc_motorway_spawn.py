"""Do not seed a taxi sideways on a motorway with an off-road connector."""
import math
import random

import pytest

from theroadragetrip.npc import NPCVehicleManager, PathPoint, _transit_initial_speed, place_parked_npc
from theroadragetrip.osm import Way
from theroadragetrip.physics import SpatialWayGrid
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld, run_route_steps


@pytest.mark.parametrize('indexed', [False, True])
@pytest.mark.parametrize('angle', [0, math.pi / 2, math.pi, 3 * math.pi / 2])
def test_transit_rejects_disconnected_service_road_across_motorway(indexed, angle):
    # Pohjantie screenshot 1792607591798546176: motorway to an isolated
    # service road 128 m away. A* permits endpoint connectors across the gap.
    def point(x, y):
        return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)

    ways = [
        Way([point(0, -350), point(0, 0), point(0, 350)], 'motorway', 7, oneway=1, speed_limit_kmh=100),
        Way([point(128, -100), point(128, 0), point(128, 100)], 'service', 3),
    ]
    world = TrafficWorld(ways)
    grid = SpatialWayGrid(ways) if indexed else None
    manager = NPCVehicleManager(target_count=1)
    vehicle = place_parked_npc(1, point(0, 0), None)
    random.seed(4)
    plan = run_route_steps(manager._short_transit_trip_steps(
        vehicle, point(0, 0), ResidentManager(), world, ways, grid,
        None, None, None, None, None, None, [],
    ))
    assert plan is None
    assert not manager.vehicles and not manager.drivers


def test_transit_rejects_start_without_identified_road():
    vehicle = place_parked_npc(1, (0, 0), None)
    plan = ([PathPoint(0, 0), PathPoint(128, 0)], (128, 0), None, True)
    assert _transit_initial_speed(vehicle, plan) is None
    manager = NPCVehicleManager(target_count=1)
    assert manager._apply_transit_spawn((vehicle, plan), ResidentManager(), []) is None
    assert not manager.vehicles and not manager.drivers
