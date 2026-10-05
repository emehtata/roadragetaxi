# Road Rage Trip — Phase 7: Level-aware Collision, Road-Overlap and Environment Queries

You are working on the `Road Rage Trip` repository.

**Branch:** `release/0.15.0alpha`

This is **Phase 7** of the parking-garage / map-level implementation.

Phase 6 introduced level-aware driving networks.

The goal of this phase is to make the existing **collision, road-overlap, and environment queries** respect the player's current `Car.map_level`.

Do not implement level transitions, ramps, garage entrances, or underground NPC traffic in this phase.

---

# 1. Current architecture

The game now has one logical map-level model:

```text
0   = surface
-1  = underground level 1
-2  = underground level 2
+1  = above surface
...
```

The authoritative level is:

```python
Car.map_level
```

A road's logical level is determined by:

```python
Way.map_level
```

with:

```text
map_level=None → logical level 0
map_level=0    → logical level 0
map_level=-1   → logical level -1
map_level=-2   → logical level -2
...
```

The existing helper:

```python
on_map_level(...)
```

in:

```text
theroadragetrip.map_level
```

defines the level semantics.

Reuse it rather than introducing another interpretation.

---

# 2. Phase 6 state

Phase 6 introduced level-aware driving networks.

The current architecture contains:

```text
world.ways
world.level_ways
world.level_roads
```

and:

```python
world.level_roads.network(car.map_level)
```

for non-surface levels.

The surface road `SpatialWayGrid` only indexes logical level-0 roads.

Important:

* `map_level` determines logical vertical level.
* `layer` remains independent.
* `layer=-1` does NOT mean underground.
* `tunnel=yes` does NOT imply an underground map level.
* `covered=yes` does NOT imply an underground map level.
* geometry inside a `ParkingGarage` does NOT imply a level.
* only explicit `level=*` or game state can establish a non-surface level.

Do not change these semantics.

---

# 3. Phase 7 objective

Make existing collision and environment queries level-aware.

After this phase:

### On level 0

The player interacts with:

```text
surface collision geometry
surface roads
surface puddles
surface road-overlap data
```

but not explicitly levelled underground/above-ground objects.

### On level -1

The player interacts with:

```text
level -1 collision geometry
level -1 road-overlap data
level -1 puddles/wet-road state
```

and must not collide with unrelated level-0 geometry merely because the coordinates overlap.

### On level -2

The same rule applies to level -2.

### General rule

An environment object with no explicit map level belongs to the surface world.

An explicitly levelled object belongs only to that level.

Do not infer a level from geometry, `layer`, `tunnel`, `covered`, or garage membership.

---

# 4. First task: audit the existing collision architecture

Before changing code, inspect the repository thoroughly.

Find all code involved in:

* building collision
* tree collision
* obstacle collision
* scenery collision
* road overlap
* road proximity
* taxi road overlap
* puddles
* wet roads
* surface/environment queries
* collision grids/spatial indexes
* nearest-way queries
* vehicle collision
* player collision
* environment avoidance
* collision caches
* world synchronization
* tile merge/unload handling

Search for references to:

```text
world.ways
world.buildings
buildings
trees
Scenery
collision
collider
overlap
road overlap
puddle
wet
SpatialWayGrid
map_level
level_ways
level_roads
```

Do not assume the three limitations listed in the Phase 6 report are the only level-sensitive queries.

Find every relevant query.

---

# 5. Do not redesign physics

This phase is about **selecting the correct existing world data**, not redesigning the physics engine.

Do not:

* replace Pygame collision handling
* introduce a new physics engine
* change collision shapes unnecessarily
* change vehicle dimensions
* change collision response
* change movement acceleration
* change friction
* change steering
* change damage
* change taxi gameplay

If the existing collision implementation is correct once it receives level-filtered candidates, preserve it.

The desired architecture is:

```text
current Car.map_level
        ↓
level-aware world query
        ↓
existing collision/physics
```

not:

```text
new physics implementation
```

---

# 6. Buildings

The Phase 6 report explicitly states:

> building and tree collisions still use the surface world on any level.

Fix this.

Inspect how buildings are currently represented and how collision geometry is generated.

