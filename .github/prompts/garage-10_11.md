# Road Rage Trip — Phase 11/12: Level-Aware Routing and Level Connector Graph Integration

You are working on the `Road Rage Trip` repository.

**Branch:** `release/0.15.0alpha`

This phase combines the previously planned:

* **Phase 11 — level-aware route graphs**
* **Phase 12 — level connector integration**

Do not implement them as two independent temporary systems. The goal is one coherent routing architecture in which each logical map level has its own road graph and existing, resolved `LevelConnector` objects provide the only legal graph-to-graph transitions.

---

# 1. Current architecture

Phases 1–10 have already implemented:

* `Car.map_level`
* strict OSM `level=*` parsing
* `Way.map_level`
* raw `Way.level`
* `explicit_levels(way)`
* `world.level_ways`
* `LevelRoadNetworks`
* level-aware spatial road grids
* level-aware driving/collision/rendering
* `ParkingGarage`
* `LevelConnector`
* `world.level_connectors`
* `LevelTransitions`
* connector resolution based on explicit road levels
* multi-level roads such as `level=0;-1`
* level-specific road networks
* runtime player level transitions

Important current semantics:

```text
Car.map_level == 0
    → surface network

Car.map_level == -1
    → level -1 network

Car.map_level == -2
    → level -2 network
```

A road may explicitly belong to multiple logical levels when its raw OSM `level=*` is a clean multi-level list.

Example:

```text
level=0;-1
```

means the road is available on both levels.

---

# 2. Current routing limitation

The current route graph remains effectively surface-only.

The existing architecture already has:

```text
LevelRoadNetworks
```

but route planning does not yet construct independent route graphs for those networks.

When the player leaves level 0:

* the surface route becomes invalid
* route planning cannot continue on the current level
* level connectors are not graph edges
* there is no route through a parking garage from surface to an underground destination

The goal of this phase is to remove that limitation.

---

# 3. Target architecture

The final architecture should conceptually be:

```text
                    ┌─────────────────────┐
                    │  Surface RouteGraph │
                    │       level 0       │
                    └──────────┬──────────┘
                               │
                         LevelConnector
                               │
                         0 ↔ -1
                               │
                    ┌──────────▼──────────┐
                    │  RouteGraph level   │
                    │        -1           │
                    └──────────┬──────────┘
                               │
                         LevelConnector
                               │
                         -1 ↔ -2
                               │
                    ┌──────────▼──────────┐
                    │  RouteGraph level   │
                    │        -2           │
                    └─────────────────────┘
```

There may be any number of logical levels.

Do not hard-code:

```text
-1
-2
```

as special cases.

---

# 4. Critical semantic rule

A route graph must only contain roads that are actually drivable on that logical level.

Use the already-established level semantics.

Do NOT infer levels from:

* `tunnel`
* `covered`
* `layer`
* `location`
* `building`
* `ParkingGarage.levels`
* geometry
* physical containment

The route graph must use the existing level-aware road selection.

---

# 5. Reuse the existing level networks

Do not create a second implementation of level-aware spatial road selection.

Inspect and reuse:

```text
LevelRoadNetworks
level_view_ways
SpatialWayGrid
on_map_level
explicit_levels
```

The route graph builder should consume the same road set that the driving system considers valid for the level.

There must not be a situation where:

```text
driving network says road is available
```

but:

```text
route graph says road does not exist
```

or vice versa.

---

# 6. First task: audit the existing RouteGraph implementation

Before changing anything, inspect:

* `RouteGraph`
* `RouteGraphBuild`
* route-node creation
* road segment creation
* route lookup
* nearest-road lookup
* player navigation
* NPC route generation
* route cache/rebuild logic
* map synchronization
* any code assuming level 0

Do not start by designing a new graph abstraction.

First determine how the current graph can be generalized with the smallest coherent change.

---

# 7. Level-specific RouteGraph instances

Introduce level-specific route graphs using the existing architecture.

Conceptually:

```python
route_graphs[0]
route_graphs[-1]
route_graphs[-2]
```

The exact implementation is up to the existing codebase.

Do not require callers to understand the internal storage representation if a manager/service abstraction is more appropriate.

The important contract is:

```text
get_route_graph(level)
```

returns the graph representing roads legally drivable on that logical level.

If a level has no roads:

```text
get_route_graph(level)
→ None / empty graph
```

according to existing project conventions.

Never silently return the surface graph as a fallback.

