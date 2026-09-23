# bin-loader-v5: Incremental / Budgeted Tile-World Merge

## Objective

Continue the performance investigation/optimization work from `bin-loader-v1` through `bin-loader-v4`.

The `bin-loader-v4.md` investigation identified the dominant remaining tile-streaming stall:

```text
_merge_tile_world_for_tiles()
    ~532 ms in the measured spike frame
    ~70.5% of the 755 ms frame
```

This operation is currently performed synchronously after completed tiles are fetched and before the rest of the map synchronization/rendering pipeline proceeds.

The goal of this task is to make tile-world merging incremental/budgeted so that a large completed tile batch cannot create a single 500+ ms frame.

The desired architecture is similar to the incremental synchronization work implemented in `bin-loader-v3`.

---

# 1. Critical scope

This task is specifically about:

```text
AutoFetchManager.integrate_completed_tiles()
    ->
_merge_tile_world_for_tiles()
```

and the data structures directly required by that merge.

Do NOT optimize unrelated systems in this task.

In particular, do NOT optimize:

- road rendering
- `render/roads.py`
- taxi offer generation
- `pick_random_building_point()`
- `pick_random_road_point()`
- illuminated-window rendering/cache
- NPC simulation
- routing algorithms
- collision detection
- traffic simulation
- Overpass queries
- PBF extraction
- BIN generation/loading

Those were identified as separate future optimization targets in `bin-loader-v4`.

Do not combine multiple optimizations into this task.

---

# 2. Read the existing implementation first

Before modifying code, inspect and understand:

- `src/theroadragetrip/osm/autofetch.py`
- `src/theroadragetrip/main.py`
- the existing map synchronization state machine from `bin-loader-v3`
- `SpatialWayGrid`
- building grid implementation
- world/tile cache structures
- `WorldCache`
- tile integration metrics
- all callers of `integrate_completed_tiles()`
- all callers of `_merge_tile_world_for_tiles()`
- all code that consumes the lists/data structures modified by `_merge_tile_world_for_tiles()`

Also inspect:

- `bin-loader-v1.md`
- `bin-loader-v2.md`
- `bin-loader-v3.md`
- `bin-loader-v4.md`
- `FPS_OPTIMIZE.md`
- existing performance benchmarks
- existing relevant tests

Do not assume the V3 incremental synchronization architecture already solves tile merging. V4 explicitly demonstrated that it does not.

---

# 3. Establish exactly what `_merge_tile_world_for_tiles()` does

Before implementing the optimization, document the current behavior.

Identify every world-level collection or structure that `_merge_tile_world_for_tiles()` modifies.

For example, determine whether it updates:

- ways
- buildings
- water
- scenery
- trees
- grass
- parking
- landmarks
- venues
- POIs
- relations
- spatial indexes
- tile ownership information
- deduplication structures
- caches
- any other derived or source data

Do not assume the list above is complete.

For each structure, determine:

1. Is it source data or derived data?
2. Can it safely be updated incrementally?
3. Does any consumer require the entire merge to be complete?
4. Does it have to remain internally consistent while the merge is paused?
5. Does it have an existing incremental rebuild mechanism?
6. Is it currently rebuilt again later by the V3 map-sync pipeline?

The result should be documented in the final report.

---

# 4. Preserve semantic behavior exactly

The optimization must not change game behavior.

The final state after an incremental merge must be equivalent to the existing synchronous merge.

For the same completed tile set:

```text
old synchronous merge
        ==
new incremental merge after completion
```

This applies to:

- item counts
- item identity
- tile ownership
- deduplication
- ordering where ordering is semantically relevant
- geometry
- building data
- road data
- water/scenery data
- any other world data touched by the merge

Do not accept approximate equivalence.

---

# 5. Do not expose partially invalid world state

This is the most important architectural constraint.

The merge may be spread across multiple frames, but the game must never observe a half-updated structure in a way that violates existing assumptions.

Analyze each data structure individually.

Prefer designs such as:

```text
completed tile batch
        ↓
pending merge state
        ↓
incremental processing
        ↓
complete/commit
```

where appropriate.

If a structure can safely be appended incrementally, that is fine.

If a structure must be atomically published, prepare it separately and commit it when complete.

Do not introduce transient states that can cause:

- missing roads
- corrupted geometry
- duplicate entities
- broken routing
- invalid spatial indexes
- incorrect collision geometry
- inconsistent building data
- crashes
- intermittent rendering artifacts

---

# 6. Budgeting model

Use the same general philosophy as `bin-loader-v3`.

The merge should have a small per-frame time budget.

Do not hard-code the existing road-rendering budget.

Use a dedicated constant, for example:

```python
TILE_MERGE_BUDGET_S = ...
```

Choose the value based on the existing architecture and benchmark results.

The exact value should be justified in the report.

The implementation must:

- process as much work as possible within the budget
- yield before producing a large frame
- resume on the next frame
- preserve progress
- eventually complete
- not restart already completed work
- not duplicate items
- handle multiple completed tiles in one batch

---

