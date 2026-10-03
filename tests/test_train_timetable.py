import csv
import gzip
import io
import json
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_railway_timetable as importer  # noqa: E402
from theroadragetrip.osm.models import Railway  # noqa: E402
from theroadragetrip.train_timetable import TimetableClock, load_timetable, match_timetable, service_time  # noqa: E402
from theroadragetrip.trains import MAX_ACTIVE_TRAINS, RailwayManager  # noqa: E402

MONDAY = date(2026, 9, 28)


def metres(lat, lon):
    """Toy projection: 1 degree = 100 km both ways, y north, x east."""
    return lon * 100_000.0, lat * 100_000.0


def timetable(*trains, stations=None):
    return {
        "version": 4,
        "stations": stations or {"S": [0.0, 0.0, "South"], "N": [0.2, 0.0, "North"], "W": [0.1, -0.1, "West"], "E": [0.1, 0.1, "East"]},
        "trains": list(trains),
    }


def train(stops, number="1", days=0b1111111, kind="IC", category="long_distance"):
    """stops: (code, time) = a stop, or (code, arrival, departure[, stops_here])."""
    calls = []
    for stop in stops:
        code, arrival = stop[0], stop[1]
        departure = stop[2] if len(stop) > 2 else arrival
        calls.append([code, arrival, departure, stop[3] if len(stop) > 3 else 1, stop[4] if len(stop) > 4 else ""])
    return {
        "type": kind, "number": number, "category": category, "origin": stops[0][0], "destination": stops[-1][0],
        "days": days, "stops": calls,
    }


NORTH_SOUTH_TRACK = [Railway(points_m=[(0.0, 5_000.0), (0.0, 15_000.0)])]  # route start = south end
EAST_WEST_TRACK = [Railway(points_m=[(5_000.0, 10_000.0), (-5_000.0, 10_000.0)])]  # route start = east end


def run(manager, start, minutes, step_s=60):
    """Advance the game clock minute by minute; trains barely move (dt 0)."""
    manager.update(0.0, 0.0, start)
    now = start
    for _ in range(minutes):
        now += timedelta(seconds=step_s)
        manager.update(0.0, 0.0, now)
    return now


def test_no_railway_means_no_trains_even_with_a_timetable():
    manager = RailwayManager([], timetable(train([("S", 36000), ("N", 37000)])), metres)
    run(manager, datetime(2026, 9, 28, 9, 0), 180)
    assert manager.routes == [] and manager.trains == []


def test_timetable_trains_elsewhere_never_spawn():
    far = timetable(train([("A", 36000), ("B", 37000)]), stations={"A": [5.0, 5.0, "A"], "B": [5.2, 5.0, "B"]})
    manager = RailwayManager(NORTH_SOUTH_TRACK, far, metres)
    run(manager, datetime(2026, 9, 28, 9, 0), 180)
    assert manager.trains == []


def test_northbound_enters_south_and_southbound_enters_north():
    north = train([("S", 36000), ("N", 36000 + 1000)], number="N1")
    south = train([("N", 43200), ("S", 43200 + 1000)], number="S1")
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(north, south), metres)
    run(manager, datetime(2026, 9, 28, 9, 0), 70)  # to 10:10 (midpoint at 10:08:20)
    (northbound,) = manager.trains
    assert northbound.service.number == "N1" and northbound.service.heading == "N"
    assert northbound.route.point_at(northbound.distance_m)[1] < 6_000  # at the south end
    run(manager, datetime(2026, 9, 28, 10, 0), 180)  # to 13:00
    southbound = manager.trains[-1]
    assert southbound.service.heading == "S" and southbound.route.point_at(southbound.distance_m)[1] > 14_000


def test_east_west_lines_are_not_assumed_north_south():
    westbound = train([("E", 36000), ("W", 37000)], number="W1")
    manager = RailwayManager(EAST_WEST_TRACK, timetable(westbound), metres)
    run(manager, datetime(2026, 9, 28, 9, 50), 20)
    (train_,) = manager.trains
    assert train_.service.heading == "W"
    assert train_.route.point_at(train_.distance_m)[0] > 4_000  # entered at the east end


