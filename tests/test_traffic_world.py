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