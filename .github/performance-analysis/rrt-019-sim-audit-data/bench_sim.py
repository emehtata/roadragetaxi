"""Simulation-server tick audit (rrt-019-audit-sim): the real headless server
at a map spot, ticked at 30 Hz back to back, with per-phase timing.

    PYTHONPATH=src .venv/bin/python .github/performance-analysis/rrt-019-sim-audit-data/bench_sim.py \
        --at 427400 7210500 --city Oulu --start-time 2026-10-23T17:00 \
        --warmup 60 --seconds 120 --speed 0 --seed 1 --out result.json [--cprofile prof.out]

Measures per tick: wall and thread-CPU time, the advance_simulation sections
(physics, collisions, trains, trams, taxi, npc, traffic, pedestrians - not
nested), the server phases around it (broadcast, chunk streaming, map
streamer, navigation ...), GC pauses by generation, and entity counts.
Section times are inclusive of their callees; the phases do not overlap.
Audit-only: monkeypatches the server instance, production code is untouched.
"""
import argparse
import gc
import json
import math
import random
import resource
import sys
import time
from collections import defaultdict
from contextlib import contextmanager

if __name__ != "__main__":  # the server's helper process re-imports this file
    raise SystemExit

p = argparse.ArgumentParser()
p.add_argument("--at", nargs=2, type=float, required=True)
p.add_argument("--city", default="Oulu")
p.add_argument("--start-time")
p.add_argument("--heading", type=float, default=0.0)
p.add_argument("--speed", type=float, default=0.0)
p.add_argument("--warmup", type=float, default=30.0, help="simulated seconds before measuring")
p.add_argument("--seconds", type=float, default=60.0)
p.add_argument("--box-km", type=float, default=3.0)
p.add_argument("--view", nargs=2, type=float, default=(142.0, 80.0))
p.add_argument("--seed", type=int, default=1)
p.add_argument("--fare", action="store_true", help="accept an offer: game time 1:1 instead of 60x")
p.add_argument("--cprofile")
p.add_argument("--sample-ms", type=float, default=0.0,
               help="sample the tick thread's stack every N ms; ticks over 25 ms keep their samples (adds overhead)")
p.add_argument("--out")
A = p.parse_args()

random.seed(A.seed)
from theroadragetrip.geo import meters_to_latlon  # noqa: E402

x0, y0 = A.at
lat, lon = meters_to_latlon(x0, y0)
half = A.box_km / 2 / 111.0
half_lon = half / math.cos(math.radians(lat))
sys.argv = ["prog", "--preset", A.city, "--bbox", f"{lat - half},{lon - half_lon},{lat + half},{lon + half_lon}",
            "--no-historical-weather", "--no-intercity-fares", "--osm-source", "overpass"]
if A.start_time:
    sys.argv += ["--start-time", A.start_time]

from theroadragetrip.server import SimulationServer, _NullFrameProfiler  # noqa: E402
from theroadragetrip.server.cli import parse_server_args  # noqa: E402
from theroadragetrip.performance import tune_interpreter  # noqa: E402

tune_interpreter()  # as server/__main__.py
t_load = time.perf_counter()
args, config = parse_server_args()
server = SimulationServer(args, config)
load_s = time.perf_counter() - t_load
server._fares_opened = True
server._set_fares_open(True)
car = server.car
car.x, car.y, car.heading, car.speed = x0, y0, A.heading, 0.0
vw, vh = A.view
server._visible_bounds = lambda: (car.x - vw / 2, car.y - vh / 2, car.x + vw / 2, car.y + vh / 2)

# --- instrumentation -------------------------------------------------------
tick_sections = defaultdict(float)


@contextmanager
def _section(_self, name):
    t = time.perf_counter()
    try:
        yield
    finally:
        tick_sections["sim." + name] += time.perf_counter() - t


_NullFrameProfiler.section = _section


