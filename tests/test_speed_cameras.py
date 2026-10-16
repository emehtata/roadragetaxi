import math
import pytest

from theroadragetrip.osm import TaxiStop, Way
from theroadragetrip.police import SpeedCamera, camera_count, camera_sees_car, place_speed_cameras
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager


def test_runtime_cameras_start_empty_wait_and_remain_sparse():
    from theroadragetrip.police import SpeedCameraSpawner
    from theroadragetrip.physics import SpatialWayGrid

    spawner = SpeedCameraSpawner(seed=1)
    grid = SpatialWayGrid([road(length=2000)])
    cameras = []
    car = Car(0, 0, 0, 0)
    assert 120 <= spawner.remaining_s <= 300
    assert spawner.update(119, car, grid, cameras) is None
    assert cameras == []
    camera = spawner.update(spawner.remaining_s, car, grid, cameras)
    assert cameras == [camera] and camera is not None
    assert math.hypot(camera.x, camera.y) >= 300
    assert 120 <= spawner.remaining_s <= 300
    # A huge elapsed time must not create a catch-up batch. The existing
    # camera also excludes other positions along this short stretch.
    assert spawner.update(10000, car, grid, cameras) is None
    assert cameras == [camera]


@pytest.mark.parametrize("highway,car_level,road_level", [
    ("service", 0, None), ("residential", 0, None),
    ("primary", -1, None), ("primary", 0, -1),
])
def test_runtime_cameras_reject_minor_roads_and_garage_levels(highway, car_level, road_level):
    from theroadragetrip.police import SpeedCameraSpawner
    from theroadragetrip.physics import SpatialWayGrid

    way = Way([(0, 0), (2000, 0)], highway, 4, map_level=road_level)
    spawner = SpeedCameraSpawner(seed=1)
    cameras = []
    assert spawner.update(1000, Car(0, 0, 0, 0, map_level=car_level), SpatialWayGrid([way]), cameras) is None
    assert cameras == []


def road(length=1000.0, name="Test Road"):
    return Way([(0.0, 0.0), (length, 0.0)], "primary", 4.0, name=name, speed_limit_kmh=50)


def test_camera_count_scales_and_helsinki_has_twenty():
    ways = [road(name=f"Road {index}") for index in range(250)]
    assert 1 <= camera_count([road()]) <= 20
    assert camera_count(ways, "Helsinki") == 20
    assert camera_count(ways) == 20


def test_camera_count_ignores_disconnected_roads():
    main_network = [road(name=f"Main {index}") for index in range(20)]
    isolated = Way([(10000.0, 10000.0), (11000.0, 10000.0)], "primary", 4.0, name="Isolated")
    assert camera_count(main_network + [isolated]) == camera_count(main_network)


def test_camera_detection_is_directional_and_limited_to_fifty_metres():
    camera = SpeedCamera(100.0, 0.0, 0.0, 50, 1)
    assert camera_sees_car(camera, 60.0, 0.0, 0.0)
    assert not camera_sees_car(camera, 40.0, 0.0, 0.0)
    assert not camera_sees_car(camera, 60.0, 10.0, 0.0)


def test_speeding_at_camera_costs_300_once_per_pass():
    manager = TaxiManager([road()])
    car = Car(x=60.0, y=0.0, heading=0.0, speed=20.0)
    camera = SpeedCamera(100.0, 0.0, 0.0, 50, 1)

    assert manager.check_speed_cameras(car, [camera])
    assert manager.total_score == -300
    assert not manager.check_speed_cameras(car, [camera])
    car.x = 200.0
    manager.check_speed_cameras(car, [camera])
    car.x = 60.0
    assert manager.check_speed_cameras(car, [camera])
    assert manager.total_score == -600


