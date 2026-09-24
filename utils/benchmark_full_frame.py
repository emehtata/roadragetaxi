"""Full real-frame profiling harness (bin-loader-v2.md): runs the actual
interactive main() game loop in-process, with a dummy SDL driver and
synthetic input, capturing every FrameProfiler section per frame -
simulation and every render layer, not just roads. See
utils/benchmark_road_rendering.py for the roads-only benchmark this
complements; this one answers "what's the real bottleneck across the
WHOLE frame", which an isolated draw_ways() call can't show.

bin-loader-v4.md extends this in place (rather than building a parallel
profiling framework) with: per-frame metrics capture (car/tile position),
GC-time attribution per frame, and a spike-frame decomposition report for
frames past a threshold - needed to explain the ~440-560ms frames left
after bin-loader-v3's incremental map sync.

Run with: PYTHONPATH=src:. python utils/benchmark_full_frame.py [city ...]
Defaults to oulu (dense) and rovaniemi (sparse) if no city is given.
"""

import gc
import os
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import statistics
import sys
from collections import defaultdict

import pygame

pygame.init()

import theroadragetrip.performance as performance_module

# Capture every frame's section/metric breakdown as advance() rotates them
# out, instead of touching main()'s internals - it already calls
# frame_profiler.advance(raw_frame_ms) once per real loop iteration.
_captured: list[dict] = []
_real_advance = performance_module.FrameProfiler.advance

# Counts real gameplay-loop iterations only (one frame_profiler.advance()
# call per real `while running:` iteration in main.py) - deliberately NOT
# the same as counting pygame.event.get() calls (bin-loader-v4.md #8/#16
# regression): _wait_for_active_tile_fetch's own blocking loading-screen
# loop also polls pygame.event.get() every ~33ms while a fetch is in
# flight, but never touches frame_profiler at all. The original harness
# keyed "how many frames have we driven"/"when do we stop" off the event-poll
# count, so a multi-second loading-screen wait silently ate into the
# requested drive-frame budget - the car could still be stationary at
# warmup+100 events in. Keying both off real loop iterations instead makes
# "frames=N" mean N real ticks of actual driving.
_gameplay_frame = [0]

# GC time attribution (bin-loader-v4.md #11): gc.callbacks fires at the
# start/stop of every collection, wherever in the frame it happens to run -
# attribute its wall time to whichever real loop iteration is current when
# it fires, so a spike frame's report can show "N ms was GC" instead of
# silently folding it into "unaccounted" time.
_gc_time_by_frame: dict[int, float] = defaultdict(float)
_gc_start = [None]
# bin-loader-v10.md: per-generation counts/pauses, and for each (rare)
# generation-2 collection its pause, objects collected and RSS. Cheap: no
# object enumeration unless V10_GC_OBJECTS=1 (diagnostic runs only).
_gc_by_gen = {gen: {"count": 0, "ms": 0.0, "max_ms": 0.0, "collected": 0, "uncollectable": 0} for gen in range(3)}
_gc_full_events: list[dict] = []
_GC_COUNT_OBJECTS = os.environ.get("V10_GC_OBJECTS") == "1"


def _rss_mb() -> float:
    try:
        with open("/proc/self/statm") as statm:
            return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
    except OSError:
        return float("nan")


def _gc_callback(phase, info):
    # Interpreter shutdown can trigger a final collection after module
    # globals (including `time`) are already torn down - guard rather than
    # let that print shutdown noise for an already-finished benchmark run.
    try:
        if phase == "start":
            _gc_start[0] = time.perf_counter()
        elif phase == "stop" and _gc_start[0] is not None:
            ms = (time.perf_counter() - _gc_start[0]) * 1000.0
            _gc_time_by_frame[_gameplay_frame[0]] += ms
            _gc_start[0] = None
            stats = _gc_by_gen[info["generation"]]
            stats["count"] += 1
            stats["ms"] += ms
            stats["max_ms"] = max(stats["max_ms"], ms)
            stats["collected"] += info["collected"]
            stats["uncollectable"] += info["uncollectable"]
            if info["generation"] == 2:
                _gc_full_events.append({
                    "frame": _gameplay_frame[0], "ms": ms, "collected": info["collected"],
                    "rss_mb": _rss_mb(),
                    "tracked": len(gc.get_objects()) if _GC_COUNT_OBJECTS else None,
                })
    except Exception:
        pass


