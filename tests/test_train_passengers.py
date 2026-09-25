from datetime import datetime
from types import SimpleNamespace

from theroadragetrip.osm.models import Railway
from theroadragetrip.train_passengers import ARRIVED, ON_TRAIN, WAITING, PassengerFlow
from theroadragetrip.trains import RailwayManager

NOON = datetime(2026, 9, 28, 12, 0)


def fake_train(number, calls, local, kind="IC"):
    """Just what PassengerFlow reads: service identity + journey calls and
    the train's stops on the map (stop[2] = station name)."""
    service = SimpleNamespace(train_type=kind, number=number, calls=tuple(calls))
    return SimpleNamespace(service=service, stops=tuple((0.0, 0, name) for name in local), stop_index=0, manifest={})


def aboard(train):
    return [p for group in train.manifest.values() for p in group]


def test_passengers_get_only_later_stations_of_the_trains_own_journey():
    flow = PassengerFlow()
    train = fake_train("1", ["X", "A", "B", "C", "D"], ["A", "B", "C", "D"])  # X is before the map
    flow.populate(train, NOON)
    calls = train.service.calls
    assert aboard(train)  # boarded at X, off the map
    for passenger in aboard(train):
        assert passenger.origin == "X" and passenger.state == ON_TRAIN
        assert passenger.destination in ("A", "B", "C", "D")
    for station in ("A", "B", "C"):
        waiting = flow.waiting[station][("IC", "1")]
        assert waiting
        for passenger in waiting:
            assert passenger.origin == station and passenger.state == WAITING
            assert calls.index(passenger.destination) > calls.index(station)
    assert "D" not in flow.waiting  # nobody boards at the journey's end


def test_each_stop_lets_passengers_off_before_boarding_and_never_early():
    flow = PassengerFlow()
    train = fake_train("1", ["A", "B", "C", "D"], ["A", "B", "C", "D"])
    flow.populate(train, NOON)
    boarded_at = {}
    for index, station in enumerate(["A", "B", "C", "D"]):
        waiting_here = list(flow.waiting.get(station, {}).get(("IC", "1"), []))
        before = aboard(train)
        off, on = (len(group) for group in flow.on_arrival(train, station, NOON))
        leaving = [p for p in before if p.destination == station]
        assert off == len(leaving) and all(p.state == ARRIVED for p in leaving)
        assert on == len(waiting_here) and all(p.state == ON_TRAIN for p in waiting_here)
        assert flow.waiting_count(station) == 0  # boarded: gone from the station
        assert all(p.destination != station for p in aboard(train))  # got on here, not off at once
        for passenger in waiting_here:
            boarded_at[id(passenger)] = index
        train.stop_index = index + 1
    assert aboard(train) == []  # everyone off by the last stop
    arrived = [p for station in "BCD" for p in flow.arrived.get(station, [])]
    assert all(["A", "B", "C", "D"].index(p.destination) > ["A", "B", "C", "D"].index(p.origin) for p in arrived)
    assert len(arrived) == flow.boarded_total  # all who boarded arrived


def test_a_passenger_waiting_for_one_train_never_boards_another():
    flow = PassengerFlow()
    first = fake_train("1", ["A", "B", "C"], ["A", "B", "C"])
    second = fake_train("2", ["A", "B", "C"], ["B", "C"])
    flow.populate(first, NOON)
    waiting_for_first = list(flow.waiting["B"][("IC", "1")])
    flow.on_arrival(second, "B", NOON)
    assert all(p.state == WAITING for p in waiting_for_first)
    assert flow.waiting["B"][("IC", "1")] == waiting_for_first
    assert all(p.train == ("IC", "2") for p in aboard(second))


def test_generation_is_deterministic_and_scales_with_train_and_time():
    def count(kind, when):
        flow = PassengerFlow()
        train = fake_train("9", ["A", "B", "C"], ["A", "B", "C"], kind=kind)
        flow.populate(train, when)
        return flow.waiting_count("A")

    assert count("IC", NOON) == count("IC", NOON)
    assert count("IC", datetime(2026, 9, 28, 3, 0)) < count("IC", NOON)  # night
    assert count("H", NOON) < count("S", NOON)  # small local train vs Pendolino


# -- through the real train simulation ----------------------------------------

def metres(lat, lon):
    return lon * 100_000.0, lat * 100_000.0


