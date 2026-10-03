# Road Rage Taxi — V13: Investigate and optimize `map_sync:traffic`

## Context

Repository:

`https://github.com/emehtata/roadragetaxi`

Working branch:

`release/0.15.0alpha`

The project is a Pygame-based OSM city simulation with streamed map tiles, pedestrians, road traffic, NPC vehicles, routing, traffic lights, buildings, scenery, lighting and incremental map synchronization.

V12 introduced asynchronous, time-budgeted NPC route planning. Do **not** undo or redesign that architecture as part of V13.

The V13 objective is specifically to investigate and, if justified by measurements, reduce the cost of:

```text
map_sync:traffic
```

This must be done without sacrificing frame-time stability or correctness.

---

# Important architectural requirement

The current game is a taxi game, but the world/rendering/simulation architecture must remain reusable for future vehicle types.

Future vehicles may include:

* taxi
* bus
* truck
* tram
* train
* metro
* snowplough
* ski-track machine
* other special vehicles

Therefore:

> Do not introduce optimizations or abstractions that make the world/traffic graph infrastructure depend on the taxi or on one particular NPC vehicle implementation.

The traffic/network synchronization architecture should be considered reusable infrastructure.

If the current implementation already has generic graph/revision/index concepts, extend those rather than introducing parallel taxi-specific systems.

---

# V12 findings

V12 changed NPC route planning from synchronous work inside the population tick into resumable route jobs.

Important V12 results:

* `TrafficWorld.plan_route` on the real Oulu road graph:

  * p50: 3.0 ms → 0.8 ms
  * p95: 855.9 ms → 18.7 ms
  * p99: 960.8 ms → 32.8 ms
  * worst: 1063.3 ms → 56.6 ms
* NPC route planning is now processed through a persistent job queue.
* Route jobs receive a 2 ms/frame budget with 0.5 ms per-job slices.
* Route graph revisions invalidate stale jobs safely.
* No ≥200 ms frame in the V12 stress runs was attributed to NPC route planning.

However, V12 still measured:

```text
map_sync:traffic: 166–218 ms
```

The report identifies this as the synchronous traffic graph rebuild, which also builds weakly connected components.

V12 explicitly lists this as a confirmed remaining bottleneck.

The V12 report also notes:

* atomic planner steps can still take approximately 7.5–9 ms
* moving NPC simulation costs remain
* route throughput may be limited by validation rejections
* stale drops cluster around startup when initial tile merges rebuild the graph

Do not assume that weak-component construction is the sole cause of the 166–218 ms cost. Measure it.

---

# V13 mission

Investigate the complete `map_sync:traffic` pipeline and determine exactly why it can consume 166–218 ms.

Then reduce the synchronous cost without merely moving the same work somewhere else in a way that causes equivalent frame spikes.

The desired end state is:

```text
tile/map change
      |
      v
traffic graph sync request
      |
      v
incremental / budgeted preparation
      |
      v
atomic graph commit
      |
      v
new graph revision
      |
      v
route jobs using the new immutable/committed graph
```

The exact implementation may differ if the existing architecture suggests a better solution. Do not force this design without inspecting the code first.

---

# Phase 1 — Inspect before changing anything

Thoroughly inspect the current implementation.

At minimum inspect:

```text
src/theroadragetrip/traffic_world.py
src/theroadragetrip/npc.py
src/theroadragetrip/
tests/
utils/benchmark_full_frame.py
```

Trace the complete lifecycle of the traffic graph:

1. What triggers `map_sync:traffic`?
2. What data is captured/snapshotted?
3. Which world lists are read?
4. Which indexes/grids are built?
5. Which graph structures are allocated?
6. Where are weakly connected components calculated?
7. Where is `route_graph_revision` incremented?
8. What remains live from the previous graph during rebuilding?
9. When is the new graph made visible?
10. Which NPC route jobs depend on that graph?
11. What happens when another tile merge changes the graph while a sync is running?
12. What happens when tiles are unloaded?
13. Are multiple traffic sync requests coalesced?
14. Which work is actually synchronous today?

Do not make architectural changes until this is understood.

---

# Phase 2 — Establish a clean V13 baseline

