# bin-loader-v7: budgeted street-light cache

## 1. Executive summary

Street-light invalidation now follows completed `SpatialWayGrid` revisions and the stable contributor set inside the committed geometry region, rather than raw `ways`/`buildings` list growth. Lamp placement is resumed in 4 ms per-way chunks while the last committed geometry and composited frame remain visible. In the real 9-tile Oulu merge, merge-window frames at or above 100 ms fell from 24–25 to 3; there were 5 cache jobs over 20 update frames, not one rebuild per merge frame.

## 2. V6 baseline

V6's two 3000-frame runs measured 21.69/34.53 ms average, 36/53 ms p95, 114/111 ms p99, 822/353 ms worst, 37/47 frames >=100 ms, 5/7 >=200 ms, and 1/0 >=400 ms. Maximum `render:lighting` was 188/122 ms, maximum street-light time about 185 ms, and maximum tile integration 228/241 ms. Merge windows averaged 68/62 ms, p95 145/124 ms, worst 262/275 ms, with 24/25 frames >=100 ms.

## 3. Existing street-light architecture

The renderer has a world-space geometry cache of `(x, y, direction, pool radius)` lamps, junction and per-segment lighting caches, and screen-space lamp/pool surfaces tied to camera, zoom, darkness, and screen size. Relevant ways come from `SpatialWayGrid.ways_in_rect`; nearby buildings and explicit OSM lamps come from their corresponding grids. Expensive work is urban-road classification, junction/road indexing, candidate placement/occlusion, and drawing the composited lamp surfaces.

## 4. Root cause

The old geometry and frame keys included `len(ways)` and `id(ways[-1])`. V5 appends into that list each merge frame while the completed spatial grid continues serving the old indexed world. Identical rendered input therefore caused repeated full geometry reconstruction. A second issue found during V7 was recomputing the visible signature from a moving padded query even while the committed geometry region still covered the viewport; the final code queries the committed region until its boundary is crossed.

## 5. New architecture

```text
raw world lists grow -> completed grid revision unchanged -> reuse cache
completed grid changes / region crossed
        -> snapshot exact visible contributors
        -> process lamp ways for <=4 ms per frame
        -> keep old committed geometry/surfaces visible
        -> atomically commit completed geometry
new revision during work -> finish safe snapshot -> queue current revision
```

`SpatialWayGrid.revision` changes only when a synchronous rebuild or budgeted rebuild commits, including same-count replacement/removal. Cache counters expose rebuild jobs, update frames, and extensions to the existing benchmark.

## 6. Cache invalidation

Geometry invalidates on a completed road/building/lamp grid revision, a changed exact visible contributor signature, or leaving the committed padded region. Same-count unload/replacement is detected by the revision. Zoom, resolution, camera bucket, and darkness remain screen-surface concerns; geometry is world-space and independent of brightness. Raw list growth before grid commit is deliberately ignored. Callers without grids retain an identity signature fallback.

## 7. Incremental behavior

Each job owns an immutable way snapshot, road index, junction grid, lighting classification, explicit-lamp set, cursor, and output. Placement advances until the dedicated `STREET_LIGHT_CACHE_BUDGET_S = 0.004` deadline, always completing the current way. A newer revision is recorded as an extension and becomes the next safe snapshot; it is not mixed into structures built for the prior revision. This avoids duplicates and junction inconsistencies. The previous committed cache stays visible throughout.

## 8. Performance

Real command: `PYTHONPATH=src:. .venv/bin/python -c 'import utils.benchmark_full_frame as b; b.run_scenario("Driving V7 final", "oulu", frames=3000, drive=True, spike_threshold_ms=100.0)'`. It used `--preset oulu --no-menu --osm-source pbf`, the package `assets/roads/oulu.bin`, warm WorldCache, real streaming/rendering, 9 integrated tiles, and 30,589 final ways.