def test_spawn_time_is_the_time_at_the_route_midpoint():
    # Midpoint y=10 km is half way S (0) -> N (20 km): 10:00 + 500 s = 10:08:20.
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(train([("S", 36000), ("N", 37000)])), metres)
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 10, 7))
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 10, 8))
    assert manager.trains == []
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 10, 9))
    assert len(manager.trains) == 1


def test_monday_only_service_does_not_run_on_sunday():
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(train([("S", 36000), ("N", 37000)], days=0b0000001)), metres)
    run(manager, datetime(2026, 10, 4, 9, 0), 180)  # Sunday
    assert manager.trains == []
    run(manager, datetime(2026, 10, 5, 9, 0), 180)  # Monday
    assert len(manager.trains) == 1


def test_past_midnight_service_runs_on_the_next_calendar_day():
    late = train([("S", 24 * 3600), ("N", 24 * 3600 + 1000)], days=0b0000001)  # Monday service, 00:08 Tuesday
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(late), metres)
    run(manager, datetime(2026, 9, 28, 23, 50), 30)  # Mon 23:50 -> Tue 00:20
    assert len(manager.trains) == 1
    manager.trains.clear()
    run(manager, datetime(2026, 9, 29, 23, 50), 30)  # Tuesday service would be needed: none
    assert manager.trains == []


def test_finnish_local_time_across_dst_changes():
    # GTFS times count from local noon - 12 h, in Europe/Helsinki.
    assert service_time(date(2026, 3, 29), 12 * 3600) == datetime(2026, 3, 29, 12, 0)  # EET -> EEST day
    assert service_time(date(2026, 10, 25), 18 * 3600) == datetime(2026, 10, 25, 18, 0)  # EEST -> EET day
    assert service_time(date(2026, 7, 1), 25 * 3600 + 60) == datetime(2026, 7, 2, 1, 1)
    assert service_time(date(2026, 1, 15), 8 * 3600) == datetime(2026, 1, 15, 8, 0)


def test_timetable_train_leaves_at_the_far_end_instead_of_reversing():
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(train([("S", 36000), ("N", 37000)])), metres)
    run(manager, datetime(2026, 9, 28, 10, 0), 10)
    assert len(manager.trains) == 1
    for _ in range(600):
        manager.update(1.0, 0.0, datetime(2026, 9, 28, 10, 10))
    assert manager.trains == []


def test_many_scheduled_trains_stay_capped():
    many = [train([("S", 36000 + i * 60), ("N", 37000 + i * 60)], number=str(i)) for i in range(MAX_ACTIVE_TRAINS + 10)]
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(*many), metres)
    run(manager, datetime(2026, 9, 28, 10, 0), 60)
    assert len(manager.trains) == MAX_ACTIVE_TRAINS


def test_clock_counts_todays_trains_and_ignores_a_first_call_backlog():
    passes = match_timetable(timetable(train([("S", 36000), ("N", 37000)], days=0b0011111)), [
        RailwayManager(NORTH_SOUTH_TRACK).routes[0]
    ], metres)
    clock = TimetableClock(passes)
    assert clock.todays_count(datetime(2026, 9, 28, 1)) == 1 and clock.todays_count(datetime(2026, 10, 3, 1)) == 0
    assert clock.due(datetime(2026, 9, 28, 23)) == []  # starting late: no burst of the day's trains


# -- importer -----------------------------------------------------------------