gc.callbacks.append(_gc_callback)


# bin-loader-v10.md experiment switch (benchmark only, game defaults
# untouched): V10_GC=base | thresh:A,B,C | collect_sync | freeze_start |
# freeze_sync | freeze_nc (freeze without collecting, at start and after
# each sync). "sync" hooks run right after the pedestrian map-sync commit,
# the last heavy map-sync stage.
_GC_STRATEGY = os.environ.get("V10_GC", "base")
# main() sets the game's own GC_THRESHOLDS; a thresh:A,B,C experiment
# overrides them from the first gameplay frame on.
_GC_THRESHOLD_OVERRIDE = next(
    (tuple(int(v) for v in part.split(":", 1)[1].split(",")) for part in _GC_STRATEGY.split("+")
     if part.startswith("thresh:")),
    None,
)
_GC_FREEZE_NC = "freeze_nc" in _GC_STRATEGY.split("+")


def _after_map_sync_commit():
    if _GC_STRATEGY == "collect_sync":
        gc.collect()
    elif _GC_STRATEGY == "freeze_sync":
        gc.collect()
        gc.freeze()
    elif _GC_FREEZE_NC:
        gc.freeze()


def _capturing_advance(self, real_frame_ms=None):
    if _GC_THRESHOLD_OVERRIDE is not None and _gameplay_frame[0] == 0:
        gc.set_threshold(*_GC_THRESHOLD_OVERRIDE)
    if _GC_STRATEGY == "freeze_start" and _gameplay_frame[0] == 0:
        gc.collect()
        gc.freeze()
    elif _GC_FREEZE_NC and _gameplay_frame[0] == 0:
        gc.freeze()
    # GC time for this frame was keyed under the index current while it ran
    # (before this increment) - label the entry with that same index.
    frame_index = _gameplay_frame[0]
    _gameplay_frame[0] += 1
    if self.enabled and self.sections:
        _captured.append({
            "frame_ms": real_frame_ms,
            "frame_index": frame_index,
            "sections": dict(self.sections),
            "metrics": dict(self.metrics),
        })
    _real_advance(self, real_frame_ms=real_frame_ms)


performance_module.FrameProfiler.advance = _capturing_advance

# Force profiling on from frame 1 instead of scripting an F3 keypress
# through the "awaiting_start" gate (main.py:1409-1414 swallows the very
# first KEYDOWN after warmup purely to dismiss the start overlay, so a
# single injected F3 event never reaches the real toggle). The overlay
# itself only affects which HUD is drawn, not simulation or rendering, so
# nothing else needs a synthetic keypress either.
_real_profiler_init = performance_module.FrameProfiler.__init__


def _auto_enabled_init(self, *args, **kwargs):
    _real_profiler_init(self, *args, **kwargs)
    self.enabled = True


performance_module.FrameProfiler.__init__ = _auto_enabled_init

# Keep the gameplay PedestrianManager (not the CyclistManager subclass) so
# its sync/route counters can be reported (bin-loader-v9.md).
from theroadragetrip import pedestrian as pedestrian_module  # noqa: E402

_pedestrian_managers = []
_real_pedestrian_init = pedestrian_module.PedestrianManager.__init__


def _tracking_pedestrian_init(self, *args, **kwargs):
    _real_pedestrian_init(self, *args, **kwargs)
    if type(self) is pedestrian_module.PedestrianManager:
        _pedestrian_managers.append(self)