# 7. Handle large tile batches

V4 demonstrated a batch containing approximately:

```text
9 tiles
18,000+ new items
```

The implementation must explicitly support large batches.

Do not solve the problem merely by processing one tile per frame if a single tile can itself be expensive.

Prefer chunking within tiles where necessary.

The algorithm should therefore be able to do something conceptually similar to:

```text
pending batch
    ├── tile A
    │    ├── chunk
    │    ├── chunk
    │    └── complete
    ├── tile B
    │    ├── chunk
    │    └── ...
    └── tile C
         └── ...
```

rather than assuming every tile is cheap.

---

# 8. Interaction with existing V3 map synchronization

This is critical.

V4 discovered that there are currently two different mechanisms involved:

```text
integrate_completed_tiles()
    ↓
spatial_grid_immediate
building_grid_immediate
```

and separately:

```text
map_sync_stage
    ↓
incremental spatial grid rebuild
incremental building-related synchronization
```

Do NOT blindly preserve duplicate work.

Trace exactly why the immediate rebuilds exist.

Determine whether the new incremental merge can safely hand off to the existing V3 synchronization pipeline.

The target architecture should ideally become:

```text
tile fetch completes
        ↓
pending tile merge
        ↓
incremental tile-world merge
        ↓
existing incremental map synchronization
        ↓
render/simulation
```

rather than:

```text
tile fetch completes
        ↓
huge synchronous merge
        ↓
immediate grid rebuild
        ↓
incremental grid rebuild again
```

If the immediate rebuilds are still required, document precisely why.

If they are redundant, remove/bypass them carefully and add regression tests proving correctness.

Do not remove them merely because they look redundant.

---

# 9. Interaction with loading-screen behavior

Do NOT remove or redesign the existing loading-screen behavior.

The V4 report explicitly established that:

```text
_wait_for_active_tile_fetch()
```

already intentionally blocks while waiting for tile fetch completion.

That behavior is out of scope.

The goal is only to eliminate the subsequent synchronous merge stall.

Keep:

```text
tile fetch wait
    ↓
loading screen
    ↓
fetch completes
```

as-is.

After the fetch completes, however, the merge should no longer produce a 500+ ms frame.

---

# 10. Correct handling of repeated calls

The incremental operation must be safely callable once per frame.

It must support:

- pause
- resume
- multiple consecutive calls
- zero available budget
- empty batches
- one tile
- many tiles
- repeated completed-tile notifications
- a new completed batch arriving while an older merge is still in progress

Do not restart an existing merge because a new tile batch arrives.

If new tiles arrive during an existing merge, queue them correctly.

Ensure that the same tile cannot be merged twice.

---

# 11. Failure and cancellation behavior

Inspect how tile failures are currently handled.

Preserve existing semantics for:

- failed tile fetches
- invalid tile data
- empty tiles
- duplicate tiles
- cache misses
- cache hits
- cancelled/stale tile requests

Do not silently drop failed or pending work.

If an incremental merge can fail partway through, make sure the state machine can recover safely.

---

# 12. Instrumentation

Add precise profiling around the new incremental merge.

At minimum expose:

```text
map_sync:tile_integration
```

or a more specific hierarchy such as:

```text
map_sync:tile_integration
    tile_merge:ways
    tile_merge:buildings
    tile_merge:water
    tile_merge:scenery
    ...
```

Only add stages that are actually useful.

Measure:

- work performed this frame
- elapsed time this frame
- remaining work
- number of pending tiles
- number of processed items
- number of completed tiles
- number of queued tiles

Do not leave noisy permanent debug logging in the normal runtime path.

---

# 13. Benchmark requirements

Use the same real Oulu environment as `bin-loader-v4`:

```text
--preset oulu --no-menu --osm-source pbf
```

Use:

```text
assets/roads/oulu.bin
```

and the real auto-fetch/tile-streaming path.

Do not replace tile streaming with mocks.

Do not use a synthetic miniature dataset as the primary performance proof.

Warm WorldCache should be used for the main comparison so that disk/network fetch time does not dominate the result.

---

# 14. Required before/after measurements

Measure at least:

### Before

From the V4 baseline:

```text
average frame          ~28.10 ms
p95                    ~33.00 ms
worst                   755 ms
>=400 ms frames           1
```

The exact values may vary slightly between runs; report the actual values.

### After

Capture:

- average frame
- p95
- p99 if available
- worst frame
- number of frames >=100 ms
- number >=200 ms
- number >=400 ms
- number >=500 ms
- maximum `map_sync:tile_integration`
- maximum per-frame tile-merge work

Most importantly:

**demonstrate that the former ~532 ms synchronous merge no longer appears as one frame-sized stall.**

---

# 15. Correctness tests

Add focused tests for the incremental merge.

At minimum cover:

1. one tile
2. multiple tiles
3. large batch
4. pause/resume
5. empty batch
6. duplicate tile notification
7. new tiles arriving while another merge is active
8. exact final-state equivalence with the old synchronous implementation
9. no duplicate world objects
10. all pending work eventually completes

