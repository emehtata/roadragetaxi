# Road Rage Trip — Phase 6: Level-aware Road / Driving Network

You are working on the `Road Rage Trip` repository.

**Branch:** `release/0.15.0alpha`

This is **Phase 6** of the parking-garage / map-level implementation.

Read the repository and the existing implementation before changing anything. Do not assume that class names, helper functions, routing architecture, or data structures are exactly as described below. The repository is the source of truth.

---

## 1. Objective

Make the existing road/driving network **map-level aware**.

After this phase:

* surface roads remain drivable on map level `0`
* roads with explicit `level=0` remain drivable on map level `0`
* roads with explicit `level=-1` are drivable only on map level `-1`
* roads with explicit `level=-2` are drivable only on map level `-2`
* positive levels follow the same rule
* a road with `map_level=None` belongs to the surface world and is usable only on level `0`
* the player's current `Car.map_level` determines which road network is used for driving/routing
* level-specific roads must no longer accidentally become part of the surface driving network
* existing surface driving behaviour must remain unchanged

This phase is **not** about connecting different levels.

There must be **no automatic movement between levels yet**.

---

# 2. Important architectural rules

These rules are mandatory.

## 2.1 `map_level` and `layer` are different concepts

`map_level`:

```text
0   = surface
-1  = first underground level
-2  = second underground level
+1  = first level above surface
...
```

`layer` is still the existing OSM/rendering ordering mechanism for bridges/tunnels within a physical map level.

Do NOT replace or reinterpret `Way.layer`.

For example:

```text
Way.map_level = None
Way.layer = -1
```

is still a **surface road**.

It must remain part of the surface driving network.

Do not turn `layer=-1` into `map_level=-1`.

---

## 2.2 `map_level=None` means surface

An object without an explicit clean `level=*` has:

```python
map_level = None
```

That means:

```text
surface / level 0
```

It must not become underground merely because it has:

* `tunnel=yes`
* `covered=yes`
* `location=underground`
* `parking=underground`
* `layer=-1`
* geometry inside a `ParkingGarage`

Level must never be inferred.

---

## 2.3 Only explicit `level=*` creates a non-surface level

The existing `parse_map_level()` rules remain authoritative.

Only a clean single integer such as:

```text
-4
-2
-1
0
1
2
+1
```

creates a `map_level`.

Values such as:

```text
0;1
0-2
1.5
foo
```

remain:

```python
map_level = None
```

Do not introduce new parsing semantics in this phase.

---

# 3. Existing Phase 5 architecture

Phase 5 introduced:

```text
world.ways
world.level_ways
```

and the rendering gate.

Understand the actual implementation before changing it.

The important distinction is:

### `world.ways`

Contains the normal surface road collection.

It may also contain some roads which have explicit off-surface `map_level` values because earlier phases intentionally kept some objects there, notably:

```text
service=parking_aisle
```

and potentially other roads depending on the import rules.

Therefore:

> Do not assume that every `world.ways` entry has `map_level=None`.

The driving-network implementation must inspect `Way.map_level` rather than relying solely on collection membership.

### `world.level_ways`

Contains explicit level-aware roads which were separated from the normal surface network.

Phase 5 uses these for rendering through the level grid.

The driving implementation must reuse the existing data rather than creating a second OSM parser or duplicate road model.

---

# 4. First task: audit the existing driving architecture

Before modifying code, inspect and document internally how the game currently determines:

* which `Way` objects are drivable
* road graph construction
* road node/edge creation
* nearest-road lookup
* player road following
* car movement along roads
* collision-related road lookup
* routing/pathfinding
* NPC route selection
* traffic spawning
* any spatial road indexes/grids used by driving
* any caches derived from `world.ways`
* map synchronization / tile streaming hooks
* world rebuild hooks

Search the repository rather than guessing.

Look specifically for:

```text
world.ways
world.level_ways
Way
map_level
Car.map_level
SpatialWayGrid
routing
route
path
road graph
nearest road
nearest way
drivable
driveable
```

Also inspect the code introduced in phases 1–5.

