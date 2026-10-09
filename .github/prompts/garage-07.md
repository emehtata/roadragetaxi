# Road Rage Trip — Phase 8: Parking Entrances and Level Connectors

You are working on the `Road Rage Trip` repository.

**Branch:** `release/0.15.0alpha`

This is **Phase 8** of the parking-garage / map-level implementation.

Phases 1–7 have established:

* `ParkingGarage` data imported from OSM
* one shared `map_level` model
* `Way.map_level`
* `Building.map_level`
* `Car.map_level`
* level-aware rendering
* level-aware driving networks
* level-aware collision/environment queries

This phase introduces the **data model for connections between map levels**.

It does **not** implement actual level changes yet.

---

# 1. Objective

Inspect the actual OSM data and repository architecture and add a representation for explicit connections between map levels.

The purpose is to prepare the game for a later phase where the player can actually drive through a garage entrance/ramp and transition between:

```text
level 0 ↔ level -1
level -1 ↔ level -2
...
```

This phase must only establish reliable connector data.

After this phase the game should know:

```text
"There is an OSM-defined connector here."

"It connects these logical map levels."

"It has this position/geometry/type."

```

But the player must **not yet be able to use it automatically**.

---

# 2. Hard scope boundary

This phase is deliberately data-only.

Do NOT implement:

* automatic level changes
* driving through connectors
* connector collision
* connector routing
* cross-level route planning
* player teleportation
* player snapping
* ramps as special physics surfaces
* speed changes on ramps
* NPC level transitions
* pedestrian level transitions
* garage parking behaviour
* garage entrance rendering
* garage interior generation
* inferred level transitions

Phase 9 will handle actual transition behaviour.

---

# 3. First task: audit the repository

Before writing code, inspect the existing implementation.

In particular inspect:

```text
osm/models.py
osm/build.py
osm/parking.py
osm/pbf_source.py
osm/overpass.py
world cache implementation
tile streaming
Way
ParkingGarage
map_level.py
LevelRoadNetworks
```

Also search for existing handling of:

```text
entrance
parking=entrance
amenity=parking_entrance
parking_entrance
level
level:ref
highway=service
highway=track
highway=footway
ramp
ramp=* 
building_passage
indoor
```

Do not assume that OSM uses one universal tagging scheme.

The actual repository and Oulu data must determine what is supported.

---

# 4. Inspect real Oulu OSM data

Before defining the final connector model, investigate the existing Oulu data.

Determine whether the local PBF/cache contains objects such as:

```text
parking=entrance
amenity=parking_entrance
entrance=*
level=*
level:ref=*
highway=service
highway=track
highway=footway
tunnel=*
covered=*
building_passage
```

Look for examples around the already imported `ParkingGarage` records.

Document what tagging patterns actually exist.

Do not build a complicated generalized OSM connector model based purely on hypothetical tags that do not occur in the project's data.

---

# 5. Important level semantics

The existing map-level rules remain authoritative.

A logical map level is:

```text
0   surface
-1  underground
-2  deeper underground
+1  above surface
...
```

`map_level=None` means logical level 0.

Only explicit clean `level=*` values create non-surface levels.

Do not infer a level from:

```text
layer
tunnel
covered
geometry
building membership
garage membership
```

This rule also applies to connectors.

---

# 6. Proposed connector model

Inspect the existing models and introduce the smallest appropriate model.

A conceptual model could look like:

```python
ParkingLevelConnector
```

with fields equivalent to:

```text
osm_type
osm_id

connector_type

position / geometry

from_level
to_level

raw_level
raw_level_ref

garage_osm_id
```

However:

> Do not blindly implement these exact fields.

Use the repository's existing model conventions and only store information that can be supported by actual OSM data.

The model must have a stable OSM identity.

For example:

```text
osm_type = "node"
osm_id = 12345
```

or:

```text
osm_type = "way"
osm_id = 67890
```

---

# 7. Connector types

Use a small, explicit vocabulary.

At minimum distinguish the source type where it is known.

Possible examples:

```text
parking_entrance
ramp
building_passage
other
```

Do not invent dozens of connector categories.

The important distinction for Phase 8 is:

```text
what kind of OSM object says there is a possible connection?
```

not how the vehicle will behave on it.

If the repository's data only supports one or two categories, keep the model correspondingly small.

---

# 8. `from_level` and `to_level`

This is the most important design issue in this phase.

Do not invent `from_level` / `to_level` values unless OSM data explicitly provides enough information to justify them.

