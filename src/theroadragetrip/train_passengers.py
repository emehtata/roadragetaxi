"""Lightweight rail passengers (trains phase 4): who waits at which station
for which train, who rides it, and who gets off where.

Passengers are plain data, never NPCs: a station keeps its waiting
passengers indexed by train, a train keeps its manifest indexed by
destination, so an arrival touches only the passengers it concerns
(O(affected), no per-frame work). trains.RailwayManager calls populate()
when a timetable train appears and on_arrival() when one stops.

Journeys are one train, origin -> a later stop of that train's own
timetable journey (ScheduledPass.calls). Arrived passengers are recorded
at their station; turning them into pedestrians / taxi demand is a later
phase.
"""
from __future__ import annotations

import itertools
import random
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

WAITING, ON_TRAIN, ARRIVED = "WAITING_AT_STATION", "ON_TRAIN", "ARRIVED"
# How a passenger continues from their destination station.
WALK, TAXI = "WALK", "TAXI"
TAXI_DEMAND_SHARE = 0.05  # share of rail passengers wanting a taxi on arrival

# Passengers aboard a train when it is full-ish, by train type (GTFS route
# short name prefix); others use DEFAULT_LOAD. Tunable, not ticket data.
TRAIN_LOAD = {"IC": 120, "S": 150, "PYO": 90, "P": 60, "H": 40}
DEFAULT_LOAD = 60
# Share of the load boarding at a stop: the journey's first station fills
# the train, later stops add fewer as it empties towards the end.
ORIGIN_BOARDING_SHARE = 0.8
STOP_BOARDING_SHARE = 0.25
ARRIVED_KEPT_PER_STATION = 200  # recent arrivals kept for the next phase / debug
# Restaurant car: between stations a guest there has a drink with this
# chance, adding this much blood alcohol (promille); stepping off at
# DRUNK_FROM_PROMILLE or more they are a drunk pedestrian.
DRINK_CHANCE_PER_LEG = 0.6
DRINK_PROMILLE = (0.2, 0.7)
MAX_PROMILLE = 3.0
DRUNK_FROM_PROMILLE = 0.5


def time_of_day_factor(when: datetime) -> float:
    hour = when.hour
    if 7 <= hour < 9 or 15 <= hour < 18:
        return 1.3  # rush hours
    if hour < 5 or hour >= 23:
        return 0.3  # night
    return 1.0


_passenger_ids = itertools.count(1)


@dataclass(eq=False)
class RailPassenger:
    origin: str
    destination: str
    train: Tuple[str, str]  # (train type, number) of the one train they take
    state: str = WAITING
    waiting_since: Optional[datetime] = None
    arrived_at: Optional[datetime] = None
    # Where at the station they wait / step off (the train's platform point).
    platform: Optional[Tuple[float, float]] = None
    # Their visible pedestrian while at a station (station_passengers.py);
    # always None on a train - data or NPC, never both.
    pedestrian: object = None
    resident_id: Optional[int] = None  # the resident they are shown as (kept across shows)
    name: str = ""
    car: Optional[int] = None  # index into the train's composition vehicles while aboard
    promille: float = 0.0  # blood alcohol - the restaurant car
    intent: str = WALK  # WALK or TAXI, decided when the journey is created
    taxi_stand: object = None  # the existing TaxiStop nearest their destination station (TAXI only)
    booking: object = None  # optional rail_bookings.TaxiBooking; logical, not tied to a pedestrian
    id: int = field(default_factory=lambda: next(_passenger_ids))


def train_key(service) -> Tuple[str, str]:
    return service.train_type, service.number


def _name(rng: random.Random) -> str:
    from .residents import FIRST_NAMES, SURNAMES

    if not FIRST_NAMES or not SURNAMES:
        return ""
    return f"{rng.choice(FIRST_NAMES)['name']} {rng.choice(SURNAMES)['name']}"


def _cars(train, profile: Optional[str] = None) -> List[int]:
    """Indices of the train's passenger cars (all but locomotives), or of
    those with a given visual profile."""
    vehicles = getattr(getattr(train, "composition", None), "vehicles", ())
    return [
        index for index, (_, kind) in enumerate(vehicles)
        if kind != "locomotive" and (profile is None or kind == profile)
    ]


def _seat(passenger: "RailPassenger", train, rng: random.Random) -> None:
    cars = _cars(train)
    passenger.car = rng.choice(cars) if cars else None


