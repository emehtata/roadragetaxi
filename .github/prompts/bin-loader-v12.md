# Road Rage Taxi — V12: Asynchronous Traffic Route Planning

## Working branch

Work ONLY on:

`release/0.15.0alpha`

Do not switch branches.

---

# 1. Objective

The current NPC traffic system successfully creates/places NPC vehicles, but almost all vehicles remain parked because starting a trip requires route planning that cannot complete within the current per-frame budget.

The latest Oulu measurements show:

* 24 NPC vehicles observed
* 23 were parked
* 0 of 23 trip-start attempts succeeded
* route planning costs approximately 25 ms median
* worst observed route planning is approximately 120 ms
* the population tick currently has an 8 ms route-planning budget
* increasing that budget to 30 ms caused approximately 100–280 ms frame stutters
* restoring the budget to 8 ms avoids the worst stutters but leaves traffic almost completely stationary

Recent fixes have already addressed:

1. kerbs crossing drivable roads
2. right-turn lane positioning
3. nearest-road-node lookup

Do NOT undo those changes.

The problem V12 must solve is:

> Traffic route planning must no longer require a complete route calculation inside a single gameplay frame.

The desired behavior is:

```text
NPC wants to start trip
        ↓
route request queued
        ↓
planner works incrementally/background
        ↓
route becomes ready
        ↓
NPC starts driving
```

instead of:

```text
NPC wants to start trip
        ↓
calculate entire route immediately
        ↓
block gameplay frame
```

---

# 2. Investigate before implementation

Do NOT immediately add a thread or rewrite the route planner.

First inspect the existing traffic architecture.

Identify:

* NPC population manager
* population tick
* trip-start logic
* vehicle spawn logic
* current traffic route planner
* road graph representation
* road node representation
* road edge representation
* route result representation
* route validation
* route caching
* NPC state machine
* map synchronization
* tile loading/unloading
* world/map generation
* existing threading/worker infrastructure
* existing frame-budget systems
* all callers of the route planner

Document the current flow.

Especially determine:

```text
Who requests a route?
Who owns the request?
Who owns the result?
When is the result considered valid?
What happens if the map changes while planning?
What happens if the NPC disappears before planning finishes?
```

Do not infer these answers.

Read the actual implementation.

---

# 3. Performance baseline

Before changing the planner, establish a baseline.

Use the existing profiling/benchmarking infrastructure where possible.

Measure:

* route requests per population tick
* successful routes
* failed routes
* route planning duration
* route planning p50
* p95
* p99
* worst
* nodes expanded
* edges examined if available
* frame time during route planning
* number of NPCs currently moving
* number of NPCs parked
* number of trip attempts
* number of trip starts

Run a representative Oulu session.

Do not use a synthetic benchmark as the only measurement.

---

# 4. Primary architectural goal

The planner must support route requests whose work can extend across multiple frames without blocking the main game loop.

The preferred conceptual model is:

```text
TrafficPopulation
       |
       | route request
       v
TrafficRoutePlanner
       |
       +--> pending requests
       |
       +--> active searches
       |
       +--> completed routes
       |
       v
TrafficPopulation
       |
       +--> start vehicle when route ready
```

The planner should expose a clear lifecycle such as:

```text
REQUESTED
    ↓
PLANNING
    ↓
READY
    ↓
CONSUMED
```

and:

```text
REQUESTED
    ↓
PLANNING
    ↓
FAILED
```

Use names and abstractions consistent with the existing codebase.

Do not blindly implement these exact enum names.

---

# 5. Preferred implementation: incremental search

First investigate whether the existing route search can be converted into an incremental state machine.

For example:

```python
class RouteSearch:
    def step(self, budget):
        ...
        return status
```

where one invocation performs bounded work and returns:

```text
RUNNING
FOUND
FAILED
```

The important property is:

```text
frame N:
    search.step(...)
    search still running

frame N+1:
    search.step(...)
    search still running

frame N+2:
    search.step(...)
    route found
```

The exact budget should be based on actual measurements.

