# bin-loader-v9: diagnose and budget pedestrian map synchronization

## Objective

Continue the Road Rage Taxi performance optimization on the current branch.

V8 completed the street-light optimization successfully. Street-light contributor preparation and placement are now resumable and budgeted, and street-light spikes are no longer responsible for the large frame stalls.

The next measured bottleneck is:

```text
map_sync:pedestrians
```

Recent real Oulu benchmarks show pedestrian-related work reaching approximately:

```text
~335 ms
~542 ms
```

The exact internal cause is not yet established.

The goal of V9 is therefore:

> First identify exactly which pedestrian synchronization stages cause the large stalls, then make the expensive stages resumable/budgeted without changing pedestrian behavior.

Do not optimize street lights, tile integration, taxi offers, traffic synchronization, or unrelated rendering in this task.

---

# 1. Start with investigation — do not modify behavior yet

Before changing implementation, inspect the current pedestrian synchronization architecture.

Find the exact code responsible for:

```text
map_sync:pedestrians
```

Trace the complete call path from the main game loop to the final pedestrian synchronization.

Identify all work performed inside this section.

At minimum investigate:

* pedestrian discovery
* pedestrian spawn
* pedestrian despawn
* pedestrian object creation
* resident/person association
* building lookup
* building entrance/exit lookup
* road/sidewalk lookup
* pedestrian route generation
* route/pathfinding
* spatial-grid queries
* pedestrian destination selection
* state initialization
* animation initialization
* collision/spatial registration
* pedestrian list rebuilding
* pedestrian sorting/filtering
* cleanup of removed pedestrians
* any rendering-related preparation performed here

Do not assume that `map_sync:pedestrians` means only spawning pedestrians.

Measure it.

---

# 2. Establish a V9 baseline

Before changing the implementation, run the existing benchmark with the same environment used for V8.

Use:

```bash
TZ=UTC-15 PYTHONPATH=src:. .venv/bin/python -c 'import utils.benchmark_full_frame as b; b.run_scenario("Driving V9 baseline", "oulu", frames=3000, drive=True, spike_threshold_ms=100.0)'
```

The important part is:

```text
TZ=UTC-15
```

The benchmark must start at night so that street-light rendering remains active and the comparison remains consistent with V8.

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

Record at least:

```text
average frame
p95
p99
worst frame
frames >=100 ms
frames >=200 ms
frames >=400 ms

max map_sync:pedestrians
average map_sync:pedestrians
p95 map_sync:pedestrians
```

Also record the other major contributors so the results can be compared against V8.

---

# 3. Instrument pedestrian synchronization by stage

Do not immediately make the whole pedestrian system incremental.

First split:

```text
map_sync:pedestrians
```

into meaningful nested timers.

Use the actual implementation terminology, but the instrumentation should make it possible to distinguish at least:

```text
map_sync:pedestrians
    ├── discovery
    ├── spawn
    ├── despawn
    ├── resident/person association
    ├── building lookup
    ├── route generation
    ├── spatial registration
    ├── state initialization
    └── cleanup
```

If some of these do not exist, do not invent them.

If there are additional expensive stages, instrument those too.

The most important requirement is:

> A 300–500 ms `map_sync:pedestrians` spike must be attributable to one or more concrete operations.

Do not infer the cause from surrounding frame timings.

---

# 4. Per-operation counters

Add instrumentation counters where useful.

At minimum measure:

```text
pedestrians discovered
pedestrians spawned
pedestrians despawned
routes generated
route generation failures
spatial registrations
buildings queried
roads queried
residents processed
```

Also measure the size of relevant collections:

```text
active pedestrians
candidate pedestrians
resident population
visible buildings
candidate buildings
route requests
```

Do not add expensive diagnostic work that itself materially changes benchmark behavior.

Instrumentation should be lightweight.

---

# 5. Determine whether the spike is caused by bulk synchronization

Investigate whether the system currently performs something like:

```python
for every pedestrian:
    ...
```

or:

```python
for every building:
    ...
```

or:

```python
for every resident:
    ...
```

on every synchronization event.

Determine what triggers synchronization.

For example:

```text
tile merge
building-grid update
road-grid update
camera movement
pedestrian timer
spawn timer
despawn timer
resident update
```

Find out whether one tile integration causes the pedestrian system to reconsider the entire world.

