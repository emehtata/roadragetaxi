# bin-loader-v8: budgeted street-light contributor preparation

## Objective

Continue the Road Rage Taxi performance optimization on the current branch.

V7 successfully eliminated repeated street-light cache rebuilds caused by raw `ways` list growth and made lamp placement incremental. However, V7 measurements show that expensive **street-light contributor preparation** is still synchronous.

The next goal is:

> Make the entire street-light cache rebuild pipeline incremental and budgeted, including contributor collection, local indexing, junction construction, road/segment classification, and other preparation work that currently happens synchronously before budgeted lamp placement.

Do **not** optimize pedestrians, taxi offers, traffic synchronization, tile integration, or unrelated rendering in this task.

---

# 1. Start by inspecting the existing implementation

Before changing code, inspect the actual current implementation.

Review:

* `src/theroadragetrip/render/roads.py`
* `SpatialWayGrid` implementation
* street-light cache classes/state
* junction/road/segment lighting helpers
* nearby building lookup
* explicit OSM lamp lookup
* any profiler instrumentation added in V7
* V6 and V7 reports
* existing street-light tests

Do not assume the V7 architecture from the report is implemented exactly as described. Verify the actual code.

Identify precisely:

1. What work happens when a street-light cache rebuild starts.
2. Which parts are already budgeted.
3. Which parts are still synchronous.
4. Which data structures are created for a cache job.
5. Which operations scale with:

   * number of visible ways
   * number of buildings
   * number of junctions
   * number of segments
   * number of explicit lamps
6. Which operations are repeated when a grid revision changes.
7. Which operations can safely be resumed.
8. Which operations must use an immutable snapshot.
9. Which operations can be prepared incrementally without changing rendering behavior.

Do not modify code until this analysis is understood.

---

# 2. Preserve the V7 architecture

Do not undo the important V7 behavior.

The existing architecture should remain conceptually:

```text
raw world lists grow
        │
        ▼
completed grid revision changes
        │
        ▼
new street-light cache job
        │
        ├── contributor preparation
        │
        └── lamp placement
                │
                ▼
        atomic cache commit
```

The previous committed geometry and screen-space surface must remain usable while the new job is running.

Raw list growth alone must NOT invalidate the cache.

A new completed `SpatialWayGrid.revision` must create a new job.

A new revision arriving while a job is running must not corrupt or mix the current job's data.

---

# 3. Find the real synchronous bottleneck

V7 reported:

```text
max street-light total: ~118 ms
cache-only preparation probe: 170.33 ms
```

The report specifically identifies these possible contributors:

* nearby-building collection
* junction construction
* per-segment lighting classification
* road/segment indexing
* explicit lamp collection
* other contributor preprocessing

Do not assume which one is responsible.

Add or improve instrumentation so each preparation stage has its own timer.

For example:

```text
render:lighting:street_lights
render:lighting:street_lights:contributors
render:lighting:street_lights:buildings
render:lighting:street_lights:junctions
render:lighting:street_lights:segments
render:lighting:street_lights:classification
render:lighting:street_lights:explicit_lamps
render:lighting:street_lights:placement
render:lighting:street_lights:commit
```

Use the actual implementation's terminology if different.

The instrumentation must make it possible to answer:

> Which exact preparation stage caused a >100 ms street-light frame?

Do not use timing coincidence as evidence.

---

# 4. Design a resumable contributor-preparation state machine

Refactor the street-light cache job so preparation itself can resume across frames.

The exact state structure is up to the implementation, but it should conceptually resemble:

```text
StreetLightCacheJob
    revision
    contributor_snapshot
    phase
    cursor
    prepared_buildings
    prepared_junctions
    prepared_segments
    prepared_lamps
    lighting_index
    placement_state
    output_geometry
```

Possible phases:

```text
SNAPSHOT
BUILDING_CONTRIBUTORS
JUNCTIONS
SEGMENTS
CLASSIFICATION
EXPLICIT_LAMPS
PLACEMENT
COMMIT
```

Do not blindly create all of these phases if some existing implementation already combines them safely.

The important requirement is:

> No expensive preparation stage should process an unbounded number of contributors in one frame.

---

# 5. Use a dedicated preparation budget

Do not reuse the tile merge budget or illuminated-window budget.

Introduce a dedicated constant such as:

```python
STREET_LIGHT_PREP_BUDGET_S = 0.004
```

Keep placement's existing:

```python
STREET_LIGHT_CACHE_BUDGET_S = 0.004
```

unless the current implementation has a better naming convention.

The purpose is to make preparation and placement independently measurable.

A frame should approximately behave like:

```text
prepare <= preparation budget
placement <= placement budget
```

Do not interpret the budget as an exact hard real-time guarantee. Individual atomic operations may exceed it.

---

# 6. Snapshot correctness

The cache job must work from a stable snapshot.

Do not allow:

```text
job starts
ways list changes
buildings list changes
grid changes
job continues using partially changed global structures
```

Instead:

```text
completed revision detected
        │
        ▼
snapshot contributors
        │
        ▼
job operates only on snapshot
```

