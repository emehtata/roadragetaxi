#!/usr/bin/env python3
"""Validate simulated NPC traffic against a LAM station; never imported by the game.

PYTHONPATH=src .venv/bin/python tools/lam_validate.py --station Kaukovainio --days 2026-10-14 2026-10-15 2026-10-17
docs/lam-traffic-audit.md, "Validation strategy": a headless server on the
station's map, the player parked at the station, and a virtual detector - a
line across the road at the station - counting NPC vehicles crossing it by
game hour and LAM direction (1 along the station's bearing). The simulated
hourly shape is compared with the station's measured curves (shares of the
weekday peak hour), and server tick times are reported.

Game time runs 60x without a fare, so a game hour is one real minute of
traffic: hourly counts are small; compare shapes, not volumes.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DETECTOR_HALF_WIDTH_M = 30.0  # crossings this far from the station, across the road, count
TICK_S = 1.0 / 30.0


class Detector:
    """A line across the road at (x, y); direction 1 is along `bearing` (degrees from north)."""

    def __init__(self, x: float, y: float, bearing: float) -> None:
        self.x, self.y = x, y
        self.along = (math.sin(math.radians(bearing)), math.cos(math.radians(bearing)))
        self.last: dict = {}  # vehicle id -> its last signed distance along the road

    def crossings(self, vehicles) -> list:
        """["1"|"2", ...] for the vehicles that crossed the line since the last call."""
        out, seen = [], {}
        for vehicle_id, vx, vy in vehicles:
            dx, dy = vx - self.x, vy - self.y
            along = dx * self.along[0] + dy * self.along[1]
            across = abs(dx * self.along[1] - dy * self.along[0])
            before = self.last.get(vehicle_id)
            if before is not None and across <= DETECTOR_HALF_WIDTH_M:
                if before < 0.0 <= along:
                    out.append("1")
                elif before > 0.0 >= along:
                    out.append("2")
            seen[vehicle_id] = along
        self.last = seen
        return out


def shares(counts: dict, peak: float) -> list:
    return [round((counts[h]["1"] + counts[h]["2"]) / peak, 3) if peak else 0.0 for h in range(24)]


def run(station: dict, days: list) -> dict:
    lat, lon = station["lat"], station["lon"]
    sys.argv = ["lam_validate", "--no-menu", "--no-historical-weather",
                "--bbox", f"{lat - 0.001},{lon - 0.002},{lat + 0.001},{lon + 0.002}", "--place-name", "LAM detector"]
    from theroadragetrip.server.cli import parse_server_args
    from theroadragetrip.server import SimulationServer

    server = SimulationServer(*parse_server_args())
    detector = Detector(station["x_m"], station["y_m"], station["bearing"])
    results, tick_ms = {}, []
    try:
        for day in days:
            server.calendar.current = datetime.combine(day, datetime.min.time())
            server.car.x, server.car.y = station["x_m"], station["y_m"]  # the player parked at the station
            counts = {h: {"1": 0, "2": 0} for h in range(24)}
            while server.calendar.date == day:
                hour = server.calendar.current.hour
                started = time.perf_counter()
                server.tick(TICK_S)
                tick_ms.append((time.perf_counter() - started) * 1000.0)
                for direction in detector.crossings((v.vehicle_id, v.x, v.y) for v in server.world.npcs):
                    counts[hour][direction] += 1
            results[day.isoformat()] = counts
            print(f"{day}: {sum(c['1'] + c['2'] for c in counts.values())} crossings", file=sys.stderr)
    finally:
        server.close()
    tick_ms.sort()
    return {"days": results, "tick_ms": {"p50": round(statistics.median(tick_ms), 2),
                                         "p95": round(tick_ms[int(len(tick_ms) * 0.95)], 2), "ticks": len(tick_ms)}}


def compare(station: dict, run_result: dict) -> dict:
    """Simulated vs measured hourly shares, as shares of the (simulated or
    measured) average weekday peak hour; mean absolute error per day type."""
    by_type = {"weekday": [], "weekend": []}
    for day, counts in run_result["days"].items():
        by_type["weekday" if date.fromisoformat(day).weekday() < 5 else "weekend"].append(counts)

    def mean_counts(days):
        return {h: {d: sum(c[h][d] for c in days) / len(days) for d in ("1", "2")} for h in range(24)} if days else None

    weekday = mean_counts(by_type["weekday"])
    peak = max(weekday[h]["1"] + weekday[h]["2"] for h in range(24)) if weekday else 0.0
    out = {"tick_ms": run_result["tick_ms"]}
    for kind, days in by_type.items():
        mean = mean_counts(days)
        if mean is None:
            continue
        simulated, measured = shares(mean, peak), station["profile"][f"{kind}_hourly"]
        out[kind] = {"days": len(days), "simulated": simulated, "measured": measured,
                     "mae": round(sum(abs(a - b) for a, b in zip(simulated, measured)) / 24, 3),
                     "direction_split_simulated": round(sum(mean[h]["1"] for h in range(24)) / max(1e-9, sum(mean[h]["1"] + mean[h]["2"] for h in range(24))), 3),
                     "crossings_per_day": round(sum(mean[h]["1"] + mean[h]["2"] for h in range(24)), 1)}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--station", required=True, help="a part of the station's name in lam_profiles.json")
    parser.add_argument("--days", nargs="+", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, help="write the comparison as JSON")
    args = parser.parse_args()
    data = json.loads((ROOT / "src/theroadragetrip/assets/traffic/lam_profiles.json").read_text(encoding="utf-8"))
    station = next(s for s in data["stations"] if args.station.lower() in s["name"].lower())
    if station.get("bearing") is None:
        sys.exit(f"{station['name']} has no bearing: no detector direction")
    result = compare(station, run(station, args.days))
    if args.out:
        args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"{station['name']}: tick p50 {result['tick_ms']['p50']} ms, p95 {result['tick_ms']['p95']} ms")
    for kind in ("weekday", "weekend"):
        if kind in result:
            r = result[kind]
            print(f"{kind} ({r['days']} days, {r['crossings_per_day']} crossings a day): MAE {r['mae']}")
            print("  hour      " + " ".join(f"{h:>5}" for h in range(24)))
            print("  simulated " + " ".join(f"{v:5.2f}" for v in r["simulated"]))
            print("  measured  " + " ".join(f"{v:5.2f}" for v in r["measured"]))


if __name__ == "__main__":
    main()