Do NOT measure the budget only in terms of elapsed wall-clock time if that creates excessive timing overhead in the hot loop.

Consider whether a bounded number of graph expansions is a better primary budget, with optional time monitoring.

---

# 6. Main-thread frame budget

The traffic planner must have a strict main-thread budget.

Do NOT allow a single route request to consume:

* 25 ms
* 50 ms
* 100 ms
* or more

inside one gameplay frame.

The normal gameplay frame must remain responsive.

The planner may perform a small amount of work per frame across multiple requests.

For example:

```text
traffic planner budget: 1–3 ms/frame
```

is a possible starting point, but DO NOT assume this value.

Measure and choose a suitable value based on the existing frame budget.

The planner must not monopolize the frame merely because many NPCs are waiting.

---

# 7. Multiple simultaneous route requests

The population system may have many parked NPCs waiting to start trips.

Do not process all requests serially to completion.

Instead maintain a queue:

```text
pending:
    request A
    request B
    request C
    request D
```

and active searches:

```text
active:
    A
    B
```

A frame may advance several searches within the global budget.

Avoid starvation.

For example, do not allow the first impossible route to consume the entire planner budget every frame while newer requests never receive processing time.

Use a fair scheduling strategy appropriate to the existing architecture.

A simple round-robin strategy may be sufficient.

---

# 8. Background worker investigation

Investigate whether the project already has infrastructure suitable for background route planning.

A worker thread/process may be considered if:

* the route graph is safely shareable/read-only
* the search does not access pygame
* the search does not mutate game state
* route results can safely return to the main thread
* map synchronization can be handled safely
* Python's GIL does not make the proposed design pointless

Do NOT add threading simply because "background" sounds faster.

The first preference should be an incremental, deterministic planner if it provides sufficient performance.

If a worker thread is clearly beneficial, document:

* why incremental main-thread planning is insufficient
* what data the worker reads
* what data it writes
* how results are synchronized
* how map changes invalidate searches
* how NPC deletion/despawn is handled
* how shutdown is handled

Never access pygame objects from a worker thread.

---

# 9. Map generation / stale routes

This is critical.

Road Rage Taxi dynamically loads and synchronizes map data.

A route request must be associated with the graph/world version against which it was created.

Conceptually:

```text
route request
    graph_generation = 42
```

If the graph becomes:

```text
graph_generation = 43
```

while planning is still in progress, determine whether the search:

* can safely continue
* must be restarted
* must be discarded

Do NOT allow a route based on obsolete graph data to silently become active.

Use an existing generation/version mechanism if one exists.

Do not create duplicate versioning systems unnecessarily.

---

# 10. NPC lifecycle safety

A route request may outlive the NPC that created it.

Examples:

```text
NPC requests route
NPC despawns
route completes
```

or:

```text
NPC requests route
vehicle is removed
route completes
```

or:

```text
NPC requests route
NPC state changes
route completes
```

The planner must not resurrect deleted NPCs or attach a route to the wrong vehicle.

Prefer a stable request ID:

```text
request_id
npc_id
graph_generation
```

and validate ownership before consuming the result.

Do not retain strong references to obsolete large world structures unnecessarily.

---

# 11. Failed route handling

A failed route must be cheap.

If a route is impossible:

```text
request
    ↓
planning
    ↓
FAILED
```

must not result in the same NPC immediately requesting the same impossible route every tick.

Investigate whether repeated identical requests currently occur.

If they do, add an appropriate retry policy.

Possible mechanisms include:

* retry delay
* alternate destination
* alternate start point
* failed-route cache
* temporary blacklist

Do not add these blindly.

First measure whether repeated failures are actually occurring.

---

# 12. Destination selection

Do NOT hide routing failures by simply selecting destinations that are known to be easy.

The traffic system should eventually be able to produce realistic trips across the road network.

However, inspect destination selection for obvious pathological behavior.

For example:

```text
start node
target node
```

should not repeatedly select an impossible target if a valid reachable target could have been selected.

If the current road graph already supports connected-component information, consider using it to reject impossible destinations before starting a route search.