`Building.map_level` already exists.

Use the same map-level semantics as roads:

```text
Building.map_level=None → level 0
Building.map_level=0    → level 0
Building.map_level=-1   → level -1
...
```

A building with:

```python
map_level=-1
```

must only participate in collision queries while the player is on level `-1`.

A surface building:

```python
map_level=None
```

must not collide with the player on level `-1`.

Do not infer levels from:

```text
building:levels
geometry
building type
garage membership
```

`building:levels` remains a floor count, not a map level.

---

# 7. Buildings without explicit map levels

This distinction is important.

An ordinary building with:

```python
map_level=None
```

belongs to the surface world.

It is visible/collidable on level 0.

It must not become an underground obstacle merely because:

* an underground road passes underneath it
* the road is geographically inside its footprint
* it has multiple floors
* it is a parking building
* it has `building:levels`
* it has `layer`
* another OSM object nearby has `level=-1`

Do not infer relationships that are not explicitly represented.

---

# 8. Trees and scenery collision

The Phase 6 report also states:

> tree collisions ... still use the surface world on any level.

Audit the tree/scenery representation.

Determine whether individual trees or other collidable scenery already carry:

```python
map_level
```

or whether the current scenery system is inherently surface-only.

### If the object already has an explicit map level

Make its collision query level-aware.

### If the object has no level information

Treat it as surface-world scenery.

Do NOT invent a new OSM level inference system for scenery in this phase.

If adding `map_level` to scenery is clearly necessary because the existing OSM import already has explicit level information for the object, integrate it using the existing map-level architecture.

Otherwise leave the data model unchanged and document the limitation.

Do not infer a tree's level from its position inside a garage.

---

# 9. Road-overlap queries

The Phase 6 report explicitly states:

> the taxi's road-overlap checks still use the surface world on any level.

Fix all road-overlap queries.

A car on level `L` must query roads belonging to logical level `L`.

For example:

```text
Car.map_level = 0
    → surface road network

Car.map_level = -1
    → level -1 road network

Car.map_level = -2
    → level -2 road network
```

Do not use:

```python
world.ways
```

directly when a level-aware road network already exists.

Reuse the Phase 6 road-network abstraction.

---

# 10. Taxi road overlap

Find the exact implementation used by the taxi/player system to determine:

* whether the taxi is on a road
* road overlap
* road proximity
* taxi placement relative to roads
* road-based fare/trip behaviour
* any road surface classification

Make the minimum necessary changes so these queries use the current logical map level.

Do not change taxi gameplay rules.

For example, if the existing query conceptually does:

```python
nearest_way = find_nearest_way(position)
```

it must become equivalent to:

```text
find nearest way on current map level
```

using the existing level-aware road network.

Do not add a second independent road filtering implementation.

---

# 11. Puddles and wet-road logic

The Phase 6 report states:

> puddles ... still use the surface world on any level.

Audit how puddles are created and queried.

The requirement is:

```text
puddles belonging to level L
    → visible/active only on level L
```

If puddles are generated directly from roads, make their source road selection level-aware.

If puddles are stored as independent scenery objects, inspect whether they carry sufficient source-level information.

Do not invent a new vertical-position model.

The minimum correct implementation is:

```text
surface roads → surface puddles
level -1 roads → level -1 puddles
level -2 roads → level -2 puddles
...
```

Do not allow underground puddle logic to accidentally sample surface roads.

---

# 12. Wet-road rendering

Inspect the existing wet-road rendering pass.

Phase 5 already noted that the wet-road pass did not check road levels.

Correct this where necessary.

A wet-road effect derived from a road must only use roads on the current logical map level.

Do not make unrelated global effects level-aware.

For example, a global rain/weather state can continue to exist regardless of map level.

Only road/environment geometry derived from level-specific world objects should be filtered.

---

# 13. Collision query architecture

Prefer a central level-aware query boundary.

If the existing collision system already has a spatial index, extend its query API rather than scanning the world.

Conceptually:

```python
query_colliders(position, bounds, map_level)
```

or:

```python
get_collision_candidates(..., map_level)
```

or the equivalent existing architecture.

