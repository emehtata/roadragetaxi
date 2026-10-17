"""Bounded long runs (rrt-018-testing phase 8): many game hours of the
real server, and many minutes of NPC traffic and pedestrians, checking
invariants every tick. RRT_SOAK_SCALE (default 1) multiplies their length
for a scheduled or pre-release run (TESTING.md)."""
import gc
import os
import random
import sys
import time
from datetime import timedelta

import pytest

SCALE = float(os.environ.get("RRT_SOAK_SCALE", "1"))


def test_the_server_runs_through_midnight_and_every_state_parses(monkeypatch):
    """The sample world from 18:00 past midnight (the idle game clock runs
    60x): the clock only moves forward, the date turns once, and a real
    client decodes every state the server sends."""
    from theroadragetrip import transport
    from theroadragetrip.server import run_server
    from theroadragetrip.server.cli import parse_server_args

    monkeypatch.setattr(sys, "argv", ["prog", "--use-sample", "--no-menu", "--no-historical-weather"])
    args, config = parse_server_args()
    args.port = 0
    server = run_server(args, config)
    connection = transport.connect(server.host, server.port)
    time.sleep(0.05)
    start = server.calendar.current
    previous, states = start, 0
    ticks = int(4000 * SCALE)
    for tick in range(ticks):
        server.tick(0.1)
        now = server.calendar.current
        assert now >= previous, f"the clock went back at tick {tick}: {previous} -> {now}"
        previous = now
        if tick % 50 == 0:
            for message in connection.try_recv_all():  # decoded by the transport: a bad one closes it
                if message["type"] == "state":
                    states += 1
                    assert message["state"]["game_time_seconds"] >= 0
            assert not connection.is_closed, connection.error
    assert previous - start >= timedelta(hours=6) and previous.date() > start.date()
    assert states >= ticks // 100
    connection.close()


def _invariants(npcs, pedestrians, residents):
    vehicle_ids = [vehicle.vehicle_id for vehicle in npcs.vehicles]
    assert len(vehicle_ids) == len(set(vehicle_ids)), "a vehicle is listed twice"
    assert set(npcs.drivers) <= set(vehicle_ids), "a driver without its vehicle"
    walker_ids = [ped.resident_id for ped in pedestrians.pedestrians if ped.resident_id is not None]
    assert len(walker_ids) == len(set(walker_ids)), "one resident walking twice"
    for resident_id in walker_ids:
        assert residents.get(resident_id) is not None, "a walker without a resident"
    for vehicle in npcs.vehicles:
        if vehicle.trip_group is not None:
            for resident_id in vehicle.trip_group.member_resident_ids:
                assert residents.get(resident_id) is not None, "a trip with a missing resident"


@pytest.mark.parametrize("seed", range(1, 1 + max(1, int(SCALE))))
def test_city_traffic_and_walkers_stay_consistent_for_minutes(seed):
    """Ten NPC cars and walkers on a 9 x 9 block grid for minutes of game
    time: no duplicate or orphaned vehicle, driver, walker or resident,
    counts stay within their targets, nothing grows without bound."""
    sys.path.insert(0, os.path.dirname(__file__))
    from test_npc_population import _CENTER, _SPAWN_RADIUS_M, _city_block_grid
    from theroadragetrip.npc import NPCVehicleManager
    from theroadragetrip.pedestrian import PedestrianManager
    from theroadragetrip.physics import Car
    from theroadragetrip.residents import ResidentManager
    from theroadragetrip.traffic_world import TrafficWorld

    random.seed(seed)
    ways = _city_block_grid()
    footways = [type(way)(points_m=way.points_m, highway="footway", half_width_m=1.5) for way in ways[::3]]
    traffic, residents = TrafficWorld(ways), ResidentManager()
    npcs = NPCVehicleManager(target_count=10, spawn_radius_m=_SPAWN_RADIUS_M, vehicle_distribution={"car": 1.0})
    pedestrians = PedestrianManager(ways + footways, target_count=10, traffic_manager=traffic, residents=residents)
    px, py = _CENTER
    player = Car(px, py, 0, 0)
    npcs.populate_initial(px, py, residents, ways)
    traffic.npcs = npcs.vehicles
    ticks = int(3000 * SCALE)
    half_objects = None
    peak_vehicles = peak_walkers = 0
    for tick in range(ticks):
        traffic.advance_time(1 / 30)
        npcs.update(1 / 30, px, py, residents, traffic, ways, pedestrian_mgr=pedestrians)
        pedestrians.update(player, dt=1 / 30)
        _invariants(npcs, pedestrians, residents)
        peak_vehicles = max(peak_vehicles, len(npcs.vehicles))
        peak_walkers = max(peak_walkers, len(pedestrians.pedestrians))
        if tick == ticks // 2:
            gc.collect()
            half_objects = len(gc.get_objects())
    gc.collect()
    end_objects = len(gc.get_objects())
    assert npcs.vehicles, "the traffic died out"
    assert peak_walkers >= 10, "too few walkers for this to test them"
    assert peak_vehicles <= npcs.max_count
    assert peak_walkers <= pedestrians.population_target + 20
    assert len(residents.residents) < 400, "residents pile up"
    # The second half runs in a settled state: live objects must not keep growing.
    assert end_objects < half_objects * 1.2, (half_objects, end_objects)
