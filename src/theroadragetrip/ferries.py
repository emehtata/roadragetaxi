"""Road ferries (docs/ferries.md): one ferry shuttles each car ferry route.

A route is an OSM route=ferry way that carries cars (osm/build.py,
Railway kind FERRY_KIND). Its ferry waits at a landing with its deck end
on the route's end point, crosses to the other end and waits there. No
timetable: game policy, the ferry serves the taxi. The taxi coming near a
landing finds the ferry there (it is brought there if it is not on its
way), and the ferry waits as long as the taxi is near; it leaves soon
after the taxi has stopped on its deck. Away from the taxi it leaves
after DOCK_WAIT_S. The taxi (or the parked taxi, the driver on foot) on
the deck is carried with it; deck points are dry land for the water brake
and sinking, and its side rails stop a car (simulation.py).

A ferry brought to the taxi's landing may arrive with a few NPC cars
(npc.NPCVehicleManager.ferry_car): they drive off the deck one at a time,
waiting while the taxi is in their way (a lawful wait, not a stuck car),
and start an ordinary trip from the landing (ferry_car_ashore). NPC trips
never plan across a ferry. Bounded work: ferries only on routes near the
viewpoint, a few rectangle tests a tick.
"""
from __future__ import annotations

import bisect
import itertools
import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .geo import get_oriented_box_corners
from .osm.build import FERRY_KIND

FERRY_LENGTH_M = 50.0  # a Finferries road ferry: ~50-90 m x 12-16 m
FERRY_WIDTH_M = 12.0  # render_style.gd FERRY_WIDTH_M
FERRY_SPEED_MPS = 4.5  # ~9 knots
FERRY_ACCEL_MPS2 = 0.25
DOCK_WAIT_S = 40.0  # docked with the taxi away: it leaves after this long
READY_WAIT_S = 4.0  # the taxi stopped on the deck this long: it leaves
STOPPED_MPS = 0.3
SUMMON_M = 150.0  # the taxi this near a landing (and not aboard): the ferry is there for it
HEADING_SPAN_M = 15.0  # heading from the route this far either side: no jolt at a bend
ACTIVE_RADIUS_M = 2500.0  # routes this near the viewpoint have their ferry
POPULATION_CHECK_S = 2.0
DUPLICATE_END_M = 80.0  # a route whose ends both lie this near another's: the other direction's way
RAIL_M = 0.8  # a corner this far inside a side rail crossed it
# NPC cars aboard: single file, driving off at walking pace.
MAX_ARRIVING_CARS = 2
LANE_ACROSS_M = 3.0
CAR_SLOT_M = 7.0
RIDER_SPEED_MPS = 3.0
ASHORE_M = 8.0  # a car this far past the deck end is ashore
RIDER_CLEARANCE_M = 8.0  # it waits while the taxi is this far ahead in its lane...
RIDER_LANE_M = 2.4  # ...this near its lane's centre line (two car half widths and a margin)

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

    def docked_s(self, end: int) -> float:
        """The ferry's centre docked at landing `end` (0: the route's first point, 1: its last)."""
        half = FERRY_LENGTH_M / 2.0
        return half if end == 0 else self.length_m - half


@dataclass
class Rider:
    """An NPC car on the deck, in deck coordinates (along the route, across to its left)."""
    vehicle: object
    along: float
    across: float
    facing: float  # its heading on the deck: 0 or pi
    exit_sign: int = 0  # driving off: towards +along (1) or -along (-1); 0 standing


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
    riders: List[Rider] = field(default_factory=list)

    def pose(self) -> Tuple[float, float, float]:
        x, y = self.route.at(self.s)
        return x, y, self.route.heading(self.s)

    def local(self, x: float, y: float) -> Tuple[float, float]:
        cx, cy, h = self.pose()
        dx, dy = x - cx, y - cy
        return dx * math.cos(h) + dy * math.sin(h), -dx * math.sin(h) + dy * math.cos(h)

    def world(self, along: float, across: float) -> Tuple[float, float]:
        cx, cy, h = self.pose()
        return cx + along * math.cos(h) - across * math.sin(h), cy + along * math.sin(h) + across * math.cos(h)

    def on_deck(self, x: float, y: float) -> bool:
        along, across = self.local(x, y)
        return abs(along) <= FERRY_LENGTH_M / 2.0 and abs(across) <= FERRY_WIDTH_M / 2.0

    @property
    def landing(self) -> Optional[int]:
        """The landing it is docked at (0 or 1), None while crossing."""
        if self.state != "DOCKED":
            return None
        return 0 if self.s <= self.route.length_m / 2.0 else 1

    def landing_sign(self, end: int) -> int:
        """Which way along the deck landing `end` lies: -1 (its rear) for the first point."""
        return -1 if end == 0 else 1