def timed(obj, attr, label):
    fn = getattr(obj, attr)

    def wrapper(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            tick_sections[label] += time.perf_counter() - t
    setattr(obj, attr, wrapper)


import theroadragetrip.server as srv_mod  # noqa: E402
from theroadragetrip import protocol  # noqa: E402

_last_msg = {}
_build = protocol.build_state_message


def _capture(**k):
    _last_msg["m"] = _build(**k)
    return _last_msg["m"]


protocol.build_state_message = _capture  # timed by srv.broadcast_state; encoded below, outside the tick
timed(srv_mod, "advance_simulation", "advance_simulation")
for attr in ("_broadcast_state", "_stream_map_chunks", "_apply_map_growth", "_update_outside",
             "_update_speed_cameras", "_prepare_home_map", "_apply_incoming_messages", "_update_sports",
             "_tyre_mark"):
    timed(server, attr, "srv." + attr.lstrip("_"))
timed(server.navigation, "update", "srv.navigation")
timed(server.world.weather, "update", "srv.weather")
if server._map_streamer is not None:
    timed(server._map_streamer, "tick", "srv.map_streamer")
w = server.world
timed(w.npc_manager, "discard_outside", "npc.discard_outside")
timed(w.pedestrian_mgr, "discard_outside", "ped.discard_outside")
for attr in ("ensure_taxi_stop_waiter", "ensure_sports_players"):
    timed(w.pedestrian_mgr, attr, "ped." + attr)
timed(w.competitor_dispatcher, "update", "competitors")
if getattr(w, "arena_crowds", None) is not None:
    timed(w.arena_crowds, "update", "arena_crowds")

class _StageRecorder:  # pedestrian.py's own _record stages (inside sim.pedestrians)
    def record(self, name, ms):
        if not name.endswith(":wait"):
            tick_sections["ped_stage." + name.split(":", 1)[-1]] += ms / 1000


w.pedestrian_mgr.profiler = _StageRecorder()

gc_pauses = []
_gc_start = {}


def _gc_cb(phase, info):
    if phase == "start":
        _gc_start["t"] = time.perf_counter()
    else:
        gc_pauses.append((info["generation"], time.perf_counter() - _gc_start.get("t", time.perf_counter())))


gc.callbacks.append(_gc_cb)


def counts():
    npcs = w.npc_manager.vehicles
    rail = getattr(w, "railway_mgr", None)
    trams = getattr(w, "tram_mgr", None)
    return {
        "npcs": len(npcs),
        "npcs_moving": sum(1 for v in npcs if abs(v.car.speed) > 0.5),
        "pedestrians": len(w.pedestrian_mgr.pedestrians),
        "residents": len(getattr(getattr(w, "residents", None), "residents", {}) or {}),
        "trains": len(getattr(rail, "trains", ()) or ()) if rail else 0,
        "trams": len(getattr(trams, "trams", ()) or ()) if trams else 0,
        "ways": len(w.ways),
        "buildings": len(w.buildings),
        "parking_spaces": len(getattr(w, "parking_spaces", ()) or ()),
    }


def rss_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024
    return 0.0


DT = 1 / 30


def step():
    car.x += math.cos(car.heading) * A.speed * DT
    car.y += math.sin(car.heading) * A.speed * DT
    car.speed = A.speed
    server.tick(DT)


print(f"loaded in {load_s:.1f}s; {counts()}", flush=True)
for _ in range(int(A.warmup * 30)):
    step()
if A.fare:  # game time runs 1:1 during a fare
    for _ in range(30 * 120):
        if w.taxi_mgr.phone_items() and w.taxi_mgr.accept_offer(0, car.x, car.y):
            break
        step()
    print("fare active:", w.taxi_mgr.has_active_job(), flush=True)
print(f"warm; {counts()}", flush=True)

sampler_on = A.sample_ms > 0
cur_tick = [-1]
tick_samples = defaultdict(list)


def _sampler(main_id):
    import threading  # noqa: F401
    while sampler_on:
        f = sys._current_frames().get(main_id)
        stack = []
        while f is not None and len(stack) < 40:
            co = f.f_code
            if "theroadragetrip" in co.co_filename:
                stack.append(f"{co.co_filename.split('theroadragetrip/')[-1]}:{co.co_name}")
            f = f.f_back
        tick_samples[cur_tick[0]].append(tuple(stack))
        time.sleep(A.sample_ms / 1000)


if sampler_on:
    import threading
    threading.Thread(target=_sampler, args=(threading.get_ident(),), daemon=True).start()

prof = None
if A.cprofile:
    import cProfile
    prof = cProfile.Profile()
ticks = []
gc_pauses.clear()
samples = []
rss0 = rss_mb()
objs0 = len(gc.get_objects())
n = int(A.seconds * 30)
if prof:
    prof.enable()
for i in range(n):
    tick_sections.clear()
    cur_tick[0] = i
    g0 = len(gc_pauses)
    c0 = time.thread_time()
    t0 = time.perf_counter()
    step()
    wall = time.perf_counter() - t0
    cpu = time.thread_time() - c0
    e0 = time.perf_counter()
    blob = protocol.encode(_last_msg["m"])  # what transport.py's writer thread does per client
    rec = {"wall": wall, "cpu": cpu, "sec": dict(tick_sections), "encode": time.perf_counter() - e0, "bytes": len(blob),
           "gc": [p for p in gc_pauses[g0:]]}
    if i % 30 == 0:
        rec["counts"] = counts()
    if wall < 0.025:
        tick_samples.pop(i, None)
    ticks.append(rec)
if prof:
    prof.disable()
    prof.dump_stats(A.cprofile)
rss1 = rss_mb()
objs1 = len(gc.get_objects())


def pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))] if s else 0.0


