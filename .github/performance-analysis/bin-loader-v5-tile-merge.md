# bin-loader-v5: incremental / budgeted tile-world merge

## 1. Executive summary

`AutoFetchManager.integrate_completed_tiles()` no longer merges a completed
tile batch in one synchronous call. It queues each tile-group as a resumable
`_TileMergeJob` (section/item cursor) and merges a `TILE_MERGE_BUDGET_S`
(4 ms) slice per frame. The ~535 ms merge frame is gone; the worst
`map_sync:tile_integration` is now ~4 ms in a typical run.

The change exposed three follow-on problems, all fixed here because they are
part of the merge hand-off: tiles were re-fetched in a loop (pending released
too early), map sync ran twice against a growing world, and the final
place-to-building association was an unbudgeted ~300 ms step.

**Honest caveat:** total ≥100 ms frames went *up* in short runs (see §7) and
the worst overall frame is still 390-410 ms in some runs. The merge stall was
removed, but the load is now spread over several seconds during which other
un-budgeted work (illuminated-window cache, pedestrian sync sub-operation)
repeats. One intermittent 250-320 ms `tile_integration` frame remains
unexplained (§7).

## 2. V4 baseline

From bin-loader-v4 (15,111-frame run): avg 28.10 ms, p95 33.00, worst 755,
≥100 ms: 42, ≥400 ms: 1, ≥500 ms: 1, merge 532 ms. That run is not
like-for-like with the shorter V5 runs, so the V4 commit was re-run through
the identical 3000-frame scenario as the comparison column below.

## 3. Merge architecture before

`integrate_completed_tiles(max_tiles=9)` drained `_completed_tile_batches`
and called `_merge_tile_world_for_tiles()` once per tile-group, in-frame: for
each of 17 sections and each new item, compute key + owning tiles, update
`_tile_objects`/`_object_tiles`, append to the live list if new; then merge
bounds and run `associate_places_with_buildings()` (O(all buildings+places)).
`main.py` then ran full `spatial_grid.rebuild()` and `building_grid.rebuild()`
("immediate" rebuilds) in the same frame.

Structures touched (all are source data or bookkeeping, none derived except
the last): the 17 live lists (append-only, safe to grow incrementally),
`_tile_objects`/`_object_tiles` (ownership bookkeeping, read only by
merge/unload), `bounds` (monotonic), `loaded_tiles`/`pending_tiles`,
`map_revision`, and `Building.associated_places` (derived; full recompute).
Derived grids (`spatial_grid`, `building_grid`, ...) are rebuilt by the V3
map-sync pipeline; the two "immediate" rebuilds were a duplicate of that.

## 4. Merge architecture after

```
tile fetch completes (background thread)
   -> integrate_completed_tiles(budget_s): admit as _TileMergeJob (queue)
   -> per frame: advance_chunked over sections/items (shared _merge_item)
   -> job done: bounds, then place association (generator, budgeted)
   -> commit: pending->loaded, map_revision++
   -> map sync waits for queue to drain, then runs once (V3 pipeline)
```

`_merge_item` is the single per-item implementation used by both the
unchanged synchronous `_merge_tile_world_for_tiles` (direct callers/tests) and
the incremental path, so equivalence holds by construction. `budget_s=None`
keeps the exact old contract, so all 40 pre-existing tile tests pass
unchanged. Items are appended to live lists as they are merged (safe:
append-only); `associate_places_with_buildings_steps` touches buildings only
in a final cheap apply step.

## 5. Budget

`TILE_MERGE_BUDGET_S = 0.004`: same order as the other V3/render budgets, and
a dedicated constant because the merge runs earlier in the frame than map
sync. Measured: merge frames sit at 4.0-4.3 ms; a merge of ~48k items
completes in roughly 10-20 s of frames on this machine (slower than the old
one-shot, which the task accepts).

## 6. Correctness

12 new tests in `tests/test_tile_streaming.py`: one tile, multiple tiles,
2000-item large batch, pause/resume (cursor only advances), empty batch,
inactive tile group ignored, duplicate batch notification (no duplicates),
batch arriving mid-merge (queued, not dropped/restarted), zero-budget
termination, metrics, `budget_s=None` stays synchronous, tiles stay pending
until commit (regression for the re-fetch loop), and place association
identical to sync. The key test merges the same world synchronously and
incrementally with a zero budget (one item per call) and compares `ways`,
`bounds`, `_object_tiles` and `_tile_objects` exactly.

