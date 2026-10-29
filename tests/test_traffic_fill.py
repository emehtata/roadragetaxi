"""Passing traffic without a route search: npc.walk_road_graph."""
import random

from theroadragetrip.npc import walk_road_graph


def _graph():
    # A straight east-west road 0..4 with a side street at node 2 (to 5), one way 3 -> 4 only.
    nodes = [(0, 0, 0), (100, 0, 0), (200, 0, 0), (300, 0, 0), (400, 0, 0), (200, 100, 0)]
    edges = {0: [(1, 100)], 1: [(0, 100), (2, 100)], 2: [(1, 100), (3, 100), (5, 100)],
             3: [(2, 100), (4, 100)], 4: [], 5: [(2, 100)]}
    return nodes, edges


def test_the_walk_follows_the_road_forward_and_never_turns_back():
    nodes, edges = _graph()
    points = walk_road_graph(nodes, edges, 0, 1000.0, rng=random.Random(1))
    assert points[0] == (0, 0)
    assert all(a != c for a, b, c in zip(points, points[1:], points[2:]))  # no U-turn on an edge
    assert points[-1] in ((400, 0), (200, 100))  # a dead end ends it


def test_the_walk_mostly_keeps_straight_on():
    nodes, edges = _graph()
    ends = [walk_road_graph(nodes, edges, 0, 1000.0, rng=random.Random(seed))[-1] for seed in range(50)]
    assert ends.count((400, 0)) > ends.count((200, 100)) > 0


def test_the_walk_stops_once_long_enough():
    nodes, edges = _graph()
    assert walk_road_graph(nodes, edges, 0, 150.0, rng=random.Random(0)) == [(0, 0), (100, 0), (200, 0)]


def test_one_way_edges_are_honoured():
    nodes, edges = _graph()
    assert walk_road_graph(nodes, edges, 4, 1000.0) == [(400, 0)]  # 4 -> 3 is against the one-way


def test_the_walk_sets_off_the_way_it_is_pointed():
    nodes, edges = _graph()
    assert walk_road_graph(nodes, edges, 2, 100.0, rng=random.Random(0), heading=3.14159) == [(200, 0), (100, 0)]


def test_peak_traffic_comes_from_the_roads_around_the_taxi_by_class():
    from types import SimpleNamespace
    from theroadragetrip.npc import peak_cars_on_roads
    from theroadragetrip.population import CLASS_DENSITIES

    secondary = SimpleNamespace(highway="secondary", points_m=[(-100.0, 0.0), (100.0, 0.0)], map_level=0, ref=None)
    yard = SimpleNamespace(highway="service", points_m=[(0.0, -50.0), (0.0, 50.0)], map_level=0, ref=None)
    far = SimpleNamespace(highway="residential", points_m=[(900.0, 0.0), (1000.0, 0.0)], map_level=0, ref=None)
    grid = SimpleNamespace(ways_in_rect=lambda *_: [secondary, yard, far])
    urban, rural = peak_cars_on_roads(grid, 0.0, 0.0)
    assert urban == pytest_approx(CLASS_DENSITIES["urban"]["secondary"] * 0.2)  # LAM median; no yards, nothing far
    assert rural == pytest_approx(CLASS_DENSITIES["rural"]["secondary"] * 0.2)


def pytest_approx(value):
    import pytest
    return pytest.approx(value, rel=1e-6)