walls = [t["wall"] for t in ticks]
summary = {
    "args": vars(A), "fare_active_end": w.taxi_mgr.has_active_job(), "python": sys.version, "load_s": load_s,
    "ticks": len(ticks),
    "wall_ms": {k: 1000 * pct(walls, q) for k, q in (("p50", .5), ("p95", .95), ("p99", .99), ("max", 1.0))},
    "wall_mean_ms": 1000 * sum(walls) / len(walls),
    "cpu_mean_ms": 1000 * sum(t["cpu"] for t in ticks) / len(ticks),
    "over_budget_pct": 100 * sum(1 for x in walls if x > DT) / len(walls),
    "over_half_budget_pct": 100 * sum(1 for x in walls if x > DT / 2) / len(walls),
    "encode_ms": {"mean": 1000 * sum(t["encode"] for t in ticks) / len(ticks), "max": 1000 * max(t["encode"] for t in ticks)},
    "state_bytes": {"mean": sum(t["bytes"] for t in ticks) / len(ticks), "max": max(t["bytes"] for t in ticks)},
    "sections_mean_ms": {},
    "sections_max_ms": {},
    "gc": {}, "rss_mb": [rss0, rss1], "gc_objects": [objs0, objs1],
    "counts_first": next(t["counts"] for t in ticks if "counts" in t),
    "counts_last": [t["counts"] for t in ticks if "counts" in t][-1],
    "counts_mean": {},
    "maxrss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
}
keys = sorted({k for t in ticks for k in t["sec"]})
for k in keys:
    vals = [t["sec"].get(k, 0.0) for t in ticks]
    summary["sections_mean_ms"][k] = round(1000 * sum(vals) / len(vals), 3)
    summary["sections_max_ms"][k] = round(1000 * max(vals), 2)
for gen in (0, 1, 2):
    ps = [d for t in ticks for g, d in t["gc"] if g == gen]
    summary["gc"][gen] = {"count": len(ps), "total_ms": 1000 * sum(ps), "max_ms": 1000 * max(ps, default=0)}
cs = [t["counts"] for t in ticks if "counts" in t]
for k in cs[0]:
    summary["counts_mean"][k] = sum(c[k] for c in cs) / len(cs)
# worst ticks with their composition
worst = sorted(range(len(ticks)), key=lambda i: -ticks[i]["wall"])[:8]
summary["worst"] = [{"i": i, "wall_ms": 1000 * ticks[i]["wall"], "cpu_ms": 1000 * ticks[i]["cpu"],
                     "gc": ticks[i]["gc"],
                     "sec_ms": {k: round(1000 * v, 2) for k, v in sorted(ticks[i]["sec"].items(), key=lambda kv: -kv[1])[:6]}}
                    for i in worst]
summary["npc_diag"] = {k: v for k, v in (getattr(w.npc_manager, "population_diagnostics", {}) or {}).items()
                       if isinstance(v, (int, float))}
rjs = getattr(w.npc_manager, "route_job_stats", None)
if isinstance(rjs, dict):
    summary["route_job_stats"] = {k: v for k, v in rjs.items() if isinstance(v, (int, float, dict))}
if sampler_on:
    # per long tick: the innermost project frames' share of its samples, and
    # (inclusive) every project function on those stacks
    long_ticks = []
    incl = defaultdict(int)
    leaf = defaultdict(int)
    total = 0
    for i, stacks in tick_samples.items():
        if i < 0 or not stacks:
            continue
        total += len(stacks)
        for st in stacks:
            if st:
                leaf[st[0]] += 1
            for fn in set(st):
                incl[fn] += 1
        top = defaultdict(int)
        for st in stacks:
            for fn in set(st[:6]):
                top[fn] += 1
        long_ticks.append({"i": i, "wall_ms": 1000 * ticks[i]["wall"], "samples": len(stacks),
                           "top": sorted(top.items(), key=lambda kv: -kv[1])[:12]})
    summary["sampled_long_ticks"] = sorted(long_ticks, key=lambda t: -t["wall_ms"])[:25]
    summary["sampled_inclusive"] = sorted(incl.items(), key=lambda kv: -kv[1])[:60]
    summary["sampled_leaf"] = sorted(leaf.items(), key=lambda kv: -kv[1])[:40]
    summary["sampled_total"] = total
out = json.dumps(summary, indent=1, default=str)
print(out)
if A.out:
    open(A.out, "w").write(out)
