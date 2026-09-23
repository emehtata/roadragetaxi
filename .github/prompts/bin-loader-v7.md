# bin-loader-v7: Incremental / Budgeted Street-Light Cache

## Objective

Continue the performance optimization work from:

- `bin-loader-v1`
- `bin-loader-v2`
- `bin-loader-v3`
- `bin-loader-v4`
- `bin-loader-v5`
- `bin-loader-v6`

The `bin-loader-v6` investigation corrected an important earlier assumption.

The repeated 150–200 ms `render:lighting` spikes during incremental tile merging were NOT primarily caused by illuminated windows.

Per-call profiling established that the dominant cost is:

```text
src/theroadragetrip/render/roads.py
    draw_street_lights()
```

The current street-light cache is invalidated by changes such as:

```text
len(ways)
id(ways[-1])
```

During the V5 incremental tile merge, `ways` grows incrementally.

As a result, the street-light cache is rebuilt repeatedly while the world is being extended.

V6 measured:

```text
draw_street_lights()
    28 calls > 50 ms
    maximum ~185 ms
```

while the V6 illuminated-window cache was only:

```text
maximum ~6–13 ms
average ~0.4 ms
```

The goal of this task is therefore:

> Make the street-light cache incremental/budgeted and invalidate it based on the actual indexed/rendered data rather than raw `ways` list growth.

---

# 1. Strict scope

This task is specifically about:

```text
src/theroadragetrip/render/roads.py
```

and the street-light rendering/cache implementation.

Primary target:

```text
draw_street_lights()
```

Inspect all helpers and cache state directly involved in it.

Do NOT optimize unrelated systems.

Do NOT modify:

- `_merge_tile_world_for_tiles()`
- `integrate_completed_tiles()`
- illuminated-window cache
- pedestrian synchronization
- taxi offer generation
- `pick_random_building_point()`
- `pick_random_road_point()`
- NPC simulation
- traffic
- routing
- collision detection
- Overpass
- PBF extraction
- BIN generation/loading
- general road rendering

The only reason to modify surrounding road-render code is if it is directly required for correct street-light cache integration.

---

# 2. Read the previous work

Before modifying anything, inspect:

```text
bin-loader-v4.md
bin-loader-v5.md
bin-loader-v6.md
```

Also inspect:

```text
src/theroadragetrip/render/roads.py
```

and the code that provides:

- `ways`
- `SpatialWayGrid`
- building/world updates
- street-light data
- tile integration
- map synchronization
- camera state
- zoom state

Pay particular attention to:

```text
draw_street_lights()
```

and determine:

1. What the cache actually contains.
2. Which ways/buildings/objects contribute to it.
3. How the visible set is determined.
4. Whether visibility comes from `ways`, `SpatialWayGrid`, or another structure.
5. What `len(ways)` and `id(ways[-1])` are being used to detect.
6. Whether the cache is screen-space or world-space.
7. What changes genuinely require a rebuild.
8. Whether newly appended ways can be incrementally added.
9. Whether ways can be removed/unloaded.
10. Whether street-light geometry can mutate after insertion.

Do not implement the optimization until these assumptions are verified from the code.

---

# 3. Critical lesson from bin-loader-v6

Do NOT assume:

```text
ways changed
    =
visible street-light geometry changed
```

V6 demonstrated exactly why this is dangerous.

During V5 tile merging:

```text
ways list grows
        ↓
building grid has NOT necessarily caught up yet
        ↓
actual rendered building/road set may remain unchanged
```

Therefore a cache key such as:

```python
(len(ways), id(ways[-1]))
```

is insufficiently precise.

The new implementation should be based on the actual data structure that determines which street lights are rendered.

If that is `SpatialWayGrid`, use its relevant revision/count/index state.

If there is no suitable revision mechanism, design the smallest appropriate one.

---

# 4. First determine what the cache represents

Document the current cache.

Determine whether it contains:

- street-light positions
- glow circles
- lamp geometry
- illuminated road segments
- screen-space pixels
- world-space geometry
- a composited surface
- precomputed visibility information
- some combination

Determine which portions are expensive.

Measure separately if necessary:

```text
cache lookup
cache invalidation
cache rebuild
per-light geometry generation
surface drawing
blit
```

Do not assume the entire `draw_street_lights()` duration is cache construction.

The V6 result shows that per-call instrumentation is necessary.

---

# 5. Correct cache invalidation

The existing cache appears to use information such as:

```text
len(ways)
id(ways[-1])
```

Do not simply delete those checks.

First determine what they were protecting against.

Replace them with a semantically correct invalidation mechanism.

The desired logic is conceptually:

```text
world data changes
        ↓
did the street-light input actually change?
        ↓
NO ──────────────> reuse cache
        │
        YES
        ↓
can the change be appended incrementally?
        │
        ├── YES → incremental extension
        │
        └── NO  → full rebuild
```

---

# 6. Prefer the existing SpatialWayGrid

V6 explicitly identified the mismatch between:

```text
ways list
```

and:

```text
building/spatial grid
```

The existing `SpatialWayGrid` is already used for road rendering and spatial queries.

Investigate whether it can provide a stable indication of:

- indexed way count
- grid revision
- added ways
- removed ways
- changed ways

Prefer reusing an existing authoritative spatial structure over introducing a second independent indexing system.

Do not add a new spatial index if an existing one already provides the required information.

---

# 7. Incremental street-light cache

If street-light geometry can be safely appended, implement a resumable incremental cache update.

Conceptually:

```text
existing cache
    +
new street-light contributors
    ↓
incremental update
```

rather than:

```text
invalidate
    ↓
rebuild all street lights
```

Use a dedicated budget:

```python
STREET_LIGHT_CACHE_BUDGET_S = ...
```

Do not reuse:

```text
TILE_MERGE_BUDGET_S
ILLUMINATED_WINDOW_CACHE_BUDGET_S
```

The appropriate value should be determined from measurements.

---

# 8. Do not confuse world additions with visible additions

This is critical.

Suppose 10,000 new ways are merged, but only 50 are relevant to the visible street-light area.

The cache must not necessarily process all 10,000.

Use the existing spatial query/culling mechanism wherever appropriate.

The implementation should reason about:

```text
new world data
        ↓
potential street-light contributors
        ↓
visible/relevant contributors
        ↓
cache update
```

not:

```text
all ways
    ↓
draw everything
```

---

# 9. Large tile batches

Test the same large V5/V6 scenario:

```text
~9 tiles
~48,000 merged items
```

The street-light cache must not rebuild once per incremental merge frame.

It must be capable of handling large batches without producing:

```text
150 ms
180 ms
200 ms
...
```

frames.

If thousands of new street-light contributors really need processing, spread that work across frames using the budget.

---

# 10. Handle multiple additions while a rebuild is active

The implementation must support:

```text
cache update active
        ↓
more ways arrive
        ↓
extend pending work
```

without:

- restarting from zero
- duplicating lights
- dropping lights
- corrupting the cache

Conceptually:

```text
cursor = 1000
end = 1100

new ways arrive

end = 1150

continue:
1000 -> 1150
```

rather than:

```text
restart:
0 -> 1150
```

where possible.

---

# 11. Preserve a valid previous cache

If an existing valid street-light cache exists, keep it visible while incremental work proceeds where technically possible.

Prefer:

```text
old valid cache
+
completed new work
```

rather than:

```text
cache invalidated
blank/no lights
until rebuild completes
```

Do not introduce visible flicker.

If this is impossible because of the current screen-space architecture, document why and use the least disruptive fallback.

---

# 12. Camera movement

Determine how camera movement affects the street-light cache.

Test:

- stationary camera
- small camera movement
- fast camera movement
- movement during incremental cache update
- crossing a cache boundary
- zoom changes

If the cache is camera-relative, preserve the existing semantics.

If camera movement causes a full rebuild today, determine whether the existing cache can be reused in the same way as the illuminated-window cache.

Do not introduce incorrect screen-space offsets.

---

# 13. Zoom and screen-size changes

Verify:

- zoom changes
- window resize
- resolution changes

Do not accidentally reuse a cache generated for another zoom or screen size.