If creating the snapshot itself is expensive, make snapshot creation resumable too.

The snapshot must be consistent with the completed grid revision.

Do not mix:

```text
old road grid
new building grid
old junction data
new ways
```

unless the existing architecture explicitly guarantees that combination is valid.

---

# 7. Avoid unnecessary work

Be careful not to make the new implementation technically incremental but computationally worse.

For example, avoid:

```python
for every frame:
    rebuild list of all buildings
```

or:

```python
for every visible way:
    scan every building
```

or:

```python
for every segment:
    reconstruct the same junction information
```

Prefer existing spatial indexes:

```text
SpatialWayGrid
BuildingGrid
LampGrid
```

and existing cached/indexed structures where possible.

If a spatial query itself is expensive, measure it before changing it.

Do not replace spatial indexes with brute-force scans.

---

# 8. Keep the committed cache visible

This is critical.

While contributor preparation or placement is running:

```text
previous committed street-light geometry
        +
previous screen-space surface
```

must remain visible.

Do not clear the cache at the beginning of a rebuild.

Do not temporarily render an empty street-light layer.

Do not introduce flicker when:

* entering a new region
* crossing a cache boundary
* a grid revision commits
* several revisions arrive during an update

The new result should become visible atomically when complete.

---

# 9. Handle revisions arriving during preparation

Test this explicitly.

Example:

```text
revision 10
    ↓
start preparation
    ↓
process 4 ms
    ↓
revision 11 arrives
    ↓
continue safely with revision 10 snapshot
    ↓
finish revision 10
    ↓
commit revision 10
    ↓
queue revision 11
    ↓
prepare revision 11
```

Do not mix revision 11 contributors into revision 10's partially built indexes.

If revision 10 becomes obsolete before commit, determine whether it is safe to discard it.

Prefer correctness and bounded work over trying to merge multiple revisions into one partially constructed cache.

Avoid unbounded queues.

If revisions arrive faster than they can be processed, coalesce obsolete pending revisions where correctness permits.

---

# 10. Camera and region behavior

Preserve V7's camera-region behavior.

Small camera movement inside the committed padded region should not rebuild the geometry.

Crossing the committed region boundary should start a new contributor snapshot.

Do not continuously recompute contributor signatures from a moving padded query while the existing committed region is still valid.

The architecture should remain:

```text
camera inside committed region
        ↓
reuse existing geometry

camera crosses region boundary
        ↓
new contributor snapshot
```

Zoom and screen-size changes remain screen-space concerns unless the existing implementation proves otherwise.

Do not make world-space street-light geometry depend on brightness.

---

# 11. Preserve day/night behavior

During daylight, the existing early-out behavior should remain.

Do not perform expensive street-light preparation merely because the camera moved during daylight if the renderer does not need street lights.

Darkness changes should affect the screen-space surface, not force rebuilding world-space geometry.

Do not regress:

* dusk
* night
* dawn
* darkness transitions
* lamp alpha
* pool radius
* lamp direction

---

# 12. Exact visual correctness

The incremental preparation path must produce exactly the same geometry as the existing full rebuild.

Create or extend a test that does:

```text
same world snapshot
        │
        ├── full rebuild
        │
        └── incremental rebuild
```

Then compare:

* lamp count
* lamp positions
* directions
* pool radii
* ordering where relevant
* geometry data
* final rendered output where practical

The result must not merely be visually similar.

Prefer exact equality for deterministic geometry structures.

If floating-point ordering makes exact comparison inappropriate, explain why and use the strongest deterministic comparison available.

---

# 13. Regression tests

Add focused tests for at least:

### A. Budgeted contributor preparation

Create enough contributors that preparation cannot finish in one frame.

Verify:

```text
frame 1: job incomplete
frame 2+: job continues
final frame: job commits
```

### B. Old cache remains visible

Start a rebuild and verify the previously committed result remains available until commit.

### C. Revision during preparation

Start revision N.

While processing it, commit revision N+1.

Verify:

* N job remains internally consistent
* N+1 is not mixed into N
* final committed result corresponds to N+1

### D. Raw list growth

Grow raw `ways`/building lists without changing the completed grid revision.

Verify no street-light geometry rebuild occurs.

### E. Same-count replacement

Replace/remove contributors while keeping list length unchanged.

Commit the grid revision.

Verify the cache invalidates correctly.

### F. Camera boundary

Move the camera inside the committed region.

Verify no rebuild.

Cross the region boundary.

Verify a new job starts.

### G. Zoom/screen

Verify geometry cache behavior remains correct when:

* zoom changes
* screen size changes

### H. Day/night

Verify daylight does not trigger unnecessary street-light preparation.

### I. Exact full-vs-incremental result

Compare final incremental result with a fresh full rebuild.

---

# 14. Instrumentation requirements

Keep the V7 street-light instrumentation.

Add counters such as:

```text
street_light_rebuild_jobs
street_light_prepare_frames
street_light_prepare_completed
street_light_prepare_aborted
street_light_placement_frames
street_light_extensions
street_light_revision_changes
street_light_snapshot_size
```

Also expose per-stage timing.

