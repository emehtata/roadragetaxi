
````text
# Road Rage Taxi — V11: Pedestrian Route Search Optimization

## Working branch

Work ONLY on:

release/0.15.0alpha

Do not switch branches.

## Objective

Optimize the pedestrian route-search system.

V10 profiling established that Python GC is no longer the main performance problem. The shipped GC configuration reduced generation-2 collections from 39 per 3000-frame run to 0, with maximum observed GC pauses around 22 ms.

The next confirmed bottleneck is pedestrian route search.

The V10 final verification observed:

- `pedestrians:route_search` taking up to 621 ms in one run
- the 621 ms search appears to have been a Dijkstra search over the whole pedestrian graph
- the target was most likely unreachable
- another run completed the same stage in approximately 0.48 ms
- V9 had already observed pedestrian route-search spikes up to approximately 68 ms

The primary goal of V11 is therefore:

1. prevent route searches from exploring the entire pedestrian graph when the target is unreachable
2. preserve existing route-search behavior/output wherever a valid route exists
3. reduce worst-case route-search latency
4. avoid introducing per-frame allocations or expensive global work
5. preserve the existing world/map architecture so the same world representation can later support cars, buses, trucks, trams, trains, metros, snowplows, etc.

Do NOT optimize unrelated systems in this task.

---

# 1. IMPORTANT: investigate before changing code

Before implementing anything, inspect the existing pedestrian routing implementation thoroughly.

Find and document:

- pedestrian graph data structures
- pedestrian nodes
- pedestrian edges
- pedestrian segments/junctions
- how the graph is built
- how the graph is rebuilt during map synchronization
- how pedestrian routes are requested
- how start and target nodes are selected
- how unreachable targets can currently occur
- the exact Dijkstra implementation
- all callers of the route-search function
- route result representation
- route caching, if any
- pedestrian spawn/despawn logic related to routing
- whether route searches can happen concurrently or recursively
- whether the graph changes incrementally or is rebuilt
- whether map tiles can be unloaded after graph construction
- whether node objects remain valid across map-sync commits

Do not assume the architecture.

Read the actual code and tests.

Before modifying the implementation, identify the smallest safe insertion points for:

- connected-component calculation
- route-search rejection of impossible routes
- optional A* replacement/optimization

---

# 2. Establish the current behavior with tests/measurements

Run the existing relevant pedestrian-routing tests first.

Also locate any tests covering:

- successful pedestrian routing
- no-route cases
- map/tile loading
- pedestrian graph rebuilding
- pedestrian spawning
- pedestrian destinations
- route invalidation

Run the existing benchmark/profiling mechanism used by V10 if practical.

Record the current implementation's behavior.

Do NOT change the route algorithm before understanding the expected route output.

---

# 3. First optimization: connected components

Investigate whether the pedestrian graph can be partitioned into connected components.

Preferred approach:

During pedestrian graph construction/rebuild, assign every pedestrian graph node a component ID.

Conceptually:

```python
component_id = 0

for node in all_nodes:
    if node already assigned:
        continue

    flood_fill_or_bfs(node, component_id)

    component_id += 1
````

Use an appropriate implementation based on the actual graph structure.

Do NOT blindly implement this exact pseudocode if the existing architecture provides a better integration point.

The component calculation must:

* operate on the actual pedestrian graph
* respect the same connectivity semantics used by route search
* be performed during graph construction/rebuild, NOT once per route search
* avoid repeated full-graph scans for every pedestrian
* not add significant per-frame work
* remain valid for the graph version currently used by pedestrians

If the graph is directed, carefully determine whether route reachability requires:

* weakly connected components
* strongly connected components
* another reachability representation

Do NOT assume ordinary undirected connectivity is correct.

The component logic must match actual route reachability.

---

# 4. Early rejection

Once component information exists, add an early route-search rejection.

Conceptually:

```python
if start_node.component_id != target_node.component_id:
    return NO_ROUTE
