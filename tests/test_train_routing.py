"""Phase 3: station-anchored, track-level train paths (trains.plan_train_path)."""
import math
from datetime import datetime, timedelta

from theroadragetrip.osm.models import Railway
from theroadragetrip.trains import APPROACH_DISTANCE_M, RailwayManager, build_rail_graph, plan_train_path

STATION = (5.0, 10_000.0)


def rail(*points):
    return Railway(points_m=list(points))


def double_track_station(extra=()):
    """Single line from the south, splitting at y=0 into two parallel
    tracks (x=0 west, x=10 east) that rejoin at y=20000; station between."""
    return [
        rail((5.0, -5000.0), (5.0, -100.0)),
        rail((5.0, -100.0), (0.0, 0.0), (0.0, 20_000.0), (5.0, 20_100.0)),
        rail((5.0, -100.0), (10.0, 0.0), (10.0, 20_000.0), (5.0, 20_100.0)),
        rail((5.0, 20_100.0), (5.0, 25_000.0)),
        *extra,
    ]


def track_x_at_station(railways, entry, exit_, stations=(STATION,)):
    route, alongs = plan_train_path(build_rail_graph(railways), entry, exit_, list(stations))
    x, y, _ = route.point_at(alongs[0])
    return round(x), round(y), route


SOUTH, NORTH = (5.0, -5000.0), (5.0, 25_000.0)


def test_opposing_trains_keep_to_their_own_right_hand_track():
    assert track_x_at_station(double_track_station(), SOUTH, NORTH)[:2] == (10, 10_000)  # northbound: east
    assert track_x_at_station(double_track_station(), NORTH, SOUTH)[:2] == (0, 10_000)  # southbound: west


def test_many_parallel_tracks_are_kept_apart():
    middle = rail((5.0, -100.0), (5.0, 0.0), (5.0, 20_000.0), (5.0, 20_100.0))
    x, _, route = track_x_at_station(double_track_station([middle]), SOUTH, NORTH)
    assert x == 10
    # The whole platform stretch stays on that one track: no hopping over.
    assert {round(p[0]) for p in route.points if 1000 < p[1] < 19_000} == {10}


def test_single_track_station_is_used_whatever_the_side():
    line = [rail((5.0, -5000.0), (5.0, 25_000.0))]
    assert track_x_at_station(line, SOUTH, NORTH)[0] == 5
    assert track_x_at_station(line, NORTH, SOUTH)[0] == 5


def test_nearby_but_unconnected_track_is_never_used():
    # x=12 runs right beside the line (the "right" side for northbound)
    # but shares no node with it: proximity is not a connection.
    railways = [rail((5.0, -5000.0), (5.0, 25_000.0)), rail((12.0, 2000.0), (12.0, 18_000.0))]
    x, _, route = track_x_at_station(railways, SOUTH, NORTH)
    assert x == 5 and all(round(p[0]) == 5 for p in route.points)


def test_dead_end_siding_at_the_station_is_not_the_through_route():
    # A siding branches off the single line and ends right at the station;
    # entering it would need reversing back out.
    siding = rail((5.0, 9_000.0), (-5.0, 9_300.0), (-5.0, 10_000.0))
    x, _, route = track_x_at_station([rail((5.0, -5000.0), (5.0, 25_000.0)), siding], SOUTH, NORTH)
    assert x == 5 and min(p[0] for p in route.points) == 5


def test_route_never_reverses_direction():
    _, _, route = track_x_at_station(double_track_station(), SOUTH, NORTH)
    headings = [route.point_at(s)[2] for s in range(0, int(route.length), 50)]
    assert all(abs(math.sin(h) - 1.0) < 0.2 for h in headings)  # always heading north


def test_disconnected_networks_give_no_path():
    railways = [rail((0.0, 0.0), (0.0, 5000.0)), rail((0.0, 6000.0), (0.0, 12_000.0))]
    assert plan_train_path(build_rail_graph(railways), (0.0, 0.0), (0.0, 12_000.0), []) is None


# -- trains on their selected track ----------------------------------------------

def metres(lat, lon):
    return lon * 100_000.0, lat * 100_000.0


