# Performance analysis reports

Measured performance work on the Godot client and the Python simulation server.
Each report names its own date, revision and reproduction steps.

- [rrt-019.1-fps-audit.md](rrt-019.1-fps-audit.md) (2026-10-28): native client
  FPS audit, ranked bottlenecks; raw data and scripts in `rrt-019.1-fps-audit-data/`.
- `rrt-019-sim-audit-data/` (2026-10-28): simulation-server tick benchmark
  (`bench_sim.py`, `run_all.sh`, `summarise.py`) and its raw results.
- [2026-10-27-load-and-render.md](2026-10-27-load-and-render.md): server
  footprint checks and wet-road drawing.
- [visibility-first-2026-10-18.md](visibility-first-2026-10-18.md):
  visibility-first simulation.
- [map-loading-02.md](map-loading-02.md) (2026-10-14): stalls and UI jitter
  while the map grows; `tools/bench_map_jitter.py`.