```

But only use this exact condition if it is mathematically valid for the actual graph.

For directed graphs, implement the appropriate reachability test.

The early rejection must happen BEFORE Dijkstra/A* starts.

The important property is:

```text
unreachable target
        ↓
cheap reachability/component check
        ↓
NO_ROUTE
```

instead of:

```text
unreachable target
        ↓
Dijkstra
        ↓
visit huge portion of graph
        ↓
NO_ROUTE
```

This is the highest-priority optimization in V11.

---

# 5. Preserve route semantics

Do not change pedestrian behavior merely to improve benchmark numbers.

For reachable routes:

* same start
* same target
* same connectivity rules
* same walkable edges
* same blocked/unwalkable rules
* same route validity rules

must remain intact.

If the current Dijkstra implementation has deterministic tie-breaking behavior, preserve it unless there is a strong technical reason not to.

If route tests compare exact node sequences, do not casually change those sequences.

If tests only require a valid route, still verify that the new implementation does not introduce invalid shortcuts.

---

# 6. Investigate A* after component rejection

Only after the component/reachability optimization is implemented and verified, investigate replacing or augmenting Dijkstra with A*.

Do NOT assume A* is automatically better.

Determine:

* what coordinates pedestrian nodes have
* whether coordinates represent actual world/map positions
* whether Euclidean distance is admissible for the current edge weights
* whether edge costs are physical distance, time, or something else
* whether there are penalties that make Euclidean distance unsuitable
* whether the graph contains unusual topology
* whether all edges satisfy the assumptions required by the heuristic

If edge cost is physical walking distance and coordinates are in the same metric coordinate system, an exact Euclidean heuristic may be admissible.

If the coordinate system is latitude/longitude or otherwise not directly metric, implement the appropriate distance calculation or use a safe heuristic.

The heuristic MUST NOT overestimate the remaining path cost.

If there is uncertainty about admissibility, keep Dijkstra as the correctness reference and do not introduce an unsafe heuristic.

---

# 7. Prefer a safe architecture

If A* is appropriate, structure the code so that route searching has a clear abstraction.

For example:

```text
find_pedestrian_route(start, target)
        |
        +-- reachability check
        |
        +-- route search
              |
              +-- A* / Dijkstra
```

Avoid scattering routing decisions throughout pedestrian code.

If practical, keep the existing Dijkstra implementation available as a reference implementation for tests.

Do not duplicate large amounts of routing logic unnecessarily.

---

# 8. Graph rebuild and map synchronization

This is critical.

Road Rage Taxi streams map data and rebuilds map-derived structures.

Determine exactly what happens when:

* tiles are loaded
* tiles are merged
* tiles are unloaded
* pedestrian structures are rebuilt
* old pedestrian graph structures are replaced

Component IDs must never silently refer to an obsolete graph.

A route request must never compare:

```text
node from graph generation N
```

against:

```text
node from graph generation N+1
```

without the architecture explicitly supporting that.

If the current system has a graph generation/version mechanism, use it.

If it does not, determine whether one is necessary.

Do NOT introduce a heavyweight global synchronization mechanism unless the existing architecture requires it.

---

# 9. Tile unloading

Inspect the relationship between pedestrian graph nodes and tile ownership.

When a tile is unloaded:

* old pedestrian nodes must not remain reachable through stale component metadata
* component IDs must not survive incorrectly into a new graph
* cached routes containing removed nodes must be invalidated if such caching exists
* no references to obsolete graph structures should prevent normal cleanup

Do not solve this with `gc.freeze()` or explicit garbage collection.

V10 established that the current world is predominantly acyclic and Python reference counting already handles normal cleanup.

Keep that property.

---

# 10. Performance requirements

The optimization must target worst-case latency rather than only average FPS.

Measure at least:

* route search count
* successful route count
* failed/unreachable route count
* average route-search time
* p95
* p99
* maximum
* number of graph nodes visited by the search
* number of graph edges examined, if practical

For A*/Dijkstra comparison, preferably record:

```text
algorithm
route result
elapsed time
nodes expanded
edges examined
```

Do not add expensive instrumentation to the normal game loop unless it is behind an existing/debug/benchmark flag.

Production code should not perform logging for every route search.

---

# 11. Specifically investigate the 621 ms case

Try to reproduce the V10 behavior.

Find out why the search can run for hundreds of milliseconds.

Determine whether the expensive case is:

* unreachable target
* huge reachable search
* bad target selection
* disconnected graph
* stale graph reference
* malformed pedestrian topology
* excessive graph size
* repeated route calculation
* another issue

If the exact 621 ms case cannot be reproduced, do not invent an explanation.

Use the available profiling data and code inspection to identify the most plausible mechanism and state clearly what was and was not verified.

---

# 12. Route-search request frequency

Also inspect whether the same pedestrian can repeatedly request essentially the same route.

Look for patterns such as:

```text
pedestrian
    route request
    route fails
    next frame
    route request
    route fails
    next frame
    route request
