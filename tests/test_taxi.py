import math
from types import SimpleNamespace

import pytest
from theroadragetrip.osm import Building, Place, TaxiStop, Way
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager, TaxiPassenger, TaxiManager, TaxiState, TaxiTarget
from theroadragetrip.taxi import TaxiManager, TaxiPassenger, TaxiState, TaxiTarget


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


def test_phone_passenger_waits_at_right_road_edge():
    way = Way(
        points_m=[(0.0, 0.0), (200.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Odotuskatu",
    )
    taxi_mgr = TaxiManager(ways=[way])
    pickup = TaxiTarget(100.0, 0.0, "Odotuskatu")

    passenger_x, passenger_y, heading = taxi_mgr.passenger_waiting_position(pickup)

    assert passenger_x == 100.0
    assert passenger_y < 0.0
    assert heading == 0.0


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


def test_taxi_named_building_target_uses_reachable_road_point():
    from theroadragetrip.osm import Building

    way = Way(
        points_m=[(0.0, 0.0), (300.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Asemakatu",
    )
    building = Building(
        points_m=[(120.0, 30.0), (180.0, 30.0), (180.0, 60.0), (120.0, 60.0)],
        name="Kaupungintalo",
    )
    taxi_mgr = TaxiManager(ways=[way], buildings=[building])

    target = taxi_mgr.pick_random_building_point()

    assert target is not None
    assert target.address == "Kaupungintalo"
    assert target.way_name == "Asemakatu"
    assert target.y == 0.0
    assert 120.0 <= target.x <= 180.0


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

    # 2. Stop at pickup -> Client starts walking towards car
    car.speed = 0.5
    taxi_mgr.update(car, dt=0.1)
    assert taxi_mgr.state == TaxiState.CLIENT_WALKING_TO_CAR
    assert taxi_mgr.current_passenger.is_walking_to_car is True

    # 3. Passenger completes walk and boards
    for _ in range(30):
        if taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF:
            break
        taxi_mgr.update(car, dt=0.2)

    assert taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF
    assert taxi_mgr.current_passenger.boarded is True
    assert taxi_mgr.get_current_target() == dropoff

    # 4. Drive towards dropoff
    car.x, car.y = dropoff.x, dropoff.y
    car.speed = 0.0
    taxi_mgr.update(car, dt=5.0)  # fast delivery in 5s

    # 5. Complete fare, award points, and offer next rides through the phone
    assert taxi_mgr.completed_fares == 1
    assert taxi_mgr.total_score > 0
    assert taxi_mgr.last_fare_points > 0
    assert taxi_mgr.current_passenger is None
    assert taxi_mgr.offers


def test_taxi_mission_prefers_osm_taxi_stops():
    way = Way(
        points_m=[(0.0, 0.0), (2000.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Stop Street",
    )
    stops = [TaxiStop(500.0, 0.0), TaxiStop(1000.0, 0.0)]
    taxi_mgr = TaxiManager(ways=[way], taxi_stops=stops, min_distance_m=100.0, max_distance_m=1200.0)

    taxi_mgr.spawn_mission(0.0, 0.0)

    assert taxi_mgr.current_passenger is not None
    assert taxi_mgr.current_passenger.pickup.x in (500.0, 1000.0)
    assert taxi_mgr.current_passenger.dropoff.x in (500.0, 1000.0)


def test_phone_offers_show_distance_and_accept_selected_ride():
    way = Way(
        points_m=[(0.0, 0.0), (3000.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Phone Street",
    )
    stops = [TaxiStop(500.0, 0.0), TaxiStop(1000.0, 0.0), TaxiStop(1600.0, 0.0)]
    taxi_mgr = TaxiManager(ways=[way], taxi_stops=stops, min_distance_m=100.0, max_distance_m=1200.0)

    offers = taxi_mgr.generate_offers(0.0, 0.0, count=3)

    assert len(offers) == 3
    assert all(offer.pickup_distance_m > 0.0 for offer in offers)
    selected = offers[1].passenger
    assert taxi_mgr.accept_offer(1, 0.0, 0.0) is True
    assert taxi_mgr.current_passenger is selected
    assert taxi_mgr.offers == []


def test_phone_offers_use_allowed_pickup_and_dropoff_locations():
    way = Way(
        points_m=[(0.0, 0.0), (3000.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Keskuskatu",
    )
    stops = [TaxiStop(500.0, 0.0), TaxiStop(2500.0, 0.0)]
    buildings = [
        Building([(400.0, 20.0), (420.0, 20.0), (420.0, 40.0), (400.0, 40.0)], name="Kahvila"),
        Building([(2200.0, 20.0), (2220.0, 20.0), (2220.0, 40.0), (2200.0, 40.0)], name="Hotelli"),
    ]
    taxi_mgr = TaxiManager(
        ways=[way],
        buildings=buildings,
        taxi_stops=stops,
        min_distance_m=300.0,
        max_distance_m=2500.0,
    )

    offers = taxi_mgr.generate_offers(0.0, 0.0, count=1)

    assert len(offers) == 1
    pickup = offers[0].passenger.pickup
    dropoff = offers[0].passenger.dropoff
    assert pickup.address in {"Kahvila", "Hotelli"} or "Keskuskatu" in pickup.address
    assert dropoff.x not in {stop.x for stop in stops}


def test_idle_taxi_gets_one_random_phone_request_and_can_reject():
    way = Way(
        points_m=[(0.0, 0.0), (3000.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Request Street",
    )
    taxi_mgr = TaxiManager(ways=[way], min_distance_m=100.0, max_distance_m=1200.0)
    taxi_mgr.next_offer_timer = 0.0

    taxi_mgr.update(Car(x=0.0, y=0.0, heading=0.0, speed=0.0), dt=0.1)

    assert len(taxi_mgr.offers) == 1
    assert taxi_mgr.reject_offer() is True
    assert taxi_mgr.offers == []


def test_stopped_taxi_at_stand_can_board_nearby_pedestrian(monkeypatch: pytest.MonkeyPatch):
    way = Way(
        points_m=[(0.0, 0.0), (2000.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Stand Street",
    )
    stops = [TaxiStop(0.0, 0.0), TaxiStop(1000.0, 0.0)]
    taxi_mgr = TaxiManager(ways=[way], taxi_stops=stops, min_distance_m=300.0, max_distance_m=1200.0)
    pedestrian = SimpleNamespace(x=3.0, y=0.0, heading=0.0, wants_taxi=True)
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    monkeypatch.setattr("theroadragetrip.taxi.random.random", lambda: 0.0)

    boarded = taxi_mgr.check_waiting_pickup(car, [pedestrian], dt=2.0)

    assert boarded is pedestrian
    assert taxi_mgr.current_passenger is not None
    assert taxi_mgr.current_passenger.boarded is False
    assert taxi_mgr.current_passenger.is_walking_to_car is True
    assert taxi_mgr.state == TaxiState.CLIENT_WALKING_TO_CAR

    for _ in range(10):
        taxi_mgr.update(car, dt=0.2)
        if taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF:
            break

    assert taxi_mgr.current_passenger.boarded is True
    assert taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF


def test_stopped_taxi_can_pick_up_street_hail_without_taxi_stops(monkeypatch: pytest.MonkeyPatch):
    way = Way(
        points_m=[(0.0, 0.0), (2000.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Hail Street",
    )
    taxi_mgr = TaxiManager(ways=[way], min_distance_m=300.0, max_distance_m=1200.0)
    pedestrian = SimpleNamespace(x=3.0, y=0.0, heading=0.0)
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    monkeypatch.setattr("theroadragetrip.taxi.random.random", lambda: 0.0)

    boarded = taxi_mgr.check_waiting_pickup(car, [pedestrian], dt=2.0)

    assert boarded is pedestrian
    assert "huusi taksin" in taxi_mgr.notification_msg
    assert taxi_mgr.current_passenger.boarded is False
    assert taxi_mgr.current_passenger.is_walking_to_car is True
    assert taxi_mgr.state == TaxiState.CLIENT_WALKING_TO_CAR


def test_moving_taxi_hail_waits_for_car_to_stop(monkeypatch: pytest.MonkeyPatch):
    way = Way(
        points_m=[(0.0, 0.0), (2000.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Passing Hail Street",
    )
    taxi_mgr = TaxiManager(ways=[way], min_distance_m=300.0, max_distance_m=1200.0)
    pedestrian = SimpleNamespace(x=5.0, y=2.0, heading=0.0, wants_taxi=True)
    car = Car(x=0.0, y=0.0, heading=0.0, speed=8.0)
    monkeypatch.setattr("theroadragetrip.taxi.random.random", lambda: 0.0)

    boarded = taxi_mgr.check_waiting_pickup(car, [pedestrian], dt=0.1)

    assert boarded is pedestrian
    assert taxi_mgr.current_passenger is not None
    assert taxi_mgr.current_passenger.boarded is False
    assert taxi_mgr.current_passenger.is_walking_to_car is True
    assert taxi_mgr.state == TaxiState.CLIENT_WALKING_TO_CAR


def test_pedestrian_who_does_not_want_taxi_is_ignored(monkeypatch: pytest.MonkeyPatch):
    way = Way(
        points_m=[(0.0, 0.0), (2000.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="No Hail Street",
    )
    taxi_mgr = TaxiManager(ways=[way], min_distance_m=300.0, max_distance_m=1200.0)
    pedestrian = SimpleNamespace(x=3.0, y=0.0, heading=0.0, wants_taxi=False)
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    monkeypatch.setattr("theroadragetrip.taxi.random.random", lambda: 0.0)

    assert taxi_mgr.check_waiting_pickup(car, [pedestrian], dt=2.0) is None
    assert taxi_mgr.current_passenger is None


def test_taxi_scoring_speed_bonus():
    taxi_mgr = TaxiManager(ways=[])
    # Fast delivery: 1000m in 20s (50 m/s = 180 km/h) vs slow delivery (1000m in 100s)
    fast_score = taxi_mgr.calculate_score(distance_m=1000.0, elapsed_sec=20.0)
    slow_score = taxi_mgr.calculate_score(distance_m=1000.0, elapsed_sec=100.0)
    assert fast_score > slow_score


def test_passenger_nausea_is_relieved_when_taxi_stops():
    way = Way(points_m=[(0.0, 0.0), (2000.0, 0.0)], highway="residential", half_width_m=4.5, name="Nausea Street")
    pickup = TaxiTarget(0.0, 0.0, "Pickup")
    dropoff = TaxiTarget(1000.0, 0.0, "Dropoff")
    taxi_mgr = TaxiManager(ways=[way])
    passenger = TaxiPassenger("Test", pickup, dropoff, boarded=True, nausea_warning_timer=3.0)
    taxi_mgr.current_passenger = passenger
    taxi_mgr.state = TaxiState.DRIVING_TO_DROPOFF
    car = Car(x=100.0, y=0.0, heading=0.0, speed=0.0)

    taxi_mgr.update(car, dt=0.1)

    assert passenger.nausea_resolved is True
    assert passenger.nausea_vomited is False
    assert taxi_mgr.current_passenger is passenger
    assert len(taxi_mgr.vomit_puddles) == 1


def test_vomiting_ends_fare_only_after_taxi_stops():
    way = Way(points_m=[(0.0, 0.0), (2000.0, 0.0)], highway="residential", half_width_m=4.5, name="Nausea Street")
    pickup = TaxiTarget(0.0, 0.0, "Pickup")
    dropoff = TaxiTarget(1000.0, 0.0, "Dropoff")
    taxi_mgr = TaxiManager(ways=[way])
    passenger = TaxiPassenger("Test", pickup, dropoff, boarded=True, nausea_warning_timer=0.1)
    taxi_mgr.current_passenger = passenger
    taxi_mgr.state = TaxiState.DRIVING_TO_DROPOFF
    car = Car(x=100.0, y=0.0, heading=0.0, speed=10.0)

    taxi_mgr.update(car, dt=0.2)
    assert passenger.nausea_vomited is True
    assert taxi_mgr.total_score == -500
    assert taxi_mgr.current_passenger is passenger

    car.speed = 0.0
    released = taxi_mgr.take_vomited_passenger(car)
    assert released is passenger
    assert taxi_mgr.current_passenger is None


def test_discard_pickup_penalty():
    way1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Torikatu",
    )
    taxi_mgr = TaxiManager(ways=[way1])
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    taxi_mgr.spawn_mission(car.x, car.y)
    assert taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP

    old_score = taxi_mgr.total_score
    old_passenger = taxi_mgr.current_passenger

    # Discard pickup
    taxi_mgr.discard_mission(car.x, car.y, penalty=150)
    assert taxi_mgr.total_score == old_score - 150
    assert taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP
    assert taxi_mgr.current_passenger is None
    assert taxi_mgr.offers


def test_respawn_penalizes_onboard_passenger():
    way1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Torikatu",
    )
    taxi_mgr = TaxiManager(ways=[way1], pickup_radius_m=20.0, max_stop_speed_mps=2.0)
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    taxi_mgr.spawn_mission(car.x, car.y)

    # 1. Respawn before picking up -> no penalty for respawning
    init_score = taxi_mgr.total_score
    taxi_mgr.handle_respawn(car.x, car.y)
    assert taxi_mgr.total_score == init_score

    # 2. Pick up passenger
    pickup = taxi_mgr.current_passenger.pickup
    car.x, car.y = pickup.x, pickup.y
    car.speed = 0.0
    taxi_mgr.update(car, dt=0.1)
    assert taxi_mgr.state == TaxiState.CLIENT_WALKING_TO_CAR
    for _ in range(30):
        if taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF:
            break
        taxi_mgr.update(car, dt=0.2)
    assert taxi_mgr.state == TaxiState.DRIVING_TO_DROPOFF

    # 3. Respawn with passenger on board -> penalty applied & mission discarded
    taxi_mgr.handle_respawn(car.x, car.y)
    assert taxi_mgr.total_score == init_score - 200
    assert taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP
    assert taxi_mgr.current_passenger is None
    assert taxi_mgr.offers

