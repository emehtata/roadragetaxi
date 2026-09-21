import math

from theroadragetrip.osm import Building, Scenery, Way
from theroadragetrip.physics import (
    Car,
    SpatialWayGrid,
    is_car_road,
    is_on_road,
    is_point_on_road,
    update_car_physics,
)
from theroadragetrip.taxi import TaxiManager


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


def test_grass_offroad_is_not_speed_capped_but_has_poor_grip():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=5.0)
    grid = SpatialWayGrid(cell_size=100.0)
    grid.rebuild([road])
    car = Car(x=50.0, y=4.0, heading=math.pi / 2.0, speed=10.0)

    blocked = update_car_physics(
        car, 1.0, 0.0, 0.0, 0.0, 0.2, ways=[road], spatial_grid=grid, block_offroad=False
    )
    assert blocked is False
    assert car.speed > 10.0 - 0.5  # no off-road cap on soft ground
    assert car.ground_kind == "soft"

    update_car_physics(car, 1.0, 0.0, 0.0, 0.0, 0.2, ways=[road], spatial_grid=grid, block_offroad=False)
    assert car.max_grip_g < 0.9 * 2.0 * 0.5  # grass grip, well under asphalt's (arcade x2)


def test_sand_is_the_slowest_surface_and_hard_ground_is_uncapped():
    from theroadragetrip.osm import Scenery

    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=5.0)
    beach = Scenery(points_m=[(0.0, 10.0), (100.0, 10.0), (100.0, 60.0), (0.0, 60.0)], kind="beach", bbox=(0.0, 10.0, 100.0, 60.0))
    plaza = Scenery(points_m=[(0.0, 70.0), (100.0, 70.0), (100.0, 120.0), (0.0, 120.0)], kind="pedestrian_area", bbox=(0.0, 70.0, 100.0, 120.0))
    grid = SpatialWayGrid(cell_size=100.0)
    grid.rebuild([road])
    scenery_grid = SpatialWayGrid([beach, plaza])

    def drive(y):
        car = Car(x=20.0, y=y, heading=0.0, speed=15.0)
        for _ in range(30):
            update_car_physics(car, 1.0, 0.0, 0.0, 0.0, 0.1, ways=[road], spatial_grid=grid, scenery_grid=scenery_grid, block_offroad=False)
        return car

    sand = drive(30.0)
    assert sand.ground_kind == "sand" and sand.speed <= 2.5
    hard = drive(90.0)
    assert hard.ground_kind == "hard" and hard.speed > 15.0


def test_pedestrian_way_is_not_slowed_but_costs_penalty_points():
    from theroadragetrip.taxi import TaxiManager

    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=5.0)
    footway = Way(points_m=[(0.0, 20.0), (100.0, 20.0)], highway="footway", half_width_m=2.0)
    grid = SpatialWayGrid(cell_size=100.0)
    grid.rebuild([road, footway])
    car = Car(x=10.0, y=20.0, heading=0.0, speed=12.0)
    update_car_physics(car, 1.0, 0.0, 0.0, 0.0, 0.1, ways=[road, footway], spatial_grid=grid, block_offroad=False)
    assert car.speed >= 12.0

    taxi = TaxiManager(ways=[road])
    for _ in range(60):
        taxi.check_pedestrian_way_violation(car, 0.1, ways=[road, footway], spatial_grid=grid)
    assert taxi.total_score < 0  # ~6s on a footway -> at least one penalty

    on_road = Car(x=10.0, y=0.0, heading=0.0, speed=12.0)
    taxi2 = TaxiManager(ways=[road])
    for _ in range(100):
        taxi2.check_pedestrian_way_violation(on_road, 0.1, ways=[road, footway], spatial_grid=grid)
    assert taxi2.total_score == 0


def test_can_accelerate_forward_from_rest_offroad():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=5.0)
    grid = SpatialWayGrid(cell_size=100.0)
    grid.rebuild([road])
    car = Car(x=50.0, y=20.0, heading=0.0, speed=0.0)

    update_car_physics(
        car, 1.0, 0.0, 0.0, 0.0, 0.2, ways=[road], spatial_grid=grid, block_offroad=False
    )

    assert car.speed > 0.0
    assert car.x > 50.0


