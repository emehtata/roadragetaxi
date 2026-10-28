"""tools/lam_profiles.py (docs/lam-traffic-audit.md phases 0-1): raw LAM detections to hourly curves."""
import importlib.util
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location("lam_profiles", Path(__file__).parents[1] / "tools" / "lam_profiles.py")
lam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lam)


def _row(hour, direction, vehicle_class=1, faulty=0):
    # station;yy;day;hour;min;sec;1/100;length;lane;direction;class;speed;faulty;...
    return f"21205;26;294;{hour};1;32;286;4.900;1;{direction};{vehicle_class};114;{faulty};92286;1;0"


def test_valid_detections_are_counted_by_local_hour_and_direction_every_class_included():
    csv = "\n".join([_row(7, 1), _row(7, 1, vehicle_class=9), _row(7, 2, vehicle_class=8),
                     _row(7, 1, faulty=1), _row(23, 2), "garbage"])
    counts = lam.hourly_counts(csv)
    assert counts["1"][7] == 2 and counts["2"][7] == 1 and counts["2"][23] == 1
    assert sum(counts["1"]) + sum(counts["2"]) == 4  # the faulty record and the junk line left out


def test_curves_are_shares_of_the_average_weekday_peak_and_months_of_their_mean():
    def day(peak_hour, size):
        counts = {"1": [0] * 24, "2": [0] * 24}
        counts["1"][peak_hour] = size
        counts["2"][peak_hour] = size
        return counts

    days = {date(2026, 1, 19): day(16, 50), date(2026, 1, 20): day(16, 150),  # Mon, Tue: 200 at 16 on average
            date(2026, 7, 13): day(16, 50),  # a July Monday: 100
            date(2026, 1, 24): day(13, 60)}  # Saturday
    profile = lam.profile(days)
    assert profile["weekday_peak_vehicles_per_hour"] == 167  # (100 + 300 + 100) / 3
    assert profile["weekday_hourly"][16] == 1.0 and profile["weekend_hourly"][13] == round(120 / (500 / 3), 3)
    assert profile["weekday_hourly_direction"]["1"][16] == 0.5
    assert profile["month_factor"] == {"1": round(200 / 150, 3), "7": round(100 / 150, 3)}
    assert profile["days_used"] == {"weekday": 3, "weekend": 1}


def _way(way_id, points, **tags):
    # points in metres; the test projection maps lon/lat 1:1 to metres / 1e5
    return {"id": way_id, "tags": {"highway": "trunk", **tags}, "geometry": [{"lon": x / 1e5, "lat": y / 1e5} for x, y in points]}


def _match(ways, bearing=0, road_number=4):
    meta = {"lon": 0.0, "lat": 0.0, "bearing": bearing, "road_number": road_number}
    return lam.match_station(meta, ways, lambda lon, lat: (lon * 1e5, lat * 1e5))


def test_a_two_way_road_maps_its_forward_travel_to_the_direction_its_bearing_names():
    northward = _way(1, [(0, -100), (0, 100)], ref="4;E8")
    assert _match([northward])["ways"][0] == {"osm_id": 1, "highway": "trunk", "name": None, "ref": "4;E8",
                                               "distance_m": 0.0, "forward": "1", "backward": "2"}
    assert _match([northward], bearing=180)["ways"][0]["forward"] == "2"


def test_a_divided_road_keeps_both_carriageways_each_one_way():
    north = _way(1, [(-8, -100), (-8, 100)], ref="4", oneway="yes")
    south = _way(2, [(8, 100), (8, -100)], ref="4", oneway="yes")
    ways = {w["osm_id"]: w for w in _match([north, south], bearing=5)["ways"]}
    assert ways[1]["forward"] == "1" and ways[2]["forward"] == "2" and ways[1]["backward"] is ways[2]["backward"] is None


def test_uncertain_stations_are_rejected_with_their_reason():
    road = _way(1, [(0, -100), (0, 100)], ref="4")
    assert "no ref 4" in _match([_way(1, [(0, -100), (0, 100)], ref="20")])["reason"]
    assert "no ref 4" in _match([_way(1, [(60, -100), (60, 100)], ref="4")])["reason"]  # too far
    assert "heading" in _match([road], bearing=90)["reason"]  # the station measures a crossing road
    frontage = _way(2, [(6, -100), (6, 100)], highway="tertiary", name="Service road")
    assert "parallel tertiary way 2" in _match([road, frontage])["reason"]
    assert _match([road, _way(3, [(-100, 30), (100, 30)], highway="tertiary")])["status"] == "matched"  # crossing: fine
    assert _match([road], bearing=None)["status"] == "rejected"