```

If this exists, fix it only if the fix is directly related to route-search performance and is safe.

Possible safe mechanisms include:

* short-lived failed-route suppression
* route request cooldown
* caching by `(start, target, graph_generation)`
* caching successful routes where appropriate

But DO NOT introduce caching automatically.

First establish whether repeated identical searches actually occur.

If caching is added, graph generation/tile changes must invalidate stale routes correctly.

---

# 13. Do not solve the wrong problem

Do NOT:

* rewrite the entire pedestrian system
* rewrite map loading
* rewrite OSM parsing
* optimize rendering
* optimize taxi logic
* optimize NPC traffic
* disable pedestrian routing
* impose arbitrary maximum route lengths
* impose arbitrary search node limits
* randomly choose nearby destinations to hide failures
* return fake routes when no route exists
* add sleeps/yields to hide long searches
* use threading/processes merely to hide CPU cost
* add `gc.collect()` calls
* add `gc.freeze()`
* globally disable Python GC

The route result must remain correct.

---

# 14. Testing requirements

Add or update tests for at least:

### Reachable graph

```text
A -- B -- C

A -> C
```

must find a route.

### Different components

```text
A -- B

C -- D
```

must return no route immediately.

### Multiple components

Verify that component assignment is deterministic enough for the application's needs and that every graph node receives the correct reachability metadata.

### Graph rebuild

Build graph generation N.

Create route.

Rebuild graph generation N+1.

Verify old graph metadata cannot accidentally make a new route appear valid.

### Unloaded tile

If supported by the current architecture, unload the tile containing route nodes and verify stale routes are not used.

### Existing regression tests

Run the complete existing test suite.

The five established failures from V7–V10 are known:

* NPC ×2
* RWD ×2
* headless boundary

Do not silently "fix" or reinterpret these unrelated failures.

Report them separately.

---

# 15. Benchmark before and after

Use the same benchmark methodology as V10 wherever possible.

Do not compare unrelated runs without noting host/run variance.

Report:

```text
BEFORE

route search avg:
route search p95:
route search p99:
route search worst:
worst nodes expanded:
worst failed search:

AFTER