For example, if an object has:

```text
level=-1
```

that does NOT automatically prove:

```text
from_level=0
to_level=-1
```

It may indicate the level on which the entrance is located rather than the level it connects to.

Likewise:

```text
layer=-1
```

does not establish a map-level connection.

Therefore distinguish between:

```text
known connection
```

and:

```text
candidate connector
```

If the OSM tags only identify an entrance but do not identify both connected levels, preserve that uncertainty in the model.

Do not fabricate the missing level.

---

# 9. Represent incomplete connector information safely

If an OSM object clearly represents a parking entrance but only one level is known, the model may contain:

```text
from_level = None
to_level = -1
```

or an equivalent representation.

The exact direction is not important yet.

What is important is:

> Never pretend that the unknown side is level 0 merely because the entrance is near the surface.

The later transition phase can resolve or reject incomplete connectors using stronger evidence.

---

# 10. Level references

Inspect and support relevant explicit tags where appropriate.

Potential examples:

```text
level=*
level:ref=*
```

But preserve the raw values.

If a value is:

```text
0;1
```

or:

```text
-1;0
```

do not force it through the existing single-integer `parse_map_level()` function if that function is intentionally limited to one clean level.

Instead, determine whether the connector model needs a separate representation for multiple levels.

Do not modify `parse_map_level()` globally just to make connectors accept complex values.

That function already defines the semantics for `Way.map_level` and `Building.map_level`.

---

# 11. Directionality

Do not assume that a connector has a driving direction.

OSM entrance/ramp data may contain directional information, but Phase 8 should only preserve it if it is explicitly represented and useful later.

If the existing OSM object is bidirectional or direction is unknown, retain that fact.

Do not invent:

```text
one-way
entry-only
exit-only
```

behaviour.

Actual driving direction belongs to the later transition/routing phase.

---

# 12. Geometry

Preserve the source geometry where useful.

For a node connector:

```text
single position
```

For a way connector:

```text
ordered points / geometry
```

Do not turn a connector into a road.

Do not add it to:

```text
world.ways
world.level_ways
LevelRoadNetworks
```

in this phase.

A connector is **metadata about a possible relationship between levels**, not yet a drivable road.

---

# 13. Do not create fake roads

This is a hard requirement.

Given:

```text
ParkingLevelConnector
```

do NOT generate:

```text
Way
```

or:

```text
level road
```

from it.

For example, if OSM contains:

```text
parking=entrance
```

but no explicit connecting road, the game must not create one.

The connector only records what OSM explicitly tells us.

---

# 14. Relation to `ParkingGarage`

A connector may be associated with a `ParkingGarage` if OSM provides a reliable relationship.

Possible evidence includes:

* relation membership
* explicit identifiers
* direct source relationship
* a clearly defined existing OSM association

Do NOT associate a connector with the nearest garage merely because its coordinates happen to be close.

Do not perform:

```text
nearest garage polygon
    ↓
assign connector
```

as an inferred relationship.

If no reliable relationship exists:

```text
garage_osm_id = None
```

is preferable.

---

# 15. Do not infer levels from garage geometry

This is particularly important.

Given:

```text
ParkingGarage
    levels=(-3, -2, -1)

ParkingLevelConnector
    position inside garage polygon
```

do NOT conclude:

```text
connector connects -1 to -2
```

or:

```text
connector connects 0 to -1
```

unless the OSM data explicitly supports that conclusion.

The garage's `levels` describe available garage levels.

They do not describe the level of every object inside the polygon.

---

# 16. Candidate connectors vs confirmed connectors

Consider distinguishing:

```text
confirmed connector
```

from:

```text
candidate connector
```

if the OSM data requires it.

For example:

```text
parking=entrance
level=-1
```

may clearly identify a garage entrance but not explicitly identify the other connected level.

In that case the object can safely be stored as a connector candidate with:

```text
known level = -1
other level = unknown
```

The later transition phase can decide whether it is usable.

Do not discard useful OSM information merely because the transition cannot yet be proven.

---

# 17. World storage

Add a world collection following the existing patterns.

Conceptually:

```python
world.parking_level_connectors
```

or another repository-consistent name.

It must:

* exist on the world
* contain imported connector records
* survive map synchronization
* be deduplicated by OSM identity
* be unloaded with the appropriate tile
* remain available regardless of current `Car.map_level`

Do not make connector residency depend on the current level.

---

# 18. Tile streaming

Integrate connectors into the existing `AutoFetchManager` world-section architecture.

