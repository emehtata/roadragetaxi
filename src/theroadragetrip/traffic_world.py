"""Resident-first world services without autonomous NPC vehicles."""

from __future__ import annotations

import heapq
import math
import time
from typing import Any, Generator, List, Optional, Tuple

from .osm import TrafficLight, Way
from .performance import advance_chunked
from .physics import is_car_road
from .residents import ResidentManager

# Cell size for _route_node_grid, plan_route's nearest-node lookup index -
# coarse relative to the ~3m node-merge distance in _build_route_graph,
# since this only needs to bound "how many cells to scan to find a
# handful of nearby graph nodes", not represent individual roads.
_ROUTE_NODE_GRID_CELL_M = 200.0
# plan_route joins start/target to any of several nearby graph nodes with a
# straight off-road "connector". Priced at plain distance, a connector from
# a node well before a corner beat driving the corner itself (e.g. 60 m +
# a 108 m beeline vs 200 m of road), producing cross-country shortcuts that
# NPC validation then rejected. Off-road metres cost this much more; the A*
# heuristic stays admissible since graph edges are never shorter than the
# straight line between their nodes.
ROUTE_CONNECTOR_COST_FACTOR = 4.0

# A resumable route search: a generator that yields after each unit of work
# and returns its result (bin-loader-v12.md "route planning is a job").
RouteSteps = Generator[None, None, Any]


def run_route_steps(steps: RouteSteps, deadline: Optional[float] = None) -> Any:
    """Drive a route job to completion, or give up (None) once `deadline`
    (a time.perf_counter() value) passes - the synchronous form every
    existing caller keeps using."""
    try:
        while True:
            next(steps)
            if deadline is not None and time.perf_counter() >= deadline:
                steps.close()
                return None
    except StopIteration as finished:
        return finished.value


def _component_root(parent: List[int], index: int) -> int:
    """Union-find root with path halving. Unions always keep the smaller
    root, so a root is its component's lowest node index."""
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


class RouteGraphBuild:
    """One in-progress route graph build (bin-loader-v13.md): nodes merged
    within 3 m per layer, directed edges honouring oneway, plus the node
    grid and weakly-connected-component union-find, all maintained way by
    way so no whole-graph pass runs in a single frame. Road-network
    agnostic: `include` selects which ways form the graph (car roads by
    default), so other networks (bus, tram, rail) can reuse it."""

    def __init__(self, ways, parking_spaces=None, parking_cell_size: float = 100.0, include=None) -> None:
        self.ways = list(ways)  # snapshot: later merges into the live list never leak in
        self.include = include or is_car_road
        self.parking_spaces = list(parking_spaces) if parking_spaces is not None else None
        self.parking_cell_size = parking_cell_size
        self.parking_grid = {} if parking_spaces is not None else None
        self.nodes: List[Tuple[float, float, int]] = []
        self.edges: dict[int, List[Tuple[int, float]]] = {}
        self.node_grid: dict[Tuple[int, int], List[int]] = {}
        self.component_parent: List[int] = []
        self._buckets: dict[Tuple[int, int, int], List[int]] = {}
        self._parking_index = 0
        self._way_index = 0

    def advance(self, budget_s: float) -> bool:
        """Process parking spaces, then ways, for about budget_s (always
        at least one item); True once everything is in."""
        deadline = time.perf_counter() + budget_s
        if self.parking_spaces is not None and self._parking_index < len(self.parking_spaces):
            self._parking_index = advance_chunked(
                self.parking_spaces, self._parking_index, budget_s, self._add_parking_space,
            )
            if self._parking_index < len(self.parking_spaces) or time.perf_counter() >= deadline:
                return False
        if self._way_index < len(self.ways):
            self._way_index = advance_chunked(
                self.ways, self._way_index, deadline - time.perf_counter(), self._add_way,
            )
        return self._way_index >= len(self.ways)

    def _add_parking_space(self, space) -> None:
        min_x, min_y, max_x, max_y = space.bbox
        cell = self.parking_cell_size
        for cell_x in range(math.floor(min_x / cell), math.floor(max_x / cell) + 1):
            for cell_y in range(math.floor(min_y / cell), math.floor(max_y / cell) + 1):
                self.parking_grid.setdefault((cell_x, cell_y), []).append(space)

    def _node_id(self, point: Tuple[float, float], layer: int) -> int:
        key = (round(point[0] / 3.0), round(point[1] / 3.0), layer)
        nodes = self.nodes
        for candidate in self._buckets.get(key, ()):
            if math.hypot(nodes[candidate][0] - point[0], nodes[candidate][1] - point[1]) <= 3.0:
                return candidate
        index = len(nodes)
        node = (point[0], point[1], layer)
        nodes.append(node)
        self.edges[index] = []
        self.component_parent.append(index)
        self._buckets.setdefault(key, []).append(index)
        self._index_node(index, node)
        return index

    def _index_node(self, index: int, node) -> None:
        cell = (math.floor(node[0] / _ROUTE_NODE_GRID_CELL_M), math.floor(node[1] / _ROUTE_NODE_GRID_CELL_M))
        self.node_grid.setdefault(cell, []).append(index)

    def _union(self, first: int, second: int) -> None:
        root_first = _component_root(self.component_parent, first)
        root_second = _component_root(self.component_parent, second)
        if root_first != root_second:
            self.component_parent[max(root_first, root_second)] = min(root_first, root_second)

    def _add_way(self, way) -> None:
        if not self.include(way) or len(way.points_m) < 2:
            return
        layer = getattr(way, "layer", 0)
        point_ids = [self._node_id(point, layer) for point in way.points_m]
        oneway = getattr(way, "oneway", 0)
        nodes, edges = self.nodes, self.edges
        for first, second in zip(point_ids, point_ids[1:]):
            distance = math.hypot(nodes[second][0] - nodes[first][0], nodes[second][1] - nodes[first][1])
            if oneway >= 0:
                edges[first].append((second, distance))
            if oneway <= 0:
                edges[second].append((first, distance))
            self._union(first, second)


