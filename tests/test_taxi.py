import math
import time
from types import SimpleNamespace

import pytest
from theroadragetrip.osm import Building, Place, Scenery, TaxiStop, Way
from theroadragetrip.physics import Car, is_point_on_road
from theroadragetrip.taxi import TaxiManager, TaxiOffer, TaxiPassenger, TaxiState, TaxiTarget


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
    # Regression: the offset used to be capped *below* half_width_m,
    # placing the passenger inside the road's own driving surface
    # instead of on the sidewalk beside it.
    assert abs(passenger_y) > way.half_width_m


def test_phone_passenger_never_waits_in_a_highway_lane():
    """Regression: on a wide road (e.g. a motorway) the old offset
    formula placed the passenger a few meters from the centerline -
    inside a travel lane - instead of clearing the road entirely."""
    way = Way(
        points_m=[(0.0, 0.0), (200.0, 0.0)],
        highway="motorway",
        half_width_m=7.0,
        name="Moottoritie",
    )
    taxi_mgr = TaxiManager(ways=[way])
    pickup = TaxiTarget(100.0, 0.0, "Moottoritie")

    _, passenger_y, _ = taxi_mgr.passenger_waiting_position(pickup)

    assert not is_point_on_road(100.0, passenger_y, ways=[way], car_roads_only=True)


def test_offer_generation_adds_one_offer_at_a_time(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.5)
    taxi_mgr = TaxiManager(ways=[way])
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    requested_counts = []

    def fake_generate(car_x, car_y, count=3, append=False):
        requested_counts.append(count)
        taxi_mgr._initial_offer_pending = False
        return []

    monkeypatch.setattr(taxi_mgr, "generate_offers", fake_generate)
    taxi_mgr.next_offer_timer = 0.0
    taxi_mgr.update(car, 0.1)
    taxi_mgr.next_offer_timer = 0.0
    taxi_mgr.update(car, 0.1)

    assert requested_counts == [1, 1]


def test_offer_generation_caps_phone_at_three_offers(monkeypatch):
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.5)
    taxi_mgr = TaxiManager(ways=[way])
    taxi_mgr.offers = [TaxiOffer(SimpleNamespace(), 100.0) for _ in range(3)]
    taxi_mgr.next_offer_timer = 0.0
    taxi_mgr.update(Car(x=0.0, y=0.0, heading=0.0, speed=0.0), 0.1)

    assert len(taxi_mgr.offers) == 3


def test_offer_generation_is_suppressed_while_passenger_is_active():
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.5)
    taxi_mgr = TaxiManager(ways=[way])
    taxi_mgr.current_passenger = object()
    taxi_mgr.offers = [object()]

    assert taxi_mgr.generate_offers(0.0, 0.0) == []
    assert taxi_mgr.offers == []


def test_phone_offers_are_cleared_while_passenger_is_active():
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.5)
    taxi_mgr = TaxiManager(ways=[way])
    taxi_mgr.current_passenger = SimpleNamespace(
        boarded=False,
        nausea_resolved=False,
        nausea_vomited=False,
        pickup=None,
        dropoff=None,
    )
    taxi_mgr.offers = [object(), object()]

    taxi_mgr.update(Car(x=0.0, y=0.0, heading=0.0, speed=0.0), 0.1)

    assert taxi_mgr.offers == []


def test_unaccepted_phone_offers_expire_over_time():
    way = Way(points_m=[(0.0, 0.0), (200.0, 0.0)], highway="residential", half_width_m=4.5)
    taxi_mgr = TaxiManager(ways=[way])
    offer = TaxiOffer(
        passenger=SimpleNamespace(),
        pickup_distance_m=100.0,
        time_remaining_s=1.0,
    )
    taxi_mgr.offers = [offer]

    taxi_mgr.update(Car(x=0.0, y=0.0, heading=0.0, speed=0.0), 1.1)

    assert taxi_mgr.offers == []


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


