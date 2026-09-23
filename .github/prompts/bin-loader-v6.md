# bin-loader-v6: Incremental / Budgeted Illuminated-Window Cache

## Objective

Continue the performance optimization work from:

- `bin-loader-v1`
- `bin-loader-v2`
- `bin-loader-v3`
- `bin-loader-v4`
- `bin-loader-v5`

The `bin-loader-v5` implementation successfully converted the approximately 532 ms synchronous tile-world merge into a budgeted incremental operation.

However, V5 exposed a new major performance regression:

```text
while the incremental tile merge is active:

buildings list changes
        ↓
draw_illuminated_windows() cache invalidates
        ↓
full illuminated-window cache rebuild
        ↓
~150–200 ms/frame
        ↓
repeat for many merge frames
```

This now creates repeated large frame spikes during tile integration.

The V4 implementation paid this cost approximately once when the building list changed.

V5 spreads the building-list change over many frames, causing the same cache to rebuild repeatedly.

The goal of this task is therefore:

> Make the illuminated-window cache incremental and/or intelligently invalidated so that incremental tile merging does not cause a 150–200 ms cache rebuild on every frame.

---

# 1. Strict scope

This task is ONLY about the illuminated-window rendering/cache implementation.

Primary code:

```text
src/theroadragetrip/render/buildings.py
```

Specifically investigate:

```text
draw_illuminated_windows()
_illuminated_window_cache
```

and all related cache state/helpers.

Do NOT optimize unrelated systems.

Do NOT modify:

- `render/roads.py`
- `_merge_tile_world_for_tiles()`
- taxi offer generation
- `pick_random_building_point()`
- `pick_random_road_point()`
- pedestrian synchronization
- NPC simulation
- traffic
- routing
- collision detection
- Overpass
- PBF extraction
- BIN generation
- tile streaming
- WorldCache

V5 is considered the baseline for this task.

---

# 2. Read the previous work first

Before changing code, inspect:

```text
bin-loader-v1.md
bin-loader-v2.md
bin-loader-v3.md
bin-loader-v4.md
bin-loader-v5.md
```

Also inspect:

```text
src/theroadragetrip/render/buildings.py
src/theroadragetrip/main.py
```

and the existing rendering/cache implementations for:

- roads
- buildings
- scenery
- water
- grass

The codebase already contains several incremental cache implementations.

Use those as architectural references where appropriate.

Do not blindly copy their implementation.

---

# 3. Understand the current cache invalidation

First determine exactly why the illuminated-window cache is invalidated.

V4/V5 evidence indicates that it is currently tied to the buildings list length/identity.

Trace:

```text
buildings list changes
    ↓
cache invalidation condition
    ↓
draw_illuminated_windows()
    ↓
full cache rebuild
```

Document:

- what invalidates the cache
- what data the cache contains
- what part of the cache is actually affected by a newly added building
- whether existing buildings can change after insertion
- whether building order is stable
- whether buildings are ever removed
- whether building geometry can mutate
- whether window geometry depends on camera/zoom/time/weather
- whether the cache contains screen-space or world-space information
- whether lighting state changes invalidate it
- whether day/night transitions invalidate it

Do not implement anything until these assumptions are verified from the code.

---

# 4. Preserve visual correctness

The optimization must not change the visual result.

For identical:

- building data
- camera
- zoom
- lighting/time state
- window parameters

the optimized cache must produce the same illuminated-window output as the current implementation.

Do not accept approximate equivalence.

Pay particular attention to:

- window positions
- window counts
- building orientation
- window geometry
- visibility
- night/day behavior
- alpha/transparency
- zoom behavior
- camera movement
- buildings entering/leaving the viewport
- tile integration
- cache rebuild completion

---

# 5. Do NOT simply rebuild the entire cache less frequently

A solution such as:

```python
if buildings_changed:
    invalidate()
```

changed to:

```python
if buildings_changed and time_since_last_rebuild > 1:
    invalidate()
```

is NOT sufficient.

Likewise, do not simply disable invalidation.

The cache must eventually contain all required buildings.

The preferred design is incremental work:

```text
existing cache
    +
new/changed buildings
    ↓
incremental cache update
```

rather than:

```text
existing cache discarded
    ↓
rebuild every building
```

---

# 6. Determine whether the cache can be append-only

V5 established that world building lists are append-only during incremental tile merging.

Verify whether this is true for the illuminated-window cache.

If buildings are only added, an ideal architecture may be:

```text
existing illuminated-window cache
        +
new building window geometry
        ↓
incremental cache extension
```

For example:

```text
cache contains buildings 0..9999

tile merge adds buildings 10000..10100

next frame:
    process only buildings 10000..10100

cache becomes:
    buildings 0..10100
```

Do not assume this is safe.

Verify the actual data model first.

---

# 7. Handle tile merging correctly

The critical scenario is:

```text
V5 incremental tile merge
        ↓
buildings appended over many frames
        ↓
illuminated-window rendering
```

