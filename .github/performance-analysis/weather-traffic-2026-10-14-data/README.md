# Evidence for the weather/traffic performance plan

- `weather-matrix.json`: two live-population repetitions of ten verified scenarios.
- `attribution.json`: fixed-actor layer comparisons, road-draw instrumentation and
  synthetic 4,000-point tyre tracks.
- `driving-jitter.json`: existing map-jitter benchmark, 60 seconds northbound.
- `early-population-profile.txt`: independent 180-tick cProfile attribution.
- `steady-snow-profile.txt`: later ploughed-snow 180-tick cProfile attribution.
- `analysis_driver.py`, `client_driver.gd`: diagnostic harnesses; never imported by
  the game. They alter in-memory test conditions only, not game source or settings.
- `snow-optimization-baseline.json`, `snow-optimization-controlled.json`: sequential
  old/new road-renderer comparison after the parking optimization.
- `snow-optimization-matrix.json`: final-code four-scenario rendered smoke check
  (repeat 1 only; exploratory repeat 0 discarded).

These harnesses intentionally record the local machine's exact Godot and PBF paths.
Inspect those paths before reproducing elsewhere. Run from the repository root
with the project virtual environment, a working X11 display and local cache/PBF
access. They create reports under `/tmp` and may populate normal map caches;
they do not clear caches. The test taxi does not accept/complete fares or set Home.

```sh
cp .github/performance-analysis/weather-traffic-2026-10-14-data/client_driver.gd /tmp/rrt_perf_client.gd
PYTHONPATH=src .venv/bin/python .github/performance-analysis/weather-traffic-2026-10-14-data/analysis_driver.py --out /tmp/rrt-performance-matrix-v2 --seconds 15 --repeats 2
PYTHONPATH=src .venv/bin/python .github/performance-analysis/weather-traffic-2026-10-14-data/analysis_driver.py --ablations --instrument-roads --out /tmp/rrt-performance-attribution --seconds 15 --repeats 1
PYTHONPATH=src .venv/bin/python tools/bench_map_jitter.py --preset Oulu --osm-source pbf --drive-s 60 --speed 33.3333 --heading 1.5708 --sample-ms 40 --json /tmp/rrt-performance-driving.json
```

`--headless` is useful only for script/server attribution; it does not reproduce
rendered FPS. cProfile runs occur after the rendered runs, not simultaneously.
Frozen actors apply only to the layer comparisons and are restored for profiling.
The protocol's actual weather/temperature are recorded so incorrect injected
conditions can be rejected. See the main report for sampling and interpretation
limits, especially evolving populations and the software renderer.