def test_taxi_venue_target_prefers_nearby_unnamed_access_road():
    from theroadragetrip.osm import Building

    main_road = Way(
        points_m=[(0.0, 0.0), (145.0, 0.0)],
        highway="primary",
        half_width_m=5.0,
        name="Iso tie",
    )
    main_road_continuation = Way(
        points_m=[(145.0, 0.0), (300.0, 0.0)],
        highway="primary",
        half_width_m=5.0,
        name="Iso tie",
    )
    access_road = Way(
        points_m=[(145.0, 0.0), (145.0, 70.0)],
        highway="service",
        half_width_m=3.0,
    )
    building = Building(
        points_m=[(140.0, 70.0), (170.0, 70.0), (170.0, 90.0), (140.0, 90.0)],
        name="Sysmän venue",
        venue_type="restaurant",
    )
    taxi_mgr = TaxiManager(
        ways=[main_road, main_road_continuation, access_road], buildings=[building]
    )

    target = taxi_mgr.pick_random_building_point(venue_types={"restaurant"})

    assert target is not None
    assert target.way_name == ""
    assert target.x == 145.0
    assert target.y == 70.0


def test_taxi_venue_target_accepts_named_amenity_place():
    way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="service",
        half_width_m=3.0,
        name="Pihakatu",
    )
    pub = Place(x=40.0, y=6.0, name="Kulmapubi", kind="pub")
    taxi_mgr = TaxiManager(ways=[way], places=[pub])

    target = taxi_mgr.pick_random_building_point(venue_types={"pub"})

    assert target is not None
    assert target.address == "Kulmapubi"
    assert target.venue_type == "pub"
    assert target.way_name == "Pihakatu"


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


def test_taxi_mission_uses_osm_taxi_stops_for_pickup_only():
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
    assert taxi_mgr.current_passenger.dropoff.x not in (500.0, 1000.0)


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
    assert all(30.0 <= offer.time_remaining_s <= 180.0 for offer in offers)
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


@pytest.mark.parametrize("hour", [1.0, 6.0, 9.0, 14.0, 21.0, 22.5])
def test_phone_offers_fall_back_to_a_road_point_with_no_buildings_or_stands(hour):
    """Regression: discarding/finishing a ride in an area with no named
    buildings or taxi stops nearby - a real, sparsely-mapped area, or just
    one the game hasn't loaded much of yet - left generate_offers stuck
    returning nothing for every hour bracket except the default (12-20h)
    one, which was the only one with a fallback past its preferred
    source. spawn_mission already falls back to any named road point;
    pick_phone_pickup/dropoff now do too, for every hour."""
    way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="residential",
        half_width_m=4.5,
        name="Torikatu",
    )
    taxi_mgr = TaxiManager(ways=[way])  # no buildings, no places, no taxi stops
    taxi_mgr.game_time_seconds = hour * 3600.0

    offers = taxi_mgr.generate_offers(0.0, 0.0, count=1)

    assert len(offers) == 1


def test_generate_offers_shortens_the_retry_wait_after_coming_up_empty():
    """Regression: next_offer_timer is frozen (not decremented) while a
    passenger is aboard, so right after a discard/dropoff/vomit-abandon it
    can still hold a stale value up to PHONE_OFFER_MAX_INTERVAL_S (60s)
    old from before that ride even started. If the immediate
    generate_offers(count=1) those call sites make also finds nothing,
    the player was stuck watching zero offers for up to a minute with no
    indication anything was happening."""
    taxi_mgr = TaxiManager(ways=[])  # nothing anywhere can ever be picked
    taxi_mgr.next_offer_timer = 55.0

    offers = taxi_mgr.generate_offers(0.0, 0.0, count=1)

    assert offers == []
    assert taxi_mgr.next_offer_timer <= 6.0


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