This is particularly important because the V5–V8 architecture now performs incremental tile integration.

Look for a pattern like:

```text
one small map change
        ↓
full pedestrian synchronization
        ↓
hundreds/thousands of objects processed
```

If such a pattern exists, measure it explicitly.

---

# 6. Establish the authoritative pedestrian inputs

Determine exactly which data changes should invalidate pedestrian synchronization.

Possible inputs include:

```text
road grid revision
building grid revision
sidewalk/footway revision
resident data revision
tile revision
camera region
```

Do not assume all of them are necessary.

The goal is to determine the smallest correct invalidation boundary.

For example, if a raw building list grows but the completed building grid has not changed, determine whether pedestrian synchronization actually needs to run.

Avoid using:

```python
len(buildings)
len(ways)
```

as invalidation signals if authoritative grid revisions already exist.

Use completed revisions where the architecture provides them.

---

# 7. Identify the actual expensive algorithm

For each stage exceeding approximately 5–10 ms, inspect the algorithm rather than immediately adding a time budget.

Determine whether the cost comes from:

* brute-force scans
* repeated spatial queries
* pathfinding
* route reconstruction
* repeated object allocation
* list copying
* sorting
* duplicate filtering
* building-to-pedestrian association
* resident iteration
* unnecessary destruction/recreation
* repeated initialization
* cache invalidation
* Python-level nested loops

Do not optimize based only on function names.

Find the actual hot loop.

---

# 8. Pay special attention to route generation

Pedestrian route generation is a likely candidate for expensive work, but this must be measured rather than assumed.

Determine:

1. How many routes are generated during a spike.
2. Average route-generation time.
3. Maximum route-generation time.
4. Whether the same origin/destination is routed repeatedly.
5. Whether routes are generated synchronously during map synchronization.
6. Whether route generation can safely be deferred.
7. Whether a pedestrian can temporarily retain its previous route while a new route is prepared.

If route generation is the dominant cost, design a resumable route-generation queue rather than simply reducing the number of pedestrians.

Do not change route behavior yet unless required for correctness.

---

# 9. Preserve pedestrian behavior

The optimization must not change gameplay behavior.

Preserve:

* pedestrian spawn rules
* pedestrian despawn rules
* resident association
* pedestrian destinations
* walking speed
* route selection
* pedestrian states
* door/building behavior
* collision behavior
* animation state
* traffic interaction
* map boundaries
* pedestrian visibility rules

Do not reduce pedestrian population merely to improve FPS.

Do not introduce arbitrary caps.

Do not silently skip pedestrians.

---

# 10. Prefer incremental synchronization

If the investigation shows that synchronization processes a large number of independent pedestrians, refactor it into a resumable job.

Conceptually:

```text
PedestrianSyncJob
    revision
    snapshot
    phase
    cursor
    pending_spawns
    pending_despawns
    pending_routes
    pending_registrations
```

Possible phases:

```text
SNAPSHOT
DISCOVER
DESPAWN
SPAWN
ROUTE
REGISTER
COMMIT
```

Do not blindly implement all phases.

Use only the phases required by the actual implementation.

The important property is:

> No single synchronization event should process an unbounded number of pedestrians synchronously.

---

# 11. Dedicated pedestrian budget

If incrementalization is justified by profiling, introduce a dedicated budget.

For example:

```python
PEDESTRIAN_SYNC_BUDGET_S = 0.004
```

Do not reuse:

```text
STREET_LIGHT_CACHE_BUDGET_S
STREET_LIGHT_PREP_BUDGET_S
TILE_MERGE_BUDGET_S
```

The pedestrian budget must be independently measurable.

As with V8, individual atomic operations may exceed the nominal budget.

Do not split an operation in the middle if doing so would violate pedestrian-state consistency.

---

# 12. Preserve the old pedestrian state while updating

If synchronization becomes incremental, avoid destroying the current pedestrian population at the beginning of a job.

Bad:

```text
start sync
    ↓
delete all pedestrians
    ↓
rebuild
```

This can cause:

* visible disappearing pedestrians
* spawn/despawn bursts
* route resets
* animation resets
* collision changes
* flicker

Prefer:

```text
current pedestrian state
        │
        ▼
incremental update
        │
        ▼
new state becomes authoritative
```

If individual pedestrians can safely be updated independently, commit those changes individually.