def timetable(*trains):
    # S and N are beyond the track ends (not stops here); M is on the line.
    stations = {"S": [-0.2, 0.00005, "South"], "M": [0.1, 0.00005, "Middle"], "N": [0.4, 0.00005, "North"]}
    return {"version": 4, "stations": stations, "trains": list(trains)}


def service(number, calls):
    return {
        "type": "IC", "number": number, "category": "long_distance", "origin": calls[0][0],
        "destination": calls[-1][0], "days": 0b1111111, "stops": [list(c) + [""] * (5 - len(c)) for c in calls],
    }


NORTHBOUND = service("1", [("S", 30000, 30000, 1), ("M", 36000, 36120, 1), ("N", 42000, 42000, 1)])
SOUTHBOUND = service("2", [("N", 30000, 30000, 1), ("M", 36000, 36120, 1), ("S", 42000, 42000, 1)])


def test_train_stops_and_departs_on_its_selected_track():
    manager = RailwayManager(double_track_station(), timetable(NORTHBOUND), metres)
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 10, 1))
    (train,) = manager.trains
    xs = set()
    while train.state != "DWELLING":
        manager.update(0.5, 0.5, datetime(2026, 9, 28, 10, 1))
        xs.add(round(train.cars()[0][0]))
    assert train.next_stop[2] == "Middle"
    for _ in range(300):  # dwell and pull out
        manager.update(0.5, 0.5, datetime(2026, 9, 28, 10, 1))
        xs.add(round(train.cars()[0][0]))
    assert xs == {10} and train.state == "RUNNING"


def test_startup_places_a_train_already_approaching_on_its_track_in_view():
    manager = RailwayManager(double_track_station(), timetable(SOUTHBOUND), metres)
    # 60x game: approach takes ~87 real s = ~87 game minutes. At 09:30 the
    # 10:00 arrival is about a third of the approach away.
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 9, 30))
    (train,) = manager.trains
    x, y, heading = train.cars()[0]
    assert round(x) == 0 and train.state == "RUNNING"  # southbound, west track
    assert 10_000 < y < 10_000 + APPROACH_DISTANCE_M  # north of the station, closing in
    assert abs(math.sin(heading) + 1.0) < 0.2  # heading south


def test_startup_places_a_train_at_its_platform_mid_dwell():
    manager = RailwayManager(double_track_station(), timetable(NORTHBOUND), metres)
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 10, 1))  # 1 game minute into its 2 min dwell
    (train,) = manager.trains
    assert train.state == "DWELLING" and 55 < train.dwell_remaining_s < 65
    assert round(train.cars()[0][0]) == 10


def test_startup_skips_trains_that_already_left():
    manager = RailwayManager(double_track_station(), timetable(NORTHBOUND), metres)
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 13, 0))  # 3 game h after arrival: dwell long over
    assert manager.trains == []


def test_track_streaming_in_does_not_place_trains_again():
    railways = double_track_station()
    manager = RailwayManager(railways, timetable(NORTHBOUND), metres)
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 10, 1))  # placed mid-dwell at start
    assert len(manager.trains) == 1
    manager.rebuild(railways + [rail((50.0, 0.0), (50.0, 3000.0))])
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 10, 1, 2))
    assert len(manager.trains) == 1


def test_timetable_platform_picks_its_numbered_track_over_the_right_hand_rule():
    # OSM railway:track_ref on the two station tracks: east = 7, west = 8.
    railways = double_track_station()
    railways[1].track_ref, railways[2].track_ref = "8", "7"
    graph = build_rail_graph(railways)
    route, (along,) = plan_train_path(graph, SOUTH, NORTH, [STATION], ["8"])
    assert round(route.point_at(along)[0]) == 0  # northbound, but platform 8 is the west track
    route, (along,) = plan_train_path(graph, SOUTH, NORTH, [STATION], ["99"])  # unknown track
    assert round(route.point_at(along)[0]) == 10  # falls back to the right-hand track


def test_trains_on_different_platforms_stand_on_different_tracks():
    railways = double_track_station()
    railways[1].track_ref, railways[2].track_ref = "8", "7"
    on_7 = service("1", [("S", 30000, 30000, 1), ("M", 36000, 36600, 1, "7"), ("N", 42000, 42000, 1)])
    on_8 = service("3", [("S", 30060, 30060, 1), ("M", 36060, 36660, 1, "8"), ("N", 42060, 42060, 1)])
    manager = RailwayManager(railways, timetable(on_7, on_8), metres)
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 10, 2))  # game start: both standing at M
    assert sorted(round(train.cars()[0][0]) for train in manager.trains) == [0, 10]