def _route(points) -> Optional[FerryRoute]:
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + math.dist(a, b))
    if cumulative[-1] < FERRY_LENGTH_M + 10.0:  # no room to cross
        return None
    return FerryRoute([tuple(p) for p in points], cumulative)


def _corners(car) -> List[Tuple[float, float]]:
    return get_oriented_box_corners(car.x, car.y, car.heading, getattr(car, "length_m", 4.5), getattr(car, "width_m", 1.8))


class FerryManager:
    def __init__(self, railways: Sequence = (), rng: Optional[random.Random] = None) -> None:
        self.routes: List[FerryRoute] = []
        self.ferries: List[Ferry] = []
        self.rng = rng or random  # the game's seeded draws (--test-seed)
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

    def blocks(self, car, previous: Tuple[float, float]) -> bool:
        """Whether the car's move from `previous` (x, y) took a corner across a
        ferry's side rail, in or out: the ends are a ferry's only way on and off."""
        before = get_oriented_box_corners(previous[0], previous[1], car.heading,
                                          getattr(car, "length_m", 4.5), getattr(car, "width_m", 1.8))
        for ferry in self.ferries:
            for (x0, y0), (x1, y1) in zip(before, _corners(car)):
                along0, across0 = ferry.local(x0, y0)
                along1, across1 = ferry.local(x1, y1)
                half_l, half_w = FERRY_LENGTH_M / 2.0, FERRY_WIDTH_M / 2.0
                if abs(along0) > half_l and abs(along1) > half_l:
                    continue  # beyond its ends
                if (abs(across0) <= half_w) != (abs(across1) <= half_w) and max(abs(along0), abs(along1)) <= half_l + RAIL_M:
                    return True
        return False

    def cars(self, ferry: Ferry) -> List[Tuple[float, float, float, float, str]]:
        """Drawn like a train of one car (the state's "trains"): x, y, heading, length, look."""
        x, y, h = ferry.pose()
        return [(x, y, h, FERRY_LENGTH_M, "ferry")]

    def _populate(self, view_centre: Tuple[float, float], npcs) -> None:
        served = {id(f.route) for f in self.ferries}
        for route in self.routes:
            near = min(math.dist(view_centre, p) for p in route.points) <= ACTIVE_RADIUS_M
            if near and id(route) not in served:
                self.ferries.append(Ferry(route, route.docked_s(0), route.docked_s(0)))
        gone = [f for f in self.ferries if min(math.dist(view_centre, p) for p in f.route.points) > ACTIVE_RADIUS_M * 1.3]
        for ferry in gone:
            for rider in ferry.riders:
                if npcs is not None and rider.vehicle in npcs.vehicles:
                    npcs.vehicles.remove(rider.vehicle)
        self.ferries = [f for f in self.ferries if f not in gone]

    def update(self, dt: float, view_centre: Tuple[float, float], car=None, npcs=None) -> None:
        """`npcs`: the NPC vehicle manager (its ferry_car, ferry_car_ashore, vehicles), None: no NPC cars aboard."""
        self._population_elapsed += dt
        if self._population_elapsed >= POPULATION_CHECK_S:
            self._population_elapsed = 0.0
            self._populate(view_centre, npcs)
        for ferry in self.ferries:
            if npcs is not None:
                ferry.riders = [r for r in ferry.riders if r.vehicle in npcs.vehicles]
            self._summon(ferry, car, npcs)
            self._run(ferry, dt, car, npcs)
            self._place_riders(ferry)

    def _taxi_landing(self, route: FerryRoute, car) -> Optional[int]:
        """The landing (0/1) the taxi is near, None."""
        if car is None:
            return None
        for end, point in ((0, route.points[0]), (1, route.points[-1])):
            if math.dist((car.x, car.y), point) <= SUMMON_M:
                return end
        return None

    def _summon(self, ferry: Ferry, car, npcs) -> None:
        """The taxi near a landing finds the ferry there: brought at once
        unless it is on its way or carries the taxi."""
        end = self._taxi_landing(ferry.route, car)
        if end is None or any(ferry.on_deck(x, y) for x, y in _corners(car)):
            return
        docked = ferry.route.docked_s(end)
        if ferry.landing == end or (ferry.state == "CROSSING" and ferry.target == docked):
            return
        ferry.s = ferry.target = docked
        ferry.state, ferry.speed_mps, ferry.wait_s, ferry.ready_s, ferry.brought = "DOCKED", 0.0, 0.0, 0.0, False
        if npcs is None or ferry.riders:
            return
        sign = ferry.landing_sign(end)  # they came from the other side: facing this landing
        # Single file in the lane on the right of the way they drive off (right-hand
        # traffic): the taxi waiting in its own lane at the landing is not in their way.
        across = -sign * LANE_ACROSS_M
        for k in range(self.rng.randint(0, MAX_ARRIVING_CARS)):
            along = sign * (FERRY_LENGTH_M / 2.0 - 5.0 - CAR_SLOT_M * k)
            facing = 0.0 if sign > 0 else math.pi
            x, y = ferry.world(along, across)
            ferry.riders.append(Rider(npcs.ferry_car(x, y, ferry.pose()[2] + facing), along, across, facing))

    def _run(self, ferry: Ferry, dt: float, car, npcs) -> None:
        aboard = sum(ferry.on_deck(x, y) for x, y in _corners(car)) if car is not None else 0
        if ferry.state == "DOCKED":
            self._unload(ferry, dt, car, npcs)
            ferry.wait_s += dt
            ferry.brought = ferry.brought and aboard > 0
            ready = aboard == 4 and not ferry.brought and abs(car.speed) < STOPPED_MPS
            ferry.ready_s = ferry.ready_s + dt if ready else 0.0
            taxi_near = self._taxi_landing(ferry.route, car) == ferry.landing
            unloading = any(abs(r.along) > FERRY_LENGTH_M / 2.0 - 2.5 for r in ferry.riders)  # one on the ramp
            leaves = (ferry.ready_s >= READY_WAIT_S if aboard or taxi_near
                      else ferry.wait_s >= DOCK_WAIT_S and not ferry.riders)
            if leaves and not unloading and aboard in (0, 4):  # never pulls the ramp from under a car
                ferry.target = ferry.route.docked_s(1 - ferry.landing)
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

    def _unload(self, ferry: Ferry, dt: float, car, npcs) -> None:
        """Docked: the NPC cars aboard drive off at its landing, nearest the ramp first."""
        if npcs is None or not ferry.riders:
            return
        sign = ferry.landing_sign(ferry.landing)
        rider = max(ferry.riders, key=lambda r: r.along * sign)
        rider.exit_sign = sign
        if car is not None and self._in_lane(ferry, rider, sign, car):
            rider.vehicle.car.speed = 0.0
            return  # the taxi is in its way: it waits
        rider.along += sign * RIDER_SPEED_MPS * dt
        rider.vehicle.car.speed = RIDER_SPEED_MPS if math.cos(rider.facing) * sign > 0 else -RIDER_SPEED_MPS
        if rider.along * sign >= FERRY_LENGTH_M / 2.0 + ASHORE_M:
            self._place(ferry, rider)
            ferry.riders.remove(rider)
            npcs.ferry_car_ashore(rider.vehicle)

    @staticmethod
    def _in_lane(ferry: Ferry, rider: Rider, sign: int, car) -> bool:
        """Whether the taxi is in the rider's way: in its lane, ahead of it towards the landing."""
        along, across = ferry.local(car.x, car.y)
        ahead = (along - rider.along) * sign
        return abs(across - rider.across) < RIDER_LANE_M and 0.0 < ahead < RIDER_CLEARANCE_M + getattr(car, "length_m", 4.5)

    def _place_riders(self, ferry: Ferry) -> None:
        for rider in ferry.riders:
            self._place(ferry, rider)

    def _place(self, ferry: Ferry, rider: Rider) -> None:
        rider.vehicle.car.x, rider.vehicle.car.y = ferry.world(rider.along, rider.across)
        rider.vehicle.car.heading = ferry.pose()[2] + rider.facing


def _carry(car, before: Tuple[float, float, float], after: Tuple[float, float, float]) -> None:
    """Moves the car on the deck as the deck moved: before -> after (x, y, heading)."""
    (bx, by, bh), (ax, ay, ah) = before, after
    turn = ah - bh
    dx, dy = car.x - bx, car.y - by
    car.x = ax + dx * math.cos(turn) - dy * math.sin(turn)
    car.y = ay + dx * math.sin(turn) + dy * math.cos(turn)
    car.heading += turn
