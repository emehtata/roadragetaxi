from theroadragetrip.osm import TaxiStop, Way
from theroadragetrip.physics import Car
from theroadragetrip.localization import tr
from theroadragetrip.police import PoliceManager, SpeedCamera, camera_count, camera_sees_car, place_speed_cameras
from theroadragetrip.taxi import TaxiManager
from theroadragetrip.traffic import TrafficManager


def road(length=1000.0, name="Test Road"):
    return Way([(0.0, 0.0), (length, 0.0)], "primary", 4.0, name=name, speed_limit_kmh=50)


def test_camera_count_scales_and_helsinki_has_twenty():
    ways = [road(name=f"Road {index}") for index in range(250)]
    assert 1 <= camera_count([road()]) <= 20
    assert camera_count(ways, "Helsinki") == 20
    assert camera_count(ways) == 20


def test_camera_count_ignores_disconnected_roads_like_traffic_count():
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
    assert manager.speed_camera_flash_timer == 0.35
    assert manager.speed_camera_flash_index == 0
    assert not manager.check_speed_cameras(car, [camera])
    assert manager.total_score == -300

    manager.update(car, 0.35)
    assert manager.speed_camera_flash_timer == 0.0
    assert manager.speed_camera_flash_index is None

    car.x = 200.0
    manager.check_speed_cameras(car, [camera])
    car.x = 60.0
    assert manager.check_speed_cameras(car, [camera])
    assert manager.total_score == -600


def test_camera_placement_is_reproducible():
    ways = [road(name=f"Road {index}") for index in range(20)]
    first = place_speed_cameras(ways, (0.0, 0.0, 1000.0, 1000.0))
    second = place_speed_cameras(ways, (0.0, 0.0, 1000.0, 1000.0))
    assert first == second


def test_each_taxi_stop_gets_a_camera():
    ways = [road(name=f"Road {index}") for index in range(100)]
    stops = [TaxiStop(100.0, 0.0, 1), TaxiStop(600.0, 0.0, 2)]
    cameras = place_speed_cameras(ways, (0.0, 0.0, 1000.0, 1000.0), taxi_stops=stops)
    assert any(abs(camera.x - stops[0].x) <= 5.0 and abs(camera.y - stops[0].y) <= 5.0 for camera in cameras)
    assert any(abs(camera.x - stops[1].x) <= 5.0 and abs(camera.y - stops[1].y) <= 5.0 for camera in cameras)
    assert all(abs(camera.y - stop.y) >= 4.0 for camera, stop in zip(cameras[:2], stops))


def test_taxi_stop_camera_option_is_opt_in_at_call_site():
    ways = [road(name=f"Road {index}") for index in range(100)]
    stops = [TaxiStop(100.0, 0.0, 1), TaxiStop(600.0, 0.0, 2)]
    without_stops = place_speed_cameras(ways, (0.0, 0.0, 1000.0, 1000.0))
    with_stops = place_speed_cameras(ways, (0.0, 0.0, 1000.0, 1000.0), taxi_stops=stops)
    assert len(with_stops) >= len(without_stops)
    assert len(with_stops) >= len(stops)


def test_police_cars_spawn_as_traffic_npcs():
    traffic = TrafficManager([road()], target_count=0)
    police = PoliceManager(traffic, 100.0, 0.0, count=1)

    assert len(police.cars) == 1
    assert police.cars[0] in traffic.npcs
    assert police.cars[0].is_police


def test_police_stop_releases_taxi_after_penalty():
    traffic = TrafficManager([road()], target_count=0)
    police = PoliceManager(traffic, 100.0, 0.0, count=1)
    taxi = Car(x=100.0, y=0.0, heading=0.0, speed=20.0)
    police.cars[0].x = 20.0
    police.cars[0].y = 0.0
    police.cars[0].heading = 0.0

    for _ in range(120):
        if police.update(taxi, road(), 0.1):
            break

    assert police.collect_penalty(taxi, road())
    assert not police.update(taxi, road(), 0.1)
    assert tr("fi", "police_stop", penalty=300) == "Poliisipysäytys! -300 pistettä"


def test_opposite_direction_police_waits_for_taxi_to_pass():
    traffic = TrafficManager([road()], target_count=0)
    police = PoliceManager(traffic, 100.0, 0.0, count=1)
    patrol = police.cars[0]
    patrol.x = 80.0
    patrol.y = 0.0
    patrol.heading = 3.141592653589793
    taxi = Car(x=60.0, y=0.0, heading=0.0, speed=20.0)

    police.update(taxi, road(), 0.1)

    assert patrol.pursuing is True
    assert patrol.pursuit_phase == "yielding"
    assert patrol.speed == 0.0
    assert patrol.x == 80.0

    taxi.x = 90.0
    police.update(taxi, road(), 0.1)
    assert patrol.pursuit_phase == "behind"
    assert patrol.heading == taxi.heading


def test_rage_shout_interrupts_police_pursuit():
    traffic = TrafficManager([road()], target_count=0)
    police = PoliceManager(traffic, 100.0, 0.0, count=1)
    patrol = police.cars[0]
    patrol.pursuing = True
    patrol.heading = 0.0

    assert police.scare()
    assert not patrol.pursuing
    assert patrol.scared_timer == 3.0
    assert patrol.heading == 3.141592653589793


def test_rage_shout_prevents_immediate_police_re_pursuit():
    traffic = TrafficManager([road()], target_count=0)
    police = PoliceManager(traffic, 100.0, 0.0, count=1)
    patrol = police.cars[0]
    patrol.pursuing = True
    taxi = Car(x=60.0, y=0.0, heading=0.0, speed=20.0)

    assert police.scare()
    police.update(taxi, road(), 0.1)

    assert patrol.pursuing is False
    assert patrol.scared_timer == 2.9