---

# 8. Surface graph must remain correct

The existing surface graph must continue to contain only surface-drivable roads.

That means:

```text
map_level is None
```

roads remain surface roads.

Explicit:

```text
map_level=0
```

roads are surface roads.

A multi-level road:

```text
level=0;-1
```

must be available on the surface graph.

A road:

```text
level=-1
```

must NOT appear in the surface graph.

---

# 9. Multi-level road handling

Phase 9/10 established this important behaviour.

For:

```text
level=0;-1
```

the road is available on:

```text
graph[0]
graph[-1]
```

For:

```text
level=-1;-2
```

the road is available on:

```text
graph[-1]
graph[-2]
```

For:

```text
level=-2
```

it is available only on:

```text
graph[-2]
```

Use `explicit_levels(way)` where appropriate.

Do not duplicate parsing logic.

---

# 10. Graph identity

A route graph must be associated with exactly one logical level.

Do not create one graph that contains roads from every level and attempt to filter during A*.

Prefer:

```text
RouteGraph(level=0)
RouteGraph(level=-1)
RouteGraph(level=-2)
```

or an equivalent manager-owned representation.

This keeps routing semantics explicit and prevents accidental cross-level edges.

---

# 11. No implicit cross-level edges

A route graph must NEVER connect:

```text
level 0
```

to:

```text
level -1
```

merely because roads share coordinates or OSM nodes.

Cross-level routing is only legal through an explicitly resolved `LevelConnector`.

This is critical.

Do not use:

* identical x/y
* shared OSM node IDs
* building containment
* road proximity
* `layer`
* tunnel geometry

as implicit level transitions.

---

# 12. Integrate LevelConnector into routing

Existing:

```text
world.level_connectors
```

and:

```text
level_transitions.resolve_connectors
```

already determine which connectors are valid.

Reuse that resolution.

Do not create a second connector-resolution algorithm.

Only connectors that are already resolved and have an unambiguous transition may become routing transitions.

For example:

```text
connector 636848833
0 ↔ -1
```

may create a routing connection.

An unresolved connector must not appear in the route graph.

---

# 13. Connector graph edge

A resolved connector represents a connection between two logical route graphs.

Conceptually:

```text
graph[0]
   |
   | connector 636848833
   |
graph[-1]
```

The graph-level representation must retain enough information to reconstruct the actual route.

At minimum, preserve:

```text
connector OSM ID
from_level
to_level
road association
connector position
```

Do not invent `from_level` and `to_level` in `LevelConnector` itself if the existing model intentionally does not contain those fields.

Use the existing resolved transition representation.

---

# 14. Connector cost

A connector must have a route cost.

Do not make level changes free.

Use the existing road/route cost conventions where possible.

The cost should represent at least the physical distance required to traverse the connector.

If the current connector model does not provide a complete connector geometry, use the existing road geometry around the connector rather than inventing a separate ramp length.

Do not introduce arbitrary large penalties such as:

```text
+1000
```

without a documented reason.

If a connector's physical traversal cost cannot currently be calculated reliably, keep the implementation minimal and document the limitation rather than inventing a value.

---

# 15. Do not create fake roads

The connector itself is not necessarily a road.

Do not create a synthetic road segment merely to make A* work unless the existing route architecture requires one.

Prefer connecting the nearest valid graph nodes/road segments associated with the connector's actual `road_os_ids`.

The resulting route must still correspond to real OSM road geometry.

---

# 16. Connector endpoints

Use:

```text
LevelConnector.road_os_ids
```

to identify the actual roads participating in the connector.

Resolve those OSM IDs against:

* `world.ways`
* `world.level_ways`

according to the existing architecture.

For each resolved connector determine the appropriate graph node/edge on each side.

Do not use arbitrary nearest-road searches if the connector already provides exact road IDs.

---

# 17. Multi-level road and connector interaction

A road such as:

```text
level=0;-1
```

already exists in both graphs.

Therefore do not create a connector merely because the same road exists in two graphs.

The connector is required only for an actual level transition.

Example:

```text
level=0;-1 road
```

can be present in:

```text
graph[0]
graph[-1]
```

but a `LevelConnector` is still the mechanism that changes:

```text
Car.map_level
```

from 0 to -1.

Do not confuse:

```text
road available on two levels
```

with:

```text
level transition exists
```

---

# 18. Route planning across levels

Implement route planning that can find:

```text
surface
    ↓
connector
    ↓
level -1
    ↓
destination
```

