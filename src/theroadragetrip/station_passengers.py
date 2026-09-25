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

import math
import random
from typing import Callable, Iterable, List, Optional, Tuple

from .pedestrian import closest_point_and_dist_to_segment

VISIBLE_RADIUS_M = 250.0  # stations this close to the view show their passengers
SYNC_INTERVAL_S = 1.0  # real seconds between visibility syncs
SPREAD_M = 25.0  # passengers scatter this far around their platform point
MAX_WALKWAY_DISTANCE_M = 60.0  # no walkway this close: stay data-only
TRACK_CLEARANCE_M = 2.0  # never stand on a track


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
        self.pedestrians.pedestrians.append(pedestrian)
        passenger.pedestrian = pedestrian if standing else None  # walkers are the pedestrian system's now
        return True

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
            self.show(passenger, standing=False)

    def dropped(self, passengers: Iterable) -> None:
        for passenger in passengers:
            self.hide(passenger)

    def update(self, dt: float, flow, stations: List[Tuple[str, Tuple[float, float]]], view_point) -> None:
        """About once a second: waiting passengers at stations near the
        view become standing pedestrians, those at stations out of view
        go back to data (their journey is untouched)."""
        self._since_sync += dt
        if self._since_sync < SYNC_INTERVAL_S or view_point is None:
            return
        self._since_sync = 0.0
        for name, point in stations:
            near = math.dist(point, view_point) <= VISIBLE_RADIUS_M
            for group in flow.waiting.get(name, {}).values():
                for passenger in group:
                    if near:
                        self.show(passenger, standing=True)
                    else:
                        self.hide(passenger)
