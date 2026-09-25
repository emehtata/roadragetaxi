"""NPC trains running back and forth on OSM railway=rail track (phase 1).

Visual traffic only: no stations, timetables, signals or collisions. Each
connected rail network gets one TrainRoute - its longest end-to-end line,
following the real track geometry - built once when the railways change,
never per frame. Trains then just advance a distance along that polyline
and reverse at its ends (a network end, or where the loaded map stops).
"""
from __future__ import annotations

import bisect
import heapq
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .train_timetable import ScheduledPass, StationCall, TimetableClock, match_timetable, prepare_timetable, station_calls

logger = logging.getLogger(__name__)

TRAIN_ENABLED = True
TRAIN_SPAWN_INTERVAL_S = 30.0 * 60.0  # game seconds between spawns, per route and direction
TRAIN_SPEED_MPS = 22.0  # ~80 km/h, constant
# Trains move in real time while the game clock runs up to 60x, so a busy
# line can have many timetable trains crossing the map at once.
MAX_ACTIVE_TRAINS = 16
# Oulu's rail pieces run from a few metres (yard stubs) to kilometres; a
# train of TRAIN_CARS cars is ~150 m, so shorter lines would look silly.
MIN_TRAIN_ROUTE_LENGTH_M = 1000.0
TRAIN_CARS = 6  # locomotive + 5 carriages
TRAIN_CAR_LENGTH_M = 24.0
TRAIN_CAR_GAP_M = 1.5
TRAIN_WIDTH_M = 3.2
TRAIN_LENGTH_M = TRAIN_CARS * (TRAIN_CAR_LENGTH_M + TRAIN_CAR_GAP_M) - TRAIN_CAR_GAP_M
TRAIN_ACCELERATION_MPS2 = 0.6  # brake into / pull out of a station: ~40 s from 80 km/h
# Railway simulation time runs 1:1 with real time - trains move at real
# speed while the game clock runs up to 60x - so a timetable dwell of 2 min
# is a 2 min (real) stop, not 2 s. Tune here, never via the game clock.
DWELL_REAL_S_PER_TIMETABLE_S = 1.0
# Trains run in real time while the game clock runs up to 60x, so a train
# is spawned this far before its first stop and early enough (game time =
# its real approach time x the current game speed) to come to rest there
# at the scheduled arrival - usually off-screen, from the correct side.
APPROACH_DISTANCE_M = 1500.0
APPROACH_REAL_S = (
    (APPROACH_DISTANCE_M - TRAIN_SPEED_MPS ** 2 / (2 * TRAIN_ACCELERATION_MPS2)) / TRAIN_SPEED_MPS
    + TRAIN_SPEED_MPS / TRAIN_ACCELERATION_MPS2
)
_MERGE_M = 0.5  # track points closer than this are one node (tile seams share OSM nodes)


@dataclass
class TrainRoute:
    """A polyline with cumulative distances: point_at(s) is O(log n)."""

    points: List[Tuple[float, float]]
    cumulative: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.cumulative:
            total = 0.0
            self.cumulative = [0.0]
            for a, b in zip(self.points, self.points[1:]):
                total += math.dist(a, b)
                self.cumulative.append(total)

    @property
    def length(self) -> float:
        return self.cumulative[-1]

    def point_at(self, s: float) -> Tuple[float, float, float]:
        """(x, y, heading) at distance s along the route, clamped to it."""
        s = min(max(s, 0.0), self.length)
        i = min(max(bisect.bisect_right(self.cumulative, s) - 1, 0), len(self.points) - 2)
        (ax, ay), (bx, by) = self.points[i], self.points[i + 1]
        seg = self.cumulative[i + 1] - self.cumulative[i]
        t = (s - self.cumulative[i]) / seg if seg > 0 else 0.0
        return ax + (bx - ax) * t, ay + (by - ay) * t, math.atan2(by - ay, bx - ax)


