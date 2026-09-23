# bin-loader-v6: incremental illuminated-window cache

## 1. Executive summary

`draw_illuminated_windows()` no longer rebuilds its glow cache when the
building list grows, and extends it incrementally (budgeted) when the
building grid gains buildings. The window cache now costs 0.4 ms average,
6-13 ms max (was ~150-200 ms per rebuild). Merge-window frames over 100 ms
fell from 45 to ~25 and frames over 200 ms from 18 to 5-7.

**Important correction to V4/V5:** the repeated 150-250 ms `render:lighting`
frames during the tile merge were *mostly not the window cache*. V4 inferred
that from timing coincidence. Per-call timing shows `draw_street_lights()`
(in `render/roads.py`, out of scope and forbidden here) is the dominant
cost: 28 of 511 calls over 50 ms, max 185 ms, versus window cache max 13 ms.
Its cache key includes `len(ways)`/`id(ways[-1])`, so the V5 merge's
per-frame `ways` growth rebuilds it every frame - the same failure mode as
the window cache. The acceptance goal "no repeated 150-200 ms frames during
merge" is therefore only partly met; the remainder needs a `roads.py` change.

## 2. V5 baseline (like-for-like: V5 commit 00b5a3e, same harness, 3000 driving frames)

avg 25.93 ms, p95 42, p99 185, worst 1588 (noisy), ≥100 ms 66, ≥200 ms 18,
≥400 ms 1; max `render:lighting` 285; max `tile_integration` 240;
merge window 149 frames, avg 91.07, p95 203, worst 1588, ≥100 ms: 45.

## 3. Existing cache architecture (verified in code)

- Contents: one screen-space (camera-relative) `SRCALPHA` surface of opaque
  lit-window quads, `screen + 2*224px` padding, drawn at a snapshot camera.
- Alpha (darkness/dusk fade) is applied at blit, so day/night does **not**
  invalidate geometry; before dark (`darkness <= 0.25`) the function returns
  before touching the cache.
- Reused while the camera stays within 224 px of the snapshot (blitted at an
  offset); zoom, screen size, list identity or grid identity change -> rebuild.
- Old key: `id(buildings)`, `len(buildings)`, `id(buildings[-1])`, grid id,
  zoom, screen. Visible set came from the building grid (`ways_in_rect`).
- Data model: window geometry is a pure function of building points/height/
  identity; buildings are append-only during the V5 merge, but `_unload_tiles`
  filters the list in place (removals do exist).
- Bug in the old key: the *grid*, not the list, decides which buildings are
  drawn, and the grid only catches up at map-sync stage 3. So during the V5
  merge the key changed every frame while the rendered output was identical.

## 4. New architecture

```
key = (id(buildings), id(grid), zoom, screen); count = grid.indexed_way_count
count == cached count, camera ok        -> reuse (blit)
count > cached count, prefix intact,
  camera ok                             -> extension job: draw buildings[cursor:end]
                                           onto the SAME surface, 4 ms/frame,
                                           committed surface stays visible
otherwise (cold, camera/zoom/list-id
  change, unload)                       -> full synchronous rebuild (as before)
```

Job state: cursor, end, cache reference; a later count increase retargets
`end` without restarting. `_draw_illuminated_building` is the single
per-building implementation used by both paths (opaque same-colour polygons,
so draw order is irrelevant). No grid: count = `len(buildings)`.

## 5. Invalidation

Full rebuild: first build, camera beyond 224 px, zoom/screen change, list or
grid object change, or unload detected (building at `count-1` no longer at
that position). Extension: grid index grew, same world, camera in range.
No-op: list grew but grid did not (the V5 case). Time-of-day, weather and
alpha never invalidate geometry (unchanged).

## 6. Budget