The benchmark must make it possible to distinguish:

```text
preparation spike
placement spike
screen-surface spike
```

Do not report only the combined `render:lighting` value.

---

# 15. Benchmark

Use the same benchmark environment as V7.

Do not change the benchmark scenario.

Run:

```bash
PYTHONPATH=src:. .venv/bin/python -c 'import utils.benchmark_full_frame as b; b.run_scenario("Driving V8 final", "oulu", frames=3000, drive=True, spike_threshold_ms=100.0)'
```

Environment:

```text
--preset oulu
--no-menu
--osm-source pbf
assets/roads/oulu.bin
warm WorldCache
real tile streaming
real rendering
```

The benchmark should use the same Oulu setup as V7.

Do not replace the real streaming benchmark with a synthetic microbenchmark.

---

# 16. Compare against V7

Use the V7 measurements as baseline:

```text
average:              32.52 ms
p95:                  48 ms
p99:                  103 ms
worst:                358 ms
>=100 ms:             33
>=200 ms:             8
>=400 ms:             0

max render:lighting:  126.53 ms
max street-light:     118.39 ms
max tile integration: 251.08 ms

merge-window:
average:              46.38 ms
p95:                  56 ms
worst:                292 ms
>=100 ms:             3
>=200 ms:             1
```

Do not expect average FPS to necessarily improve dramatically.

The primary acceptance criterion is:

> Remove the remaining large synchronous street-light preparation spikes.

Report separately:

```text
street-light preparation average
street-light preparation p95
street-light preparation worst
street-light placement average
street-light placement worst
number of preparation frames
number of rebuild jobs
number of extensions
```

---

# 17. Measure before and after

Before changing the architecture, capture a baseline for the current V7 code.

At minimum record:

```text
street-light preparation max
street-light preparation p95
street-light placement max
render:lighting max
merge-window >=100 ms
merge-window >=200 ms
```

After implementation, run the same measurement.

If the benchmark is noisy, repeat it at least twice and report both runs.

Do not hide an unfavorable run.

---

# 18. Do not optimize unrelated bottlenecks

The V7 report identified:

```text
map_sync:pedestrians       ~335 ms
taxi work                  ~145 ms
map_sync:traffic           ~144 ms
tile integration           ~251 ms outlier
```

Do not change these in V8.

If they appear in the benchmark, report them separately.

Do not let the implementation scope expand into those systems.

The goal of V8 is specifically:

> Make street-light contributor preparation incremental and budgeted.

---

# 19. Avoid premature abstraction

Do not create a generic "budgeted task framework" for the whole game unless the existing code clearly requires it.

Keep the implementation local to the street-light cache architecture.

Prefer a small explicit state machine over a highly abstract coroutine/task framework if that is simpler and easier to verify.

Maintain readability.

---

# 20. Performance requirements

The new implementation should satisfy:

1. No full contributor preparation merely because raw lists grow.
2. No unbounded building/junction/segment scan in one frame.
3. No repeated preparation every frame while the grid revision is unchanged.
4. Preparation work is resumable.
5. Placement remains resumable.
6. Previous committed cache remains visible.
7. New revisions do not mix into an active snapshot.
8. Final incremental geometry matches a full rebuild.
9. Daylight remains cheap.
10. Camera movement inside the committed region remains cheap.

Most importantly:

> A new street-light revision must not produce another 100–170 ms synchronous preparation stall.

---

# 21. Test commands

Run focused street-light tests first.

Then run the relevant renderer/spatial-grid/profiler tests.

Then run the full test suite.

Use the repository's existing test commands rather than inventing new ones.

Also run:

```bash
git diff --check
```

Do not declare success if focused tests pass but the full suite has new regressions.

If the known five flaky tests remain, identify them explicitly and compare against the V7 baseline.

---

# 22. Final report

Create:

```text
bin-loader-v8.md
```

The report must contain:

1. Executive summary
2. V7 baseline
3. Actual pre-change contributor preparation architecture
4. Profiling results before the change
5. Exact synchronous bottleneck(s) found
6. New state-machine architecture
7. Snapshot/revision handling
8. Budgeting behavior
9. Camera/region behavior
10. Correctness strategy
11. Tests
12. Benchmark results
13. Comparison against V7
14. Remaining bottlenecks
15. Recommendation for V9

Include exact measured numbers.

Do not claim that a stage was optimized unless measurements demonstrate it.

---

# 23. Final response requirements

At the end, report:

```text
Implementation:
- files changed
- key architectural changes

Correctness:
- focused tests
- full suite
- git diff --check

Performance:
- V7 baseline
- V8 run A
- V8 run B if performed

Street-light:
- preparation max
- placement max
- total max
- rebuild jobs
- preparation frames
- extensions

Remaining:
- largest street-light bottleneck
- largest unrelated bottleneck

Report:
- bin-loader-v8.md
```

Do not modify pedestrian simulation, taxi-offer generation, traffic synchronization, or tile integration in this task.

The V8 task is complete only when contributor preparation is genuinely incremental, measurable, resumable, and behaviorally equivalent to the previous full rebuild.