def _grid_buildings(count, spacing=30.0, size=10.0, cols=200):
    buildings = []
    for i in range(count):
        x = float(i % cols) * spacing
        y = float(i // cols) * spacing
        pts = [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
        buildings.append(Building(points_m=pts, bbox=(x, y, x + size, y + size)))
    return buildings


def test_nearby_collision_buildings_indexes_incrementally_not_the_whole_list():
    """Regression: _nearby_collision_buildings() rebuilt its whole spatial
    grid - every building ever loaded, not just the newly-added ones -
    every time the buildings list changed length, which fired on nearly
    every frame right after autofetch integrated a tile (osm/autofetch.py's
    _extend_unique() only ever appends in place - same list object,
    never reordered or shrunk). Confirmed via profiling a real
    autofetch-enabled drive: "collisions" dominated 97% of frames that
    missed the 60fps budget, at car speed 0 (this scales with total
    loaded map size, not distance driven).

    Reproduces the growth pattern directly - .extend() in batches on one
    list object, exactly like autofetch - and asserts on wall time.
    Fixed measured ~6ms total for 20 growth calls against 6000 buildings;
    unfixed (rebuilding the whole grid every growth) measured ~52ms."""
    mgr = TaxiManager(ways=[], language="en")
    all_buildings = _grid_buildings(6000)
    live_buildings: list = []
    batch = 300

    total_ms = 0.0
    for start in range(0, len(all_buildings), batch):
        live_buildings.extend(all_buildings[start:start + batch])
        t0 = time.perf_counter()
        mgr._nearby_collision_buildings(live_buildings, 0.0, 0.0, 5.0)
        total_ms += (time.perf_counter() - t0) * 1000.0

    assert total_ms < 25.0, (
        f"20 growth calls against 6000 buildings took {total_ms:.1f}ms total - "
        f"looks like the whole list is being re-indexed on every growth"
    )


def test_nearby_collision_buildings_stays_correct_across_incremental_growth():
    """The incremental-indexing optimization above must never change what
    _nearby_collision_buildings() actually returns - only how cheaply it
    gets there."""
    mgr = TaxiManager(ways=[], language="en")
    all_buildings = _grid_buildings(300)
    live_buildings: list = []
    for start in range(0, len(all_buildings), 50):
        live_buildings.extend(all_buildings[start:start + 50])
        mgr._nearby_collision_buildings(live_buildings, 0.0, 0.0, 5.0)

    # A building placed well within the query radius of the origin - the
    # very first one in the grid - must be found once everything's loaded.
    found = mgr._nearby_collision_buildings(live_buildings, 0.0, 0.0, 5.0)
    assert all_buildings[0] in found
    # One far outside must not be.
    assert all_buildings[-1] not in found


def _grid_fences(count, spacing=30.0, size=10.0, cols=200):
    fences = []
    for i in range(count):
        x = float(i % cols) * spacing
        y = float(i // cols) * spacing
        pts = [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
        fences.append(SimpleNamespace(kind="construction", points_m=pts, bbox=(x, y, x + size, y + size)))
    return fences


def test_nearby_collision_fences_indexes_incrementally_not_the_whole_list():
    """Same fix, same reason, as the buildings test above -
    _nearby_collision_fences() had the identical whole-list-rebuild bug."""
    mgr = TaxiManager(ways=[], language="en")
    all_fences = _grid_fences(6000)
    live_fences: list = []
    batch = 300

    total_ms = 0.0
    for start in range(0, len(all_fences), batch):
        live_fences.extend(all_fences[start:start + batch])
        t0 = time.perf_counter()
        mgr._nearby_collision_fences(live_fences, 0.0, 0.0, 5.0)
        total_ms += (time.perf_counter() - t0) * 1000.0

    assert total_ms < 25.0, (
        f"20 growth calls against 6000 fences took {total_ms:.1f}ms total - "
        f"looks like the whole list is being re-indexed on every growth"
    )


def test_nearby_collision_fences_stays_correct_across_incremental_growth():
    mgr = TaxiManager(ways=[], language="en")
    all_fences = _grid_fences(300)
    live_fences: list = []
    for start in range(0, len(all_fences), 50):
        live_fences.extend(all_fences[start:start + 50])
        mgr._nearby_collision_fences(live_fences, 0.0, 0.0, 5.0)

    found = mgr._nearby_collision_fences(live_fences, 0.0, 0.0, 5.0)
    assert all_fences[0] in found
    assert all_fences[-1] not in found


def _grid_sceneries_with_trees(count, trees_per=8, spacing=50.0, cols=100):
    out = []
    for i in range(count):
        x = float(i % cols) * spacing
        y = float(i // cols) * spacing
        trees = [(x + t * 2.0, y + t * 2.0) for t in range(trees_per)]
        out.append(Scenery(
            points_m=[(x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)],
            kind="forest", trees=trees,
        ))
    return out


def test_nearby_collision_trees_indexes_incrementally_not_the_whole_map():
    """Regression: same bug family as buildings/fences, but trickier -
    an individual scenery's own .trees list can change after that
    scenery is already indexed (osm/trees.py both appends to it as
    tiles stream in and reassigns it outright when
    remove_trees_under_roads() prunes some), so _nearby_collision_trees()
    tracks how many of each scenery's trees are already indexed rather
    than assuming the whole sceneries list is append-only. Confirmed via
    profiling: unfixed, growing to 1500 sceneries (8 trees each, in
    batches of 75) cost ~68ms total; fixed, ~11ms."""
    mgr = TaxiManager(ways=[], language="en")
    all_sceneries = _grid_sceneries_with_trees(1500)
    live_sceneries: list = []
    batch = 75

    total_ms = 0.0
    for start in range(0, len(all_sceneries), batch):
        live_sceneries.extend(all_sceneries[start:start + batch])
        t0 = time.perf_counter()
        mgr._nearby_collision_trees(live_sceneries, 0.0, 0.0, 5.0)
        total_ms += (time.perf_counter() - t0) * 1000.0

    assert total_ms < 35.0, (
        f"20 growth calls against 1500 tree-bearing sceneries took {total_ms:.1f}ms "
        f"total - looks like the whole tree map is being re-indexed on every growth"
    )


def test_nearby_collision_trees_stays_correct_across_incremental_growth():
    mgr = TaxiManager(ways=[], language="en")
    all_sceneries = _grid_sceneries_with_trees(60)
    live_sceneries: list = []
    for start in range(0, len(all_sceneries), 10):
        live_sceneries.extend(all_sceneries[start:start + 10])
        mgr._nearby_collision_trees(live_sceneries, 0.0, 0.0, 5.0)

    found = mgr._nearby_collision_trees(live_sceneries, 0.0, 0.0, 5.0)
    found_positions = {(fx, fy) for _, _, fx, fy in found}
    assert all_sceneries[0].trees[0] in found_positions
    assert all_sceneries[-1].trees[0] not in found_positions


def test_nearby_collision_trees_reflects_removal_from_an_already_indexed_scenery():
    """remove_trees_under_roads() (osm/trees.py) reassigns an existing,
    already-indexed scenery's .trees to a shorter list - a pruned tree
    must actually disappear from collision queries, not linger as a
    stale grid entry pointing at a tree that no longer exists."""
    mgr = TaxiManager(ways=[], language="en")
    scenery = Scenery(
        points_m=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        kind="forest", trees=[(1.0, 1.0), (2.0, 2.0)],
    )
    sceneries = [scenery]
    mgr._nearby_collision_trees(sceneries, 0.0, 0.0, 5.0)
    found = mgr._nearby_collision_trees(sceneries, 0.0, 0.0, 5.0)
    assert {(fx, fy) for _, _, fx, fy in found} == {(1.0, 1.0), (2.0, 2.0)}

    scenery.trees = [(1.0, 1.0)]  # (2.0, 2.0) pruned
    found_after = mgr._nearby_collision_trees(sceneries, 0.0, 0.0, 5.0)
    assert {(fx, fy) for _, _, fx, fy in found_after} == {(1.0, 1.0)}

