"""Refresh the bundled Veikkausliiga start times from its official tables (timing only)."""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "src/theroadragetrip/assets/sports_fixtures.json.gz"
URL = "https://www.veikkausliiga.com/tilastot/2026/veikkausliiga/ottelut/?group={}"


class MatchRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row = {"date": attrs.get("data-time"), "cells": []}
        elif self.row is not None and tag == "td":
            self.cell = ""
        elif self.row is not None and tag == "a":
            match = re.search(r"/ottelut/(\d+)/", attrs.get("href", ""))
            if match:
                self.row["id"] = match.group(1)

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data.strip() + " "

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.row["cells"].append(self.cell.strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row.get("id"):
                self.rows.append(self.row)
            self.row = None


def fetch_group(group: int) -> list[dict]:
    response = requests.get(URL.format(group), timeout=30, headers={"User-Agent": "RoadRageTrip fixture updater"})
    response.raise_for_status()
    parser = MatchRows()
    parser.feed(response.text)
    if len(parser.rows) != {1: 132, 2: 30, 3: 15}[group]:
        raise RuntimeError(f"official group {group} returned {len(parser.rows)} matches")
    return parser.rows


def strip_to_timing(match: dict) -> None:
    for key in ("home_team", "away_team", "result", "attendance"):
        match.pop(key, None)
    match["venue"].pop("name", None)


def main() -> None:
    with gzip.open(FIXTURES, "rt", encoding="utf-8") as source:
        data = json.load(source)
    fixtures = {m["id"].rsplit(":", 1)[-1]: m for m in data["matches"]
                if m["competition"] == "veikkausliiga" and m["season"] == "2026"}
    official = {row["id"]: row for group in (1, 2, 3) for row in fetch_group(group)}
    if fixtures.keys() != official.keys():
        raise RuntimeError("bundled 2026 match IDs do not match the official schedule")

    helsinki = ZoneInfo("Europe/Helsinki")
    updated = 0
    for match_id, row in official.items():
        match = fixtures[match_id]
        cells = row["cells"]
        kickoff = next((value for value in cells if re.fullmatch(r"\d{1,2}:\d{2}", value)), None)
        if kickoff is None or not row["date"]:
            raise RuntimeError(f"missing date or kickoff for official match {match_id}")
        start = datetime.strptime(row["date"] + kickoff, "%Y%m%d%H:%M").replace(tzinfo=helsinki)
        start = start.astimezone(timezone.utc)
        match["start"] = start.isoformat(timespec="seconds").replace("+00:00", "Z")
        match["crowd_start"] = (start - timedelta(hours=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
        match["crowd_end"] = (start + timedelta(minutes=150)).isoformat(timespec="seconds").replace("+00:00", "Z")
        updated += 1

    for match in data["matches"]:  # timing table only: no names, results or attendances
        strip_to_timing(match)
    data["generated_at"] = datetime.now(timezone.utc).date().isoformat()
    temporary = FIXTURES.with_name(FIXTURES.name + ".tmp")
    with temporary.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
        compressed.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    temporary.replace(FIXTURES)
    print(f"Updated official start times for {updated} Veikkausliiga 2026 matches")


if __name__ == "__main__":
    main()