If practical, create a test helper that executes:

```text
synchronous merge
```

and:

```text
incremental merge with tiny budgets
```

and compares their final state.

This is especially important.

The incremental version should still produce the same final world state even when forced to yield after almost every operation.

---

# 16. Do not optimize taxi offers in this task

V4 also discovered that:

```text
pick_random_building_point()
pick_random_road_point()
```

can occasionally take:

```text
175–650 ms
```

and use a brute-force spatial scan.

This is a real performance problem, but it is NOT part of this task.

Do not modify it.

Do not add a spatial index for taxi offers.

Do not include taxi optimization in the same patch.

Mention it in the final report as a known follow-up only.

---

# 17. Do not optimize illuminated windows in this task

V4 also identified:

```text
draw_illuminated_windows()
```

as an approximately 100+ ms cache rebuild after building-list changes.

Do not optimize it in this task.

Do not introduce incremental illuminated-window rendering.

That should be a separate future task so its impact can be measured independently.

---

# 18. Road rendering remains out of scope

Do not modify:

```text
src/theroadragetrip/render/roads.py
```

V1 and V4 already established that road rendering is not the source of the large frame spikes.

---

# 19. Regression testing

Run:

```text
git diff --check
```

Run focused tests for the modified code.

Then run the full test suite.

Report:

- focused tests
- full suite
- failures
- whether failures are new or pre-existing

Do not hide unrelated existing failures.

---

# 20. Performance correctness

Do not declare success merely because average FPS improves.

The key metric is removal of the large synchronous frame spike.

The desired result is approximately:

```text
Before:

tile merge
██████████████████████████████████████████████████  ~532 ms
```

becoming something conceptually like:

```text
Frame N:
████  ~4 ms

Frame N+1:
████  ~4 ms

Frame N+2:
████  ~4 ms

...
```

while the rest of the game remains responsive.

A somewhat higher total merge duration is acceptable if it dramatically reduces worst-frame latency, provided the final state remains correct.

---

# 21. Implementation quality

Keep the implementation understandable.

Prefer an explicit state object/state machine over scattered boolean flags.

The state should make it obvious:

- whether a merge is active
- which tile is being processed
- what part of that tile is being processed
- what remains
- when the merge is complete

Follow the existing codebase conventions from V3.

Do not introduce a generic framework unless it is genuinely useful.

Do not over-engineer this.

---

# 22. Required final report

Create:

```text
bin-loader-v5.md
```

The report must contain:

## 1. Executive summary

What changed and why.

## 2. Previous V4 baseline

Include:

```text
average frame
p95
worst frame
>=100ms
>=400ms
>=500ms
```

## 3. Merge architecture before

Explain exactly how completed tiles were merged synchronously.

## 4. Merge architecture after

Explain the new incremental state machine.

Include a simple flow diagram.

## 5. Budget

State the chosen merge budget and why.

## 6. Correctness

Explain how final-state equivalence was verified.

## 7. Performance results

Include before/after table.

At minimum:

```text
Metric                    V4       V5
average frame
p95
p99
worst frame
frames >=100ms
frames >=200ms
frames >=400ms
frames >=500ms
max tile integration
```

## 8. Tile-batch behavior

Show how the implementation behaves with the large multi-tile batch.

## 9. Immediate grid rebuilds

Explicitly explain whether:

```text
spatial_grid_immediate
building_grid_immediate
```

still exist.

If removed or changed, explain why correctness is preserved.

If retained, explain why they are necessary.

## 10. Remaining bottlenecks

Do not optimize them.

Just list the evidence:

- illuminated-window cache
- taxi offer brute-force lookup
- anything else discovered

## 11. Road rendering

Confirm it remains unchanged and is not a bottleneck.

## 12. Tests

Report focused and full-suite results.

## 13. Final recommendation

Identify the next optimization target based strictly on measured evidence.

Do NOT automatically optimize the next target in this task.

---

# 23. Acceptance criteria

The task is successful only if all of the following are true:

- `_merge_tile_world_for_tiles()` no longer blocks one frame for hundreds of milliseconds.
- Large tile batches are processed incrementally.
- Work resumes correctly across frames.
- No tile is merged twice.
- No world objects are lost.
- Final incremental state matches synchronous state.
- Existing loading-screen behavior remains unchanged.
- Existing V3 incremental synchronization remains correct.
- Duplicate/redundant grid rebuilds are either removed safely or explicitly justified.
- Road rendering remains untouched.
- Taxi-offer code remains untouched.
- Illuminated-window code remains untouched.
- Focused tests pass.
- Full test suite is run.
- `git diff --check` passes.
- `bin-loader-v5.md` is produced.
- The performance report contains actual measured before/after results.

---

## Important

Do not stop after identifying the problem.

Implement the incremental tile-world merge, test it, benchmark it, and document the result.

At the same time, do not expand the task into a general performance refactor.

The single objective is:

> **Turn the synchronous ~532 ms tile-world merge identified by bin-loader-v4 into a correct, incremental, budgeted operation without changing gameplay semantics.**