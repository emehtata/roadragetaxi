"""The player's navigation route, owned by the server (godot-final-04).

The route lifecycle, for every client:

- **No route without a target.**
- **When it replans:** for a new pickup/drop-off target, a new map level, a new
  route graph (`route_graph_revision`), or when the taxi is more than 35 m from
  every segment.
- **Surface routes** run as the resumable `plan_route_steps` job, a slice of at
  most `budget_s` per tick, so the 30 Hz tick never stalls on a long search.
- **Off the surface,** `world.level_routes.plan` gives this level's leg.
- **What is published:** only a finished route, compacted once with
  `simplify_polyline`, as the state's `navigation.points`, plus the next-turn
  instruction (direction, route distance and outgoing street) for the phone.
"""

from __future__ import annotations

import time
import math
from typing import List, Optional, Sequence, Tuple

from .geo import dist_point_to_segment, closest_point_and_dist_to_segment, angle_diff
from .map_level import SURFACE_LEVEL, on_map_level

ROUTE_DEVIATION_M = 35.0  # farther than this from every segment -> re-plan
ROUTE_TOLERANCE_M = 0.5  # simplify_polyline: no dropped point lies farther than this from the line
ROUTE_BUDGET_S = 0.002  # route search per tick


def next_turn(points, x, y):
    """Next geometric turn and distance along the route, never straight-line
    distance, and the whole remaining route (total_m)."""
    if len(points) < 2:
        return None
    nearest = None
    for i, (a, b) in enumerate(zip(points, points[1:])):
        px, py, _, gap = closest_point_and_dist_to_segment(x, y, *a, *b)
        candidate = (gap, -i, px, py)
        if nearest is None or candidate < nearest:
            nearest = candidate
    _, negative_index, px, py = nearest
    index = -negative_index
    distance = math.hypot(points[index + 1][0] - px, points[index + 1][1] - py)
    total = round(distance + sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points[index + 1:], points[index + 2:])), 1)
    for i in range(index + 1, len(points) - 1):
        a, b, c = points[i - 1:i + 2]
        incoming = math.atan2(b[1] - a[1], b[0] - a[0])
        outgoing = math.atan2(c[1] - b[1], c[0] - b[0])
        turn = math.degrees(angle_diff(outgoing, incoming))
        if abs(turn) >= 30:
            return {"maneuver": "uturn" if abs(turn) >= 150 else "left" if turn > 0 else "right",
                    "distance_m": round(distance, 1), "total_m": total, "angle_deg": round(turn), "turn_index": i}
        distance += math.hypot(c[0] - b[0], c[1] - b[1])
    return {"maneuver": "arrive" if distance <= 10 else "straight", "distance_m": round(distance, 1),
            "total_m": total, "angle_deg": 0, "turn_index": len(points) - 1}


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
        self.worst_slice_s = 0.0  # longest single tick of route search so far
        self.plans_started = 0
        self._key = None  # (target, level, graph revision) the route and job belong to
        self._job = None  # the surface route search in progress
        self.instruction = {"maneuver": "no_target"}
        self._street_names = {}
        self._intercity = None
        self._future = None
        self._intercity_key = None
        self._national = None
        self._national_index = 0
        self._failed_revision = None
        self._failed_start = None

    def close(self):
        if self._intercity:
            self._intercity.close()

    def _clear_intercity(self, world):
        if self._intercity_key is None:
            return
        self._intercity.cancel()
        if self._future:
            self._future.cancel()
        self._future = self._national = self._intercity_key = None
        self._key = None
        self.points = []
        manager = getattr(world,"auto_fetch_manager",None)
        if manager:
            manager.set_route_tiles([])

    def _update_intercity(self, world, car, target, current_way):
        from .intercity_navigation import IntercityPlanner
        from .geo import closest_point_and_dist_to_segment
        from .tile_streaming import world_to_tile, active_tiles
        if self._intercity is None:
            self._intercity = IntercityPlanner(world.intercity_database)
        key = (target.intercity_place_id,getattr(car,"map_level",0))
        revision = world.traffic_mgr.route_graph_revision
        if self._failed_start and math.dist(self._failed_start,(car.x,car.y)) > 100:
            self._failed_revision = None
        if key != self._intercity_key:
            self._clear_intercity(world)
            self._intercity_key = key
            self._failed_revision = None
            self._job = None
        if self._future and self._future.done():
            try:
                self._national = self._future.result()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Intercity planning failed")
                self._national = None
            self._future = None
            self._national_index = 0
            self._failed_revision = revision
            self._failed_start = (car.x,car.y)
            self._street_names = {}
        if self._national:
            points = self._national["points"]
            first = self._national_index
            # A bounded forward window, not a national-polyline scan each tick.
            last = min(len(points)-1,first+128)
            nearest = min((closest_point_and_dist_to_segment(car.x,car.y,*points[i],*points[i+1])[3],-i)
                          for i in range(first,last)) if last > first else (math.inf,-first)
            if nearest[0] > ROUTE_DEVIATION_M:
                self._national = None
                self.points = []
                self._failed_revision = None
            else:
                if self._national_index != -nearest[1]:
                    self._street_names = {}
                self._national_index = -nearest[1]
                self.points = [list(p) for p in points[self._national_index:self._national_index+257]]
        if self._national is None and self._future is None and self._failed_revision != revision:
            self.plans_started += 1
            self._future = self._intercity.request((car.x,car.y),target.intercity_place_id,
                world.traffic_mgr.route_graph(),getattr(current_way,"layer",None),tuple(world.traffic_mgr.ways))
        self._update_instruction(world,car,current_way)
        if self._future:
            self.instruction = {"maneuver":"routing"}
        if self._national and "total_m" in self.instruction:
            index = self._national_index+len(self.points)-1
            self.instruction["total_m"] = round(self.instruction["total_m"]+self._national["remaining"][index],1)
        if self._national and self.instruction.get("maneuver") in {"arrive","straight"} and self._national_index+len(self.points) < len(self._national["points"]):
            self.instruction["maneuver"] = "straight"
        manager = getattr(world,"auto_fetch_manager",None)
        if manager:
            core = set(active_tiles(world_to_tile(car.x,car.y)))
            tiles = []
            travelled = 0.0
            for segment_index,(a,b) in enumerate(zip(self.points,self.points[1:])):
                if segment_index == 0:
                    px,py,_,_ = closest_point_and_dist_to_segment(car.x,car.y,*a,*b)
                    a = (px,py)
                length = math.dist(a,b)
                # Sample long straight segments too; vertices may be kilometres apart.
                for step in range(1,min(10,math.ceil(length/500))+1):
                    distance = min(length,step*500)
                    if travelled+distance > 5000:
                        break
                    ratio = distance/max(length,.001)
                    tile = world_to_tile(a[0]+(b[0]-a[0])*ratio,a[1]+(b[1]-a[1])*ratio)
                    if tile not in core and tile not in tiles:
                        tiles.append(tile)
                travelled += length
                if travelled >= 5000 or len(tiles) >= 3:
                    break
            if math.dist((car.x,car.y),(target.x,target.y)) <= 6000:
                tiles.insert(0,world_to_tile(target.x,target.y))
            manager.set_route_tiles(tiles[:3])

    def update(self, world, car, current_way=None) -> None:
        """Once per server tick, after the simulation step."""
        target = world.taxi_mgr.get_current_target()
        if (target is not None and getattr(target,"municipality",None)
                and getattr(target,"intercity_place_id",None) and getattr(world,"intercity_database",None)
                and getattr(car,"map_level",SURFACE_LEVEL) == SURFACE_LEVEL):
            self._update_intercity(world,car,target,current_way)
            return
        self._clear_intercity(world)
        if target is None:
            self._job, self._key, self.points = None, None, []
            self.instruction = {"maneuver": "no_target"}
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
        self._update_instruction(world, car, current_way)

    def _update_instruction(self, world, car, current_way):
        if self._job is not None:
            self.instruction = {"maneuver": "routing"}
            return
        instruction = next_turn(self.points, car.x, car.y)
        if instruction is None:
            self.instruction = {"maneuver": "unreachable"}
            return
        index = instruction.pop("turn_index")
        if index not in self._street_names:
            name = ""
            if index < len(self.points) - 1:
                a, b = self.points[index:index + 2]
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                t = min(.5, 8.0 / max(length, .001))
                x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                grid = getattr(world, "spatial_grid", None)
                ways = grid.ways_in_rect(x - 4, y - 4, x + 4, y + 4) if grid else getattr(world.traffic_mgr, "ways", ())
                best = None
                heading = math.atan2(b[1] - a[1], b[0] - a[0])
                for way in ways:
                    if not getattr(way, "is_drivable", True) or not on_map_level(way, getattr(car, "map_level", 0)):
                        continue
                    if current_way is not None and way.layer != current_way.layer:
                        continue
                    for start, end in zip(way.points_m, way.points_m[1:]):
                        gap = dist_point_to_segment(x, y, *start, *end)
                        alignment = abs(math.sin(math.atan2(end[1] - start[1], end[0] - start[0]) - heading))
                        if gap <= way.half_width_m and alignment < .5:
                            key = (gap, alignment)
                            if best is None or key < best:
                                best, name = key, way.name or ""
            self._street_names[index] = name
        instruction["street"] = self._street_names[index]
        self.instruction = instruction

    def _off_route(self, car) -> bool:
        if len(self.points) < 2:
            return False  # no route (unreachable): no retry until something changes
        return min(
            dist_point_to_segment(car.x, car.y, a[0], a[1], b[0], b[1])
            for a, b in zip(self.points, self.points[1:])
        ) > ROUTE_DEVIATION_M

    def _start(self, world, car, current_way, target, level, key) -> None:
        self._key = key
        self.plans_started += 1
        if level == SURFACE_LEVEL:
            # Surface roads include connected bridges of different OSM layers.
            self._job = world.traffic_mgr.plan_route_steps(
                (car.x, car.y), (target.x, target.y), on_road=True,
                start_layer=getattr(current_way, "layer", None))
            return
        # Off the surface: this level's graph, out through its connectors; the
        # leg on this level (it re-plans on the next one). Synchronous.
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
        self._street_names = {}
        self.points = [[round(x, 2), round(y, 2)] for x, y in simplify_polyline(route)] if route and len(route) >= 2 else []
