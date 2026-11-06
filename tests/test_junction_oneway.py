"""Tests for one-way intersection and junction handling."""
from theroadragetrip.osm import Way
from theroadragetrip.physics import (
    Car,
    SpatialWayGrid,
    is_violating_oneway,
    update_car_physics,
)


def test_oneway_junction_with_twoway_allows_turning():
    # Through Street is a two-way street at (50, 100) running East-West
    main_street = Way(
        points_m=[(0.0, 100.0), (100.0, 100.0)],
        highway="primary",
        half_width_m=5.0,
        name="Through Street",
        oneway=0,
    )
    # One-way bridge ramp ending at Through Street running North -> South (y decreases from 150 to 100)
    bridge_ramp = Way(
        points_m=[(50.0, 150.0), (50.0, 100.0)],
        highway="primary",
        half_width_m=5.0,
        name="Test Bridge",
        oneway=1,  # North to South
    )

    grid = SpatialWayGrid([main_street, bridge_ramp])

    # Car arrives at junction (50.0, 100.0) coming from bridge ramp
    car = Car(x=50.0, y=100.0, heading=0.0, speed=5.0)

    # Turning East onto Through Street (dx > 0, dy = 0)
    assert not is_violating_oneway(car, 50.0, 100.0, 1.0, 0.0, spatial_grid=grid)

    # Turning West onto Through Street (dx < 0, dy = 0)
    # Even though it's perpendicular / opposite to bridge ramp, Through Street is two-way, so it must not be blocked!
    assert not is_violating_oneway(car, 50.0, 100.0, -1.0, 0.0, spatial_grid=grid)

    # Driving backwards up the bridge ramp North (dx = 0, dy > 0) -> opposing the one-way ramp!
    # At (50, 120) which is on ramp only:
    assert is_violating_oneway(car, 50.0, 120.0, 0.0, 1.0, spatial_grid=grid)


def test_no_deadlock_at_intersection():
    main_street = Way(
        points_m=[(0.0, 100.0), (100.0, 100.0)],
        highway="primary",
        half_width_m=5.0,
        name="Through Street",
        oneway=0,
    )
    bridge_ramp = Way(
        points_m=[(50.0, 150.0), (50.0, 100.0)],
        highway="primary",
        half_width_m=5.0,
        name="Test Bridge",
        oneway=1,
    )

    grid = SpatialWayGrid([main_street, bridge_ramp])

    # Turn left or right at intersection:
    car = Car(x=50.0, y=100.0, heading=3.14159, speed=5.0)  # heading West
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
    assert not blocked
    assert car.x < 50.0  # moved West along Through Street without deadlock