and the reverse:

```text
level -1
    ↓
connector
    ↓
surface
```

For multiple levels:

```text
0 → -1 → -2
```

must be possible if and only if actual resolved connectors exist.

Do not permit:

```text
0 → -2
```

unless there is a valid connector path.

---

# 19. Preferred routing architecture

If practical within the existing codebase, use a two-layer model:

```text
Level route graphs
        +
Level transition graph
```

For example:

```text
Level 0 graph
Level -1 graph
Level -2 graph

Connector graph:
0 ↔ -1
0 ↔ -2
-1 ↔ -2
```

Route planning can then:

1. determine the relevant level graph(s)
2. find a valid sequence of levels through resolved connectors
3. route within each level
4. join the segments through connectors

Do not build a huge monolithic graph containing every level unless the existing route implementation makes that clearly superior.

The implementation should remain compatible with the current graph architecture.

---

# 20. Do not assume level order

Do not assume that routing always proceeds:

```text
0 → -1 → -2
```

A connector may theoretically connect:

```text
0 ↔ +1
-2 ↔ -1
+1 ↔ +2
```

The graph must use actual resolved connectors rather than arithmetic assumptions.

---

# 21. Route result must contain level information

A route crossing levels must retain enough information for the driving system to know when the route enters another level.

The exact route representation should follow the existing project architecture, but conceptually:

```text
RouteSegment(level=0)
RouteTransition(connector=636848833, 0, -1)
RouteSegment(level=-1)
```

Do not discard the level information after pathfinding.

---

# 22. Player routing

Update player navigation so that:

```text
Car.map_level
```

selects the appropriate starting graph.

If the player is on level -1:

```text
route_graph = graph[-1]
```

not:

```text
graph[0]
```

If the destination is on another level, route planning must consider valid connectors.

---

# 23. Route invalidation

Existing route invalidation must remain correct.

A route must be invalidated/rebuilt when:

* map data changes
* relevant level roads change
* connector resolution changes
* current level changes
* destination changes

Do not rebuild every route graph every frame.

---

# 24. Map synchronization

Existing tile streaming can add/remove roads.

When map synchronization occurs:

1. update affected `LevelRoadNetworks`
2. update affected level route graphs
3. update connector resolution if necessary
4. update level transition graph
5. invalidate affected routes

Do not rebuild all level graphs on every frame.

Prefer incremental or map-sync-time rebuilding consistent with the existing route architecture.

---

# 25. Tile streaming

This is particularly important.

The game uses runtime tile streaming.

A connector may reference a road that is not currently loaded.

Existing Phase 8/9 behaviour already waits for missing referenced roads.

Preserve that principle.

Do not create a permanent invalid connector because one referenced road is temporarily outside the loaded tile set.

When the required tile arrives:

```text
roads loaded
    ↓
connector resolves
    ↓
route graph transition becomes available
```

When the tile disappears:

```text
connector/road removed
    ↓
transition invalidated
    ↓
affected route invalidated
```

---

# 26. No blocking during streaming

Do not introduce:

* synchronous OSM fetches
* synchronous route-graph rebuilds over the whole world
* loading screens

into gameplay.

Background tile fetching must remain background work.

Graph integration must respect the existing incremental/map-sync architecture.

---

# 27. NPC routing

Do not immediately rewrite all NPC traffic routing.

First make the routing infrastructure level-aware.

Then inspect existing NPC route callers.

If the existing NPC route API can automatically use:

```text Car.map_level
```

without a broad redesign, adapt it.

Otherwise keep NPC behaviour surface-only for this phase and explicitly document that level-aware NPC routing is deferred.

Do NOT implement a second NPC routing system.

---

# 28. Pedestrians

Do not implement level-aware pedestrian routing in this phase.

Pedestrian networks are a separate concern.

Do not mix pedestrian graph changes into this work.

---

# 29. Parking garages are not automatically destinations

Do not make every `ParkingGarage` routable as a destination merely because it exists.

The route graph should only contain actual road geometry.

Garage metadata remains separate.

---

# 30. Debugging support

Extend the existing debug HUD where useful.

At minimum, when debug mode is enabled, provide enough information to diagnose:

```text
current map level
active route graph level
number of route graphs
resolved level connectors
current route level
next connector
```

Do not add expensive per-frame debug calculations.

If there is already an existing route debug overlay, extend it rather than creating another system.

---

