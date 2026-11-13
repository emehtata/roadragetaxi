#!/usr/bin/env python3
"""Map growth while driving, as a connected client sees it.

    PYTHONPATH=src python tools/bench_map_jitter.py --preset Oulu --osm-source pbf \\
        [--drive-s 180] [--speed 20] [--heading 0] [--sample-ms 45] [--json out.json]

The real simulation server ticks in this process at its tick rate (as
run_forever does); a socket client in a child process reads the same
line-JSON stream Godot reads and notes when each message arrives. Once the
start has settled, the taxi is moved along a straight line (--heading in
radians, 0 east) through new map tiles. Reported:
- tick wall time, overall and while the map is idle / busy (merging,
  syncing, rebuilding chunks or loading a tile), and how long ticks waited
  for the GIL or a lock (wall minus thread CPU time) per background thread;
- what the ticks over one tick interval were made of: phases, and full
  garbage collections on any thread (a collection holds the GIL);
- chunks sent, and how many were resends of a chunk the client already had;
- the client's state arrival gaps, and godot/state_buffer.gd replayed at
  60 fps on those arrivals: frames frozen (render time past the newest
  state), clock snaps (visible jumps) and frames drawn at the wrong speed.

A cold run needs a route whose tiles are not cached yet (another --heading).
Godot's own frame costs are not covered: this client never drops a frame.
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import math
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

# godot/state_buffer.gd
LATE_FOLLOW, EARLY_FOLLOW, CLOCK_SNAP_S, SLEW_GAIN, MAX_SLEW, DELAY_S = 0.5, 0.05, 0.25, 5.0, 0.25, 0.1
MAX_EXTRAPOLATE_S = 0.2  # state_buffer.gd: movement carries on this long past the newest state
FRAME_S = 1.0 / 60.0
BACKGROUND = ("map-growth", "taxi-roads", "_background_tile_fetch")  # thread names: the map is busy


def client(port: int, path: str) -> int:
    """The child process: one row per message, [kind, arrival, bytes, tick or chunk id, server_time]."""
    sock = socket.create_connection(("127.0.0.1", port))
    buf = b""
    with open(path, "w", buffering=1) as log:
        try:
            while data := sock.recv(1 << 20):
                now = time.monotonic()
                *lines, buf = (buf + data).split(b"\n")
                for line in lines:
                    if line.startswith(b'{"type":"state"'):
                        message = json.loads(line)
                        row = ["state", now, len(line), message["tick"], message["server_time"]]
                    elif line.startswith(b'{"type":"chunk'):
                        at = line.find(b'"chunk_id":"') + 12
                        row = ["unload" if b"chunk_unload" in line[:30] else "chunk", now, len(line),
                               line[at:line.find(b'"', at)].decode(), None]
                    else:
                        continue
                    log.write(json.dumps(row) + "\n")
        except OSError:
            pass
    return 0


def pct(values, p):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * p))], 1) if values else 0.0


def replay(states) -> dict:
    """state_buffer.gd sampled every 60 fps frame, each state pushed at the first frame after it arrived."""
    offset = clock = 0.0
    has_clock, clock_local, newest, frozen_now, i = False, -1.0, None, False, 0
    frames = frozen = episodes = snaps = off_speed = late = late_episodes = 0
    late_now = False
    t = states[0][1]
    while t < states[-1][1]:
        while i < len(states) and states[i][1] <= t:
            sample = states[i][4] - t
            if not has_clock or abs(sample - offset) > CLOCK_SNAP_S:
                offset, has_clock = sample, True
            else:
                offset += (sample - offset) * (LATE_FOLLOW if sample < offset else EARLY_FOLLOW)
            newest = states[i][4]
            i += 1
        target = t + offset - DELAY_S
        if clock_local < 0 or abs(target - clock) > CLOCK_SNAP_S:
            snaps += clock_local >= 0
            clock = target
        else:
            rate = 1.0 + max(-MAX_SLEW, min(MAX_SLEW, (target - clock) * SLEW_GAIN))
            clock += (t - clock_local) * rate
            off_speed += abs(rate - 1.0) > 0.05
        clock_local = t
        frames += 1
        # late: past the newest state (extrapolating); frozen: past the cap too, the picture stands still
        late += clock > newest
        late_episodes += clock > newest and not late_now
        late_now = clock > newest
        stuck = clock > newest + MAX_EXTRAPOLATE_S
        frozen += stuck
        episodes += stuck and not frozen_now
        frozen_now = stuck
        t += FRAME_S
    return {"frames": frames, "frozen_frames": frozen, "freezes": episodes, "frozen_s": round(frozen * FRAME_S, 1),
            "late_frames": late, "late_episodes": late_episodes, "late_s": round(late * FRAME_S, 1),
            "clock_snaps": snaps, "wrong_speed_pct": round(100.0 * off_speed / max(1, frames), 1)}


def _rss_mb() -> float:
    """This process's resident set (the server's: it ticks in-process), MiB; 0 without /proc."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024.0)
    except OSError:
        pass
    return 0.0