Use the same real Oulu benchmark methodology used by previous versions.

Run at least:

```bash
TZ=UTC-15 PYTHONPATH=src:. .venv/bin/python -c 'import utils.benchmark_full_frame as b; b.run_scenario("Driving V13 baseline", "oulu", frames=3000, drive=True, spike_threshold_ms=100.0)'
```

Use the existing benchmark/instrumentation rather than inventing a second benchmark system.

Run at least two baseline runs.

Record:

* average frame time
* p95
* p99
* worst frame
* frames >=100 ms
* frames >=200 ms
* frames >=400 ms
* `map_sync:traffic` average/p95/max
* traffic graph rebuild sub-stages
* GC time associated with each stage
* number of traffic graph rebuilds
* frames spent rebuilding
* graph revision changes
* route jobs queued/completed/stale/discarded
* NPC moving/parked counts
* route wait times

Separate GC time from actual traffic graph computation.

Do not mistake a 200 ms GC pause triggered during traffic synchronization for 200 ms of traffic graph work.

---

# Phase 3 — Instrument the traffic sync pipeline

Add temporary or permanent instrumentation as appropriate.

Break `map_sync:traffic` into meaningful stages.

At minimum investigate:

```text
snapshot / input preparation
road filtering
node construction
edge construction
nearest-node/grid construction
junction-related structures
weak-component construction
other indexes
allocations
commit
old graph release
```

Use the actual implementation's stages rather than blindly creating these exact labels.

For each stage measure:

* wall time
* CPU time if useful
* item count
* allocation-heavy operations if measurable
* GC time
* number of frames consumed
* whether the stage can safely be resumed

Also measure graph sizes:

```text
nodes
edges
ways
junctions
components
grid cells
```

for the real Oulu world.

---

# Phase 4 — Identify the actual synchronous bottleneck

Do not assume the answer.

Determine whether the 166–218 ms comes primarily from:

* graph construction
* weak-component calculation
* spatial index construction
* road filtering
* junction processing
* copying/snapshotting
* object allocation
* old graph destruction
* GC
* commit
* some combination

Produce a quantified breakdown.

For example, the report should be able to answer something like:

```text
map_sync:traffic = 184 ms

graph input preparation       12 ms
node/edge construction        71 ms
spatial index                 24 ms
weak components               53 ms
commit                        18 ms
GC                             6 ms
```

The numbers above are only an example. Do not use them unless measurement produces them.

---

# Phase 5 — Determine whether the existing pedestrian pattern can be reused

The pedestrian synchronization system already uses incremental/budgeted rebuilding and atomic generation commits.

Inspect that architecture carefully.

Determine whether traffic graph rebuilding can use the same general pattern.

Possible desired architecture:

```text
TrafficGraphBuild
    |
    +-- snapshot current world input
    |
    +-- incremental graph construction
    |
    +-- incremental spatial indexes
    |
    +-- incremental component calculation
    |
    +-- final validation
    |
    +-- atomic commit
```

But do not blindly duplicate pedestrian code.

Prefer extracting genuinely generic infrastructure if that reduces duplication and makes the architecture clearer.

Avoid a large generic framework abstraction if it merely makes the code harder to understand.

---

# Phase 6 — Weak components

V12 introduced:

```text
TrafficWorld._route_component
```

and builds weakly connected components with the traffic graph.

Investigate this carefully.

Determine:

1. How expensive is it?
2. Is it currently recomputed from scratch?
3. Can it be constructed incrementally while nodes/edges are being added?
4. Can union-find be reused safely?
5. Does the directed nature of the road graph matter?
6. Is weak connectivity sufficient for the existing early-rejection optimization?
7. Does component data have to be rebuilt after tile unload?
8. Can it be committed atomically with the graph?
9. Can route jobs safely use the previous component data until the new graph commits?

If union-find is appropriate, implement it in the graph build rather than adding a separate full-graph pass.

However:

> Do not optimize weak components merely because the name appears in the V12 report. Prove that it is a significant portion of the measured cost first.

---

# Phase 7 — Tile streaming and graph revisions

This is critical.

