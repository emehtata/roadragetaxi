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
        "version": 1,
        "stations": stations or {"S": [0.0, 0.0], "N": [0.2, 0.0], "W": [0.1, -0.1], "E": [0.1, 0.1]},
        "trains": list(trains),
    }


def train(stops, number="1", days=0b1111111, kind="IC"):
    return {"type": kind, "number": number, "origin": stops[0][0], "destination": stops[-1][0], "days": days, "stops": [list(s) for s in stops]}


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
    far = timetable(train([("A", 36000), ("B", 37000)]), stations={"A": [5.0, 5.0], "B": [5.2, 5.0]})
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
    many = [train([("S", 36000 + i * 60), ("N", 37000 + i * 60)], number=str(i)) for i in range(40)]
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
        "stops.txt": [["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station"],
                      ["HKI", "Helsinki", "60.17", "24.94", "1", ""], ["HKI_1", "Helsinki", "60.17", "24.94", "0", "HKI"],
                      ["OL", "Oulu", "65.01", "25.48", "1", ""], ["OL_2", "Oulu", "65.01", "25.48", "0", "OL"]],
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
    assert document["stations"] == {"HKI": [60.17, 24.94], "OL": [65.01, 25.48]}  # platforms -> station
    by_number = {t["number"]: t for t in document["trains"]}
    assert by_number["21"]["days"] == 0b1111011  # weekdays+weekend merged, Wednesday cancelled
    assert by_number["21"]["type"] == "IC" and by_number["21"]["origin"] == "Helsinki"
    assert by_number["8193"]["type"] == "A" and by_number["8193"]["stops"][1] == ["OL", 24 * 3600 + 600]


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