def _gtfs_zip() -> bytes:
    files = {
        "feed_info.txt": [["feed_publisher_name", "feed_start_date", "feed_end_date", "feed_version"], ["Fintraffic", "20260918", "20261231", "v1"]],
        "calendar.txt": [
            ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
            ["weekdays", "1", "1", "1", "1", "1", "0", "0", "20260918", "20261231"],
            ["weekend", "0", "0", "0", "0", "0", "1", "1", "20260918", "20261231"],
        ],
        "calendar_dates.txt": [["service_id", "date", "exception_type"], ["weekdays", "20260930", "2"]],  # no Wednesday
        "routes.txt": [["route_id", "agency_id", "route_short_name", "route_long_name", "route_desc", "route_type"],
                       ["R1", "10", "IC 21", "Helsinki - Oulu", "", "102"], ["R2", "10", "A", "Leppävaara", "", "109"]],
        "trips.txt": [["route_id", "service_id", "trip_id", "trip_headsign", "trip_short_name"],
                      ["R1", "weekdays", "t1", "Oulu", "IC 21"], ["R1", "weekend", "t2", "Oulu", "IC 21"],
                      ["R2", "weekdays", "t3", "Leppävaara", "A (HL 8193)"]],
        "stops.txt": [["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station", "platform_code"],
                      ["HKI", "Helsinki", "60.17", "24.94", "1", "", ""], ["HKI_1", "Helsinki", "60.1702", "24.9401", "0", "HKI", "1"],
                      ["OL", "Oulu", "65.01", "25.48", "1", "", ""], ["OL_2", "Oulu", "65.0101", "25.4802", "0", "OL", "2"]],
        "stop_times.txt": [["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
                           ["t1", "07:00:00", "07:00:00", "HKI_1", "0"], ["t1", "13:00:00", "13:00:00", "OL_2", "1"],
                           ["t2", "07:00:00", "07:00:00", "HKI_1", "0"], ["t2", "13:00:00", "13:00:00", "OL_2", "1"],
                           ["t3", "23:50:00", "23:50:00", "HKI_1", "0"], ["t3", "24:10:00", "24:10:00", "OL_2", "1"]],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, rows in files.items():
            text = io.StringIO()
            csv.writer(text).writerows(rows)
            archive.writestr(name, text.getvalue())
    return buffer.getvalue()


def test_importer_builds_weekly_masks_identities_and_merges_duplicate_runs():
    document = importer.convert(_gtfs_zip(), today=date(2026, 9, 25), downloaded_at="2026-09-25T00:00:00Z")
    assert document["reference_week"] == MONDAY.isoformat()
    # Platforms -> station; each matched by station code to the OSM station
    # in the committed places.json (its coordinates appended).
    assert document["stations"] == {
        "HKI": [60.17, 24.94, "Helsinki", 60.172097, 24.941249],
        "OL": [65.01, 25.48, "Oulu", 65.011332, 25.484336],
    }
    by_number = {t["number"]: t for t in document["trains"]}
    assert by_number["21"]["days"] == 0b1111011  # weekdays+weekend merged, Wednesday cancelled
    assert by_number["21"]["type"] == "IC" and by_number["21"]["origin"] == "Helsinki"
    assert (by_number["21"]["category"], by_number["8193"]["category"]) == ("long_distance", "commuter")
    # Platform (track) codes per call and their positions per station.
    assert by_number["21"]["stops"][0][4] == "1"
    assert document["platforms"] == {"HKI": {"1": [60.1702, 24.9401]}, "OL": {"2": [65.0101, 25.4802]}}
    assert by_number["8193"]["type"] == "A" and by_number["8193"]["stops"][1] == ["OL", 24 * 3600 + 600, 24 * 3600 + 600, 1, "2"]


def test_offline_game_uses_the_stored_file_and_a_failed_import_keeps_it(tmp_path, capsys):
    output = tmp_path / "railway_timetable.json.gz"
    source = tmp_path / "gtfs.zip"
    source.write_bytes(_gtfs_zip())
    assert importer.main(["--zip", str(source), str(output)]) == 0
    stored = output.read_bytes()
    assert load_timetable(output)["valid_until"] == "2026-12-31"  # no network needed to load

    source.write_bytes(b"not a zip")  # e.g. a failed / truncated download
    assert importer.main(["--zip", str(source), str(output)]) == 1
    assert "keeping the existing timetable" in capsys.readouterr().err
    assert output.read_bytes() == stored
    assert load_timetable(tmp_path / "missing.json.gz") is None


def test_committed_timetable_loads():
    document = load_timetable()
    assert document is not None and len(document["trains"]) > 500
    json.dumps(document["trains"][0])


def test_next_train_is_the_next_scheduled_pass_even_after_midnight():
    route = RailwayManager(NORTH_SOUTH_TRACK).routes[0]
    passes = match_timetable(timetable(
        train([("S", 36000), ("N", 37000)], number="10"),  # 10:08:20 daily
        train([("N", 25 * 3600), ("S", 25 * 3600 + 1000)], number="99"),  # 01:08:20 next day
    ), [route], metres)
    clock = TimetableClock(passes)
    when, service = clock.next_after(datetime(2026, 9, 28, 9, 0))
    assert (when, service.number) == (datetime(2026, 9, 28, 10, 8, 20), "10")
    when, service = clock.next_after(datetime(2026, 9, 28, 23, 0))
    assert (when, service.number) == (datetime(2026, 9, 29, 1, 8, 20), "99")


def test_commuter_trains_are_not_followed():
    commuter = train([("S", 36000), ("N", 37000)], number="8193", kind="A", category="commuter")
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(commuter), metres)
    run(manager, datetime(2026, 9, 28, 9, 0), 180)
    assert manager.trains == [] and manager.stations == []


def test_next_arrival_is_for_the_station_nearest_the_driver():
    # Stations "M1" (y=6 km) and "M2" (y=14 km) lie on the track; the
    # northbound train stops at both, the southbound one starts at M2.
    stations = {"S": [0.0, 0.0, "South"], "M1": [0.06, 0.0, "Alpha"], "M2": [0.14, 0.0, "Beta"], "N": [0.2, 0.0, "North"]}
    north = train([("S", 36000), ("M1", 36600), ("M2", 37800), ("N", 38400)], number="N1")
    south = train([("M2", 39000), ("M1", 40000), ("S", 41000)], number="S1")
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(north, south, stations=stations), metres)
    assert sorted(station[0] for station in manager.stations) == ["Alpha", "Beta"]

    when, call = manager.next_arrival(0.0, 13_000.0, datetime(2026, 9, 28, 9, 0))  # driver near Beta
    assert (call.station, call.number, when) == ("Beta", "N1", datetime(2026, 9, 28, 10, 30))
    assert manager.next_arrival(0.0, 13_000.0, datetime(2026, 9, 28, 10, 31)) is not None
    assert manager.next_arrival(0.0, 13_000.0, datetime(2026, 9, 28, 10, 31))[1].number == "N1"  # next day's run; S1 starts at Beta
    when, call = manager.next_arrival(0.0, 7_000.0, datetime(2026, 9, 28, 10, 20))  # near Alpha
    assert (call.station, call.number, when) == ("Alpha", "S1", datetime(2026, 9, 28, 11, 6, 40))


