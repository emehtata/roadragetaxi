"""Tests for underground road filtering and bridge layer separation."""
from theroadragetrip.osm import Way, build_ways
from theroadragetrip.physics import (
    Car,
    SpatialWayGrid,
    is_car_colliding_with_bridge_edge,
    is_point_on_road,
    pull_car_inside_bridge_edge,
    update_car_physics,
)


def test_underground_parking_aisles_remain_drivable():
    elements = [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 65.001, "lon": 25.0},
        {"type": "node", "id": 3, "lat": 65.0, "lon": 25.001},
        {"type": "node", "id": 4, "lat": 65.001, "lon": 25.001},
        # Normal surface road
        {
            "type": "way",
            "id": 101,
            "nodes": [1, 2],
            "tags": {"highway": "residential", "name": "Normal Street"},
        },
        # Underground parking aisle
        {
            "type": "way",
            "id": 102,
            "nodes": [3, 4],
            "tags": {
                "highway": "service",
                "service": "parking_aisle",
                "location": "underground",
                "level": "-1",
            },
        },
    ]

    ways, _, _, _, _, _ = build_ways(elements)
    assert len(ways) == 2
    assert {way.name for way in ways} == {"Normal Street", None}
    parking_aisles = [way for way in ways if way.service == "parking_aisle"]
    assert len(parking_aisles) == 1


def test_bridge_cross_layer_collision_isolation():
    # Ground road at layer 0 (East-West)
    ground_road = Way(
        points_m=[(0.0, 100.0), (100.0, 100.0)],
        highway="primary",
        half_width_m=4.0,
        layer=0,
    )
    # Overpass bridge at layer 1 (North-South crossing at (50, 100))
    bridge_road = Way(
        points_m=[(50.0, 50.0), (50.0, 150.0)],
        highway="primary",
        half_width_m=4.0,
        layer=1,
        is_bridge=True,
    )

    grid = SpatialWayGrid([ground_road, bridge_road])

    # Car is on bridge (layer 1) at (50.0, 100.0) heading North (along bridge)
    car_on_bridge = Car(x=50.0, y=100.0, heading=1.570796, speed=10.0, layer=1)

    # Bridge car is on road in layer 1
    assert is_point_on_road(car_on_bridge.x, car_on_bridge.y, spatial_grid=grid, layer=car_on_bridge.layer)

    # Attempt to drive East (off the bridge side onto the crossing ground road below)
    # Since ground road is layer 0 and car is layer 1, moving East (dx=10, dy=0) is off-road for layer 1
    blocked = update_car_physics(
        car=car_on_bridge,
        throttle=0.0,
        brake=0.0,
        steer_left=0.0,
        steer_right=0.0,
        dt=0.1,
        spatial_grid=grid,
        block_offroad=True,
    )

    # Heading is North, moving forward along bridge:
    assert car_on_bridge.layer == 1
    # Check that a point to the East (70, 100) is on road for layer 0 but NOT for layer 1
    assert is_point_on_road(70.0, 100.0, spatial_grid=grid, layer=0)
    assert not is_point_on_road(70.0, 100.0, spatial_grid=grid, layer=1)


def test_car_hits_bridge_guardrail_with_a_corner():
    bridge = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        is_bridge=True,
        layer=1,
    )
    centered_car = Car(x=50.0, y=0.0, heading=0.0, speed=0.0, layer=1)
    edge_car = Car(x=50.0, y=3.2, heading=0.0, speed=0.0, layer=1)
    bridge_end_car = Car(x=102.0, y=0.0, heading=0.0, speed=0.0, layer=1)

    assert not is_car_colliding_with_bridge_edge(centered_car, bridge)
    assert is_car_colliding_with_bridge_edge(edge_car, bridge)
    assert not is_car_colliding_with_bridge_edge(bridge_end_car, bridge)


def test_bridge_guardrail_recovery_moves_car_inside_road():
    bridge = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=5.0,
        is_bridge=True,
    )
    car = Car(x=50.0, y=4.8, heading=0.0, speed=0.0)

    assert is_car_colliding_with_bridge_edge(car, bridge)
    pull_car_inside_bridge_edge(car, bridge)

    assert abs(car.y) <= bridge.half_width_m - car.width_m * 0.5 - 0.35
    assert not is_car_colliding_with_bridge_edge(car, bridge)


def test_bridge_guardrail_ignores_segment_when_car_is_not_on_it():
    bridge = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        is_bridge=True,
        layer=1,
    )
    crossing_car = Car(x=50.0, y=6.0, heading=0.0, speed=0.0, layer=1)

    assert not is_car_colliding_with_bridge_edge(crossing_car, bridge)


def test_no_false_guardrail_crash_on_the_seam_between_divided_bridge_lanes():
    """Regression: a divided highway bridge is often split into one Way per
    direction. draw_ways already unions overlapping bridge lanes so no
    guardrail is drawn between them (see bridge_polygons in
    render/roads.py) - but the collision check used to know nothing about
    the neighboring lane, so a car near the shared inner seam (well inside
    the combined bridge deck, nowhere near a real rail) registered a crash."""
    northbound = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        is_bridge=True,
        layer=1,
    )
    southbound = Way(
        points_m=[(0.0, 8.0), (100.0, 8.0)],
        highway="primary",
        half_width_m=4.0,
        is_bridge=True,
        layer=1,
    )
    # y=3.9 is inside northbound's own half-width (4.0) but past its
    # edge_distance (3.8) - and inside southbound's half-width too, since
    # the lanes touch at y=4.0.
    seam_car = Car(x=50.0, y=3.9, heading=0.0, speed=0.0, layer=1)

    assert not is_car_colliding_with_bridge_edge(seam_car, northbound, ways=[northbound, southbound])
    # Without the neighboring lane, the same edge is still a real crash.
    assert is_car_colliding_with_bridge_edge(seam_car, northbound)
    # A car past the outer edge of the combined deck still crashes.
    outer_car = Car(x=50.0, y=-3.9, heading=0.0, speed=0.0, layer=1)
    assert is_car_colliding_with_bridge_edge(outer_car, northbound, ways=[northbound, southbound])
