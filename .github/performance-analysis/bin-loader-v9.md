# bin-loader-v9: pedestrian synchronization spikes

## 1. Executive summary

The 250–350 ms `map_sync:pedestrians` spikes turned out to be **full (generation-2) Python garbage collections**, not pedestrian computation. They are triggered by the pedestrian sync's allocations and land inside whichever chunk allocates next. The benchmark's GC column was attributing GC time to the previous frame, which hid this. That column is now fixed.

The pedestrian code's own synchronous work was real but smaller:

- **Job start:** 62–78 ms (venue and scenery indexing plus candidate filtering).
- **Commit:** 92–98 ms (spawn/way grid rebuild).
- **Route generation** in the per-frame `pedestrians` update: two brute-force whole-city scans costing up to **101 ms + 86 ms per route**. This was the source of V8's `pedestrians` spikes (84–542 ms including GC).

All three are now fixed, with output identical to the previous implementation:

- Job-start and commit work are budgeted stages of the existing incremental job.
- Route endpoint lookups use exact spatial indexes built during the (already budgeted) route-graph rebuild.

With GC excluded, the largest remaining pedestrian costs are the Dijkstra search (66–68 ms, 6–8 routes per run) and the commit (29–34 ms). GC pauses (250–350 ms) remain and appear in every subsystem. They are the V10 target.

## 2. V8 baseline

V8 runs A and B:

| Metric | Run A | Run B |
|---|---:|---:|
| average | 30.7 ms | 30.4 ms |
| p95 | 49 ms | 44 ms |
| worst | 1794 ms | 579 ms |
| street-light max | 16.3 ms | 28.0 ms |
| lighting max | 33 ms | 40 ms |
| pedestrians (update) max | 495 ms | 542 ms |
| `map_sync:pedestrians` max | 370 ms | 309 ms |

**V9 baseline (V8 code, uninstrumented).** Command: `TZ=UTC-15 … run_scenario("Driving V9 baseline", "oulu", 3000, drive=True)`.

- Frames: avg 29.41 ms, p95 44, p99 77, worst 345. Frames ≥100 / ≥200 / ≥400 ms: 19 / 6 / 0.
- `map_sync:pedestrians`: avg 6.80, p95 5.20, max **320.62 ms** (293 frames).
- `pedestrians` update: max **314.74 ms**.
- Others: `map_sync:traffic` 146.67, `map_sync:taxi` 46.56, tile integration 244.11, taxi 73.41 ms.

## 3. Pedestrian architecture before V9

Map-sync stage 13 in `main/__init__.py` runs synchronously in its first frame:

1. `set_venue_buildings(buildings)`: walks all ~21k buildings to build the building grid, venue/entrance lists and the entrance grid.
2. `set_scenery_features(...)`: grids every scenery object and polygon.
3. `start_incremental_sync(ways)`: copies the list and runs a candidate filter over all ~31k ways.

After that, `advance_incremental_sync(MAP_SYNC_BUDGET_S = 4 ms)` runs the budgeted phases: building_free → route_graph → junction_grid. The commit then ran `_commit_spawn_and_way_grids()` synchronously over every ped way.

The trigger is a completed map revision or a stale grid count, only once the tile-merge queue is empty. There is one job per sync: the previous `ped_ways` result stays live until commit. There is no per-pedestrian bulk work in map sync. Spawn, despawn and resident association happen in `update()`, bounded by 5-second population ticks and the target count.

The per-frame `pedestrians` update runs route generation inside the movement loop (via `_walk_route_to` → `_footway_route_to`) the first time a pedestrian needs one:

- `network.nearest_point()` scanned **every segment of every pedestrian way** in the city, calling `reject` (building-crossing test) on each improving candidate.
- `network.route()` then picked start and target nodes with `min(self.edges, …)` over **every node**, then ran Dijkstra.

## 4. Baseline profiling (nested timers, uninstrumented vs instrumented)

