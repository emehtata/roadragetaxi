"""Road graph construction and shortest-path routing."""
from __future__ import annotations

import heapq
import math
from typing import Callable, Dict, List, Optional, Tuple

from .osm import Way

RouteNode = Tuple[float, float, int]
RouteEdges = Dict[int, List[Tuple[int, float]]]


def roundabout_direction(way: Way) -> int:
    """Return point traversal direction that is geometrically counter-clockwise."""
    points = way.points_m
    area = sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(points, points[1:])
    )
    return 1 if area >= 0.0 else -1


def build_route_graph(ways: List[Way]) -> Tuple[List[RouteNode], RouteEdges, Dict[int, RouteEdges]]:
    """Build the immutable vertex graph used by navigation routing."""
    nodes: List[RouteNode] = []
    edges: RouteEdges = {}
    endpoint_buckets: Dict[Tuple[int, int, int], List[int]] = {}

    def node_id(point: Tuple[float, float], point_layer: int) -> int:
        bucket = (round(point[0] / 3.0), round(point[1] / 3.0), point_layer)
        for candidate in endpoint_buckets.get(bucket, []):
            candidate_point = nodes[candidate]
            if math.hypot(candidate_point[0] - point[0], candidate_point[1] - point[1]) <= 3.0:
                return candidate
        candidate = len(nodes)
        nodes.append((point[0], point[1], point_layer))
        endpoint_buckets.setdefault(bucket, []).append(candidate)
        edges[candidate] = []
        return candidate

    for way in ways:
        if len(way.points_m) < 2:
            continue
        point_layer = getattr(way, "layer", 0)
        point_ids = [node_id(point, point_layer) for point in way.points_m]
        oneway = getattr(way, "oneway", 0)
        if getattr(way, "is_roundabout", False):
            oneway = roundabout_direction(way)
        for first, second in zip(point_ids, point_ids[1:]):
            distance = math.hypot(
                nodes[second][0] - nodes[first][0], nodes[second][1] - nodes[first][1]
            )
            if oneway >= 0:
                edges[first].append((second, distance))
            if oneway <= 0:
                edges[second].append((first, distance))

    layers = {node[2] for node in nodes}
    edges_by_layer = {
        layer: {
            index: [
                (neighbor, distance)
                for neighbor, distance in neighbors
                if nodes[neighbor][2] == layer
            ]
            for index, neighbors in edges.items()
            if nodes[index][2] == layer
        }
        for layer in layers
    }
    return nodes, edges, edges_by_layer


def plan_route(
    nodes: List[RouteNode],
    edges: RouteEdges,
    edges_by_layer: Dict[int, RouteEdges],
    start: Tuple[float, float],
    target: Tuple[float, float],
    layer: Optional[int] = None,
) -> Optional[List[Tuple[float, float]]]:
    """Return a shortest route over road vertices between two map positions."""
    route_edges = edges_by_layer.get(layer, {}) if layer is not None else edges
    if not nodes:
        return None
    start_candidates = sorted(
        route_edges,
        key=lambda index: (nodes[index][0] - start[0]) ** 2 + (nodes[index][1] - start[1]) ** 2,
    )[:12]
    target_candidates = sorted(
        route_edges,
        key=lambda index: (nodes[index][0] - target[0]) ** 2 + (nodes[index][1] - target[1]) ** 2,
    )[:12]
    distances: Dict[int, float] = {}
    previous: Dict[int, int] = {}
    queue: List[Tuple[float, int]] = []
    for start_id in start_candidates:
        connector = math.hypot(nodes[start_id][0] - start[0], nodes[start_id][1] - start[1])
        distances[start_id] = connector
        heapq.heappush(queue, (connector, start_id))
    while queue:
        distance, current = heapq.heappop(queue)
        if distance != distances.get(current):
            continue
        for neighbor, edge_distance in route_edges[current]:
            new_distance = distance + edge_distance
            if new_distance < distances.get(neighbor, math.inf):
                distances[neighbor] = new_distance
                previous[neighbor] = current
                heapq.heappush(queue, (new_distance, neighbor))
    best_target = None
    best_score = math.inf
    for target_id in target_candidates:
        if target_id not in distances:
            continue
        target_connector = math.hypot(nodes[target_id][0] - target[0], nodes[target_id][1] - target[1])
        score = distances[target_id] + target_connector
        if score < best_score:
            best_score = score
            best_target = target_id
    if best_target is None:
        return None
    path = [best_target]
    while path[-1] in previous:
        path.append(previous[path[-1]])
    path.reverse()
    return [(start[0], start[1])] + [
        (nodes[index][0], nodes[index][1]) for index in path
    ] + [target]