When a tile is loaded:

```text
connector objects
```

should arrive through the same map-data pipeline.

When the tile is unloaded:

```text
connector objects
```

must leave with it.

Do not add a separate connector-specific fetcher.

Do not make level switching trigger connector fetching.

---

# 19. World cache

Persist connector data in the existing world cache.

Follow the existing `.rwc` schema/versioning approach.

If a cache-format change is necessary:

* increment the cache format version according to existing conventions
* make older caches fail/rebuild safely
* do not silently interpret an old cache as containing connectors

Store only the information needed to reconstruct the connector model.

Do not duplicate raw OSM payloads.

---

# 20. Overpass / PBF import

If the current local PBF pipeline already provides the necessary objects, reuse it.

If Overpass needs an additional query for connector nodes/ways, add the smallest appropriate query.

Do not introduce a separate connector-specific OSM import pipeline.

The same source should work for:

```text
local PBF
Overpass
world cache
tile streaming
```

where applicable.

---

# 21. Multipolygon / relation handling

Inspect whether connector-like objects can occur in relations.

Do not assume every connector is a node.

Support:

* node
* way
* relation

only if the actual OSM representation and existing parser architecture require it.

Do not add generic relation handling merely for completeness.

If a relation is encountered and cannot be interpreted safely, preserve existing behaviour and document the limitation.

---

# 22. Spatial index

Do NOT add a spatial index yet unless the existing architecture makes it effectively free and clearly appropriate.

Phase 8 only establishes the connector data.

The later transition phase may need queries such as:

```text
nearest connector
connector at current road
connector near vehicle
```

Do not optimize those prematurely.

If Oulu contains only a small number of connectors, a normal world collection is sufficient for this phase.

---

# 23. Rendering

Do not render connectors in the normal game.

No:

* entrance markers
* arrows
* ramps
* debug graphics

are required by default.

If the repository already has a debug OSM overlay, you may expose connector information there **only if it is trivial and does not affect normal rendering**.

Do not introduce a new per-frame rendering system.

---

# 24. Driving and routing

Do not connect connectors to the driving graph yet.

The following must remain true:

```text
level 0 road graph
    X
level -1 road graph
```

There is still no route between them.

A connector may exist physically at the boundary, but:

```text
route(level 0 → level -1)
```

must still fail exactly as it did before Phase 8.

Do not modify `LevelRoadNetworks` to create cross-level edges.

---

# 25. Collision

Do not make connectors collidable.

Do not create invisible walls around garage entrances.

Do not create special ramp collision geometry.

Existing Phase 7 collision behaviour remains unchanged.

---

# 26. Player behaviour

`Car.map_level` must remain unchanged by connector proximity.

Driving near:

```text
parking=entrance
```

must NOT automatically change:

```python
car.map_level
```

The player can pass the connector exactly as before.

Phase 8 must have zero gameplay effect.

---

# 27. NPCs and pedestrians

Do not use connector data for:

* NPC routing
* NPC traffic
* pedestrian routing
* pedestrian level transitions

They remain surface-only.

---

# 28. Tests

Add focused tests for the connector data model and import.

At minimum cover:

## Basic connector

A valid connector object preserves:

```text
osm_type
osm_id
type
position/geometry
```

## Explicit level

If an OSM connector has a clean:

```text
level=-1
```

the known level is preserved as `-1`.

## Complex level

Values such as:

```text
0;1
-1;0
0-1
```

must not be incorrectly converted into a single level.

## Unknown level

A connector without explicit level information must retain:

```text
unknown
```

rather than assuming surface.

## Layer independence

```text
layer=-1
```

must not become:

```text
map_level=-1
```

## Garage association

A connector is associated with a garage only when there is explicit/reliable OSM evidence.

## No geometry inference

A connector inside a garage polygon must not automatically inherit the garage's level.

## Identity

Two records with the same:

```text
osm_type + osm_id
```

must deduplicate correctly.

## Tile lifecycle

Load/unload/sync must correctly add/remove connectors.

## Cache round-trip

Connector data written to the world cache must load back with equivalent information.

---

# 29. Real-data tests

Use the actual Oulu dataset where possible.

Report:

* number of connector candidates
* number of confirmed connectors, if the implementation distinguishes them
* connector types
* known/unknown levels
* number associated with garages
* number with incomplete level information

Do not invent or hard-code expected counts.

The counts are diagnostic and may change with OSM data.

---

# 30. Performance

Connector import must not add noticeable per-frame cost.