Do not duplicate the pedestrian V11 implementation if a reusable graph-connectivity abstraction is appropriate.

---

# 13. Route planner and future vehicle architecture

This is an important architectural requirement.

The traffic route planner must not be designed so tightly around one specific NPC car implementation that it prevents future vehicle types.

Road Rage Taxi is intended to eventually support:

* cars
* buses
* trucks
* lorries
* motorcycles
* bicycles
* trams
* metros
* trains
* snowplows
* snow tractors
* other service vehicles

The current implementation is specifically for road traffic.

Keep the abstraction conceptually reusable:

```text
RouteRequest
    actor / vehicle
    routing network
    start
    destination
    constraints
```

without prematurely building an enormous generic transport framework.

The road route planner should be a clean component that future planners can learn from or reuse where appropriate.

---

# 14. Do not mix rendering into the planner

The planner must operate independently of rendering.

It must not:

* create sprites
* access pygame surfaces
* draw
* modify camera state
* perform visual effects

Route planning should produce data.

The main simulation consumes the result and updates the NPC.

---

# 15. Memory and allocation requirements

The V10 GC investigation showed that the game already has approximately 1.1–1.2 GB RSS during a large Oulu session.

Do not introduce a large number of persistent allocations.

Pay particular attention to:

* open sets
* closed sets
* priority queues
* temporary route lists
* per-request graph copies
* duplicated graph structures

Never copy the entire road graph for every route request.

If multiple searches run simultaneously, determine whether their search state can share immutable graph data safely.

---

# 16. Interaction with pedestrian routing

V11 may independently optimize pedestrian routing.

Do not couple the traffic planner to pedestrian routing unnecessarily.

However, look for reusable infrastructure such as:

* graph generation IDs
* graph node IDs
* connectivity metadata
* priority queue implementations
* route result types
* profiling hooks

If a reusable abstraction is clearly beneficial, extract it carefully.

Do not perform a broad refactor merely for theoretical reuse.

---

# 17. NPC behavior after route completion

When a route becomes ready:

```text
route READY
    ↓
validate NPC still exists
    ↓
validate graph generation
    ↓
attach route
    ↓
change NPC state:
PARKED → STARTING / CRUISING
```

The transition must be deterministic.

Measure how long a newly spawned parked NPC typically waits before it starts moving.

The goal is not necessarily zero-frame latency.

A small delay is acceptable.

The important requirement is that the NPC should eventually start moving without blocking the game.

---

# 18. Traffic population target

The recent population-based NPC count change is already implemented.

Current behavior when `traffic_count` is empty:

```text
target = sqrt(population) / 6
```

clamped to:

```text
15–100
```

with explicit configuration overriding the formula.

Do not change this formula in V12 unless measurements prove it directly interacts with the planner design.

The purpose of V12 is to make the existing NPC population actually move.

---

# 19. Existing kerb and right-turn fixes

Preserve the recent fixes:

### Kerb gaps

Kerbs crossing drivable roads are cut to create a road-width gap.

Kerbs running along road edges remain intact.

### Right turns

NPCs remain approximately 0.8 m clear of the road edge during right turns.

Do not regress either behavior.

Run the existing tests for both.

---

# 20. Stress testing

After implementation, test with increasingly high NPC populations.

At minimum test:

```text
15 NPC
30 NPC
50 NPC
75 NPC
100 NPC
```

where practical.

For each scenario measure:

* parked NPC count
* moving NPC count
* route requests
* completed routes
* failed routes
* average route wait time
* p95 route wait
* maximum route wait
* planner CPU time/frame
* worst frame
* frames >=100 ms
* frames >=200 ms
* frames >=400 ms

The goal is not simply to increase NPC count.

The goal is:

```text
more NPCs
+
more route requests
=
controlled planner cost
+
no catastrophic frame spikes
```

---

# 21. Before/after benchmark

Produce a table like:

| Metric                 | Before | After |
| ---------------------- | -----: | ----: |
| parked NPCs            |        |       |
| moving NPCs            |        |       |
| successful trip starts |        |       |
| failed trip starts     |        |       |
| route p50              |        |       |
| route p95              |        |       |
| route p99              |        |       |
| route worst            |        |       |
| max planner time/frame |        |       |
| avg frame time         |        |       |
| p95 frame time         |        |       |
| p99 frame time         |        |       |
| worst frame            |        |       |
| frames >=100 ms        |        |       |
| frames >=200 ms        |        |       |
| frames >=400 ms        |        |       |

If multiple NPC-count scenarios are tested, provide a second table.

Do not compare unrelated runs without stating that host/run variance exists.

---

# 22. Important success criteria

V12 is successful if:

1. NPC route planning no longer blocks a gameplay frame for tens/hundreds of milliseconds.
2. Multiple NPCs can wait for routes concurrently.
3. NPCs actually transition from parked to moving.
4. Route planning work remains bounded per frame.
5. Failed routes do not cause a tight retry loop.
6. stale route results cannot affect newer NPC/world state.
7. map synchronization does not create invalid routes.
8. memory usage remains stable.
9. the existing kerb-gap behavior remains correct.
10. the existing right-turn clearance remains correct.
11. the system scales better as NPC count increases.
12. the design does not prevent future vehicle types.

---

# 23. Regression tests

Add tests covering:

### Incremental search

Start a route search with an intentionally small budget.

Verify:

```text
step 1 -> RUNNING
step 2 -> RUNNING
...
step N -> FOUND
```

without performing the whole search in one call.

### Failed route

Verify an unreachable destination eventually produces:

```text
FAILED
```

without blocking the frame.

### Multiple requests

Create several simultaneous route requests.

Verify all eventually progress.

### Fairness

Verify one expensive search cannot indefinitely starve other requests.

### NPC removed

Create a request.

Remove the NPC.

Complete the route.

Verify the result is discarded safely.

### Graph generation changed

Start request on graph generation N.

Change to generation N+1.

Verify stale result is not applied.

### Successful trip

Route becomes ready.

Verify:

```text
PARKED → STARTING/CRUISING
```

and the NPC begins moving.

### Failed trip retry

Verify a failed route does not immediately hammer the planner again every tick.

### Existing tests

Run the full suite.

Known existing failures must be reported separately.

---

# 24. Full test suite

Run the complete test suite after implementation.

The latest baseline was:

```text
1149 passed
6 failed
```

The six failures were:

* 5 established failures
* household-ownership NPC test, which currently fails intermittently

Do not assume any of these are caused by V12.

Determine whether the failure count changes.

Report exactly what happened.

---

# 25. Code verification

Run:

```bash
git diff --check
```

and the full test suite.

Do not claim the task is complete without running them.

---

# 26. Final report

Provide a concise engineering report.

## Root cause

Explain exactly why NPC traffic was not moving.

## Architecture

Explain:

* request queue
* active searches
* completed results
* per-frame budget
* scheduling/fairness
* graph generation handling
* NPC lifecycle handling

## Implementation

List changed files and important changes.

## Performance

Provide before/after measurements.

## Traffic result

Report:

```text
NPC population:
parked:
moving:
trip requests:
successful:
failed:
average route wait:
p95 route wait:
worst route wait:
```

## Frame impact

Report:

```text
average frame:
p95:
p99:
worst:
>=100 ms:
>=200 ms:
>=400 ms:
```

## Tests

Report:

```text
tests passed:
tests failed:
git diff --check:
```

## Remaining bottlenecks

Separate:

* confirmed bottlenecks
* suspected bottlenecks
* future work

---

# 27. Final architectural rule

Do not "solve" this by increasing the existing route-planning budget from 8 ms to 30+ ms.

That was already measured and caused unacceptable frame stalls.

Do not solve it by simply moving the existing blocking function to another place in the same frame.

The fundamental change required is:

```text
route planning is a job
```

rather than:

```text
route planning is a synchronous operation required to complete immediately
```

The implementation may use incremental main-thread planning, a worker, or another appropriate mechanism.

Choose based on the actual architecture and measurements.

Start with investigation and profiling.

Do not rewrite the planner until its current behavior and data ownership are understood.