class TrafficWorld:
    """Own shared world traffic services while vehicles remain player-controlled."""

    def __init__(
        self,
        ways: List[Way],
        traffic_lights: Optional[List[TrafficLight]] = None,
        crossings: Optional[List] = None,
        parking_spaces: Optional[List] = None,
        residents: Optional[ResidentManager] = None,
        logical_intersections: Optional[List] = None,
    ) -> None:
        self.ways = ways
        self.traffic_lights = traffic_lights or []
        self.crossings = crossings or []
        self.residents = residents or ResidentManager()
        self.sim_time = 0.0
        self.logical_intersections: List = logical_intersections if logical_intersections is not None else []
        self.intersection_manager = None
        self._parking_grid = {}
        self._parking_grid_cell_size = 100.0
        self._route_nodes: List[Tuple[float, float, int]] = []
        self._route_edges: dict[int, List[Tuple[int, float]]] = {}
        self._route_node_grid: dict[Tuple[int, int], List[int]] = {}
        self._pending_route_graph: Optional[RouteGraphBuild] = None
        # Set by main.py once npc.py's NPC vehicle list exists (a plain
        # list, kept as the same object reference so later appends to it
        # stay visible here) - lets PedestrianManager's linked-driver/
        # trip-group logic (multi-passenger-car.md) and its unrelated
        # generic "grab any nearby idle vehicle" mechanic both find real
        # NPCVehicle instances through this one duck-typed traffic_manager
        # interface, instead of needing their own copy of the list.
        self.npcs: List = []
        self.sync_map_data(
            ways,
            traffic_lights=traffic_lights,
            crossings=crossings,
            parking_spaces=parking_spaces,
            logical_intersections=logical_intersections,
        )

    def advance_time(self, dt: float) -> None:
        self.sim_time += dt

    def nearby_npcs_at(self, x: float, y: float, radius_m: float = 150.0) -> List:
        """NPC vehicles within radius_m of (x, y) - a linear scan is fine
        here: real NPC vehicle counts are tiny compared to ways/buildings,
        nowhere near needing a spatial grid of their own."""
        radius_sq = radius_m * radius_m
        return [
            vehicle for vehicle in self.npcs
            if (vehicle.x - x) ** 2 + (vehicle.y - y) ** 2 <= radius_sq
        ]

    def activate_occupied_vehicle(self, vehicle) -> None:
        """A pedestrian just stepped out of `vehicle` (pedestrian.py's
        generic "opportunistically drive any idle parked vehicle" flow,
        PedestrianManager.exit_vehicle) - clear its driver so it reads as
        idle/parked again."""
        vehicle.current_driver_id = None
        vehicle.state = "driving"

    def _build_route_graph(self) -> None:
        """Synchronous full rebuild of the route graph from self.ways."""
        build = RouteGraphBuild(self.ways)
        build.advance(math.inf)
        self._commit_route_graph(build)

    def _commit_route_graph(self, build: "RouteGraphBuild") -> None:
        """Atomically swap in a finished graph; route_graph_revision
        identifies it - a route job planned against an older revision must
        not be applied (bin-loader-v12.md)."""
        self._route_nodes = build.nodes
        self._route_edges = build.edges
        self._route_node_grid = build.node_grid
        self._route_component_parent = build.component_parent
        if build.parking_grid is not None:
            self._parking_grid = build.parking_grid
        self.route_graph_revision = getattr(self, "route_graph_revision", 0) + 1

    def _finish_route_graph(self) -> None:
        """Rebuild the derived indexes (grid, components) for an already
        assigned _route_nodes/_route_edges and commit a new revision -
        for callers that construct the graph arrays directly (tests)."""
        build = RouteGraphBuild([])
        build.nodes, build.edges = self._route_nodes, self._route_edges
        build.component_parent = list(range(len(build.nodes)))
        for index, node in enumerate(build.nodes):
            build._index_node(index, node)
        for first, neighbors in build.edges.items():
            for second, _distance in neighbors:
                build._union(first, second)
        self._commit_route_graph(build)

    def start_map_sync(
        self, ways, traffic_lights=None, crossings=None, parking_spaces=None,
        logical_intersections=None, **_kwargs,
    ) -> None:
        """Begin a budgeted rebuild (bin-loader-v13.md) of the route graph
        and parking grid from a snapshot of `ways`/`parking_spaces`. The
        previous graph stays authoritative for every query and route job
        until advance_map_sync() commits the new one atomically. Signal
        lists are cheap and applied immediately, as before."""
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights
        if crossings is not None:
            self.crossings = crossings
        if logical_intersections is not None:
            self.logical_intersections = logical_intersections
        self._pending_route_graph = RouteGraphBuild(ways, parking_spaces, self._parking_grid_cell_size)

    def advance_map_sync(self, budget_s: float) -> bool:
        """Advance a start_map_sync() build by about budget_s; True once the
        new graph (and a new route_graph_revision) is committed."""
        build = getattr(self, "_pending_route_graph", None)
        if build is None:
            return True
        if not build.advance(budget_s):
            return False
        self.ways = build.ways
        self._commit_route_graph(build)
        self._pending_route_graph = None
        return True

    def _nearest_node_indices(self, point: Tuple[float, float], count: int, allowed) -> List[int]:
        """The `count` nodes in `allowed` closest to `point`, found by
        expanding outward through `_route_node_grid`'s cells instead of
        sorting the *entire* route graph (client-server-016.md: plan_route
        used to do exactly that sort - twice, on every single call,
        regardless of how close start/target actually were - dominating
        its cost on a real city-sized graph and showing up as a periodic
        frame spike each time the population tick started an NPC trip).

        One extra ring past the first that satisfies `count` is a cheap,
        standard safety margin for a diagonal neighbor slightly closer
        than something already found (same expanding-radius idiom
        pedestrian.py's _nearby_ped_ways already uses) - candidate seeding
        only, not the final path, so an occasional imperfect ordering here
        can't produce a wrong route, at most a marginally different one.
        """
        cell_size = _ROUTE_NODE_GRID_CELL_M
        cx = math.floor(point[0] / cell_size)
        cy = math.floor(point[1] / cell_size)
        found: List[int] = []
        radius = 0
        extra_ring = False
        max_radius = max(1, len(self._route_node_grid))
        while radius <= max_radius:
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue  # only the newly-added outer ring
                    for index in self._route_node_grid.get((cx + dx, cy + dy), ()):
                        if allowed is None or index in allowed:
                            found.append(index)
            if len(found) >= count:
                if extra_ring:
                    break
                extra_ring = True
            radius += 1
        if not found:
            # point is nowhere near any mapped road (e.g. a genuinely
            # unreachable/off-map destination) - the grid can't help
            # here since expanding from point's own cell never reaches
            # the populated area within a sane radius. Rare; fall back
            # to the exhaustive sort plan_route always used to do.
            found = list(range(len(self._route_nodes))) if allowed is None else list(allowed)
        found.sort(
            key=lambda index: (self._route_nodes[index][0] - point[0]) ** 2
            + (self._route_nodes[index][1] - point[1]) ** 2
        )
        return found[:count]

    def plan_route(
        self,
        start: Tuple[float, float],
        target: Tuple[float, float],
        layer: Optional[int] = None,
        deadline: Optional[float] = None,
    ) -> Optional[List[Tuple[float, float]]]:
        """Return a shortest road route for player navigation (None if
        none, or if `deadline` passes first)."""
        return run_route_steps(self.plan_route_steps(start, target, layer), deadline)

    def plan_route_steps(
        self,
        start: Tuple[float, float],
        target: Tuple[float, float],
        layer: Optional[int] = None,
    ) -> RouteSteps:
        """plan_route as a resumable job: yields after every search node
        expansion, returns the route (or None) - see run_route_steps."""
        # None = every node allowed (layer is None): no whole-graph set per call.
        allowed = None if layer is None else {
            index for index, node in enumerate(self._route_nodes) if node[2] == layer
        }
        if not self._route_nodes or allowed is not None and not allowed:
            return None
        # Nearest 64 (the largest candidate_count search() below ever
        # asks for) via the grid index, not a sort of the whole graph -
        # search() still slices smaller candidate_counts from these same
        # two lists exactly as before.
        node_count = len(self._route_nodes) if allowed is None else len(allowed)
        max_candidate_count = 64
        ranked_starts = self._nearest_node_indices(start, max_candidate_count, allowed)
        ranked_targets = self._nearest_node_indices(target, max_candidate_count, allowed)
        nodes = self._route_nodes
        parent = self._route_component_parent

        def search(candidate_count: int):
            starts = ranked_starts[:candidate_count]
            targets = ranked_targets[:candidate_count]
            # No start shares a weak component with any target: no route
            # can exist, so skip the search that would explore it all.
            if not {_component_root(parent, index) for index in starts} & {
                _component_root(parent, index) for index in targets
            }:
                return None
            target_distance = {
                index: ROUTE_CONNECTOR_COST_FACTOR * math.hypot(nodes[index][0] - target[0], nodes[index][1] - target[1])
                for index in targets
            }
            heuristic_cache: dict = {}

            def heuristic(index: int) -> float:
                value = heuristic_cache.get(index)
                if value is None:
                    value = heuristic_cache[index] = min(
                        math.hypot(nodes[index][0] - nodes[target_id][0], nodes[index][1] - nodes[target_id][1])
                        + target_distance[target_id]
                        for target_id in targets
                    )
                return value

            distances = {}
            previous = {}
            queue = []
            for index in starts:
                distance = ROUTE_CONNECTOR_COST_FACTOR * math.hypot(nodes[index][0] - start[0], nodes[index][1] - start[1])
                distances[index] = distance
                heapq.heappush(queue, (distance + heuristic(index), distance, index))
            best_target = None
            best_total = math.inf
            while queue:
                yield
                estimated_total, distance, current = heapq.heappop(queue)
                if distance != distances.get(current):
                    continue
                if estimated_total > best_total:
                    break
                if current in target_distance:
                    total = distance + target_distance[current]
                    if total < best_total:
                        best_total = total
                        best_target = current
                for neighbor, edge_distance in self._route_edges.get(current, ()):
                    if allowed is not None and neighbor not in allowed:
                        continue
                    candidate = distance + edge_distance
                    if candidate < distances.get(neighbor, math.inf):
                        distances[neighbor] = candidate
                        previous[neighbor] = current
                        heapq.heappush(queue, (candidate + heuristic(neighbor), candidate, neighbor))
            if best_target is None:
                return None
            path = [best_target]
            while path[-1] in previous:
                path.append(previous[path[-1]])
            path.reverse()
            return path

        for candidate_count in (8, 16, 32, 64):
            yield
            path = yield from search(min(candidate_count, node_count))
            if path is not None:
                return [start] + [(nodes[index][0], nodes[index][1]) for index in path] + [target]
        return None

    def _nearby_traffic_lights(self, x: float, y: float, radius_m: float = 60.0) -> List[TrafficLight]:
        radius_sq = radius_m * radius_m
        return [
            light for light in self.traffic_lights
            if (light.x - x) ** 2 + (light.y - y) ** 2 <= radius_sq
        ]

    def let_taxi_pick_up_waiter(self, taxi_stops, pedestrians, dt: float = 1.0 / 60.0) -> None:
        return None

    def sync_map_data(
        self, ways, traffic_lights=None, crossings=None, parking_spaces=None,
        logical_intersections=None, **_kwargs,
    ) -> None:
        """Synchronous form of start_map_sync()/advance_map_sync()."""
        self.start_map_sync(
            ways, traffic_lights=traffic_lights, crossings=crossings,
            parking_spaces=parking_spaces, logical_intersections=logical_intersections,
        )
        self.advance_map_sync(math.inf)