def test_camera_placement_is_reproducible_and_ignores_taxi_stops():
    ways = [road(name=f"Road {index}") for index in range(100)]
    stops = [TaxiStop(100.0, 0.0, 1), TaxiStop(600.0, 0.0, 2)]
    first = place_speed_cameras(ways, (0.0, 0.0, 1000.0, 1000.0))
    second = place_speed_cameras(ways, (0.0, 0.0, 1000.0, 1000.0))
    with_stops = place_speed_cameras(ways, (0.0, 0.0, 1000.0, 1000.0), taxi_stops=stops)

    assert first == second
    assert with_stops == first
    assert first
    assert all(camera.y < 0.0 and math.isclose(camera.y, -5.0, abs_tol=1e-9) for camera in first)


def test_cameras_are_only_placed_on_main_roads():
    main_road = road(name="Main road")
    main_road.osm_id = 1
    parking_aisle = Way(
        [(0.0, 20.0), (1000.0, 20.0)], "service", 3.0,
        name="Parking aisle", osm_id=2, service="parking_aisle",
    )

    cameras = place_speed_cameras([parking_aisle, main_road], (0.0, 0.0, 1000.0, 1000.0), seed=1)

    assert cameras and all(camera.way_id == main_road.osm_id for camera in cameras)


@pytest.mark.parametrize("heading", [0.0, math.pi / 2, math.pi, -math.pi / 3])
def test_generated_camera_watches_inner_lane_of_a_wide_road(heading):
    way = Way([(0, 0), (1000 * math.cos(heading), 1000 * math.sin(heading))],
              "primary", 12, speed_limit_kmh=50)
    camera = place_speed_cameras([way], (0, 0, 1000, 1000), seed=1)[0]
    # An inner lane, ten metres from the roadside pole: outside the old 8m check.
    x = camera.x - 20 * math.cos(heading) - 10 * math.sin(heading)
    y = camera.y - 20 * math.sin(heading) + 10 * math.cos(heading)
    manager = TaxiManager([way])
    car = Car(x, y, heading, 200 / 3.6)
    assert manager.check_speed_cameras(car, [camera])
    assert manager.total_score == -300
    assert manager.speed_camera_flash_index == 0
    assert manager.speed_camera_notice_timer > 0


def test_reverse_oneway_camera_watches_the_legal_travel_direction():
    way = road()
    way.oneway = -1
    camera = place_speed_cameras([way], (0, 0, 1000, 1000), seed=1)[0]
    assert camera.y > 0
    assert camera_sees_car(camera, camera.x + 20, 2, math.pi)
    assert not camera_sees_car(camera, camera.x - 20, -2, 0)


def test_fast_pass_cannot_skip_the_whole_detection_zone():
    manager = TaxiManager([road()])
    camera = SpeedCamera(100, 0, 0, 50, 1)
    car = Car(110, 0, 0, 1000)
    assert not camera_sees_car(camera, car.x, car.y, car.heading)
    assert manager.check_speed_cameras(car, [camera], previous_position=(40, 0))
    assert manager.total_score == -300
    assert not manager.check_speed_cameras(car, [camera], previous_position=(100, 0))
    assert manager.total_score == -300


@pytest.mark.parametrize("previous,current,heading", [
    ((40, 20), (110, 20), 0),  # parallel road outside the detection corridor
    ((110, 0), (40, 0), math.pi),  # opposite direction
    ((0, 0), (40, 0), 0),  # has not reached the zone
])
def test_swept_detection_does_not_catch_unwatched_traffic(previous, current, heading):
    camera = SpeedCamera(100, 0, 0, 50, 1)
    assert not camera_sees_car(camera, *current, heading, previous)


@pytest.mark.parametrize("layer,level", [(1, 0), (0, -1)])
def test_camera_does_not_detect_a_different_bridge_or_map_level(layer, level):
    manager = TaxiManager([road()])
    car = Car(60, 0, 0, 100)
    car.layer, car.map_level = layer, level
    assert not manager.check_speed_cameras(car, [SpeedCamera(100, 0, 0, 50, 1)])


def test_camera_does_not_fine_a_legal_speed_even_on_a_swept_pass():
    manager = TaxiManager([road()])
    car = Car(110, 0, 0, 50 / 3.6)
    assert not manager.check_speed_cameras(car, [SpeedCamera(100, 0, 0, 50, 1)], previous_position=(40, 0))
    assert manager.total_score == 0
