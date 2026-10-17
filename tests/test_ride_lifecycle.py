"""Taxi ride lifecycle and passenger identity, across whole rides and
from one ride to the next (rrt-018-testing, phases 3-4).

Valid states: PICKUP -> WALKING -> DROPOFF -> (fare paid, no passenger).
After a fare the state stays DROPOFF with no passenger until the next
offer is accepted; nothing is charged or paid in that interval."""
import random

import pytest

from theroadragetrip.osm import Way
from theroadragetrip.physics import Car
from theroadragetrip.residents import ResidentManager
from theroadragetrip.taxi import TaxiManager, TaxiState


def make_taxi(seed=3):
    random.seed(seed)
    ways = [
        Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=4.5, name="Torikatu"),
        Way(points_m=[(500.0, 0.0), (600.0, 0.0)], highway="primary", half_width_m=6.0, name="Saaristonkatu"),
    ]
    residents = ResidentManager()
    taxi = TaxiManager(ways=ways, min_distance_m=100.0, max_distance_m=1000.0, pickup_radius_m=20.0,
                       max_stop_speed_mps=2.0, resident_manager=residents)
    return taxi, residents, Car(x=0.0, y=0.0, heading=0.0, speed=0.0)


def identity(passenger):
    return passenger.resident_id, passenger.name, passenger.gender


def drive_ride(taxi, car):
    """Pick up the current passenger and deliver them; return them."""
    passenger = taxi.current_passenger
    car.x, car.y, car.speed = passenger.pickup.x, passenger.pickup.y, 0.0
    for _ in range(60):
        taxi.update(car, dt=0.2)
        if taxi.state == TaxiState.DRIVING_TO_DROPOFF:
            break
    assert taxi.state == TaxiState.DRIVING_TO_DROPOFF and taxi.current_passenger is passenger
    car.odometer_m += 1000.0
    car.x, car.y = passenger.dropoff.x, passenger.dropoff.y
    taxi.update(car, dt=5.0)
    assert taxi.current_passenger is None
    return passenger


def test_the_passenger_is_the_same_person_from_pickup_to_drop_off():
    taxi, residents, car = make_taxi()
    taxi.spawn_mission(car.x, car.y)
    passenger = taxi.current_passenger
    before = identity(passenger)
    resident = residents.get(passenger.resident_id)
    assert resident is not None and before[1] == f"{resident.first_name} {resident.surname}"
    assert before[2] == {"female": "woman", "male": "man"}[resident.gender]
    drive_ride(taxi, car)
    assert identity(passenger) == before  # the finished ride leaves the passenger as they were


def test_a_fare_is_paid_once_and_the_next_ride_is_a_different_person():
    taxi, residents, car = make_taxi()
    taxi.spawn_mission(car.x, car.y)
    first = identity(drive_ride(taxi, car))
    paid = taxi.balance_cents
    assert taxi.completed_fares == 1 and paid == taxi.last_fare_cents + taxi.last_tip_cents > 0

    for _ in range(20):  # waiting at the drop-off: no second payment
        taxi.update(car, dt=1.0)
    assert taxi.completed_fares == 1 and taxi.balance_cents == paid

    taxi.offers.clear()
    taxi.spawn_mission(car.x, car.y)
    second_passenger = taxi.current_passenger
    assert second_passenger.resident_id != first[0]
    assert taxi.live_fare_cents == 0 or taxi.state == TaxiState.WAITING_FOR_PICKUP
    second = identity(drive_ride(taxi, car))
    assert second == identity(second_passenger) and second[0] != first[0]
    assert taxi.completed_fares == 2
    assert taxi.balance_cents == paid + taxi.last_fare_cents + taxi.last_tip_cents
    assert residents.get(first[0]) is not None and residents.get(second[0]) is not None


