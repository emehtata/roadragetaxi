#!/usr/bin/env python3
"""Learn real train compositions from Digitraffic into the game's local,
offline composition database (theroadragetrip.train_compositions).

    python tools/import_train_compositions.py [--date YYYY-MM-DD ...] [--from-json FILE] [OUTPUT]

Fetches https://rata.digitraffic.fi/api/v1/compositions/<date> (one
request per date, all trains) for today and tomorrow unless dates are
given. Compositions are published close to departure, so rerun it now and
then: every run *adds* knowledge. The game never downloads anything.

Kept per long-distance train (the ones the game runs):
- observations: exact "<date>|<number>" compositions, the last
  KEEP_OBSERVATION_DAYS days of them (older ones are dropped, not needed
  once "latest" has learned from them)
- latest: the newest composition seen for each train number - what a
  future run of that train reuses
- by_type: the newest composition seen for each train type (IC, S, ...)
Newer observations always replace older "latest"/"by_type" entries.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

API = "https://rata.digitraffic.fi/api/v1/compositions/{date}"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "src" / "theroadragetrip" / "assets" / "train_compositions.json.gz"
FORMAT_VERSION = 1
KEEP_OBSERVATION_DAYS = 14
SERVICE_FLAGS = ("catering", "playground", "pet", "disabled", "luggage", "smoking", "video")
REQUEST_TIMEOUT_S = 60.0


def download(day: date) -> list:
    import requests

    response = requests.get(
        API.format(date=day.isoformat()),
        headers={"Accept-Encoding": "gzip", "Digitraffic-User": "RoadRageTrip/composition-import"},
        timeout=REQUEST_TIMEOUT_S,
    )
    response.raise_for_status()
    return response.json()


def compact(section: dict) -> dict:
    """One journey section -> {max_speed_kmh, total_length_m, vehicles}.
    vehicles: [kind, type, length_m or None, [service flags]] in train
    order. Multiple units (Sm*/Dm*) are fully described by their
    wagons; a hauled train's locomotives come first."""
    wagons = section.get("wagons", [])
    wagon_types = {w.get("wagonType") for w in wagons}
    ordered = [
        (loco.get("location", 0), ["locomotive", loco.get("locomotiveType", ""), None, []])
        for loco in section.get("locomotives", [])
        if loco.get("locomotiveType") not in wagon_types  # not a multiple unit's own car
    ]
    for wagon in wagons:
        length_cm = wagon.get("length")
        ordered.append((wagon.get("location", 0), [
            "wagon", wagon.get("wagonType", ""),
            round(length_cm / 100.0, 2) if isinstance(length_cm, (int, float)) else None,
            [flag for flag in SERVICE_FLAGS if wagon.get(flag) is True],
        ]))
    # Digitraffic's location order, locomotives included (a push-pull
    # set can have its locomotive at the far end).
    vehicles = [vehicle for _, vehicle in sorted(ordered, key=lambda item: item[0])]
    return {"max_speed_kmh": section.get("maximumSpeed"), "total_length_m": section.get("totalLength"), "vehicles": vehicles}


def merge(database: dict, compositions: List[dict], fetched_at: str) -> int:
    """Add Digitraffic compositions to the database; returns how many."""
    added = 0
    for item in compositions:
        if item.get("trainCategory") != "Long-distance" or not item.get("journeySections"):
            continue
        number, day, train_type = str(item["trainNumber"]), item["departureDate"], item.get("trainType", "")
        # The first section: how the train leaves its origin (later
        # sections, where a train splits or joins, are not modelled).
        entry = dict(compact(item["journeySections"][0]), train_type=train_type, departure_date=day, fetched_at=fetched_at)
        database["observations"][f"{day}|{number}"] = entry
        for key, table in ((number, "latest"), (train_type, "by_type")):
            known = database[table].get(key)
            if known is None or (known["departure_date"], known["fetched_at"]) <= (day, fetched_at):
                database[table][key] = entry
        added += 1
    return added


def load(path: Path) -> dict:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            database = json.load(source)
        if database.get("version") == FORMAT_VERSION:
            return database
    except (OSError, ValueError, EOFError):
        pass
    return {"version": FORMAT_VERSION, "observations": {}, "latest": {}, "by_type": {}}


def prune(database: dict, today: date) -> None:
    oldest = (today - timedelta(days=KEEP_OBSERVATION_DAYS)).isoformat()
    database["observations"] = {key: value for key, value in database["observations"].items() if key.split("|")[0] >= oldest}


def write(database: dict, path: Path) -> None:
    database.update({
        "source": "https://rata.digitraffic.fi/api/v1/compositions",
        "attribution": "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "modifications": "Long-distance train compositions condensed to vehicle type, length and service flags by Road Rage Trip.",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as sink:
        json.dump(database, sink, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--date", action="append", type=date.fromisoformat, help="departure date(s) to fetch")
    parser.add_argument("--from-json", type=Path, help="use a saved compositions JSON instead of downloading")
    args = parser.parse_args(argv)
    today = date.today()
    database = load(args.output)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    added, failures = 0, []
    if args.from_json:
        added += merge(database, json.loads(args.from_json.read_text(encoding="utf-8")), fetched_at)
    else:
        for day in args.date or [today, today + timedelta(days=1)]:
            try:
                added += merge(database, download(day), fetched_at)
            except Exception as exc:  # offline / not published yet: keep what we know
                failures.append(f"{day}: {exc}")
    for failure in failures:
        print(f"warning: {failure}", file=sys.stderr)
    if not added:
        print(f"error: no compositions fetched; keeping {args.output}", file=sys.stderr)
        return 1
    prune(database, today)
    write(database, args.output)
    print(f"Added {added} compositions; database now {len(database['latest'])} trains, "
          f"{len(database['observations'])} dated observations, types {sorted(database['by_type'])}")
    print(f"Output: {args.output} ({args.output.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