The optimized implementation must NOT rebuild all existing windows every time a building is appended.

The desired behavior is approximately:

```text
Frame N:
    merge buildings 1000-1100
    generate windows only for those buildings

Frame N+1:
    merge buildings 1100-1200
    generate windows only for those buildings

...
```

Use a dedicated budget.

For example:

```python
ILLUMINATED_WINDOW_CACHE_BUDGET_S = ...
```

Do not automatically reuse `TILE_MERGE_BUDGET_S`.

The appropriate value should be determined from measurements.

---

# 8. Use incremental work, not one large append

A single tile may contain many buildings.

Therefore this is NOT sufficient:

```text
one frame = process one tile's entire building set
```

If a tile contains thousands of buildings, it could simply move the same spike to one frame.

The implementation should be capable of:

```text
building 1
building 2
building 3
...
```

or another appropriately sized chunk.

Use a resumable cursor/state machine.

---

# 9. Cache state design

Prefer explicit state.

For example, conceptually:

```text
cache state:

valid buildings
pending buildings
cursor
generation/revision
cache surface/data
```

The actual implementation does not need to use these exact names.

The important property is that the state makes it clear:

- which buildings have been processed
- which remain
- whether a rebuild is active
- whether the cache is complete
- which generation of building data it represents

Avoid scattered boolean flags.

---

# 10. Camera movement

The implementation must remain correct while the camera moves.

Test:

- stationary camera
- slow movement
- fast movement
- camera movement while cache rebuild is active
- zoom changes
- camera movement across tile boundaries

Determine whether the cache itself is:

- world-space
- screen-space
- camera-relative
- bucketed by zoom

If camera/zoom changes require a complete rebuild, preserve that semantic behavior unless it can be safely optimized.

Do not accidentally make a cache tied to one camera position.

---

# 11. Day/night and lighting changes

Inspect all existing invalidation conditions related to:

- time of day
- night/day
- lighting intensity
- weather
- building visibility
- window state

Preserve them.

If the cache is geometry-only and lighting is applied later, do not unnecessarily invalidate geometry.

If lighting affects the cached pixels directly, determine whether an incremental rebuild is still safe.

Document the conclusion.

---

# 12. Avoid repeated invalidation during V5 merge

This is the main acceptance scenario.

The following should NOT happen:

```text
Frame 1:
    building list length changed
    full cache rebuild

Frame 2:
    building list length changed
    full cache rebuild

Frame 3:
    building list length changed
    full cache rebuild
```

Instead:

```text
Frame 1:
    cache update begins

Frame 2:
    cache update resumes

Frame 3:
    cache update resumes

...

Frame N:
    cache complete
```

The already processed buildings must not be regenerated.

---

# 13. Rendering during an incomplete rebuild

Determine what should be rendered while the incremental cache is incomplete.

Prefer:

```text
old valid cache
+
completed incremental additions
```

rather than:

```text
blank cache until rebuild completes
```

If the existing implementation has a previous valid cache, keep it visible while new work is processed where possible.

Avoid visual flicker.

Do not block the entire frame waiting for the cache to finish.

---

# 14. First-build behavior

There may be no existing cache on the first render.

Handle that separately.

A cold first build may legitimately take longer than steady-state incremental updates, but it should still be budgeted if practical.

Do not introduce a new 100+ ms first-frame stall merely to optimize incremental updates.

Measure:

- cold cache
- warm cache
- incremental building additions

separately.

---

# 15. Cache invalidation and removals

Verify whether buildings can ever be removed from the live world.

If they can:

- determine how removal is represented
- invalidate affected window data correctly

If buildings are append-only in the current architecture, document that fact and do not introduce unnecessary removal machinery.

---

# 16. Performance instrumentation

Add precise profiling if existing instrumentation is insufficient.

Do not leave noisy debug logging.

Expose useful measurements such as:

```text
render:lighting
render:lighting:illuminated_windows
```

and, if practical:

```text
window_cache:
    processed buildings
    pending buildings
    cache complete
    rebuild time
```

The instrumentation should make it possible to distinguish:

```text
lighting baseline
```

from:

```text
illuminated-window cache rebuild
```

This distinction was missing in V4.

---

# 17. Benchmark scenario

Use the same Oulu benchmark configuration as V5:

```text
--preset oulu --no-menu --osm-source pbf
```

Use:

```text
assets/roads/oulu.bin
```

Use real tile streaming.

Use warm WorldCache.

Do NOT disable auto-fetch.

Do NOT replace tile streaming with mocks.

---

# 18. Primary benchmark

The most important benchmark is the V5 tile-merge scenario.

Use a large completed tile batch comparable to:

```text
9 tiles
~48,000 items
```

and allow the V5 incremental merge to run normally.

Measure the frames during the merge.

The previous behavior was approximately:

```text
tile merge active
    ↓
building list changes every frame
    ↓
illuminated-window cache
    ↓
~150–200 ms/frame
```

