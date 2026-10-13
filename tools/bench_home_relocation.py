#!/usr/bin/env python3
"""Server-side benchmark of a Home (H) relocation: the real simulation
server, in this process, ticking at its tick rate in real time (background
loads need the wall-clock time they really take), with no Godot client.

    PYTHONPATH=src python tools/bench_home_relocation.py --preset Oulu \\
        --dest-offset 0 6000 [--osm-source pbf] [--prepare-s 0] [--json out.json]

It starts the city, saves a Home at the destination (map metres, or an
offset from the start), presses H and keeps ticking until the map has
settled. Reported, in seconds after the press:
- position_s: the taxi is at home (the authoritative position changed)
- central_s: the server's map chunk under the taxi has roads - what the
  client would draw first (the chunk index is what is sent to Godot)
- settled_s: no fetch, merge, sync or chunk rebuild left
plus the map-sync stage busy times, tick durations (max/p95/p99), RWC hits
and misses, PBF extractions, Overpass downloads and resident memory.

Godot's own chunk parsing/geometry time is not covered here (no client);
the Godot benchmark is godot/main.gd --bench with a running server.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path


class _Counter(logging.Handler):
    """Counts log lines the pipeline already writes at each expensive step."""

    MARKS = {
        "rwc_hit": "[WorldCache] Cache hit", "rwc_covering_hit": "[WorldCache] Covering cache hit",
        "rwc_miss": "[WorldCache] Cache miss", "pbf_extract": "Extracting local OSM data",
        "osm_json_cache_hit": "Loaded OSM data from local cache", "tile_fetch": "Tile streaming transition",
    }

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.counts = {name: 0 for name in self.MARKS}

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        for name, mark in self.MARKS.items():
            if mark in message:
                self.counts[name] += 1


STALL_S = 0.5  # a tick this long is a stall: its stack is recorded


def _rss_mb() -> dict:
    try:
        lines = Path("/proc/self/status").read_text().splitlines()
    except OSError:
        return {}
    values = {line.split(":")[0]: int(line.split()[1]) / 1024.0 for line in lines if line.startswith(("VmRSS", "VmHWM"))}
    return {"rss_mb": round(values.get("VmRSS", 0.0)), "peak_rss_mb": round(values.get("VmHWM", 0.0))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--preset", default="Oulu")
    parser.add_argument("--osm-source", choices=("overpass", "pbf"), default=None)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--dest", nargs=2, type=float, metavar=("X", "Y"), help="home in map metres")
    where.add_argument("--dest-offset", nargs=2, type=float, metavar=("DX", "DY"), help="home this far from the start")
    parser.add_argument("--prepare-s", type=float, default=0.0, help="tick this long after saving home, before H")
    parser.add_argument("--timeout-s", type=float, default=300.0)
    parser.add_argument("--json", type=Path, help="also write the result here")
    parser.add_argument("--stall-ms", type=float, default=STALL_S * 1000.0, help="record the stack of ticks longer than this")
    args = parser.parse_args(argv)

    server_argv = ["--preset", args.preset, "--no-menu", "--game-mode", "gig_driver", "--log-level", "INFO"]
    if args.osm_source:
        server_argv += ["--osm-source", args.osm_source]
    sys.argv = ["bench"] + server_argv
    from theroadragetrip.server import SimulationServer
    from theroadragetrip.server.cli import parse_server_args

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    counter = _Counter()
    logging.getLogger().addHandler(counter)
    server_args, config = parse_server_args()
    started = time.perf_counter()
    server = SimulationServer(server_args, config)
    startup_s = time.perf_counter() - started
    dt = 1.0 / server.tick_rate
    server._on_foot = False
    server.homes_file = Path("/dev/null")  # never touch the player's saved homes
    import theroadragetrip.server as server_module
    server_module.save_home = lambda *a, **k: None

    stalls: list = []  # (tick ms, main-thread stack) of ticks over STALL_S, seen by the watchdog
    in_tick = [None]

    def watchdog() -> None:
        import threading
        import traceback

        main_id, reported = threading.main_thread().ident, None
        while True:
            time.sleep(0.01)
            began = in_tick[0]
            if began is not None and began != reported and time.perf_counter() - began > args.stall_ms / 1000.0:
                reported = began
                frame = sys._current_frames().get(main_id)
                stalls.append([round((time.perf_counter() - began) * 1000.0), traceback.format_stack(frame)[-8:]])

    import threading
    threading.Thread(target=watchdog, daemon=True).start()

    def run(seconds: float, until=None) -> list:
        durations, deadline = [], time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            tick_started = time.perf_counter()
            in_tick[0] = tick_started
            server.tick(dt)
            in_tick[0] = None
            durations.append(time.perf_counter() - tick_started)
            if until is not None and until():
                break
            time.sleep(max(0.0, dt - (time.perf_counter() - tick_started)))
        return durations

    run(3.0)  # settle the start (initial tile window)
    while server._map_streamer is not None and server._map_streamer.status():
        run(1.0)
    start = (server.car.x, server.car.y)
    home = tuple(args.dest) if args.dest else (start[0] + args.dest_offset[0], start[1] + args.dest_offset[1])
    server._home = (home[0], home[1], 0.0)
    counts_before = dict(counter.counts)
    if args.prepare_s > 0.0:
        run(args.prepare_s)

    pressed = time.perf_counter()
    server._home_pressed()
    marks = {"position_s": time.perf_counter() - pressed if (server.car.x, server.car.y) == home else None}
    statuses, durations, last_status = [], [], None
    while time.perf_counter() - pressed < args.timeout_s:
        durations += run(dt * 3)
        now = time.perf_counter() - pressed
        status = server._map_streamer.status() if server._map_streamer is not None else ""
        if status != last_status:
            statuses.append((round(now, 2), status))
            last_status = status
        if "central_s" not in marks and server.central_chunk_ready():
            marks["central_s"] = now
        if "central_s" in marks and not status and not server._map_growth:
            marks["settled_s"] = now
            break
    streamer = server._map_streamer
    ms = sorted(d * 1000.0 for d in durations) or [0.0]
    result = {
        "preset": args.preset, "osm_source": server_args.osm_source, "start": [round(v) for v in start],
        "home": [round(v) for v in home], "distance_m": round(((home[0] - start[0]) ** 2 + (home[1] - start[1]) ** 2) ** 0.5),
        "startup_s": round(startup_s, 2), "prepare_s": args.prepare_s,
        **{name: (round(value, 2) if value is not None else None) for name, value in marks.items()},
        "statuses": statuses,
        "tick_ms": {"max": round(ms[-1], 1), "p95": round(ms[int(len(ms) * 0.95)], 1),
                    "p99": round(ms[int(len(ms) * 0.99)], 1), "mean": round(statistics.fmean(ms), 2), "ticks": len(ms)},
        "last_sync": streamer.last_sync if streamer else None,
        "sync_stage_ms": {k: round(v) for k, v in (streamer.sync_stage_ms if streamer else {}).items()},
        "counts": {name: counter.counts[name] - counts_before[name] for name in counter.counts},
        **_rss_mb(),
        "stalls": stalls,
    }
    print(json.dumps(result, indent=2))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2))
    return 0 if "settled_s" in result else 1


if __name__ == "__main__":
    sys.exit(main())
