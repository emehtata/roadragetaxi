"""Railway taxi phases 9-10: the booked passenger at the stand, met by the
driver on foot with a name card and an explicit greeting."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pygame

from theroadragetrip.fare import calculate_fare_cents
from theroadragetrip.pedestrian import PlayerPedestrian
from theroadragetrip.physics import Car
from theroadragetrip.rail_bookings import (
    IN_TAXI,
    MISSED,
    PASSENGER_MET,
    PASSENGER_WAITING,
    PICKUP_WINDOW,
    PREBOOKING_SURCHARGE_CENTS,
    RailBookingManager,
    waiting_booking,
)
from theroadragetrip.render.pedestrians import BOOKED_CUSTOMER_COLOR, draw_booked_passenger_arrow, draw_pedestrians
from theroadragetrip.simulation import apply_enter_exit_vehicle
from theroadragetrip.station_passengers import SYNC_INTERVAL_S, StationPassengerView
from theroadragetrip.taxi import GREET_RADIUS_M, TaxiManager, TaxiState
from theroadragetrip.train_passengers import ON_TRAIN, TAXI, PassengerFlow, RailPassenger

from test_station_passengers import FakePedestrians

NOW = datetime(2026, 9, 25, 18, 42)
STATION = (0.0, 0.0)
STAND = SimpleNamespace(x=20.0, y=40.0)  # the stand's waiting spot is on the walkway at (20, 40)
DESTINATION = SimpleNamespace(x=900.0, y=900.0, address="Kirkkokatu 1", radius_m=25.0)
ELSEWHERE = SimpleNamespace(x=-900.0, y=0.0, address="Random street 2", radius_m=25.0)
SILENT = SimpleNamespace(play=lambda *args, **kwargs: None)


class Always:
    def random(self):
        return 0.0


def booked_train(*names):
    """A train arriving at Oulu with one accepted booked passenger per name."""
    bookings = RailBookingManager(destination_for=lambda stand: DESTINATION)
    service = SimpleNamespace(train_type="IC", number="57", seconds=66000)
    train = SimpleNamespace(service=service, stops=((0.0, 60, "Oulu", 67320, 67380),), manifest={})
    for name in names:
        passenger = RailPassenger("Helsinki", "Oulu", ("IC", "57"), ON_TRAIN, name=name, intent=TAXI, taxi_stand=STAND)
        bookings.accept(bookings.consider(passenger, train, NOW - timedelta(minutes=22), Always()))
        train.manifest.setdefault("Oulu", []).append(passenger)
    return bookings, train


def arrive(bookings, train, view, view_point):
    leaving, boarding = PassengerFlow().on_arrival(train, "Oulu", NOW)
    bookings.passengers_arrived(leaving)
    view.on_arrival(leaving, boarding, STATION, view_point)
    view.update(0.0, PassengerFlow(), [("Oulu", STATION)], view_point, bookings.waiting())
    return leaving


def taxi(bookings):
    manager = TaxiManager(ways=[])
    manager.pick_random_building_point = lambda *args, **kwargs: ELSEWHERE
    manager.rail_bookings = bookings
    return manager


def at_stand(*names):
    """Booked passengers standing at the stand, the taxi parked 10 m away."""
    bookings, train = booked_train(*names)
    pedestrians = FakePedestrians()
    passengers = arrive(bookings, train, StationPassengerView(pedestrians), view_point=STATION)
    for passenger in passengers:
        passenger.pedestrian.x, passenger.pedestrian.y = 20.0, 40.0
    return bookings, passengers, pedestrians, taxi(bookings), Car(x=20.0, y=50.0, heading=0.0, speed=0.0)


def get_out(car, pedestrians=None, manager=None):
    player = PlayerPedestrian(x=0.0, y=0.0)
    assert apply_enter_exit_vehicle(car, player, False, SILENT, manager, pedestrians) is True
    return player


def walk_to(player, pedestrian, gap=1.0):
    player.x, player.y = pedestrian.x, pedestrian.y - gap


def test_the_booked_passenger_steps_off_as_one_linked_pedestrian():
    bookings, train = booked_train("Aino Virtanen")
    pedestrians = FakePedestrians()
    view = StationPassengerView(pedestrians)
    (passenger,) = arrive(bookings, train, view, view_point=STATION)

    assert passenger.booking.status == PASSENGER_WAITING
    assert pedestrians.pedestrians == [passenger.pedestrian]  # one pedestrian, no duplicate
    pedestrian = passenger.pedestrian
    assert pedestrian.rail_passenger is passenger and waiting_booking(pedestrian) is passenger.booking
    assert pedestrian.held_by is view  # never culled while the job waits
    assert pedestrian.taxi_stop_target == (20.0, 40.0)  # the existing stand, as in phase 7


def test_parking_by_the_booked_passenger_no_longer_picks_them_up():
    bookings, (passenger,), pedestrians, manager, _ = at_stand("Aino Virtanen")
    manager.taxi_stops = [STAND]
    right_by = Car(x=20.0, y=45.0, heading=0.0, speed=0.0)
    for _ in range(10):  # well past the stand's 2 s at 5 m
        assert manager.check_waiting_pickup(right_by, [passenger.pedestrian], 1.0) is None
    assert passenger.booking.status == PASSENGER_WAITING and manager.current_passenger is None


def test_f_in_the_taxi_only_gets_the_driver_out():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    car.x, car.y = passenger.pedestrian.x, passenger.pedestrian.y - 1.0  # even parked on top of them
    get_out(car, pedestrians, manager)
    assert passenger.booking.status == PASSENGER_WAITING and manager.current_passenger is None


def test_the_target_is_the_booked_passenger_itself_not_whoever_is_nearest():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    stranger = SimpleNamespace(x=20.0, y=39.5, heading=0.0, wants_taxi=True)
    pedestrians.pedestrians.append(stranger)
    passenger.pedestrian.x = 21.5  # walked a bit - the arrow and greeting follow them
    player = get_out(car, pedestrians, manager)

    assert manager.meet_booking() is passenger.booking
    player.x, player.y = 20.0, 38.0  # beside the stranger, 2.5 m from the booked passenger
    assert manager.greetable(player) is None
    walk_to(player, passenger.pedestrian)
    assert manager.greetable(player) == (passenger.booking, passenger.pedestrian)


def test_greeting_takes_an_explicit_f_and_is_the_only_way_to_met():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    player = get_out(car, pedestrians, manager)
    walk_to(player, passenger.pedestrian, gap=GREET_RADIUS_M - 0.5)
    for _ in range(50):  # standing there is not greeting
        manager.update(car, 0.1)
        manager.check_waiting_pickup(car, pedestrians.pedestrians, 0.1)
    assert passenger.booking.status == PASSENGER_WAITING

    pedestrian = passenger.pedestrian
    assert apply_enter_exit_vehicle(car, player, True, SILENT, manager, pedestrians) is True  # greets, stays out
    assert passenger.booking.status == PASSENGER_MET
    assert pedestrian not in pedestrians.pedestrians  # the fare's walker now
    assert manager.state == TaxiState.CLIENT_WALKING_TO_CAR


def test_boarding_and_the_trip_wait_for_the_driver():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    booking = passenger.booking
    player = get_out(car, pedestrians, manager)
    walk_to(player, passenger.pedestrian)
    apply_enter_exit_vehicle(car, player, True, SILENT, manager, pedestrians)
    customer = manager.current_passenger

    manager.driver_on_foot = True
    for _ in range(200):  # long enough to reach the door
        manager.update(car, 0.1)
    assert booking.status == PASSENGER_MET and not customer.boarded
    assert manager.state == TaxiState.CLIENT_WALKING_TO_CAR and manager.fare_started_at is None

    walk_to(player, car)  # back to the taxi
    assert apply_enter_exit_vehicle(car, player, True, SILENT, manager, pedestrians) is False
    manager.driver_on_foot = False
    manager.update(car, 0.1)
    assert booking.status == IN_TAXI and customer.boarded
    assert manager.state == TaxiState.DRIVING_TO_DROPOFF
    assert customer.rail_booking is booking and customer.dropoff is DESTINATION  # not regenerated
    assert customer.name == "Aino Virtanen"
    assert booking.surcharge_cents == PREBOOKING_SURCHARGE_CENTS == 800
    # The meter starts at the normal startup fare, the fee is not added into it.
    assert manager.live_fare_cents == calculate_fare_cents(0.0, 0.0, manager.fare_started_at)


def test_the_arrow_and_card_are_only_for_the_meeting_in_progress():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    assert manager.meet_booking() is passenger.booking  # arrow on them, card while on foot
    player = get_out(car, pedestrians, manager)
    walk_to(player, passenger.pedestrian)
    apply_enter_exit_vehicle(car, player, True, SILENT, manager, pedestrians)
    assert manager.meet_booking() is None  # greeted: no arrow, no card

    bookings, (passenger,), pedestrians, manager, car = at_stand("Eero Laine")
    bookings.update(NOW + PICKUP_WINDOW + timedelta(seconds=1))
    assert passenger.booking.status == MISSED and manager.meet_booking() is None


def test_one_meeting_at_a_time_and_the_others_untouched():
    bookings, (first, second), pedestrians, manager, car = at_stand("Aino Virtanen", "Eero Laine")
    second.booking.arrival_at -= timedelta(minutes=5)  # came in on an earlier train
    second.pedestrian.x = 25.0
    assert manager.meet_booking() is second.booking

    player = get_out(car, pedestrians, manager)
    walk_to(player, first.pedestrian)
    assert manager.greetable(player) is None  # not the one being met now
    walk_to(player, second.pedestrian)
    apply_enter_exit_vehicle(car, player, True, SILENT, manager, pedestrians)
    assert second.booking.status == PASSENGER_MET and first.booking.status == PASSENGER_WAITING
    assert manager.current_passenger.rail_booking is second.booking


def test_a_missed_booking_can_no_longer_be_greeted():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    pedestrian = passenger.pedestrian
    player = get_out(car, pedestrians, manager)
    walk_to(player, pedestrian)
    bookings.update(NOW + PICKUP_WINDOW + timedelta(seconds=1))

    assert manager.greet_booked_passenger(player, car) is None
    assert passenger.booking.status == MISSED and manager.current_passenger is None


def test_an_ordinary_stand_customer_still_boards_by_stopping():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    passenger.pedestrian.x, passenger.pedestrian.y = 20.0, 80.0
    ordinary = SimpleNamespace(x=20.0, y=40.0, heading=0.0, wants_taxi=True)
    manager.taxi_stops = [STAND]

    car.y = 45.0
    assert manager.check_waiting_pickup(car, [passenger.pedestrian, ordinary], 3.0) is ordinary
    assert manager.current_passenger.rail_booking is None
    assert manager.current_passenger.dropoff is ELSEWHERE
    assert passenger.booking.status == PASSENGER_WAITING


def test_an_uncollected_passenger_is_missed_and_becomes_ordinary():
    bookings, train = booked_train("Aino Virtanen")
    view = StationPassengerView(FakePedestrians())
    (passenger,) = arrive(bookings, train, view, view_point=STATION)
    booking, pedestrian = passenger.booking, passenger.pedestrian

    bookings.update(NOW + PICKUP_WINDOW)
    assert booking.status == PASSENGER_WAITING
    bookings.update(NOW + PICKUP_WINDOW + timedelta(seconds=1))
    assert booking.status == MISSED and booking not in bookings.bookings

    view.update(SYNC_INTERVAL_S, PassengerFlow(), [("Oulu", STATION)], STATION, bookings.waiting())
    assert pedestrian.held_by is None and passenger.pedestrian is None
    assert waiting_booking(pedestrian) is None


def test_a_pending_booking_is_missed_when_its_train_comes_in():
    bookings, train = booked_train()
    passenger = RailPassenger("Helsinki", "Oulu", ("IC", "57"), ON_TRAIN, intent=TAXI, taxi_stand=STAND)
    booking = bookings.consider(passenger, train, NOW, Always())
    bookings.passengers_arrived([passenger])
    assert booking.status == MISSED


def test_an_out_of_view_arrival_stays_data_until_its_station_is_seen():
    bookings, train = booked_train("Aino Virtanen")
    pedestrians = FakePedestrians()
    view = StationPassengerView(pedestrians)
    far = (5000.0, 0.0)
    (passenger,) = arrive(bookings, train, view, view_point=far)
    manager = taxi(bookings)
    assert passenger.pedestrian is None and pedestrians.pedestrians == []
    assert manager.meet_booking() is passenger.booking  # a job, but nothing to point the arrow at yet

    view.update(SYNC_INTERVAL_S, PassengerFlow(), [("Oulu", STATION)], STATION, bookings.waiting())
    pedestrian = passenger.pedestrian
    assert pedestrians.pedestrians == [pedestrian] and waiting_booking(pedestrian) is passenger.booking
    assert (pedestrian.x, pedestrian.y) == (20.0, 40.0) and pedestrian.is_taxi_stop_waiter

    view.update(SYNC_INTERVAL_S, PassengerFlow(), [("Oulu", STATION)], far, bookings.waiting())
    assert passenger.pedestrian is None and pedestrians.pedestrians == []
    assert passenger.booking.status == PASSENGER_WAITING

    view.update(SYNC_INTERVAL_S, PassengerFlow(), [("Oulu", STATION)], STATION, bookings.waiting())
    assert passenger.pedestrian.resident_id == pedestrian.resident_id  # the same person again


def _drawn(draw):
    screen = pygame.Surface((200, 200))
    draw(screen)
    return screen


def _count(screen, color):
    return sum(1 for x in range(200) for y in range(200) if screen.get_at((x, y))[:3] == color)


def test_arrow_and_white_card_are_drawn_without_any_name_text():
    class NoText:
        def render(self, *args, **kwargs):
            raise AssertionError("the meet & greet needs no text")

    booked = SimpleNamespace(x=0.0, y=0.0, heading=0.0, radius_m=0.45)
    arrow = _drawn(lambda screen: draw_booked_passenger_arrow(screen, booked, 0.0, 0.0, 10.0, 200, 200))
    assert _count(arrow, BOOKED_CUSTOMER_COLOR) > 0

    player = PlayerPedestrian(x=0.0, y=0.0)
    plain = _drawn(lambda screen: draw_pedestrians(screen, [player], 0.0, 0.0, font=NoText(), px_per_m=10.0,
                                                   screen_w=200, screen_h=200))
    player.name_card = True
    carded = _drawn(lambda screen: draw_pedestrians(screen, [player], 0.0, 0.0, font=NoText(), px_per_m=10.0,
                                                    screen_w=200, screen_h=200))
    assert _count(carded, (255, 255, 255)) > _count(plain, (255, 255, 255))
