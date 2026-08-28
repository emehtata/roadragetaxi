"""Tests for one-way street parsing and driving direction enforcement."""
import math
from theroadragetrip.osm import Way
from theroadragetrip.physics import (
    Car,
    SpatialWayGrid,
    is_violating_oneway,
    update_car_physics,
)


def test_oneway_way_parsing_and_violation():
    # Way going East along y=100 from x=0 to x=100, oneway=1 (forward)
    way = Way(
        points_m=[(0.0, 100.0), (100.0, 100.0)],
        highway="residential",
        half_width_m=4.0,
        is_drivable=True,
        oneway=1,
    )
    grid = SpatialWayGrid([way])

    car = Car(x=50.0, y=100.0, heading=0.0, speed=10.0)

    # Driving East (dx > 0): legal direction -> no violation
    assert not is_violating_oneway(car, 50.0, 100.0, 1.0, 0.0, spatial_grid=grid)

    # Driving West (dx < 0): opposite direction -> violation!
    assert is_violating_oneway(car, 50.0, 100.0, -1.0, 0.0, spatial_grid=grid)


def test_oneway_physics_not_blocking_by_default():
    way = Way(
        points_m=[(0.0, 100.0), (100.0, 100.0)],
        highway="residential",
        half_width_m=4.0,
        is_drivable=True,
        oneway=1,
    )
    grid = SpatialWayGrid([way])

    # Heading West (pi radians), throttle forward
    car = Car(x=50.0, y=100.0, heading=math.pi, speed=5.0)

    # By default, driving wrong direction is not physically blocked (penalty handled by game manager)
    blocked = update_car_physics(
        car=car,
        throttle=1.0,
        brake=0.0,
        steer_left=0.0,
        steer_right=0.0,
        dt=0.1,
        spatial_grid=grid,
        block_offroad=True,
    )

    assert blocked is False
    assert car.x < 50.0  # car allowed to drive west


def test_oneway_penalty_every_5_seconds():
    from theroadragetrip.taxi import TaxiManager

    way = Way(
        points_m=[(0.0, 100.0), (100.0, 100.0)],
        highway="residential",
        half_width_m=4.0,
        name="Test One-Way St",
        is_drivable=True,
        oneway=1,
    )
    grid = SpatialWayGrid([way])
    mgr = TaxiManager(ways=[way])
    mgr.total_score = 500

    # Car driving backwards (West) on Eastbound one-way
    car = Car(x=50.0, y=100.0, heading=math.pi, speed=10.0)

    # 4 seconds driving wrong way -> no penalty yet
    for _ in range(40):
        mgr.check_wrong_way_violation(car, dt=0.1, spatial_grid=grid, penalty=50, interval_s=5.0)
    assert mgr.total_score == 500

    # Pass 5.0 seconds -> penalty triggers (-50 pts)
    for _ in range(11):
        mgr.check_wrong_way_violation(car, dt=0.1, spatial_grid=grid, penalty=50, interval_s=5.0)
    assert mgr.total_score == 450
    assert "Wrong Way" in mgr.notification_msg