def test_real_trains_carry_passengers_between_stations_on_the_map():
    line = [Railway(points_m=[(5.0, -5000.0), (5.0, 25_000.0)])]
    stations = {code: [lat, 0.00005, code] for code, lat in (("X", -0.3), ("A", 0.0), ("B", 0.08), ("C", 0.16), ("Z", 0.5))}
    journey = {
        "type": "IC", "number": "7", "category": "long_distance", "origin": "X", "destination": "Z", "days": 0b1111111,
        "stops": [[code, t, t + (60 if code in "ABC" else 0), 1, ""] for code, t in (("X", 36000), ("A", 39000), ("B", 40000), ("C", 41000), ("Z", 45000))],
    }
    manager = RailwayManager(line, {"version": 4, "stations": stations, "trains": [journey]}, metres)
    now = datetime(2026, 9, 28, 10, 51)  # its event: arrival at A (first stop on the map) 10:50
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
    manager.update(0.0, 0.0, now)
    (train,) = manager.trains
    flow = manager.passengers
    assert aboard(train) and all(p.origin == "X" for p in aboard(train))
    waiting_b = list(flow.waiting["B"][("IC", "7")])
    visited = []
    for _ in range(8000):
        manager.update(0.5, 0.5, now)
        stop = train.next_stop
        if train.state == "DWELLING" and stop is not None and (not visited or visited[-1] != stop[2]):
            visited.append(stop[2])
        if not manager.trains:
            break
    assert visited == ["A", "B", "C"]
    assert all(p.state == ON_TRAIN or p.state == ARRIVED for p in waiting_b)
    assert all(p.destination in ("C", "Z") for p in waiting_b)
    assert all(p.destination != "B" for p in waiting_b)
    arrived_b = list(flow.arrived.get("B", []))
    assert arrived_b and all(p.destination == "B" for p in arrived_b)
    assert flow.waiting_count("A") == flow.waiting_count("B") == flow.waiting_count("C") == 0


# -- seats, the restaurant car and the car popup ---------------------------

from theroadragetrip.train_compositions import TrainComposition  # noqa: E402


def seated_train(number="1", calls=("X", "A", "B", "C", "D"), local=("A", "B", "C", "D")):
    train = fake_train(number, calls, local)
    train.composition = TrainComposition(((19.6, "locomotive"), (26.4, "standard"), (26.4, "restaurant"), (26.4, "standard")))
    return train


def test_every_passenger_has_a_name_and_a_seat_in_a_passenger_car():
    flow = PassengerFlow()
    train = seated_train()
    flow.populate(train, NOON)
    flow.on_arrival(train, "A", NOON)
    assert aboard(train)
    for passenger in aboard(train):
        assert passenger.name and passenger.car in (1, 2, 3)  # never the locomotive (0)
    assert sum(len(flow.in_car(train, car)) for car in (0, 1, 2, 3)) == len(aboard(train))
    assert flow.in_car(train, 0) == []


def test_restaurant_car_guests_drink_on_the_way_and_step_off_drunk():
    from theroadragetrip.station_passengers import StationPassengerView
    from theroadragetrip.train_passengers import DRUNK_FROM_PROMILLE
    from tests.test_station_passengers import FakePedestrians

    flow = PassengerFlow()
    train = seated_train(calls=("A", "B", "C", "D", "E", "F", "G"), local=("A", "B", "C", "D", "E", "F", "G"))
    flow.populate(train, NOON)
    flow.on_arrival(train, "A", NOON)
    diners = flow.in_car(train, 2)
    others = [p for p in aboard(train) if p.car != 2]
    for station in "BCDEF":
        train.stop_index += 1
        flow.on_arrival(train, station, NOON)
    assert any(p.promille > 0 for p in diners)
    assert all(p.promille == 0 for p in others)  # only the restaurant car serves
    assert all(p.promille <= 3.0 for p in diners)

    drunk = next(p for p in diners if p.promille >= DRUNK_FROM_PROMILLE)
    peds = FakePedestrians([SimpleNamespace(points_m=[(0.0, -100.0), (0.0, 100.0)])])
    drunk.platform = (0.0, 0.0)
    view = StationPassengerView(peds)
    view.on_arrival([drunk], [], (0.0, 0.0), view_point=(0.0, 0.0))
    view.update(0.0, flow, [], None)
    (walker,) = peds.pedestrians
    assert walker.is_drunk and walker.blood_alcohol_promille == drunk.promille


def test_clicking_a_train_car_finds_that_car():
    from theroadragetrip.trains import Train, TrainRoute

    manager = RailwayManager([], None, None)
    train = Train(TrainRoute([(0.0, 0.0), (1000.0, 0.0)]), 500.0, 1)
    manager.trains.append(train)
    cars = train.cars()
    assert manager.vehicle_at(cars[2][0], cars[2][1] + 1.0) == (train, 2)
    assert manager.vehicle_at(cars[2][0], 30.0) is None  # beside the track


def test_car_popup_lists_its_passengers():
    import pygame
    from theroadragetrip.render.vehicles import draw_train_car_popup

    pygame.init()
    flow = PassengerFlow()
    train = seated_train()
    flow.populate(train, NOON)
    diners = flow.in_car(train, 2)
    screen = pygame.Surface((1280, 720))
    draw_train_car_popup(screen, pygame.font.SysFont(None, 22), train, 2, diners, "fi", 1280)
    assert pygame.transform.average_color(screen.subsurface((900, 150, 300, 60)))[:3] != (0, 0, 0)
