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
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .train_timetable import ScheduledPass, StationCall, TimetableClock, match_timetable, prepare_timetable, station_calls

logger = logging.getLogger(__name__)

TRAIN_ENABLED = True
TRAIN_SPAWN_INTERVAL_S = 30.0 * 60.0  # game seconds between spawns, per route and direction
TRAIN_SPEED_MPS = 22.0  # ~80 km/h, constant
# Trains move in real time while the game clock runs up to 60x, so a busy
# line can have many timetable trains crossing the map at once.
MAX_ACTIVE_TRAINS = 48  # Helsinki at 60x dropped departures at 16 and 32
# Oulu's rail pieces run from a few metres (yard stubs) to kilometres; a
# train of TRAIN_CARS cars is ~150 m, so shorter lines would look silly.
MIN_TRAIN_ROUTE_LENGTH_M = 1000.0
TRAIN_CARS = 6  # locomotive + 5 carriages
TRAIN_CAR_LENGTH_M = 24.0
TRAIN_CAR_GAP_M = 1.5
TRAIN_WIDTH_M = 3.2
TRAIN_LENGTH_M = TRAIN_CARS * (TRAIN_CAR_LENGTH_M + TRAIN_CAR_GAP_M) - TRAIN_CAR_GAP_M
TRAIN_ACCELERATION_MPS2 = 0.6  # brake into / pull out of a station: ~40 s from 80 km/h
# Station stops follow the game clock: a 2 min timetable dwell is 2 game
# minutes - a couple of real seconds at 60x, the full 2 minutes at 1x (a
# fare aboard). Trains still *move* in real time.
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
    ends_at_buffer: bool = False  # route ends at a terminus buffer stop
    starts_at_buffer: bool = False  # route starts at a (departure platform's) buffer stop

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

    def locate(self, point) -> float:
        """Distance along the route of the point on it nearest `point`."""
        best, best_distance = 0.0, math.inf
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length_sq = dx * dx + dy * dy
            t = 0.0 if length_sq == 0 else min(1.0, max(0.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq))
            distance = math.hypot(a[0] + dx * t - point[0], a[1] + dy * t - point[1])
            if distance < best_distance:
                best, best_distance = self.cumulative[i] + t * (self.cumulative[i + 1] - self.cumulative[i]), distance
        return best

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
    reached_end: bool = False  # ran off an end of its route this update
    waiting_for: Optional[tuple] = None  # (departure time, ScheduledPass) it will become

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
        if self.state == "WAITING" and self.waiting_for is not None:
            when, next_service = self.waiting_for
            return f"{self.service.label} WAITING -> {next_service.train_type} {next_service.number} {when:%H:%M}"
        stop = self.next_stop
        if self.state == "DWELLING" and stop is not None:
            track = f" track {stop[6]}" if len(stop) > 6 and stop[6] else ""
            return f"{self.service.label} DWELLING {stop[2]}{track} {self.dwell_remaining_s:.0f}s"
        return f"{self.service.label} RUNNING" + (f" -> {stop[2]}" if stop is not None else " -> leaving")

    @property
    def next_stop(self):
        return self.stops[self.stop_index] if self.stop_index < len(self.stops) else None

    def _stop_position(self, stop) -> float:
        """Locomotive position that centres the train on the station - kept
        so the whole train stays on its route (a terminus/origin at the
        route's end or start)."""
        if stop[7:8] == ("terminus",) and self.route.ends_at_buffer and self.direction > 0:
            return self.route.length  # all the way to the buffer stop
        if stop[7:8] == ("origin",) and self.route.starts_at_buffer and self.direction > 0:
            return min(TRAIN_LENGTH_M, self.route.length)  # last car at the buffer stop
        nose = stop[0] + self.direction * TRAIN_LENGTH_M / 2
        if self.direction > 0:
            return min(max(nose, min(TRAIN_LENGTH_M, self.route.length)), self.route.length)
        return max(min(nose, max(self.route.length - TRAIN_LENGTH_M, 0.0)), 0.0)

    def reverse_out(self) -> None:
        """Drive back out the way it came (a cab at each end): the old
        tail becomes the front, no stops left."""
        self.distance_m -= self.direction * TRAIN_LENGTH_M
        self.direction = -self.direction
        self.stops, self.stop_index = (), 0
        self.state, self.current_speed_mps = "RUNNING", 0.0

    def update(self, dt: float, game_dt: Optional[float] = None) -> None:
        """dt: real seconds, for movement; game_dt: game seconds, for the
        station dwell (defaults to dt, i.e. a 1x clock). TERMINATED
        (journey over, the manager decides what next) and WAITING (for its
        next departure) trains stand still."""
        if self.state in ("TERMINATED", "WAITING"):
            return
        if self.state == "DWELLING":
            self.dwell_remaining_s -= dt if game_dt is None else game_dt
            if self.dwell_remaining_s > 0.0:
                return
            finished = self.next_stop
            if finished is not None and finished[7:8] == ("terminus",):
                self.state = "TERMINATED"  # RailwayManager: wait for a next departure, or leave
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
                self.dwell_remaining_s = stop[1]
                return
        self.current_speed_mps = speed
        self.distance_m += self.direction * speed * dt
        # Only the end it is heading for counts (a train spawned at an end
        # has not "reached" it).
        if self.distance_m >= self.route.length and self.direction > 0:
            self.distance_m, self.direction, self.reached_end = self.route.length, -1, True
        elif self.distance_m <= 0.0 and self.direction < 0:
            self.distance_m, self.direction, self.reached_end = 0.0, 1, True

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
    tracks: Dict[int, set] = field(default_factory=dict)  # node -> OSM track numbers through it

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
        track_ref = getattr(railway, "track_ref", "")
        if track_ref:
            for node_id in ids:
                graph.tracks.setdefault(node_id, set()).add(track_ref)
        for a, b in zip(ids, ids[1:]):
            if a != b:
                d = math.dist(graph.points[a], graph.points[b])
                graph.edges.setdefault(a, {})[b] = d
                graph.edges.setdefault(b, {})[a] = d
    return graph