@dataclass
class Train:
    route: TrainRoute
    distance_m: float  # of the locomotive along the route
    direction: int  # +1 towards the route's end, -1 towards its start
    speed_mps: float = TRAIN_SPEED_MPS  # line speed
    service: Optional[ScheduledPass] = None  # timetable identity; None = phase-1 shuttle
    # Timetable stop state: RUNNING between stations, DWELLING at one.
    state: str = "RUNNING"
    stop_index: int = 0  # next entry of service.stops
    dwell_remaining_s: float = 0.0
    current_speed_mps: Optional[float] = None  # enters the map at line speed

    def __post_init__(self) -> None:
        if self.current_speed_mps is None:
            self.current_speed_mps = self.speed_mps

    @property
    def debug_label(self) -> str:
        """Timetable identity + state, for the debug overlay."""
        if self.service is None:
            return "shuttle"
        stop = self.next_stop
        if self.state == "DWELLING" and stop is not None:
            return f"{self.service.label} DWELLING {stop[2]} {self.dwell_remaining_s:.0f}s"
        return f"{self.service.label} RUNNING" + (f" -> {stop[2]}" if stop is not None else " -> leaving")

    @property
    def next_stop(self):
        stops = self.service.stops if self.service is not None else ()
        return stops[self.stop_index] if self.stop_index < len(stops) else None

    def _stop_position(self, stop) -> float:
        """Locomotive position that centres the train on the station."""
        return min(max(stop[0] + self.direction * TRAIN_LENGTH_M / 2, 0.0), self.route.length)

    def update(self, dt: float) -> None:
        """dt in real seconds (railway simulation time, see
        DWELL_REAL_S_PER_TIMETABLE_S) - never the accelerated game time."""
        if self.state == "DWELLING":
            self.dwell_remaining_s -= dt
            if self.dwell_remaining_s > 0.0:
                return
            self.state, self.stop_index = "RUNNING", self.stop_index + 1
        stop = self.next_stop
        speed = min(self.speed_mps, self.current_speed_mps + TRAIN_ACCELERATION_MPS2 * dt)
        if stop is not None:
            to_stop = (self._stop_position(stop) - self.distance_m) * self.direction
            # Brake so the train comes to rest exactly at the platform.
            speed = min(speed, math.sqrt(2.0 * TRAIN_ACCELERATION_MPS2 * max(to_stop, 0.0)))
            if to_stop <= max(speed * dt, 0.05):
                self.distance_m = self._stop_position(stop)
                self.current_speed_mps = 0.0
                self.state = "DWELLING"
                self.dwell_remaining_s = stop[1] * DWELL_REAL_S_PER_TIMETABLE_S
                return
        self.current_speed_mps = speed
        self.distance_m += self.direction * speed * dt
        if self.distance_m >= self.route.length:
            self.distance_m, self.direction = self.route.length, -1
        elif self.distance_m <= 0.0:
            self.distance_m, self.direction = 0.0, 1

    def cars(self) -> List[Tuple[float, float, float]]:
        """(x, y, heading) of each car's centre, locomotive first; the rest
        trail behind it along the track (so they bend through curves)."""
        pitch = TRAIN_CAR_LENGTH_M + TRAIN_CAR_GAP_M
        result = []
        for index in range(TRAIN_CARS):
            x, y, heading = self.route.point_at(self.distance_m - self.direction * (index * pitch + TRAIN_CAR_LENGTH_M / 2))
            result.append((x, y, heading if self.direction > 0 else heading + math.pi))
        return result


def build_train_routes(railways: Sequence, min_length_m: float = MIN_TRAIN_ROUTE_LENGTH_M) -> List[TrainRoute]:
    """One route per connected railway=rail network: the path between its
    two farthest-apart ends (double Dijkstra, the tree-diameter trick -
    exact on tree-like lines, a good long line through yards/crossovers).
    Networks are only joined where their track actually shares points."""
    key_of: Dict[Tuple[int, int], int] = {}
    points: List[Tuple[float, float]] = []
    edges: Dict[int, Dict[int, float]] = {}

    def node(p) -> int:
        key = (round(p[0] / _MERGE_M), round(p[1] / _MERGE_M))
        if key not in key_of:
            key_of[key] = len(points)
            points.append((float(p[0]), float(p[1])))
        return key_of[key]

    for railway in railways:
        if getattr(railway, "kind", "rail") != "rail":
            continue
        ids = [node(p) for p in railway.points_m]
        for a, b in zip(ids, ids[1:]):
            if a != b:
                d = math.dist(points[a], points[b])
                edges.setdefault(a, {})[b] = d
                edges.setdefault(b, {})[a] = d

    def farthest(start: int) -> Tuple[int, Dict[int, int], set]:
        dist, previous, done = {start: 0.0}, {}, set()
        heap = [(0.0, start)]
        best = start
        while heap:
            d, n = heapq.heappop(heap)
            if n in done:
                continue
            done.add(n)
            if d > dist[best]:
                best = n
            for m, w in edges[n].items():
                if d + w < dist.get(m, math.inf):
                    dist[m], previous[m] = d + w, n
                    heapq.heappush(heap, (d + w, m))
        return best, previous, done

    routes, seen = [], set()
    for start in sorted(edges):
        if start in seen:
            continue
        a, _, component = farthest(start)
        seen |= component
        b, previous, _ = farthest(a)
        path = [b]
        while path[-1] != a:
            path.append(previous[path[-1]])
        route = TrainRoute([points[n] for n in path])
        if route.length >= min_length_m:
            routes.append(route)
    return routes