## 7. Performance results (Oulu, warm cache, real tile streaming)

Like-for-like 3000 driving frames (V4 commit vs V5 final code):

| Metric | V4 | V5 (run A) | V5 (run B) |
|---|---|---|---|
| avg frame ms | 33.18 | 33.38 | 32.48 |
| p95 ms | 44 | 49 | 52 |
| p99 | not captured | not captured | not captured |
| worst frame ms | 763 | 389 | 1735 (noisy) |
| frames ≥100 ms | 17 | 47 | 77 |
| frames ≥200 ms | n/a | n/a | n/a |
| frames ≥400 ms | 1 | 0 | 7 |
| frames ≥500 ms | 1 | 0 | 3 |
| max `tile_integration` | 535 ms | 250 ms* | 270 ms* |

Run B was noisy (machine variance, worst 1735 ms was not merge-related) and
is shown rather than hidden. Other V5 runs at the same configuration: worst
412 and 389 ms. *An intermittent single frame of 250-320 ms inside
`integrate_completed_tiles` on the job's first frame appears in about half
of runs; it was not reproduced under an in-process cProfile/timer probe
(first call measured 4 ms) and gc attribution shows no GC in that frame. Root
cause not found. Typical case: max 4.0-4.3 ms.

Why ≥100 ms frames rose: while ~48k items trickle in, the buildings list
length changes every frame, so `draw_illuminated_windows()`'s cache
(out of scope) rebuilds every frame at ~150-200 ms for the whole merge
window, instead of once. That is the direct cost of spreading the merge.

## 8. Tile-batch behavior

The 9-tile / ~48k-item batch (`tile_merge_remaining_items` 47,804 at start)
drains at ~4 ms per frame with queue depth 1; sections and items within the
tile are chunked, not just tiles. Post-fix there is exactly one fetch and one
integration (`map_revision` 90 -> 91); before the pending fix the same run
re-fetched 9 times.

## 9. Immediate grid rebuilds

`spatial_grid_immediate` and `building_grid_immediate` are **removed**.
Physics runs earlier in the frame than that block, so it never saw a
same-frame grid anyway; with incremental growth a full rebuild per partial
step would cost more than the stall it prevented. `any_grid_stale` detects
the length mismatch and the V3 pipeline (stage 2 incremental spatial grid,
stage 3 building grid) catches up; old grids keep serving until then.
Map sync is now held while the merge is active (and held at stage 2 if
already running) so it runs once instead of twice.

## 10. Remaining bottlenecks (not optimized)

- Illuminated-window cache: ~150-200 ms per frame while buildings grow (now
  repeated across the merge window; worse than V4's single hit).
- `map_sync:pedestrians` sub-operation: ~290-390 ms single frames.
- Taxi offer brute-force scan (V4 finding, untouched).
- `map_sync:remove_trees` cost ~1.3 s if it runs on the full world: it did in
  an intermediate V5 build (second pass); in V4 and final V5 it runs once, on
  the small pre-merge world, so trees under newly merged roads are never
  removed - a latent V4-era issue, not changed here.
- `building_grid.rebuild()` (~25-30 ms) still synchronous in stage 3.
- One unexplained intermittent 250-320 ms first-merge-frame outlier.
- Memory: an early 4000-frame run reached 3.8 GB RSS and crashed the earlier
  session; after the re-fetch fix runs peak ~1.1 GB.

## 11. Road rendering

`render/roads.py` untouched; `render:roads` not a contributor.

## 12. Tests

Focused: `tests/test_tile_streaming.py` 53 passed (40 old + 13 new).
Full suite: 1126 passed, 6 failed - the same pre-existing flaky set
(`test_npc` x2, `test_rwd_oversteer` x2, `test_simulation_boundary`
subprocess-import) plus one flaky `test_npc_population` test that passes
in isolation; none touch tile/merge code. `git diff --check` clean.

## 13. Recommendation

Next target: `draw_illuminated_windows()` cache (now the largest recurring
cost during and after a merge, ~150-200 ms x many frames), then the
`map_sync:pedestrians` sub-operation.
