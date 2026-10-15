"""Trams on their rails (docs/trams.md), in the cities that have them.

The tram network (OSM railway=tram) is a rail graph (trains.build_rail_graph
of kind "tram"). A tram serves one of the OSM tram lines on its track
(Railway.lines, the route=tram relations): at a junction it takes the way
its line goes on; off its line's mapped track, mostly straight on. It
stops at the tram stops on its way (Railway.stops),
and brakes for anything on its track ahead: the taxi, cars, people,
another tram. Trams are kept near the viewpoint only: spawned out of
sight, removed far away; a tram at a dead end of the loaded track turns
back (seen) or goes (unseen). Bounded work: a few trams, each looking a
short way ahead.
"""
from __future__ import annotations

import bisect
import itertools
import math
import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .geo import dist_point_to_segment, get_oriented_box_corners, point_in_polygon, segments_intersect
from .trains import NODE_SPACING_M, build_rail_graph

NODE_REACH_M = NODE_SPACING_M + 5.0  # a track segment's nodes lie this near any point on it

# City -> its trams' look (render_style.gd TRAIN_PROFILES) and sections
# (an articulated tram: each section's length in metres).
TRAM_CITIES = {
    "helsinki": ("tram_helsinki", (9.2, 9.2, 9.2)),  # HSL green-and-white, ~28 m Artic
    "tampere": ("tram_tampere", (12.4, 12.4, 12.4)),  # red-and-white, ~37 m
}
DEFAULT_TRAM = ("tram_helsinki", (9.2, 9.2, 9.2))
TRAM_WIDTH_M = 2.4
TRAM_SPEED_MPS = 10.0  # ~36 km/h in the city
TRAM_ACCEL_MPS2 = 1.0
TRAM_BRAKE_MPS2 = 1.3  # service braking; at a stop or behind an obstacle
STOP_DWELL_S = 15.0
SAFETY_GAP_M = 5.0  # stops this far short of anything on its track
CORRIDOR_HALF_WIDTH_M = 2.2  # what counts as "on its track": this near the rail line
LOOKAHEAD_M = 160.0  # track planned ahead
KEEP_BEHIND_M = 60.0  # track kept behind the tail
TRAMS_PER_KM = 0.5  # of tram track near the viewpoint
MAX_TRAMS = 8
SPAWN_RADIUS_M = 900.0  # trams are kept on track this near the viewpoint...
DESPAWN_RADIUS_M = 1300.0  # ...and removed beyond this
POPULATION_CHECK_S = 2.0
STOP_SNAP_M = 15.0  # a stop's position (often beside the track) to its nearest track node (osm/build.py TRAM_STOP_SNAP_M)
STRAIGHT_ON_CHANCE = 0.75  # at a junction: the straightest continuation, else another
MAX_TURN_RAD = math.radians(70.0)  # sharper than this is not a way a tram can go on
# Keep right: on a double line the other track lies this far to a tram's
# left. A tram track this near on its right means it is on the wrong one.
OTHER_TRACK_OFFSET_M = 3.5
OTHER_TRACK_TOLERANCE_M = 1.3
STUCK_HOLD_S = 20.0  # held (by anything on its track) this long, unseen: it goes - a deadlock's safety net

_tram_ids = itertools.count(1)


@dataclass
class Tram:
    nodes: List[int]  # track nodes in travel order, behind it to ahead of it
    front_m: float  # the front's distance along `nodes`
    sections: Tuple[float, ...]
    profile: str
    tram_id: int = field(default_factory=lambda: next(_tram_ids))
    speed_mps: float = 0.0
    state: str = "RUNNING"  # RUNNING, DWELLING (at a stop), HOLDING (something on the track)
    dwell_until: float = 0.0
    served_stop: Optional[int] = None  # the stop node it last stood at (not again until past it)
    held_since: Optional[float] = None  # sim time it began HOLDING
    line: Optional[str] = None  # the OSM tram line it serves ("7"), None off any mapped line
    cumulative: List[float] = field(default_factory=list)

    @property
    def length_m(self) -> float:
        return sum(self.sections)