pedestrian_module.PedestrianManager.__init__ = _tracking_pedestrian_init
_real_commit_incremental_sync = pedestrian_module.PedestrianManager._commit_incremental_sync


def _hooked_commit_incremental_sync(self):
    _real_commit_incremental_sync(self)
    if _pedestrian_managers and self is _pedestrian_managers[-1]:
        _after_map_sync_commit()


pedestrian_module.PedestrianManager._commit_incremental_sync = _hooked_commit_incremental_sync

# The game reads continuous key state (pygame.key.get_pressed()) for
# driving, not discrete events - a plain defaultdict stands in for the
# real ScancodeWrapper (both support keys[K_x] -> bool).
_held_keys = defaultdict(bool)
pygame.key.get_pressed = lambda: _held_keys

_stop_after_frame = [None]
_drive = [False]
_entry_stage = [0]  # bin-loader-v4.md: see comment below - the player spawns on_foot
WARMUP_FRAMES = 110  # > the 1.5s/~90-frame "awaiting_start" gate (main.py); only paces when driving starts


def _fake_event_get(*_args, **_kwargs):
    events = []
    # bin-loader-v4.md regression: the player spawns on_foot=True (main.py)
    # - holding K_UP alone (the original harness's whole "driving"
    # mechanism) is forced to zero throttle the entire time
    # (`throttle = 0.0 if on_foot ... else command.throttle`, simulation.py)
    # until the 'F' get-in-car key is pressed once. Undetected until now:
    # car_x/car_y metrics showed the "Driving" scenario had never actually
    # moved the car in ANY prior benchmark run - confirmed via a distinct
    # per-frame position probe. Two synthetic KEYDOWNs are needed, one
    # frame apart, not one: the very first KEYDOWN once warmup clears is
    # unconditionally consumed by main.py's own "awaiting_start" dismiss
    # handler (it `continue`s before ever checking which key it was), so a
    # single injected K_f lands on- that dismiss instead of the real
    # get-in-car handler. Send a throwaway key first, then K_f one frame
    # later, then start holding K_UP.
    if _drive[0] and _gameplay_frame[0] > WARMUP_FRAMES:
        if _entry_stage[0] == 0:
            _entry_stage[0] = 1
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        elif _entry_stage[0] == 1:
            _entry_stage[0] = 2
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
    # Hold "forward" once the car has actually been entered, same held-key
    # mechanism a real player uses (main.py reads pygame.key.get_pressed()
    # every frame, not discrete key events) - released again for stationary
    # runs. Gated on _gameplay_frame (real loop iterations), not an
    # event-poll count - see its own comment above.
    _held_keys[pygame.K_UP] = _drive[0] and _entry_stage[0] >= 2
    if _stop_after_frame[0] is not None and _gameplay_frame[0] >= _stop_after_frame[0]:
        events.append(pygame.event.Event(pygame.QUIT))
    return events


pygame.event.get = _fake_event_get


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[index]


# Sections recorded as a wrapping total around a group of children (see
# main.py: "map_sync" wraps whichever single map_sync:* stage ran that
# frame; "rendering" wraps every render:* stage) - bin-loader-v4.md #10.
# Excluding these from a frame's "accounted for" sum avoids double-counting
# a stage as both itself and part of its own parent.
_PARENT_SECTIONS = {"rendering", "map_sync", "render:illuminated_windows", "render:lighting:street_lights", "render:lighting:street_light_cache", "render:lighting:street_lights:prepare", "pedestrians", "map_sync:pedestrians", "pedestrians:wait", "map_sync:pedestrians:wait", "pedestrians:route_nearest", "pedestrians:route_search"}  # last is nested inside render:lighting (bin-loader-v6.md)


def _exclusive_sections(sections: dict[str, float]) -> dict[str, float]:
    return {name: ms for name, ms in sections.items() if name not in _PARENT_SECTIONS}


