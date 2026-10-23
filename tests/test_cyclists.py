"""Cyclists as NPC traffic (rrt-019-cyclists; docs/finnish-npc-traffic-law.md)."""
import math

from theroadragetrip.cycling import cycle_cost_factor, is_cyclable_way, route_legs
from theroadragetrip.osm import Way
from theroadragetrip.traffic_world import TrafficWorld, run_route_steps


def _way(points, highway, **kw):
    return Way(points_m=points, highway=highway, half_width_m=kw.pop("half_width_m", 3.0 if highway != "cycleway" else 1.5), **kw)


def _route(world, start, target):
    points = run_route_steps(world.plan_cycle_route_steps(start, target))
    return None if points is None else route_legs(world.cycle_graph, points)


def test_cyclable_ways_follow_access_tags():
    assert is_cyclable_way(_way([(0, 0), (10, 0)], "cycleway"))
    assert is_cyclable_way(_way([(0, 0), (10, 0)], "residential"))
    assert is_cyclable_way(_way([(0, 0), (10, 0)], "footway", bicycle="designated"))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "footway"))  # no bicycle tag: pedestrians only
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "motorway"))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "trunk", motorroad=True))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "primary", bicycle="no"))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "primary", bicycle="use_sidepath"))
    assert not is_cyclable_way(_way([(0, 0), (10, 0)], "steps", bicycle="yes"))
    assert cycle_cost_factor(_way([(0, 0), (1, 0)], "cycleway")) < cycle_cost_factor(_way([(0, 0), (1, 0)], "primary"))


def test_cycle_route_honours_oneway_and_contraflow():
    oneway = _way([(0, 0), (100, 0)], "residential", oneway=1)
    world = TrafficWorld([oneway])
    assert _route(world, (0, 0), (100, 0)) is not None
    assert _route(world, (100, 0), (0, 0)) is None  # against a one-way street
    contraflow = _way([(0, 0), (100, 0)], "residential", oneway=1, oneway_bicycle=0)
    world = TrafficWorld([contraflow])
    assert _route(world, (100, 0), (0, 0)) is not None  # oneway:bicycle=no


def test_cycle_route_prefers_cycle_path_and_never_cuts_across_open_ground():
    # A busy road straight across, a cycle path detour of 1.4x its length.
    road = _way([(0, 0), (200, 0)], "primary")
    path = _way([(0, 0), (0, 40), (100, 60), (200, 40), (200, 0)], "cycleway")
    world = TrafficWorld([road, path])
    points, ways = _route(world, (0, 0), (200, 0))
    assert all(way is path for way in ways)
    # A pedestrian-only footway is no link: the far cycleway is unreachable.
    far = _way([(300, 0), (400, 0)], "cycleway")
    footway = _way([(200, 0), (300, 0)], "footway")
    world = TrafficWorld([road, footway, far])
    assert _route(world, (0, 0), (400, 0)) is None