Do not implement anything until the existing architecture is understood.

---

# 5. Design requirement: one logical road network per map level

The game should conceptually have:

```text
surface network
level -4 network
level -3 network
level -2 network
level -1 network
level  0 network
level +1 network
level +2 network
...
```

However, do **not** create unnecessary copies of all roads.

A surface road with:

```python
map_level is None
```

belongs to logical level `0`.

A road with:

```python
map_level == 0
```

also belongs to logical level `0`.

A road with:

```python
map_level == -1
```

belongs only to logical level `-1`.

A road with:

```python
map_level == -2
```

belongs only to logical level `-2`.

The implementation should provide a clean way for existing driving/routing code to ask:

```text
"Give me the drivable roads for map level X."
```

without duplicating the OSM model.

---

# 6. Surface network compatibility is critical

The default surface case must remain the fast path.

For:

```python
car.map_level == 0
```

the driving network must contain:

```text
map_level=None
map_level=0
```

but must NOT contain:

```text
map_level=-1
map_level=-2
map_level=1
...
```

This is important because Phase 5 already demonstrated that the surface game has acceptable performance.

Do not replace a fast existing surface road structure with an expensive generalized abstraction unless benchmarking proves it is safe.

If the current implementation can efficiently keep the existing surface path and add level-specific structures alongside it, prefer that approach.

---

# 7. Level-specific road networks

For non-zero levels, create/use a level-aware representation derived from the existing `Way` data.

For example, conceptually:

```text
level  0:
    world.ways where map_level is None or 0

level -1:
    world.ways/world.level_ways where map_level == -1

level -2:
    world.ways/world.level_ways where map_level == -2

level +1:
    world.ways/world.level_ways where map_level == +1
```

The exact implementation is up to the existing architecture.

Do not blindly create a dictionary of giant duplicated lists if the repository already has a better spatial/indexing abstraction.

The important property is:

> A road must belong to exactly the logical map level represented by its `map_level`, with `None` mapped to level 0.

---

# 8. Critical edge case: `world.ways` can contain off-surface roads

This must be handled correctly.

Example:

```python
Way(
    map_level=-1,
    ...
)
```

may still be present in:

```python
world.ways
```

because it is a `service=parking_aisle` or another previously exempt road.

Therefore this is WRONG:

```python
surface_roads = world.ways
```

and this is also WRONG:

```python
surface_roads = [
    way for way in world.ways
]
```

unless the implementation explicitly filters by `map_level`.

The logical surface network must be:

```text
world.ways
    where map_level is None or map_level == 0
```

and nothing else.

Likewise:

```text
level -1
    map_level == -1
```

etc.

---

# 9. Do not create level transitions

This phase must NOT implement:

* ramps
* garage entrances
* `parking=entrance`
* `highway=*` ramps between levels
* automatic level changes
* teleportation
* stairs
* elevators
* level connectors
* graph edges between `-1` and `0`
* graph edges between `-2` and `-1`

If two roads are geometrically close but have different `map_level` values, they must remain disconnected.

For example:

```text
surface road:
    map_level=None

garage road:
    map_level=-1
```

must NOT automatically become connected because their coordinates overlap.

Likewise:

```text
level=-1
level=-2
```

must not connect automatically.

There will be a later phase specifically for level transitions.

---

# 10. No geometry-based level inference

Do not introduce logic such as:

```python
if point_inside_garage:
    level = -1
```

or:

```python
if tunnel:
    level = -1
```

or:

```python
if layer < 0:
    level = -1
```

or anything similar.

The road's existing `Way.map_level` is authoritative.

`ParkingGarage` geometry is not a routing source in this phase.

---

# 11. Routing/pathfinding

Adapt the existing routing/pathfinding implementation so that it respects the current map level.

The exact changes depend on the repository's current routing implementation.

The required semantics are:

### Surface

When routing on level `0`:

```text
map_level=None    allowed
map_level=0       allowed

map_level=-1      forbidden
map_level=-2      forbidden
map_level=1       forbidden
...
```

### Underground