# 31. Tests — level graph construction

Add focused tests for:

### Surface-only road

```text
level=None
```

→ graph 0 only.

### Explicit surface road

```text
level=0
```

→ graph 0.

### Underground road

```text
level=-1
```

→ graph -1 only.

### Multi-level road

```text
level=0;-1
```

→ graph 0 and graph -1.

### Multi-level underground road

```text
level=-1;-2
```

→ graph -1 and graph -2.

### Physical tunnel without level

```text
tunnel=yes
level=None
```

→ must not become graph -1.

### Layer-only tunnel

```text
layer=-1
level=None
```

→ surface semantics remain unchanged.

---

# 32. Tests — connector integration

Use the existing Oulu connector semantics.

Test:

```text
0 ↔ -1
```

creates a valid graph transition.

Test:

```text
0 ↔ -2
```

creates a valid graph transition.

Test an unresolved connector:

```text
no resolved destination
```

creates no graph transition.

Test an ambiguous connector:

```text
0, -1, -2
```

creates no transition if the existing Phase 9 resolver rejects it.

---

# 33. Tests — route isolation

This is critical.

Verify:

```text
graph[0]
```

cannot reach:

```text
graph[-1]
```

without a resolved connector.

Verify that two roads at identical coordinates on different levels do not become connected automatically.

Verify that shared OSM geometry does not create an implicit cross-level edge.

---

# 34. Tests — actual multi-level route

Construct a small graph:

```text
surface road
    |
connector
    |
level -1 road
    |
destination
```

Verify the route contains:

```text
surface segment
connector transition
level -1 segment
```

and that the route knows the correct logical level for each segment.

---

# 35. Tests — reverse route

Verify:

```text
level -1
    ↓
connector
    ↓
surface
```

works.

The connector must be bidirectional only when the underlying road/connector semantics permit driving in both directions.

Do not assume every parking entrance is automatically bidirectional if the OSM data explicitly indicates otherwise.

---

# 36. Tests — no fake route

Verify that an unresolved parking entrance cannot produce:

```text
surface → underground
```

just because:

```text
amenity=parking_entrance
```

exists.

---

# 37. Oulu acceptance tests

Use the actual Oulu world.

The existing valid connectors are:

```text
636848833
0 ↔ -1

4116535367
0 ↔ -2
```

Verify that:

* their route graph transitions exist
* route planning can use them where appropriate
* driving through them still changes `Car.map_level`
* each transition fires only once per traversal
* reverse traversal still works

The seven unresolved Phase 10 connectors must remain unresolved.

Do not artificially increase the connector count.

---

# 38. Important Phase 10 regression

Preserve the Phase 10 multi-level road fix.

In particular:

```text
way 848810277
level=-1;0
```

must remain available to:

```text
graph[0]
graph[-1]
```

and must not regress to the old Phase 4 behaviour.

---

# 39. Performance requirements

This phase must not introduce per-frame route-graph construction.

Route graphs must be:

* built at startup
* rebuilt/updated at map synchronization
* or updated incrementally where practical

Never:

```text
every frame:
    rebuild graph
```

Measure Oulu before and after.

Record:

* route graph build time
* number of graphs
* node count per graph
* edge count per graph
* connector count
* route calculation time
* frame time
* p95 frame time

Do not optimize prematurely.

First establish correct graph ownership and invalidation.

---

# 40. Memory

Do not duplicate the complete road geometry unnecessarily for every graph.

Where possible, route graph nodes/edges should reference existing `Way`/road data.

Especially avoid copying large coordinate arrays.

Oulu currently has approximately:

```text
30,000+ ways
```

so unnecessary duplication can become significant.

---

# 41. Cache considerations

Inspect whether `RouteGraph` is currently persisted.

If route graphs are derived entirely from world/cache road data and are currently rebuilt, continue that pattern unless there is a compelling reason to persist them.

Do not introduce another cache format merely to implement levels.

If an existing cache format genuinely needs a version bump, follow existing conventions.

---

# 42. API compatibility

Keep the existing route API working where possible.

For example, if current code expects:

```python
find_route(start, destination)
```

do not unnecessarily change every caller to:

```python
find_route(level, start, destination)
```

Prefer deriving the starting level from:

```text
Car.map_level
```

or introducing a small compatibility layer.

For explicit cross-level destinations, use a clean route request representation.

Do not spread map-level logic through unrelated gameplay systems.

---

# 43. Avoid special-casing Oulu