class RailwayManager:
    """Owns the train routes and trains; main() calls rebuild() when the
    railways list changes and update() once per frame."""

    def __init__(
        self,
        railways: Sequence = (),
        timetable: Optional[dict] = None,
        to_metres: Optional[Callable[[float, float], Tuple[float, float]]] = None,
    ) -> None:
        """With a timetable (train_timetable.load_timetable) and a
        lat/lon -> world metres function, trains run to it; without, the
        phase-1 fixed interval keeps the track alive."""
        self.routes: List[TrainRoute] = []
        self.trains: List[Train] = []
        self.timetable = timetable
        self.to_metres = to_metres
        self.clock: Optional[TimetableClock] = None
        # (station name, position, arrivals clock) for timetable stations on this map.
        self.stations: List[Tuple[str, Tuple[float, float], TimetableClock]] = []
        self._prepared = prepare_timetable(timetable, to_metres) if timetable is not None and to_metres is not None else None
        self._spawn_timers: Dict[Tuple[int, int], float] = {}
        self.rebuild(railways)

    def rebuild(self, railways: Sequence) -> None:
        if not TRAIN_ENABLED:
            return
        self.routes = build_train_routes(railways)
        if self.timetable is not None and self.to_metres is not None:
            self.clock = TimetableClock(match_timetable(self.timetable, self.routes, prepared=self._prepared))
            self.stations = [
                (name, point, TimetableClock(calls))
                for name, point, calls in station_calls(self.timetable, self._prepared, self.routes)
            ]
            self._spawn_timers = {}
            logger.info(
                "Railway timetable: %d of %d trains pass this map's routes",
                len({(p.train_type, p.number) for p in self.clock.passes}), len(self.timetable["trains"]),
            )
        else:
            # Due immediately, so a new map shows traffic without a 30 min wait.
            self._spawn_timers = {(i, d): 0.0 for i in range(len(self.routes)) for d in (1, -1)}
        # Trains on replaced routes keep running on their old geometry (the
        # track is still there) until their next turnaround (update()).
        logger.info(
            "Railways: %d train routes (%s km), %d active trains",
            len(self.routes), ", ".join(f"{r.length / 1000:.1f}" for r in self.routes) or "-", len(self.trains),
        )

    def _spawn(self, service: ScheduledPass) -> Train:
        route = self.routes[service.route_index]
        entry = 0.0 if service.direction > 0 else route.length
        train = Train(route, entry, service.direction, service=service)
        if service.stops:
            # APPROACH_DISTANCE_M before the first stop, never beyond the
            # entry end (then it simply arrives a little early).
            start = train._stop_position(service.stops[0]) - service.direction * APPROACH_DISTANCE_M
            train.distance_m = min(max(start, 0.0), route.length)
        return train

    def next_arrival(self, x: float, y: float, now: datetime) -> Optional[Tuple[datetime, StationCall]]:
        """Next timetable train arriving at the station nearest (x, y)."""
        if not self.stations:
            return None
        _, _, clock = min(self.stations, key=lambda station: math.dist(station[1], (x, y)))
        return clock.next_after(now)

    def update(self, dt: float, game_dt: float, now: Optional[datetime] = None) -> None:
        """dt moves trains (real seconds, like every vehicle); now (the
        game clock, naive Finnish time) drives timetable spawns, game_dt
        the fallback interval - both follow the game's time scale."""
        if not TRAIN_ENABLED:
            return
        current = {id(route) for route in self.routes}
        kept = []
        for train in self.trains:
            direction = train.direction
            train.update(dt)
            # A timetable train leaves the map at the far end; a train on a
            # replaced route (more track streamed in) retires at its next
            # turnaround - at a track end, never mid-view.
            if train.direction == direction or (train.service is None and id(train.route) in current):
                kept.append(train)
        self.trains = kept
        if self.clock is not None and now is not None:
            game_speed = game_dt / dt if dt > 0.0 else 0.0
            for service in self.clock.due(now, timedelta(seconds=APPROACH_REAL_S * game_speed)):
                if len(self.trains) >= MAX_ACTIVE_TRAINS or service.route_index >= len(self.routes):
                    continue
                self.trains.append(self._spawn(service))
        for key in self._spawn_timers:
            self._spawn_timers[key] -= game_dt
            if self._spawn_timers[key] > 0.0 or len(self.trains) >= MAX_ACTIVE_TRAINS:
                continue
            self._spawn_timers[key] = TRAIN_SPAWN_INTERVAL_S
            route_index, direction = key
            route = self.routes[route_index]
            # Enters from the route's end: a map edge or a track end.
            self.trains.append(Train(route, 0.0 if direction > 0 else route.length, direction))