# -- journeys ending / starting at a terminus (e.g. Helsinki) ----------------------

TERMINUS_LINE = [rail((5.0, -5000.0), (5.0, 10_050.0))]  # dead end just past the station at y=10 km


def test_train_terminating_at_a_dead_end_arrives_dwells_and_leaves_backwards():
    ending = service("5", [("S", 30000, 30000, 1), ("M", 36000, 36000, 1)])  # M is its terminus
    manager = RailwayManager(TERMINUS_LINE, timetable(ending), metres)
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 10, 1))
    (train,) = manager.trains
    assert train.stops and train.stops[-1][7] == "terminus"
    states = []
    for _ in range(4000):
        manager.update(0.5, 0.5, datetime(2026, 9, 28, 10, 1))
        if not manager.trains:
            break
        states.append((train.state, train.direction))
        head_y = max(car[1] for car in train.cars())
        assert head_y <= 10_050.5  # never runs off the dead end
    assert ("DWELLING", 1) in states and states[-1] == ("RUNNING", -1)  # reversed after the dwell
    assert manager.trains == []  # left the map at the far (south) end


def test_train_starting_at_a_terminus_drives_in_empty_then_departs_on_time():
    starting = service("6", [("M", 36000, 36000, 1), ("S", 42000, 42000, 1)])  # departs M at 10:00
    manager = RailwayManager(TERMINUS_LINE, timetable(starting), metres)
    now = datetime(2026, 9, 28, 8, 0)
    manager.update(1 / 30, 2.0, now)  # 60x clock
    first_seen, dwelling_at, departed_at = None, None, None
    while now < datetime(2026, 9, 28, 11, 0) and departed_at is None:
        now += timedelta(seconds=2)
        manager.update(1 / 30, 2.0, now)
        if manager.trains and first_seen is None:
            first_seen = [car[1] for car in manager.trains[0].cars()]
        if manager.trains:
            train = manager.trains[0]
            if train.state == "DWELLING" and train.service.stops[0][7] == "origin" and dwelling_at is None:
                dwelling_at = now
            if dwelling_at is not None and train.state == "RUNNING":
                departed_at = now
    assert first_seen is not None and max(first_seen) < 9_000  # appeared well away from the platform (not under the roof)
    assert dwelling_at is not None and dwelling_at < datetime(2026, 9, 28, 10, 0)
    assert departed_at is not None and abs((departed_at - datetime(2026, 9, 28, 10, 0)).total_seconds()) < 5 * 60

def test_arrived_train_waits_on_its_platform_and_becomes_the_next_departure_from_that_track():
    arriving = service("5", [("S", 30000, 30000, 1), ("M", 36000, 36000, 1, "3")])  # ends at M track 3
    other_track = service("7", [("M", 37000, 37000, 1, "4"), ("S", 43000, 43000, 1)])
    same_track = service("6", [("M", 38000, 38000, 1, "3"), ("S", 44000, 44000, 1)])  # 10:33 from track 3
    manager = RailwayManager(TERMINUS_LINE, timetable(arriving, other_track, same_track), metres)
    now = datetime(2026, 9, 28, 10, 1)
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
    manager.update(0.0, 0.0, now)
    (train,) = manager.trains
    for _ in range(2000):  # arrive and dwell (clock stands still: game time frozen)
        manager.update(0.5, 0.5, now)
    assert train.state == "WAITING" and train.waiting_for[1].number == "6"  # not 7: other track
    parked = train.cars()
    for minute in range(1, 60):  # game clock runs on to 11:00; train 7 appears on its own
        manager.update(0.0, 0.0, now + timedelta(minutes=minute))
    assert train in manager.trains and train.service.number == "6"  # same train, new identity
    assert train.state == "DWELLING" and train.stops[0][7] == "origin"
    assert {round(y) for _, y, _ in train.cars()} == {round(y) for _, y, _ in parked}  # did not move
    assert sorted(t.service.number for t in manager.trains) == ["6", "7"]  # 6 was not spawned anew