Instrumentation adds per-stage timers through the optional `PedestrianManager.profiler`. It records a `…:wait` diagnostic (wall time minus `time.thread_time()`), which is about 0 in every run, so no GIL or OS waits were involved. Instrumented runs had 32.93 / 31.09 ms averages against the 29.41 ms baseline, which is within run-to-run noise (V8's two runs differed by 0.3–9 ms).

| Stage (instrumented run 1) | max |
|---|---:|
| `junction_grid` chunk | 319.12 ms |
| `building_free` chunk | 256.33 ms |
| commit | 91.59 ms |
| `venue_buildings` | 30.40 ms |
| `scenery_features` | 21.66 ms |
| `start` | 10.06 ms |
| `route_graph` | 5.50 ms |
| update `movement` | 84.12 ms (run 2: 253 ms) |
| update `spawn` | 9–30 ms |
| update `despawn` / `lod` / `avoidance` / `activities` | < 1 ms |

## 5. Exact bottleneck identification

- **250–350 ms chunks are GC.** A temporary per-item diagnostic caught a **2-point footway** insertion taking 332.9 ms, and a 10-point path split taking 256.2 ms. `gc.get_stats()` around those single items showed a generation-2 collection each time (gen-2 count 38→39 and 39→40) over 1.13 M / 1.35 M tracked objects. Once the benchmark's GC frame index was fixed (§11), the final runs show every such frame's GC time matching the section. Examples: `junction_grid` 328.9 ms with gc 328.3 ms; `sceneries` 274.9 ms with gc 273.4 ms. The same happens outside pedestrians: `tile_integration` 261.8 ms with gc 259.5 ms, and `render:lighting` 282.9 ms with gc 276.6 ms.
- **Route generation.** Timers inside `_footway_route_to`: `route_nearest` max **101.30 ms**, `route_search` max **85.81 ms**, averaging about 98 ms per route. Only 9 routes were generated in a 3000-frame run, all synchronously in the update frame. They account for the 84–187 ms `pedestrians:movement` frames, all with gc=0.
- **Deterministic synchronous sync work.** Job start is 62–78 ms (venue + scenery + candidate filter), and commit is 92–98 ms (spawn/way grids over every ped way).

## 6. Trigger and invalidation analysis

Pedestrian sync already follows authoritative map revisions and runs once per completed merge window. Raw list growth mid-job does not start another job, because main only starts one when `_sync_stage` is None or done. No tile-integration-triggered full pedestrian re-population was found: spawn and despawn never iterate the world. The sync job needs ways, buildings, scenery and signals, and every one of those is now snapshotted at job start. Invalidation semantics were left unchanged.

## 7. New incremental architecture

`PedestrianManager.start_incremental_sync(ways, …, venue_buildings=…, scenery_features=…)` now runs these stages:

```text
venue → scenery_objects → sceneries → candidates → building_free → route_graph → junction_grid → spawn_grid → commit
```

- Each chunked stage goes through `_sync_stage_work()` → `(items, process_item)` driven by the existing `advance_chunked`.
- The per-item helpers (`_index_venue_building`, `_index_scenery_object`, `_index_scenery`, `_classify_candidate_way`, `_index_spawn_way`) are shared with the synchronous `set_venue_buildings`, `set_scenery_features` and `sync_map_data` paths, so both paths compute identically.
- The venue and scenery indexes commit as soon as each is complete. `building_free` needs the new building grid, exactly as before, when `set_venue_buildings` ran first.
- `ped_ways`, the route graph, the junction grid and the spawn/way grids commit together at the end.

`PedestrianNetwork` now builds through `_PedestrianNetworkBuild`, which holds nodes and edges plus a 50 m segment grid and node grid. `nearest_point()` and `route()`'s endpoint lookup use `_ring_search`, an exact expanding-ring search ordered by (original comparison value, original scan index). Ties and `reject` therefore resolve exactly as the old linear scans did. `set_ways` uses its own local build, so a synchronous sync can never clobber an in-progress incremental rebuild.

## 8. Budgeting model

Every stage shares the existing dedicated `MAP_SYNC_BUDGET_S = 0.004` deadline per `advance_incremental_sync` call. That constant was already the pedestrian stage's budget and is not shared with the street-light or tile-merge budgets. The stage a call starts in always makes progress; later stages cascade only while time remains. A single atomic item may exceed the budget (for example, one long way's building split). Final runs show budgeted stages at 4–6 ms, with `building_free` up to 11 ms and one `route_graph` chunk at 18–20 ms (non-GC single items).

Counters in `PedestrianManager.sync_stats`: `jobs`, `frames`, `completed`, `routes`. The benchmark prints them. Timers: `map_sync:pedestrians:{start, venue, scenery_objects, sceneries, candidates, building_free, route_graph, junction_grid, spawn_grid, commit, wait}` and `pedestrians:{lod, materialize_drivers, despawn, spawn, activities, avoidance, movement, route_nearest, route_search, wait}`.

Not added, because the measurements showed no need: separate spawn/despawn/route queues, and per-resident dirty sets. Spawn is at most 7.5 ms and despawn under 0.2 ms.

## 9. Revision handling

The job snapshots `list(ways)`, `list(buildings)` and the scenery lists at start. Growth of the caller's raw lists (tested) never reaches the job. The main loop's map-sync state machine still serializes syncs: a revision that arrives mid-job is picked up by the next sync after this one commits, so there is at most one pending re-sync and intermediate revisions coalesce. The old `ped_ways`, route graph, junction grid and spawn/way grids stay authoritative until the atomic commit (tested).

## 10. Correctness strategy

Three layers:

- **Exact structural equality** of every pedestrian index against the full synchronous path. This covers ped_ways, spawn ways, the way grid, the junction grid (entry by entry), network nodes and edges, route nodes and edges, the building grid, venue/entrance/amenity lists, the entrance grid, and both scenery grids.
- **Exact equality of `nearest_point` / `route` answers** against the original brute-force algorithms.
- **A one-off script against HEAD's `pedestrian.py`.** It used 10 random worlds, each with 150 mixed ways (footway, path, residential, service, primary, steps), 60 buildings with entrances and venues, and scenery. It compared HEAD's sync and incremental paths with the V9 incremental path at 0 s and 10 s budgets: all identical. It also compared 100 `nearest_point` (with the real building-crossing `reject`) and `route` queries per world, old against new network: all identical.

## 11. Tests

In `tests/test_pedestrians.py`:

- `test_v9_budgeted_sync_matches_full_sync_and_snapshots_inputs[dedicated|fallback]`:
  - A: zero budget spreads the job over more than 10 frames.
  - B / C: raw ways and buildings mutated after start are ignored.
  - Old `ped_ways` stay live until commit.
  - D / E / F / G: exact full-vs-incremental equality of all indexes, including venue/entrance associations.
  - H: repeating the sync with unchanged inputs gives an identical result with no duplicates.
  - Counters are checked.
- `test_v9_budgeted_sync_handles_an_empty_world` (I).
- `test_v9_indexed_network_lookups_match_brute_force`: 150 random queries (near and far, with and without `reject`) on both the sync-built and incrementally built network, shared-node ties, and empty/all-rejected networks.
- J: existing pedestrian, activity and resident tests pass unchanged (116 tests).

`utils/benchmark_full_frame.py`: GC time is now keyed to the frame it ran in. Previously an off-by-one frame index made spike frames show gc≈0. The benchmark also prints pedestrian sync counters and treats the pedestrian parent and diagnostic sections correctly.

Results:

- Full suite: **1143 passed, 5 failed**. The 5 are the same established failures as V7/V8: NPC ×2, RWD oversteer ×2, and `test_simulation_boundary` headless.
- `git diff --check`: clean.

## 12. Full-vs-incremental comparison

See §10. Every comparison is exact `==` equality on the full structures, and junction-grid entries are compared by their way geometry because `building_free` creates new split-way objects. No tolerance was needed.

## 13. Benchmark results

| Metric | V9 baseline | V9 run A | V9 run B |
|---|---:|---:|---:|
| avg / p95 / p99 / worst | 29.41 / 44 / 77 / 345 ms | 33.51 / 45 / 78 / 366 ms | 31.75 / 40 / 66 / 578 ms |
| frames ≥100 / ≥200 / ≥400 | 19 / 6 / 0 | 15 / 5 / 0 | **8** / 4 / 1 |
| `map_sync:pedestrians` avg / p95 / max | 6.80 / 5.20 / 320.62 | 6.04 / 5.38 / 328.87 (gc 328.3) | 5.28 / 5.30 / 324.06 (gc 321.6) |
| largest non-GC sync stage | commit 92–98 (instrumented) | commit 29.47 | commit 34.33 |
| job-start frame | 62–78 | 1.40 | 1.42 |
| `pedestrians` update max | 314.74 | 71.89 | 71.88 |
| route nearest max | 101.30 (instr.) | **0.25** | **0.27** |
| route search max | 85.81 (instr.) | 68.01 | 66.17 |
| sync jobs / frames / routes | – | 1 / 351 / 6 | 1 / 342 / 8 |
| merge window ≥100 ms | 1 | 5 | 1 |
| gc total | – | 3319 ms / 433 frames | 3219 ms / 407 frames |

Unrelated peaks, recorded but not changed:

| Section | Run A | Run B |
|---|---:|---:|
| taxi | 333.7 ms (gc 0) | **544.1 ms** (gc 0; run B's worst frame, 578 ms) |
| `map_sync:traffic` | 142 ms | 136 ms |
| `map_sync:taxi` | 51 ms | 46 ms |
| tile integration | 262 ms (GC) | 261 ms (GC) |
| npc | 164 ms | 53 ms |

## 14. Remaining bottlenecks

- **GC pauses (global).** Full collections of 250–350 ms over about 1.1–1.35 M objects, 5–6 per run, landing in whatever allocates. Pedestrian sync allocations are one trigger, but not the only one.
- **Pedestrian (non-GC):**
  - Dijkstra route search, up to 68 ms per route. Only 6–8 routes per run, synchronous in the update.
  - Commit, 29–34 ms. What remains is deallocating the old grids once their last references drop.
- **Unrelated:** taxi up to 544 ms (non-GC, the worst frame of run B), `map_sync:traffic` 136–142 ms, npc up to 164 ms.

## 15. Recommendation for V10

GC is now the single largest spike source across subsystems. Measure `gc.freeze()` after world load and after each map-sync commit, and/or tuned `gc.set_threshold`, against these runs. Check memory growth, because frozen tile data can then only be reclaimed by reference counting.

Then look at the taxi spike (544 ms, not GC). For pedestrians, the next step would be a bounded route-request queue (a pedestrian keeps its previous behavior for a frame) or A* with an exact heuristic, but only if 66–68 ms route frames matter after GC is handled.
