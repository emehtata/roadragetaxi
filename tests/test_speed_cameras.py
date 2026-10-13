import math

from theroadragetrip.osm import TaxiStop, Way
from theroadragetrip.police import SpeedCamera, camera_count, camera_sees_car, place_speed_cameras
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager


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
