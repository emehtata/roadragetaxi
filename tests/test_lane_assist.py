"""Tests for automated lane keeping assistance."""
import math
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car, SpatialWayGrid, update_car_physics
from theroadragetrip.traffic import NPCCar


def test_lane_assist_activates_and_tracks_right_lane_on_two_way_road():
    # Straight two-way road going East along y = 0, half_width = 4.0m
    # Right lane center for heading East (right = negative y in EPSG:3067):
    # desired offset = 2.0m -> y = -2.0m
    way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        oneway=0,
    )
    grid = SpatialWayGrid([way])

    # Car placed at centerline y = 0.0, moving east with small heading perturbation
    car = Car(x=10.0, y=0.0, heading=0.0, speed=15.0, lane_assist_enabled=True)
    car.time_since_last_steer = 0.5  # Driver idle

    # Update physics without manual steer
    for _ in range(60):
        update_car_physics(
            car,
            throttle=1.0,
            brake=0.0,
            steer_left=0.0,
            steer_right=0.0,
            dt=0.05,
            ways=[way],
            spatial_grid=grid,
        )

    # Lane assist should have activated
    assert car.lane_assist_active is True
    # Car should have steered toward the right lane (y < -0.5)
    assert car.y < -0.5
    # Car stays within road boundary (half_width = 4.0m)
    assert abs(car.y) <= 4.0


def test_lane_assist_does_not_return_into_adjacent_vehicle():
    way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        oneway=0,
    )
    grid = SpatialWayGrid([way])
    car = Car(x=10.0, y=0.0, heading=0.0, speed=15.0, lane_assist_enabled=True)
    car.time_since_last_steer = 0.5
    adjacent_vehicle = NPCCar(
        x=10.0,
        y=-2.0,
        heading=0.0,
        speed=10.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=10.0,
        color=(100, 100, 100),
    )

    for _ in range(60):
        adjacent_vehicle.x = car.x
        update_car_physics(
            car,
            throttle=1.0,
            brake=0.0,
            steer_left=0.0,
            steer_right=0.0,
            dt=0.05,
            ways=[way],
            spatial_grid=grid,
            nearby_vehicles=[adjacent_vehicle],
        )

    assert car.lane_assist_active is True
    assert car.y > -0.5


def test_lane_assist_disabled_by_default():
    way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        oneway=0,
    )
    grid = SpatialWayGrid([way])

    # Car default has lane_assist_enabled=False
    car = Car(x=10.0, y=0.0, heading=0.1, speed=15.0)
    assert car.lane_assist_enabled is False
    car.time_since_last_steer = 1.0

    update_car_physics(
        car,
        throttle=1.0,
        brake=0.0,
        steer_left=0.0,
        steer_right=0.0,
        dt=0.05,
        ways=[way],
        spatial_grid=grid,
    )

    assert car.lane_assist_active is False


def test_lane_assist_tracks_right_lane_on_multi_lane_one_way():
    # 2-lane one-way road going East (half_width = 5.0m, lanes = 2)
    # Right lane center should be at y = -2.5m
    way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="primary",
        half_width_m=5.0,
        oneway=1,
        lanes=2,
    )
    grid = SpatialWayGrid([way])

    # Car placed at centerline y = 0.0, moving east
    car = Car(x=10.0, y=0.0, heading=0.0, speed=15.0, lane_assist_enabled=True)
    car.time_since_last_steer = 0.5

    for _ in range(60):
        update_car_physics(
            car,
            throttle=1.0,
            brake=0.0,
            steer_left=0.0,
            steer_right=0.0,
            dt=0.05,
            ways=[way],
            spatial_grid=grid,
        )

    assert car.lane_assist_active is True
    # Steers into the right-hand lane (y < -0.5)
    assert car.y < -0.5
    assert abs(car.y) <= 5.0


def test_lane_assist_tracks_center_on_single_lane_one_way_road():
    # Narrow single-lane one-way road going East (half_width = 2.5m, lanes = 1)
    way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="residential",
        half_width_m=2.5,
        oneway=1,
        lanes=1,
    )
    grid = SpatialWayGrid([way])

    # Car placed slightly off-center (y = 0.8)
    car = Car(x=10.0, y=0.8, heading=0.0, speed=15.0, lane_assist_enabled=True)
    car.time_since_last_steer = 0.5

    for _ in range(60):
        update_car_physics(
            car,
            throttle=1.0,
            brake=0.0,
            steer_left=0.0,
            steer_right=0.0,
            dt=0.05,
            ways=[way],
            spatial_grid=grid,
        )

    assert car.lane_assist_active is True
    # On narrow single-lane 1-way road, it centers at y = 0.0
    assert abs(car.y) < 0.3


def test_manual_steer_overrides_lane_assist():
    way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        oneway=0,
    )
    grid = SpatialWayGrid([way])

    car = Car(x=10.0, y=0.0, heading=0.0, speed=15.0)
    car.time_since_last_steer = 2.0
    car.lane_assist_active = True

    # User starts turning left
    update_car_physics(
        car,
        throttle=1.0,
        brake=0.0,
        steer_left=1.0,
        steer_right=0.0,
        dt=0.05,
        ways=[way],
        spatial_grid=grid,
    )

    # Lane assist must disengage immediately
    assert car.lane_assist_active is False
    assert car.time_since_last_steer == 0.0
    assert car.heading > 0.0

