"""Visible rail passengers (trains phase 5): the bridge between passenger
data (train_passengers.py, the source of truth) and the ordinary
pedestrian NPC system, which draws and moves them.

A passenger is a pedestrian only while physically at a station near the
view - waiting (standing near their platform) or just off a train
(walking away like anyone else); on a train, or at a far station, only
data. Everything here is event-driven (train arrivals) plus one sync
about once a second for stations coming into / going out of view; the
pedestrian system does all per-frame work.
"""
from __future__ import annotations

import logging
import math
import random
import time
from collections import deque
from typing import Callable, Deque, Iterable, List, Optional, Tuple

from .pedestrian import closest_point_and_dist_to_segment
from .rail_bookings import PASSENGER_MET, PASSENGER_WAITING
from .train_passengers import ARRIVED, DRUNK_FROM_PROMILLE, TAXI, WAITING

logger = logging.getLogger(__name__)

VISIBLE_RADIUS_M = 250.0  # stations this close to the view show their passengers
SYNC_INTERVAL_S = 1.0  # real seconds between visibility syncs
SHOW_BUDGET_S = 0.002  # per frame for creating queued passenger pedestrians
SPREAD_M = 25.0  # passengers scatter this far around their platform point
MAX_WALKWAY_DISTANCE_M = 60.0  # no walkway this close: stay data-only
TRACK_CLEARANCE_M = 2.0  # never stand on a track
STAND_WALK_CHECK_M = 5.0  # sampling of a route's unmapped hops to a taxi stand for track crossings


def track_checker(railway_grid, clearance_m: float = TRACK_CLEARANCE_M) -> Callable[[Tuple[float, float]], bool]:
    """on_track(point) for StationPassengerView from the game's railway
    spatial grid: is any track segment within clearance_m."""
    from .geo import dist_point_to_segment

    def on_track(point) -> bool:
        x, y = point
        for railway in railway_grid.ways_in_rect(x - clearance_m, y - clearance_m, x + clearance_m, y + clearance_m):
            points = railway.points_m
            if any(dist_point_to_segment(x, y, a[0], a[1], b[0], b[1]) <= clearance_m for a, b in zip(points, points[1:])):
                return True
        return False

    return on_track


