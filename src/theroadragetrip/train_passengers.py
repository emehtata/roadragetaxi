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

import random
import zlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

WAITING, ON_TRAIN, ARRIVED = "WAITING_AT_STATION", "ON_TRAIN", "ARRIVED"

# Passengers aboard a train when it is full-ish, by train type (GTFS route
# short name prefix); others use DEFAULT_LOAD. Tunable, not ticket data.
TRAIN_LOAD = {"IC": 120, "S": 150, "PYO": 90, "P": 60, "H": 40}
DEFAULT_LOAD = 60
# Share of the load boarding at a stop: the journey's first station fills
# the train, later stops add fewer as it empties towards the end.
ORIGIN_BOARDING_SHARE = 0.8
STOP_BOARDING_SHARE = 0.25
ARRIVED_KEPT_PER_STATION = 200  # recent arrivals kept for the next phase / debug


def time_of_day_factor(when: datetime) -> float:
    hour = when.hour
    if 7 <= hour < 9 or 15 <= hour < 18:
        return 1.3  # rush hours
    if hour < 5 or hour >= 23:
        return 0.3  # night
    return 1.0


@dataclass
class RailPassenger:
    origin: str
    destination: str
    train: Tuple[str, str]  # (train type, number) of the one train they take
    state: str = WAITING
    waiting_since: Optional[datetime] = None
    arrived_at: Optional[datetime] = None


def train_key(service) -> Tuple[str, str]:
    return service.train_type, service.number


class PassengerFlow:
    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        # station -> train key -> passengers waiting for that train there
        self.waiting: Dict[str, Dict[Tuple[str, str], List[RailPassenger]]] = {}
        self.arrived: Dict[str, Deque[RailPassenger]] = {}
        self.boarded_total = 0
        self.alighted_total = 0

    def _rng(self, service, when: datetime) -> random.Random:
        # Same train on the same day -> the same passengers (debuggable).
        key = f"{self.seed}|{service.train_type}|{service.number}|{when:%Y-%m-%d}"
        return random.Random(zlib.crc32(key.encode()))

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
                passenger = RailPassenger(calls[origin_index], destination, train_key(service), ON_TRAIN)
                train.manifest.setdefault(destination, []).append(passenger)
        # Waiting at this train's stops on the map (not its final one).
        for station in local:
            index = calls.index(station) if station in calls else len(calls)
            if index >= len(calls) - 1:
                continue
            share = ORIGIN_BOARDING_SHARE if index == 0 else STOP_BOARDING_SHARE
            waiting = self.waiting.setdefault(station, {}).setdefault(train_key(service), [])
            for _ in range(self._count(service, now, share, rng)):
                destination = calls[rng.randrange(index + 1, len(calls))]
                waiting.append(RailPassenger(station, destination, train_key(service), WAITING, waiting_since=now))

    def on_arrival(self, train, station: str, now: datetime) -> Tuple[int, int]:
        """The train stopped at `station`: those going here get off first,
        then those waiting here for *this* train get on. Returns (off, on)."""
        leaving = train.manifest.pop(station, [])
        for passenger in leaving:
            passenger.state, passenger.arrived_at = ARRIVED, now
        if leaving:
            self.arrived.setdefault(station, deque(maxlen=ARRIVED_KEPT_PER_STATION)).extend(leaving)
        boarding = self.waiting.get(station, {}).pop(train_key(train.service), []) if train.service else []
        for passenger in boarding:
            passenger.state = ON_TRAIN
            train.manifest.setdefault(passenger.destination, []).append(passenger)
        self.alighted_total += len(leaving)
        self.boarded_total += len(boarding)
        return len(leaving), len(boarding)

    def forget(self, train) -> None:
        """The train left the map: nobody can board it here any more."""
        if train.service is None:
            return
        for station in {stop[2] for stop in train.stops}:
            self.waiting.get(station, {}).pop(train_key(train.service), None)

    def waiting_count(self, station: str) -> int:
        return sum(len(group) for group in self.waiting.get(station, {}).values())