The new target is:

```text
tile merge active
    ↓
building list changes
    ↓
small incremental cache work
    ↓
no repeated 150–200 ms frames
```

---

# 19. Before/after measurements

Use V5 as the baseline.

Report:

```text
Metric                         V5       V6
average frame
p95
p99
worst frame
frames >=100ms
frames >=200ms
frames >=400ms
max render:lighting
max illuminated-window cost
max tile integration
```

Also measure specifically during the tile merge window:

```text
merge-window average frame
merge-window p95
merge-window worst frame
number of >100ms frames
```

This is important because the V5 overall average can hide the repeated cache rebuilds.

---

# 20. Success criteria

The main success criterion is NOT simply average FPS.

The key requirement is:

> Incremental tile merging must no longer cause a full illuminated-window cache rebuild on every frame.

Specifically:

- no repeated 150–200 ms window-cache rebuilds during merge
- no full-cache rebuild for every building-list append
- cache eventually contains all required window geometry
- visual output remains correct
- existing cache behavior remains correct after merge completion
- camera movement remains correct
- zoom changes remain correct
- day/night behavior remains correct

---

# 21. Correctness tests

Add focused tests where practical.

At minimum cover:

1. cold cache
2. warm cache
3. adding one building
4. adding multiple buildings
5. adding buildings over multiple frames
6. pause/resume
7. duplicate update notification
8. camera movement during rebuild
9. zoom change during rebuild
10. final incremental output equals full rebuild output

The most important correctness test should compare:

```text
full cache rebuild
```

against:

```text
incremental cache build
```

using identical building data and rendering state.

The final generated cache/output must match.

---

# 22. Regression testing

Run:

```text
git diff --check
```

Run focused tests for the modified renderer.

Then run the full test suite.

Report:

- focused test count
- full test count
- failures
- whether failures are pre-existing

Do not hide unrelated flaky tests.

---

# 23. Do not touch the V5 merge implementation unnecessarily

V5's incremental merge is the current baseline.

Do not redesign it in this task.

Only make the minimum integration changes necessary if the renderer requires an explicit notification/generation/cursor mechanism.

If such a change is required, explain it in the final report.

---

# 24. Do not optimize pedestrian synchronization

V5 also reported:

```text
map_sync:pedestrians
~290–390 ms single frames
```

Do not optimize it here.

It should remain a separate follow-up task.

Likewise do not optimize:

```text
pick_random_building_point()
pick_random_road_point()
```

The taxi-offer spatial lookup remains a separate task.

---

# 25. Final report

Create:

```text
bin-loader-v6.md
```

The report must contain:

## 1. Executive summary

What was changed and why.

## 2. V5 baseline

Include the relevant V5 measurements.

## 3. Existing cache architecture

Explain exactly how illuminated-window caching worked before V6.

## 4. New architecture

Explain the incremental cache state machine.

Include a simple flow diagram.

## 5. Cache invalidation

Document all invalidation conditions.

## 6. Budget

State the chosen budget and justify it.

## 7. Tile-merge behavior

Explain exactly how the V6 cache behaves while V5 incrementally adds buildings.

## 8. Performance

Provide before/after measurements.

## 9. Worst-frame analysis

Explain every remaining >100 ms frame observed during the benchmark.

Do not hide outliers.

If another system is responsible, identify it.

## 10. Correctness

Explain how incremental and full rebuild results were compared.

## 11. Visual behavior

Document camera, zoom and day/night testing.

## 12. Tests

Report focused and full-suite results.

## 13. Remaining bottlenecks

Do not optimize them.

At minimum mention the known V5 findings:

- `map_sync:pedestrians`
- taxi offer brute-force lookup
- any remaining tile-sync costs
- anything newly discovered

## 14. Recommendation

Based strictly on measurements, identify the next optimization target.

Do not implement the next optimization in this task.

---

# 26. Acceptance criteria

The task is complete only if:

- `draw_illuminated_windows()` no longer performs a full cache rebuild whenever the building list grows by one incremental merge chunk.
- Illuminated-window cache work is incremental/budgeted.
- Large building batches cannot create a new single-frame 100–200 ms window-cache stall.
- Existing valid cache remains usable while incremental work is pending where technically possible.
- Final cache output matches a full rebuild.
- Camera movement remains correct.
- Zoom changes remain correct.
- Day/night behavior remains correct.
- V5 tile merge behavior remains unchanged.
- `render/roads.py` remains untouched.
- pedestrian synchronization remains untouched.
- taxi offer lookup remains untouched.
- focused tests pass.
- full test suite is run.
- `git diff --check` passes.
- `bin-loader-v6.md` is produced.
- actual before/after measurements are included.

---

## Final instruction

Do not broaden this into a general rendering refactor.

The single objective is:

> **Make the illuminated-window cache incremental and budgeted so that V5's incremental tile-world merge does not turn one 100+ ms cache rebuild into dozens of repeated 150–200 ms frame stalls.**