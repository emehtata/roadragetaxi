"""Tests for underground road filtering and bridge layer separation."""
from theroadragetrip.osm import Way, build_ways
from theroadragetrip.physics import (
    Car,
    SpatialWayGrid,
    is_point_on_road,
    update_car_physics,
)


def test_underground_parking_aisles_filtered_out():
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
    assert len(ways) == 1
    assert ways[0].name == "Normal Street"


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
