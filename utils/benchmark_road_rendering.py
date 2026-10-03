"""Benchmark render/roads.py's draw_ways() static-cache pipeline against a
real city's road network, stationary vs moving camera.

Run with: PYTHONPATH=src:. python utils/benchmark_road_rendering.py
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import statistics
import sys
import time
from pathlib import Path

import pygame

from theroadragetrip.osm.bin_source import load_city_ways
from theroadragetrip.performance import FrameProfiler
from theroadragetrip.physics import SpatialWayGrid
from theroadragetrip.render import common as render_common
from theroadragetrip.render import roads as roads_module
from theroadragetrip.render.roads import draw_ways

SCREEN_W, SCREEN_H = 1280, 720
PX_PER_M = 9.0


def _reset_road_cache() -> None:
    render_common._road_frame_cache_key = None
    render_common._road_frame_cache_surface = None
    render_common._road_frame_cache_camera = None
    roads_module._road_wip = None


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[index]


def run_scenario(
    name: str, ways, grid: SpatialWayGrid, frames: int,
    camx0: float, camy0: float, dx_per_frame: float, dy_per_frame: float,
) -> None:
    _reset_road_cache()
    profiler = FrameProfiler()
    profiler.enabled = True
    screen = pygame.Surface((SCREEN_W, SCREEN_H))
    camx, camy = camx0, camy0
    frame_ms: list[float] = []
    rebuild_ms: list[float] = []
    rebuilding_frames = 0

    for _ in range(frames):
        profiler.begin_frame()
        started = time.perf_counter()
        draw_ways(screen, ways, camx, camy, px_per_m=PX_PER_M, spatial_grid=grid, profiler=profiler)
        frame_ms.append((time.perf_counter() - started) * 1000.0)
        chunk = profiler.sections.get("render:roads_cache_rebuild", 0.0)
        rebuild_ms.append(chunk)
        if chunk > 0.01:
            rebuilding_frames += 1
        profiler.end_frame()
        camx += dx_per_frame
        camy += dy_per_frame

    # Drop the first frame: it's the one-time synchronous full build every
    # layer's "no cache yet" case pays, not representative of steady state.
    steady = frame_ms[1:] if len(frame_ms) > 1 else frame_ms
    print(f"=== {name} ===")
    print(f"  frames: {frames}, first-frame (cold build) ms: {frame_ms[0]:.3f}")
    print(f"  steady-state average ms: {statistics.mean(steady):.3f}")
    print(f"  steady-state worst ms: {max(steady):.3f}")
    print(f"  steady-state p95 ms: {_percentile(steady, 0.95):.3f}")
    print(f"  frames touching the incremental rebuild: {rebuilding_frames}/{frames}")
    active_rebuild_ms = [v for v in rebuild_ms[1:] if v > 0.01]
    if active_rebuild_ms:
        print(f"  average rebuild-chunk ms (when active, excl. cold build): {statistics.mean(active_rebuild_ms):.3f}")
        print(f"  worst rebuild-chunk ms (excl. cold build): {max(active_rebuild_ms):.3f}")
    print()


def main() -> None:
    pygame.init()
    city = sys.argv[1] if len(sys.argv) > 1 else "oulu"
    ways, nodes, geometry_points, load_seconds = load_city_ways(city)
    grid = SpatialWayGrid()
    grid.rebuild(ways)
    print(f"City: {city} | ways={len(ways):,} nodes={nodes:,} geometry_points={geometry_points:,} "
          f"(loaded in {load_seconds * 1000:.0f} ms)")
    print()

    minx = min(w.bbox[0] for w in ways)
    miny = min(w.bbox[1] for w in ways)
    maxx = max(w.bbox[2] for w in ways)
    maxy = max(w.bbox[3] for w in ways)
    center_x, center_y = (minx + maxx) / 2.0, (miny + maxy) / 2.0

    run_scenario("Stationary camera (dense center)", ways, grid, frames=180,
                 camx0=center_x, camy0=center_y, dx_per_frame=0.0, dy_per_frame=0.0)

    # ~40 km/h taxi cruise: 11.1 m/s / 60 fps.
    run_scenario("Slow driving (~40 km/h, 60s straight line)", ways, grid, frames=3600,
                 camx0=minx + 200.0, camy0=center_y, dx_per_frame=11.1 / 60.0, dy_per_frame=0.0)

    # ~110 km/h: 30.6 m/s / 60 fps - the "high-speed driving" case from
    # bin-loader-v1.md #9, checking whether the incremental rebuild keeps
    # the cache from visibly lagging behind a fast-moving camera.
    run_scenario("Fast driving (~110 km/h, 20s straight line)", ways, grid, frames=1200,
                 camx0=minx + 200.0, camy0=center_y, dx_per_frame=30.6 / 60.0, dy_per_frame=0.0)


if __name__ == "__main__":
    main()
