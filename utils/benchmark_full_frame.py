"""Full real-frame profiling harness (bin-loader-v2.md): runs the actual
interactive main() game loop in-process, with a dummy SDL driver and
synthetic input, capturing every FrameProfiler section per frame -
simulation and every render layer, not just roads. See
utils/benchmark_road_rendering.py for the roads-only benchmark this
complements; this one answers "what's the real bottleneck across the
WHOLE frame", which an isolated draw_ways() call can't show.

Run with: PYTHONPATH=src:. python utils/benchmark_full_frame.py [city ...]
Defaults to oulu (dense) and rovaniemi (sparse) if no city is given.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import statistics
import sys
from collections import defaultdict

import pygame

pygame.init()

import theroadragetrip.performance as performance_module

# Capture every frame's section breakdown as advance() rotates them out,
# instead of touching main()'s internals - it already calls
# frame_profiler.advance(raw_frame_ms) once per real loop iteration.
_captured: list[dict] = []
_real_advance = performance_module.FrameProfiler.advance


def _capturing_advance(self, real_frame_ms=None):
    if self.enabled and self.sections:
        _captured.append({"frame_ms": real_frame_ms, "sections": dict(self.sections)})
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

# The game reads continuous key state (pygame.key.get_pressed()) for
# driving, not discrete events - a plain defaultdict stands in for the
# real ScancodeWrapper (both support keys[K_x] -> bool).
_held_keys = defaultdict(bool)
pygame.key.get_pressed = lambda: _held_keys

_frame_index = [0]
_stop_after_frame = [None]
_drive = [False]
WARMUP_FRAMES = 110  # > the 1.5s/~90-frame "awaiting_start" gate (main.py); only paces when driving starts


def _fake_event_get(*_args, **_kwargs):
    events = []
    _frame_index[0] += 1
    # Hold "forward" once warmup has cleared, same held-key mechanism a
    # real player uses (main.py reads pygame.key.get_pressed() every
    # frame, not discrete key events) - released again for stationary runs.
    _held_keys[pygame.K_UP] = _drive[0] and _frame_index[0] > WARMUP_FRAMES
    if _stop_after_frame[0] is not None and _frame_index[0] >= _stop_after_frame[0]:
        events.append(pygame.event.Event(pygame.QUIT))
    return events


pygame.event.get = _fake_event_get


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[index]


def run_scenario(name: str, city: str, frames: int, drive: bool) -> None:
    import theroadragetrip.main as main_module

    _captured.clear()
    _held_keys.clear()
    _frame_index[0] = 0
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
    print()


def main() -> None:
    cities = sys.argv[1:] or ["oulu", "rovaniemi"]
    for city in cities:
        run_scenario(f"Stationary ({city.title()})", city, frames=300, drive=False)
        run_scenario(f"Driving ({city.title()})", city, frames=1200, drive=True)


if __name__ == "__main__":
    main()