When routing on level `-1`:

```text
map_level=-1      allowed

map_level=None    forbidden
map_level=0       forbidden
map_level=-2      forbidden
map_level=1       forbidden
...
```

### Level `-2`

Only:

```text
map_level=-2
```

is allowed.

And similarly for positive levels.

Do not silently fall back to the surface network when no route exists on the current level.

A later level-transition phase will solve cross-level routing.

---

# 12. Nearest-road queries

Audit every nearest-road / nearest-way lookup.

A query made for a car on:

```python
map_level = -1
```

must not return a surface road merely because the surface road is geographically closest.

Likewise, a surface car must not select an underground parking aisle.

The lookup must respect logical map level.

If the existing spatial index does not support levels, extend it or introduce a level-aware query layer.

Prefer:

```text
spatial culling first
→ map-level filtering
→ nearest candidate selection
```

over scanning the entire world.

Do not introduce a full-world per-frame scan.

---

# 13. Player driving

The player car currently has:

```python
Car.map_level
```

which is `0` during normal gameplay.

Do not change its default.

The existing player driving code must continue working exactly as before on level 0.

For testing, Phase 5 already provides the debug level switch:

```text
F11
```

when the debug HUD is enabled.

If the player is manually switched to:

```text
-1
```

the driving/road lookup code must use the level `-1` network.

If the player is switched back to:

```text
0
```

the surface network must be restored.

The level switch must not:

* reload OSM data
* fetch network data
* rebuild the entire world
* regenerate unrelated scenery
* create a loading screen

Only the selected road network/query should change.

---

# 14. Player movement must not invent cross-level movement

Until the transition phase exists:

```text
level -1 → level 0
level 0 → level -1
```

must be impossible through road connectivity.

If F11 is used to change the debug level, that is a debug-only state change.

Do not add gameplay logic that changes `Car.map_level`.

---

# 15. NPCs and pedestrians

Do not implement level-aware NPC or pedestrian simulation in this phase.

However, inspect the current NPC routing code carefully.

If NPC routing currently directly consumes the same road network, ensure the new filtering does not accidentally:

* make surface NPC traffic disappear
* send NPCs onto level roads
* cause NPC routes to include underground roads
* create invalid graph connections

NPCs can remain surface-only for now.

If the existing NPC system does not have a meaningful `map_level`, leave it at surface level.

Do not redesign NPC architecture.

---

# 16. Trains and railway simulation

Do not redesign the railway simulation.

Phase 5 explicitly allows the railway simulation to continue running while underground while its rendering is hidden.

Do not make railway simulation level-aware in this phase unless the existing road-routing implementation directly depends on it.

Do not change train schedules, spawning, rendering, or railway routing.

---

# 17. Collision and physics

Do not implement full level-aware collision physics yet.

However, audit whether the current collision implementation obtains road/geometry data from `world.ways`.

If changing the road network would cause underground roads to participate in surface collision logic, prevent that regression.

Do not invent underground collision rules.

The goal of this phase is road/driving-network separation, not full underground physics.

---

# 18. Tile streaming integration

The existing tile streaming architecture must remain unchanged.

When a tile containing:

```text
level=-1 roads
level=-2 roads
```

is loaded, those roads must remain available even when the player is currently on level 0.

When the player switches to `-1`, the data must already be available if its tile is loaded.

Do NOT:

* fetch different OSM data based on the current map level
* unload hidden level roads
* rebuild the world when changing level
* add level-specific network requests

Map level is a **visibility/driving selection**, not a data residency rule.

---

# 19. Cache compatibility

Respect the current world-cache format and existing serialization.

Do not introduce unnecessary cache-format changes if `Way.map_level` is already persisted.

Verify that:

* `map_level` survives cache load
* `map_level` survives tile streaming
* `world.level_ways` survives map synchronization
* level-specific driving structures are rebuilt from existing world data rather than serialized unnecessarily, unless the architecture clearly benefits from caching them

Do not duplicate OSM source data in a second cache format.

---

# 20. Map synchronization and rebuilding

Find the existing points where:

* tiles are merged
* `world.ways` changes
* `world.level_ways` changes
* spatial road grids are rebuilt
* routing data is refreshed

Integrate the level-aware driving network into those existing lifecycle hooks.

Do not add a second independent world synchronization mechanism.

After a tile merge:

```text
new level-aware roads
        ↓
existing map synchronization
        ↓
level-aware road index/network updated
```

The implementation must correctly handle:

* tile load
* tile unload
* tile replacement
* repeated synchronization
* deduplication

---

# 21. Performance requirements

Performance is a first-class requirement.

The surface network is already optimized.

Do not introduce:

* full-world scans every frame
* rebuilding all road graphs every frame
* allocating large temporary lists every frame
* repeated filtering of every `world.ways` entry from the render/update loop
* duplicated spatial grids for every level unless justified
* expensive geometry calculations during player movement

The desired architecture is:

```text
WORLD DATA
    ↓
map synchronization
    ↓
level-aware road structures / indexes
    ↓
runtime query
    ↓
current Car.map_level
```

not:

```text
every frame
    ↓
scan every world way
    ↓
check map_level
    ↓
build candidates
```

If level-specific road indexes are necessary, build/update them only when the underlying world data changes.

---

# 22. Recommended internal abstraction

If the current architecture permits it, introduce a small abstraction around level-aware road selection.

Conceptually:

```python
get_drivable_ways(map_level)
```

or:

```python
get_road_network(map_level)
```

or an equivalent existing architecture.

Do not force this exact API if the repository already has a better pattern.

The important property is that all callers use the same level-selection rules.

Centralize the semantics:

```text
None → logical level 0
explicit 0 → logical level 0
explicit non-zero → that exact level
```

Avoid scattering slightly different `map_level` checks throughout:

* routing
* nearest-road lookup
* player movement
* NPC routing
* collision queries

---

# 23. Important semantic test cases

Add focused automated tests for the new behaviour.

At minimum test:

### Surface road

```text
map_level=None
```

is available on level `0`.

### Explicit surface road

```text
map_level=0
```

is available on level `0`.

### Underground road

```text
map_level=-1
```

is available on `-1`.

### Second underground level

```text
map_level=-2
```

is available on `-2`.

### Isolation

`-1` is not available on:

```text
0
-2
+1
```

`-2` is not available on:

```text
0
-1
```

### Surface isolation

`map_level=None` must not be available on:

```text
-1
-2
+1
```

### Layer independence

A road with:

```text
map_level=None
layer=-1
```

must still be a surface road.

### `world.ways` edge case

A road with:

```text
map_level=-1
```

that happens to remain in `world.ways` must not enter the surface network.

### `world.level_ways`

A road in:

```text
world.level_ways
map_level=-1
```

must enter the level `-1` driving network.

### No implicit connection

A level `0` road and level `-1` road with identical or adjacent geometry must remain disconnected.

### Debug level switching

Switching:

```text
0 → -1 → -2 → -1 → 0
```

must change the selected road network without triggering:

* OSM fetch
* world reload
* tile rebuild
* complete world rebuild

Use mocks/spies where appropriate to verify this.

---

# 24. Regression tests

All existing tests must continue to pass.

Pay particular attention to:

* road parsing
* BIN loading
* world cache loading
* tile streaming
* `SpatialWayGrid`
* routing
* NPC traffic
* player movement
* collision
* map-level tests
* render tests

Do not weaken or delete existing tests merely to make the new implementation pass.

---

# 25. Performance benchmark

Run a representative Oulu driving benchmark before and after the implementation.

Use the existing benchmark methodology if the repository already contains one.

Measure at minimum:

* average frame time
* p95 frame time
* worst frame time
* average FPS
* visible/drivable road counts if available
* routing/query timings if available
* allocation/GC information if available

Test at least:

```text
surface level 0
level -1
level -2
0 → -1 → -2 → -1 → 0 switching
```

The most important metric is **frame-time stability**, not merely average FPS.

Do not claim performance improvement unless measurements demonstrate it.