If atomic commit is required for correctness, keep the old state active until the new state is ready.

Determine which model is appropriate from the existing architecture.

---

# 13. Handle map revisions during an active job

Test explicitly:

```text
revision N
    ↓
start pedestrian synchronization
    ↓
process some work
    ↓
revision N+1 arrives
    ↓
continue safely with N snapshot
    ↓
finish or discard N
    ↓
process N+1
```

Do not mix:

```text
old pedestrian snapshot
+
new building grid
+
new road grid
```

unless the architecture explicitly guarantees this is safe.

Avoid unbounded revision queues.

If several revisions arrive while a job is active, coalesce obsolete intermediate revisions where correctness permits.

---

# 14. Avoid unnecessary full-world work

The Oulu benchmark contains a large number of roads and buildings.

Do not create a solution that does:

```python
for every pedestrian:
    for every building:
        ...
```

or:

```python
for every pedestrian:
    scan every road
```

Use existing spatial indexes wherever appropriate.

If the existing pedestrian code already has a spatial structure, reuse it rather than introducing another competing index.

Measure the spatial-query cost before optimizing it.

---

# 15. Consider lazy/deferred work

If a pedestrian does not need some information immediately, determine whether it can be prepared later.

Examples:

```text
route
destination
animation details
building interaction
collision registration
```

However, do not defer something if it can cause a visible behavioral regression.

The priority is:

```text
correctness
→ stable behavior
→ frame-time consistency
→ throughput
```

not maximum theoretical throughput.

---

# 16. No changes to unrelated systems

V9 must NOT modify:

* street-light cache
* illuminated-window cache
* tile merge algorithm
* tile integration
* taxi offer generation
* traffic synchronization
* road rendering
* OSM loading
* BIN loading

If one of these systems appears in the profiler, record it but leave it unchanged.

The V8 street-light implementation should remain untouched unless a compile/test failure proves otherwise.

---

# 17. Benchmark after the diagnostic phase

After instrumentation alone, run the benchmark again.

Compare:

```text
baseline
instrumented
```

If instrumentation materially changes performance, identify why.

Do not use an instrumentation-heavy configuration as the final performance measurement.

Once the bottleneck is identified, keep only lightweight instrumentation needed for regression measurements.

---

# 18. Only then implement the optimization

The implementation must be driven by the measured bottleneck.

Examples:

### If discovery is expensive

Make discovery incremental.

### If route generation is expensive

Create a bounded route-generation queue.

### If building lookup is expensive

Use existing building-grid queries and cache stable associations.

### If resident iteration is expensive

Use incremental resident processing or dirty subsets.

### If spawn/despawn is expensive

Process spawn/despawn queues incrementally.

### If repeated full synchronization is the problem

Change invalidation semantics so only the affected subset is synchronized.

Do not implement all of these.

Implement only what profiling proves is necessary.

---

# 19. Correctness tests

Add focused tests for the actual optimization.

At minimum cover:

### A. Incremental synchronization

A large pedestrian population requires multiple frames.

Verify all pedestrians eventually reach the same state as the full implementation.

### B. No unnecessary synchronization

Change raw lists without changing authoritative completed revisions.

Verify no full pedestrian synchronization starts.

### C. Revision during synchronization

Start revision N, then commit N+1 during processing.

Verify no mixed state.

### D. Spawn

Verify all expected pedestrians eventually spawn.

### E. Despawn

Verify all pedestrians that should disappear are eventually removed.

### F. Routes

Verify generated routes are equivalent to the previous implementation.

### G. Resident association

Verify resident/person relationships remain unchanged.

### H. Repeated synchronization

Running synchronization twice with unchanged inputs must not duplicate pedestrians or routes.

### I. Empty world

Verify zero-building/zero-road cases remain safe.

### J. Existing pedestrian behavior

Run the relevant existing pedestrian tests unchanged.

Do not weaken existing assertions merely to make the new implementation pass.

---

# 20. Full-vs-incremental comparison

Where practical, create a deterministic comparison between:

```text
old/full pedestrian synchronization
```

and:

```text
new/incremental pedestrian synchronization
```

Use identical world snapshots.

Compare:

* pedestrian count
* pedestrian IDs
* positions
* destinations
* routes
* states
* resident associations
* spawn/despawn state
* relevant spatial registrations

Do not accept "looks correct" as the only validation.

---

