"""Railway taxi phase 8: logical, runtime-only pre-bookings."""
import random
from datetime import datetime
from types import SimpleNamespace

from theroadragetrip.rail_bookings import (
    ACCEPTED,
    DECLINED,
    PASSENGER_WAITING,
    PENDING,
    PREBOOKING_SURCHARGE_CENTS,
    TRAIN_ARRIVING,
    RailBookingManager,
)
from theroadragetrip.train_passengers import TAXI, WALK, RailPassenger


OCCURRENCE = datetime(2026, 9, 25, 18, 20)
STAND = SimpleNamespace(x=10.0, y=20.0)
DESTINATION = SimpleNamespace(address="Kirkkokatu 1")


class Always:
    def random(self):
        return 0.0


def train(number="57"):
    service = SimpleNamespace(train_type="IC", number=number, seconds=66000)
    return SimpleNamespace(
        service=service,
        stops=((0.0, 60, "Oulu", 67320, 67380),),
        manifest={},
    )


def passenger(intent=TAXI, stand=STAND):
    return RailPassenger("Helsinki", "Oulu", ("IC", "57"), intent=intent, taxi_stand=stand)


def manager():
    return RailBookingManager(destination_for=lambda stand: DESTINATION)


def test_booking_keeps_existing_passenger_train_stand_destination_and_surcharge():
    bookings = manager()
    rail_passenger = passenger()
    booking = bookings.consider(rail_passenger, train(), OCCURRENCE, Always())

    assert booking.passenger is rail_passenger and booking.passenger_id == rail_passenger.id
    assert rail_passenger.booking is booking
    assert booking.train_instance_id == ("2026-09-25", "IC", "57")
    assert booking.station == "Oulu" and booking.taxi_stand is STAND
    assert booking.destination is DESTINATION
    assert booking.arrival_at == datetime(2026, 9, 25, 18, 42)
    assert booking.surcharge_cents == PREBOOKING_SURCHARGE_CENTS == 800
    assert booking.status == PENDING


def test_only_taxi_passengers_with_a_real_stand_can_be_booked():
    bookings = manager()
    assert bookings.consider(passenger(WALK), train(), OCCURRENCE, Always()) is None
    assert bookings.consider(passenger(TAXI, None), train(), OCCURRENCE, Always()) is None
    assert bookings.bookings == []


def test_generation_is_partial_and_deterministic():
    def choices(seed):
        bookings = manager()
        rng = random.Random(seed)
        return [bookings.consider(passenger(), train(), OCCURRENCE, rng) is not None for _ in range(100)]

    first = choices(7)
    assert 0 < sum(first) < len(first)
    assert choices(7) == first
    assert choices(8) != first


def test_accept_decline_and_train_events_are_explicit():
    bookings = manager()
    accepted = bookings.consider(passenger(), train(), OCCURRENCE, Always())
    declined = bookings.consider(passenger(), train("58"), OCCURRENCE, Always())
    assert bookings.accept(accepted) and accepted.status == ACCEPTED
    assert bookings.decline(declined) and declined.status == DECLINED

    approaching = train()
    approaching.manifest = {"Oulu": [accepted.passenger]}
    bookings.train_approaching(approaching)
    assert accepted.status == TRAIN_ARRIVING
    bookings.passengers_arrived([accepted.passenger])
    assert accepted.status == PASSENGER_WAITING


def test_same_train_number_on_different_dates_is_a_different_instance():
    bookings = manager()
    first = bookings.consider(passenger(), train(), OCCURRENCE, Always())
    second = bookings.consider(passenger(), train(), datetime(2026, 9, 26, 18, 20), Always())
    assert first.train_instance_id != second.train_instance_id
    assert len(bookings.visible()) == 2


def test_accepting_an_already_approaching_train_advances_on_next_update():
    bookings = manager()
    booking = bookings.consider(passenger(), train(), OCCURRENCE, Always())
    approaching = train()
    approaching.manifest = {"Oulu": [booking.passenger]}
    bookings.train_approaching(approaching)
    assert booking.status == PENDING
    assert bookings.accept(booking) and booking.status == ACCEPTED
    bookings.update()
    assert booking.status == TRAIN_ARRIVING
