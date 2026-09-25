"""Trains phase 7: rail passengers wanting a taxi, and the existing taxi
stand nearest each station."""
from datetime import datetime
from types import SimpleNamespace

from theroadragetrip.osm.models import Railway, TaxiStop
from theroadragetrip.station_passengers import StationPassengerView
from theroadragetrip.train_passengers import ARRIVED, TAXI, TAXI_DEMAND_SHARE, WALK, PassengerFlow, RailPassenger
from theroadragetrip.trains import RailwayManager
from tests.test_station_passengers import FakePedestrians
from tests.test_train_passengers import NOON, aboard, fake_train


def metres(lat, lon):
    return lon * 100_000.0, lat * 100_000.0


LINE = [Railway(points_m=[(5.0, -5000.0), (5.0, 25_000.0)])]
STATIONS = {code: [lat, 0.00005, code] for code, lat in (("X", -0.3), ("A", 0.0), ("B", 0.08), ("Z", 0.5))}
JOURNEY = {
    "type": "IC", "number": "7", "category": "long_distance", "origin": "X", "destination": "Z", "days": 0b1111111,
    "stops": [[code, t, t + (120 if code in "AB" else 0), 1, ""] for code, t in (("X", 36000), ("A", 39000), ("B", 40000), ("Z", 45000))],
}


def manager_with(stands):
    manager = RailwayManager(LINE, {"version": 4, "stations": STATIONS, "trains": [JOURNEY]}, metres)
    manager.associate_taxi_stands(stands)
    return manager


def test_each_station_gets_its_nearest_existing_stand_and_none_are_created():
    # Station B is at (5, 8000): stands 500 m, 120 m and 300 m away.
    far, near, middle = TaxiStop(505.0, 8000.0, id=1), TaxiStop(5.0, 8120.0, id=2), TaxiStop(5.0, 7700.0, id=3)
    stands = [far, near, middle]
    manager = manager_with(stands)
    assert manager.station_stands["B"] is near
    assert stands == [far, near, middle] and len(stands) == 3  # the existing list, untouched
    assert all(stand in stands for stand in manager.station_stands.values())


def test_without_any_stand_stations_have_none_and_trains_still_carry_passengers():
    manager = manager_with([])
    assert manager.station_stands == {}
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 10, 51))
    assert manager.trains and aboard(manager.trains[0])
    assert all(p.taxi_stand is None for p in aboard(manager.trains[0]))


def test_only_a_share_of_passengers_want_a_taxi_and_it_is_reproducible():
    def intents(seed):
        flow = PassengerFlow(seed=seed)
        train = fake_train("1", ["A", "B", "C", "D"], ["A", "B", "C", "D"])
        flow.populate(train, NOON)
        return [p.intent for group in flow.waiting.values() for g in group.values() for p in g]

    first = intents(1)
    assert TAXI in first and WALK in first
    assert abs(first.count(TAXI) / len(first) - TAXI_DEMAND_SHARE) < 0.15
    assert intents(1) == first  # same seed, same demand
    assert intents(2) != first


def test_taxi_passenger_keeps_its_stand_through_the_train_and_walks_to_it():
    stand = TaxiStop(40.0, 8000.0, id=9)
    manager = manager_with([stand])
    flow = manager.passengers
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 10, 51))
    (train,) = manager.trains
    taxi_to_b = [p for p in flow.waiting["A"][("IC", "7")] + aboard(train) if p.destination == "B" and p.intent == TAXI]
    assert taxi_to_b and all(p.taxi_stand is stand for p in taxi_to_b)  # known from the start

    peds = FakePedestrians([SimpleNamespace(points_m=[(20.0, -5000.0), (20.0, 25_000.0)])])
    manager.passenger_view = StationPassengerView(peds)
    manager.view_point = (5.0, 8000.0)
    now = datetime(2026, 9, 28, 10, 51)
    for _ in range(4000):
        manager.update(0.5, 0.5, now)
        if not manager.trains:
            break
    arrived = [p for p in flow.arrived.get("B", []) if p.intent == TAXI]
    assert arrived and all(p.state == ARRIVED and p.taxi_stand is stand for p in arrived)
    walkers = [n for n in peds.pedestrians if getattr(n, "rail_passenger", None) in arrived]
    assert walkers and all(n.is_walking_to_taxi_stop and n.taxi_stop_target == (20.0, 8000.0) for n in walkers)
    walkers_on_foot = [n for n in peds.pedestrians if getattr(getattr(n, "rail_passenger", None), "intent", None) == WALK]
    assert all(not getattr(n, "is_walking_to_taxi_stop", False) for n in walkers_on_foot)


def test_never_sent_across_a_track_to_the_stand():
    # Platform walkway at x=20, the stand's walkway at x=60, a track between.
    peds = FakePedestrians([SimpleNamespace(points_m=[(20.0, -200.0), (20.0, 200.0)]),
                            SimpleNamespace(points_m=[(60.0, -200.0), (60.0, 200.0)])])
    view = StationPassengerView(peds, on_track=lambda point: 25.0 < point[0] < 35.0)
    passenger = RailPassenger("X", "B", ("IC", "7"), ARRIVED, platform=(0.0, 0.0), intent=TAXI, taxi_stand=TaxiStop(60.0, 0.0))
    assert view.show(passenger, standing=False)
    (walker,) = peds.pedestrians
    assert not getattr(walker, "is_walking_to_taxi_stop", False)  # walks off instead
    assert walker.rail_passenger is passenger and passenger.intent == TAXI  # still wants a taxi


def test_stands_are_matched_on_rebuild_not_per_frame(monkeypatch):
    manager = manager_with([TaxiStop(5.0, 8100.0)])
    calls = []
    monkeypatch.setattr(manager, "associate_taxi_stands", lambda *a: calls.append(a))
    for second in range(300):
        manager.update(0.5, 30.0, datetime(2026, 9, 28, 10, 0, second % 60))
    assert calls == []
