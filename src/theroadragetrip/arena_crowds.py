"""Small, bounded samples of Liiga crowds around the current city's arena."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from .calendar import finnish_local_time
from .geo import point_in_polygon
from .pedestrian import closest_point_and_dist_to_segment
from .sports_fixtures import load_sports_fixtures

ARRIVAL_BEFORE = timedelta(hours=1)
GAME_DURATION = timedelta(hours=2, minutes=30)
DEPARTURE_WINDOW = timedelta(minutes=30)
VISIBLE_RADIUS_M = 600.0
MAX_VISIBLE_SPECTATORS = 40
DEFAULT_VISIBLE_SPECTATORS = 24
TAXI_SHARE = 0.10
WEEKDAY_INTOXICATION_CHANCE = 0.10
WEEKEND_INTOXICATION_CHANCE = 0.35
INTOXICATION_PROMILLE = (0.5, 3.0)


def _local_time(value: str) -> datetime:
    utc = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    return finnish_local_time(utc)


def _arena_entrances(pedestrians, point: tuple[float, float], buildings=None) -> tuple[tuple[float, float], ...]:
    containing = []
    candidates = getattr(pedestrians, "buildings", ()) if buildings is None else buildings
    for building in candidates:
        bbox = getattr(building, "bbox", None)
        points = getattr(building, "points_m", ())
        if not bbox or not points:
            continue
        if bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3] \
                and point_in_polygon(*point, points):
            containing.append(building)
    if containing:
        building = max(
            containing,
            key=lambda candidate: (candidate.bbox[2] - candidate.bbox[0]) *
                                  (candidate.bbox[3] - candidate.bbox[1]),
        )
        building.arena_windows = True
        return tuple(dict.fromkeys(getattr(building, "entrances", ())))
    entrance_locations = getattr(pedestrians, "entrance_locations", ()) if buildings is None else (
        entrance for building in candidates for entrance in getattr(building, "entrances", ())
    )
    return tuple(dict.fromkeys(
        entrance for entrance in entrance_locations
        if math.dist(point, entrance) <= 150.0
    ))


@dataclass
class ArenaEvent:
    fixture_id: str
    start: datetime
    point: tuple[float, float]
    visible_total: int
    home_team: str = ""
    away_team: str = ""
    venue_name: str = ""
    entrances: tuple[tuple[float, float], ...] = ()
    next_entrance: int = 0
    arrivals_spawned: int = 0
    departures_spawned: int = 0
    arrivals: list = field(default_factory=list)


class ArenaCrowds:
    """Turn local Liiga fixtures into a few visible pedestrians near the taxi."""

    def __init__(self, pedestrians, taxi_stops, city: str, fixtures: Iterable[dict] | None = None,
                 to_metres=None, seed: int = 0) -> None:
        self.pedestrians = pedestrians
        self.taxi_stops = taxi_stops
        self.rng = random.Random(seed)
        self._next_update: datetime | None = None
        if to_metres is None:
            from .world_loader import latlon_to_world_metres
            to_metres = latlon_to_world_metres()
        city_key = city.strip().casefold()
        self.events = []
        for match in fixtures if fixtures is not None else load_sports_fixtures():
            venue = match.get("venue", {})
            if match.get("competition") != "liiga" or str(venue.get("city", "")).casefold() != city_key:
                continue
            latitude, longitude = venue.get("latitude"), venue.get("longitude")
            if latitude is None or longitude is None:
                continue
            attendance = match.get("attendance")
            visible = DEFAULT_VISIBLE_SPECTATORS if attendance is None else max(
                8, min(MAX_VISIBLE_SPECTATORS, round(attendance / 150)),
            )
            point = to_metres(latitude, longitude)
            self.events.append(ArenaEvent(
                match["id"], _local_time(match["start"]), point, visible,
                home_team=match.get("home_team", ""), away_team=match.get("away_team", ""),
                venue_name=venue.get("name", ""), entrances=_arena_entrances(pedestrians, point),
            ))

    def schedule_on(self, day: date) -> list[ArenaEvent]:
        """The current city's Liiga games on a Finnish local calendar day."""
        return sorted((event for event in self.events if event.start.date() == day), key=lambda event: event.start)

    def sync_buildings(self, buildings) -> None:
        for event in self.events:
            event.entrances = _arena_entrances(self.pedestrians, event.point, buildings)

    def lights_on(self, now: datetime) -> bool:
        """Whether an arena is occupied for arrivals, a game, or departures."""
        return any(event.start - ARRIVAL_BEFORE <= now < event.start + GAME_DURATION + DEPARTURE_WINDOW
                   for event in self.events)

    def update(self, now: datetime, taxi_position: tuple[float, float]) -> None:
        if self._next_update is not None and now < self._next_update:
            return
        self._next_update = now + timedelta(seconds=10)
        for event in self.events:
            arrival_start = event.start - ARRIVAL_BEFORE
            departure_start = event.start + GAME_DURATION
            if now >= event.start:
                self._move_arrivals_inside(event)
            if math.dist(event.point, taxi_position) > VISIBLE_RADIUS_M:
                continue
            if arrival_start <= now < event.start:
                progress = (now - arrival_start) / ARRIVAL_BEFORE
                self._spawn_arrivals(event, round(event.visible_total * progress))
            elif event.start <= now < departure_start:
                pass
            elif departure_start <= now < departure_start + DEPARTURE_WINDOW:
                progress = (now - departure_start) / DEPARTURE_WINDOW
                self._spawn_departures(event, round(event.visible_total * progress))

    def _spawn_at_arena(self, event: ArenaEvent):
        for _ in event.entrances:
            entrance = event.entrances[event.next_entrance]
            event.next_entrance = (event.next_entrance + 1) % len(event.entrances)
            pedestrian = self.pedestrians.spawn_pedestrian_at_door(*entrance)
            if pedestrian is not None:
                self.pedestrians.add_pedestrian(pedestrian)
                return pedestrian

        pedestrian = self.pedestrians.spawn_pedestrian_at(
            *event.point, heading=self.rng.uniform(-math.pi, math.pi),
        ) if not event.entrances else None
        if pedestrian is not None:
            start = pedestrian.way.points_m[pedestrian.segment_idx]
            end = pedestrian.way.points_m[pedestrian.segment_idx + 1]
            pedestrian.x, pedestrian.y, _, _ = closest_point_and_dist_to_segment(
                *event.point, *start, *end,
            )
            self.pedestrians.add_pedestrian(pedestrian)
        return pedestrian

    def _spawn_arrivals(self, event: ArenaEvent, target: int) -> None:
        while event.arrivals_spawned < target:
            pedestrian = self._spawn_at_arena(event)
            if pedestrian is None:
                break
            event.arrivals_spawned += 1
            pedestrian.held_by = self
            event.arrivals.append(pedestrian)

    def _move_arrivals_inside(self, event: ArenaEvent) -> None:
        if not event.arrivals:
            return
        for pedestrian in event.arrivals:
            if pedestrian in self.pedestrians.pedestrians:
                self.pedestrians.pedestrians.remove(pedestrian)
        event.arrivals.clear()

    def _spawn_departures(self, event: ArenaEvent, target: int) -> None:
        stand = min(
            self.taxi_stops,
            key=lambda item: math.dist(event.point, (item.x, item.y)),
            default=None,
        )
        while event.departures_spawned < target:
            pedestrian = self._spawn_at_arena(event)
            if pedestrian is None:
                break
            wants_taxi = self.rng.random() < TAXI_SHARE
            if wants_taxi:
                pedestrian.wants_taxi = True
            if wants_taxi and stand is not None:
                destination = self.pedestrians._taxi_stop_waiting_position(stand)
                pedestrian.route = self.pedestrians._footway_route_to(pedestrian, destination)
                pedestrian.current_route_segment = 1
                pedestrian.destination = pedestrian.taxi_stop_target = destination
                pedestrian.is_walking_to_taxi_stop = True
            self._apply_departure_intoxication(event, pedestrian)
            event.departures_spawned += 1

    def _apply_departure_intoxication(self, event: ArenaEvent, pedestrian) -> None:
        residents = getattr(self.pedestrians, "residents", None)
        resident = residents.get(getattr(pedestrian, "resident_id", None)) if residents is not None else None
        if resident is None:
            return
        birthday = resident.birth_date
        match_day = event.start.date()
        age = match_day.year - birthday.year - (
            (match_day.month, match_day.day) < (birthday.month, birthday.day)
        )
        if age <= 18:
            return
        chance = WEEKEND_INTOXICATION_CHANCE if event.start.weekday() in (4, 5) \
            else WEEKDAY_INTOXICATION_CHANCE
        if self.rng.random() < chance:
            pedestrian.is_drunk = True
            pedestrian.blood_alcohol_promille = self.rng.uniform(*INTOXICATION_PROMILLE)