def _place_collections(long: list, ticks: list) -> list:
    """Each collection over 20 ms against the tick timeline: inside tick N, or
    between ticks N and N+1, with the gap between those two ticks' starts
    (the loop resets its schedule when behind, so tick_start_late misses it)."""
    placed = []
    for end, generation, ms, thread in long:
        start = end - ms / 1000.0
        where, tick, gap = "between", None, None
        for i, t in enumerate(ticks):
            if t["start"] <= start <= t["end"]:
                where, tick = "inside", i
                break
            if t["end"] <= start and (i + 1 == len(ticks) or ticks[i + 1]["start"] >= start):
                tick = i
                gap = round((ticks[i + 1]["start"] - t["start"]) * 1000.0) if i + 1 < len(ticks) else None
                break
        placed.append({"ms": round(ms, 1), "generation": generation, "thread": thread, "where": where, "tick": tick,
                       "next_tick_start_gap_ms": gap})
    return placed[:40]


def _memory_summary(samples: list) -> dict:
    if not samples:
        return {}
    return {"rss_start_mb": samples[0]["rss_mb"], "rss_end_mb": samples[-1]["rss_mb"],
            "rss_max_mb": max(s["rss_mb"] for s in samples), "tiles_end": samples[-1]["tiles"],
            "tiles_max": max(s["tiles"] for s in samples), "chunks_end": samples[-1]["chunks"],
            "every_30s": samples[::30]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--preset", default="Oulu")
    parser.add_argument("--osm-source", choices=("overpass", "pbf"), default=None)
    parser.add_argument("--osm-pbf-path", help="the local .osm.pbf for --osm-source pbf")
    parser.add_argument("--drive-s", type=float, default=180.0)
    parser.add_argument("--speed", type=float, default=20.0, help="m/s (20: 72 km/h)")
    parser.add_argument("--heading", type=float, default=0.0, help="radians, 0 east, 1.5708 north")
    parser.add_argument("--sample-ms", type=float, default=0.0, help="record the stack of ticks running longer than this")
    parser.add_argument("--json", type=Path, help="also write the result here (and the server log beside it)")
    parser.add_argument("--port", type=int, default=0,
                        help="listen here, for a Godot client to attach too (godot --headless --path godot -- "
                             "--skip-menu --port N --bench S); default: any free port")
    parser.add_argument("--client", nargs=2, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.client:
        return client(int(args.client[0]), args.client[1])

    log_path = args.json.with_suffix(".log") if args.json else Path(tempfile.gettempdir()) / "bench_map_jitter.log"
    logging.basicConfig(level=logging.INFO, filename=str(log_path), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.argv = ["bench", "--preset", args.preset, "--no-menu", "--game-mode", "gig_driver", "--no-historical-weather"] + (
        ["--osm-source", args.osm_source] if args.osm_source else []) + (
        ["--osm-pbf-path", args.osm_pbf_path] if args.osm_pbf_path else [])
    import theroadragetrip.server as server_module
    from theroadragetrip.performance import tune_interpreter
    from theroadragetrip.server.cli import parse_server_args

    tune_interpreter()  # as server/__main__.py
    server_args, config = parse_server_args()
    server = server_module.SimulationServer(server_args, config)
    streamer = server._map_streamer
    if streamer is None:
        parser.error("the map must grow: auto-fetch is off for this city")
    server._on_foot, server._home = False, None  # in the taxi; no Home preparation in the background
    server.start("127.0.0.1", args.port)

    current = [None]  # the running tick's record

    def timed(name, fn):
        def wrapper(*a, **k):
            w0, c0 = time.perf_counter(), time.thread_time()
            try:
                return fn(*a, **k)
            finally:
                rec = current[0]
                if rec is not None:
                    w, c = rec["phases"].get(name, (0.0, 0.0))
                    rec["phases"][name] = (w + (time.perf_counter() - w0) * 1000.0, c + (time.thread_time() - c0) * 1000.0)
        return wrapper

    @contextmanager
    def profile_section(name):
        started = time.perf_counter()
        try:
            yield
        finally:
            rec = current[0]
            if rec is not None:
                elapsed = (time.perf_counter() - started) * 1000.0
                rec.setdefault("sim_sections", {})[name] = rec.setdefault("sim_sections", {}).get(name, 0.0) + elapsed

    class FrameProfiler:
        section = staticmethod(profile_section)

    server_module._NullFrameProfiler.INSTANCE = FrameProfiler()

    # Attribute state-build time to the repeated serializers and nearby scans.
    from theroadragetrip import protocol
    from theroadragetrip.npc import NPCVehicleManager

    for helper in ("_npc_to_dict", "_pedestrian_to_dict", "shown_pedestrians", "_broken_hedges", "_knocked",
                   "_traffic_light_phases", "_live_roadworks"):
        original = getattr(protocol, helper)
        setattr(protocol, helper, timed("state." + helper, original))
    for helper in ("rebuild_spatial_grid", "_update_bike_thefts", "_advance_route_jobs", "_run_population_tick",
                   "_check_vehicle_collision"):
        setattr(NPCVehicleManager, helper, timed("npc." + helper, getattr(NPCVehicleManager, helper)))

    class PedestrianProfiler:
        def record(self, name, elapsed_ms):
            rec = current[0]
            if rec is not None:
                values = rec.setdefault("ped_internal", {})
                values[name] = values.get(name, 0.0) + elapsed_ms

    server.world.pedestrian_mgr.profiler = PedestrianProfiler()

    manager = streamer.manager
    server_module.advance_simulation = timed("simulation", server_module.advance_simulation)
    streamer.tick = timed("map_streamer", streamer.tick)
    manager.integrate_completed_tiles = timed("merge", manager.integrate_completed_tiles)
    manager.start_tile_streaming = timed("tile_streaming", manager.start_tile_streaming)
    server._apply_map_growth = timed("chunk_swap_and_resend", server._apply_map_growth)
    server._stream_map_chunks = timed("chunk_streaming", server._stream_map_chunks)
    server._broadcast_state = timed("state", server._broadcast_state)

    collections, gc_started = [], {}  # [end, generation, ms, thread] of every collection, any thread

    def gc_timer(phase, info):
        if phase == "start":
            gc_started[threading.get_ident()] = time.perf_counter()
        elif threading.get_ident() in gc_started:
            ms = (time.perf_counter() - gc_started.pop(threading.get_ident())) * 1000.0
            collections.append((time.monotonic(), info["generation"], ms, threading.current_thread().name))

    gc.callbacks.append(gc_timer)
    if args.sample_ms > 0:
        main_id = threading.main_thread().ident

        def sampler():
            while True:
                time.sleep(0.01)
                rec = current[0]
                if rec is not None and "stack" not in rec and time.perf_counter() - rec["began"] > args.sample_ms / 1000.0:
                    frames = sys._current_frames()
                    frame = frames.get(main_id)
                    if frame is not None:
                        rec["stack"] = " < ".join(f"{Path(f.filename).stem}:{f.name}:{f.lineno}"
                                                  for f in reversed(traceback.extract_stack(frame)[-12:]))
                        # What the other threads run meanwhile: the GIL holder a waiting tick waits for.
                        names = {t.ident: t.name for t in threading.enumerate()}
                        rec["others"] = {names.get(ident, str(ident)): " < ".join(
                            f"{Path(f.filename).stem}:{f.name}:{f.lineno}" for f in reversed(traceback.extract_stack(other)[-6:]))
                            for ident, other in frames.items() if ident not in (main_id, threading.get_ident())
                            and any(name in names.get(ident, "") for name in BACKGROUND)}

        threading.Thread(target=sampler, name="sampler", daemon=True).start()

    interval = 1.0 / server.tick_rate
    ticks = []
    collect = hasattr(server, "collect_between_ticks")  # as run_forever (older revisions lack it)

    def run(seconds, move=None):
        next_tick = time.monotonic()
        end = next_tick + seconds
        while time.monotonic() < end:
            if move is not None:
                move()
            rec = current[0] = {"began": time.perf_counter(), "start": time.monotonic(), "phases": {}}
            rec["late"] = (rec["start"] - next_tick) * 1000.0  # woke late: the GIL held elsewhere, or the OS
            cpu = time.thread_time()
            server.tick(interval)
            current[0] = None
            rec["wall"] = (time.perf_counter() - rec["began"]) * 1000.0
            rec["cpu"] = (time.thread_time() - cpu) * 1000.0
            rec["end"] = time.monotonic()
            rec["background"] = sorted({name for t in threading.enumerate() for name in BACKGROUND if name in t.name})
            rec["busy"] = bool(rec["background"] or streamer.status() or server._map_growth)
            rec["population"] = {"npcs": len(server.world.npc_manager.vehicles),
                                  "moving_npcs": sum(abs(v.speed) > 0.5 for v in server.world.npc_manager.vehicles),
                                  "pedestrians": len(server.world.pedestrian_mgr.pedestrians)}
            if len(ticks) % server.tick_rate == 0:  # once a second: resident memory and what is held
                rec["memory"] = {"rss_mb": _rss_mb(), "tiles": len(streamer.manager.loaded_tiles),
                                 "chunks": len(server._chunks_index._chunks)}
            ticks.append(rec)
            next_tick += interval
            if collect:
                server.collect_between_ticks(next_tick - time.monotonic())  # as run_forever
            wait = next_tick - time.monotonic()
            if wait > 0:
                time.sleep(wait)  # computed once: re-reading the clock could make it negative
            else:
                next_tick = time.monotonic()  # behind: no catching up in a burst (run_forever)

    client_log = tempfile.NamedTemporaryFile(prefix="bench_map_jitter_", suffix=".jsonl", delete=False).name
    child = subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "--client", str(server.port), client_log])
    while not server._clients:
        time.sleep(0.01)
    run(3.0)  # the start: the first chunks and the initial tile window
    for _ in range(120):
        if not (streamer.status() or server._map_growth):
            break
        run(1.0)
    ticks.clear()
    car, moved = server.car, [0.0]
    x0, y0 = car.x, car.y

    def move():
        moved[0] += args.speed * interval
        car.x, car.y = x0 + moved[0] * math.cos(args.heading), y0 + moved[0] * math.sin(args.heading)
        car.heading, car.speed = args.heading, args.speed

    run(args.drive_s, move)
    tracked, frozen = len(gc.get_objects()), gc.get_freeze_count()
    gc.unfreeze()
    garbage = gc.collect()  # cyclic garbage left at the end (a frozen object is never collected)
    child.terminate()
    child.wait()
    rows = []
    with open(client_log) as log:
        for line in log:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass  # the last line, cut by terminate()
    os.unlink(client_log)

    t0, t1 = ticks[0]["start"], ticks[-1]["end"]
    in_window = [c for c in collections if t0 <= c[0] <= t1]
    full = [c for c in in_window if c[1] == 2]
    young = [c[2] for c in in_window if c[1] < 2]
    slow = [t for t in ticks if t["wall"] > interval * 1000.0]
    phases = {}
    for t in slow:
        ph = {name: v[0] for name, v in t["phases"].items()}
        ph["map_sync"] = ph.get("map_streamer", 0.0) - ph.get("merge", 0.0) - ph.get("tile_streaming", 0.0)
        ph.pop("map_streamer", None)
        for name, ms in ph.items():
            phases[name] = phases.get(name, 0.0) + ms
        for name, ms in t.get("sim_sections", {}).items():
            phases["simulation." + name] = phases.get("simulation." + name, 0.0) + ms
        for name, ms in t.get("ped_internal", {}).items():
            phases[name] = phases.get(name, 0.0) + ms
        for name, (wall_ms, _cpu_ms) in t["phases"].items():
            if name.startswith("npc."):
                phases[name] = phases.get(name, 0.0) + wall_ms

    def overlapping(t):
        return [[round(c[2]), c[1], c[3]] for c in collections
                if c[0] >= t["start"] and c[0] - c[2] / 1000.0 <= t["end"]]

    def tick_stats(rows_):
        walls = [t["wall"] for t in rows_]
        return {"ticks": len(walls), "p50": pct(walls, .5), "p95": pct(walls, .95), "p99": pct(walls, .99),
                "max": round(max(walls, default=0.0), 1), "over_33ms": sum(w > 1000.0 / 30.0 for w in walls),
                "over_50ms": sum(w > 50 for w in walls),
                "over_100ms": sum(w > 100 for w in walls)}

    waits = {}
    for t in ticks:
        waits.setdefault(",".join(t["background"]) or "-", []).append(t["wall"] - t["cpu"])
    states = [r for r in rows if r[0] == "state" and t0 <= r[1] <= t1 + 1.0]
    gaps = [(b[1] - a[1]) * 1000.0 for a, b in zip(states, states[1:])]
    worst_gaps = sorted(((b[1] - a[1], a[1]) for a, b in zip(states, states[1:])), reverse=True)[:5]
    late = [t["late"] for t in ticks]
    have = {r[3] for r in rows if r[0] == "chunk" and r[1] < t0}
    sent = resent = size = 0
    for r in rows:
        if r[1] < t0:
            continue
        if r[0] == "unload":
            have.discard(r[3])
        elif r[0] == "chunk":
            sent, size, resent = sent + 1, size + r[2], resent + (r[3] in have)
            have.add(r[3])
    result = {
        "preset": args.preset, "osm_source": server_args.osm_source, "drive_s": args.drive_s, "speed_mps": args.speed,
        "heading": args.heading, "distance_m": round(moved[0]),
        "ticks": tick_stats(ticks), "tick_start_late_ms": {"p99": pct(late, .99), "max": round(max(late, default=0.0)),
                                                         "over_20ms": sum(ms > 20 for ms in late)},
        "map_idle": tick_stats([t for t in ticks if not t["busy"]]),
        "map_busy": tick_stats([t for t in ticks if t["busy"]]),
        "busy_pct": round(100.0 * sum(t["busy"] for t in ticks) / len(ticks), 1),
        "waiting_ms_per_tick": {k: {"mean": round(sum(v) / len(v), 1), "p95": pct(v, .95), "ticks": len(v)} for k, v in waits.items()},
        "slow_ticks": {"count": len(slow), "wall_ms": round(sum(t["wall"] for t in slow)),
                       "waiting_ms": round(sum(t["wall"] - t["cpu"] for t in slow)),
                       "phases_ms": {k: round(v) for k, v in sorted(phases.items(), key=lambda kv: -kv[1])}},
        "gc": {"count": len(in_window), "max_ms": round(max((c[2] for c in in_window), default=0.0)),
                    "total_ms": round(sum(c[2] for c in in_window)),
                    "by_generation": {str(g): {"count": sum(c[1] == g for c in in_window),
                                                "total_ms": round(sum(c[2] for c in in_window if c[1] == g)),
                                                "max_ms": round(max((c[2] for c in in_window if c[1] == g), default=0.0))}
                                      for g in range(3)},
                    "longest_over_10ms": [[round(c[2], 1), c[1], c[3]] for c in sorted(in_window, key=lambda c: c[2], reverse=True)[:20]]},
        "long_collections": _place_collections([c for c in in_window if c[2] > 20.0], ticks),
        "tick_start_gap_max_ms": round(max(((b["start"] - a["start"]) * 1000.0 for a, b in zip(ticks, ticks[1:])), default=0.0)),
        "full_gc": {"count": len(full), "max_ms": round(max((c[2] for c in full), default=0.0)),
                    "total_ms": round(sum(c[2] for c in full)), "by_thread": sorted({c[3].split(" (")[0] for c in full}),
                    "tracked_objects_at_end": tracked, "frozen_at_end": frozen, "cyclic_garbage_at_end": garbage},
        "young_gc": {"count": len(young), "max_ms": round(max(young, default=0.0), 1), "total_ms": round(sum(young)),
                     "over_10ms": sum(ms > 10 for ms in young)},
        "chunks": {"sent": sent, "resent": resent, "mb": round(size / 1e6, 1)},
        "memory": _memory_summary([t["memory"] for t in ticks if "memory" in t and t0 <= t["start"]]),
        "client": {"states": len(states), "gap_p99_ms": pct(gaps, .99), "gap_max_ms": round(max(gaps, default=0.0)),
                   "gaps_over_100ms": sum(g > 100 for g in gaps), **replay(states),
                   "worst_gaps": [{"t_s": round(at - t0, 1), "ms": round(gap * 1000.0)} for gap, at in worst_gaps]},
        "worst_ticks": [{"t_s": round(t["start"] - t0, 1), "wall_ms": round(t["wall"]), "cpu_ms": round(t["cpu"]),
                         "phases": {k: round(v[0]) for k, v in sorted(t["phases"].items(), key=lambda kv: -kv[1][0])[:3]},
                         "gc": overlapping(t), "sim_sections": t.get("sim_sections", {}),
                         "ped_internal": t.get("ped_internal", {}),
                         "population": t.get("population", {}),
                         **({"stack": t["stack"]} if "stack" in t else {}), **({"others": t["others"]} if t.get("others") else {})}
                        for t in sorted(ticks, key=lambda t: -t["wall"])[:12]],
        "log": str(log_path),
    }
    print(json.dumps(result, indent=2))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