The game has streamed map tiles and the traffic graph can change as tiles are loaded/unloaded.

The implementation must preserve:

```text
old graph
    |
    | new graph is being built
    |
    v
old graph remains authoritative
    |
    | build completes
    v
atomic commit
    |
    v
new route_graph_revision
```

While a new graph is being prepared:

* existing NPC route jobs must not observe partially built state
* existing route queries must not observe partially built state
* the old graph must remain valid until commit
* stale route jobs must remain safely detectable
* intermediate graph revisions should be coalesced if possible

Do not introduce a synchronization scheme that repeatedly rebuilds the same graph because several tile events arrive during a build.

Test:

1. tile addition during build
2. tile removal during build
3. multiple tile changes during build
4. graph revision changes during route jobs
5. rapid consecutive map updates

---

# Phase 8 — Memory and GC

V9/V10 showed that Python GC can produce very large pauses.

Therefore explicitly measure:

```text
traffic sync CPU time
traffic sync GC time
traffic sync allocation pressure
old graph lifetime
new graph lifetime
```

If a large synchronous pause is caused by old graph destruction or garbage collection, identify that separately.

Do not "solve" the problem by globally disabling GC.

Do not use `gc.freeze()` or threshold changes unless measurements demonstrate that they are safe and beneficial in the current architecture.

---

# Phase 9 — Preserve V12 route-job behavior

This is mandatory.

Do not turn asynchronous route jobs back into synchronous route planning.

After traffic graph synchronization changes, verify:

* route jobs still use graph revisions correctly
* stale jobs are discarded safely
* removed vehicles are not resurrected
* parked vehicle validation still works
* transit spawn validation still works
* retry backoff remains intact
* route output remains unchanged
* route jobs eventually make progress

The V12 scheduler must remain a stable subsystem.

---

# Phase 10 — Do NOT optimize route-job throughput yet

Do not make these V13 goals:

```text
increase NPC_ROUTE_JOB_BUDGET_S
make build_driving_path stepwise
make candidate selection stepwise
increase NPC population
reduce route wait time
```

unless the traffic-sync investigation proves that one of them is directly necessary for correctness.

Those are potential future tasks.

V13 should primarily answer:

> Why does `map_sync:traffic` take 166–218 ms, and can that work be made incremental/budgeted without harming the existing V12 route-job architecture?

---

# Phase 11 — Correctness tests

Add focused tests for the actual implementation.

At minimum test:

### A. Exact graph equivalence

Compare:

```text
old synchronous/full traffic graph
```

against:

```text
new incremental traffic graph
```

on representative synthetic worlds.

Verify exact equivalence of all externally relevant structures.

### B. Component equivalence

Compare component assignments against a brute-force reference implementation.

### C. Zero-budget progress

With zero or extremely small budget, verify that:

* work progresses over multiple frames
* no infinite loop occurs
* old graph remains active until commit

### D. Revision safety

Verify:

```text
graph N
    ↓
job created
    ↓
graph N+1 commits
    ↓
job is stale
    ↓
job result is never applied
```

### E. Tile unload

Load tiles, build graph, unload some tiles, rebuild.

Verify:

* no stale nodes
* no stale edges
* no stale components
* no stale spatial index entries

### F. Multiple revisions during build

Trigger multiple world changes while rebuilding.

Verify that intermediate generations are coalesced safely.

### G. Route compatibility

For a fixed graph, compare route output before and after V13.

The same route must be produced.

Do not accept "equivalent enough" unless the existing tests explicitly define such behavior.

---

# Phase 12 — Real Oulu benchmark

After implementation, rerun the exact baseline benchmark.

At least two runs.

Compare:

```text
V12 baseline
V13
```

Measure:

* frame average
* p95
* p99
* worst
* > =100 ms
* > =200 ms
* > =400 ms
* traffic sync average
* traffic sync p95
* traffic sync max
* GC contribution
* rebuild jobs
* rebuild frames
* graph commits
* graph revisions
* route-job statistics
* NPC counts
* route wait times

The most important acceptance criterion is not merely average FPS.

We want to reduce or eliminate large synchronous `map_sync:traffic` spikes.

---

