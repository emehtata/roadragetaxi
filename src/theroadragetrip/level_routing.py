"""Level-aware route planning (garage-10_11.md).

One route graph per logical map level, and resolved level connectors as
the only links between them:

- level 0 is the existing surface graph (TrafficWorld's, surface car
  roads only); every other level gets a RouteGraphBuild over exactly the
  roads LevelRoadNetworks drives on there - level=-1 roads, plus
  multi-level ramps such as level=0;-1 on each level they name. Driving
  and routing therefore always agree on what a level contains, and a
  graph never holds a road from another level, so nothing connects
  across levels by shared coordinates or nodes.
- a cross-level edge exists only for a connector level_transitions.
  resolve_connectors resolved (explicit road-level evidence, unambiguous
  destination), and only where the connector's own entrance node is a
  node of both level graphs. Connectors have no direction in OSM, so the
  edge runs both ways; the roads' own oneway still applies on each side.
- a connector adds no cost of its own: an entrance is a point, and the
  real distance through it is the road geometry on either side, which
  each leg already counts.

Planning is a Dijkstra over (level, position) states whose steps are
ordinary single-level routes (traffic_world.graph_route_steps) to a
connector or to the target; with a handful of connectors per city that
is a few route searches. The result keeps each leg's level and the
connectors between them. Graphs are built when map data changes (startup,
map sync) - small (Oulu: a few hundred roads off the surface) - never
per frame.
"""

import heapq
import itertools
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .map_level import SURFACE_LEVEL
from .physics import is_car_road
from .traffic_world import RouteGraphBuild, graph_route_steps, nearest_node_indices, run_route_steps

CONNECTOR_NODE_SNAP_M = 3.0  # a level graph must have a node this close to the entrance node


@dataclass(frozen=True)
class LevelTransitionEdge:
    connector_osm_id: int
    from_level: int
    to_level: int
    x: float
    y: float


@dataclass
class LevelRoute:
    """A route across levels: legs[i] = (level, points) driven on that
    level, joined by transitions[i] between legs[i] and legs[i + 1]."""

    legs: List[Tuple[int, List[Tuple[float, float]]]] = field(default_factory=list)
    transitions: List[LevelTransitionEdge] = field(default_factory=list)
    length_m: float = 0.0


def _length(points) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _has_node_near(graph, x: float, y: float) -> bool:
    nearest = nearest_node_indices(graph.nodes, graph.node_grid, (x, y), 1, None) if graph.nodes else []
    return bool(nearest) and math.dist(graph.nodes[nearest[0]][:2], (x, y)) <= CONNECTOR_NODE_SNAP_M


class LevelRouteGraphs:
    def __init__(self, level_roads, topologies=()) -> None:
        self.graphs: Dict[int, RouteGraphBuild] = {}
        for level in level_roads.levels():
            build = RouteGraphBuild(level_roads.network(level)[0], include=is_car_road)
            build.advance(math.inf)
            if build.nodes:
                self.graphs[level] = build
        self.edges: Dict[int, List[LevelTransitionEdge]] = {}
        for topology in topologies:
            connector = topology.connector
            for level in topology.levels:
                destination = topology.destination(level)
                if destination is not None:
                    self.edges.setdefault(level, []).append(
                        LevelTransitionEdge(connector.osm_id, level, destination, connector.x, connector.y)
                    )

    def graph(self, level: int, surface_graph):
        """The route graph for a level - the surface one for level 0 - or
        None when the level has no car roads. Never another level's."""
        return surface_graph if level == SURFACE_LEVEL else self.graphs.get(level)

    def usable_edges(self, surface_graph) -> List[LevelTransitionEdge]:
        """Connector edges whose entrance node is in both level graphs."""
        return [
            edge for edges in self.edges.values() for edge in edges
            if all(
                (graph := self.graph(level, surface_graph)) is not None and _has_node_near(graph, edge.x, edge.y)
                for level in (edge.from_level, edge.to_level)
            )
        ]

    def plan(self, surface_graph, start, start_level: int, target, target_level: int = SURFACE_LEVEL) -> Optional[LevelRoute]:
        """Shortest route from start on start_level to target on
        target_level, through resolved connectors only; None if none."""
        edges_by_level: Dict[int, List[LevelTransitionEdge]] = {}
        for edge in self.usable_edges(surface_graph):
            edges_by_level.setdefault(edge.from_level, []).append(edge)
        order = itertools.count()
        queue = [(0.0, next(order), start_level, tuple(start), (), (), False)]
        settled = set()
        while queue:
            cost, _, level, position, legs, transitions, done = heapq.heappop(queue)
            if done:
                return LevelRoute(list(legs), list(transitions), cost)
            if (level, position) in settled:
                continue
            settled.add((level, position))
            graph = self.graph(level, surface_graph)
            if graph is None:
                continue
            if level == target_level:
                points = run_route_steps(graph_route_steps(graph, position, tuple(target)))
                if points:
                    heapq.heappush(queue, (cost + _length(points), next(order), level, tuple(target),
                                           legs + ((level, points),), transitions, True))
            for edge in edges_by_level.get(level, ()):
                points = run_route_steps(graph_route_steps(graph, position, (edge.x, edge.y)))
                if points:
                    heapq.heappush(queue, (cost + _length(points), next(order), edge.to_level, (edge.x, edge.y),
                                           legs + ((level, points),), transitions + (edge,), False))
        return None