route search avg:
route search p95:
route search p99:
route search worst:
worst nodes expanded:
worst failed search:
```

Also report overall frame metrics:

```text
avg FPS / frame time
p95
p99
worst frame
frames >= 100 ms
frames >= 200 ms
frames >= 400 ms
```

If the 621 ms case cannot be reproduced, explicitly say so.

Do not claim a percentage improvement based on unrelated benchmark runs.

---

# 16. Regression verification

Run:

```bash
git diff --check
```

Run the full test suite.

Report:

* tests passed
* tests failed
* whether failures are pre-existing
* benchmark results
* files changed
* architectural changes
* any remaining concerns

Do not modify tests merely to make them pass unless the test itself is genuinely incorrect because of the intended architectural change.

---

# 17. Code quality

Keep the implementation consistent with the existing project.

Prefer:

* existing type conventions
* existing naming conventions
* existing graph abstractions
* existing logging conventions
* existing configuration patterns

Avoid unnecessary dependencies.

Do not add a new library for graph algorithms unless the repository already uses one and there is a compelling reason.

For this workload, a straightforward in-project implementation is preferable.

Keep hot-path allocations low.

Do not construct large temporary lists/sets on every route request unless unavoidable.

If component IDs are stored on nodes, document their lifecycle.

---

# 18. Architectural constraint for future vehicles

This is important for Road Rage Taxi's future architecture.

The pedestrian routing optimization must NOT make the world representation pedestrian-specific in a way that prevents future transport modes.

The underlying world should remain conceptually reusable:

```text
World
 ├── roads
 ├── lanes
 ├── intersections
 ├── pedestrian graph
 ├── vehicle graph / routing data
 ├── rail infrastructure
 └── other traversable networks
```

Future transport modes may include:

* passenger cars
* buses
* trucks
* motorcycles
* bicycles
* trams
* metros
* trains
* snowplows
* snow tractors
* other service vehicles

Do not build a generic "everything graph" prematurely.

However, do keep the pedestrian graph implementation cleanly separated from the general world/map data so future routing systems can reuse appropriate infrastructure.

---

# 19. V11 success criteria

V11 is successful if:

1. unreachable pedestrian destinations can be rejected without a full Dijkstra traversal
2. reachable pedestrian routes remain correct
3. graph rebuilds do not leave stale component IDs
4. tile unloading does not create stale route/component references
5. route-search worst-case latency is materially reduced
6. no new recurring frame spikes are introduced
7. memory behavior remains stable
8. existing tests remain green apart from the known five failures
9. the implementation does not compromise the future multi-vehicle/world architecture

The most important success criterion is NOT average FPS.

It is eliminating pathological pedestrian route searches.

---

# 20. Final report format

At the end, provide a concise engineering report with:

## Implementation

* files changed
* connected-component implementation
* route-search changes
* A* changes, if any
* graph-generation handling
* caching/cooldown changes, if any

## Correctness

* reachable route tests
* unreachable route tests
* rebuild tests
* tile-unload tests
* regression suite

## Performance

Table:

| Metric               | Before | After |
| -------------------- | -----: | ----: |
| route avg            |        |       |
| route p95            |        |       |
| route p99            |        |       |
| route worst          |        |       |
| worst nodes expanded |        |       |
| avg frame            |        |       |
| p95 frame            |        |       |
| p99 frame            |        |       |
| worst frame          |        |       |
| frames >=100 ms      |        |       |
| frames >=200 ms      |        |       |
| frames >=400 ms      |        |       |

## Remaining bottlenecks

Separate confirmed bottlenecks from hypotheses.

V10 currently identified:

1. pedestrian route search
2. taxi
3. `map_sync:traffic`

After V11, update this list based on actual measurements.

## Verification

Report:

```text
Tests: X passed, Y failed
git diff --check: clean/not clean
```

Do not claim success without actually running the tests and benchmark.

---

## Final instruction

Start by investigating the existing implementation.

Do not immediately rewrite Dijkstra.

First determine whether connected-component information can safely be integrated into the existing pedestrian graph build.

Then implement the cheapest correct early rejection.

Only after that, evaluate A* based on the actual edge-cost and coordinate semantics.

Keep the change focused on pedestrian route search and leave the taxi, NPC traffic, rendering and other V10 bottlenecks for later optimization passes.

```

Tässä on tarkoituksella **A* vasta kakkosvaiheena**. V10:n perusteella suurin yksittäinen voitto pitäisi saada jo siitä, että mahdoton kohde tunnistetaan ennen kuin Dijkstra lähtee tutkimaan 621 ms:n edestä koko graafia.
```
