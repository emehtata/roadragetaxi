#!/usr/bin/env python3
"""Offline LAM (TMS) traffic profile builder; never imported by the game.

PYTHONPATH=src .venv/bin/python tools/lam_profiles.py
docs/lam-traffic-audit.md phases 0-1: downloads Fintraffic's raw per-vehicle
detections (lamraw_<tmsNumber>_<yy>_<ordinal day>.csv) for a few
representative stations and one holiday-free week per season, keeps only
hourly counts per direction (cached; the raw files are ~2.5 MB a day), and
writes normalized weekday/weekend hourly curves, month factors and the
station metadata to src/theroadragetrip/assets/traffic/lam_profiles.json.
It also prints the curves against population.py's estimates.

Source: Fintraffic / digitraffic.fi, license CC 4.0 BY.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from theroadragetrip.digitraffic_road import _default_opener  # noqa: E402
from theroadragetrip.population import MONTH_FACTOR, WEEKDAY_HOURLY, WEEKEND_HOURLY  # noqa: E402

BASE = "https://tie.digitraffic.fi"
HEADERS = {"Accept-Encoding": "gzip", "Digitraffic-User": "RoadRageTrip/lam-profiles"}
OUT = ROOT / "src/theroadragetrip/assets/traffic/lam_profiles.json"
CACHE = Path.home() / ".cache/RoadRageTrip/lam"
SCHEMA_VERSION = 1

# (station id, setting): urban Oulu and Helsinki region, rural Northern Ostrobothnia
# and Kainuu. The id is the API's; raw files use the station's tmsNumber.
STATIONS = [
    (21205, "urban"),  # vt4 Oulu Välivainio: urban motorway
    (24256, "urban"),  # vt22 Oulu Kaukovainio: urban main road
    (24247, "urban"),  # st847 Oulunlahti: urban regional road
    (20002, "urban"),  # vt1 Espoo Hirvisuo: capital motorway
    (23011, "urban"),  # st101 Helsinki Vartiokylä: Ring I
    (23153, "urban"),  # kt45 Oulunkylä: Helsinki arterial
    (24229, "rural"),  # vt4 Ii Myllykangas
    (24227, "rural"),  # vt22 Muhos Riihikylä
    (24205, "rural"),  # kt86 Liminka Heinijärvi
    (24253, "rural"),  # st816 Hailuoto
    (24203, "rural"),  # vt5 Kuusamo Nissinvaara
]
# One Monday-Sunday week per season: no public holidays, no clock-change Sunday
# (a 23- or 25-hour day would skew the hourly bins). July is the holiday season.
WEEKS = [date(2026, 1, 19), date(2026, 4, 20), date(2026, 7, 13), date(2026, 10, 12)]
GROUP_MIN_DAYS = 21  # a station with fewer sampled days stays in the file, out of the urban/rural curves


def get(url: str) -> bytes:
    return _default_opener(url, HEADERS)


def hourly_counts(csv_text: str) -> dict:
    """{"1": [24 counts], "2": [24 counts]} of valid detections (faulty 0) by
    local hour and direction. Every vehicle class counts, 8 and 9 included:
    the files mark them valid, although the documented faulty rule says > 7."""
    counts = {"1": [0] * 24, "2": [0] * 24}
    for line in csv_text.splitlines():
        fields = line.split(";")
        if len(fields) >= 13 and fields[12] == "0" and fields[9] in counts and fields[3].isdigit() and int(fields[3]) < 24:
            counts[fields[9]][int(fields[3])] += 1
    return counts


def day_counts(tms: int, day: date, cache: Path):
    """A station-day's hourly counts, from the cache or downloaded; None when unpublished."""
    path = cache / f"{tms}_{day.isoformat()}.json"
    if path.exists():
        return json.loads(path.read_text())
    url = f"{BASE}/api/tms/v1/history/raw/lamraw_{tms}_{day:%y}_{day.timetuple().tm_yday}.csv"
    try:
        counts = hourly_counts(get(url).decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        if error.code not in (403, 404):  # the file store answers a missing day with 403
            raise
        counts = None
    time.sleep(0.5)  # well under the 60 requests a minute an IP may make
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(counts))
    return counts


def station_meta(station_id: int) -> dict:
    feature = json.loads(get(f"{BASE}/api/tms/v1/stations/{station_id}"))
    properties = feature["properties"]
    lon, lat = feature["geometry"]["coordinates"][:2]
    address = properties.get("roadAddress") or {}
    return {"id": station_id, "tms_number": properties["tmsNumber"], "name": properties["name"], "lon": lon, "lat": lat,
            "road_number": address.get("roadNumber"), "road_section": address.get("roadSection"),
            "distance_from_section_start_m": address.get("distanceFromRoadSectionStart"),
            "carriageway": address.get("carriageway"), "side": address.get("side"),
            "direction1_municipality": properties.get("direction1Municipality"),
            "direction2_municipality": properties.get("direction2Municipality"),
            "free_flow_speed_kmh": [properties.get("freeFlowSpeed1"), properties.get("freeFlowSpeed2")]}


