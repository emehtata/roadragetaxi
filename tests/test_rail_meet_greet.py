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
    TRAIN_ARRIVING,
    PREBOOKING_SURCHARGE_CENTS,
    RailBookingManager,
    waiting_booking,
)
from theroadragetrip.render.pedestrians import BOOKED_CUSTOMER_COLOR, draw_booked_passenger_arrow, draw_pedestrians
from theroadragetrip.simulation import apply_enter_exit_vehicle, remove_boarded_rail_walker
from theroadragetrip.station_passengers import SYNC_INTERVAL_S, StationPassengerView
from theroadragetrip.taxi import GREET_RADIUS_M, TaxiManager, TaxiState
from theroadragetrip.train_passengers import ON_TRAIN, TAXI, PassengerFlow, RailPassenger

from test_station_passengers import FakePedestrians

NOW = datetime(2026, 9, 25, 18, 42)
STATION = (0.0, 0.0)
STAND = SimpleNamespace(x=20.0, y=40.0)  # the stand's waiting spot is on the walkway at (20, 40)
DESTINATION = SimpleNamespace(x=900.0, y=900.0, address="Kirkkokatu 1", radius_m=25.0)
ELSEWHERE = SimpleNamespace(x=-900.0, y=0.0, address="Random street 2", radius_m=25.0)
SILENT = SimpleNamespace(play=lambda *args, **kwargs: None, play_group=lambda *args, **kwargs: None)


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


def get_out(car, manager=None):
    player = PlayerPedestrian(x=0.0, y=0.0)
    assert apply_enter_exit_vehicle(car, player, False, SILENT, manager) is True
    if manager is not None:
        manager.driver_on_foot = True  # as simulation.advance_simulation sets it every tick
    return player


def press_f(car, player, manager):
    on_foot = apply_enter_exit_vehicle(car, player, True, SILENT, manager)
    manager.driver_on_foot = on_foot
    return on_foot


def walk_to(player, target, gap=1.0):
    player.x, player.y = target.x, target.y - gap


def greeted(*names):
    """At the stand, the driver out and the first passenger greeted."""
    bookings, passengers, pedestrians, manager, car = at_stand(*names)
    player = get_out(car, manager)
    walk_to(player, passengers[0].pedestrian)
    assert press_f(car, player, manager) is True
    return bookings, passengers, pedestrians, manager, car, player


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


def test_the_walk_to_the_stand_is_a_footway_route_planned_once():
    bookings, train = booked_train("Aino Virtanen")
    pedestrians = FakePedestrians()
    pedestrians.via = [(20.0, 10.0), (20.0, 30.0)]  # what the footway network returned
    view = StationPassengerView(pedestrians)
    (passenger,) = arrive(bookings, train, view, view_point=STATION)
    pedestrian = passenger.pedestrian

    assert pedestrians.routes_planned == 1
    assert pedestrian.route[1:] == [(20.0, 10.0), (20.0, 30.0), (20.0, 40.0)]
    # Handed to the pedestrian system's _walk_route_to as already planned:
    assert pedestrian.destination == pedestrian.taxi_stop_target and pedestrian.current_route_segment == 1


def test_no_safe_route_to_the_stand_means_walking_off_not_through_a_building(caplog):
    bookings, train = booked_train("Aino Virtanen")
    pedestrians = FakePedestrians()
    pedestrians._path_crosses_building = lambda *line: True
    with caplog.at_level("INFO", logger="theroadragetrip.station_passengers"):
        (passenger,) = arrive(bookings, train, StationPassengerView(pedestrians), view_point=STATION)

    assert not getattr(passenger.pedestrian, "is_walking_to_taxi_stop", False)
    assert passenger.booking.status == PASSENGER_WAITING  # still booked, still findable
    assert "no safe route to taxi stand" in caplog.text and "building" in caplog.text


def test_a_waiting_booking_keeps_the_clock_real_time():
    """Root cause of the vanishing F prompt: between fares the game clock
    ran 60x, so PICKUP_WINDOW (20 game minutes) lapsed ~20 real seconds
    after the train came in - usually just as the driver reached the
    passenger - and the booking was MISSED."""
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    assert manager.current_passenger is None and manager.has_active_job()

    bookings.update(NOW + timedelta(seconds=25))  # 25 real seconds at 1x
    assert passenger.booking.status == PASSENGER_WAITING and manager.has_active_job()
    bookings.update(NOW + timedelta(seconds=25 * 60))  # what 60x used to make of them
    assert passenger.booking.status == MISSED and not manager.has_active_job()


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
    get_out(car, manager)
    assert passenger.booking.status == PASSENGER_WAITING and manager.current_passenger is None


