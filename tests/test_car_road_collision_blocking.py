from theroadragetrip.osm import Way
from theroadragetrip.physics import (
    Car,
    SpatialWayGrid,
    is_car_road,
    is_on_road,
    is_point_on_road,
    update_car_physics,
)


def test_is_car_road_filtering():
    primary = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="primary", half_width_m=6.0)
    residential = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.5)
    footway = Way(
        points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=2.0, is_drivable=False
    )
    cycleway = Way(
        points_m=[(0.0, 0.0), (10.0, 0.0)], highway="cycleway", half_width_m=2.0, is_drivable=False
    )
    track = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="track", half_width_m=3.0, is_drivable=False)
    ice_road = Way(
        points_m=[(0.0, 0.0), (10.0, 0.0)], highway="primary", half_width_m=6.0, is_ice_road=True
    )

    assert is_car_road(primary) is True
    assert is_car_road(residential) is True
    assert is_car_road(footway) is False
    assert is_car_road(cycleway) is False
    assert is_car_road(track) is False
    assert is_car_road(ice_road) is False


def test_block_motion_when_exiting_road_boundary():
    # Horizontal primary road along y = 0 from x = 0 to x = 100, half_width = 5.0 meters (so y in [-5, 5])
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=5.0)
    ways = [road]
    grid = SpatialWayGrid(cell_size=100.0)
    grid.rebuild(ways)

    # Place car at (50.0, 4.0), heading north (heading = pi/2, heading towards y > 5 which is offroad)
    import math

    car = Car(x=50.0, y=4.0, heading=math.pi / 2.0, speed=10.0)

    # Attempt to drive north (off-road)
    blocked = update_car_physics(
        car,
        throttle=1.0,
        brake=0.0,
        steer_left=0.0,
        steer_right=0.0,
        dt=0.2,
        ways=ways,
        spatial_grid=grid,
        block_offroad=True,
    )

    assert blocked is True
    assert car.y <= 5.0  # Kept inside the road corridor!
    assert car.speed == 0.0  # Speed stopped upon collision with road boundary


def test_allow_driving_parallel_to_road():
    # Horizontal road along y = 0 from x = 0 to x = 100, half_width = 5.0
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=5.0)
    ways = [road]
    grid = SpatialWayGrid(cell_size=100.0)
    grid.rebuild(ways)

    # Place car at (10.0, 0.0), heading east (heading = 0.0)
    car = Car(x=10.0, y=0.0, heading=0.0, speed=10.0)

    blocked = update_car_physics(
        car,
        throttle=1.0,
        brake=0.0,
        steer_left=0.0,
        steer_right=0.0,
        dt=0.5,
        ways=ways,
        spatial_grid=grid,
        block_offroad=True,
    )

    assert blocked is False
    assert car.x > 10.0  # Car moved forward along the road
    assert abs(car.y) <= 5.0


def test_block_motion_into_footway_or_pedestrian_path():
    # Drivable road and adjoining non-drivable footway
    road = Way(points_m=[(0.0, 0.0), (50.0, 0.0)], highway="residential", half_width_m=4.0)
    footway = Way(
        points_m=[(50.0, 0.0), (100.0, 0.0)],
        highway="footway",
        half_width_m=2.0,
        is_drivable=False,
    )
    ways = [road, footway]
    grid = SpatialWayGrid(cell_size=100.0)
    grid.rebuild(ways)

    # Place car at (50.0, 0.0), heading east towards footway
    car = Car(x=50.0, y=0.0, heading=0.0, speed=10.0)

    blocked = update_car_physics(
        car,
        throttle=1.0,
        brake=0.0,
        steer_left=0.0,
        steer_right=0.0,
        dt=0.6,
        ways=ways,
        spatial_grid=grid,
        block_offroad=True,
    )

    assert blocked is True
    assert car.x <= 54.0  # Blocked from entering the footway corridor!
