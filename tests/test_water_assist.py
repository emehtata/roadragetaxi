from theroadragetrip.osm import Water, Way
from theroadragetrip.physics import Car, SpatialWayGrid, is_point_in_water, update_car_physics, water_ahead_speed_limit

LAKE = Water(points_m=[(30.0, -50.0), (200.0, -50.0), (200.0, 50.0), (30.0, 50.0), (30.0, -50.0)],
             kind="water", is_polygon=True)


def test_full_throttle_towards_a_lake_stops_before_the_shore():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=20.0)
    for _ in range(600):
        limit = water_ahead_speed_limit(car, [LAKE], month=9)
        hard = limit is not None and car.speed > limit + 0.5  # as simulation.py: emergency braking
        update_car_physics(car, 0.0 if hard else 1.0, 1.0 if hard else 0.0, 0.0, 0.0, 1 / 30,
                           ways=[], block_offroad=False, speed_limit_mps=limit)
    front = car.x + car.length_m / 2
    assert car.speed < 0.6 and not is_point_in_water(front, 0.0, [LAKE])
    assert front > 30.0 - 4.0  # stops at the shore, not far back


def test_reversing_away_from_the_shore_is_free():
    car = Car(x=26.0, y=0.0, heading=0.0, speed=-2.0)
    assert water_ahead_speed_limit(car, [LAKE], month=9) is None


def test_a_bridge_over_the_water_and_winter_lake_ice_do_not_brake():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=20.0)
    assert water_ahead_speed_limit(car, [LAKE], month=1) is None
    bridge = Way(points_m=[(-10.0, 0.0), (300.0, 0.0)], highway="primary", half_width_m=4.0, is_bridge=True)
    assert water_ahead_speed_limit(car, [LAKE], month=9, spatial_grid=SpatialWayGrid([bridge])) is None
