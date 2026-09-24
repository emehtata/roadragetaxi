import time

from theroadragetrip.osm import ParkingSpace, Way
from theroadragetrip.traffic_world import TrafficWorld


def test_logical_intersections_survive_construction_and_sync():
    """Regression: TrafficWorld silently dropped logical_intersections -
    never accepted at construction, and sync_map_data's **_kwargs quietly
    swallowed it too - so traffic_mgr.logical_intersections stayed empty
    for the whole game, and the debug HUD's stop-line overlay
    (draw_logical_intersections) never had anything to draw."""
    road = Way([(0.0, 0.0), (100.0, 0.0)], "residential", 4.0)
    world = TrafficWorld([road], logical_intersections=["fake-intersection"])
    assert world.logical_intersections == ["fake-intersection"]

    world.sync_map_data([road], logical_intersections=["updated-intersection"])
    assert world.logical_intersections == ["updated-intersection"]


def test_navigation_route_uses_drivable_roads_only():
    pedestrian_shortcut = Way(
        points_m=[(0.0, 0.0), (0.0, 100.0)],
        highway="footway",
        half_width_m=2.0,
        is_drivable=False,
    )
    road = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)],
        highway="residential",
        half_width_m=4.0,
        is_drivable=True,
    )
    world = TrafficWorld([pedestrian_shortcut, road])

    route = world.plan_route((0.0, 0.0), (0.0, 100.0))

    assert route is not None
    assert (0.0, 100.0, 0) not in world._route_nodes
    assert (100.0, 0.0, 0) in world._route_nodes
    assert (0.0, 100.0) not in route[1:-1]


def test_navigation_route_connects_from_middle_of_long_road_segment():
    road = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)],
        highway="residential",
        half_width_m=4.0,
        is_drivable=True,
    )
    target_road = Way(
        points_m=[(100.0, 100.0), (200.0, 100.0)],
        highway="residential",
        half_width_m=4.0,
        is_drivable=True,
    )
    world = TrafficWorld([road, target_road])

    route = world.plan_route((50.0, 0.0), (200.0, 100.0))

    assert route is not None
    assert route[-1] == (200.0, 100.0)


def test_plan_route_honors_an_expired_deadline():
    world = TrafficWorld(_large_city_block_grid(block_count=20, step_m=40.0))

    assert world.plan_route((0.0, 0.0), (760.0, 760.0), deadline=0.0) is None


def test_sync_map_data_adds_streamed_road_to_route_graph():
    streamed_road = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=4.0,
        is_drivable=True,
    )
    world = TrafficWorld([])

    world.sync_map_data([streamed_road])

    assert (0.0, 0.0, 0) in world._route_nodes
    assert world.plan_route((0.0, 0.0), (100.0, 0.0)) is not None


def test_sync_map_data_indexes_parking_spaces_for_rendering():
    space = ParkingSpace(
        [(10.0, 10.0), (20.0, 10.0), (20.0, 15.0), (10.0, 15.0)],
        bbox=(10.0, 10.0, 20.0, 15.0),
    )
    world = TrafficWorld([])

    world.sync_map_data([], parking_spaces=[space])

    assert space in world._parking_grid[(0, 0)]


def _large_city_block_grid(block_count: int, step_m: float):
    ways = []
    for row in range(block_count):
        for i in range(block_count - 1):
            ways.append(Way(points_m=[(i * step_m, row * step_m), ((i + 1) * step_m, row * step_m)], highway="residential", half_width_m=4.5))
    for col in range(block_count):
        for i in range(block_count - 1):
            ways.append(Way(points_m=[(col * step_m, i * step_m), (col * step_m, (i + 1) * step_m)], highway="residential", half_width_m=4.5))
    return ways


def test_plan_route_stays_fast_on_a_large_graph():
    """Regression (client-server-016.md section 9/10): plan_route used to
    sort *every* node in the whole route graph, twice, on every call,
    regardless of how close start/target actually were - a real cost on
    a city-sized graph (the NPC population tick's own comments call this
    "well over a second against real dense OSM data (measured)"). Nearest
    candidates now come from a grid index instead of a full sort. This
    doesn't assert an exact time bound (too flaky across machines) - it
    asserts route correctness on a large graph and that a nearby-to-
    nearby route call is dramatically cheaper than the graph is big,
    which the old O(all nodes) sort could never be."""
    ways = _large_city_block_grid(block_count=150, step_m=40.0)
    world = TrafficWorld(ways)
    assert len(world._route_nodes) > 20000

    start = time.perf_counter()
    route = world.plan_route((0.0, 0.0), (120.0, 80.0))
    elapsed = time.perf_counter() - start

    assert route is not None
    assert route[0] == (0.0, 0.0)
    assert route[-1] == (120.0, 80.0)
    # A local/nearby route's cost should come from the A* search over a
    # small candidate pool, not from sorting the whole 20000+-node graph
    # twice - measured ~2.7ms with the grid-index lookup vs. ~13.9ms for
    # the old full-sort approach at this same graph size. 10ms leaves
    # headroom for a slow CI box while still failing against the old
    # approach.
    assert elapsed < 0.01, f"plan_route took {elapsed * 1000:.1f}ms for a nearby route on a large graph"


def test_nearest_node_indices_falls_back_when_point_is_off_the_mapped_area():
    """A target far outside any mapped road (e.g. a genuinely unreachable
    destination) can't be found by expanding outward from its own grid
    cell - _nearest_node_indices must fall back to considering every
    allowed node rather than silently returning nothing, or plan_route's
    A* search gets an empty target set and crashes instead of just
    failing to find a route."""
    ways = _large_city_block_grid(block_count=10, step_m=40.0)
    world = TrafficWorld(ways)
    allowed = set(range(len(world._route_nodes)))

    found = world._nearest_node_indices((1_000_000.0, 1_000_000.0), 8, allowed)

    assert len(found) == 8


