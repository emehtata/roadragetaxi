"""Road ferries (docs/ferries.md): one ferry shuttles each car ferry route.

A route is an OSM route=ferry way that carries cars (osm/build.py,
Railway kind FERRY_KIND). Its ferry waits at a landing with its deck end
on the route's end point, crosses to the other end and waits there. No
timetable: it leaves after DOCK_WAIT_S, or soon after the taxi has
stopped on its deck. The taxi (or the parked taxi, the driver on foot)
on the deck is carried with it; deck points are dry land for the water
brake and sinking (simulation.py). Bounded work: ferries only on routes
near the viewpoint, a few rectangle tests a tick.
"""
from __future__ import annotations

import bisect
import itertools
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .geo import get_oriented_box_corners
from .osm.build import FERRY_KIND

FERRY_LENGTH_M = 50.0  # a Finferries road ferry: ~50-90 m x 12-16 m
FERRY_WIDTH_M = 12.0  # render_style.gd FERRY_WIDTH_M
FERRY_SPEED_MPS = 4.5  # ~9 knots
FERRY_ACCEL_MPS2 = 0.25
DOCK_WAIT_S = 40.0
READY_WAIT_S = 4.0  # the taxi stopped on the deck this long: it leaves
STOPPED_MPS = 0.3
HEADING_SPAN_M = 15.0  # heading from the route this far either side: no jolt at a bend
ACTIVE_RADIUS_M = 2500.0  # routes this near the viewpoint have their ferry
POPULATION_CHECK_S = 2.0
DUPLICATE_END_M = 80.0  # a route whose ends both lie this near another's: the other direction's way

_ferry_ids = itertools.count(1)


@dataclass
class FerryRoute:
    points: List[Tuple[float, float]]
    cumulative: List[float]

    @property
    def length_m(self) -> float:
        return self.cumulative[-1]

    def at(self, s: float) -> Tuple[float, float]:
        s = min(max(s, 0.0), self.length_m)
        i = max(1, bisect.bisect_left(self.cumulative, s))
        i = min(i, len(self.points) - 1)
        a, b = self.points[i - 1], self.points[i]
        span = self.cumulative[i] - self.cumulative[i - 1]
        f = (s - self.cumulative[i - 1]) / span if span > 0.0 else 0.0
        return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f

    def heading(self, s: float) -> float:
        (ax, ay), (bx, by) = self.at(s - HEADING_SPAN_M), self.at(s + HEADING_SPAN_M)
        return math.atan2(by - ay, bx - ax)


@dataclass
class Ferry:
    route: FerryRoute
    s: float  # its centre's distance along the route
    target: float  # the centre's distance at the landing it is bound for (or waits at)
    ferry_id: int = field(default_factory=lambda: next(_ferry_ids))
    speed_mps: float = 0.0
    state: str = "DOCKED"  # DOCKED or CROSSING
    wait_s: float = 0.0
    ready_s: float = 0.0  # the taxi stopped on the deck for this long
    brought: bool = False  # the taxi on the deck came across with it: no hurry back until it drives off

    def pose(self) -> Tuple[float, float, float]:
        x, y = self.route.at(self.s)
        return x, y, self.route.heading(self.s)

    def local(self, x: float, y: float) -> Tuple[float, float]:
        cx, cy, h = self.pose()
        dx, dy = x - cx, y - cy
        return dx * math.cos(h) + dy * math.sin(h), -dx * math.sin(h) + dy * math.cos(h)

    def on_deck(self, x: float, y: float) -> bool:
        along, across = self.local(x, y)
        return abs(along) <= FERRY_LENGTH_M / 2.0 and abs(across) <= FERRY_WIDTH_M / 2.0


def _route(points) -> Optional[FerryRoute]:
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + math.dist(a, b))
    if cumulative[-1] < FERRY_LENGTH_M + 10.0:  # no room to cross
        return None
    return FerryRoute([tuple(p) for p in points], cumulative)