# 21. Performance instrumentation

The final implementation should expose at least:

```text
pedestrian_sync_jobs
pedestrian_sync_frames
pedestrian_sync_revisions
pedestrian_sync_spawns
pedestrian_sync_despawns
pedestrian_sync_routes
pedestrian_sync_extensions
```

And timing sections such as:

```text
map_sync:pedestrians
map_sync:pedestrians:discovery
map_sync:pedestrians:spawn
map_sync:pedestrians:despawn
map_sync:pedestrians:routes
map_sync:pedestrians:registration
```

Use the actual stage names from the implementation.

The instrumentation must allow a future benchmark to answer:

> Why did this pedestrian synchronization take 300 ms?

---

# 22. V9 acceptance criteria

The task is successful only if:

1. The actual cause of the large pedestrian spikes is identified with measurements.
2. The expensive stage is made incremental if incrementalization is appropriate.
3. No single pedestrian synchronization frame performs an unbounded amount of work.
4. Existing pedestrian behavior remains unchanged.
5. No arbitrary pedestrian-count reduction is introduced.
6. No unrelated subsystem is modified.
7. Large pedestrian spikes are substantially reduced.
8. The implementation has focused correctness tests.
9. Full-suite results are compared against the V8 baseline.
10. `git diff --check` passes.

Do not optimize merely for average FPS.

The primary goal is to reduce frame-time spikes and make pedestrian synchronization predictable.

---

# 23. V8 baseline

Use the V8 benchmark as the comparison point.

V8 runs:

```text
Run A:
average       30.7 ms
p95           49 ms
worst         1794 ms
street-light  16.3 ms
lighting      33 ms

Run B:
average       30.4 ms
p95           44 ms
worst         579 ms
street-light  28.0 ms
lighting      40 ms
```

The V8 report identified these remaining unrelated peaks:

```text
pedestrians    up to ~542 ms
tile merging   up to ~303 ms
traffic        up to ~176 ms
taxi           up to ~139 ms
```

The pedestrian optimization should primarily be compared against the pedestrian-specific measurements, not only overall FPS.

---

# 24. Benchmark conditions

Use:

```bash
TZ=UTC-15 PYTHONPATH=src:. .venv/bin/python -c 'import utils.benchmark_full_frame as b; b.run_scenario("Driving V9 final", "oulu", frames=3000, drive=True, spike_threshold_ms=100.0)'
```

Keep:

```text
--preset oulu
--no-menu
--osm-source pbf
warm WorldCache
real tile streaming
real rendering
night-time start
```

Run at least two final benchmark runs.

Report both if they differ materially.

Do not hide noisy runs.

---

# 25. Do not misattribute spikes

For every frame above 100 ms, use nested timing sections to determine whether the cause is:

```text
pedestrian synchronization
tile integration
traffic
taxi
rendering
physics
something else
```

Do not call a frame a "pedestrian spike" merely because pedestrians were active on that frame.

The attribution must come from the nested timers.

---

# 26. Final report

Create:

```text
bin-loader-v9.md
```

The report must contain:

1. Executive summary
2. V8 baseline
3. Pedestrian architecture before V9
4. Baseline profiling
5. Exact bottleneck identification
6. Trigger/invalidation analysis
7. New incremental architecture
8. Budgeting model
9. Revision handling
10. Correctness strategy
11. Tests
12. Full-vs-incremental comparison
13. Benchmark results
14. Remaining bottlenecks
15. Recommendation for V10

Include exact measurements.

Do not claim an optimization succeeded without measured evidence.

---

# 27. Final response

At completion, report:

```text
Implementation:
- files changed
- key architectural changes

Root cause:
- exact pedestrian bottleneck
- evidence

Correctness:
- focused tests
- full suite
- full-vs-incremental comparison
- git diff --check

Performance:
- V8 baseline
- V9 run A
- V9 run B

Pedestrian:
- max sync time
- preparation/sync average
- p95
- number of sync jobs
- number of sync frames
- spawns
- despawns
- routes

Remaining:
- largest pedestrian bottleneck
- largest unrelated bottleneck

Report:
- bin-loader-v9.md
```

Do not modify unrelated performance systems.

The V9 task is complete only when the pedestrian synchronization bottleneck has been measured precisely and the demonstrated expensive work has been made incremental or otherwise bounded without changing pedestrian behavior.
