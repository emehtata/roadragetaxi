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
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

TRAIN_ENABLED = True
TRAIN_SPAWN_INTERVAL_S = 30.0 * 60.0  # game seconds between spawns, per route and direction
TRAIN_SPEED_MPS = 22.0  # ~80 km/h, constant
MAX_ACTIVE_TRAINS = 6
# Oulu's rail pieces run from a few metres (yard stubs) to kilometres; a
# train of TRAIN_CARS cars is ~150 m, so shorter lines would look silly.
MIN_TRAIN_ROUTE_LENGTH_M = 1000.0
TRAIN_CARS = 6  # locomotive + 5 carriages
TRAIN_CAR_LENGTH_M = 24.0
TRAIN_CAR_GAP_M = 1.5
TRAIN_WIDTH_M = 3.2
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
    speed_mps: float = TRAIN_SPEED_MPS

    def update(self, dt: float) -> None:
        self.distance_m += self.direction * self.speed_mps * dt
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

    def __init__(self, railways: Sequence = ()) -> None:
        self.routes: List[TrainRoute] = []
        self.trains: List[Train] = []
        self._spawn_timers: Dict[Tuple[int, int], float] = {}
        self.rebuild(railways)

    def rebuild(self, railways: Sequence) -> None:
        if not TRAIN_ENABLED:
            return
        self.routes = build_train_routes(railways)
        # Due immediately, so a new map shows traffic without a 30 min wait.
        self._spawn_timers = {(i, d): 0.0 for i in range(len(self.routes)) for d in (1, -1)}
        # Trains on replaced routes keep running on their old geometry (the
        # track is still there) until their next turnaround (update()).
        logger.info(
            "Railways: %d train routes (%s km), %d active trains",
            len(self.routes), ", ".join(f"{r.length / 1000:.1f}" for r in self.routes) or "-", len(self.trains),
        )

    def update(self, dt: float, game_dt: float) -> None:
        """dt moves trains (real seconds, like every vehicle); game_dt runs
        the spawn clock, so intervals follow the game's time scale."""
        if not TRAIN_ENABLED:
            return
        current = {id(route) for route in self.routes}
        kept = []
        for train in self.trains:
            direction = train.direction
            train.update(dt)
            # A train on a replaced route (the map streamed in more track)
            # retires at its next turnaround - at a track end, not mid-view.
            if train.direction == direction or id(train.route) in current:
                kept.append(train)
        self.trains = kept
        for key in self._spawn_timers:
            self._spawn_timers[key] -= game_dt
            if self._spawn_timers[key] > 0.0 or len(self.trains) >= MAX_ACTIVE_TRAINS:
                continue
            self._spawn_timers[key] = TRAIN_SPAWN_INTERVAL_S
            route_index, direction = key
            route = self.routes[route_index]
            # Enters from the route's end: a map edge or a track end.
            self.trains.append(Train(route, 0.0 if direction > 0 else route.length, direction))