def _segment_distance(point, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else min(1.0, max(0.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq))
    return math.hypot(a[0] + dx * t - point[0], a[1] + dy * t - point[1])


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
# How strongly a stop prefers the track node nearest the platform point
# over a slightly shorter route (1 = a node 100 m early costs the same as
# 100 m extra travel, which let trains stop well short of the platform).
STOP_DISTANCE_WEIGHT = 4.0
TERMINUS_SEARCH_M = 600.0  # how far past a terminus platform point to look for its buffer stop
ENTRY_CANDIDATES = 3  # track dead ends tried per side when planning a train's path
# A train whose journey ends here waits on its platform this long (game
# time) at most for a departure from the same track, and gives up this
# long after that departure's time.
TURNAROUND_MAX_WAIT = timedelta(hours=12)
PLATFORM_CLEARANCE_M = 2.0  # a stopping point this close to a used track is on it
OCCUPANCY_REPLANS = 4  # tracks tried per spawn before accepting a shared one
TURNAROUND_GRACE = timedelta(minutes=30)


def plan_train_path(
    graph: RailGraph, entry, exit_, stations: Sequence[Tuple[float, float]], tracks: Sequence[str] = (),
    starts_at_first: bool = False, ends_at_last: bool = False, avoid: frozenset = frozenset(),
) -> Optional[Tuple[TrainRoute, List[Optional[float]]]]:
    """Track-level path entry -> each station (in order) -> exit, as a
    TrainRoute in travel order plus each station's stopping point along it
    (None for a station no track reaches). Dijkstra over (node, came-from,
    stations passed) states, so the path never reverses and every station
    is passed on a track that continues onwards (a dead-end siding can't
    be part of it). Only real track connections are used. Called when a
    train is spawned (cached per pattern), never per frame."""
    start, goal = graph.node_at(entry), graph.node_at(exit_)
    if (start is None and not starts_at_first) or (goal is None and not ends_at_last):
        return None
    # avoid: station track nodes other trains occupy - never a stopping place.
    candidates = [set(graph.nodes_near(point, STATION_TRACK_RADIUS_M)) - avoid for point in stations]
    # The timetable platform names the track: stop only on nodes of that
    # OSM track (railway:track_ref) when the map has it; the right-hand
    # rule is then moot.
    assigned = [False] * len(stations)
    for index, track in enumerate(tracks):
        on_track = {n for n in candidates[index] if track and track in graph.tracks.get(n, ())}
        if on_track:
            candidates[index], assigned[index] = on_track, True
    reachable = [i for i, c in enumerate(candidates) if c]
    points, edges = graph.points, graph.edges
    n_stages = len(reachable)
    if (starts_at_first or ends_at_last) and not reachable:
        return None
    # A journey starting here begins standing on its first station's track
    # (any direction); one ending here stops at its last station - a
    # terminus is usually a dead end, so no through route is required.
    if starts_at_first:
        # Start at the platform node nearest the platform point (same
        # weighting as stopping), not wherever the way out is shortest.
        first = stations[reachable[0]]
        begins = {(node, -1, 1): STOP_DISTANCE_WEIGHT * math.dist(points[node], first) for node in candidates[reachable[0]]}
    else:
        begins = {(start, -1, 0): 0.0}
    best = dict(begins)
    parent: Dict[tuple, tuple] = {}
    heap = [(cost, begin) for begin, cost in begins.items()]
    final = None
    while heap:
        cost, state = heapq.heappop(heap)
        if cost > best.get(state, math.inf):
            continue
        node, previous, stage = state
        if stage == n_stages and (node == goal or (ends_at_last and state in parent and parent[state][2] < stage)):
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
                side = 0.0 if right_side or assigned[reachable[stage]] else WRONG_SIDE_PENALTY_M
                penalty = side + STOP_DISTANCE_WEIGHT * math.dist(points[nxt], (sx, sy))
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
    nodes = [state[0] for state in states]
    # A terminus / origin: carry the route on along the platform track (to
    # the buffer stop) so the train can stand centred on the platform
    # rather than wholly before it.
    before, starts_at_buffer = [], False
    if starts_at_first and len(nodes) > 1:
        # Departing from a dead end: the route reaches back to the buffer
        # stop, under the whole train standing there (it just swaps ends).
        before = _continue_track(graph, nodes[1], nodes[0], TERMINUS_SEARCH_M)
        starts_at_buffer = len(graph.edges.get((before or nodes)[-1], {})) == 1
        if not starts_at_buffer:
            before = _continue_track(graph, nodes[1], nodes[0])
    after, at_buffer = [], False
    if ends_at_last and len(nodes) > 1:
        # A terminus: follow the platform track on; if it ends at a buffer
        # stop within TERMINUS_SEARCH_M the locomotive drives right up to
        # it, else (a through station) just leave room to stand centred.
        after = _continue_track(graph, nodes[-2], nodes[-1], TERMINUS_SEARCH_M)
        at_buffer = len(graph.edges.get((after or nodes)[-1], {})) == 1
        if not at_buffer:
            after = _continue_track(graph, nodes[-2], nodes[-1])
    route = TrainRoute([points[n] for n in list(reversed(before)) + nodes + after])
    route.ends_at_buffer = at_buffer
    route.starts_at_buffer = starts_at_buffer
    stops: List[Optional[float]] = [None] * len(stations)
    if starts_at_first:
        stops[reachable[0]] = route.cumulative[len(before)]
    for index in range(1, len(states)):
        if states[index][2] > states[index - 1][2]:
            stops[reachable[states[index][2] - 1]] = route.cumulative[len(before) + index]
    return route, stops


def _continue_track(graph: RailGraph, previous: int, node: int, limit_m: float = TRAIN_LENGTH_M) -> List[int]:
    """Nodes straight on from previous -> node (never turning more than
    MAX_TURN_COS allows) until a dead end or limit_m."""
    points, result, travelled = graph.points, [], 0.0
    while travelled < limit_m:
        px, py = points[node][0] - points[previous][0], points[node][1] - points[previous][1]
        best, best_cos = None, MAX_TURN_COS
        for nxt in graph.edges.get(node, {}):
            if nxt == previous:
                continue
            tx, ty = points[nxt][0] - points[node][0], points[nxt][1] - points[node][1]
            norm = math.hypot(tx, ty) * math.hypot(px, py)
            cos = (tx * px + ty * py) / norm if norm else -1.0
            if cos >= best_cos:
                best, best_cos = nxt, cos
        if best is None:
            break
        travelled += graph.edges[node][best]
        previous, node = node, best
        result.append(node)
    return result


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
        self._track_ends: List[int] = []
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
        self._track_ends = [node for node, links in self.graph.edges.items() if len(links) == 1]
        if self.timetable is not None and self.to_metres is not None:
            previous_clock = self.clock
            self.clock = TimetableClock(match_timetable(
                self.timetable, self.routes, prepared=self._prepared,
                has_track=lambda point: bool(self.graph.nodes_near(point, STATION_TRACK_RADIUS_M)),
            ))
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

    def _track_ends_towards(self, point, fallback) -> List[Tuple[float, float]]:
        """Where a train enters from / leaves towards `point` (a station
        beyond this map): the track dead ends - the map's edge or a line's
        end - nearest to it, best first. `fallback` without a point."""
        if point is None:
            return [fallback]
        ends = sorted(self._track_ends, key=lambda n: math.dist(self.graph.points[n], point))
        return [self.graph.points[n] for n in ends[:ENTRY_CANDIDATES]] or [fallback]

    def train_path(self, service: ScheduledPass, avoid: frozenset = frozenset()) -> Optional[Tuple[TrainRoute, list]]:
        """This service's own track through the map (plan_train_path),
        cached per (where it comes from / goes to, stations, tracks) -
        trains with the same pattern share it. Entry and exit come from
        the journey itself, not the network's longest line (which can
        double back through a big station yard)."""
        network = self.routes[service.route_index]
        start, end = (network.points[0], network.points[-1]) if service.direction > 0 else (network.points[-1], network.points[0])
        key = (service.came_from, service.going_to, tuple(stop[5:8] for stop in service.stops), avoid)
        if key not in self._paths:
            planned = None
            stations, tracks = [stop[5] for stop in service.stops], [stop[6] for stop in service.stops]
            starts_here = bool(service.stops) and service.stops[0][7] == "origin"
            ends_here = bool(service.stops) and service.stops[-1][7] == "terminus"
            for entry in self._track_ends_towards(None if starts_here else service.came_from, start):
                for exit_ in self._track_ends_towards(None if ends_here else service.going_to, end):
                    planned = plan_train_path(
                        self.graph, entry, exit_, stations, tracks, starts_at_first=starts_here, ends_at_last=ends_here,
                        avoid=avoid,
                    )
                    if planned is not None:
                        break
                if planned is not None:
                    break
            self._paths[key] = planned
            logger.info(
                "Train path %s %s: %s", service.label,
                " -> ".join(f"{stop[2]} track {stop[6] or '?'}" for stop in service.stops) or "(no stops)",
                f"{planned[0].length / 1000:.1f} km, stops at {[None if a is None else round(a) for a in planned[1]]} m"
                if planned else "no track path, using the network line",
            )
        return self._paths[key]

    def _platform_taken(self, station: str, track: str) -> bool:
        """Some active train still has (or is at) this station track ahead."""
        return any(
            (stop[2], stop[6]) == (station, track)
            for train in self.trains for stop in train.stops[train.stop_index:] if len(stop) > 6
        )

    def _free_tracks(self, service: ScheduledPass) -> ScheduledPass:
        """The service with each occupied timetable track swapped for the
        nearest free numbered track at that station (by track number) that
        its route can actually reach, so trains don't stand on top of each
        other. Unchanged where the timetable track isn't a numbered track
        on this map (then the stop is chosen by position anyway)."""
        number = lambda ref: int(ref) if ref.isdigit() else 10 ** 6  # noqa: E731
        for index, stop in enumerate(service.stops):
            station, track = stop[2], stop[6]
            if not track or not self._platform_taken(station, track):
                continue
            here = {ref for node in self.graph.nodes_near(stop[5], STATION_TRACK_RADIUS_M) for ref in self.graph.tracks.get(node, ())}
            if track not in here:
                continue
            free = sorted(
                (ref for ref in here if ref != track and not self._platform_taken(station, ref)),
                key=lambda ref: (abs(number(ref) - number(track)), number(ref), ref),
            )
            for ref in free:
                stops = service.stops[:index] + (stop[:6] + (ref,) + stop[7:],) + service.stops[index + 1:]
                candidate = replace(service, stops=stops)
                if self.train_path(candidate) is not None:
                    logger.info("%s: %s track %s occupied, using track %s", service.label, station, track, ref)
                    service = candidate
                    break
        return service

    def _occupied_nodes(self, route: TrainRoute, alongs: list, service: ScheduledPass) -> frozenset:
        """Track nodes at this train's stations where another train stands
        or will stop within PLATFORM_CLEARANCE_M of this train's stopping
        point - physical occupancy, for stations whose platform numbers
        are not OSM track numbers (e.g. Pasila)."""
        occupied = set()
        for stop, along in zip(service.stops, alongs):
            if along is None:
                continue
            mine = route.point_at(along)[:2]
            for other in self.trains:
                if not any(other_stop[2] == stop[2] for other_stop in other.stops[other.stop_index:]):
                    continue
                # Their track through this station: if I would stop on it,
                # it is taken.
                theirs = [p for p in other.route.points if math.dist(p, stop[5]) <= STATION_TRACK_RADIUS_M]
                if any(_segment_distance(mine, a, b) <= PLATFORM_CLEARANCE_M for a, b in zip(theirs, theirs[1:])):
                    occupied.update(self.graph.node_at(p) for p in theirs)
        occupied.discard(None)
        return frozenset(occupied)

    def _spawn(self, service: ScheduledPass) -> Train:
        service = self._free_tracks(service)
        planned = self.train_path(service)
        avoid = frozenset()
        for _ in range(OCCUPANCY_REPLANS):
            # Stops on a track another train uses at that station: plan
            # again without those tracks, until the stop is free.
            occupied = self._occupied_nodes(*planned, service) - avoid if planned is not None else frozenset()
            if not occupied:
                break
            avoid |= occupied
            alternative = self.train_path(service, avoid)
            if alternative is None:
                break
            planned = alternative
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

    def _turn_around(self, now: datetime) -> None:
        """A train that ended its journey here waits on its platform for
        the next departure that starts from the same station and track
        (the timetable has no vehicle links, so the platform is the link)
        - else, or if that departure is missed, it drives back out."""
        claimed = {id(t.waiting_for[1]) for t in self.trains if t.waiting_for is not None}
        for train in self.trains:
            if train.state == "WAITING" and now > train.waiting_for[0] + TURNAROUND_GRACE:
                train.waiting_for = None
                train.reverse_out()
            if train.state != "TERMINATED":
                continue
            _, _, station, _, _, _, track, _ = train.stops[train.stop_index][:8]
            train.waiting_for = next(
                (
                    (when, service) for when, service in self.clock.events_between(now, now + TURNAROUND_MAX_WAIT)
                    if id(service) not in claimed and service.stops and service.stops[0][7] == "origin"
                    and service.stops[0][2] == station and service.stops[0][6] == track
                ),
                None,
            )
            if train.waiting_for is None:
                train.reverse_out()
            else:
                train.state = "WAITING"
                claimed.add(id(train.waiting_for[1]))

    def _take_over(self, service: ScheduledPass, when: Optional[datetime] = None, now: Optional[datetime] = None) -> bool:
        """The train waiting for this departure becomes it: new identity,
        route and stops, standing at its platform - no new train appears."""
        if not service.stops or service.stops[0][7] != "origin":
            return False
        platform = (service.stops[0][2], service.stops[0][6])

        def at_platform(train) -> bool:
            # Journey over on this very platform: dwelling at its terminus,
            # or already standing there waiting.
            stop = train.stops[train.stop_index] if train.stop_index < len(train.stops) else None
            return (
                stop is not None and stop[7:8] == ("terminus",) and (stop[2], stop[6]) == platform
                and train.state in ("DWELLING", "TERMINATED", "WAITING")
            )

        standing = [t for t in self.trains if at_platform(t)]
        waiting = next((t for t in standing if t.waiting_for is not None and t.waiting_for[1] is service), None)
        waiting = waiting or next((t for t in standing if t.waiting_for is None), None)
        return waiting is not None and self._become(waiting, service, when, now)

    def _become(self, train: Train, service: ScheduledPass, when: Optional[datetime], now: Optional[datetime]) -> bool:
        """A train standing at its platform turns into this departure: new
        identity, route and stops, same place (its old tail is the new
        front - a cab at each end), standing until the departure time."""
        planned = self.train_path(service)
        if planned is None:
            return False
        route, alongs = planned
        stops = tuple((along,) + stop[1:] for stop, along in zip(service.stops, alongs) if along is not None)
        if not stops:
            return False
        tail = train.route.point_at(train.distance_m - train.direction * TRAIN_LENGTH_M)[:2]
        train.route, train.direction, train.service, train.stops = route, 1, service, stops
        train.reached_end = False
        train.stop_index, train.waiting_for = 0, None
        train.distance_m = route.locate(tail)
        train.state, train.current_speed_mps = "DWELLING", 0.0
        until_departure = (when - now).total_seconds() if when is not None and now is not None else 0.0
        train.dwell_remaining_s = max(stops[0][1], until_departure)  # game seconds
        return True

    def _place_running_trains(self, now: datetime, game_speed: float) -> None:
        """Game start: trains that by the timetable should already be on
        the approach to, or standing at, their first stop here are placed
        there directly - even in view - instead of arriving hours late."""
        approach = timedelta(seconds=APPROACH_REAL_S * game_speed)
        # Dwells are in game time: look back over the longest plausible stop
        # (each train's own dwell is checked below).
        longest_dwell = timedelta(hours=1)
        for when, service in self.clock.events_between(now - longest_dwell, now + approach):
            if len(self.trains) >= MAX_ACTIVE_TRAINS or service.route_index >= len(self.routes):
                break
            train = self._spawn(service)
            if not train.stops:
                continue
            stop_at = train._stop_position(train.stops[0])
            if train.stops[0][7:8] == ("origin",) and when > now:
                # Departs from here later: already standing at its platform
                # (game start may place trains in view), until departure.
                train.distance_m, train.current_speed_mps = stop_at, 0.0
                train.state = "DWELLING"
                train.dwell_remaining_s = max(train.stops[0][1], (when - now).total_seconds())
            elif when > now:  # approaching: the matching share of the approach left
                share = (when - now) / approach
                train.distance_m = min(max(stop_at - train.direction * APPROACH_DISTANCE_M * share, 0.0), train.route.length)
            else:
                dwell_left = train.stops[0][1] - (now - when).total_seconds()
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
            train.reached_end = False
            train.update(dt, game_dt)
            # A timetable train leaves the map at the end of its route; a
            # shuttle on a replaced route (more track streamed in) retires
            # at its next turnaround - at a track end, never mid-view.
            if not train.reached_end or (train.service is None and id(train.route) in current):
                kept.append(train)
        self.trains = kept
        if self.clock is not None and now is not None:
            self._turn_around(now)
            game_speed = game_dt / dt if dt > 0.0 else 0.0
            if not self.clock.started and game_speed > 0.0:
                self._place_running_trains(now, game_speed)  # game start only
            for when, service in self.clock.due_times(now, timedelta(seconds=APPROACH_REAL_S * game_speed)):
                if self._take_over(service, when, now):
                    continue
                if len(self.trains) >= MAX_ACTIVE_TRAINS or service.route_index >= len(self.routes):
                    continue
                train = self._spawn(service)
                if train.stops and train.stops[0][7:8] == ("origin",):
                    # A journey starting here with no train on its platform:
                    # the train stands there - last car at a terminus's
                    # buffer stop - until its departure.
                    train.distance_m, train.current_speed_mps = train._stop_position(train.stops[0]), 0.0
                    train.state = "DWELLING"
                    train.dwell_remaining_s = max(train.stops[0][1], (when - now).total_seconds())
                self.trains.append(train)
        for key in self._spawn_timers:
            self._spawn_timers[key] -= game_dt
            if self._spawn_timers[key] > 0.0 or len(self.trains) >= MAX_ACTIVE_TRAINS:
                continue
            self._spawn_timers[key] = TRAIN_SPAWN_INTERVAL_S
            route_index, direction = key
            route = self.routes[route_index]
            # Enters from the route's end: a map edge or a track end.
            self.trains.append(Train(route, 0.0 if direction > 0 else route.length, direction))
