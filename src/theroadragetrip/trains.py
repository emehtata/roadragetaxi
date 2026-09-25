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
    # Stops along *this train's* route: (distance along route, dwell, name,
    # ...). Defaults to the service's stops on the shared network route.
    stops: Optional[tuple] = None

    def __post_init__(self) -> None:
        if self.current_speed_mps is None:
            self.current_speed_mps = self.speed_mps
        if self.stops is None:
            self.stops = self.service.stops if self.service is not None else ()

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
        return self.stops[self.stop_index] if self.stop_index < len(self.stops) else None

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


@dataclass
class RailGraph:
    """railway=rail track as a graph: OSM points merged within _MERGE_M
    (ways meeting at a shared OSM node - a switch - connect; tracks that
    merely run close together never do), undirected edges in metres, and
    a coarse node grid for "which track passes this station"."""

    points: List[Tuple[float, float]] = field(default_factory=list)
    edges: Dict[int, Dict[int, float]] = field(default_factory=dict)
    key_of: Dict[Tuple[int, int], int] = field(default_factory=dict)
    grid: Dict[Tuple[int, int], List[int]] = field(default_factory=dict)

    GRID_M = 100.0

    def node_at(self, point) -> Optional[int]:
        return self.key_of.get((round(point[0] / _MERGE_M), round(point[1] / _MERGE_M)))

    def nodes_near(self, point, radius: float) -> List[int]:
        cx, cy = int(point[0] // self.GRID_M), int(point[1] // self.GRID_M)
        reach = int(radius // self.GRID_M) + 1
        return [
            n for gx in range(cx - reach, cx + reach + 1) for gy in range(cy - reach, cy + reach + 1)
            for n in self.grid.get((gx, gy), ()) if math.dist(self.points[n], point) <= radius
        ]


NODE_SPACING_M = 50.0


def build_rail_graph(railways: Sequence) -> RailGraph:
    graph = RailGraph()

    def node(p) -> int:
        key = (round(p[0] / _MERGE_M), round(p[1] / _MERGE_M))
        if key not in graph.key_of:
            graph.key_of[key] = len(graph.points)
            graph.points.append((float(p[0]), float(p[1])))
            graph.grid.setdefault((int(p[0] // graph.GRID_M), int(p[1] // graph.GRID_M)), []).append(graph.key_of[key])
        return graph.key_of[key]

    for railway in railways:
        if getattr(railway, "kind", "rail") != "rail":
            continue
        # Long straight OSM segments get extra nodes every <= NODE_SPACING_M
        # so a station always has track nodes to stop at.
        dense = [railway.points_m[0]] if railway.points_m else []
        for p, q in zip(railway.points_m, railway.points_m[1:]):
            pieces = max(1, math.ceil(math.dist(p, q) / NODE_SPACING_M))
            dense.extend((p[0] + (q[0] - p[0]) * i / pieces, p[1] + (q[1] - p[1]) * i / pieces) for i in range(1, pieces + 1))
        ids = [node(p) for p in dense]
        for a, b in zip(ids, ids[1:]):
            if a != b:
                d = math.dist(graph.points[a], graph.points[b])
                graph.edges.setdefault(a, {})[b] = d
                graph.edges.setdefault(b, {})[a] = d
    return graph


def build_train_routes(
    railways: Sequence, min_length_m: float = MIN_TRAIN_ROUTE_LENGTH_M, graph: Optional[RailGraph] = None,
) -> List[TrainRoute]:
    """One route per connected railway=rail network: the path between its
    two farthest-apart ends (double Dijkstra, the tree-diameter trick).
    It defines the network's ends (where trains enter and leave) and which
    timetable trains concern it; each train then gets its own track-level
    path from plan_train_path."""
    graph = graph or build_rail_graph(railways)
    points, edges = graph.points, graph.edges

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


# A train may turn at most this much at a node: through a switch or a
# curve, never back the way it came (no reversing into/out of sidings).
MAX_TURN_COS = math.cos(math.radians(60.0))
# Tracks passing within this distance of a station serve it.
STATION_TRACK_RADIUS_M = 150.0
# Finnish double track runs on the right: a station track on the left of
# the direction of travel costs this much extra route length, so opposing
# trains keep to their own tracks unless only one track exists.
WRONG_SIDE_PENALTY_M = 400.0


def plan_train_path(
    graph: RailGraph, entry, exit_, stations: Sequence[Tuple[float, float]],
) -> Optional[Tuple[TrainRoute, List[Optional[float]]]]:
    """Track-level path entry -> each station (in order) -> exit, as a
    TrainRoute in travel order plus each station's stopping point along it
    (None for a station no track reaches). Dijkstra over (node, came-from,
    stations passed) states, so the path never reverses and every station
    is passed on a track that continues onwards (a dead-end siding can't
    be part of it). Only real track connections are used. Called when a
    train is spawned (cached per pattern), never per frame."""
    start, goal = graph.node_at(entry), graph.node_at(exit_)
    if start is None or goal is None:
        return None
    candidates = [set(graph.nodes_near(point, STATION_TRACK_RADIUS_M)) for point in stations]
    reachable = [i for i, c in enumerate(candidates) if c]
    points, edges = graph.points, graph.edges
    n_stages = len(reachable)
    begin = (start, -1, 0)
    best = {begin: 0.0}
    parent: Dict[tuple, tuple] = {}
    heap = [(0.0, begin)]
    final = None
    while heap:
        cost, state = heapq.heappop(heap)
        if cost > best.get(state, math.inf):
            continue
        node, previous, stage = state
        if node == goal and stage == n_stages:
            final = state
            break
        for nxt, length in edges.get(node, {}).items():
            if nxt == previous:
                continue
            tx, ty = points[nxt][0] - points[node][0], points[nxt][1] - points[node][1]
            if previous >= 0:
                px, py = points[node][0] - points[previous][0], points[node][1] - points[previous][1]
                norm = math.hypot(tx, ty) * math.hypot(px, py)
                if norm > 0 and (tx * px + ty * py) / norm < MAX_TURN_COS:
                    continue
            moves = [((nxt, node, stage), cost + length)]
            if stage < n_stages and nxt in candidates[reachable[stage]]:
                sx, sy = stations[reachable[stage]]
                right_side = tx * (points[nxt][1] - sy) - ty * (points[nxt][0] - sx) < 0
                penalty = (0.0 if right_side else WRONG_SIDE_PENALTY_M) + math.dist(points[nxt], (sx, sy))
                moves.append(((nxt, node, stage + 1), cost + length + penalty))
            for new_state, new_cost in moves:
                if new_cost < best.get(new_state, math.inf):
                    best[new_state], parent[new_state] = new_cost, state
                    heapq.heappush(heap, (new_cost, new_state))
    if final is None:
        return None
    states = [final]
    while states[-1] in parent:
        states.append(parent[states[-1]])
    states.reverse()
    route = TrainRoute([points[state[0]] for state in states])
    stops: List[Optional[float]] = [None] * len(stations)
    for index in range(1, len(states)):
        if states[index][2] > states[index - 1][2]:
            stops[reachable[states[index][2] - 1]] = route.cumulative[index]
    return route, stops


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
        self.graph = RailGraph()
        self._paths: Dict[tuple, Optional[Tuple[TrainRoute, list]]] = {}  # per train pattern
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
        self.graph = build_rail_graph(railways)
        self.routes = build_train_routes(railways, graph=self.graph)
        self._paths = {}
        if self.timetable is not None and self.to_metres is not None:
            previous_clock = self.clock
            self.clock = TimetableClock(match_timetable(self.timetable, self.routes, prepared=self._prepared))
            if previous_clock is not None:
                # More track streamed in: carry on from the old clock (no
                # second game-start placement, no re-spawned trains).
                self.clock.continue_from(previous_clock)
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

    def train_path(self, service: ScheduledPass) -> Optional[Tuple[TrainRoute, list]]:
        """This service's own track through the map (plan_train_path),
        cached per (network, direction, stations) - trains with the same
        stopping pattern share it."""
        network = self.routes[service.route_index]
        entry, exit_ = (network.points[0], network.points[-1]) if service.direction > 0 else (network.points[-1], network.points[0])
        key = (service.route_index, service.direction, tuple(stop[5] for stop in service.stops))
        if key not in self._paths:
            self._paths[key] = plan_train_path(self.graph, entry, exit_, [stop[5] for stop in service.stops])
            planned = self._paths[key]
            logger.info(
                "Train path %s %s: %s", service.label,
                " -> ".join(stop[2] for stop in service.stops) or "(no stops)",
                f"{planned[0].length / 1000:.1f} km, stops at {[None if a is None else round(a) for a in planned[1]]} m"
                if planned else "no track path, using the network line",
            )
        return self._paths[key]

    def _spawn(self, service: ScheduledPass) -> Train:
        planned = self.train_path(service)
        if planned is not None:
            route, alongs = planned
            stops = tuple((along,) + stop[1:] for stop, along in zip(service.stops, alongs) if along is not None)
            train = Train(route, 0.0, 1, service=service, stops=stops)
            entry = 0.0
        else:
            route = self.routes[service.route_index]
            entry = 0.0 if service.direction > 0 else route.length
            train = Train(route, entry, service.direction, service=service)
        if train.stops:
            # APPROACH_DISTANCE_M before the first stop, never beyond the
            # entry end (then it simply arrives a little early).
            start = train._stop_position(train.stops[0]) - train.direction * APPROACH_DISTANCE_M
            train.distance_m = min(max(start, 0.0), route.length)
        return train

    def _place_running_trains(self, now: datetime, game_speed: float) -> None:
        """Game start: trains that by the timetable should already be on
        the approach to, or standing at, their first stop here are placed
        there directly - even in view - instead of arriving hours late."""
        approach = timedelta(seconds=APPROACH_REAL_S * game_speed)
        # Look back far enough for a long dwell at this game speed (each
        # train's own dwell is checked below), but at most half a day.
        longest_dwell = min(timedelta(seconds=1800 * game_speed), timedelta(hours=12))
        for when, service in self.clock.events_between(now - longest_dwell, now + approach):
            if len(self.trains) >= MAX_ACTIVE_TRAINS or service.route_index >= len(self.routes):
                break
            train = self._spawn(service)
            if not train.stops:
                continue
            stop_at = train._stop_position(train.stops[0])
            if when > now:  # approaching: the matching share of the approach left
                share = (when - now) / approach
                train.distance_m = min(max(stop_at - train.direction * APPROACH_DISTANCE_M * share, 0.0), train.route.length)
            else:
                dwell_left = train.stops[0][1] * DWELL_REAL_S_PER_TIMETABLE_S - (now - when).total_seconds() / game_speed
                if dwell_left <= 0.0:
                    continue  # already left its stop here: gone before we look
                train.distance_m, train.current_speed_mps = stop_at, 0.0
                train.state, train.dwell_remaining_s = "DWELLING", dwell_left
            self.trains.append(train)
        if self.trains:
            logger.info("Railway start: %d trains placed on the map by the timetable", len(self.trains))

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
            if not self.clock.started and game_speed > 0.0:
                self._place_running_trains(now, game_speed)  # game start only
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