Do not write:

```python
if city == "Oulu":
```

or hard-code:

```text
636848833
4116535367
```

into production routing code.

Those IDs are acceptance-test fixtures only.

---

# 44. Do not solve unresolved Phase 10 connectors

Do not revisit the seven unresolved tunnel stubs in this phase.

Their current status is intentional:

```text
no explicit level
no unambiguous topology
→ unresolved
```

Do not add level inference merely because routing now exists.

A future phase may investigate richer OSM topology, but this phase must use the existing resolver semantics.

---

# 45. Implementation order

Follow this order.

## Step 1 — Audit

Understand the existing RouteGraph implementation.

## Step 2 — Extract level-specific road inputs

Reuse `LevelRoadNetworks` / existing level filtering.

## Step 3 — Build route graphs per level

Keep each graph internally level-specific.

## Step 4 — Test graph isolation

Prove that graphs cannot implicitly cross levels.

## Step 5 — Integrate resolved connectors

Use existing `LevelTransitions`/connector resolution.

## Step 6 — Build the level transition graph

Only resolved connectors become cross-level edges.

## Step 7 — Implement multi-level route planning

Support:

```text
same-level route
cross-level route
multi-level route
```

## Step 8 — Integrate player navigation

Use `Car.map_level`.

## Step 9 — Handle map synchronization

Keep graph updates off the per-frame path.

## Step 10 — Oulu validation

Test the actual 0 ↔ -1 and 0 ↔ -2 connectors.

## Step 11 — Performance benchmark

Compare against the current implementation.

## Step 12 — Full regression suite

Run all tests.

---

# 46. Acceptance criteria

This phase is complete only when:

* [ ] Every logical level with drivable roads can have its own route graph.
* [ ] Surface routing remains unchanged for surface-only maps.
* [ ] `level=-1` roads are absent from graph 0.
* [ ] `level=-1` roads appear in graph -1.
* [ ] `level=0;-1` roads appear in both graphs.
* [ ] `level=-1;-2` roads appear in both corresponding graphs.
* [ ] `tunnel=yes` without `level` does not create an underground graph membership.
* [ ] `layer=-1` without `level` remains surface semantics.
* [ ] No graph has implicit cross-level edges.
* [ ] Only resolved `LevelConnector` objects create cross-level route transitions.
* [ ] Unresolved connectors cannot be used for routing.
* [ ] Connector transitions are bidirectional only when the underlying road semantics permit it.
* [ ] Routes can cross 0 ↔ -1.
* [ ] Routes can cross 0 ↔ -2.
* [ ] Routes can traverse multiple levels when actual connectors permit it.
* [ ] Reverse routes work.
* [ ] Route segments retain their logical level.
* [ ] Player routing uses `Car.map_level`.
* [ ] Existing player level transitions remain functional.
* [ ] Phase 10's `level=-1;0` regression remains fixed.
* [ ] Map streaming does not introduce blocking route-graph rebuilds.
* [ ] No route graph is rebuilt every frame.
* [ ] The seven unresolved Phase 10 connectors remain unresolved.
* [ ] No Oulu-specific production special cases are introduced.
* [ ] Existing tests pass.
* [ ] New level-routing tests pass.
* [ ] Oulu acceptance tests pass.
* [ ] Frame-time regression is within normal benchmark noise.
* [ ] Route calculation performance is measured.
* [ ] Memory impact is measured.

---

# 47. Final report

Provide a concise implementation report containing:

1. files changed
2. RouteGraph architecture before/after
3. how level-specific graphs are represented
4. how roads are assigned to graphs
5. how multi-level roads are represented
6. how connector transitions are represented
7. how connector costs are calculated
8. how routes cross levels
9. how route results retain level information
10. how player navigation selects the correct graph
11. map-sync/update behaviour
12. Oulu graph counts per level
13. Oulu connector graph transitions
14. route examples using 0 ↔ -1 and 0 ↔ -2
15. tests added
16. full test-suite result
17. route calculation benchmark
18. frame-time benchmark
19. memory impact
20. remaining limitations

Clearly separate:

```text
implemented
```

from:

```text
intentionally deferred
```

Do not implement pedestrian level routing, underground NPC traffic, garage parking AI, visual transition effects, or new OSM level inference in this phase.

The central rule remains:

> **A road belongs to a logical level only because explicit OSM level semantics or already-established game data says so. A cross-level route exists only through a resolved LevelConnector.**