If these require a full rebuild, retain that behavior unless a safe incremental solution exists.

---

# 14. Night/day behavior

Inspect whether street-light geometry and brightness are coupled.

Determine whether:

```text
time of day
darkness
weather
lighting intensity
```

affect:

- cached geometry
- cached pixels
- only final blit/compositing

If brightness/alpha can be applied at render time, avoid unnecessarily rebuilding geometry.

If the cache contains pre-rendered lighting pixels, preserve visual correctness.

Do not alter lighting appearance as part of this optimization.

---

# 15. Profiling requirements

Add or improve profiling so that the following are separately visible:

```text
render:lighting
render:lighting:street_lights
```

If useful, also expose:

```text
street_light_cache:
    full_rebuild_ms
    incremental_ms
    processed_count
    pending_count
    cache_complete
```

The exact names can follow existing project conventions.

The key requirement is that future reports can distinguish:

```text
draw_street_lights total
```

from:

```text
street-light cache rebuild
```

and from unrelated lighting work.

Do not leave verbose per-frame logging enabled in normal gameplay.

---

# 16. Benchmark environment

Use the same environment as V6:

```text
--preset oulu --no-menu --osm-source pbf
```

Use:

```text
assets/roads/oulu.bin
```

Use:

- real tile streaming
- warm WorldCache
- actual game loop
- actual rendering path
- same benchmark harness

Do not use only synthetic microbenchmarks.

Microbenchmarks may supplement the real benchmark but must not replace it.

---

# 17. Primary benchmark

Run the same large tile-merge scenario used by V5/V6:

```text
~9 tiles
~48,000 items
```

Measure the merge window separately.

The V6 baseline is approximately:

```text
merge window:
    average ~62–68 ms
    p95 ~124–145 ms
    worst ~262–275 ms

merge-window frames >=100 ms:
    ~24–25
```

The exact numbers may vary.

The important signal is the repeated `render:lighting` spikes.

---

# 18. Before/after measurements

Use V6 as the baseline.

Report:

```text
Metric                         V6       V7
average frame
p95
p99
worst frame
frames >=100ms
frames >=200ms
frames >=400ms
max render:lighting
max street-light cost
max tile integration
```

Also report merge-window-specific values:

```text
merge-window average
merge-window p95
merge-window worst
merge-window >=100ms
merge-window >=200ms
```

And:

```text
number of full street-light rebuilds
number of incremental updates
number of cache extensions
```

---

# 19. Primary acceptance criterion

The main objective is:

> Incremental tile merging must no longer cause a full street-light cache rebuild on every frame.

The previous behavior:

```text
tile merge
    ↓
ways list grows
    ↓
street-light cache invalidates
    ↓
~150–200 ms
    ↓
next merge frame
    ↓
ways list grows again
    ↓
street-light cache invalidates
    ↓
~150–200 ms
```

must become something closer to:

```text
tile merge
    ↓
street-light input unchanged
    ↓
cache reused
```

or:

```text
tile merge
    ↓
street-light input changed
    ↓
incremental cache update
    ↓
small bounded cost
```

---

# 20. Correctness tests

Add focused tests for:

1. cold cache
2. warm cache
3. no relevant world change
4. ways list grows but indexed street-light input does not change
5. relevant ways added
6. multiple additions
7. incremental update
8. pause/resume
9. new additions while update is active
10. duplicate update notification
11. camera movement
12. zoom change
13. screen-size change
14. unload/removal
15. final incremental result equals full rebuild

The most important test should verify:

```text
full rebuild output
        ==
incremental output
```

for identical input and rendering state.

If the cache is pixel-based, compare the resulting surfaces appropriately.

If it is geometry-based, compare the generated geometry/state.

---

# 21. Unload handling

V6 established that buildings can be removed by tile unloading.

Verify whether street-light source data can also be removed.

If ways are removed:

```text
old cache
    ↓
source data changes
    ↓
affected lights must disappear
```

Do not use an append-only optimization if removals make it incorrect.

If removal requires a full rebuild, that is acceptable if it is rare and documented.

---

# 22. Avoid duplicate indexing

Do not create a second street-light spatial index unless necessary.

The project already has:

```text
SpatialWayGrid
```

Reuse it where possible.

If it cannot provide the required semantics, explain why before introducing a new structure.

---

# 23. Do not modify the tile merge

V5's incremental merge is now the baseline.

Do not redesign:

```text
_merge_tile_world_for_tiles()
integrate_completed_tiles()
```

in this task.

Do not attempt to solve the unexplained:

```text
250–320 ms first-merge-frame
```

outlier here.

That remains a separate problem.

---

# 24. Do not optimize pedestrian synchronization

The V6 report still identifies:

```text
map_sync:pedestrians
~300 ms single frames
```

Do not modify pedestrian synchronization in this task.

It should remain a separate optimization.

Likewise, do not modify:

```text
pick_random_building_point()
pick_random_road_point()
```

---

# 25. Important measurement discipline

Do not assume that reducing:

```text
render:lighting
```

automatically means street-light performance improved.

Use the new per-call instrumentation to prove it.

For every significant remaining `render:lighting` spike, determine:

```text
street lights
illuminated windows
other lighting
```

and report the actual contributor.

This is specifically required because V4's timing-based attribution was incorrect.

---

# 26. Full test suite

Run:

```text
git diff --check
```

Run focused renderer tests.

Then run the full test suite.

Report:

- focused tests
- full suite
- failures
- whether failures are pre-existing
- any newly introduced failures

Do not hide flaky tests.

---

# 27. Final report

Create:

```text
bin-loader-v7.md
```

The report must contain:

## 1. Executive summary

What changed and why.

## 2. V6 baseline

Include actual V6 baseline measurements.

## 3. Existing street-light architecture

Explain:

- cache contents
- invalidation key
- visibility source
- coordinate system
- expensive operations

## 4. Root cause

Explain exactly why V5's incremental world merge caused repeated street-light rebuilds.

## 5. New architecture

Explain the new cache state machine.

Include a simple diagram.

## 6. Cache invalidation

Document precisely what now invalidates the cache.

## 7. Incremental behavior

Explain how newly indexed ways/lights are incorporated.

## 8. Performance

Provide before/after measurements.

## 9. Merge-window analysis

Show whether repeated >100 ms lighting frames disappeared.

## 10. Remaining >100 ms frames

For every important remaining spike, identify the actual subsystem.

Do not attribute it to street lights without evidence.

## 11. Correctness

Explain full-vs-incremental comparison.

## 12. Camera/zoom/day-night behavior

Document test results.

## 13. Tests

Report focused and full suite.

## 14. Remaining bottlenecks

At minimum:

- `map_sync:pedestrians`
- taxi offer brute-force scan
- unexplained first-merge-frame `tile_integration` outlier
- any remaining lighting/rendering bottleneck discovered by V7

Do not optimize those in this task.

## 15. Recommendation

Choose the next optimization target strictly from measured evidence.

---

# 28. Acceptance criteria

The task is complete only if:

- `draw_street_lights()` no longer performs a full cache rebuild merely because `ways` grows.
- Cache invalidation is based on the actual street-light input.
- Relevant additions can be incorporated incrementally where safe.
- Incremental work is budgeted.
- Large tile batches do not create repeated 150–200 ms street-light stalls.
- Existing valid cache remains usable while incremental work proceeds where possible.
- Removed/unloaded ways are handled correctly.
- Camera behavior remains correct.
- Zoom behavior remains correct.
- Lighting/day-night behavior remains correct.
- Incremental and full rebuild results match.
- `render/roads.py` changes are limited to the street-light implementation and required instrumentation.
- V5 tile merge remains unchanged.
- V6 illuminated-window implementation remains unchanged.
- pedestrian synchronization remains unchanged.
- taxi offer lookup remains unchanged.
- focused tests pass.
- full test suite is run.
- `git diff --check` passes.
- `bin-loader-v7.md` is produced.
- actual before/after measurements are included.

---

## Final instruction

Do not turn this into a general road-rendering refactor.

The single objective is:

> **Stop incremental tile-world growth from repeatedly invalidating and rebuilding the street-light cache, while preserving exact visual behavior and keeping street-light cache work bounded per frame.**