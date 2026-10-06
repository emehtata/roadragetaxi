"""godot-final-04: the server-owned navigation route (navigation_route.py),
on a real TrafficWorld route graph."""

import time
from types import SimpleNamespace

from theroadragetrip.geo import dist_point_to_segment
from theroadragetrip.navigation_route import ROUTE_TOLERANCE_M, NavigationRoute, simplify_polyline
from theroadragetrip.osm import Way
from theroadragetrip.taxi import TaxiTarget
from theroadragetrip.traffic_world import TrafficWorld


def _grid(blocks=12, step=40.0):
    ways = []
    for row in range(blocks):
        for i in range(blocks - 1):
            ways.append(Way(points_m=[(i * step, row * step), ((i + 1) * step, row * step)], highway="residential", half_width_m=4.5))
            ways.append(Way(points_m=[(row * step, i * step), (row * step, (i + 1) * step)], highway="residential", half_width_m=4.5))
    return ways


def _world(traffic=None, target=None):
    taxi = SimpleNamespace(target=target)
    taxi.get_current_target = lambda: taxi.target
    return SimpleNamespace(traffic_mgr=traffic or TrafficWorld(_grid()), taxi_mgr=taxi, level_routes=None)


def _finish(nav, world, car, ticks=10_000):
    for _ in range(ticks):
        nav.update(world, car)
        if nav._job is None:
            return
    raise AssertionError("route never finished")


def test_no_target_no_route_and_no_search():
    world, car, nav = _world(), SimpleNamespace(x=0.0, y=0.0, map_level=0), NavigationRoute()
    nav.update(world, car)
    assert nav.points == [] and nav._job is None and nav.plans_started == 0


def test_a_pickup_gets_a_route_from_the_taxi_to_the_target_once():
    pickup = TaxiTarget(x=400.0, y=280.0, address="Kirkkokatu 4")
    world, car, nav = _world(target=pickup), SimpleNamespace(x=0.0, y=0.0, map_level=0), NavigationRoute()
    _finish(nav, world, car)
    assert nav.points[0] == [0.0, 0.0] and nav.points[-1] == [400.0, 280.0]
    for _ in range(30):  # the same target, level and graph: no new search
        nav.update(world, car)
    assert nav.plans_started == 1 and nav._job is None


def test_the_drop_off_replaces_the_pickup_route_and_its_job():
    pickup = TaxiTarget(x=400.0, y=280.0, address="Kirkkokatu 4")
    world, car = _world(target=pickup), SimpleNamespace(x=0.0, y=0.0, map_level=0)
    nav = NavigationRoute(budget_s=0.0)  # one search step per tick: the pickup job is still running
    nav.update(world, car)
    assert nav._job is not None
    world.taxi_mgr.target = TaxiTarget(x=40.0, y=440.0, address="Rautatientori")
    nav.update(world, car)  # the stale pickup job is dropped, never published
    _finish(nav, world, car)
    assert nav.points[-1] == [40.0, 440.0] and nav.plans_started == 2


def test_the_route_is_replanned_only_beyond_35_m_off_it():
    target = TaxiTarget(x=440.0, y=0.0, address="Isokatu 1")
    world, car, nav = _world(target=target), SimpleNamespace(x=0.0, y=0.0, map_level=0), NavigationRoute()
    _finish(nav, world, car)
    car.y = 35.0  # exactly 35 m off the straight route along y = 0
    nav.update(world, car)
    assert nav.plans_started == 1
    car.y = 36.0
    nav.update(world, car)
    assert nav.plans_started == 2


def test_a_new_route_graph_replans_and_keeps_the_old_line_until_then():
    target = TaxiTarget(x=440.0, y=0.0, address="Isokatu 1")
    world, car, nav = _world(target=target), SimpleNamespace(x=0.0, y=0.0, map_level=0), NavigationRoute(budget_s=0.0)
    _finish(nav, world, car)
    old = nav.points
    world.traffic_mgr.route_graph_revision = getattr(world.traffic_mgr, "route_graph_revision", 0) + 1
    nav.update(world, car)
    assert nav.plans_started == 2 and nav.points == old  # still shown while the new search runs


def test_a_level_change_plans_that_levels_leg():
    calls = []
    leg = [(5.0, 5.0), (20.0, 5.0), (20.0, 30.0)]
    level_routes = SimpleNamespace(plan=lambda graph, start, level, goal: calls.append((start, level, goal)) or SimpleNamespace(legs=[(level, leg)]))
    world = _world(target=TaxiTarget(x=440.0, y=0.0, address="Isokatu 1"))
    world.level_routes = level_routes
    car, nav = SimpleNamespace(x=5.0, y=5.0, map_level=-1), NavigationRoute()
    nav.update(world, car)
    assert calls == [((5.0, 5.0), -1, (440.0, 0.0))] and nav.points == [[5.0, 5.0], [20.0, 5.0], [20.0, 30.0]]
    car.map_level = 0  # back on the surface: a surface route
    _finish(nav, world, car)
    assert nav.points[-1] == [440.0, 0.0] and len(calls) == 1


def test_an_unreachable_target_gives_no_line():
    island = Way(points_m=[(5000.0, 5000.0), (5040.0, 5000.0)], highway="residential", half_width_m=4.5)  # no road to it
    traffic = TrafficWorld(_grid() + [island])
    world = _world(traffic, TaxiTarget(x=5040.0, y=5000.0, address="Saari"))
    car, nav = SimpleNamespace(x=0.0, y=0.0, map_level=0), NavigationRoute()
    _finish(nav, world, car)
    assert nav.points == []  # no line, no crash
    nav.update(world, car)
    assert nav.plans_started == 1  # no retry every tick


def test_a_long_search_spans_ticks_within_its_budget():
    traffic = TrafficWorld(_grid(blocks=60))
    world = _world(traffic, TaxiTarget(x=59 * 40.0, y=59 * 40.0, address="Kaukana"))
    car, nav = SimpleNamespace(x=0.0, y=0.0, map_level=0), NavigationRoute(budget_s=0.001)
    ticks = 0
    while True:
        nav.update(world, car)
        ticks += 1
        if nav._job is None:
            break
    assert ticks > 1 and nav.points[-1] == [2360.0, 2360.0]
    assert nav.worst_slice_s < 0.001 + 0.004  # the budget plus one search step's overshoot


def test_simplify_keeps_the_shape_and_drops_the_straight_points():
    line = [(x * 2.0, 0.0) for x in range(201)] + [(400.0, y * 2.0) for y in range(1, 201)]  # 400 m, a corner, 400 m
    line[50] = (100.0, 0.3)  # a wobble inside the tolerance
    simple = simplify_polyline(line)
    assert simple[0] == line[0] and simple[-1] == line[-1] and (400.0, 0.0) in simple
    assert len(simple) <= 4 < len(line) // 50
    for p in line:  # every dropped point stays within the tolerance of the compact line
        assert min(dist_point_to_segment(p[0], p[1], *a, *b) for a, b in zip(simple, simple[1:])) <= ROUTE_TOLERANCE_M + 1e-9