class FerryManager:
    def __init__(self, railways: Sequence = ()) -> None:
        self.routes: List[FerryRoute] = []
        self.ferries: List[Ferry] = []
        self._population_elapsed = POPULATION_CHECK_S
        self.rebuild(railways)

    def rebuild(self, railways: Sequence) -> None:
        """The car ferry routes (again, as more map streams in); ferries on
        a route that is still there keep their place."""
        routes: List[FerryRoute] = []
        for railway in railways:
            if getattr(railway, "kind", "") != FERRY_KIND or len(railway.points_m) < 2:
                continue
            a, b = railway.points_m[0], railway.points_m[-1]
            if any(min(math.dist(a, r.points[0]) + math.dist(b, r.points[-1]),
                       math.dist(a, r.points[-1]) + math.dist(b, r.points[0])) <= 2 * DUPLICATE_END_M for r in routes):
                continue
            route = _route(railway.points_m)
            if route is not None:
                routes.append(route)
        kept = {tuple(r.points): r for r in routes}
        for ferry in self.ferries:
            ferry.route = kept.get(tuple(ferry.route.points), ferry.route)
        self.ferries = [f for f in self.ferries if tuple(f.route.points) in kept]
        self.routes = routes

    def on_deck(self, x: float, y: float) -> bool:
        return any(ferry.on_deck(x, y) for ferry in self.ferries)

    def cars(self, ferry: Ferry) -> List[Tuple[float, float, float, float, str]]:
        """Drawn like a train of one car (the state's "trains"): x, y, heading, length, look."""
        x, y, h = ferry.pose()
        return [(x, y, h, FERRY_LENGTH_M, "ferry")]

    def _populate(self, view_centre: Tuple[float, float]) -> None:
        served = {id(f.route) for f in self.ferries}
        for route in self.routes:
            near = min(math.dist(view_centre, p) for p in route.points) <= ACTIVE_RADIUS_M
            if near and id(route) not in served:
                half = FERRY_LENGTH_M / 2.0
                self.ferries.append(Ferry(route, half, half))
        self.ferries = [f for f in self.ferries
                        if min(math.dist(view_centre, p) for p in f.route.points) <= ACTIVE_RADIUS_M * 1.3]

    def update(self, dt: float, view_centre: Tuple[float, float], car=None) -> None:
        self._population_elapsed += dt
        if self._population_elapsed >= POPULATION_CHECK_S:
            self._population_elapsed = 0.0
            self._populate(view_centre)
        for ferry in self.ferries:
            self._run(ferry, dt, car)

    def _run(self, ferry: Ferry, dt: float, car) -> None:
        corners = get_oriented_box_corners(car.x, car.y, car.heading, getattr(car, "length_m", 4.5),
                                           getattr(car, "width_m", 1.8)) if car is not None else []
        aboard = sum(ferry.on_deck(x, y) for x, y in corners)
        if ferry.state == "DOCKED":
            ferry.wait_s += dt
            ferry.brought = ferry.brought and aboard > 0
            ready = aboard == 4 and not ferry.brought and abs(car.speed) < STOPPED_MPS
            ferry.ready_s = ferry.ready_s + dt if ready else 0.0
            straddling = 0 < aboard < 4  # never pulls the ramp from under a car
            if not straddling and (ferry.wait_s >= DOCK_WAIT_S or ferry.ready_s >= READY_WAIT_S):
                half = FERRY_LENGTH_M / 2.0
                ferry.target = ferry.route.length_m - half if ferry.target <= half else half
                ferry.state, ferry.wait_s, ferry.ready_s = "CROSSING", 0.0, 0.0
            return
        before = ferry.pose()
        remaining = abs(ferry.target - ferry.s)
        ferry.speed_mps = min(FERRY_SPEED_MPS, ferry.speed_mps + FERRY_ACCEL_MPS2 * dt,
                              math.sqrt(2.0 * FERRY_ACCEL_MPS2 * remaining))
        step = max(ferry.speed_mps * dt, min(remaining, 0.05))  # never stalls just short of the landing
        if step >= remaining:
            ferry.s, ferry.speed_mps, ferry.state = ferry.target, 0.0, "DOCKED"
            ferry.brought = aboard == 4
        else:
            ferry.s += math.copysign(step, ferry.target - ferry.s)
        if aboard == 4:
            _carry(car, before, ferry.pose())


def _carry(car, before: Tuple[float, float, float], after: Tuple[float, float, float]) -> None:
    """Moves the car on the deck as the deck moved: before -> after (x, y, heading)."""
    (bx, by, bh), (ax, ay, ah) = before, after
    turn = ah - bh
    dx, dy = car.x - bx, car.y - by
    car.x = ax + dx * math.cos(turn) - dy * math.sin(turn)
    car.y = ay + dx * math.sin(turn) + dy * math.cos(turn)
    car.heading += turn
