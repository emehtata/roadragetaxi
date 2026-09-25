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
    return {"version": 3, "stations": stations, "trains": list(trains)}


def service(number, calls):
    return {
        "type": "IC", "number": number, "category": "long_distance", "origin": calls[0][0],
        "destination": calls[-1][0], "days": 0b1111111, "stops": [list(c) for c in calls],
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
        manager.update(0.5, 0.0, datetime(2026, 9, 28, 10, 1))
        xs.add(round(train.cars()[0][0]))
    assert train.next_stop[2] == "Middle"
    for _ in range(300):  # dwell and pull out
        manager.update(0.5, 0.0, datetime(2026, 9, 28, 10, 1))
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
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 10, 0) + timedelta(minutes=60))  # 60 game min = 60 real s into its 120 s dwell
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
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 11, 0))  # placed mid-dwell at start
    assert len(manager.trains) == 1
    manager.rebuild(railways + [rail((50.0, 0.0), (50.0, 3000.0))])
    manager.update(1 / 30, 2.0, datetime(2026, 9, 28, 11, 0, 2))
    assert len(manager.trains) == 1
