"""Navigation across car ferries (docs/ferries.md): the player's local route
search and the intercity backbone; NPC trips keep off them."""
from io import BytesIO

from theroadragetrip.intercity import IntercityGraph, build_xml
from theroadragetrip.osm.models import Way
from theroadragetrip.traffic_world import TrafficWorld, run_route_steps


def test_navigation_crosses_on_the_ferry_npc_trips_do_not():
    mainland = Way(points_m=[(-600.0, 0.0), (-10.0, 0.0)], highway="secondary", half_width_m=3.5)
    island = Way(points_m=[(510.0, 0.0), (1100.0, 0.0)], highway="secondary", half_width_m=3.5)
    world = TrafficWorld([mainland, island])
    world.set_ferry_routes([[(0.0, 0.0), (500.0, 0.0)]])
    route = run_route_steps(world.plan_route_steps((-500.0, 0.0), (1000.0, 0.0), on_road=True, ferries=True))
    assert route is not None and route[0] == (-500.0, 0.0) and route[-1] == (1000.0, 0.0)
    assert any(a[0] <= 0.0 and b[0] >= 500.0 for a, b in zip(route, route[1:]))  # the crossing
    landings = [i for i, node in enumerate(world._route_nodes) if node[:2] in ((-10.0, 0.0), (510.0, 0.0))]
    assert len(landings) == 2
    assert all(v not in landings for v, _ in world._route_edges[landings[0]])  # NPC trips and spawning never see it
    assert world._route_component_parent[landings[0]] != world._route_component_parent[landings[1]]


def test_intercity_routes_cross_on_backbone_ferries(tmp_path):
    xml = ('<osm version="0.6"><node id="1" lon="0" lat="0"/><node id="2" lon="1000" lat="0"/>'
           '<node id="3" lon="1450" lat="0"/><node id="4" lon="2450" lat="0"/>'
           '<way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="secondary"/></way>'
           '<way id="11"><nd ref="2"/><nd ref="3"/><tag k="route" v="ferry"/><tag k="ferry" v="secondary"/></way>'
           '<way id="12"><nd ref="3"/><nd ref="4"/><tag k="highway" v="secondary"/></way>'
           '<way id="13"><nd ref="4"/><nd ref="1"/><tag k="route" v="ferry"/></way></osm>')  # a passenger boat
    path = tmp_path / "intercity.sqlite"
    build_xml(BytesIO(xml.encode()), path, lambda x, y: (x, y))
    graph = IntercityGraph(path)
    try:
        route = graph.route(1, 4)
        assert route is not None and route.distance_m == 2450.0
        assert route.duration_s >= 450.0 / 4.5 + 60.0  # the crossing and its boarding wait
    finally:
        graph.close()