| Metric | V6 range | V7 |
|---|---:|---:|
| average frame | 21.69–34.53 ms | 32.52 ms |
| p95 | 36–53 ms | 48 ms |
| p99 | 111–114 ms | 103 ms |
| worst | 353–822 ms | 358 ms |
| frames >=100 ms | 37–47 | 33 |
| frames >=200 ms | 5–7 | 8 |
| frames >=400 ms | 0–1 | 0 |
| max `render:lighting` | 122–188 ms | 126.53 ms |
| max street-light total | ~185 ms | 118.39 ms |
| max tile integration | 228–241 ms | 251.08 ms |

Run-to-run noise remains substantial. A separate 600-frame warm-cache probe with the new cache-only timer measured 4 rebuild jobs, 24 update frames, and 4 extensions. Its cache timer includes synchronous contributor classification/index preparation as well as the budgeted placement and reached 170.33 ms on a cold/revision preparation frame; this is the remaining street-light bottleneck, not repeated raw-list invalidation.

## 9. Merge-window analysis

| Metric | V6 range | V7 |
|---|---:|---:|
| frames | not reported | 104 |
| average | 62–68 ms | 46.38 ms |
| p95 | 124–145 ms | 56 ms |
| worst | 262–275 ms | 292 ms |
| >=100 ms | 24–25 | 3 |
| >=200 ms | 5–7 overall | 1 observed merge outlier |

The merge-window worst frame was the known `map_sync:tile_integration` outlier (251.08 ms), not street-light placement. Repeated 150–200 ms lighting frames disappeared.

## 10. Remaining >100 ms frames

The important observed contributors were: one 251 ms tile-integration outlier; `map_sync:pedestrians` up to 335.53 ms; `map_sync:traffic` 144.08 ms; pedestrian simulation around 97–120 ms on several frames; and occasional 106–126 ms lighting surface/preparation frames. Illuminated windows remained small (9.82 ms maximum). Taxi work reached 145.37 ms in the full run. These attributions come from nested per-call sections, not timing coincidence.

## 11. Correctness

The V7 regression forces zero-budget one-way progress, grows the raw list without committing the grid, commits multiple grid revisions while work is active, and compares the final incremental geometry exactly with a fresh full build. Existing tests cover cold/warm rendering, explicit versus synthetic lamps, camera-region reuse, zoom/screen behavior, building scoping, and pixel stability. Same-count removal/replacement is covered by the grid revision mechanism and the full street-light test sequence no longer leaks an equal-length cache between inputs.

## 12. Camera, zoom, and day/night

Small camera moves reuse the committed padded geometry region; boundary crossing starts a new budgeted snapshot. The old screen-space cache is offset while a job runs, avoiding blank frames/flicker. Zoom and screen size remain in the surface key. Darkness changes only the screen-space surface; geometry remains reusable. Daylight still exits before cache work.

## 13. Tests

Focused: 51 renderer/spatial-grid/profiler tests passed; after the full-suite sequence exposed a no-grid equal-length fallback collision, all 16 street-light tests passed with the identity fallback fix. Final full suite: 1133 passed, 5 failed. The failures are the established unrelated/flaky NPC (2), RWD oversteer (2), and subprocess import (1) failures; all 16 street-light tests passed. `git diff --check` passed.

## 14. Remaining bottlenecks

- Street-light contributor classification/local-index preparation is not yet chunked and can spike on cold/revision frames; placement itself is budgeted.
- `map_sync:pedestrians` reached 335.53 ms.
- Taxi offer work still uses its brute-force path and reached 145.37 ms.
- The unexplained first-merge `tile_integration` outlier remains (251.08 ms here).
- `map_sync:traffic` reached 144.08 ms.

## 15. Recommendation

Next, split street-light contributor preparation (nearby-building grid, junction construction, and per-segment lighting classification) into the same resumable state machine; it is now separately measured and is the only remaining street-light cache spike. After that, measured evidence favors `map_sync:pedestrians`, while the tile-integration outlier should be diagnosed independently.
