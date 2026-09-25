#!/usr/bin/env python3
"""Import Finland's passenger-train timetable (Digitraffic GTFS) into the
compact weekly timetable the game reads (theroadragetrip.train_timetable).

    python tools/import_railway_timetable.py [--zip gtfs-passenger.zip] [OUTPUT]

Stations are matched to OSM railway stations from the committed
assets/places.json (station code, else nearest within 1 km) so trains stop
at the mapped station. Downloads
https://rata.digitraffic.fi/api/v1/trains/gtfs-passenger.zip
(~6 MB) unless --zip is given. Run it whenever a newer timetable is
wanted; the game itself never downloads anything and plays offline. If the
download fails, the existing file is left untouched and the error printed.

Weekly model: one reference Monday-Sunday week inside the feed is taken,
and every trip running on some day of it becomes one entry with a 7-day
mask from GTFS calendar.txt + calendar_dates.txt (never guessed). Each call
keeps arrival, departure and whether the train stops there (GTFS pickup/
drop-off types), with times exactly as GTFS gives them: seconds after the
service day's local "noon minus 12 h", which may exceed 24 h for trips past
midnight. Each train keeps its GTFS category
(long_distance / commuter) so the game can choose which to follow.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

GTFS_URL = "https://rata.digitraffic.fi/api/v1/trains/gtfs-passenger.zip"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "src" / "theroadragetrip" / "assets" / "railway_timetable.json.gz"
FORMAT_VERSION = 3  # 3: arrival + departure + stop flag per call, OSM station positions
PLACES_PATH = Path(__file__).resolve().parents[1] / "src" / "theroadragetrip" / "assets" / "places.json"
# GTFS -> OSM station match: same station code within CODE_MATCH_M, else the
# nearest OSM railway station within NEAR_MATCH_M (coordinates differ by
# tens of metres between the datasets).
CODE_MATCH_M = 3000.0
NEAR_MATCH_M = 1000.0
# GTFS extended route types used by Digitraffic.
CATEGORIES = {"102": "long_distance", "109": "commuter"}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
REQUEST_TIMEOUT_S = 120.0


class ImportError_(RuntimeError):
    pass


def download(url: str = GTFS_URL) -> bytes:
    import requests

    # Digitraffic rejects requests without gzip (HTTP 406) and asks for a
    # Digitraffic-User header identifying the application.
    response = requests.get(
        url,
        headers={"Accept-Encoding": "gzip", "Digitraffic-User": "RoadRageTrip/timetable-import"},
        timeout=REQUEST_TIMEOUT_S,
    )
    response.raise_for_status()
    return response.content


def _rows(archive: zipfile.ZipFile, name: str) -> Iterable[dict]:
    with archive.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def _seconds(text: str) -> int:
    hours, minutes, seconds = (int(part) for part in text.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _identity(route: dict, trip: dict) -> Tuple[str, str]:
    """(type, number): "IC 150" -> ("IC", "150"); commuter lines carry
    only their letter in the route ("A") and the number in the trip name
    ("A (HL 8192)") -> ("A", "8192")."""
    parts = route["route_short_name"].split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    number = trip.get("trip_short_name", "").rstrip(")").split()[-1]
    return parts[0] if parts else "", number


def _osm_stations() -> List[dict]:
    """OSM railway stations from the committed places.json (see
    tools/osm/extract_places.py); empty if it is missing."""
    try:
        document = json.loads(PLACES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [place for place in document.get("places", []) if place.get("type") == "railway_station"]


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    kx = 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat1 - lat2) * 111_320.0, (lon1 - lon2) * kx)


def _match_osm(code: str, lat: float, lon: float, osm: List[dict]) -> Optional[Tuple[float, float]]:
    """(lat, lon) of the OSM station for a GTFS station, or None."""
    for place in osm:
        if str(place.get("station_code", "")).upper() == code.upper() and _distance_m(lat, lon, place["lat"], place["lon"]) <= CODE_MATCH_M:
            return place["lat"], place["lon"]
    nearest = min(osm, key=lambda place: _distance_m(lat, lon, place["lat"], place["lon"]), default=None)
    if nearest is not None and _distance_m(lat, lon, nearest["lat"], nearest["lon"]) <= NEAR_MATCH_M:
        return nearest["lat"], nearest["lon"]
    return None


def reference_week(feed_start: date, feed_end: date, today: date) -> date:
    """The first full Monday-Sunday week starting on/after max(today,
    feed start) that the feed still covers."""
    start = max(today, feed_start)
    monday = start + timedelta(days=(7 - start.weekday()) % 7)
    if monday + timedelta(days=6) > feed_end:
        raise ImportError_(f"feed {feed_start}..{feed_end} holds no full week after {start}")
    return monday


def convert(zip_bytes: bytes, today: Optional[date] = None, downloaded_at: Optional[str] = None) -> dict:
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    feed = next(_rows(archive, "feed_info.txt"))
    feed_start = datetime.strptime(feed["feed_start_date"], "%Y%m%d").date()
    feed_end = datetime.strptime(feed["feed_end_date"], "%Y%m%d").date()
    monday = reference_week(feed_start, feed_end, today or date.today())
    week = [monday + timedelta(days=i) for i in range(7)]
    week_keys = [d.strftime("%Y%m%d") for d in week]

    calendar = {row["service_id"]: row for row in _rows(archive, "calendar.txt")}
    exceptions: Dict[str, Dict[str, str]] = {}
    for row in _rows(archive, "calendar_dates.txt"):
        exceptions.setdefault(row["service_id"], {})[row["date"]] = row["exception_type"]

    def mask(service_id: str) -> int:
        bits = 0
        base = calendar.get(service_id)
        for index, key in enumerate(week_keys):
            exception = exceptions.get(service_id, {}).get(key)
            runs = exception == "1" or (
                exception != "2" and base is not None
                and base["start_date"] <= key <= base["end_date"] and base[WEEKDAYS[index]] == "1"
            )
            bits |= runs << index
        return bits

    routes = {row["route_id"]: row for row in _rows(archive, "routes.txt")}
    trips = {}
    for trip in _rows(archive, "trips.txt"):
        days = mask(trip["service_id"])
        if days:
            trips[trip["trip_id"]] = (trip, days)

    stops = {row["stop_id"]: row for row in _rows(archive, "stops.txt")}

    def station(stop_id: str) -> str:
        return stops[stop_id]["parent_station"] or stop_id if stop_id in stops else stop_id

    stop_times: Dict[str, List[tuple]] = {}
    for row in _rows(archive, "stop_times.txt"):
        if row["trip_id"] in trips:
            arrival = _seconds(row["arrival_time"] or row["departure_time"])
            departure = _seconds(row["departure_time"] or row["arrival_time"])
            # pickup_type = drop_off_type = 1: a timing point the train
            # passes without stopping (most rows) - kept for the path only.
            stops_here = not (row.get("pickup_type") == "1" and row.get("drop_off_type") == "1")
            stop_times.setdefault(row["trip_id"], []).append(
                (int(row["stop_sequence"]), station(row["stop_id"]), arrival, departure, int(stops_here))
            )

    merged: Dict[tuple, dict] = {}
    for trip_id, (trip, days) in trips.items():
        sequence = [call[1:] for call in sorted(stop_times.get(trip_id, []))]
        if len(sequence) < 2:
            continue
        train_type, number = _identity(routes[trip["route_id"]], trip)
        key = (train_type, number, tuple(sequence))
        if key in merged:  # same run under another service period: union the days
            merged[key]["days"] |= days
            continue
        merged[key] = {
            "type": train_type,
            "category": CATEGORIES.get(routes[trip["route_id"]]["route_type"], "other"),
            "number": number,
            "origin": stops.get(sequence[0][0], {}).get("stop_name", sequence[0][0]),
            "destination": stops.get(sequence[-1][0], {}).get("stop_name", sequence[-1][0]),
            "days": days,
            # [station code, arrival, departure, 1 = stops / 0 = passes]
            "stops": [list(call) for call in sequence],
        }

    used = {call[0] for entry in merged.values() for call in entry["stops"]}
    osm = _osm_stations()
    stations = {}
    for code in sorted(used):
        if code not in stops:
            continue
        lat, lon = round(float(stops[code]["stop_lat"]), 6), round(float(stops[code]["stop_lon"]), 6)
        stations[code] = [lat, lon, stops[code]["stop_name"]] + list(_match_osm(code, lat, lon, osm) or [])
    trains = sorted(merged.values(), key=lambda e: (e["stops"][0][1], e["type"], e["number"], e["stops"][0][0]))
    matched = sum(1 for entry in stations.values() if len(entry) == 5)
    print(f"OSM station match: {matched} of {len(stations)} timetable stations")
    return {
        "version": FORMAT_VERSION,
        "source": GTFS_URL,
        # CC BY 4.0 (https://www.digitraffic.fi/en/terms-of-service/): keep
        # attribution, licence link and a note of the changes with the data.
        "attribution": "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "modifications": "Converted by Road Rage Trip from GTFS to a compact one-week timetable "
                         "(station coordinates, per-train stop times and weekday masks, matched OSM "
                         "station positions); other fields dropped.",
        "feed_version": feed.get("feed_version", ""),
        "downloaded_at": downloaded_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_from": feed_start.isoformat(),
        "valid_until": feed_end.isoformat(),
        "reference_week": monday.isoformat(),
        "timezone": "Europe/Helsinki",
        "stations": stations,
        "trains": trains,
    }


def write(document: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as sink:
        json.dump(document, sink, ensure_ascii=False, separators=(",", ":"))
    temporary.replace(output)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--zip", type=Path, help="use a downloaded gtfs-passenger.zip instead of downloading")
    args = parser.parse_args(argv)
    try:
        data = args.zip.read_bytes() if args.zip else download()
        document = convert(data)
    except Exception as exc:  # network, HTTP, bad zip, bad feed
        kept = "keeping the existing timetable" if args.output.exists() else "no timetable written"
        print(f"error: timetable import failed ({exc}); {kept}: {args.output}", file=sys.stderr)
        return 1
    write(document, args.output)
    per_day = [sum(1 for t in document["trains"] if t["days"] >> i & 1) for i in range(7)]
    print(f"Timetable {document['feed_version']} (valid {document['valid_from']}..{document['valid_until']})")
    print(f"Reference week from {document['reference_week']}: {len(document['trains'])} trains, "
          f"{len(document['stations'])} stations; per day Mon..Sun {per_day}")
    print(f"Output: {args.output} ({args.output.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