def test_light_traffic_way_is_faster_than_terrain():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=5.0)
    cycleway = Way(points_m=[(0.0, 20.0), (100.0, 20.0)], highway="cycleway", half_width_m=2.0)
    grid = SpatialWayGrid(cell_size=100.0)
    grid.rebuild([road, cycleway])

    car = Car(x=50.0, y=20.0, heading=0.0, speed=10.0)
    update_car_physics(
        car, 1.0, 0.0, 0.0, 0.0, 0.2,
        ways=[road, cycleway], spatial_grid=grid, block_offroad=False,
    )

    assert car.speed > 2.0


def test_building_collision_bounces_and_penalizes_once():
    from theroadragetrip.osm import Building

    building = Building(points_m=[(4.0, -3.0), (8.0, -3.0), (8.0, 3.0), (4.0, 3.0)])
    car = Car(x=5.0, y=0.0, heading=0.0, speed=4.0)
    taxi_manager = TaxiManager(ways=[])

    crashed = taxi_manager.check_building_collision(car, [building], sim_time=1.0, previous_position=(3.0, 0.0))
    score_after_crash = taxi_manager.total_score
    crashed_again = taxi_manager.check_building_collision(car, [building], sim_time=2.0, previous_position=(3.0, 0.0))

    assert crashed is True
    assert crashed_again is True
    assert (car.x, car.y) == (3.0, 0.0)
    assert car.speed == 0.0
    assert taxi_manager.taxi_smoke_timer == 5.0
    assert score_after_crash == -200
    assert taxi_manager.total_score == score_after_crash


def test_building_overlapping_road_does_not_cause_crash():
    from theroadragetrip.osm import Building

    road = Way(points_m=[(0.0, 0.0), (20.0, 0.0)], highway="residential", half_width_m=4.0)
    building = Building(points_m=[(5.0, -5.0), (15.0, -5.0), (15.0, 5.0), (5.0, 5.0)])
    car = Car(x=10.0, y=0.0, heading=0.0, speed=4.0)
    taxi_manager = TaxiManager(ways=[road])

    crashed = taxi_manager.check_building_collision(car, [building], sim_time=1.0, ways=[road])

    assert crashed is False
    assert car.speed == 4.0
    assert taxi_manager.total_score == 0


def test_tunnel_through_building_does_not_cause_crash_across_layers():
    tunnel = Way(
        points_m=[(0.0, 0.0), (20.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        layer=0,
        is_tunnel=True,
    )
    building = Building(points_m=[(5.0, -5.0), (15.0, -5.0), (15.0, 5.0), (5.0, 5.0)])
    car = Car(x=10.0, y=0.0, heading=0.0, speed=4.0, layer=1)
    taxi_manager = TaxiManager(ways=[tunnel])

    crashed = taxi_manager.check_building_collision(car, [building], sim_time=1.0, ways=[tunnel])

    assert crashed is False
    assert car.speed == 4.0
    assert taxi_manager.total_score == 0


def test_building_collision_still_triggers_off_road():
    from theroadragetrip.osm import Building

    road = Way(points_m=[(0.0, 0.0), (20.0, 0.0)], highway="residential", half_width_m=1.0)
    building = Building(points_m=[(5.0, -5.0), (15.0, -5.0), (15.0, 5.0), (5.0, 5.0)])
    car = Car(x=10.0, y=2.5, heading=0.0, speed=4.0)
    taxi_manager = TaxiManager(ways=[road])

    crashed = taxi_manager.check_building_collision(car, [building], sim_time=1.0, ways=[road])

    assert crashed is True
    assert car.speed == 0.0


def test_tree_collision_stops_and_penalizes_once():
    scenery = Scenery(points_m=[(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0)], kind="park", trees=[(0.0, 0.0)])
    car = Car(x=0.0, y=0.0, heading=0.0, speed=4.0)
    taxi_manager = TaxiManager(ways=[])

    crashed = taxi_manager.check_tree_collision(car, [scenery], sim_time=1.0, previous_position=(-3.0, 0.0))
    score_after_crash = taxi_manager.total_score
    crashed_again = taxi_manager.check_tree_collision(car, [scenery], sim_time=2.0, previous_position=(-3.0, 0.0))

    assert crashed is True
    assert crashed_again is False
    assert math.hypot(car.x, car.y) > math.hypot(car.length_m, car.width_m) * 0.5 + 1.0
    assert car.speed == 0.0
    assert score_after_crash == -100
    assert taxi_manager.total_score == score_after_crash