def test_gtfs_stations_match_osm_by_code_then_proximity_but_not_far_away():
    osm = [
        {"type": "railway_station", "name": "Oulu", "lat": 65.0113, "lon": 25.4843, "station_code": "Ol"},
        {"type": "railway_station", "name": "Kempele", "lat": 64.9120, "lon": 25.5080},
    ]
    assert importer._match_osm("OL", 65.0120, 25.4850, osm) == (65.0113, 25.4843)  # code, ~80 m off
    assert importer._match_osm("KML", 64.9150, 25.5090, osm) == (64.9120, 25.5080)  # no code: nearest, ~340 m
    assert importer._match_osm("HVN", 64.60, 25.40, osm) is None  # a timing point far from any station


# -- station stops and dwell ------------------------------------------------------

STOP_STATIONS = {"S": [0.0, 0.0, "South"], "M": [0.1, 0.0, "Middle"], "N": [0.2, 0.0, "North"]}


def _stopping_train(dwell_s=120, stops_at_middle=1):
    # Northbound S -> M -> N; M (y = 10 km) is the middle of the track.
    return train([("S", 30000), ("M", 36000, 36000 + dwell_s, stops_at_middle), ("N", 42000)], number="7")


def _run_until_dwelling(manager, now, game_dt=0.0, limit_s=2000):
    for step in range(limit_s * 10):
        manager.update(0.1, game_dt, now)
        (train_,) = manager.trains
        if train_.state == "DWELLING":
            return train_, step / 10
    raise AssertionError("train never stopped")