Do not force this exact API if the repository has a better pattern.

The important rule is:

```text
spatial culling
    ↓
map-level filtering
    ↓
existing collision test
```

Do not do:

```text
scan every building
scan every tree
scan every scenery object
check map_level
```

every frame.

---

# 14. Spatial indexes

Inspect existing spatial indexes.

Possible examples include:

```text
SpatialWayGrid
building grids
scenery grids
collision grids
tile-local indexes
```

Reuse existing indexes.

If an index is surface-only today, determine whether the smallest correct change is:

1. build separate level-aware indexes, or
2. keep the index spatial and filter `map_level` when querying.

Prefer the option that preserves the current performance characteristics.

Do not create one enormous duplicated index per map level unless there is a clear measured benefit.

---

# 15. Level 0 fast path

Level 0 is the common/default case.

Preserve the existing optimized surface path.

Avoid adding expensive generic processing such as:

```python
for every collider:
    if on_map_level(...)
```

every frame if the same filtering can happen when:

* the spatial index is built
* the tile is merged
* the world is synchronized
* the collision candidate list is generated

Use the existing architecture to move filtering out of the frame loop where practical.

---

# 16. Level switching

The Phase 5 debug control currently allows:

```text
0 → -1 → -2 → 0
```

and Phase 6 made the road network selection dynamic.

The same must now apply to collision/environment queries.

When `Car.map_level` changes:

```text
0 → -1
```

the next collision/environment query must automatically use level `-1`.

When changing:

```text
-1 → -2
```

it must use level `-2`.

When returning:

```text
-2 → 0
```

it must use the surface world.

Changing level must NOT:

* reload OSM
* fetch tiles
* rebuild the entire world
* recreate unrelated scenery
* rebuild all physics state unnecessarily

If an existing index can be reused, reuse it.

---

# 17. No cross-level collision

This is a hard requirement.

Suppose the following objects occupy the same XY coordinates:

```text
Building A:
    map_level=None

Road B:
    map_level=-1
```

They are not automatically collision-related.

Likewise:

```text
Tree A:
    surface

Road B:
    level=-1
```

must not collide merely because their coordinates overlap.

The map-level system is intentionally a logical separation at this stage.

---

# 18. `layer` remains independent

Do not change the meaning of:

```python
Way.layer
Car.layer
```

A road such as:

```text
map_level=None
layer=-1
```

is still a surface road.

A building's or object's `layer` must not be converted into a `map_level`.

Do not add logic such as:

```python
if layer < 0:
    underground = True
```

---

# 19. Garage geometry remains data-only

`ParkingGarage` remains a data model.

Do not use:

```python
ParkingGarage.points_m
```

as collision geometry in this phase.

Do not make the garage outline itself a collision boundary.

Do not prevent the player from entering a garage polygon.

Do not infer:

```text
inside garage → underground
```

A later phase will introduce actual garage entrances and level transitions.

---

# 20. Tile streaming

Level-aware collision must work with the existing tile streaming lifecycle.

When a tile loads:

```text
surface collision objects
level-specific collision objects
```

must become available through the normal world synchronization process.

When a tile unloads, their existing collision/index data must be removed using the existing mechanisms.

Do not create a separate collision-specific OSM fetch.

Do not keep hidden level geometry loaded solely because it is currently the player's level.

Data residency remains independent of visibility and current level.

---

# 21. Map synchronization

Find the existing map-sync lifecycle.

When:

```text
world data changes
```

ensure all affected level-aware collision/index structures are refreshed.

Avoid rebuilding unrelated structures if only one tile changed.

If the existing architecture already rebuilds a global index after synchronization, reuse it.

Do not create an independent synchronization system.

---

# 22. NPC traffic

NPC traffic remains **surface-only** in Phase 7.

Do not implement underground NPC traffic.

However, make sure the new level-aware road-overlap/collision changes do not accidentally break surface NPC behaviour.

NPC cars without explicit level state should continue to behave as surface entities.

Do not introduce `NPC.map_level` merely for completeness.

If a shared helper now requires a level argument, use:

```text
0
```

for existing surface-only NPC traffic.

---

# 23. Pedestrians

Do not redesign the pedestrian network in this phase.