def _v13_reference_graph(ways):
    """The pre-V13 synchronous _build_route_graph + weak components, kept
    verbatim as the exactness reference for the incremental build."""
    import math as _math
    from theroadragetrip.physics import is_car_road

    nodes, edges, buckets = [], {}, {}

    def node_id(point, layer):
        key = (round(point[0] / 3.0), round(point[1] / 3.0), layer)
        for candidate in buckets.get(key, ()):
            if _math.hypot(nodes[candidate][0] - point[0], nodes[candidate][1] - point[1]) <= 3.0:
                return candidate
        index = len(nodes)
        nodes.append((point[0], point[1], layer))
        edges[index] = []
        buckets.setdefault(key, []).append(index)
        return index

    for way in ways:
        if not is_car_road(way) or len(way.points_m) < 2:
            continue
        layer = getattr(way, "layer", 0)
        point_ids = [node_id(point, layer) for point in way.points_m]
        oneway = getattr(way, "oneway", 0)
        for first, second in zip(point_ids, point_ids[1:]):
            distance = _math.hypot(nodes[second][0] - nodes[first][0], nodes[second][1] - nodes[first][1])
            if oneway >= 0:
                edges[first].append((second, distance))
            if oneway <= 0:
                edges[second].append((first, distance))
    grid = {}
    for index, node in enumerate(nodes):
        grid.setdefault((_math.floor(node[0] / 200.0), _math.floor(node[1] / 200.0)), []).append(index)
    parent = list(range(len(nodes)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for first, neighbors in edges.items():
        for second, _ in neighbors:
            a, b = root(first), root(second)
            if a != b:
                parent[max(a, b)] = min(a, b)
    return nodes, edges, grid, [root(index) for index in range(len(nodes))]


def _v13_random_world(seed, count=150):
    import random as _random

    rnd = _random.Random(seed)
    ways = []
    for _ in range(count):
        points = [(round(rnd.uniform(0, 900) / 10) * 10.0 + rnd.uniform(-2, 2), round(rnd.uniform(0, 900) / 10) * 10.0)
                  for _ in range(rnd.randint(2, 5))]
        way = Way(points_m=points, highway=rnd.choice(["residential", "primary", "service", "footway", "tertiary"]),
                  half_width_m=4.0)
        way.oneway = rnd.choice([0, 0, 1, -1])
        way.layer = rnd.choice([0, 0, 0, 1])
        ways.append(way)
    return ways


def _v13_state(world):
    from theroadragetrip.traffic_world import _component_root

    return (world._route_nodes, world._route_edges, world._route_node_grid,
            [_component_root(world._route_component_parent, i) for i in range(len(world._route_nodes))])


def test_v13_incremental_route_graph_matches_the_old_full_rebuild_exactly():
    for seed in range(8):
        ways = _v13_random_world(seed)
        expected = _v13_reference_graph(ways)
        synchronous = TrafficWorld(ways)
        assert list(_v13_state(synchronous)) == list(expected)

        incremental = TrafficWorld([])
        incremental.start_map_sync(ways)
        steps = 0
        while not incremental.advance_map_sync(0.0):
            steps += 1
            assert incremental._route_nodes == []  # old (empty) graph stays live until commit
        assert steps > 5
        assert list(_v13_state(incremental)) == list(expected)
        for start, target in ((w.points_m[0], v.points_m[-1]) for w, v in zip(ways[:20], ways[20:40])):
            assert incremental.plan_route(start, target) == synchronous.plan_route(start, target)


def test_v13_components_match_a_brute_force_flood_fill():
    world = TrafficWorld(_v13_random_world(3, count=120))
    nodes, edges = world._route_nodes, world._route_edges
    undirected = {i: set() for i in range(len(nodes))}
    for a, neighbors in edges.items():
        for b, _ in neighbors:
            undirected[a].add(b)
            undirected[b].add(a)
    label, labels = 0, {}
    for start in range(len(nodes)):
        if start in labels:
            continue
        stack = [start]
        labels[start] = label
        while stack:
            for other in undirected[stack.pop()]:
                if other not in labels:
                    labels[other] = label
                    stack.append(other)
        label += 1
    roots = _v13_state(world)[3]
    for a in range(len(nodes)):
        for b in range(0, len(nodes), 3):
            assert (roots[a] == roots[b]) == (labels[a] == labels[b])


def test_v13_budgeted_sync_snapshots_input_bumps_revision_once_and_unloads_cleanly():
    ways = _v13_random_world(5)
    world = TrafficWorld(ways[:40])
    revision = world.route_graph_revision
    live = list(ways)
    world.start_map_sync(live)
    live.append(Way(points_m=[(5000.0, 5000.0), (5100.0, 5000.0)], highway="residential", half_width_m=4.0))
    del live[:30]  # tile removal and addition while the build runs
    while not world.advance_map_sync(0.0):
        assert world.route_graph_revision == revision  # old graph still authoritative
    assert world.route_graph_revision == revision + 1
    assert list(_v13_state(world)) == list(_v13_reference_graph(ways))  # exactly the snapshot, no mix

    # Next sync (unloaded tiles): no stale nodes, edges, grid cells or components.
    world.sync_map_data(ways[:10])
    assert world.route_graph_revision == revision + 2
    assert list(_v13_state(world)) == list(_v13_reference_graph(ways[:10]))
