"""Competitor taxis (docs/competitor-taxis.md): they take the player's phone
fares and drive them through the NPC system."""
import math
import random
from types import SimpleNamespace

import pytest

from theroadragetrip.competitor_taxis import (
    CLAIM_RADIUS_M, MAX_ROUTE_ATTEMPTS, STOP_DWELL_S, Dispatcher, TaxiJob, is_competitor, make_competitor,
)
from theroadragetrip.npc import NPCState, NPCVehicleManager, PathPoint, place_parked_npc, spawn_npc
from theroadragetrip.osm import Way
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_world import TrafficWorld


def test_a_job_drives_to_the_pickup_waits_then_to_the_dropoff_and_ends():
    job = TaxiJob("Aino", (0.0, 0.0), (500.0, 0.0))
    assert (job.leg, job.state, job.target) == ("pickup", "await_departure", (0.0, 0.0))
    job.departing()
    assert not job.at_stop(10.0) and job.state == "stopped"  # arrived: the passenger boards
    assert not job.at_stop(10.0 + STOP_DWELL_S - 0.1) and job.leg == "pickup"
    assert not job.at_stop(10.0 + STOP_DWELL_S)
    assert (job.leg, job.state, job.target) == ("dropoff", "await_departure", (500.0, 0.0)) and job.passenger_aboard
    job.departing()
    assert not job.at_stop(100.0)
    assert job.at_stop(100.0 + STOP_DWELL_S)  # the passenger has left: done


def test_a_leg_that_cannot_be_routed_is_given_up():
    job = TaxiJob("Aino", (0.0, 0.0), (500.0, 0.0))
    assert [job.route_failed() for _ in range(MAX_ROUTE_ATTEMPTS)][-1] and not any(
        [TaxiJob("x", (0, 0), (1, 1)).route_failed() for _ in range(MAX_ROUTE_ATTEMPTS - 1)])


def _taxi(vehicle_id, x, y, state=NPCState.PARKED):
    vehicle = SimpleNamespace(vehicle_id=vehicle_id, x=x, y=y, state=state, taxi_job=None,
                              vehicle_kind="car", is_taxi=False, color=(0, 0, 0))
    make_competitor(vehicle)
    return vehicle


def _offer(name, x, y):
    target = SimpleNamespace(x=x, y=y)
    return SimpleNamespace(passenger=SimpleNamespace(name=name, pickup=target, dropoff=SimpleNamespace(x=x + 900, y=y)))


def test_an_idle_competitor_near_a_fare_takes_it_off_the_players_phone():
    near, far = _taxi(1, 100.0, 0.0), _taxi(2, CLAIM_RADIUS_M * 3, 0.0)
    busy = _taxi(3, 10.0, 0.0)
    busy.taxi_job = TaxiJob("Other", (0, 0), (1, 1))
    phone = SimpleNamespace(offers=[_offer("Aino", 0.0, 0.0), _offer("Ville", CLAIM_RADIUS_M * 6, 0.0)],
                            language="en", notification_msg="", notification_timer=0.0)
    npcs = SimpleNamespace(vehicles=[near, far, busy], drivers={1: object(), 2: object(), 3: object()})
    dispatcher = Dispatcher(rng=random.Random(1))
    for _ in range(600):  # 10 min of dispatch checks
        dispatcher.update(phone, npcs, 1.0)
    assert [o.passenger.name for o in phone.offers] == ["Ville"]  # no competitor near that one
    assert near.taxi_job is not None and near.taxi_job.passenger_name == "Aino" and near.taxi_job.pickup == (0.0, 0.0)
    assert far.taxi_job is None and busy.taxi_job.passenger_name == "Other"
    assert "Aino" in phone.notification_msg and dispatcher.taken == 1


def test_offers_stay_on_the_phone_a_while():
    phone = SimpleNamespace(offers=[_offer(f"P{i}", 0.0, 0.0) for i in range(40)], language="fi",
                            notification_msg="", notification_timer=0.0)
    npcs = SimpleNamespace(vehicles=[_taxi(i, 50.0, 0.0) for i in range(40)], drivers={i: object() for i in range(40)})
    Dispatcher(rng=random.Random(2)).update(phone, npcs, 1.0)
    assert len(phone.offers) >= 35  # a second's chance each: most fares are still there


def _city_block_grid(blocks=8, step=60.0):
    ways = []
    for row in range(blocks):
        for i in range(blocks - 1):
            ways.append(Way(points_m=[(i * step, row * step), ((i + 1) * step, row * step)], highway="residential", half_width_m=4.5))
    for col in range(blocks):
        for i in range(blocks - 1):
            ways.append(Way(points_m=[(col * step, i * step), (col * step, (i + 1) * step)], highway="residential", half_width_m=4.5))
    return ways


