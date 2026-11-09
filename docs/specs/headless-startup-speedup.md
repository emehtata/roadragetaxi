# Headless server startup: cached transformers, one map load

Goal: cut the ~35 s warm-cache `--preset Helsinki --no-menu --no-historical-weather` startup by removing
~4.5 s of repeated pyproj `Transformer.from_crs` and (if safe) the second cache read of the same city.
World contents must not change.

## Analysis (done before the spec)
- F1: `geo.meters_to_latlon` (geo.py:222-233) builds a transformer per call (377 calls). Other per-call builders
  on the startup path: `world_loader.latlon_to_world_metres` (~94, run once per world load) and
  `world_loader.load_world` (~416, once). `server/__init__.py:756-757` runs once and only with road_digitraffic
  on: NOT on the startup path, leave. borders.py:69, taxi.py:147, intercity*.py, osm/build.py:787: not confirmed
  hot; include only if the timing profile (below) shows them.
- F2 cause: the first bbox is the fixed preset (`resolve_city` -> `bbox_presets`, world_loader.py:576). The second is
  built by `AutoFetchManager.start_initial_tile_streaming` (osm/autofetch.py:561) from `_tiles_bbox(active 3x3 tiles)`
  in metres, converted to lat/lon. `initialize_player_tile` (autofetch.py:595) marks only tiles wholly inside the
  fetched rectangle as loaded, so the rest of the 3x3 window is "missing" and streamed with `allow_covering=False`
  (`preload_region`), under a different `area_id`.
- Reuse is NOT safe: the streaming bbox (N 60.187171, E 24.964030) reaches beyond the first (N 60.183039, E 24.962612),
  so the first load does not cover the window. Reusing it would leave the window's north/east tiles empty (a road
  would run out). Not done.
- Alternative (smallest safe): start `prepare_window`-style warming early. `AutoFetchManager.prepare_window` /
  `WorldCacheManager.prepare_region` already read/build a region off-thread without merging. Call it for the
  initial 3x3 window right after `initialize_player_tile`, so the 3.0 s second load overlaps other startup work
  and `start_initial_tile_streaming` gets the same future via `preload` (built once). Same bbox, same data.

## Files to change
- src/theroadragetrip/geo.py: module-level `@functools.lru_cache` helper `get_transformer(src, dst)` (always_xy);
  `meters_to_latlon` uses it when `transformer is None`. Keep the `(None, None)` on failure.
- src/theroadragetrip/world_loader.py: `latlon_to_world_metres` and the ~416 site use `get_transformer`.
- src/theroadragetrip/server/__init__.py (or world_loader after `initialize_player_tile`, ~459): kick off
  `auto_fetch_manager.prepare_window(car.x, car.y)` when auto-fetch is on.

## Acceptance criteria
1. `get_transformer("EPSG:3067","EPSG:4326")` returns the same object on repeat calls; different pairs differ.
2. `meters_to_latlon` results are bit-identical to the unfixed function for a sample of points.
3. `meters_to_latlon` x1000 constructs at most one Transformer.
4. Startup with the prepare call builds/reads the streaming region once: log shows one `[WorldCache] Lookup area=<second id>`
   cache read, and the world after streaming equals the unfixed one (same way/building counts from the log).
5. Prepare is skipped when `--no-auto-fetch`/sample map, and never merges anything itself.
6. Measured: median of 3 warm runs, "ready" time drops by at least the F1 saving (target >= 4 s under no profiler;
   record actual) and F2 does not regress. Put before/after numbers in the commit message.

## Tests to add
- tests/test_geo_transformer_cache.py::test_transformer_built_once_per_crs_pair - monkeypatch
  `pyproj.Transformer.from_crs` with a counter; 1000 `meters_to_latlon` calls; fails unfixed (count 1000).
- same file::test_meters_to_latlon_unchanged - compare to a fresh Transformer; guards criterion 2.
- tests/test_tile_streaming.py::test_initial_window_prepared_once - fake world cache manager counting
  `preload`/`prepare_region` by area_id; after prepare + `start_initial_tile_streaming` expect one build per
  area_id; fails unfixed (second area loaded only after streaming starts, no prepare call made at startup).

## Commands
- Tests: `cd /home/ubuntu/work/theroadragetrip && pytest -n auto tests/test_geo_transformer_cache.py tests/test_tile_streaming.py tests/test_predictive_streaming.py`
- Timing (run on baseline commit, then fixed; warm cache; discard the first run):
  `for i in 1 2 3; do /usr/bin/time -f "%e s wall" python road_rage_server.py --preset Helsinki --no-menu --no-historical-weather 2>&1 | tee run$i.log | grep -E "wall|ready|\[WorldCache\] (Lookup|Area .* ready)"; done`
  (stop each run once the log says ready; compare the ready timestamp and the two `Area ... ready in` lines).
- Profile F1: `python -m cProfile -s cumtime road_rage_server.py ... | grep -E "from_crs|meters_to_latlon"`.

## Out of scope
Chunk index, street light placement, NPC population, any change to bboxes, presets, tile size or what the world
contains; the digitraffic transformer site; Godot code.