def _spawned(manager):
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 6, 0))
    manager.update(0.0, 0.0, datetime(2026, 9, 28, 10, 5))  # first stop's arrival passed
    assert len(manager.trains) == 1
    return datetime(2026, 9, 28, 10, 5)


def test_train_stops_centred_at_its_station_dwells_and_pulls_away_smoothly():
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(_stopping_train(), stations=STOP_STATIONS), metres)
    now = _spawned(manager)
    train_, _ = _run_until_dwelling(manager, now)
    cars = train_.cars()
    assert abs((cars[0][1] + cars[-1][1]) / 2 - 10_000) < 15  # train centred on the station
    assert train_.next_stop[2] == "Middle" and train_.current_speed_mps == 0.0
    stopped_at = train_.distance_m
    for _ in range(1190):  # 119 s: still at the platform
        manager.update(0.1, 0.1, now)
    assert train_.state == "DWELLING" and train_.distance_m == stopped_at
    positions = []
    for _ in range(200):  # dwell over: accelerate away without a jump
        manager.update(0.1, 0.1, now)
        positions.append(train_.distance_m)
    assert train_.state == "RUNNING" and train_.next_stop is None  # North is beyond the track: leaving
    steps = [b - a for a, b in zip([stopped_at] + positions, positions)]
    assert all(0.0 <= step <= 22 * 0.1 + 1e-9 for step in steps)  # never backwards, never a jump
    assert steps[1] < 0.1 and steps[-1] > 10 * steps[1]  # starts slowly, speeds up


def test_dwell_follows_the_game_clock():
    """A 2 min timetable dwell is 2 game minutes: 2 real seconds at 60x,
    the full 120 s at 1x (a fare aboard)."""
    for game_seconds_per_real_second, real_seconds in ((60.0, 2.0), (1.0, 120.0)):
        manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(_stopping_train(), stations=STOP_STATIONS), metres)
        now = _spawned(manager)
        train_, _ = _run_until_dwelling(manager, now, game_dt=0.1 * game_seconds_per_real_second)
        dwelt = 0.0
        while train_.state == "DWELLING":
            now += timedelta(seconds=0.1 * game_seconds_per_real_second)
            manager.update(0.1, 0.1 * game_seconds_per_real_second, now)
            dwelt += 0.1
        assert abs(dwelt - real_seconds) < 0.2, (game_seconds_per_real_second, dwelt)

def test_passing_timing_points_and_zero_dwell_do_not_stop_but_termini_do():
    passing = RailwayManager(NORTH_SOUTH_TRACK, timetable(_stopping_train(stops_at_middle=0), stations=STOP_STATIONS), metres)
    _spawned(passing)
    assert [stop[2] for stop in passing.trains[0].service.stops] == []  # S/N termini are off the track

    stations = {"S": [0.05, 0.0, "South"], "M": [0.1, 0.0, "Middle"], "N": [0.15, 0.0, "North"]}  # all on the track
    through = RailwayManager(NORTH_SOUTH_TRACK, timetable(_stopping_train(dwell_s=0), stations=stations), metres)
    _spawned(through)
    stops = through.trains[0].service.stops
    assert [(stop[2], stop[1]) for stop in stops] == [("South", 120), ("North", 120)]  # termini dwell, 0 s M not


def test_train_reaches_its_station_at_the_scheduled_game_time_at_60x():
    """Trains move in real time, the clock at 60x: the train must be
    spawned early enough to stand at the platform when the game clock
    shows its arrival (10:00), not hours later."""
    manager = RailwayManager(NORTH_SOUTH_TRACK, timetable(_stopping_train(), stations=STOP_STATIONS), metres)
    now = datetime(2026, 9, 28, 8, 0)
    arrived_at = None
    for _ in range(40_000):  # 1/30 s frames, 60 game seconds per real second
        now += timedelta(seconds=2)
        manager.update(1 / 30, 2.0, now)
        if manager.trains and manager.trains[0].state == "DWELLING":
            arrived_at = now
            break
    assert arrived_at is not None
    assert abs((arrived_at - datetime(2026, 9, 28, 10, 0)).total_seconds()) < 3 * 60
    assert manager.trains[0].distance_m > 0.0  # it came from the south end's side, not mid-platform