`ILLUMINATED_WINDOW_CACHE_BUDGET_S = 0.004`, dedicated (not
`TILE_MERGE_BUDGET_S`). Same order as the other stage budgets; measured max
window-cache frame 6-13 ms including blit. Cold and camera-driven rebuilds
stay synchronous (they have nothing valid to keep showing / preserve
existing semantics); cold build happens once at startup on a small world.

## 7. Tile-merge behavior

While V5 appends buildings, the window cache does nothing (grid unchanged).
When map sync's building-grid stage indexes the merged buildings the count
jumps once and the extension draws only the new viewport-intersecting
buildings across a few frames. Already-processed buildings are never redrawn
(tested by counting `_draw_illuminated_building` calls).

## 8. Performance (Oulu, warm cache, real streaming, 3000 driving frames)

| Metric | V5 | V6 run A | V6 run B |
|---|---|---|---|
| avg frame ms | 25.93 | 21.69 | 34.53 |
| p95 | 42 | 36 | 53 |
| p99 | 185 | 114 | 111 |
| worst | 1588 | 822 | 353 |
| ≥100 ms | 66 | 37 | 47 |
| ≥200 ms | 18 | 5 | 7 |
| ≥400 ms | 1 | 1 | 0 |
| max render:lighting | 285 | 188 | 122 |
| max illuminated-window cost | n/a (unmeasured) | 13.0 | 6.0 |
| max tile integration | 240 | 228 | 241 |
| merge window avg / p95 / worst | 91 / 203 / 1588 | 68 / 145 / 262 | 62 / 124 / 275 |
| merge window ≥100 ms | 45 | 24 | 25 |

Run-to-run machine noise is large (avg 21.7 vs 34.5 for identical code);
the ≥100/≥200 counts and merge-window figures are the reliable signal.

## 9. Worst-frame analysis

- Merge-window frames ≥100 ms (30 sampled): all 30 have `render:lighting`
  as the largest section (180-256 ms) with the window cache at ~0.4 ms;
  per-call timing attributes it to `draw_street_lights` (roads.py). Not fixed
  (out of scope).
- `map_sync:pedestrians` single frames 300-320 ms (known V5 finding).
- `tile_integration` 228-241 ms: the intermittent first-merge-frame outlier
  from V5, still unexplained; not touched (merge code out of scope).
- Startup frames 2-9 lighting/first-build costs, and one 822 ms worst frame
  in run A (unattributed to the window cache; noise/other startup work).

## 10. Correctness

`test_incremental_window_cache_matches_a_full_rebuild_exactly` builds a cache,
grows buildings, extends at one building per frame (zero budget), and
compares the final rendered surface bytes to a from-scratch full rebuild.
Other tests: no regeneration and no repeat on duplicate notice; list growth
without grid growth causes zero redraws; camera move mid-extension equals a
full cache at the original camera blitted at the new one; zoom change equals a
fresh rebuild; unload triggers a correct rebuild. 81 pre-existing renderer
tests pass unchanged.

## 11. Visual behavior

Covered by tests: camera (small move reuse, move during extension), zoom
change, night vs day (existing test). Not manually exercised in a live
window (headless SDL only).

## 12. Tests

Focused: `tests/test_scenery_and_buildings.py` 86 passed (81 + 5 new).
Full: 1132 passed, 5 failed - the known pre-existing flaky set (`test_npc` x2,
`test_rwd_oversteer` x2, `test_simulation_boundary` subprocess import).
`git diff --check` clean. `render/roads.py` and the V5 merge untouched.

## 13. Remaining bottlenecks

`draw_street_lights` cache keyed on `len(ways)` (dominant, roads.py);
`map_sync:pedestrians` ~300 ms; taxi offer brute-force scan; intermittent
250 ms first-merge-frame in `integrate_completed_tiles`; `building_grid`
stage-3 synchronous rebuild (~25 ms).

## 14. Recommendation

Next target: `draw_street_lights()` cache invalidation in `render/roads.py`
(same treatment: key on what the spatial grid indexes, extend
incrementally), then `map_sync:pedestrians`.