def test_the_target_is_the_booked_passenger_itself_not_whoever_is_nearest():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    stranger = SimpleNamespace(x=20.0, y=39.5, heading=0.0, wants_taxi=True)
    pedestrians.pedestrians.append(stranger)
    passenger.pedestrian.x = 21.5  # walked a bit - the arrow and greeting follow them
    player = get_out(car, manager)

    assert manager.meet_context() is passenger.booking
    assert manager.meet_context().passenger.pedestrian is passenger.pedestrian  # the arrow's target
    player.x, player.y = 20.0, 38.0  # beside the stranger, 2.5 m from the booked passenger
    assert manager.greetable(player) is None
    walk_to(player, passenger.pedestrian)
    assert manager.greetable(player) == (passenger.booking, passenger.pedestrian)


def test_the_panel_says_who_and_what_to_do_and_f_stays_available_by_the_passenger():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    booking = passenger.booking
    player = PlayerPedestrian(x=0.0, y=0.0)
    assert manager.meet_prompt(player) == (booking, "meet_get_out")
    assert (booking.passenger.name, booking.train_number, booking.station) == ("Aino Virtanen", "IC57", "Oulu")

    player = get_out(car, manager)
    assert manager.meet_prompt(player) == (booking, "meet_walk_to_passenger")
    walk_to(player, passenger.pedestrian, gap=GREET_RADIUS_M - 0.5)
    for frame in range(100):  # 10 s standing by them is not greeting, and F stays offered
        manager.update(car, 0.1)
        manager.check_waiting_pickup(car, pedestrians.pedestrians, 0.1)
        bookings.update(NOW + timedelta(seconds=frame * 0.1))
        assert manager.meet_prompt(player) == (booking, "hint_greet_passenger")
    assert booking.status == PASSENGER_WAITING and passenger.pedestrian in pedestrians.pedestrians

    assert press_f(car, player, manager) is True  # greets, stays out
    assert booking.status == PASSENGER_MET
    assert manager.meet_prompt(player) == (booking, "meet_back_to_taxi")
    assert manager.state == TaxiState.CLIENT_WALKING_TO_CAR


def test_after_greeting_the_passenger_stays_and_walks_to_the_taxi_as_themselves():
    bookings, (passenger,), pedestrians, manager, car, player = greeted("Aino Virtanen")
    pedestrian = passenger.pedestrian

    assert pedestrian in pedestrians.pedestrians and pedestrian.rail_passenger is passenger
    assert pedestrian.is_walking_to_taxi_stop and pedestrian.taxi_stop_target == manager._door_position(car)
    assert pedestrian.route is None and pedestrian.base_speed > 0.0  # routed by the pedestrian system
    assert not pedestrian.wants_taxi  # nobody else's customer now
    assert manager.meet_context() is passenger.booking  # arrow stays on them
    assert manager.meet_booking() is None  # the card goes away once greeted

    view = pedestrian.held_by  # the station view keeps holding them, even at its next sync
    view.update(SYNC_INTERVAL_S, PassengerFlow(), [("Oulu", STATION)], STATION, bookings.waiting())
    assert passenger.pedestrian is pedestrian and pedestrian.held_by is view