def mean_curve(days: list) -> list:
    return [sum(day[h] for day in days) / len(days) for h in range(24)] if days else [0.0] * 24


def profile(days_by_date: dict) -> dict:
    """Weekday/weekend hourly curves (both directions and each one) as shares of
    the average weekday's peak hour - population.py's convention - and each
    sampled month's average weekday total against the sampled months' mean."""
    def total(counts):
        return [counts["1"][h] + counts["2"][h] for h in range(24)]

    weekdays = [counts for day, counts in days_by_date.items() if day.weekday() < 5]
    weekends = [counts for day, counts in days_by_date.items() if day.weekday() >= 5]
    peak = max(mean_curve([total(c) for c in weekdays])) or 1.0

    def shares(days, key=None):
        return [round(v / peak, 3) for v in mean_curve([total(c) if key is None else c[key] for c in days])]

    months = {}
    for day, counts in days_by_date.items():
        if day.weekday() < 5:
            months.setdefault(day.month, []).append(sum(total(counts)))
    month_daily = {m: sum(v) / len(v) for m, v in months.items()}
    mean_daily = sum(month_daily.values()) / len(month_daily) if month_daily else 1.0
    return {
        "weekday_hourly": shares(weekdays), "weekend_hourly": shares(weekends),
        "weekday_hourly_direction": {d: shares(weekdays, d) for d in ("1", "2")},
        "weekend_hourly_direction": {d: shares(weekends, d) for d in ("1", "2")},
        "month_factor": {str(m): round(v / mean_daily, 3) for m, v in sorted(month_daily.items())},
        "weekday_peak_vehicles_per_hour": round(peak),
        "days_used": {"weekday": len(weekdays), "weekend": len(weekends)},
    }


def group_curve(stations: list, key: str) -> list:
    return [round(sum(s["profile"][key][h] for s in stations) / len(stations), 3) for h in range(24)]


def mae(a: list, b: list) -> float:
    return round(sum(abs(x - y) for x, y in zip(a, b)) / len(a), 3)


def build(cache: Path) -> dict:
    stations = []
    for station_id, setting in STATIONS:
        meta = station_meta(station_id)
        days, missing = {}, []
        for week in WEEKS:
            for offset in range(7):
                day = week + timedelta(days=offset)
                counts = day_counts(meta["tms_number"], day, cache)
                if counts is None or sum(counts["1"]) + sum(counts["2"]) == 0:
                    missing.append(day.isoformat())
                else:
                    days[day] = counts
        print(f"{meta['name']}: {len(days)} days, {len(missing)} missing", file=sys.stderr)
        stations.append({**meta, "setting": setting, "missing_days": missing, "profile": profile(days)})
    complete = [s for s in stations if sum(s["profile"]["days_used"].values()) >= GROUP_MIN_DAYS]
    groups = {setting: {key: group_curve([s for s in complete if s["setting"] == setting], key)
                        for key in ("weekday_hourly", "weekend_hourly")} for setting in ("urban", "rural")}
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "Fintraffic / digitraffic.fi, license CC 4.0 BY: TMS raw detections (lamraw), valid records only",
        "sample_weeks": [week.isoformat() for week in WEEKS],
        "convention": "hourly values are shares of the station's average weekday peak hour, local Finnish time",
        "groups": groups, "group_stations": [s["id"] for s in complete], "stations": stations,
    }


def report(data: dict) -> None:
    """The measured curves next to population.py's estimates."""
    print("hour  " + " ".join(f"{h:>5}" for h in range(24)))
    rows = [("est weekday", WEEKDAY_HOURLY), ("est weekend", WEEKEND_HOURLY)]
    for setting, curves in data["groups"].items():
        rows += [(f"{setting} weekday", curves["weekday_hourly"]), (f"{setting} weekend", curves["weekend_hourly"])]
    for name, curve in rows:
        print(f"{name:<14}" + " ".join(f"{v:5.2f}" for v in curve))
    for setting, curves in data["groups"].items():
        print(f"MAE vs estimate, {setting}: weekday {mae(curves['weekday_hourly'], WEEKDAY_HOURLY)}, "
              f"weekend {mae(curves['weekend_hourly'], WEEKEND_HOURLY)}")
    for station in data["stations"]:
        factors = station["profile"]["month_factor"]
        print(f"{station['name']:<34} month factors {factors}  (estimate {[MONTH_FACTOR[int(m)] for m in factors]})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--cache", type=Path, default=CACHE, help="hourly counts per station-day (default: %(default)s)")
    args = parser.parse_args()
    data = build(args.cache)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    report(data)


if __name__ == "__main__":
    main()
