"""Level-aware route graphs joined by resolved connectors (garage-10_11.md)."""
import math

import pytest

from theroadragetrip.level_routing import LevelRouteGraphs
from theroadragetrip.level_transitions import resolve_connectors
from theroadragetrip.map_level import LevelRoadNetworks, parse_map_level
from theroadragetrip.osm import LevelConnector, Way
from theroadragetrip.traffic_world import RouteGraphBuild, graph_route_steps, run_route_steps


def _road(osm_id, points, level=None, layer=0, is_tunnel=False):
    return Way(points, "service", 3.0, osm_id=osm_id, layer=layer, is_tunnel=is_tunnel,
               level=level, map_level=parse_map_level(level))


def _entrance(osm_id, x, y, roads):
    return LevelConnector("node", osm_id, "parking_entrance", x, y, road_osm_ids=tuple(roads))


def _world(ways, level_ways=(), connectors=()):
    surface = RouteGraphBuild(ways)  # default: surface car roads only (TrafficWorld's graph)
    surface.advance(math.inf)
    level_roads = LevelRoadNetworks(ways, level_ways)
    topologies, _ = resolve_connectors(connectors, ways, level_ways)
    return surface, LevelRouteGraphs(level_roads, topologies)


def _graph_points(graph):
    return {(round(x), round(y)) for x, y, _ in graph.nodes} if graph is not None else set()


@pytest.mark.parametrize("level, graphs", [
    (None, {0}), ("0", {0}), ("-1", {-1}), ("0;-1", {0, -1}), ("-1;-2", {-1, -2}),
])
def test_roads_land_in_the_graphs_of_their_levels(level, graphs):
    road = _road(1, [(0.0, 0.0), (50.0, 0.0)], level=level)
    ways, level_ways = ([road], []) if level in (None, "0", "0;-1") else ([], [road])
    surface, routes = _world(ways, level_ways)
    present = {lvl for lvl in (0, -1, -2) if (0, 0) in _graph_points(routes.graph(lvl, surface))}
    assert present == graphs


def test_tunnel_or_layer_without_a_level_stays_surface_only():
    tunnel = _road(1, [(0.0, 0.0), (50.0, 0.0)], layer=-1, is_tunnel=True)
    surface, routes = _world([tunnel])
    assert (0, 0) in _graph_points(surface)
    assert routes.graphs == {}  # no level graph at all


def test_identical_geometry_on_two_levels_does_not_connect():
    surface_road = _road(1, [(0.0, 0.0), (100.0, 0.0)])
    garage_road = _road(2, [(0.0, 0.0), (100.0, 0.0)], level="-1")
    surface, routes = _world([surface_road], [garage_road])
    assert routes.edges == {}
    assert routes.plan(surface, (0.0, 0.0), 0, (100.0, 0.0), target_level=-1) is None
    assert routes.plan(surface, (0.0, 0.0), -1, (100.0, 0.0)) is None


# Surface street (0,0)-(100,0); entrance at (100,0); ramp level=0;-1 down to
# (130,0); garage aisle level=-1 on to (200,0).
STREET = _road(10, [(0.0, 0.0), (100.0, 0.0)])
RAMP = _road(11, [(100.0, 0.0), (130.0, 0.0)], level="0;-1", layer=-1, is_tunnel=True)
AISLE = _road(12, [(130.0, 0.0), (200.0, 0.0)], level="-1")
ENTRANCE = _entrance(99, 100.0, 0.0, (10, 11))


def test_resolved_connector_is_the_only_cross_level_edge_and_routes_both_ways():
    surface, routes = _world([STREET, RAMP], [AISLE], [ENTRANCE])
    edges = sorted((e.connector_osm_id, e.from_level, e.to_level) for e in routes.usable_edges(surface))
    assert edges == [(99, -1, 0), (99, 0, -1)]

    down = routes.plan(surface, (0.0, 0.0), 0, (190.0, 0.0), target_level=-1)
    assert [level for level, _ in down.legs] == [0, -1]
    assert [(t.connector_osm_id, t.from_level, t.to_level) for t in down.transitions] == [(99, 0, -1)]
    assert down.legs[0][1][-1] == (100.0, 0.0) and down.legs[1][1][-1] == (190.0, 0.0)
    # The cost is just the two single-level legs - no invented connector cost.
    legs = [run_route_steps(graph_route_steps(routes.graph(level, surface), a, b))
            for level, a, b in ((0, (0.0, 0.0), (100.0, 0.0)), (-1, (100.0, 0.0), (190.0, 0.0)))]
    assert down.length_m == pytest.approx(sum(math.dist(p, q) for leg in legs for p, q in zip(leg, leg[1:])))

    up = routes.plan(surface, (190.0, 0.0), -1, (5.0, 0.0))
    assert [level for level, _ in up.legs] == [-1, 0]
    assert up.transitions[0].to_level == 0


def test_unresolved_or_ambiguous_entrances_give_no_route():
    unresolved = _entrance(98, 100.0, 0.0, (10, 13))  # road 13 isn't loaded
    surface, routes = _world([STREET, RAMP], [AISLE], [unresolved])
    assert routes.edges == {}
    assert routes.plan(surface, (0.0, 0.0), 0, (190.0, 0.0), target_level=-1) is None
    ambiguous_ramp = _road(11, [(100.0, 0.0), (130.0, 0.0)], level="0;-1;-2")
    surface, routes = _world([STREET, ambiguous_ramp], [AISLE], [ENTRANCE])
    assert routes.edges == {}


def test_levels_chain_only_through_real_connectors():
    """0 -> -1 -> -2 needs both entrances; there is no direct 0 -> -2 edge."""
    deep_ramp = _road(13, [(200.0, 0.0), (230.0, 0.0)], level="-1;-2")
    deep_aisle = _road(14, [(230.0, 0.0), (300.0, 0.0)], level="-2")
    lower = _entrance(97, 200.0, 0.0, (12, 13))
    surface, routes = _world([STREET, RAMP], [AISLE, deep_ramp, deep_aisle], [ENTRANCE, lower])
    route = routes.plan(surface, (0.0, 0.0), 0, (290.0, 0.0), target_level=-2)
    assert [level for level, _ in route.legs] == [0, -1, -2]
    assert [t.connector_osm_id for t in route.transitions] == [99, 97]
    _, routes_without_lower = _world([STREET, RAMP], [AISLE, deep_ramp, deep_aisle], [ENTRANCE])
    assert routes_without_lower.plan(surface, (0.0, 0.0), 0, (290.0, 0.0), target_level=-2) is None


def test_surface_routing_is_unchanged():
    surface, routes = _world([STREET, RAMP], [AISLE], [ENTRANCE])
    direct = run_route_steps(graph_route_steps(surface, (0.0, 0.0), (90.0, 0.0)))
    planned = routes.plan(surface, (0.0, 0.0), 0, (90.0, 0.0))
    assert planned.legs == [(0, direct)] and planned.transitions == []