There should be:

```text
no connector scan every frame
no connector collision checks
no connector routing
no connector rendering
```

If the connector collection is small, keeping it as a normal world collection is acceptable.

Measure startup/map-sync impact if the repository already has suitable benchmarks.

---

# 31. Cache and compatibility

Check all relevant cache versions and serializers.

Ensure:

```text
old cache
    → safely rebuilt

new cache
    → connector records restored

tile streaming
    → connector records preserved

map sync
    → connector collection updated
```

Do not break existing caches silently.

---

# 32. Search for future integration points

At the end of implementation, identify where Phase 9 will need to integrate.

Document:

```text
connector discovery
connector → road association
from/to level resolution
player proximity detection
transition state
level change
```

But do not implement them yet.

This should give Phase 9 a clear integration point.

---

# 33. Required implementation workflow

Follow this order.

## Step 1 — Audit

Inspect:

* OSM import
* local PBF handling
* Overpass queries
* `ParkingGarage`
* `Way`
* `map_level`
* world cache
* tile streaming
* existing OSM entrance/ramp handling

## Step 2 — Inspect real Oulu data

Find actual connector examples and determine which tags are usable.

## Step 3 — Design

Define the smallest connector model supported by the real data.

Do not over-generalize.

## Step 4 — Implement model

Add the connector representation using repository conventions.

## Step 5 — Import

Integrate it into the existing OSM/PBF/Overpass build pipeline.

## Step 6 — World/cache integration

Add world storage, cache persistence, tile streaming and synchronization.

## Step 7 — Tests

Add focused unit/integration tests.

## Step 8 — Real-data validation

Run the importer against the Oulu data and report actual connector statistics.

## Step 9 — Regression

Run the complete test suite.

## Step 10 — Review

Verify that Phase 8 has **zero gameplay effect**.

---

# 34. Things explicitly NOT to implement

Do NOT implement:

* automatic level changes
* level transition state machines
* ramp driving
* cross-level route graphs
* cross-level routing
* connector collision
* connector physics
* connector rendering
* garage entrance animation
* NPC transitions
* pedestrian transitions
* garage parking
* parking-space selection
* geometry-based level inference
* garage-polygon level inference
* `layer` → `map_level`
* `tunnel` → `map_level`
* `covered` → `map_level`
* fake roads
* fake level connectors
* level-specific OSM fetching
* level-specific tile streaming
* loading screens
* unrelated rendering changes

---

# 35. Acceptance criteria

Phase 8 is complete only when:

* [ ] The actual OSM representation of parking/level connectors has been investigated.
* [ ] A minimal connector data model exists.
* [ ] Connector records have stable OSM identity.
* [ ] Explicit connector geometry/position is preserved.
* [ ] Explicit level information is preserved without inventing missing levels.
* [ ] Complex level values are not incorrectly reduced to one level.
* [ ] `layer` remains independent from `map_level`.
* [ ] No level is inferred from garage geometry.
* [ ] No level is inferred from tunnel/covered/layer.
* [ ] Connector records are stored in the world.
* [ ] Connector records survive world-cache round trips.
* [ ] Connector records participate in tile streaming.
* [ ] Connector records are correctly removed when their tile unloads.
* [ ] Connector records are deduplicated by OSM identity.
* [ ] No connector is added to `world.ways`.
* [ ] No connector is added to `world.level_ways`.
* [ ] No cross-level route exists.
* [ ] `Car.map_level` is never changed by connector proximity.
* [ ] Connectors have no normal rendering.
* [ ] Connectors have no collision behaviour.
* [ ] NPC and pedestrian behaviour is unchanged.
* [ ] No per-frame connector processing is introduced.
* [ ] Focused tests pass.
* [ ] Full existing test suite passes.
* [ ] Oulu real-data statistics have been collected.
* [ ] Existing Phase 6/7 performance remains intact.

---

# 36. Final implementation report

Provide a concise final report containing:

1. files changed
2. actual OSM connector tagging patterns found
3. connector model and fields
4. how levels are represented
5. how incomplete/ambiguous connectors are represented
6. garage association rules
7. world/cache integration
8. tile-streaming integration
9. Oulu connector statistics
10. tests added and results
11. full test-suite result
12. performance/startup impact
13. exact integration point prepared for Phase 9
14. remaining limitations

Clearly distinguish:

```text
implemented in Phase 8
```

from:

```text
intentionally deferred to Phase 9
```

The final implementation must leave actual gameplay behaviour unchanged.
