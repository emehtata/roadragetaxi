"""Refresh the bundled Veikkausliiga schedule and results from its official tables."""
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
VENUES = {
    "Veritas Stadion": ("Turku", 60.4426977, 22.2918553),
    "Bolt Arena": ("Helsinki", 60.1876025, 24.9227359),
    "Wiklöf Holding Arena": ("Mariehamn", 60.1039242, 19.9336205),
    "Tammelan Stadion": ("Tampere", 61.5004530, 23.7853443),
    "Project Liv Arena": ("Pietarsaari", 63.6721277, 22.6940523),
    "Markku.fi Areena": ("Helsinki", 60.2346893, 24.9624973),
    "OmaSp Stadion": ("Seinäjoki", 62.7787928, 22.8147745),
    "Lemonsoft Stadion": ("Vaasa", 63.0853618, 21.6278755),
    "Väre Areena": ("Kuopio", 62.8846496, 27.6715566),
    "Lahden stadion": ("Lahti", 60.9829953, 25.6359598),
    "Raatin Stadion": ("Oulu", 65.0197711, 25.4657839),
    "OTC Stadion": ("Oulu", 65.0012140, 25.4527357),
}


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
        score = re.search(r"(\d+)\s*[—–-]\s*(\d+)", cells[-2])
        attendance = re.search(r"\d+", cells[-1])
        match["result"] = {"home": int(score[1]), "away": int(score[2])} if score else None
        match["attendance"] = int(attendance[0]) if attendance else None
        venue = match["venue"]
        if venue["name"] not in VENUES:
            raise RuntimeError(f"no mapped stadium location for {venue['name']}")
        city, latitude, longitude = VENUES[venue["name"]]
        venue.update(city=city, latitude=latitude, longitude=longitude)
        updated += 1

    data["generated_at"] = datetime.now(timezone.utc).date().isoformat()
    temporary = FIXTURES.with_name(FIXTURES.name + ".tmp")
    with temporary.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
        compressed.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    temporary.replace(FIXTURES)
    print(f"Updated official dates, results and attendances for {updated} Veikkausliiga 2026 matches")


if __name__ == "__main__":
    main()