Phase 6 noted that:

> the pedestrian network still includes off-surface footways, such as Oulu's 52 level=1 walkways, as surface paths.

That is a known limitation.

Do not attempt to solve the pedestrian routing problem here unless a pedestrian query is directly used by collision/environment logic being changed.

If a shared road/environment helper affects pedestrians, preserve their existing surface-only behaviour.

A dedicated pedestrian level-aware phase can come later.

---

# 24. Rendering

Only modify rendering where required to prevent incorrect use of surface-level environment data.

Do not redo Phase 5's render gate.

Do not change:

* HUD
* debug overlays
* day/night overlay
* global weather
* train simulation
* train rendering architecture
* labels unrelated to collision/environment queries

The goal is to make physical/environmental queries level-aware, not to reopen the rendering implementation.

---

# 25. Weather

Global weather remains global.

For example:

```text
rain
snow
day/night
```

can continue to exist on every level.

Only level-specific world interactions must be filtered.

Do not create separate weather simulations for each garage level.

---

# 26. Collision semantics

Preserve existing collision behaviour.

If a building currently produces a collision rectangle/polygon:

```text
same collision shape
same collision response
same movement response
```

but candidate selection becomes level-aware.

Do not change collision tolerances unless required to fix a discovered bug.

Do not change vehicle dimensions.

Do not change player movement physics.

---

# 27. Tests

Add focused tests for level-aware collision and environment selection.

At minimum cover:

## Buildings

```text
Building.map_level=None
    → collision on level 0

Building.map_level=None
    → no collision on level -1

Building.map_level=-1
    → collision on level -1

Building.map_level=-1
    → no collision on level 0
```

## Roads

```text
surface road
    → road-overlap on level 0

surface road
    → not road-overlap on level -1

level=-1 road
    → road-overlap on level -1

level=-1 road
    → not road-overlap on level 0
```

## Layer independence

```text
map_level=None
layer=-1
```

must remain surface collision/road data.

## No geometry inference

A level-0 building containing or overlapping an underground road must not become an underground collider.

## Taxi road overlap

A taxi/player at the same XY position on:

```text
level 0
level -1
```

must query the corresponding road network.

## Level switching

Changing:

```text
0 → -1 → -2 → 0
```

must change collision/query candidates without world reload.

## Empty levels

If a level has no collision or road data:

```text
query → empty result
```

must be returned.

Do NOT fall back to surface geometry.

---

# 28. Regression tests

Run the complete existing test suite.

Pay particular attention to:

* map-level tests
* Phase 5 rendering tests
* Phase 6 road-network tests
* player movement
* taxi tests
* collision tests
* routing tests
* NPC tests
* puddle/wet-road tests
* tile streaming tests
* world cache tests

Do not weaken existing tests.

---

# 29. Performance requirements

This phase must not introduce a per-frame full-world scan.

Measure the existing Oulu benchmark before and after where possible.

At minimum measure:

```text
surface level 0
level -1
level -2
0 → -1 → -2 → 0 switching
```

Record:

* average frame time
* p95 frame time
* worst frame time
* FPS
* collision/query timing if available
* road-overlap timing if available
* allocations/GC if available
* map synchronization time if affected

The important metric is frame-time stability.

Do not claim an optimization without measurements.

If level -1/-2 contains too little collision data for a meaningful comparison, document that limitation.

---

# 30. Performance design target

The intended runtime path should look approximately like:

```text
Car.map_level
      ↓
current level-aware spatial/query structure
      ↓
small candidate set
      ↓
existing collision/overlap test
```

It must NOT look like:

```text
Car.map_level
      ↓
scan all buildings
scan all trees
scan all roads
scan all scenery
      ↓
filter by level
      ↓
collision
```

If an existing spatial index is already tile-local, use it.

---

# 31. Search for bypasses

After implementation, search the entire repository for direct access to:

```text
world.ways
world.level_ways
world.buildings
```

and relevant scenery collections.

For every usage, determine whether it is:

* rendering
* simulation
* collision
* routing
* debugging
* serialization
* map synchronization
* unrelated metadata

Make sure no important collision or road-overlap path bypasses the level-aware abstraction.