def test_boarding_and_the_trip_wait_for_the_passenger_and_the_driver():
    bookings, (passenger,), pedestrians, manager, car, player = greeted("Aino Virtanen")
    booking, customer, pedestrian = passenger.booking, manager.current_passenger, passenger.pedestrian

    walk_to(player, car)  # the driver is back in first; the passenger is still on their way
    assert press_f(car, player, manager) is False
    pedestrian.x, pedestrian.y = 20.0, 42.0
    manager.update(car, 0.1)
    assert (customer.ped_x, customer.ped_y) == (20.0, 42.0)  # the fare follows the pedestrian
    assert booking.status == PASSENGER_MET and not customer.boarded

    player = get_out(car, manager)  # out again; the passenger reaches the door
    pedestrian.x, pedestrian.y = manager._door_position(car)
    pedestrian.is_walking_to_taxi_stop = False
    for _ in range(50):
        manager.update(car, 0.1)
    assert booking.status == PASSENGER_MET and manager.fare_started_at is None  # waits for the driver
    assert pedestrian in pedestrians.pedestrians

    walk_to(player, car)
    assert press_f(car, player, manager) is False
    manager.update(car, 0.1)
    remove_boarded_rail_walker(manager, pedestrians)
    assert booking.status == IN_TAXI and customer.boarded and manager.state == TaxiState.DRIVING_TO_DROPOFF
    assert pedestrian not in pedestrians.pedestrians and passenger.pedestrian is None  # gone only now
    assert manager.meet_prompt(player) is None and manager.meet_context() is None
    assert customer.rail_booking is booking and customer.dropoff is DESTINATION  # not regenerated
    assert customer.name == "Aino Virtanen"
    assert booking.surcharge_cents == PREBOOKING_SURCHARGE_CENTS == 800
    # The meter starts at the normal startup fare, the fee is not added into it.
    assert manager.live_fare_cents == calculate_fare_cents(0.0, 0.0, manager.fare_started_at)


def test_one_meeting_at_a_time_and_the_others_untouched():
    bookings, (first, second), pedestrians, manager, car = at_stand("Aino Virtanen", "Eero Laine")
    second.booking.arrival_at -= timedelta(minutes=5)  # came in on an earlier train
    second.pedestrian.x = 25.0
    assert manager.meet_booking() is second.booking

    player = get_out(car, manager)
    walk_to(player, first.pedestrian)
    assert manager.greetable(player) is None  # not the one being met now
    walk_to(player, second.pedestrian)
    press_f(car, player, manager)
    assert second.booking.status == PASSENGER_MET and first.booking.status == PASSENGER_WAITING
    assert manager.current_passenger.rail_booking is second.booking
    assert first.pedestrian.taxi_stop_target == (20.0, 40.0) and first.pedestrian.wants_taxi  # still at the stand


def test_a_missed_booking_can_no_longer_be_greeted():
    bookings, (passenger,), pedestrians, manager, car = at_stand("Aino Virtanen")
    pedestrian = passenger.pedestrian
    player = get_out(car, manager)
    walk_to(player, pedestrian)
    bookings.update(NOW + PICKUP_WINDOW + timedelta(seconds=1))

    assert manager.greet_booked_passenger(player, car) is None
    assert manager.meet_prompt(player) is None and manager.meet_context() is None
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
    assert manager.meet_prompt(PlayerPedestrian(x=0.0, y=0.0)) == (passenger.booking, "meet_go_to_stand")

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


def test_from_accepting_the_panel_says_who_off_which_train_and_where():
    """Regression: after accepting a pre-booking nothing stayed on screen
    until the passenger was already waiting at the stand."""
    bookings = RailBookingManager(destination_for=lambda stand: DESTINATION)
    service = SimpleNamespace(train_type="IC", number="57", seconds=66000)
    train = SimpleNamespace(service=service, stops=((0.0, 60, "Oulu", 67320, 67380),), manifest={})
    later, sooner = (
        bookings.consider(RailPassenger("Helsinki", "Oulu", ("IC", "57"), ON_TRAIN, name=name, intent=TAXI,
                                        taxi_stand=STAND), train, NOW - timedelta(minutes=22), Always())
        for name in ("Eero Laine", "Aino Virtanen")
    )
    later.arrival_at += timedelta(minutes=30)
    manager = taxi(bookings)
    player = PlayerPedestrian(x=0.0, y=0.0)
    assert manager.meet_prompt(player) is None  # pending: an offer in the phone, not a job yet

    bookings.accept(later)
    assert manager.meet_prompt(player) == (later, "meet_train_due")
    bookings.accept(sooner)
    assert manager.meet_prompt(player) == (sooner, "meet_train_due")  # the next train first
    assert (sooner.passenger.name, sooner.train_number, sooner.station) == ("Aino Virtanen", "IC57", "Oulu")

    sooner.status = TRAIN_ARRIVING
    assert manager.meet_prompt(player) == (sooner, "meet_train_due")
    assert manager.meet_booking() is None  # no card or greeting before they are off the train