def test_arrived_train_with_no_next_departure_from_its_track_drives_out():
    arriving = service("5", [("S", 30000, 30000, 1), ("M", 36000, 36000, 1, "3")])
    manager = RailwayManager(TERMINUS_LINE, timetable(arriving), metres)
    now = datetime(2026, 9, 28, 10, 1)
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
    manager.update(0.0, 0.0, now)
    for _ in range(4000):
        manager.update(0.5, 0.5, now)
    assert manager.trains == []


def test_occupied_platform_sends_the_arriving_train_to_the_next_free_track():
    railways = double_track_station()
    railways[1].track_ref, railways[2].track_ref = "8", "7"  # west 8, east 7
    first = service("1", [("S", 30000, 30000, 1), ("M", 36000, 37800, 1, "7"), ("N", 42000, 42000, 1)])
    second = service("3", [("S", 30600, 30600, 1), ("M", 36600, 37900, 1, "7"), ("N", 42600, 42600, 1)])
    manager = RailwayManager(railways, timetable(first, second), metres)
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 10, 11))  # game start: both due at M
    tracks = {train.service.number: train.stops[0][6] for train in manager.trains}
    assert tracks == {"1": "7", "3": "8"}
    xs = sorted(round(train.cars()[0][0]) for train in manager.trains)
    assert xs == [0, 10]  # side by side, not on top of each other


def test_next_arrival_names_the_platform_track():
    railways = double_track_station()
    railways[2].track_ref = "7"
    arriving = service("1", [("S", 30000, 30000, 1), ("M", 36000, 36120, 1, "7"), ("N", 42000, 42000, 1)])
    manager = RailwayManager(railways, timetable(arriving), metres)
    when, call = manager.next_arrival(*STATION, datetime(2026, 9, 28, 9, 0))
    assert (call.station, call.track, when) == ("Middle", "7", datetime(2026, 9, 28, 10, 0))


def test_terminating_train_runs_up_to_the_buffer_stop_else_stands_centred():
    ending = service("5", [("S", 30000, 30000, 1), ("M", 36000, 36000, 1)])
    through = service("8", [("S", 30000, 30000, 1), ("M", 36000, 36120, 1), ("N", 42000, 42000, 1)])
    cases = (
        (ending, [rail((5.0, -5000.0), (5.0, 10_300.0))], "buffer"),  # dead end 300 m past the platform point
        (ending, [rail((5.0, -5000.0), (5.0, 25_000.0))], "centred"),  # terminates at a through station
        (through, double_track_station(), "centred"),
    )
    for journey, track, expected in cases:
        manager = RailwayManager(track, timetable(journey), metres)
        manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 10, 0, 30))  # game start: standing at M
        (train,) = manager.trains
        ys = [car[1] for car in train.cars()]
        if expected == "buffer":
            assert abs(ys[0] + 12.0 - 10_300) < 1  # locomotive's nose at the buffer stop
        else:
            assert abs((ys[0] + ys[-1]) / 2 - 10_000) < 15, journey["number"]


def test_departure_from_a_dead_end_swaps_the_train_ends_in_place():
    line = [rail((5.0, -5000.0), (5.0, 10_300.0))]  # buffer stop 300 m past the platform point
    arriving = service("5", [("S", 30000, 30000, 1), ("M", 36000, 36000, 1, "3")])
    departing = service("6", [("M", 38000, 38000, 1, "3"), ("S", 44000, 44000, 1)])
    manager = RailwayManager(line, timetable(arriving, departing), metres)
    now = datetime(2026, 9, 28, 10, 1)
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
    manager.update(0.0, 0.0, now)
    (train,) = manager.trains
    for _ in range(2000):
        manager.update(0.5, 0.5, now)
    assert train.state == "WAITING"
    before = train.cars()
    for minute in range(1, 60):
        manager.update(0.0, 0.0, now + timedelta(minutes=minute))
    after = train.cars()
    assert train.service.number == "6"
    # Same car positions, locomotive now at the other end (no squashing).
    assert [round(y) for _, y, _ in after] == [round(y) for _, y, _ in reversed(before)]
