"""Railway taxi phase 9: meeting the pre-booked passenger at the stand."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from theroadragetrip.fare import calculate_fare_cents
from theroadragetrip.physics import Car
from theroadragetrip.rail_bookings import (
    IN_TAXI,
    MISSED,
    PASSENGER_MET,
    PASSENGER_WAITING,
    PICKUP_WINDOW,
    PREBOOKING_SURCHARGE_CENTS,
    RailBookingManager,
    waiting_booking,
)
from theroadragetrip.station_passengers import SYNC_INTERVAL_S, StationPassengerView
from theroadragetrip.taxi import TaxiManager, TaxiState
from theroadragetrip.train_passengers import ON_TRAIN, TAXI, PassengerFlow, RailPassenger

from test_station_passengers import FakePedestrians

NOW = datetime(2026, 9, 25, 18, 42)
STATION = (0.0, 0.0)
STAND = SimpleNamespace(x=20.0, y=40.0)  # the stand's waiting spot is on the walkway at (20, 40)
DESTINATION = SimpleNamespace(x=900.0, y=900.0, address="Kirkkokatu 1", radius_m=25.0)
ELSEWHERE = SimpleNamespace(x=-900.0, y=0.0, address="Random street 2", radius_m=25.0)


class Always:
    def random(self):
        return 0.0


def booked_train(*names):
    """A train arriving at Oulu with one accepted booked passenger per name."""
    bookings = RailBookingManager(destination_for=lambda stand: DESTINATION)
    service = SimpleNamespace(train_type="IC", number="57", seconds=66000)
    train = SimpleNamespace(service=service, stops=((0.0, 60, "Oulu", 67320, 67380),), manifest={})
    for name in names:
        passenger = RailPassenger("Helsinki", "Oulu", ("IC", "57"), ON_TRAIN, name=name, intent=TAXI, taxi_stand=STAND)
        bookings.accept(bookings.consider(passenger, train, NOW - timedelta(minutes=22), Always()))
        train.manifest.setdefault("Oulu", []).append(passenger)
    return bookings, train


def arrive(bookings, train, view, view_point):
    leaving, boarding = PassengerFlow().on_arrival(train, "Oulu", NOW)
    bookings.passengers_arrived(leaving)
    view.on_arrival(leaving, boarding, STATION, view_point)
    view.update(0.0, PassengerFlow(), [("Oulu", STATION)], view_point, bookings.waiting())
    return leaving


def taxi():
    manager = TaxiManager(ways=[])
    manager.pick_random_building_point = lambda *args, **kwargs: ELSEWHERE
    return manager


def stopped_at(x, y):
    return Car(x=x, y=y, heading=0.0, speed=0.0)


def test_the_booked_passenger_steps_off_as_one_linked_pedestrian():
    bookings, train = booked_train("Aino Virtanen")
    pedestrians = FakePedestrians()
    view = StationPassengerView(pedestrians)
    (passenger,) = arrive(bookings, train, view, view_point=STATION)

    assert passenger.booking.status == PASSENGER_WAITING
    assert pedestrians.pedestrians == [passenger.pedestrian]  # one pedestrian, no duplicate
    pedestrian = passenger.pedestrian
    assert pedestrian.rail_passenger is passenger and waiting_booking(pedestrian) is passenger.booking
    assert pedestrian.held_by is view  # never culled while the job waits
    assert pedestrian.taxi_stop_target == (20.0, 40.0)  # the existing stand, as in phase 7


def test_only_the_booked_passenger_is_marked():
    bookings, train = booked_train("Aino Virtanen")
    view = StationPassengerView(FakePedestrians())
    (passenger,) = arrive(bookings, train, view, view_point=STATION)
    ordinary = SimpleNamespace(wants_taxi=True, is_taxi_stop_waiter=True)
    unbooked_rail = SimpleNamespace(wants_taxi=True, rail_passenger=RailPassenger("A", "Oulu", ("IC", "57")))

    assert waiting_booking(passenger.pedestrian) is passenger.booking
    assert waiting_booking(ordinary) is None and waiting_booking(unbooked_rail) is None


def test_meet_and_greet_needs_the_taxi_stopped_right_by_the_booked_passenger():
    bookings, train = booked_train("Aino Virtanen")
    view = StationPassengerView(FakePedestrians())
    (passenger,) = arrive(bookings, train, view, view_point=STATION)
    pedestrian = passenger.pedestrian
    pedestrian.x, pedestrian.y = 20.0, 40.0
    manager = taxi()

    assert manager.check_waiting_pickup(stopped_at(20.0, 70.0), [pedestrian], 3.0) is None
    assert passenger.booking.status == PASSENGER_WAITING

    car = stopped_at(20.0, 45.0)
    assert manager.check_waiting_pickup(car, [pedestrian], 3.0) is pedestrian
    booking, customer = passenger.booking, manager.current_passenger
    assert booking.status == PASSENGER_MET and customer.rail_booking is booking
    assert customer.name == "Aino Virtanen" and customer.dropoff is DESTINATION  # not regenerated
    assert manager.state == TaxiState.CLIENT_WALKING_TO_CAR

    for _ in range(100):  # the existing walk to the door
        manager.update(car, 0.1)
        if manager.state == TaxiState.DRIVING_TO_DROPOFF:
            break
    assert manager.state == TaxiState.DRIVING_TO_DROPOFF and booking.status == IN_TAXI
    assert customer.dropoff is DESTINATION
    assert booking.surcharge_cents == PREBOOKING_SURCHARGE_CENTS == 800
    # The meter starts at the normal startup fare, the fee is not added into it.
    assert manager.live_fare_cents == calculate_fare_cents(0.0, 0.0, manager.fare_started_at)


def test_an_ordinary_stand_customer_never_completes_a_booking():
    bookings, train = booked_train("Aino Virtanen")
    view = StationPassengerView(FakePedestrians())
    (passenger,) = arrive(bookings, train, view, view_point=STATION)
    passenger.pedestrian.x, passenger.pedestrian.y = 20.0, 80.0  # 35 m away
    ordinary = SimpleNamespace(x=20.0, y=40.0, heading=0.0, wants_taxi=True)
    manager = taxi()
    manager.taxi_stops = [STAND]

    assert manager.check_waiting_pickup(stopped_at(20.0, 45.0), [passenger.pedestrian, ordinary], 3.0) is ordinary
    assert manager.current_passenger.rail_booking is None
    assert manager.current_passenger.dropoff is ELSEWHERE
    assert passenger.booking.status == PASSENGER_WAITING


def test_several_booked_passengers_each_keep_their_own_booking():
    bookings, train = booked_train("Aino Virtanen", "Eero Laine")
    view = StationPassengerView(FakePedestrians())
    first, second = arrive(bookings, train, view, view_point=STATION)
    assert first.booking is not second.booking
    first.pedestrian.x, first.pedestrian.y = 20.0, 80.0
    second.pedestrian.x, second.pedestrian.y = 20.0, 40.0
    manager = taxi()

    picked = manager.check_waiting_pickup(stopped_at(20.0, 45.0), [first.pedestrian, second.pedestrian], 3.0)
    assert picked is second.pedestrian and manager.current_passenger.rail_booking is second.booking
    assert first.booking.status == PASSENGER_WAITING and second.booking.status == PASSENGER_MET


def test_an_uncollected_passenger_is_missed_and_becomes_ordinary():
    bookings, train = booked_train("Aino Virtanen")
    view = StationPassengerView(FakePedestrians())
    (passenger,) = arrive(bookings, train, view, view_point=STATION)
    booking, pedestrian = passenger.booking, passenger.pedestrian

    bookings.update(NOW + PICKUP_WINDOW)
    assert booking.status == PASSENGER_WAITING
    bookings.update(NOW + PICKUP_WINDOW + timedelta(seconds=1))
    assert booking.status == MISSED and booking not in bookings.bookings

    view.update(SYNC_INTERVAL_S, PassengerFlow(), [("Oulu", STATION)], STATION, bookings.waiting())
    assert pedestrian.held_by is None and passenger.pedestrian is None
    assert waiting_booking(pedestrian) is None


def test_a_pending_booking_is_missed_when_its_train_comes_in():
    bookings, train = booked_train()
    passenger = RailPassenger("Helsinki", "Oulu", ("IC", "57"), ON_TRAIN, intent=TAXI, taxi_stand=STAND)
    booking = bookings.consider(passenger, train, NOW, Always())
    bookings.passengers_arrived([passenger])
    assert booking.status == MISSED


def test_an_out_of_view_arrival_stays_data_until_its_station_is_seen():
    bookings, train = booked_train("Aino Virtanen")
    pedestrians = FakePedestrians()
    view = StationPassengerView(pedestrians)
    far = (5000.0, 0.0)
    (passenger,) = arrive(bookings, train, view, view_point=far)
    assert passenger.pedestrian is None and pedestrians.pedestrians == []
    assert passenger.booking.status == PASSENGER_WAITING

    view.update(SYNC_INTERVAL_S, PassengerFlow(), [("Oulu", STATION)], STATION, bookings.waiting())
    pedestrian = passenger.pedestrian
    assert pedestrians.pedestrians == [pedestrian] and waiting_booking(pedestrian) is passenger.booking
    assert (pedestrian.x, pedestrian.y) == (20.0, 40.0) and pedestrian.is_taxi_stop_waiter

    view.update(SYNC_INTERVAL_S, PassengerFlow(), [("Oulu", STATION)], far, bookings.waiting())
    assert passenger.pedestrian is None and pedestrians.pedestrians == []
    assert passenger.booking.status == PASSENGER_WAITING

    view.update(SYNC_INTERVAL_S, PassengerFlow(), [("Oulu", STATION)], STATION, bookings.waiting())
    assert passenger.pedestrian.resident_id == pedestrian.resident_id  # the same person again
