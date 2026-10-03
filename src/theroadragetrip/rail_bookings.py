"""Runtime-only pre-booked taxi jobs for railway passengers (phases 8-9)."""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

from .train_passengers import TAXI

PENDING = "PENDING"
ACCEPTED = "ACCEPTED"
TRAIN_ARRIVING = "TRAIN_ARRIVING"
PASSENGER_WAITING = "PASSENGER_WAITING"
PASSENGER_MET = "PASSENGER_MET"
IN_TAXI = "IN_TAXI"
DECLINED = "DECLINED"
MISSED = "MISSED"

PREBOOKING_SHARE = 0.20
PREBOOKING_SURCHARGE_CENTS = 800
PICKUP_WINDOW = timedelta(minutes=20)  # game time a booked passenger waits after the train arrived
FINISHED = (DECLINED, MISSED, IN_TAXI)

_booking_ids = itertools.count(1)


@dataclass
class TaxiBooking:
    passenger: object
    train_instance_id: Tuple[str, str, str]
    train_number: str
    station: str
    taxi_stand: object
    destination: object
    arrival_at: datetime
    created_at: datetime
    surcharge_cents: int = PREBOOKING_SURCHARGE_CENTS
    status: str = PENDING
    train_is_approaching: bool = False
    was_accepted: bool = False  # a missed booking only matters to the player if they took it
    id: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = next(_booking_ids)

    @property
    def passenger_id(self) -> int:
        return self.passenger.id


class RailBookingManager:
    """Creates bookings once and advances them from train events."""

    def __init__(self, destination_for: Optional[Callable] = None, on_created: Optional[Callable] = None) -> None:
        self.destination_for = destination_for
        self.on_created = on_created
        self.on_missed: Optional[Callable] = None  # called once for each accepted booking that is missed
        self.bookings: List[TaxiBooking] = []

    def consider(self, passenger, train, occurrence: datetime, rng) -> Optional[TaxiBooking]:
        if (
            passenger.intent != TAXI
            or passenger.taxi_stand is None
            or self.destination_for is None
            or rng.random() >= PREBOOKING_SHARE
        ):
            return None
        destination = self.destination_for(passenger.taxi_stand)
        if destination is None:
            return None
        service = train.service
        stop = next((stop for stop in train.stops if stop[2] == passenger.destination), None)
        if stop is None:
            return None
        arrival_at = occurrence + timedelta(seconds=stop[3] - service.seconds)
        booking = TaxiBooking(
            passenger=passenger,
            train_instance_id=(occurrence.date().isoformat(), service.train_type, service.number),
            train_number=f"{service.train_type}{service.number}",
            station=passenger.destination,
            taxi_stand=passenger.taxi_stand,
            destination=destination,
            arrival_at=arrival_at,
            created_at=occurrence,
        )
        passenger.booking = booking
        self.bookings.append(booking)
        if self.on_created is not None:
            self.on_created(booking)
        return booking

    def accept(self, booking: TaxiBooking) -> bool:
        if booking.status != PENDING:
            return False
        booking.status = ACCEPTED
        booking.was_accepted = True
        return True

    def update(self, now: Optional[datetime] = None) -> None:
        """Advance accepted jobs whose train is already approaching, miss
        passengers left waiting past PICKUP_WINDOW, forget finished jobs."""
        for booking in self.bookings:
            if booking.status == ACCEPTED and booking.train_is_approaching:
                booking.status = TRAIN_ARRIVING
            elif (
                booking.status == PASSENGER_WAITING and now is not None
                and booking.passenger.arrived_at is not None
                and now - booking.passenger.arrived_at > PICKUP_WINDOW
            ):
                booking.status = MISSED
        # Missed anywhere (here, at arrival, or by driving away mid-pickup):
        # reported once, just before the booking is forgotten below.
        if self.on_missed is not None:
            for booking in self.bookings:
                if booking.status == MISSED and booking.was_accepted:
                    self.on_missed(booking)
        if any(booking.status in FINISHED for booking in self.bookings):
            self.bookings = [booking for booking in self.bookings if booking.status not in FINISHED]

    def decline(self, booking: TaxiBooking) -> bool:
        if booking.status != PENDING:
            return False
        booking.status = DECLINED
        return True

    def train_approaching(self, train) -> None:
        for group in train.manifest.values():
            for passenger in group:
                booking = getattr(passenger, "booking", None)
                if booking is not None:
                    booking.train_is_approaching = True
                    if booking.status == ACCEPTED:
                        booking.status = TRAIN_ARRIVING

    @staticmethod
    def passengers_arrived(passengers) -> None:
        for passenger in passengers:
            booking = getattr(passenger, "booking", None)
            if booking is not None and booking.status in (ACCEPTED, TRAIN_ARRIVING):
                booking.status = PASSENGER_WAITING
            elif booking is not None and booking.status == PENDING:
                booking.status = MISSED  # never answered before the train came in

    def visible(self) -> List[TaxiBooking]:
        return [b for b in self.bookings if b.status not in FINISHED]

    def waiting(self) -> List[TaxiBooking]:
        return [b for b in self.bookings if b.status == PASSENGER_WAITING]

    def pending(self) -> List[TaxiBooking]:
        return [b for b in self.bookings if b.status == PENDING]


def waiting_booking(pedestrian) -> Optional[TaxiBooking]:
    """The accepted booking this pedestrian is the waiting customer of: the
    link is pedestrian.rail_passenger (set when the passenger was shown),
    never position or looks."""
    booking = getattr(getattr(pedestrian, "rail_passenger", None), "booking", None)
    return booking if booking is not None and booking.status == PASSENGER_WAITING else None