def _print_spike_frames(entries: list[dict], threshold_ms: float, limit: int = 12) -> None:
    spikes = [e for e in entries if e["frame_ms"] is not None and e["frame_ms"] >= threshold_ms]
    print(f"  frames >= {threshold_ms:.0f}ms: {len(spikes)}")
    for entry in spikes[:limit]:
        exclusive = _exclusive_sections(entry["sections"])
        accounted = sum(exclusive.values())
        gc_ms = _gc_time_by_frame.get(entry["frame_index"], 0.0)
        m = entry["metrics"]
        largest = max(exclusive.items(), key=lambda kv: kv[1]) if exclusive else (None, 0.0)
        print(
            f"    frame#{entry['frame_index']:<5} {entry['frame_ms']:>8.1f}ms  "
            f"car=({m.get('car_x', '?')},{m.get('car_y', '?')})  "
            f"tile=({m.get('current_tile_x', '?')},{m.get('current_tile_y', '?')})  "
            f"tiles_pending={m.get('tiles_pending', '?')}  "
            f"tile_load={m.get('tile_load_ms', 0):.1f}ms tile_integ={m.get('tile_integration_ms', 0):.1f}ms "
            f"tile_unload={m.get('tile_unload_ms', 0):.1f}ms  gc={gc_ms:.1f}ms"
        )
        print(f"      largest section: {largest[0]} ({largest[1]:.1f}ms)")
        print(f"      accounted (sum of exclusive sections): {accounted:.1f}ms  "
              f"unaccounted: {entry['frame_ms'] - accounted:.1f}ms")
        for name, ms in sorted(exclusive.items(), key=lambda kv: -kv[1]):
            if ms >= 1.0:
                print(f"        {name:<32} {ms:>8.2f}ms")
    if len(spikes) > limit:
        print(f"    ... ({len(spikes) - limit} more not shown)")
    print()


def _print_tile_transitions(entries: list[dict]) -> None:
    with_tiles = [e for e in entries if "current_tile_x" in e["metrics"]]
    transitions = []
    prev_tile = None
    for e in with_tiles:
        tile = (e["metrics"]["current_tile_x"], e["metrics"]["current_tile_y"])
        if prev_tile is not None and tile != prev_tile:
            transitions.append(e)
        prev_tile = tile
    print(f"  tile-boundary transitions: {len(transitions)}")
    for e in transitions:
        print(f"    frame#{e['frame_index']:<5} -> tile={e['metrics'].get('current_tile_x')},"
              f"{e['metrics'].get('current_tile_y')}  frame_ms={e['frame_ms']:.1f}")
    print()


