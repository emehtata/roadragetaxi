import math
from datetime import datetime
from types import SimpleNamespace

from theroadragetrip.osm.models import Railway
from theroadragetrip.station_passengers import StationPassengerView, VISIBLE_RADIUS_M
from theroadragetrip.train_passengers import ARRIVED, ON_TRAIN, WAITING, PassengerFlow, RailPassenger
from theroadragetrip.trains import RailwayManager

WALKWAY = SimpleNamespace(points_m=[(20.0, -200.0), (20.0, 200.0)])  # a platform path at x=20


class FakePedestrians:
    """What StationPassengerView uses of PedestrianManager."""

    def __init__(self, ways=(WALKWAY,)):
        self.ways = list(ways)
        self.pedestrians = []
        self.next_resident = 100

    def _nearby_ped_ways(self, x, y):
        return self.ways

    def spawn_pedestrian_at(self, x, y, heading=0.0, resident_id=None):
        if resident_id is None:
            self.next_resident += 1
            resident_id = self.next_resident
        return SimpleNamespace(x=x, y=y, heading=heading, speed=1.3, base_speed=1.3, resident_id=resident_id)


def waiting(platform=(0.0, 0.0)):
    return RailPassenger("A", "C", ("IC", "1"), WAITING, platform=platform)


def test_waiting_passenger_stands_on_a_walkway_near_the_platform_with_its_identity():
    peds = FakePedestrians()
    view = StationPassengerView(peds)
    passenger = waiting()
    assert view.show(passenger, standing=True)
    npc = passenger.pedestrian
    assert npc in peds.pedestrians and npc.rail_passenger is passenger
    assert npc.x == 20.0 and abs(npc.y) <= 30  # snapped onto the walkway, near the platform point
    assert npc.speed == 0.0 and npc.held_by is view  # stands; the pedestrian system won't cull it


def test_never_placed_on_a_track_and_data_only_without_a_safe_walkway():
    peds = FakePedestrians()
    view = StationPassengerView(peds, on_track=lambda point: abs(point[0] - 20.0) < 2.0)  # walkway lies on a track
    passenger = waiting()
    assert not view.show(passenger, standing=True)
    assert passenger.pedestrian is None and peds.pedestrians == []
    far = FakePedestrians(ways=[SimpleNamespace(points_m=[(500.0, 0.0), (500.0, 10.0)])])
    assert not StationPassengerView(far).show(waiting(), standing=True)  # no walkway within reach


def test_hiding_keeps_the_journey_and_showing_again_is_the_same_person():
    peds = FakePedestrians()
    view = StationPassengerView(peds)
    passenger = waiting()
    view.show(passenger, standing=True)
    resident = passenger.pedestrian.resident_id
    view.hide(passenger)
    assert passenger.pedestrian is None and peds.pedestrians == [] and passenger.state == WAITING
    view.show(passenger, standing=True)
    assert passenger.pedestrian.resident_id == resident


def test_boarding_removes_the_npc_and_arrivals_step_off_and_walk():
    peds = FakePedestrians()
    view = StationPassengerView(peds)
    boarder, arriving = waiting(), RailPassenger("X", "A", ("IC", "1"), ARRIVED)
    view.show(boarder, standing=True)
    boarder.state = ON_TRAIN
    view.on_arrival([arriving], [boarder], station_point=(0.0, 0.0), view_point=(10.0, 0.0))
    view.update(0.0, PassengerFlow(), [], None)  # queued pedestrians are made on the next update
    assert boarder.pedestrian is None and all(p.rail_passenger is not boarder for p in peds.pedestrians)
    (walker,) = peds.pedestrians
    assert walker.rail_passenger is arriving and walker.speed > 0 and not hasattr(walker, "held_by")
    assert arriving.pedestrian is None  # now an ordinary pedestrian; the journey stays ARRIVED data


def test_nothing_is_shown_where_nobody_looks():
    peds = FakePedestrians()
    view = StationPassengerView(peds)
    view.on_arrival([RailPassenger("X", "A", ("IC", "1"), ARRIVED)], [], (0.0, 0.0), view_point=(VISIBLE_RADIUS_M * 2, 0.0))
    assert peds.pedestrians == []


def test_stations_come_into_and_out_of_view():
    peds = FakePedestrians()
    view = StationPassengerView(peds)
    flow = PassengerFlow()
    group = [waiting() for _ in range(5)]
    flow.waiting["A"] = {("IC", "1"): group}
    view.update(1.0, flow, [("A", (0.0, 0.0))], view_point=(0.0, 0.0))  # queues them
    view.update(0.0, flow, [("A", (0.0, 0.0))], view_point=(0.0, 0.0))  # makes them
    assert len(peds.pedestrians) == 5 and all(p.pedestrian is not None for p in group)
    assert len({(n.x, n.y) for n in peds.pedestrians}) > 1  # not all on one spot
    view.update(1.0, flow, [("A", (0.0, 0.0))], view_point=(VISIBLE_RADIUS_M * 3, 0.0))
    assert peds.pedestrians == [] and flow.waiting["A"][("IC", "1")] == group  # journeys kept


def test_visible_passengers_never_change_train_timing():
    line = [Railway(points_m=[(5.0, -5000.0), (5.0, 25_000.0)])]
    stations = {code: [lat, 0.00005, code] for code, lat in (("X", -0.3), ("A", 0.0), ("B", 0.08), ("Z", 0.5))}
    journey = {
        "type": "IC", "number": "7", "category": "long_distance", "origin": "X", "destination": "Z", "days": 0b1111111,
        "stops": [[code, t, t + (120 if code in "AB" else 0), 1, ""] for code, t in (("X", 36000), ("A", 39000), ("B", 40000), ("Z", 45000))],
    }

    def run(with_view):
        manager = RailwayManager(line, {"version": 4, "stations": stations, "trains": [journey]}, lambda la, lo: (lo * 100_000.0, la * 100_000.0))
        if with_view:
            manager.passenger_view = StationPassengerView(FakePedestrians([SimpleNamespace(points_m=[(25.0, -5000.0), (25.0, 25_000.0)])]))
        now = datetime(2026, 9, 28, 10, 51)
        manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
        manager.update(0.0, 0.0, now)
        (train,) = manager.trains
        states = []
        for step in range(6000):
            manager.view_point = train.cars()[0][:2]  # camera on the train: passengers shown
            manager.update(0.5, 0.5, now)
            states.append((train.state, round(train.distance_m)))
            if not manager.trains:
                break
        return states, manager

    plain, _ = run(False)
    shown, manager = run(True)
    assert plain == shown  # same states at the same moments
    assert manager.passengers.boarded_total > 0
    assert all(p.pedestrian is None for group in manager.passengers.waiting.values() for g in group.values() for p in g)


def test_a_whole_train_stepping_off_is_spread_over_frames():
    import time
    from theroadragetrip import station_passengers

    peds = FakePedestrians()
    view = StationPassengerView(peds)
    arrivals = [RailPassenger("X", "A", ("IC", "1"), ARRIVED, platform=(0.0, 0.0)) for _ in range(100)]
    view.on_arrival(arrivals, [], (0.0, 0.0), view_point=(0.0, 0.0))
    assert peds.pedestrians == []  # nothing made inside the arrival event
    frames = 0
    while len(peds.pedestrians) < 100 and frames < 1000:
        started = time.perf_counter()
        view.update(1 / 60, PassengerFlow(), [], None)
        frames += 1
        assert time.perf_counter() - started < station_passengers.SHOW_BUDGET_S + 0.01
    assert len(peds.pedestrians) == 100