@pytest.mark.parametrize("kind", ["car", "van"])
def test_a_competitor_drives_a_fare_from_pickup_to_dropoff_on_real_roads(kind):
    random.seed(4)
    ways = _city_block_grid()
    traffic_world = TrafficWorld(ways)
    residents = ResidentManager()
    _, driver, taxi = spawn_npc(1, residents, traffic_world, ways, (30.0, 0.0), (90.0, 0.0), vehicle_type=kind)
    taxi.state = NPCState.PARKED  # waiting for a fare at the roadside
    make_competitor(taxi)
    manager = NPCVehicleManager(target_count=1, spawn_radius_m=300.0, vehicle_distribution={"car": 1.0})
    manager.competitor_taxis = 0  # just this one
    manager.vehicles.append(taxi)
    manager.drivers[taxi.vehicle_id] = driver
    pickup, dropoff = (300.0, 240.0), (60.0, 420.0)
    taxi.taxi_job = job = TaxiJob("Aino", pickup, dropoff)
    stops, aboard_the_whole_time = [], True
    for _ in range(30 * 60 * 6):  # up to 6 minutes
        traffic_world.advance_time(1.0 / 30.0)  # (the simulation keeps this clock)
        manager.update(1.0 / 30.0, 210.0, 210.0, residents, traffic_world, ways)
        aboard_the_whole_time &= manager.drivers.get(taxi.vehicle_id) is not None
        if job.state == "stopped" and (not stops or stops[-1][0] != job.leg):
            stops.append((job.leg, (taxi.x, taxi.y)))
        if taxi.taxi_job is None or taxi.state == NPCState.CRASHED:
            break
    assert taxi.state != NPCState.CRASHED
    assert taxi.taxi_job is None, f"the fare was not finished: {job}"  # driven to the end
    assert [leg for leg, _ in stops] == ["pickup", "dropoff"]
    for leg, (x, y) in stops:  # stopped near each, the driver at the wheel all along
        target = pickup if leg == "pickup" else dropoff
        assert math.hypot(x - target[0], y - target[1]) < 80.0, (leg, x, y)
    assert aboard_the_whole_time and is_competitor(taxi) and taxi.is_taxi


@pytest.mark.parametrize("kind", ["car", "van", "truck", "bus"])
def test_transit_taxi_selection_preserves_paint_dimensions_and_seats(kind):
    from theroadragetrip.protocol import _npc_to_dict
    from theroadragetrip.vehicles import vehicle_definition

    road = Way(points_m=[(-100, 0), (200, 0)], highway="residential", half_width_m=5)
    paint = (35, 70, 45)
    vehicle = place_parked_npc(1, (0, -2.5), None, ways=[road], vehicle_type=kind, color=paint)
    assert vehicle is not None
    residents = ResidentManager()
    manager = NPCVehicleManager(target_count=1)
    path = [PathPoint(0, -2.5, road), PathPoint(80, -2.5, road)]
    assert manager._apply_transit_spawn((vehicle, (path, (80, -2.5), None, False)), residents, []) is not None
    assert is_competitor(vehicle) == (kind in ("car", "van"))
    definition = vehicle_definition(kind)
    assert vehicle.color == paint
    seats = 9 if kind == "van" else definition.capacity
    assert (vehicle.length_m, vehicle.width_m, vehicle.capacity) == (definition.length_m, definition.width_m, seats)
    assert len(vehicle.trip_group.member_resident_ids) <= vehicle.capacity
    published = _npc_to_dict(vehicle, residents.residents)
    assert published["color"] == list(paint) and published["vehicle_type"] == kind
    assert published["is_taxi"] == (kind in ("car", "van"))


def test_taxi_van_seats_eight_passengers_plus_driver_and_rejects_extra_occupants():
    from theroadragetrip.npc import _begin_trip_on_vehicle
    from theroadragetrip.vehicles import vehicle_definition

    road = Way(points_m=[(-100, 0), (200, 0)], highway="residential", half_width_m=5)
    vehicle = place_parked_npc(1, (0, -2.5), None, ways=[road], vehicle_type="van")
    ordinary_capacity = vehicle.capacity
    make_competitor(vehicle)
    assert vehicle.capacity - 1 == 8
    assert vehicle_definition("van").capacity == ordinary_capacity  # ordinary vans are unchanged
    residents = ResidentManager()
    members = [residents.create().resident_id for _ in range(10)]
    path = [PathPoint(0, -2.5, road), PathPoint(80, -2.5, road)]
    _begin_trip_on_vehicle(vehicle, path, residents, (80, -2.5), member_resident_ids=members)
    assert len(vehicle.trip_group.member_resident_ids) == 9
    assert members[-1] not in vehicle.trip_group.member_resident_ids


def test_competitor_taxis_keep_the_existing_colour_variation():
    from theroadragetrip.npc import NPC_VEHICLE_COLORS

    for paint in NPC_VEHICLE_COLORS:
        vehicle = SimpleNamespace(color=paint)
        make_competitor(vehicle)
        assert vehicle.color == paint and vehicle.is_taxi