def run_scenario(name: str, city: str, frames: int, drive: bool, spike_threshold_ms: float | None = None) -> None:
    import theroadragetrip.main as main_module
    from theroadragetrip.render import roads as roads_module

    cache_stats_before = dict(roads_module._street_light_cache_stats)

    _captured.clear()
    _pedestrian_managers.clear()
    _gc_time_by_frame.clear()
    _gc_full_events.clear()
    for stats in _gc_by_gen.values():
        stats.update(count=0, ms=0.0, max_ms=0.0, collected=0, uncollectable=0)
    _held_keys.clear()
    _gameplay_frame[0] = 0
    _entry_stage[0] = 0
    _drive[0] = drive
    _stop_after_frame[0] = WARMUP_FRAMES + frames + 2

    sys.argv = ["prog", "--preset", city, "--no-menu", "--osm-source", "pbf"]
    main_module.main()

    frames_recorded = [f for f in _captured if f["frame_ms"] is not None]
    if not frames_recorded:
        print(f"=== {name} ===\n  no frames captured (debug HUD toggle likely missed) - skipping\n")
        return

    frame_ms = [f["frame_ms"] for f in frames_recorded]
    totals: dict[str, list[float]] = defaultdict(list)
    for entry in frames_recorded:
        for section, ms in entry["sections"].items():
            totals[section].append(ms)

    print(f"=== {name} ({city}) ===")
    print(f"  frames captured: {len(frames_recorded)}")
    print(f"  frame time avg/p95/worst (ms): "
          f"{statistics.mean(frame_ms):.2f} / {_percentile(frame_ms, 0.95):.2f} / {max(frame_ms):.2f}")
    print(f"  FPS (from avg frame time): {1000.0 / statistics.mean(frame_ms):.1f}")
    print("  section breakdown (avg / p95 / worst ms, frames-present):")
    for section, values in sorted(totals.items(), key=lambda kv: -statistics.mean(kv[1])):
        print(
            f"    {section:<28} {statistics.mean(values):>7.3f} / "
            f"{_percentile(values, 0.95):>7.3f} / {max(values):>7.3f}   ({len(values)}/{len(frames_recorded)})"
        )
    print(f"  frame time p99: {_percentile(frame_ms, 0.99):.2f}")
    merge_ms = [f["frame_ms"] for f in frames_recorded if f["metrics"].get("tile_merge_queue_depth", 0)]
    if merge_ms:
        print(f"  merge window: {len(merge_ms)} frames, avg/p95/worst {statistics.mean(merge_ms):.2f} / "
              f"{_percentile(merge_ms, 0.95):.2f} / {max(merge_ms):.2f}, >=100ms: {sum(m >= 100 for m in merge_ms)}")
    for threshold in (100.0, 200.0, 400.0, 500.0):
        count = sum(1 for ms in frame_ms if ms >= threshold)
        print(f"  frames >= {threshold:.0f}ms: {count}")
    print(f"  gc time total: {sum(_gc_time_by_frame.values()):.1f}ms across {len(_gc_time_by_frame)} frames")
    for gen, stats in _gc_by_gen.items():
        print(f"  gc gen{gen}: count={stats['count']} total={stats['ms']:.1f}ms max={stats['max_ms']:.1f}ms "
              f"collected={stats['collected']} uncollectable={stats['uncollectable']}")
    for event in _gc_full_events:
        print(f"    gen2 frame#{event['frame']:<5} {event['ms']:>7.1f}ms collected={event['collected']:<7} "
              f"rss={event['rss_mb']:.0f}MB" + (f" tracked={event['tracked']}" if event["tracked"] is not None else ""))
    if _GC_COUNT_OBJECTS:
        from collections import Counter
        census = Counter(type(obj).__name__ for obj in gc.get_objects())
        print("  tracked-object census (top 15): " + ", ".join(f"{name}={count}" for name, count in census.most_common(15)))
        before = len(gc.get_objects())
        found = gc.collect()
        print(f"  forced full collect at end: tracked {before} -> {len(gc.get_objects())}, unreachable found={found}")
    print(f"  gc strategy={_GC_STRATEGY} threshold={gc.get_threshold()} frozen={gc.get_freeze_count()} "
          f"rss_end={_rss_mb():.0f}MB tracked_end={len(gc.get_objects())}")
    print("  pedestrian sync: " + ", ".join(
        f"{name}={value}" for name, value in (_pedestrian_managers[-1].sync_stats.items() if _pedestrian_managers else ())
    ))
    print("  street-light cache: " + ", ".join(
        f"{name}={value - cache_stats_before[name]}"
        for name, value in roads_module._street_light_cache_stats.items()
    ))
    print()
    _print_tile_transitions(frames_recorded)
    if spike_threshold_ms is not None:
        _print_spike_frames(frames_recorded, spike_threshold_ms)


def main() -> None:
    cities = sys.argv[1:] or ["oulu", "rovaniemi"]
    for city in cities:
        run_scenario(f"Stationary ({city.title()})", city, frames=300, drive=False)
        run_scenario(f"Driving ({city.title()})", city, frames=1200, drive=True, spike_threshold_ms=400.0)


if __name__ == "__main__":
    main()
