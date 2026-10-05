# Road Rage Trip — Add OSM-Defined Parking Garage Data

Repository: `emehtata/roadragetaxi`

Branch:

`release/0.15.0alpha`

## Goal

Implement the **first phase of underground and multi-storey parking garage support**.

This phase is strictly about **discovering, importing, representing and caching parking garages from OSM data**.

Do **not** implement driving inside garages, underground rendering, routing through garages, NPC parking behaviour, or gameplay integration yet.

The goal is to create a reliable data foundation that later phases can use.

The implementation must fit the existing OSM → PBF → BIN → runtime architecture and must not introduce noticeable runtime performance overhead.

---

# 1. Inspect the existing architecture first

Before making changes, inspect the current implementation thoroughly.

Pay particular attention to:

* OSM/PBF import code
* OSM XML parsing
* existing OSM element classification
* road/way representation
* node representation
* BIN serialization/deserialization
* city-specific BIN handling
* world cache
* `AutoFetchManager`
* existing OSM object models
* existing building/parking representations
* existing tests

Relevant areas are likely under:

```text
src/theroadragetrip/osm/
```

but do not assume the exact implementation.

Search the repository for existing handling of:

```text
amenity=parking
parking=
building=parking
parking:levels
building:levels
building:levels:underground
level=
indoor=
highway=service
parking=entrance
```

Reuse existing parsing and serialization infrastructure wherever possible.

Do not create a parallel OSM import pipeline.

---

# 2. Identify parking garages from OSM

Add support for identifying parking garages using documented OSM tagging patterns.

At minimum investigate and support:

```text
amenity=parking
parking=underground
parking=multi-storey
building=parking
```

Also inspect and preserve useful related tags such as:

```text
parking:levels
building:levels
building:levels:underground
name
operator
access
fee
capacity
maxheight
maxweight
opening_hours
covered
lit
surface
```

Do not assume that every tag will exist.

OSM data is incomplete and inconsistent.

The parser must therefore tolerate missing or contradictory tags.

---

# 3. Distinguish a garage from an ordinary parking area

Do not classify every:

```text
amenity=parking
```

as an underground garage.

Create a clear classification.

For example, conceptually:

```python
ParkingFacilityType.SURFACE
ParkingFacilityType.UNDERGROUND
ParkingFacilityType.MULTI_STOREY
ParkingFacilityType.UNKNOWN
```

The exact naming should follow the project's existing conventions.

Possible examples:

```text
amenity=parking
parking=surface
    -> SURFACE

amenity=parking
parking=underground
    -> UNDERGROUND

amenity=parking
parking=multi-storey
    -> MULTI_STOREY

building=parking
    -> investigate tags and classify appropriately
```

Do not invent an underground classification merely because a parking polygon happens to overlap a building.

---

# 4. Create a dedicated parking garage data model

Introduce a dedicated representation for a parking garage/facility if the existing architecture does not already have an appropriate model.

The model should contain only information that can actually be derived from OSM.

Conceptually:

```python
ParkingGarage
    id
    osm_id
    garage_type
    geometry
    center
    levels
    underground_levels
    capacity
    name
    operator
    access
    fee
    maxheight
    maxweight
    opening_hours
    covered
    source
```

Do not copy this structure blindly.

First inspect the project's existing object model and use its conventions.

Important:

**Do not store unnecessary duplicated geometry or metadata.**

The data model should remain compact because thousands of parking facilities may eventually be loaded.

---

# 5. Preserve OSM identity

Every imported garage must retain enough information to trace it back to OSM.

At minimum preserve:

```text
OSM element type
OSM element ID
```

For example:

```text
way/123456789
relation/987654321
```

Use the existing OSM identity conventions in the project.

This will be important later for:

* debugging;
* cache invalidation;
* BIN regeneration;
* diagnostics;
* future map updates.

---

# 6. Geometry

Determine how parking garage geometry is currently represented in the project.

If the OSM object is a polygon:

* preserve its geometry using the existing geometry representation;
* calculate a useful center/anchor using the existing geometry utilities;
* do not introduce a second geometry system.