class TramManager:
    def __init__(self, railways: Sequence = (), city: str = "", rng: Optional[random.Random] = None) -> None:
        self.profile, self.sections = TRAM_CITIES.get(city.strip().lower(), DEFAULT_TRAM)
        self.rng = rng or random.Random()
        self.trams: List[Tram] = []
        self.sim_time = 0.0
        self._population_elapsed = POPULATION_CHECK_S
        self.rebuild(railways)

    # -- the track -------------------------------------------------------
    def rebuild(self, railways: Sequence) -> None:
        """The tram network (again, as more map streams in). Trams keep
        running on their own node lists; nodes are never renumbered away
        from the same point (a node's id is its merged position)."""
        self.graph = build_rail_graph(railways, kind="tram")
        self.stop_nodes: Dict[int, str] = {}
        for railway in railways:
            for x, y, name in getattr(railway, "stops", ()) if getattr(railway, "kind", "") == "tram" else ():
                near = self.graph.nodes_near((x, y), STOP_SNAP_M)
                if near:
                    self.stop_nodes[min(near, key=lambda n: math.dist(self.graph.points[n], (x, y)))] = name
        self.trams = [t for t in self.trams if all(n < len(self.graph.points) for n in t.nodes)]

    @property
    def has_track(self) -> bool:
        return bool(self.graph.edges)

    def _point(self, node: int) -> Tuple[float, float]:
        return self.graph.points[node]

    def _keeps_right(self, a: int, b: int) -> bool:
        """Whether a tram on a -> b is on the right-hand track: no other
        tram track OTHER_TRACK_OFFSET_M to its right (right-hand traffic)."""
        (ax, ay), (bx, by) = self._point(a), self._point(b)
        heading = math.atan2(by - ay, bx - ax)
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        px, py = mx + math.sin(heading) * OTHER_TRACK_OFFSET_M, my - math.cos(heading) * OTHER_TRACK_OFFSET_M
        for node in self.graph.nodes_near((px, py), NODE_REACH_M):
            for other in self.graph.edges.get(node, {}):
                if {node, other} == {a, b}:
                    continue
                (cx, cy), (dx, dy) = self._point(node), self._point(other)
                if dist_point_to_segment(px, py, cx, cy, dx, dy) <= OTHER_TRACK_TOLERANCE_M:
                    return False
        return True

    def _lines_on(self, a: int, b: int) -> set:
        return self.graph.lines.get(frozenset((a, b)), set())

    def _next_node(self, previous: int, node: int, line: Optional[str] = None) -> Optional[int]:
        """Where a tram on previous -> node goes on: where its line goes on,
        if mapped; else the straightest way, usually. Never back, nor round
        a corner sharper than MAX_TURN_RAD, nor over to the wrong-way track
        of a double line if it can help it."""
        px, py = self._point(previous)
        nx, ny = self._point(node)
        heading = math.atan2(ny - py, nx - px)
        options = []
        for candidate in self.graph.edges.get(node, {}):
            if candidate == previous:
                continue
            cx, cy = self._point(candidate)
            turn = abs((math.atan2(cy - ny, cx - nx) - heading + math.pi) % (2.0 * math.pi) - math.pi)
            if turn <= MAX_TURN_RAD:
                options.append((turn, candidate))
        if not options:
            return None
        right = [option for option in options if self._keeps_right(node, option[1])]
        if line is not None:
            # Its line's way, keeping right (both directions' tracks carry the
            # line's number); else its line's way all the same - just past a
            # junction a diverging branch can still run close beside the
            # other track and look like the wrong-way one.
            on_line = [option for option in options if line in self._lines_on(node, option[1])]
            pick = [option for option in on_line if option in right] or on_line
            if pick:
                return min(pick)[1]  # (the straightest, should two carry it)
        options = right or options
        options.sort()
        if len(options) == 1 or self.rng.random() < STRAIGHT_ON_CHANCE:
            return options[0][1]
        return self.rng.choice(options[1:])[1]

    def _measure(self, tram: Tram) -> None:
        tram.cumulative = [0.0]
        for a, b in zip(tram.nodes, tram.nodes[1:]):
            tram.cumulative.append(tram.cumulative[-1] + math.dist(self._point(a), self._point(b)))

    def _extend(self, tram: Tram) -> bool:
        """Track planned LOOKAHEAD_M ahead and KEEP_BEHIND_M behind the
        tail. False: a dead end ahead within the lookahead."""
        open_ahead = True
        while tram.cumulative[-1] - tram.front_m < LOOKAHEAD_M:
            following = self._next_node(tram.nodes[-2], tram.nodes[-1], tram.line) if len(tram.nodes) >= 2 else None
            if following is None:
                open_ahead = False
                break
            tram.cumulative.append(tram.cumulative[-1] + math.dist(self._point(tram.nodes[-1]), self._point(following)))
            tram.nodes.append(following)
        while len(tram.nodes) > 2 and tram.cumulative[1] < tram.front_m - tram.length_m - KEEP_BEHIND_M:
            drop = tram.cumulative[1]
            tram.nodes.pop(0)
            tram.cumulative = [c - drop for c in tram.cumulative[1:]]
            tram.front_m -= drop
        return open_ahead

    def _at(self, tram: Tram, distance_m: float) -> Tuple[float, float, float]:
        """(x, y, heading) on the tram's track at distance_m along it."""
        cumulative = tram.cumulative
        distance_m = min(max(distance_m, 0.0), cumulative[-1])
        i = min(max(bisect.bisect_right(cumulative, distance_m) - 1, 0), len(tram.nodes) - 2)
        (ax, ay), (bx, by) = self._point(tram.nodes[i]), self._point(tram.nodes[i + 1])
        span = cumulative[i + 1] - cumulative[i]
        t = (distance_m - cumulative[i]) / span if span > 0 else 0.0
        return ax + (bx - ax) * t, ay + (by - ay) * t, math.atan2(by - ay, bx - ax)

    def cars(self, tram: Tram) -> List[Tuple[float, float, float, float, str]]:
        """Its sections, front first: (x, y, heading, length, look) - the
        state's "trains" car shape."""
        out, back = [], tram.front_m
        for length in tram.sections:
            x, y, heading = self._at(tram, back - length / 2.0)
            out.append((x, y, heading, length, self.profile))
            back -= length
        return out

    def footprints(self, tram: Tram) -> List[list]:
        return [get_oriented_box_corners(x, y, h, length, TRAM_WIDTH_M) for x, y, h, length, _ in self.cars(tram)]

    # -- population ------------------------------------------------------
    def _spawn(self, near: Tuple[float, float], view) -> Optional[Tram]:
        nodes = [n for n in self.graph.nodes_near(near, SPAWN_RADIUS_M)
                 if len(self.graph.edges.get(n, {})) == 2 and not _in_view(self._point(n), view)]
        on_lines = [n for n in nodes if any(self._lines_on(n, m) for m in self.graph.edges[n])]
        nodes = on_lines or nodes  # on a line's track, not a depot siding, where there is one
        if not nodes:
            return None
        start = self.rng.choice(nodes)
        ends = list(self.graph.edges[start])
        self.rng.shuffle(ends)
        ends.sort(key=lambda previous: not self._keeps_right(previous, start))  # the right-hand way first
        previous = ends[0]
        lines = sorted(self._lines_on(previous, start))
        tram = Tram(nodes=[previous, start], front_m=0.0, sections=self.sections, profile=self.profile,
                    speed_mps=TRAM_SPEED_MPS, line=self.rng.choice(lines) if lines else None)
        self._measure(tram)
        # Grow its track behind it too (reversed walk), so its body fits.
        back = [start, previous]
        while len(back) >= 2 and sum(math.dist(self._point(a), self._point(b)) for a, b in zip(back, back[1:])) < tram.length_m + 5.0:
            following = self._next_node(back[-2], back[-1], tram.line)
            if following is None:
                return None
            back.append(following)
        tram.nodes = list(reversed(back))
        self._measure(tram)
        tram.front_m = tram.cumulative[-1]
        self._extend(tram)
        if any(_overlaps(self.footprints(tram), self.footprints(other)) for other in self.trams):
            return None
        return tram

    def _populate(self, view_centre: Tuple[float, float], view) -> None:
        self.trams = [t for t in self.trams
                      if math.dist(self._at(t, t.front_m)[:2], view_centre) <= DESPAWN_RADIUS_M
                      or _in_view(self._at(t, t.front_m)[:2], view)]
        track_m = sum(d for n in self.graph.nodes_near(view_centre, SPAWN_RADIUS_M)
                      for d in self.graph.edges.get(n, {}).values()) / 2.0
        wanted = min(MAX_TRAMS, int(track_m / 1000.0 * TRAMS_PER_KM + 0.5))
        if len(self.trams) < wanted:
            tram = self._spawn(view_centre, view)
            if tram is not None:
                self.trams.append(tram)

    # -- driving ---------------------------------------------------------
    def _unstick(self, view) -> None:
        """A tram held STUCK_HOLD_S, out of sight, goes: two that met on one
        track, or one behind a car that will never move, must not stand there for ever."""
        for tram in list(self.trams):
            if (tram.held_since is not None and self.sim_time - tram.held_since >= STUCK_HOLD_S
                    and tram.speed_mps == 0.0 and not _in_view(self._at(tram, tram.front_m)[:2], view)):
                self.trams.remove(tram)

    def update(self, dt: float, view_centre: Tuple[float, float], view=None,
               obstacles: Iterable[Tuple[float, float]] = ()) -> None:
        """One tick: population (every POPULATION_CHECK_S), then every
        tram drives. `obstacles`: points of whatever may be on a tram's
        track - the taxi, cars, people (other trams are added here)."""
        if not self.has_track:
            self.trams = []
            return
        self.sim_time += dt
        self._population_elapsed += dt
        if self._population_elapsed >= POPULATION_CHECK_S:
            self._population_elapsed = 0.0
            self._unstick(view)
            self._populate(view_centre, view)
        obstacles = list(obstacles)
        tails = {t.tram_id: [(x, y) for x, y, *_ in self.cars(t)] + [self._at(t, t.front_m - t.length_m)[:2]] for t in self.trams}
        for tram in list(self.trams):
            others = obstacles + [p for tid, points in tails.items() if tid != tram.tram_id for p in points]
            self._drive(tram, dt, others, view)

    def _drive(self, tram: Tram, dt: float, obstacles: List[Tuple[float, float]], view) -> None:
        if tram.state == "DWELLING":
            if self.sim_time < tram.dwell_until:
                return
            tram.state = "RUNNING"
        open_ahead = self._extend(tram)
        limit = TRAM_SPEED_MPS
        # The next stop it has not stood at, and the track's end.
        stop_at = None
        for node, distance in zip(tram.nodes, tram.cumulative):
            if distance > tram.front_m + 0.5 and node in self.stop_nodes and node != tram.served_stop:
                stop_at = distance
                break
        ends = [] if open_ahead else [tram.cumulative[-1] - 1.0]
        blocked = self._obstacle_ahead(tram, obstacles)
        tram.state = "HOLDING" if blocked is not None else "RUNNING"
        tram.held_since = (tram.held_since if tram.held_since is not None else self.sim_time) if blocked is not None else None
        for distance in [d for d in (stop_at, blocked, *ends) if d is not None]:
            limit = min(limit, math.sqrt(max(0.0, 2.0 * TRAM_BRAKE_MPS2 * (distance - tram.front_m))))
        if tram.speed_mps < limit:
            tram.speed_mps = min(limit, tram.speed_mps + TRAM_ACCEL_MPS2 * dt)
        else:
            tram.speed_mps = max(limit, tram.speed_mps - TRAM_BRAKE_MPS2 * 2.0 * dt)  # (an emergency stop may brake harder)
        tram.front_m += tram.speed_mps * dt
        # At the stop (braking for it has crept it the last half metre): there.
        if stop_at is not None and tram.front_m >= stop_at - 0.5:
            tram.front_m, tram.speed_mps = stop_at, 0.0
            tram.state, tram.dwell_until = "DWELLING", self.sim_time + STOP_DWELL_S
            tram.served_stop = tram.nodes[tram.cumulative.index(stop_at)]
        elif not open_ahead and tram.front_m >= tram.cumulative[-1] - 1.5 and tram.speed_mps < 0.3:
            if _in_view(self._at(tram, tram.front_m)[:2], view):
                self._turn_back(tram)
            else:
                self.trams.remove(tram)

    def _obstacle_ahead(self, tram: Tram, obstacles: List[Tuple[float, float]]) -> Optional[float]:
        """The distance along its track to stop at for the nearest thing
        on the track ahead within its braking reach, or None."""
        reach = tram.speed_mps ** 2 / (2.0 * TRAM_BRAKE_MPS2) + SAFETY_GAP_M + 15.0
        best = None
        fx, fy, _ = self._at(tram, tram.front_m)
        for ox, oy in obstacles:
            if math.hypot(ox - fx, oy - fy) > reach + CORRIDOR_HALF_WIDTH_M:
                continue
            along = self._along(tram, (ox, oy), tram.front_m, tram.front_m + reach)
            if along is not None and (best is None or along < best):
                best = along
        return None if best is None else best - SAFETY_GAP_M

    def _along(self, tram: Tram, point, start: float, end: float) -> Optional[float]:
        """Where `point` lies on the tram's track between start and end
        (within CORRIDOR_HALF_WIDTH_M of it), or None."""
        i = max(bisect.bisect_right(tram.cumulative, start) - 1, 0)
        while i < len(tram.nodes) - 1 and tram.cumulative[i] <= end:
            (ax, ay), (bx, by) = self._point(tram.nodes[i]), self._point(tram.nodes[i + 1])
            dx, dy = bx - ax, by - ay
            span_sq = dx * dx + dy * dy
            t = 0.0 if span_sq == 0 else max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / span_sq))
            if math.hypot(ax + dx * t - point[0], ay + dy * t - point[1]) <= CORRIDOR_HALF_WIDTH_M:
                distance = tram.cumulative[i] + t * (tram.cumulative[i + 1] - tram.cumulative[i])
                if start < distance <= end:
                    return distance
            i += 1
        return None

    def _turn_back(self, tram: Tram) -> None:
        """At the end of the track: the driver walks to the other cab."""
        tram.nodes.reverse()
        self._measure(tram)
        tram.front_m = tram.cumulative[-1] - tram.front_m + tram.length_m
        tram.served_stop = None
        tram.sections = tuple(reversed(tram.sections))

    # -- the taxi --------------------------------------------------------
    def hits(self, corners: Sequence[Tuple[float, float]]) -> bool:
        """Whether a vehicle footprint (its 4 corners) overlaps a tram."""
        return any(_overlaps([list(corners)], self.footprints(tram)) for tram in self.trams)


def _in_view(point: Tuple[float, float], view) -> bool:
    return view is not None and view[0] <= point[0] <= view[2] and view[1] <= point[1] <= view[3]


def _overlaps(boxes_a: List[list], boxes_b: List[list]) -> bool:
    """Whether any box of a overlaps any of b: a corner inside the other,
    or edges crossing (two long boxes crossing like an X have no corner in)."""
    for a in boxes_a:
        for b in boxes_b:
            if any(point_in_polygon(x, y, b) for x, y in a) or any(point_in_polygon(x, y, a) for x, y in b):
                return True
            if any(segments_intersect(p, q, r, s) for p, q in zip(a, a[1:] + a[:1]) for r, s in zip(b, b[1:] + b[:1])):
                return True
    return False