@pytest.mark.parametrize("stage", ["pickup", "onboard"])
def test_a_cancelled_ride_pays_nothing_and_leaves_no_passenger(stage):
    taxi, _, car = make_taxi()
    taxi.spawn_mission(car.x, car.y)
    passenger = taxi.current_passenger
    if stage == "onboard":
        car.x, car.y = passenger.pickup.x, passenger.pickup.y
        for _ in range(60):
            taxi.update(car, dt=0.2)
        assert taxi.state == TaxiState.DRIVING_TO_DROPOFF
    score = taxi.total_score
    assert taxi.discard_mission(car.x, car.y, penalty=150) == 150
    assert taxi.current_passenger is None and taxi.state == TaxiState.WAITING_FOR_PICKUP
    assert taxi.balance_cents == 0 and taxi.live_fare_cents == 0 and taxi.total_score == score - 150
    assert taxi.discard_mission(car.x, car.y) == 0  # a repeated cancel: nothing left to cancel, no penalty
    assert taxi.total_score == score - 150
    car.x, car.y = passenger.dropoff.x, passenger.dropoff.y
    taxi.update(car, dt=5.0)
    assert taxi.completed_fares == 0 and taxi.balance_cents == 0  # the cancelled drop-off pays nothing


def test_an_offer_cannot_be_accepted_during_a_ride():
    taxi, _, car = make_taxi()
    taxi.spawn_mission(car.x, car.y)
    passenger = taxi.current_passenger
    assert taxi.accept_offer(0, car.x, car.y) is False
    assert taxi.current_passenger is passenger


def test_random_driving_keeps_the_ride_state_consistent():
    """Seeded random driving, stopping, cancelling and new rides: states
    only move forward, payment only comes with a completed fare."""
    completed = cancelled = 0
    order = {TaxiState.WAITING_FOR_PICKUP: 0, TaxiState.CLIENT_WALKING_TO_CAR: 1, TaxiState.DRIVING_TO_DROPOFF: 2}
    for seed in range(5):
        taxi, _, car = make_taxi(seed)
        rng = random.Random(seed)
        rides = set()
        for _ in range(400):
            passenger, state, fares, balance = taxi.current_passenger, taxi.state, taxi.completed_fares, taxi.balance_cents
            action = rng.random()
            if passenger is None:
                taxi.offers.clear()
                taxi.spawn_mission(car.x, car.y)
                assert taxi.current_passenger.resident_id not in rides  # never the same ride twice
                rides.add(taxi.current_passenger.resident_id)
                continue
            if action < 0.05:
                taxi.discard_mission(car.x, car.y)
            else:
                target = rng.choice([passenger.pickup, passenger.dropoff, None])
                if target is not None:
                    car.x, car.y = target.x, target.y
                car.speed = rng.choice([0.0, 0.0, 8.0])
                car.odometer_m += rng.uniform(0.0, 50.0)
                taxi.update(car, dt=rng.choice([0.1, 0.5, 2.0]))
            if taxi.current_passenger is passenger:
                assert identity(taxi.current_passenger) == identity(passenger)
                assert order[taxi.state] >= order[state]  # no step backwards within a ride
                assert taxi.completed_fares == fares and taxi.balance_cents == balance
            elif taxi.completed_fares == fares + 1:
                assert state == TaxiState.DRIVING_TO_DROPOFF and taxi.balance_cents > balance
                completed += 1
            else:  # cancelled
                assert taxi.completed_fares == fares and taxi.balance_cents == balance
                cancelled += 1
    assert completed >= 20 and cancelled >= 5  # the walk really covers both endings


def test_a_dropped_off_passenger_walks_on_as_the_same_person():
    """Bug: a woman dropped off stepped out as a different man."""
    from types import SimpleNamespace

    from theroadragetrip.osm import Way
    from theroadragetrip.pedestrian import PedestrianManager
    from theroadragetrip.residents import ResidentManager
    from theroadragetrip.simulation import passenger_steps_out

    residents = ResidentManager()
    woman = residents.create("taxi")
    manager = PedestrianManager([Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)],
                                target_count=0, residents=residents)
    from theroadragetrip.taxi import TaxiPassenger
    passenger_steps_out(manager, TaxiPassenger("Test", None, None, resident_id=woman.resident_id), 50.0, 1.0, 0.0)
    assert [ped.resident_id for ped in manager.pedestrians] == [woman.resident_id]