Do not blindly replace every `world.ways` access.

Some systems legitimately need the complete world data.

---

# 32. Required implementation workflow

Follow this exact workflow.

## Step 1 — Audit

Inspect:

* building collision
* tree collision
* scenery collision
* road overlap
* taxi road queries
* puddles
* wet-road rendering
* collision indexes
* map synchronization
* tile loading/unloading

Identify all level-sensitive paths.

## Step 2 — Design

Choose the smallest architecture that integrates with Phase 6.

Prefer existing:

```text
SpatialWayGrid
LevelRoadNetworks
world synchronization
tile lifecycle
```

over parallel systems.

## Step 3 — Implement buildings

Make building collision level-aware.

## Step 4 — Implement road overlap

Reuse Phase 6's level-aware road networks.

## Step 5 — Implement trees/scenery where supported

Only use explicit level information.

Do not invent level inference.

## Step 6 — Implement puddle/wet-road selection

Ensure road-derived effects use roads from the current logical level.

## Step 7 — Integrate map synchronization

Ensure indexes remain correct after tile load/unload/sync.

## Step 8 — Tests

Add focused tests and run the complete suite.

## Step 9 — Benchmark

Run the Oulu benchmark before/after.

## Step 10 — Review

Search for remaining collision/road-overlap/environment queries that still implicitly assume the surface world.

---

# 33. Things explicitly NOT to implement

Do NOT implement:

* ramps
* garage entrances
* `parking=entrance`
* automatic level changes
* stairs
* elevators
* teleportation
* cross-level routing
* cross-level collision
* underground NPC traffic
* underground pedestrian simulation
* pedestrian network redesign
* garage polygon collision
* garage parking behaviour
* parking-space selection
* geometry-based level inference
* `layer` → `map_level`
* `tunnel` → `map_level`
* `covered` → `map_level`
* level-specific OSM fetching
* level-specific tile streaming
* new loading screens
* unrelated rendering changes
* new physics engine
* changes to vehicle physics

Keep this phase strictly focused on **level-aware selection of existing collision and environment data**.

---

# 34. Acceptance criteria

Phase 7 is complete only when:

* [ ] Building collision respects `map_level`.
* [ ] Surface buildings remain surface-only.
* [ ] Explicitly levelled buildings collide only on their own level.
* [ ] Tree/scenery collision is level-aware where explicit level data exists.
* [ ] Surface-only scenery remains surface-only.
* [ ] Taxi road-overlap uses the current map level.
* [ ] Road proximity/nearest-road queries use the current map level.
* [ ] Puddles use roads from the current logical level.
* [ ] Wet-road rendering does not accidentally use surface roads underground.
* [ ] `map_level=None` consistently means logical level 0.
* [ ] `layer` remains independent.
* [ ] No level is inferred from geometry.
* [ ] Garage polygons remain non-collidable.
* [ ] No surface collision occurs on underground levels merely because XY coordinates overlap.
* [ ] No underground collision occurs on the surface merely because XY coordinates overlap.
* [ ] Empty levels return empty query results.
* [ ] There is no fallback from an empty level to level 0.
* [ ] Level switching does not reload or fetch map data.
* [ ] Tile streaming continues to work normally.
* [ ] Existing surface behaviour remains unchanged.
* [ ] NPC traffic remains surface-only.
* [ ] Pedestrian routing remains unchanged unless a minimal compatibility change is unavoidable.
* [ ] No per-frame full-world scan has been introduced.
* [ ] Focused tests pass.
* [ ] Full existing test suite passes.
* [ ] Oulu performance benchmarks have been run.
* [ ] No significant surface frame-time regression has been introduced.

---

# 35. Final implementation report

At the end, provide a concise report containing:

1. files changed
2. collision/environment architecture discovered
3. building collision changes
4. tree/scenery handling
5. road-overlap changes
6. taxi integration
7. puddle/wet-road changes
8. map synchronization changes
9. tests added
10. complete test results
11. benchmark results
12. remaining limitations

Clearly separate:

```text
implemented in Phase 7
```

from:

```text
intentionally deferred to later phases
```

Do not implement Phase 8 features.