The geometry must be sufficient for future phases to determine:

* garage location;
* approximate entrance locations;
* relationship to nearby roads;
* underground rendering area.

However, **do not implement entrance detection or road connectivity yet** unless it is already naturally available from the existing imported OSM data.

---

# 7. Parking levels

Support the common level-related tags where available.

Investigate:

```text
parking:levels=*
building:levels=*
building:levels:underground=*
```

The parser must distinguish between:

* total above-ground levels;
* underground levels;
* parking-specific levels.

Do not make assumptions such as:

```text
building:levels=5
=> 5 parking levels
```

unless OSM explicitly indicates that the building is a parking structure and the interpretation is justified.

Use a conservative interpretation.

For example:

```text
parking:levels=3
```

may indicate three parking levels.

Where:

```text
building:levels=5
building:levels:underground=2
```

is present, preserve both pieces of information rather than collapsing them into one number.

---

# 8. Level representation

Introduce a representation that can later support multi-level road networks.

For example:

```python
GarageLevel
    level
    source
```

Potential levels might be:

```text
-2
-1
0
1
2
```

Do not implement 3D coordinates or a 3D renderer.

This is purely a logical map-level concept for now.

The important requirement is that the representation must allow later phases to distinguish:

```text
surface road
garage level -1
garage level -2
```

even if they share the same X/Y area.

---

# 9. OSM relations

Investigate whether parking garages can be represented by relations in the current dataset.

Do not assume that every garage is a single way.

If relations are already parsed by the existing OSM importer, determine whether parking-related relations need to be supported.

If relation support is required:

* reuse the existing relation infrastructure;
* do not create a garage-specific relation parser.

If reliable relation interpretation cannot be implemented safely in this phase, document the limitation rather than inventing geometry.

---

# 10. BIN format

The parking garage information must survive the existing PBF → BIN conversion.

Inspect the current BIN format and versioning mechanism.

Extend the BIN representation using the project's existing serialization approach.

Requirements:

* old BIN files must not silently deserialize incorrectly;
* use the existing BIN versioning strategy;
* if the format requires a version bump, implement it correctly;
* loading a BIN without garage data should remain supported if practical;
* do not break existing road/building/POI data.

Do not introduce JSON sidecar files unless the existing architecture specifically calls for them.

The goal is for parking garages to become first-class data in the existing BIN.

---

# 11. World cache integration

Inspect `WorldCacheManager`.

Parking garage data should be included in the cached world representation.

A cached garage should be available without requiring another network request.

The intended flow is:

```text
OSM/PBF
   |
   v
parse garage
   |
   v
BIN
   |
   v
WorldCacheManager
   |
   v
runtime ParkingGarage objects
```

Do not introduce a second cache.

---

# 12. Runtime integration

Add the minimum runtime support necessary to expose imported garages to the game.

For now, this should mean something similar to:

```python
world.parking_garages
```

or whatever naming fits the current architecture.

The collection should support efficient spatial access if the project already has a spatial indexing mechanism.

Do not perform expensive garage searches every frame.

Do not add per-frame processing merely because garage support exists.

---

# 13. Spatial indexing

Investigate the project's existing spatial grids/indexes.

If there is already a suitable spatial index:

* integrate garages into it where appropriate.

If there is no suitable index:

* do not build a complicated new indexing system in this phase.

A future phase will need efficient queries such as:

```text
garages near player
garages near road
garages near taxi destination
```

Prepare the data model for this, but do not prematurely implement a large spatial-index subsystem.

---

# 14. Rendering

Add only **debug visualization**, not final underground rendering.

If the project already has debug rendering facilities, add an optional debug visualization showing:

* garage polygon;
* garage center;
* garage type;
* garage ID;
* number of known levels.

For example:

```text
┌──────────────────────┐
│  PARKING GARAGE      │
│  underground         │
│  levels: -2,-1       │
│                      │
│          ●           │
└──────────────────────┘
```

Do not add permanent visible garage graphics to the game yet.

Debug rendering must be disabled by default.

