"""Resident-first world services without autonomous NPC vehicles."""

from __future__ import annotations

import heapq
import math
from typing import List, Optional, Tuple

from .osm import TrafficLight, Way
from .physics import is_car_road
from .residents import ResidentManager

# Cell size for _route_node_grid, plan_route's nearest-node lookup index -
# coarse relative to the ~3m node-merge distance in _build_route_graph,
# since this only needs to bound "how many cells to scan to find a
# handful of nearby graph nodes", not represent individual roads.
_ROUTE_NODE_GRID_CELL_M = 200.0


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
        nodes: List[Tuple[float, float, int]] = []
        edges: dict[int, List[Tuple[int, float]]] = {}
        buckets: dict[Tuple[int, int, int], List[int]] = {}

        def node_id(point: Tuple[float, float], layer: int) -> int:
            key = (round(point[0] / 3.0), round(point[1] / 3.0), layer)
            for candidate in buckets.get(key, ()):
                if math.hypot(nodes[candidate][0] - point[0], nodes[candidate][1] - point[1]) <= 3.0:
                    return candidate
            index = len(nodes)
            nodes.append((point[0], point[1], layer))
            edges[index] = []
            buckets.setdefault(key, []).append(index)
            return index

        for way in self.ways:
            if not is_car_road(way) or len(way.points_m) < 2:
                continue
            layer = getattr(way, "layer", 0)
            point_ids = [node_id(point, layer) for point in way.points_m]
            oneway = getattr(way, "oneway", 0)
            for first, second in zip(point_ids, point_ids[1:]):
                distance = math.hypot(
                    nodes[second][0] - nodes[first][0],
                    nodes[second][1] - nodes[first][1],
                )
                if oneway >= 0:
                    edges[first].append((second, distance))
                if oneway <= 0:
                    edges[second].append((first, distance))
        self._route_nodes = nodes
        self._route_edges = edges
        self._route_node_grid = {}
        for index, node in enumerate(nodes):
            cell = (math.floor(node[0] / _ROUTE_NODE_GRID_CELL_M), math.floor(node[1] / _ROUTE_NODE_GRID_CELL_M))
            self._route_node_grid.setdefault(cell, []).append(index)

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
                        if index in allowed:
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
            found = list(allowed)
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
    ) -> Optional[List[Tuple[float, float]]]:
        """Return a shortest road route for player navigation."""
        allowed = {
            index for index, node in enumerate(self._route_nodes)
            if layer is None or node[2] == layer
        }
        if not allowed:
            return None
        # Nearest 64 (the largest candidate_count search() below ever
        # asks for) via the grid index, not a sort of the whole graph -
        # search() still slices smaller candidate_counts from these same
        # two lists exactly as before.
        max_candidate_count = 64
        ranked_starts = self._nearest_node_indices(start, max_candidate_count, allowed)
        ranked_targets = self._nearest_node_indices(target, max_candidate_count, allowed)

        def search(candidate_count: int) -> Optional[List[int]]:
            starts = ranked_starts[:candidate_count]
            targets = ranked_targets[:candidate_count]
            target_distance = {
                index: math.hypot(
                    self._route_nodes[index][0] - target[0],
                    self._route_nodes[index][1] - target[1],
                )
                for index in targets
            }

            def heuristic(index: int) -> float:
                return min(
                    math.hypot(
                        self._route_nodes[index][0] - self._route_nodes[target_id][0],
                        self._route_nodes[index][1] - self._route_nodes[target_id][1],
                    )
                    + target_distance[target_id]
                    for target_id in targets
                )

            distances = {}
            previous = {}
            queue = []
            for index in starts:
                distance = math.hypot(
                    self._route_nodes[index][0] - start[0],
                    self._route_nodes[index][1] - start[1],
                )
                distances[index] = distance
                heapq.heappush(queue, (distance + heuristic(index), distance, index))
            best_target = None
            best_total = math.inf
            while queue:
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
                    if neighbor not in allowed:
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
            path = search(min(candidate_count, len(allowed)))
            if path is not None:
                return [start] + [
                    (self._route_nodes[index][0], self._route_nodes[index][1]) for index in path
                ] + [target]
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
        self.ways = ways
        if traffic_lights is not None:
            self.traffic_lights = traffic_lights
        if crossings is not None:
            self.crossings = crossings
        if logical_intersections is not None:
            self.logical_intersections = logical_intersections
        if parking_spaces is not None:
            self._parking_grid.clear()
            for space in parking_spaces:
                min_x, min_y, max_x, max_y = space.bbox
                min_cell_x = math.floor(min_x / self._parking_grid_cell_size)
                max_cell_x = math.floor(max_x / self._parking_grid_cell_size)
                min_cell_y = math.floor(min_y / self._parking_grid_cell_size)
                max_cell_y = math.floor(max_y / self._parking_grid_cell_size)
                for cell_x in range(min_cell_x, max_cell_x + 1):
                    for cell_y in range(min_cell_y, max_cell_y + 1):
                        self._parking_grid.setdefault((cell_x, cell_y), []).append(space)
        self._build_route_graph()