If the underground levels contain too little road data for a meaningful benchmark, document that fact and still measure the overhead of selecting the level-aware network.

---

# 26. Things explicitly NOT to implement

Do NOT implement any of the following in Phase 6:

* garage rendering
* garage outlines
* garage entrances
* `parking=entrance`
* ramps
* automatic level changes
* stairs
* elevators
* teleportation
* level transition routing
* multi-level route planning
* underground NPC traffic
* underground pedestrian simulation
* underground train changes
* garage parking behaviour
* automatic parking
* parking-space selection
* geometry-based level inference
* `layer` → `map_level` conversion
* `tunnel` → `map_level` conversion
* `covered` → `map_level` conversion
* new OSM download logic
* level-specific OSM fetching
* loading screens
* unrelated rendering changes

Keep the phase narrowly focused on making the existing driving/road network respect `map_level`.

---

# 27. Code quality requirements

Prefer the smallest architecture change that correctly integrates with the existing code.

Before adding a new class or subsystem, check whether an existing:

* road graph
* spatial index
* routing structure
* world synchronization mechanism
* cache
* grid

can be extended.

Avoid duplicate representations of the same OSM road unless there is a concrete performance reason.

Keep:

```text
Way.map_level
```

as the source of truth.

Do not introduce another independent "road level" field.

Use clear names and comments only where the level semantics are not obvious.

---

# 28. Required implementation workflow

Follow this order:

## Step 1 — Audit

Inspect the existing road/driving/routing architecture.

Identify exactly:

* where surface roads enter the driving system
* where road graphs/indexes are created
* how nearest-road queries work
* how routes are calculated
* how map synchronization triggers rebuilds
* how NPCs consume road data

Do not modify code yet.

## Step 2 — Design

Choose the smallest level-aware extension that fits the existing architecture.

Document the design briefly in code comments or the implementation summary.

## Step 3 — Implement

Implement level-aware road selection and routing.

Preserve the existing surface fast path.

## Step 4 — Integrate

Connect it to existing:

* world synchronization
* tile loading/unloading
* road indexes
* routing
* player movement

## Step 5 — Tests

Add focused tests for all semantics above.

## Step 6 — Benchmark

Run the before/after performance benchmark.

## Step 7 — Review

Search for every existing direct consumer of `world.ways`.

Make sure no important driving/routing path accidentally bypasses the new level filtering.

---

# 29. Final acceptance criteria

Phase 6 is complete only when all of these are true:

* [ ] `map_level` is respected by the driving road network.
* [ ] `map_level=None` means surface level 0.
* [ ] `map_level=0` is usable on level 0.
* [ ] `map_level=-1` is usable only on level -1.
* [ ] `map_level=-2` is usable only on level -2.
* [ ] Positive levels follow the same rule.
* [ ] `layer` remains independent from `map_level`.
* [ ] `layer=-1` does not make a road underground.
* [ ] Off-surface roads accidentally present in `world.ways` are filtered correctly.
* [ ] `world.level_ways` participates in the appropriate driving network.
* [ ] Surface driving remains functionally unchanged.
* [ ] Player level changes select the appropriate road network.
* [ ] Changing level does not reload or fetch map data.
* [ ] No implicit connections exist between different levels.
* [ ] No ramps or level transitions have been implemented.
* [ ] NPCs remain surface-only unless the existing architecture requires a minimal compatibility change.
* [ ] Tile streaming continues to keep hidden level data resident.
* [ ] Existing cache and streaming behaviour remains intact.
* [ ] Automated tests cover the level-selection semantics.
* [ ] Existing test suite passes.
* [ ] Oulu performance benchmarks have been run.
* [ ] No significant regression in surface frame-time stability is introduced.
* [ ] No per-frame full-world road scan has been introduced.

At the end, provide a concise implementation report containing:

1. files changed
2. architecture chosen
3. how level-specific road selection works
4. how `world.ways` and `world.level_ways` are handled
5. routing/player integration
6. tests added and test results
7. benchmark results
8. any remaining limitations

Do not move on to Phase 7 features.