class PassengerFlow:
    def __init__(self, seed: int = 0, stand_for=None, booking_manager=None) -> None:
        """stand_for(station name) -> the existing taxi stand cached for
        that station (or None) - see RailwayManager.station_stands."""
        self.seed = seed
        self.stand_for = stand_for or (lambda station: None)
        self.booking_manager = booking_manager
        # station -> train key -> passengers waiting for that train there
        self.waiting: Dict[str, Dict[Tuple[str, str], List[RailPassenger]]] = {}
        self.arrived: Dict[str, Deque[RailPassenger]] = {}
        self.boarded_total = 0
        self.alighted_total = 0

    def _rng(self, service, when: datetime) -> random.Random:
        # Same train on the same day -> the same passengers (debuggable).
        key = f"{self.seed}|{service.train_type}|{service.number}|{when:%Y-%m-%d}"
        return random.Random(zlib.crc32(key.encode()))

    def _plan_onward(self, passenger: "RailPassenger", rng: random.Random) -> "RailPassenger":
        """Walk or taxi from their destination; a taxi passenger keeps the
        destination station's cached stand for the rest of the journey."""
        if rng.random() < TAXI_DEMAND_SHARE:
            passenger.intent = TAXI
            passenger.taxi_stand = self.stand_for(passenger.destination)
        return passenger

    @staticmethod
    def _count(service, when: datetime, share: float, rng: random.Random) -> int:
        mean = TRAIN_LOAD.get(service.train_type, DEFAULT_LOAD) * share * time_of_day_factor(when)
        return max(0, round(rng.gauss(mean, mean * 0.2)))

    def populate(self, train, now: datetime) -> None:
        """A timetable train appears on the map: fill its manifest with
        passengers who boarded before it reached us (stations earlier on
        its journey), and put passengers waiting for it at each of its
        later stops here."""
        service = train.service
        calls = list(getattr(service, "calls", ()) or ())
        local = [stop[2] for stop in train.stops[train.stop_index:]]
        if not calls or not local or local[0] not in calls:
            return
        rng = self._rng(service, now)
        first_here = calls.index(local[0])
        train.manifest = {}
        # Already aboard: the journey so far, off the map - people boarded at
        # each earlier call, and those going to a call before this map got
        # off there again (so a long run doesn't pile up passengers).
        for origin_index in range(first_here):
            share = ORIGIN_BOARDING_SHARE if origin_index == 0 else STOP_BOARDING_SHARE
            for _ in range(self._count(service, now, share, rng)):
                destination_index = rng.randrange(origin_index + 1, len(calls))
                if destination_index < first_here:
                    continue  # already got off before the map
                destination = calls[destination_index]
                passenger = self._plan_onward(
                    RailPassenger(calls[origin_index], destination, train_key(service), ON_TRAIN, name=_name(rng)), rng,
                )
                if self.booking_manager is not None:
                    self.booking_manager.consider(passenger, train, now, rng)
                _seat(passenger, train, rng)
                if passenger.car in _cars(train, "restaurant"):
                    # Been in the restaurant car for part of the journey already.
                    passenger.promille = round(rng.uniform(0.0, 2.0), 2) if rng.random() < DRINK_CHANCE_PER_LEG else 0.0
                train.manifest.setdefault(destination, []).append(passenger)
        # Waiting at this train's stops on the map (not its final one).
        platforms = {stop[2]: stop[5] for stop in train.stops[train.stop_index:] if len(stop) > 5}
        for station in local:
            index = calls.index(station) if station in calls else len(calls)
            if index >= len(calls) - 1:
                continue
            share = ORIGIN_BOARDING_SHARE if index == 0 else STOP_BOARDING_SHARE
            waiting = self.waiting.setdefault(station, {}).setdefault(train_key(service), [])
            for _ in range(self._count(service, now, share, rng)):
                destination = calls[rng.randrange(index + 1, len(calls))]
                passenger = self._plan_onward(RailPassenger(
                    station, destination, train_key(service), WAITING, waiting_since=now, platform=platforms.get(station),
                    name=_name(rng),
                ), rng)
                if self.booking_manager is not None:
                    self.booking_manager.consider(passenger, train, now, rng)
                waiting.append(passenger)

    def on_arrival(self, train, station: str, now: datetime) -> Tuple[List[RailPassenger], List[RailPassenger]]:
        """The train stopped at `station`: those going here get off first,
        then those waiting here for *this* train get on. Returns (who got
        off, who got on) so their visible representation can follow."""
        rng = random.Random(zlib.crc32(f"{self.seed}|{id(train)}|{station}|{now:%Y%m%d%H%M}".encode()))
        self._drinks(train, rng)  # the leg that just ended
        leaving = train.manifest.pop(station, [])
        for passenger in leaving:
            passenger.state, passenger.arrived_at = ARRIVED, now
        if leaving:
            self.arrived.setdefault(station, deque(maxlen=ARRIVED_KEPT_PER_STATION)).extend(leaving)
        boarding = self.waiting.get(station, {}).pop(train_key(train.service), []) if train.service else []
        for passenger in boarding:
            passenger.state = ON_TRAIN
            _seat(passenger, train, rng)
            train.manifest.setdefault(passenger.destination, []).append(passenger)
        for passenger in leaving:
            passenger.car = None
        self.alighted_total += len(leaving)
        self.boarded_total += len(boarding)
        return leaving, boarding

    @staticmethod
    def _drinks(train, rng: random.Random) -> None:
        restaurant = set(_cars(train, "restaurant"))
        if not restaurant:
            return
        for group in train.manifest.values():
            for passenger in group:
                if passenger.car in restaurant and rng.random() < DRINK_CHANCE_PER_LEG:
                    passenger.promille = min(MAX_PROMILLE, round(passenger.promille + rng.uniform(*DRINK_PROMILLE), 2))

    @staticmethod
    def in_car(train, car: int) -> List["RailPassenger"]:
        """Who sits in one car of the train (for the car's popup)."""
        return sorted(
            (p for group in train.manifest.values() for p in group if p.car == car),
            key=lambda p: (p.destination, p.name),
        )

    def forget(self, train) -> List[RailPassenger]:
        """The train left the map: nobody can board it here any more.
        Returns those dropped (their pedestrians must go too)."""
        if train.service is None:
            return []
        dropped = []
        for station in {stop[2] for stop in train.stops}:
            dropped.extend(self.waiting.get(station, {}).pop(train_key(train.service), None) or ())
        return dropped

    def waiting_count(self, station: str) -> int:
        return sum(len(group) for group in self.waiting.get(station, {}).values())
