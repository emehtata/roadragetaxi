# bin-loader-v8: budgeted street-light contributor preparation

## 1. Executive summary

Street-light contributor preparation is now a resumable per-job state machine. It has its own 4 ms budget (`STREET_LIGHT_PREP_BUDGET_S`) and a timer for each stage. Before the change, the V7 code spent up to **72 ms / 133 ms** (baseline runs 1/2) in per-segment lighting classification and **21 ms / 37 ms** in junction construction, both in a single frame. It also re-ran classification on 387 frames of one run. After the change, the largest street-light preparation frame measured **10.4 ms / 8.5 ms** (runs A/B). The largest street-light total per frame was **16.3 ms / 28.0 ms**, down from 104.9 ms / 181.9 ms. The worst street-light frames are now screen-surface redraws, not preparation. Output is exactly identical to the pre-change V7 code on 12 randomized worlds, both with and without spatial grids, at both full and zero budgets.

Overall frame spikes are still driven by pedestrians, tile integration, traffic and taxi, which were out of scope and not changed.

## 2. V7 baseline

V7 report numbers: 32.52 ms average, p95 48, p99 103, worst 358, 33 frames ≥100 ms, 8 ≥200 ms, 0 ≥400 ms, max `render:lighting` 126.53 ms, max street-light 118.39 ms, max tile integration 251.08 ms. The merge window had 46.38 ms average, p95 56, worst 292, and 3 frames ≥100 ms.

**Benchmark clock note.** The game starts at `datetime.now()` (gig-driver mode). The first baseline attempt ran at 10:18 local time, so street lights never switched on (`rebuilds=0`). To compare like with like, every run below uses the unchanged command with `TZ=UTC-15`, which puts the local start time at about 22:18. Nothing else about the scenario changed: `--preset oulu --no-menu --osm-source pbf`, warm WorldCache, real streaming and rendering, 3000 frames.

The V7 code was re-measured with per-stage timers added (the pre-change code plus instrumentation only):

| Metric | V7 run 1 | V7 run 2 |
|---|---:|---:|
| average / p95 / p99 / worst | 33.86 / 49 / 90 / 349 ms | 24.71 / 44 / 80 / 350 ms |
| frames ≥100 / ≥200 / ≥400 | 26 / 7 / 0 | 28 / 5 / 0 |
| max `render:lighting` | 113.87 ms | 190.79 ms |
| max `render:lighting:street_lights` | 104.88 ms | 181.94 ms |
| street-light cache (preparation + placement) avg / p95 / max | 5.24 / 6.59 / 102.72 ms (121 frames) | 8.57 / 93.57 / 180.07 ms (387 frames) |
| classification max (p95) | 71.98 ms (0.28) | 132.77 ms (69.23) |
| junctions max | 20.73 ms | 37.15 ms |
| segments (road index) max | 2.84 ms | 5.21 ms |
| building grid max | 1.00 ms | 1.14 ms |
| contributor queries/signatures max | 0.89 ms | 1.47 ms |
| placement max | 4.12 ms | 4.23 ms |
| merge window frames / avg / p95 / worst / ≥100 | 122 / 53.47 / 97 / 288 / 6 | 108 / 53.73 / 90 / 286 / 5 |
| rebuild jobs / update frames / extensions | 4 / 17 / 1 | 7 / 37 / 12 |
| max tile integration | 260.77 ms | 242.03 ms |

The benchmark does not report merge-window ≥200 ms counts separately.

## 3. Pre-change architecture (verified in code)

Every frame that missed the screen-surface cache, including every 16 px of camera movement, `draw_street_lights` did the following synchronously:

1. Queried `spatial_grid.ways_in_rect(region)` and `building_spatial_grid.ways_in_rect(region ± 200 m)`, then built id tuples of both results.
2. Scanned the **entire** `street_lamps` list to build a region lamp-id tuple for the key.
3. Rebuilt the building cell grid whenever that key changed.
4. Rebuilt junctions whenever `(revisions, visible way ids)` changed. This covers point bucketing plus `_way_should_have_street_lighting`, which does building-proximity checks at every shared node.
5. Rebuilt the per-segment lighting classification whenever the geometry key changed. This means three `_point_is_near_building` samples per segment on unlit urban roads.
6. At job start, built the local road-segment index.
7. Then placed lamps under the 4 ms `STREET_LIGHT_CACHE_BUDGET_S`, which was the only budgeted part.

Steps 3–5 compared keys built from the *current* padded region. While a job was running and the viewport sat outside the committed region, that region moved every frame, so the visible id tuples changed and classification and junctions were recomputed on consecutive frames. This explains run 2's 387 classification frames against only 37 job frames. Explicit-lamp matching also queried the **live** `street_lamp_grid` during placement frames, so a lamp-grid revision in the middle of a job could mix into it.

Scaling of each stage:

| Stage | Scales with |
|---|---|
| building grid | buildings in the region + 200 m |
| junctions | way points; building checks per shared node |
| classification | segments of unlit urban ways × building candidates |
| segments (road index) | visible segments |
| lamp key scan | the whole `street_lamps` list |