class StationPassengerView:
    def __init__(self, pedestrians, on_track: Optional[Callable[[Tuple[float, float]], bool]] = None, seed: int = 0) -> None:
        """pedestrians: pedestrian.PedestrianManager; on_track(point): is a
        railway track within TRACK_CLEARANCE_M there."""
        self.pedestrians = pedestrians
        self.on_track = on_track or (lambda point: False)
        self.rng = random.Random(seed)
        self._since_sync = SYNC_INTERVAL_S
        self._stand_spots = {}  # id(stand) -> its waiting spot on a walkway (computed once)
        self._pending: Deque = deque()  # (passenger, standing) waiting to get a pedestrian
        self._queued = set()
        # Passengers of accepted bookings shown at their destination: their
        # pedestrian stays linked (passenger.pedestrian) and held here until
        # the booking is no longer waiting.
        self._booked: List = []

    # -- placing and removing a passenger's pedestrian ------------------

    def _walkway_point(self, anchor) -> Optional[Tuple[float, float, object, int]]:
        """Nearest point on a walkable way (footway, platform path, ...)
        to a spot scattered around the anchor, off any track."""
        for _ in range(4):
            angle = self.rng.uniform(0.0, 2.0 * math.pi)
            radius = SPREAD_M * math.sqrt(self.rng.random())
            x, y = anchor[0] + math.cos(angle) * radius, anchor[1] + math.sin(angle) * radius
            best = None
            for way in self.pedestrians._nearby_ped_ways(x, y):
                for index, (a, b) in enumerate(zip(way.points_m, way.points_m[1:])):
                    px, py, _, distance = closest_point_and_dist_to_segment(x, y, a[0], a[1], b[0], b[1])
                    if best is None or distance < best[0]:
                        best = (distance, px, py, way, index)
            if best is None or math.dist((best[1], best[2]), anchor) > MAX_WALKWAY_DISTANCE_M:
                continue
            if not self.on_track((best[1], best[2])):
                return best[1], best[2], best[3], best[4]
        return None

    def show(self, passenger, standing: bool) -> bool:
        """Give the passenger a pedestrian at their station. Waiting ones
        stand (held: the pedestrian system won't cull them); arrivals walk
        off as ordinary pedestrians. False if no safe spot."""
        if passenger.pedestrian is not None or passenger.platform is None:
            return passenger.pedestrian is not None
        spot = self._walkway_point(passenger.platform)
        if spot is None:
            return False
        x, y, _, _ = spot
        pedestrian = self.pedestrians.spawn_pedestrian_at(
            x, y, heading=self.rng.uniform(-math.pi, math.pi), resident_id=passenger.resident_id,
        )
        if pedestrian is None:
            return False
        passenger.resident_id = pedestrian.resident_id  # the same person every time they are shown
        pedestrian.x, pedestrian.y = x, y  # on the walkway itself
        pedestrian.rail_passenger = passenger  # identity / debug: the journey behind this NPC
        if standing:
            pedestrian.speed = pedestrian.base_speed = 0.0
            pedestrian.held_by = self
        elif getattr(passenger, "promille", 0.0) >= DRUNK_FROM_PROMILLE:
            # Straight from the restaurant car: the pedestrian system's own drunk walk.
            pedestrian.is_drunk = True
            pedestrian.blood_alcohol_promille = passenger.promille
            pedestrian.drunk_phase = self.rng.uniform(0.0, 2.0 * math.pi)
            pedestrian.drunk_vomit_cooldown = self.rng.uniform(8.0, 25.0)
        if not standing and getattr(passenger, "intent", None) == TAXI and passenger.taxi_stand is not None:
            self._send_to_stand(pedestrian, passenger.taxi_stand)
        self.pedestrians.pedestrians.append(pedestrian)
        if not standing and self._is_booked(passenger):
            self._hold_booked(passenger, pedestrian)
        else:
            passenger.pedestrian = pedestrian if standing else None  # walkers are the pedestrian system's now
        return True

    @staticmethod
    def _is_booked(passenger) -> bool:
        """Waiting to be met, or greeted and walking to the taxi: their
        pedestrian stays linked and held until they board."""
        booking = getattr(passenger, "booking", None)
        return booking is not None and booking.status in (PASSENGER_WAITING, PASSENGER_MET)

    def _hold_booked(self, passenger, pedestrian) -> None:
        pedestrian.held_by = self
        passenger.pedestrian = pedestrian
        self._booked.append(passenger)

    def show_at_stand(self, passenger) -> bool:
        """A booked passenger whose train came in out of view: by now they
        wait at their stand - the same person, not a replacement."""
        stand = passenger.taxi_stand
        if passenger.pedestrian is not None or stand is None:
            return passenger.pedestrian is not None
        x, y = self._stand_spot(stand)
        pedestrian = self.pedestrians.spawn_pedestrian_at(x, y, resident_id=passenger.resident_id)
        if pedestrian is None:
            return False
        passenger.resident_id = pedestrian.resident_id
        pedestrian.x, pedestrian.y = x, y
        pedestrian.rail_passenger = passenger
        pedestrian.speed = pedestrian.base_speed = 0.0
        pedestrian.wants_taxi = pedestrian.is_taxi_stop_waiter = True
        self.pedestrians.pedestrians.append(pedestrian)
        self._hold_booked(passenger, pedestrian)
        return True

    def _stand_spot(self, stand) -> Tuple[float, float]:
        """Where waiting customers stand: the nearest walkway point to the
        stand (nearby walkways only - the pedestrian system's own version
        scans every walkway on the map). Computed once per stand."""
        key = id(stand)
        if key not in self._stand_spots:
            best = None
            for way in self.pedestrians._nearby_ped_ways(stand.x, stand.y):
                for a, b in zip(way.points_m, way.points_m[1:]):
                    px, py, _, distance = closest_point_and_dist_to_segment(stand.x, stand.y, a[0], a[1], b[0], b[1])
                    if best is None or distance < best[0]:
                        best = (distance, (px, py))
            self._stand_spots[key] = best[1] if best is not None else (stand.x, stand.y)
        return self._stand_spots[key]

    def _send_to_stand(self, pedestrian, stand) -> None:
        """The pedestrian system's own taxi-stand walk (a footway route to
        the stand's waiting spot, then waiting there as a customer), planned
        once here. The route's mapped footway edges are trusted; its
        unmapped straight hops (onto the network at the start, off it at
        the end, or the whole way when there is no network route) must
        cross no track or building - else they just walk off."""
        target = self._stand_spot(stand)
        route = self.pedestrians._footway_route_to(pedestrian, target)
        hops = {index for index in (0, len(route) - 3, len(route) - 2) if 0 <= index < len(route) - 1}
        for index in sorted(hops):
            a, b = route[index], route[index + 1]
            steps = max(1, int(math.dist(a, b) // STAND_WALK_CHECK_M))
            blocked = "track" if any(
                self.on_track((a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps))
                for i in range(steps + 1)
            ) else "building" if self.pedestrians._path_crosses_building(a[0], a[1], b[0], b[1]) else None
            if blocked is not None:
                logger.info(
                    "Rail passenger walks off, no safe route to taxi stand (%.0f, %.0f): %s on hop %d of %d-point route",
                    stand.x, stand.y, blocked, index, len(route),
                )
                return
        pedestrian.route, pedestrian.destination, pedestrian.current_route_segment = route, target, 1
        pedestrian.taxi_stop_target = target
        pedestrian.is_walking_to_taxi_stop = True
        pedestrian.wants_taxi = True

    def hide(self, passenger) -> None:
        pedestrian, passenger.pedestrian = passenger.pedestrian, None
        if pedestrian is not None:
            try:
                self.pedestrians.pedestrians.remove(pedestrian)
            except ValueError:
                pass  # already gone

    # -- events ------------------------------------------------------------

    def on_arrival(self, leaving: Iterable, boarding: Iterable, station_point, view_point) -> None:
        """Boarders vanish into the train; arrivals step off and walk away
        (only where someone could see it)."""
        for passenger in boarding:
            self.hide(passenger)
        if view_point is None or math.dist(station_point, view_point) > VISIBLE_RADIUS_M:
            return
        for passenger in leaving:
            passenger.platform = passenger.platform or station_point
            self._queue(passenger, standing=False)

    def dropped(self, passengers: Iterable) -> None:
        for passenger in passengers:
            self.hide(passenger)

    def _queue(self, passenger, standing: bool) -> None:
        if passenger.pedestrian is None and id(passenger) not in self._queued:
            self._queued.add(id(passenger))
            self._pending.append((passenger, standing))

    def _show_pending(self) -> None:
        """Create queued pedestrians for up to SHOW_BUDGET_S per frame (at
        least one): a full train stepping off at once is ~100 pedestrians,
        ~150 ms if made in one frame."""
        deadline = time.perf_counter() + SHOW_BUDGET_S
        while self._pending:
            passenger, standing = self._pending.popleft()
            self._queued.discard(id(passenger))
            still_there = passenger.state == (WAITING if standing else ARRIVED)
            if still_there:
                self.show(passenger, standing=standing)
                if time.perf_counter() >= deadline:
                    break

    def update(self, dt: float, flow, stations: List[Tuple[str, Tuple[float, float]]], view_point, bookings=()) -> None:
        """Every frame: make some queued pedestrians. About once a second:
        waiting passengers at stations near the view are queued to become
        standing pedestrians, those at stations out of view go back to data
        (their journey is untouched); the same for booked passengers
        (bookings: those PASSENGER_WAITING) at their stands."""
        self._show_pending()
        self._since_sync += dt
        if self._since_sync < SYNC_INTERVAL_S or view_point is None:
            return
        self._since_sync = 0.0
        self._sync_booked(dict(stations), view_point, bookings)
        for name, point in stations:
            near = math.dist(point, view_point) <= VISIBLE_RADIUS_M
            for group in flow.waiting.get(name, {}).values():
                for passenger in group:
                    if near:
                        self._queue(passenger, standing=True)
                    else:
                        self.hide(passenger)

    def _sync_booked(self, stations, view_point, bookings) -> None:
        # Met, boarded or missed: the pedestrian (if still around) is an
        # ordinary one again.
        for passenger in [p for p in self._booked if not self._is_booked(p)]:
            self._booked.remove(passenger)
            if passenger.pedestrian is not None:
                passenger.pedestrian.held_by = None
                passenger.pedestrian = None
        for booking in bookings:
            passenger = booking.passenger
            point = stations.get(booking.station)
            if point is not None and math.dist(point, view_point) <= VISIBLE_RADIUS_M:
                if passenger.pedestrian is None and id(passenger) not in self._queued:
                    self.show_at_stand(passenger)
            elif passenger.pedestrian is not None:
                self.hide(passenger)
                self._booked.remove(passenger)
