from theroadragetrip import (
    Car,
    SpatialWayGrid,
    Water,
    Way,
    get_current_road_at_car,
    is_car_fully_in_water,
    is_on_road,
    is_point_in_water,
    respawn_car,
)


def test_is_on_road_true_and_false():
    # Create a simple horizontal road from (0,0) to (10,0)
    w = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=2.0, name="Torikatu")
    car_on = Car(x=5.0, y=0.0, heading=0.0, speed=0.0)
    car_off = Car(x=100.0, y=100.0, heading=0.0, speed=0.0)

    assert is_on_road(car_on, [w]) is True
    assert is_on_road(car_off, [w]) is False

    # Check get_current_road_at_car
    road = get_current_road_at_car(car_on, [w])
    assert road is not None
    assert road.name == "Torikatu"

    grid = SpatialWayGrid([w])
    road_grid = get_current_road_at_car(car_on, spatial_grid=grid)
    assert road_grid is not None
    assert road_grid.name == "Torikatu"

    assert get_current_road_at_car(car_off, [w]) is None
    assert get_current_road_at_car(car_off, spatial_grid=grid) is None


def test_respawn_car_places_on_road_with_heading():
    w = Way(points_m=[(10.0, 20.0), (30.0, 20.0)], highway="residential", half_width_m=2.0)
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    respawn_car(car, [w])

    assert is_on_road(car, [w]) is True
    assert car.x == 20.0
    assert car.y == 20.0
    assert car.heading == 0.0


def test_respawn_car_avoids_water_and_ice_roads():
    # Road 1: on top of lake (ice road)
    lake = Water(
        points_m=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)],
        kind="water",
        is_polygon=True,
    )
    ice_road = Way(points_m=[(10.0, 50.0), (90.0, 50.0)], highway="track", half_width_m=3.0, is_ice_road=True)
    # Road 2: footway on land (not drivable)
    footway = Way(points_m=[(200.0, 150.0), (300.0, 150.0)], highway="footway", half_width_m=2.0, is_drivable=False)
    # Road 3: drivable road on land
    land_road = Way(points_m=[(200.0, 200.0), (300.0, 200.0)], highway="residential", half_width_m=4.5, is_drivable=True)

    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    respawn_car(car, [ice_road, footway, land_road], waters=[lake])

    assert car.x == 250.0
    assert car.y == 200.0
    assert not is_point_in_water(car.x, car.y, [lake])


def test_car_is_fully_in_water_requires_all_corners_inside():
    lake = Water(
        points_m=[(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0), (-10.0, -10.0)],
        kind="water",
        is_polygon=True,
    )
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    assert is_car_fully_in_water(car, [lake])

    car.x = 9.5
    assert not is_car_fully_in_water(car, [lake])


def test_bridge_over_water_does_not_trigger_water_respawn():
    lake = Water(
        points_m=[(-20.0, -20.0), (20.0, -20.0), (20.0, 20.0), (-20.0, 20.0), (-20.0, -20.0)],
        kind="water",
        is_polygon=True,
    )
    bridge = Way(
        points_m=[(-100.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        layer=1,
        is_bridge=True,
    )
    car = Car(x=0.0, y=0.0, heading=0.0, speed=8.0, layer=1)

    assert not is_car_fully_in_water(car, [lake], current_way=bridge)