## 4–5. Profiling and the exact bottleneck

Every V7 spike frame at or above 100 ms that involved street lights broke down into **classification** and **junctions**, measured by nested per-stage timers rather than inferred from timing coincidence. For example, one spike measured 113.79 ms total lighting, of which classification was 65.83 ms, junctions 19.84 ms and placement 4.01 ms. Another measured 177.77 ms lighting: classification 111.70 ms, junctions 32.17 ms. Building-grid construction, queries and the road index all stayed at or below 5.2 ms.

## 6. New state-machine architecture

The code lives in `src/theroadragetrip/render/roads.py` and stays local to street lights; there is no generic task framework. Each job is a dict:

```text
key=(road_rev, building_rev, lamp_rev), region, snapshot(ways, buildings, explicit_lamps)
phase: buildings → junction_points → junctions → classification → segments → explicit_lamps → placement → commit
cursor, building_grid, point_ways, junction_grid, way_lit_cache, road_grid, lamp_grid/lamp_order, lamps, seen
```

- `_snapshot_street_light_job`: runs one query each against the road, building and lamp grids, once per job.
- `_street_light_prep_step`: returns `(items, process_item)` for a phase. Each item is one building, one way, or one junction candidate.
- `_advance_street_light_prep`: runs the phases through the existing `performance.advance_chunked` helper against one shared prep deadline.
- `_advance_street_light_placement`: the old placement loop, unchanged except that it reads the job-local lamp index.
- The old module-level building, junction and way-lit caches were removed because each job owns its indexes.
- `_build_street_light_road_index` still exists as a wrapper over the new per-way `_index_street_light_road`.

## 7. Snapshot and revision handling

- Geometry key = the three completed grid revisions. Raw list growth never changes the key. Same-count replacement changes it through `SpatialWayGrid.revision`.
- No per-frame contributor queries or id tuples happen any more. The full-list lamp scan is gone.
- A job reads only its snapshot, including explicit lamps. It snapshots the union of every eligible way's `bbox ± (half_width + 15 m)` query rectangle, so matching is identical to the old per-way live query, and results are sorted by the grid's own insertion order.
- A newer key arriving mid-job is recorded once as `pending` and counted in `extensions`. Job N finishes and commits, then the next frame starts a job for whatever the latest key is. Obsolete intermediate revisions are coalesced, the queue is bounded to one entry, and jobs are never aborted, so there is no `prepare_aborted` counter.

## 8. Budgeting

Preparation and placement each have their own budget: `STREET_LIGHT_PREP_BUDGET_S = 0.004` (new) and `STREET_LIGHT_CACHE_BUDGET_S = 0.004` (unchanged). Each phase processes at least one item and completes the current item, so single atomic items can exceed the budget. A long unlit urban way's classification is the main case, and it produced the 8–10 ms preparation maxima. Preparation spreads across frames: roughly 24–36 preparation frames per job were measured. The previous geometry stays visible throughout.

New counters: `revision_changes`, `prepare_frames`, `prepare_completed`, `placement_frames`, `snapshot_items`. The existing `rebuilds`, `update_frames` and `extensions` are kept. New timers: `render:lighting:street_lights:{snapshot,prepare,buildings,junction_points,junctions,classification,segments,explicit_lamps,placement,surface}`. The benchmark treats `street_light_cache` and `…:prepare` as parent sections.

## 9. Camera and region

The region logic is unchanged. Inside the committed padded region, geometry is reused with no queries. When the viewport leaves the region, a new snapshot is taken for a new padded region. Zoom, screen size and darkness remain screen-surface keys only. Daylight still returns before any cache work.

## 10. Correctness strategy

- **Exact equivalence with pre-change code.** A one-off script built 12 random worlds, each with 120 mixed ways (shared nodes, lit/unlit/`lit=no`), 80 buildings and 150 explicit lamps. It compared the V7 full rebuild against V8 at a 10 s budget and at a 0 budget (one item per frame), with and without spatial grids. All 48 comparisons were `==` on the full ordered `(x, y, direction, pool_radius)` lists, with 809–1202 lamps per world.
- **Regression test.** A repo test compares incremental output with a fresh full rebuild using exact list equality.

## 11. Tests

`tests/test_street_lights_render.py`:

- `test_v8_budgeted_preparation_resumes_keeps_old_cache_and_snapshots_revisions` covers:
  - A: multi-frame resumable preparation
  - B: the old cache stays visible during a job
  - C: revision N+1 arriving mid-preparation. The snapshot and key stay unchanged, there is exactly 1 extension, and the result then commits N+1.
  - D: raw growth causes no rebuild
  - E: same-count replacement invalidates
  - F: small moves reuse; a boundary crossing starts a job
  - G: zoom change reuses geometry
  - H: daylight starts no job. The test clears the wall-clock solar cache first.
  - I: exact equality between full and incremental output
- An autouse fixture gives single-call tests an unlimited preparation budget. Without it they flaked whenever one frame's preparation exceeded 4 ms. Budget-specific tests override it.
- The existing V7 test and the camera, zoom and building-scoping tests pass unchanged.