# Phase 13 — Avoid benchmark illusions

Be careful with random NPC population and random tile timing.

If the benchmark contains large variation:

* run multiple repetitions
* compare distributions
* distinguish NPC variance from traffic-sync variance
* report outliers honestly
* do not claim improvement based on a single lucky run

If possible, create a deterministic traffic-sync microbenchmark using a captured real Oulu graph/world snapshot.

That benchmark should measure the traffic graph rebuild itself independently of NPC randomness.

---

# Phase 14 — Future vehicle architecture check

Before finalizing, review every new abstraction introduced by V13.

Ask:

### Could this work for a bus?

### Could this work for a tram?

### Could this work for a train?

### Could this work for a metro?

### Could this work for a snowplough or ski-track machine?

The answer does not need to be "yes, immediately".

But the infrastructure must not contain assumptions such as:

```python
if vehicle.is_taxi:
```

or:

```python
npc_car_route_graph
```

when the concept is actually a generic movement/traffic graph.

Prefer names such as:

```text
TrafficGraph
RouteGraph
MovementGraph
GraphBuild
GraphRevision
RouteJob
```

where those names accurately describe the abstraction.

Do not rename existing code merely for aesthetics.

---

# Phase 15 — Full test suite

Run:

```bash
pytest -q
```

Also run the focused traffic/NPC tests separately.

Report:

* total passed
* known pre-existing failures
* new failures
* flaky failures
* focused test results

Run:

```bash
git diff --check
```

and report the result.

Do not silently classify a new failure as pre-existing. Verify it.

---

# Phase 16 — Produce a V13 report

Create:

```text
bin-loader-v13.md
```

The report must contain:

## Executive summary

What was actually found and changed.

## Root cause

Measured breakdown of `map_sync:traffic`.

## Existing architecture

Short description of how traffic graph synchronization worked before V13.

## Implementation

Exact files and major changes.

## Incremental architecture

Explain:

* snapshots
* build stages
* budgets
* graph generations
* atomic commit
* revision handling
* tile add/remove behavior

## Weak components

Explain whether they were a significant bottleneck and how they are handled.

## GC / memory

Report any GC or memory effects separately.

## Correctness

Report exact graph equivalence and route-equivalence results.

## Benchmark

Include before/after tables using real Oulu data.

## Regression

Report full test suite and `git diff --check`.

## Remaining bottlenecks

Explicitly identify what remains.

## Rejected approaches

Explain approaches investigated but not implemented and why.

## Future work

Only list evidence-based next steps.

---

# Final response requirements

When finished, report:

1. Root cause of `map_sync:traffic`
2. What was changed
3. Whether the work is now incremental/budgeted
4. Before/after traffic-sync timings
5. Before/after frame-time statistics
6. Whether GC was involved
7. Whether V12 route jobs remain correct
8. Correctness-test results
9. Full-suite results
10. Remaining bottlenecks
11. Any architectural concerns for future vehicle types
12. Path to the generated `bin-loader-v13.md`

---

# Hard constraints

* Inspect first. Measure before changing architecture.
* Do not optimize based on assumptions.
* Do not revert V12's asynchronous route-job architecture.
* Do not make NPC route planning synchronous again.
* Do not disable Python GC globally.
* Do not hide work inside another frame and call it an optimization.
* Do not introduce threads merely to hide synchronous work.
* Do not sacrifice exact route behavior without explicit evidence and tests.
* Do not introduce taxi-specific infrastructure where generic graph infrastructure is appropriate.
* Preserve atomic graph generations.
* Preserve safe tile streaming and unloading.
* Preserve existing gameplay behavior.
* Keep changes narrowly scoped to `map_sync:traffic` and the infrastructure directly required to fix it.
* Do not optimize taxi performance in V13.
* Do not optimize pedestrian routing in V13.
* Do not increase NPC population targets in V13.
* Do not optimize unrelated rendering systems in V13.

The primary success criterion is:

> **Turn the measured synchronous `map_sync:traffic` bottleneck into controlled, incremental work without reintroducing frame spikes, while preserving exact graph and routing behavior and keeping the resulting infrastructure reusable for future road and rail vehicle types.**