It must not affect normal gameplay performance.

---

# 15. Performance requirements

Performance is a first-class requirement.

The addition of parking garage support must not noticeably affect:

* game startup;
* normal game loop;
* rendering;
* NPC simulation;
* pedestrian simulation;
* road processing;
* tile streaming.

Specifically:

* Do not scan all garages every frame.
* Do not scan all OSM objects every frame.
* Do not calculate garage geometry every frame.
* Do not rebuild garage data when the player moves.
* Do not add expensive runtime geometry processing.
* Keep garage objects compact.
* Parse and construct garage data during the existing background/import pipeline where appropriate.
* Preserve the existing incremental tile streaming architecture.

If parking garages are loaded as part of a streamed tile, their integration must respect the existing streaming/integration budget.

A large number of garages must not create a frame-time spike.

---

# 16. Tests

Add comprehensive tests following the project's existing test conventions.

At minimum test:

### Classification

```text
amenity=parking + parking=underground
amenity=parking + parking=multi-storey
amenity=parking + parking=surface
building=parking
```

### Metadata

Test parsing of:

```text
parking:levels
building:levels
building:levels:underground
capacity
name
operator
access
fee
maxheight
```

including missing values.

### Geometry

Verify:

* polygon parsing;
* center calculation;
* malformed/incomplete geometry handling.

### OSM identity

Verify preservation of:

* element type;
* OSM ID.

### BIN

Verify:

```text
PBF -> BIN -> load BIN
```

preserves garage data.

### Cache

Verify cached garage data can be loaded without network access.

### Runtime

Verify imported garages appear in the runtime world representation.

### Backward compatibility

Verify existing BIN/world data without parking garage records still loads correctly where supported by the existing versioning strategy.

---

# 17. Real OSM examples

Use existing test fixtures where available.

If the repository already contains real OSM/PBF test data, use it.

Otherwise create small synthetic OSM fixtures representing realistic combinations such as:

```text
amenity=parking
parking=underground
parking:levels=2
```

and:

```text
amenity=parking
parking=multi-storey
building:levels=5
building:levels:underground=1
```

Do not depend on live Overpass queries for unit tests.

Tests must be deterministic and offline.

---

# 18. Do not implement these yet

Explicitly do NOT implement:

* driving inside parking garages;
* underground rendering;
* camera changes;
* garage entrances as driveable graph connections;
* A* routing through garages;
* NPC parking;
* automatic parking;
* parking space reservation;
* collision changes;
* garage lighting;
* 3D underground geometry;
* garage-specific traffic simulation.

Those belong to later phases.

This phase is about creating a **correct and efficient OSM data foundation**.

---

# 19. Documentation

Document:

1. Which OSM tags are recognized.
2. How parking facilities are classified.
3. How parking levels are represented.
4. How garage geometry is stored.
5. How garage data is serialized into BIN.
6. How garage data reaches the runtime world.
7. What OSM mapping cases are currently unsupported.
8. What assumptions are deliberately NOT made.

Keep the documentation concise and factual.

---

# 20. Acceptance criteria

The implementation is complete when:

* OSM-defined underground parking garages can be detected.
* Multi-storey parking structures can be detected.
* Ordinary surface parking is not incorrectly classified as underground.
* Relevant OSM metadata is preserved.
* Garage geometry is preserved.
* Level information is preserved where OSM provides it.
* OSM identity is preserved.
* Garage data survives PBF → BIN → runtime loading.
* World cache supports the new data.
* Existing BIN/world functionality continues to work.
* Tests cover the new functionality.
* No network access is required by tests.
* No significant runtime FPS or frame-time regression is introduced.
* Normal gameplay remains unchanged.

At the end, provide a concise implementation report containing:

* files changed;
* new data structures;
* recognized OSM tags;
* BIN format changes;
* cache changes;
* tests added;
* test results;
* performance impact;
* known OSM mapping limitations.

Do not proceed to underground driving or routing in this task. The output of this phase should be a clean, reliable **ParkingGarage data layer** ready for the next development phase.
