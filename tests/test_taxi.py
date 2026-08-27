import math
from theroadragetrip.osm import Place, Way
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager, TaxiState, TaxiTarget


def test_taxi_target_address_generation():
    way = Way(
        points_m=[(100.0, 100.0), (200.0, 100.0)],
        highway="residential",
        half_width_m=4.5,
        name="Kirkkokatu",
    )
    place = Place(x=150.0, y=100.0, name="Keskusta", kind="suburb")
    taxi_mgr = TaxiManager(ways=[way], places=[place])

    addr = taxi_mgr.generate_address_for_point(150.0, 100.0, way_name="Kirkkokatu")
    assert "Kirkkokatu" in addr
    assert "Keskusta" in addr


def test_taxi_fallback_to_named_road():
    way1 = Way(
        points_m=[(100.0, 100.0), (200.0, 100.0)],
        highway="residential",
        half_width_m=4.5,
        name="Saaristonkatu",
    )
    way2 = Way(
        points_m=[(120.0, 110.0), (180.0, 110.0)],
        highway="service",
        half_width_m=3.5,
        name=None,
    )
    taxi_mgr = TaxiManager(ways=[way1, way2])
    addr = taxi_mgr.generate_address_for_point(150.0, 110.0, way_name=None)
    assert "Saaristonkatu" in addr
    assert "Tie " not in addr


def test_taxi_real_osm_housenumber():
    from theroadragetrip.osm import Building

    way = Way(
        points_m=[(100.0, 100.0), (200.0, 100.0)],
        highway="residential",
        half_width_m=4.5,
        name="Kauppakatu",
    )
    bldg = Building(
        points_m=[(140.0, 110.0), (160.0, 110.0), (160.0, 130.0), (140.0, 130.0)],
        name="Kirjasto",
        housenumber="42B",
        street="Kauppakatu",
    )
    taxi_mgr = TaxiManager(ways=[way], buildings=[bldg])
    addr = taxi_mgr.generate_address_for_point(150.0, 100.0, way_name="Kauppakatu")
    assert "Kauppakatu 42B" in addr


def test_taxi_mission_lifecycle():
    way1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Torikatu",
    )
    way2 = Way(
        points_m=[(500.0, 0.0), (600.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        name="Saaristonkatu",
    )
    taxi_mgr = TaxiManager(
        ways=[way1, way2],
        min_distance_m=100.0,
        max_distance_m=1000.0,
        pickup_radius_m=20.0,
        max_stop_speed_mps=2.0,
    )

    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    taxi_mgr.spawn_mission(car.x, car.y)

    assert taxi_mgr.current_passenger is not None
    assert taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP

    pickup = taxi_mgr.current_passenger.pickup
    dropoff = taxi_mgr.current_passenger.dropoff

    # 1. Drive towards pickup at high speed -> should not pick up until car stops/slows down
    car.x, car.y = pickup.x, pickup.y
    car.speed = 15.0  # ~54 km/h
    taxi_mgr.update(car, dt=0.1)
    assert taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP

    # 2. Stop at pickup -> Passenger boards
    car.speed = 0.5
    taxi_mgr.update(car, dt=0.1)
    assert taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF
    assert taxi_mgr.get_current_target() == dropoff

    # 3. Drive towards dropoff
    car.x, car.y = dropoff.x, dropoff.y
    car.speed = 0.0
    taxi_mgr.update(car, dt=5.0)  # fast delivery in 5s

    # 4. Should complete fare, award points based on speed, and spawn next mission
    assert taxi_mgr.completed_fares == 1
    assert taxi_mgr.total_score > 0
    assert taxi_mgr.last_fare_points > 0
    assert taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP


def test_taxi_scoring_speed_bonus():
    taxi_mgr = TaxiManager(ways=[])
    # Fast delivery: 1000m in 20s (50 m/s = 180 km/h) vs slow delivery (1000m in 100s)
    fast_score = taxi_mgr.calculate_score(distance_m=1000.0, elapsed_sec=20.0)
    slow_score = taxi_mgr.calculate_score(distance_m=1000.0, elapsed_sec=100.0)
    assert fast_score > slow_score
