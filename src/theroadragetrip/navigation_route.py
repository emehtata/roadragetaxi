"""The player's navigation route, owned by the server (godot-final-04).

Pygame's main() plans the route itself (main/__init__.py: N, `navigation_route`).
The server keeps the same lifecycle here, for every client:

- **No route without a target.**
- **When it replans:** for a new pickup/drop-off target, a new map level, a new
  route graph (`route_graph_revision`), or when the taxi is more than 35 m from
  every segment.
- **Surface routes** run as the resumable `plan_route_steps` job, a slice of at
  most `budget_s` per tick, so the 30 Hz tick never stalls on a long search.
- **Off the surface,** `world.level_routes.plan` gives this level's leg (as
  Pygame does).
- **What is published:** only a finished route, compacted once with
  `simplify_polyline`, as the state's `navigation.points`.
"""

from __future__ import annotations

import time
from typing import List, Optional, Sequence, Tuple

from .geo import dist_point_to_segment
from .map_level import SURFACE_LEVEL

ROUTE_DEVIATION_M = 35.0  # main(): farther than this from every segment -> re-plan
ROUTE_TOLERANCE_M = 0.5  # simplify_polyline: no dropped point lies farther than this from the line
ROUTE_BUDGET_S = 0.002  # route search per tick


def simplify_polyline(points: Sequence[Tuple[float, float]], tolerance_m: float = ROUTE_TOLERANCE_M) -> List[Tuple[float, float]]:
    """Douglas-Peucker, iterative: keeps both endpoints and every point the
    line would otherwise miss by more than `tolerance_m`."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = points[first]
        bx, by = points[last]
        worst, worst_index = -1.0, -1
        for i in range(first + 1, last):
            d = dist_point_to_segment(points[i][0], points[i][1], ax, ay, bx, by)
            if d > worst:
                worst, worst_index = d, i
        if worst > tolerance_m:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))
    return [p for p, kept in zip(points, keep) if kept]


class NavigationRoute:
    def __init__(self, budget_s: float = ROUTE_BUDGET_S) -> None:
        self.budget_s = budget_s
        self.points: list = []  # the published route, [[x, y], ...] in world metres
        self.raw_point_count = 0  # before simplification (performance report)
        self.worst_slice_s = 0.0  # longest single tick of route search so far
        self.plans_started = 0
        self._key = None  # (target, level, graph revision) the route and job belong to
        self._job = None  # the surface route search in progress
        self._job_started = 0.0

    def update(self, world, car, current_way=None) -> None:
        """Once per server tick, after the simulation step."""
        target = world.taxi_mgr.get_current_target()
        if target is None:
            self._job, self._key, self.points = None, None, []
            return
        traffic = world.traffic_mgr
        level = getattr(car, "map_level", SURFACE_LEVEL)
        key = ((round(target.x, 3), round(target.y, 3), getattr(target, "address", "")), level,
               getattr(traffic, "route_graph_revision", 0))
        if key != self._key:
            if self._key is None or key[:2] != self._key[:2]:
                self.points = []  # another target or level: the old line is wrong now
            self._start(world, car, current_way, target, level, key)  # (a new graph keeps the old line until the new one is done)
        elif self._job is None and self._off_route(car):
            self._start(world, car, current_way, target, level, key)
        if self._job is not None:
            self._advance()

    def _off_route(self, car) -> bool:
        if len(self.points) < 2:
            return False  # no route (unreachable): main() doesn't retry either until something changes
        return min(
            dist_point_to_segment(car.x, car.y, a[0], a[1], b[0], b[1])
            for a, b in zip(self.points, self.points[1:])
        ) > ROUTE_DEVIATION_M

    def _start(self, world, car, current_way, target, level, key) -> None:
        self._key = key
        self.plans_started += 1
        if level == SURFACE_LEVEL:
            layer = getattr(current_way, "layer", None) if current_way else None
            self._job = world.traffic_mgr.plan_route_steps((car.x, car.y), (target.x, target.y), layer=layer)
            self._job_started = time.perf_counter()
            return
        # Off the surface: this level's graph, out through its connectors; the
        # leg on this level (it re-plans on the next one). Synchronous, as main().
        self._job = None
        level_routes = getattr(world, "level_routes", None)
        route = level_routes.plan(world.traffic_mgr.route_graph(), (car.x, car.y), level, (target.x, target.y)) if level_routes else None
        self._publish(route.legs[0][1] if route and route.legs else None)

    def _advance(self) -> None:
        started = time.perf_counter()
        deadline = started + self.budget_s
        try:
            while True:
                next(self._job)
                if time.perf_counter() >= deadline:
                    break
        except StopIteration as finished:
            self._job = None
            self._publish(finished.value)
        self.worst_slice_s = max(self.worst_slice_s, time.perf_counter() - started)

    def _publish(self, route: Optional[Sequence[Tuple[float, float]]]) -> None:
        self.raw_point_count = len(route) if route else 0
        self.points = [[round(x, 2), round(y, 2)] for x, y in simplify_polyline(route)] if route and len(route) >= 2 else []