Results:

- Focused: 17/17 passed, three runs in a row.
- Full suite, run 1: 1138 passed, 6 failed. Five are the known V7 failures: NPC ×2, RWD oversteer ×2 and headless subprocess (`test_simulation_boundary`, which also fails on the unchanged code). The sixth was `test_tile_fetch_pause`.
- Full suite, run 2: 1138 passed, 6 failed. The same five, plus `test_taxi::test_nearby_collision_buildings_indexes_incrementally_not_the_whole_list`.
- Both extra failures are wall-clock assertions that pass 3/3 in isolation and do not touch street lights.
- `git diff --check`: clean.

## 12. Benchmark results (V8)

| Metric | V8 run A | V8 run B |
|---|---:|---:|
| average / p95 / p99 / worst | 30.65 / 49 / 94 / **1794** ms | 30.41 / 44 / 75 / 579 ms |
| frames ≥100 / ≥200 / ≥400 | 27 / 10 / 4 | 19 / 5 / 1 |
| max `render:lighting` | 32.99 ms | 39.97 ms |
| max `render:lighting:street_lights` | 16.27 ms | 28.00 ms |
| street-light cache avg / p95 / max | 2.73 / 5.48 / 10.55 ms | 2.18 / 6.43 / 8.67 ms |
| **preparation** avg / p95 / max | 4.37 / 5.25 / **10.39** ms | 4.68 / 7.33 / **8.50** ms |
| classification max | 7.17 ms | 7.89 ms |
| junctions max | 4.24 ms | 4.29 ms |
| snapshot max | 3.54 ms | 2.02 ms |
| segments / buildings / junction points / explicit lamps max | 3.46 / 2.00 / 1.57 / 0.05 ms | 2.84 / 1.21 / 0.73 / 0.02 ms |
| **placement** avg / max | 3.72 / 4.14 ms | 3.65 / 4.24 ms |
| screen surface avg / p95 / max | 2.41 / 7.58 / 15.46 ms | 2.21 / 6.26 / 22.11 ms |
| rebuild jobs / preparation frames / placement frames / extensions | 10 / 364 / 60 / 2 | 5 / 118 / 20 / 1 |
| revision changes / snapshot items | 7 / 11991 | 4 / 4339 |
| merge window frames / avg / p95 / worst / ≥100 | 159 / 54.67 / 52 / 1794 / 3 | 101 / 44.61 / 50 / 272 / 1 |
| max tile integration | 303.46 ms | 241.96 ms |
| max `map_sync:pedestrians` / `pedestrians` | 370.23 / 495.47 ms | 308.93 / 542.35 ms |
| max `map_sync:traffic` / taxi | 176.26 / 138.91 ms | 140.79 / 84.14 ms |

Run A's 1794 ms frame fell in the merge window but was beyond the 12 spike frames the tool prints, so it could not be attributed from the output. It is **not** street-light: every street-light section's per-frame maximum in run A was at most 16.3 ms. Run B's 579 ms worst frame lines up with `pedestrians` at 542 ms.

## 13. Comparison against V7

| | V7 report | V7 re-run 1/2 | V8 A/B |
|---|---:|---:|---:|
| max street-light total | 118.39 | 104.88 / 181.94 | **16.27 / 28.00** |
| max street-light preparation | 170.33 (probe) | ~98 / ~176 (classification + junctions) | **10.39 / 8.50** |
| max placement | – | 4.12 / 4.23 | 4.14 / 4.24 |
| max `render:lighting` | 126.53 | 113.87 / 190.79 | **32.99 / 39.97** |
| merge-window ≥100 ms | 3 | 6 / 5 | 3 / 1 |
| frames ≥100 ms | 33 | 26 / 28 | 27 / 19 |
| average frame | 32.52 | 33.86 / 24.71 | 30.65 / 30.41 |

The primary goal is met: no street-light preparation frame exceeded 10.4 ms. Whole-frame averages and worst frames are dominated by run-to-run noise and by the unrelated systems below.

## 14. Remaining bottlenecks

- **Street-light:** the screen-surface redraw (all lamp sectors redrawn whenever the 16 px camera bucket or a revision changes), up to 22 ms. Preparation overruns come from atomic long-way classification items (up to 10 ms).
- **Unrelated (unchanged):**
  - `pedestrians` / `map_sync:pedestrians`: up to 542 / 370 ms
  - `map_sync:tile_integration`: up to 303 ms
  - `map_sync:traffic`: up to 176 ms
  - taxi: up to 139 ms
  - the unattributed 1794 ms merge-window frame in run A

## 15. Recommendation for V9

Pedestrians are now the largest measured spike source (270–540 ms on several frames per run). Look at them next, then diagnose the first-merge tile-integration outlier. For street lights, the next step would be to split classification per segment instead of per way, and only if the 7–10 ms preparation overrun matters. The surface redraw could be offset-blitted more often, but it is not a spike source at the 100 ms level.
