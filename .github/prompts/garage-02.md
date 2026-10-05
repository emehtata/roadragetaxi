# Road Rage Trip — Import OSM Level and Indoor Metadata

Repository: `emehtata/roadragetaxi`

Branch:

`release/0.15.0alpha`

## Context

The previous parking-garage phases are now implemented.

Commit:

`150a30b`

All 1363 tests pass.

The current architecture contains a single logical map-level model in:

```text
src/theroadragetrip/map_level.py
```

The rule is:

```text
an object with an explicit map_level is visible only when
it matches the player's current map level
```

Objects without an explicit level currently behave as surface-world objects at level `0`.

The player's car now has:

```python
Car.map_level
```

and it is currently always:

```python
0
```

The existing `ParkingGarage.levels` representation is already using the same integer level model.

For example:

```text
0   ground
-1  underground level 1
-2  underground level 2
1+  above-ground levels
```

Important:

```text
OSM layer=* != logical map level
```

`layer=*` is already used for bridge/tunnel vertical ordering and must remain a separate concept.

The render gate has deliberately NOT been implemented yet.

Do not implement it in this task.

---

# Goal

Import the relevant OSM metadata needed to identify level-aware objects.

The goal is to make the world data capable of representing:

```text
OSM object
    |
    +-- map_level
    +-- indoor
```

when the source data explicitly provides that information.

This prepares the architecture for:

* garage internal roads;
* garage entrances;
* indoor areas;
* level-aware rendering;
* underground driving;
* later routing.

Do NOT implement those gameplay features yet.

---

# 1. Inspect the existing implementation first

Before changing anything, inspect:

```text
src/theroadragetrip/map_level.py
src/theroadragetrip/osm/
src/theroadragetrip/osm/build.py
src/theroadragetrip/osm/overpass.py
src/theroadragetrip/osm/bin_source.py
src/theroadragetrip/osm/world_cache.py
```

and the existing data models for:

* `Way`
* roads
* buildings
* scenery
* entrances
* parking garages
* OSM tags
* world cache serialization
* tile streaming.

Also inspect:

```text
tests/test_map_level.py
```

and existing OSM parsing/build tests.

Reuse existing abstractions.

Do not create parallel metadata systems.

---

# 2. Add explicit map-level metadata where OSM provides it

The importer should recognize OSM:

```text
level=*
```

and convert valid values into the existing logical map-level representation.

Examples:

```text
level=-1   -> map_level=-1
level=-2   -> map_level=-2
level=0    -> map_level=0
level=1    -> map_level=1
```

Do not confuse this with:

```text
layer=*
```

Never use `layer=*` as a fallback for `map_level`.

For example:

```text
highway=primary
layer=-1
```

must NOT become:

```text
map_level=-1
```

It remains a surface-level road unless an explicit `level=*` tag says otherwise.

---

# 3. Support common OSM level syntax

OSM level tagging can contain more than a single integer.

Inspect the existing project conventions and implement only syntax that can be represented safely by the current integer `map_level` model.

At minimum support clean integer values:

```text
-2
-1
0
1
2
```

If OSM contains values such as:

```text
-2;-1
```

do NOT silently choose one arbitrary level.

Do not invent semantics.

If the current architecture cannot represent multiple levels on a single object, preserve the raw tag and leave `map_level` unset rather than guessing.

Similarly handle malformed values safely.

Examples:

```text
level=foo
level=1.5
level=-1;0
```

must not crash the importer.

Document the chosen behaviour.

---

# 4. Preserve the raw OSM metadata

Where the existing data model already preserves raw OSM tags, continue doing so.

Do not throw away:

```text
level=*
indoor=*
```

just because the current runtime cannot use all variants yet.

If the project's normal data model stores selected metadata rather than all raw tags, follow that architecture.

Do not introduce a giant arbitrary tag dictionary just for this feature.

---

# 5. Add `indoor=*`

Recognize the OSM:

```text
indoor=*
```

tag.

At minimum preserve whether an object explicitly has an indoor classification.

Examples include:

```text
indoor=yes
indoor=room
indoor=corridor
indoor=area
indoor=parking
indoor=entrance
```

Do not invent new semantics for these values.

For now, the important distinction is simply:

```text
explicit indoor metadata exists
```

versus:

```text
no indoor metadata
```

Keep the original value if that fits the existing data architecture.

---

# 6. Do not infer levels from geometry

This is a strict requirement.

Do NOT do any of the following:

```text
object inside ParkingGarage polygon
    -> assign garage level
```

or:

```text
object near underground garage
    -> assign -1
```

or:

```text
building=parking
    -> assign -1
```

or:

```text
layer=-1
    -> assign map_level=-1
```

The only source for an object's logical map level at this stage is explicit OSM level metadata or an already-existing game-world level assignment.

---

# 7. Garage internal roads

Inspect how the current OSM importer handles:

```text
highway=*
```

inside or near parking facilities.

The goal of this phase is to make explicitly tagged internal garage roads capable of carrying their OSM level metadata.

For example:

```text
highway=service
level=-1
```

should produce a road object with:

```text
map_level=-1
```

if the existing `Way` architecture supports this cleanly.

Do not attempt to determine whether it is actually inside a garage.

Do not perform polygon containment tests.

Do not automatically classify every `highway=service` near a garage as a garage road.

OSM metadata must drive the classification.

---

# 8. Parking garage entrances

Inspect existing support for:

```text
amenity=parking
parking=entrance
```

and related OSM objects.

If entrance objects are already imported, add their explicit:

```text
level=*
indoor=*
```

metadata where appropriate.

If entrance objects are not yet imported, do NOT implement the complete entrance feature in this task.

Instead document what is currently missing.

Do not create fake entrances from garage geometry.

---

# 9. Buildings

Inspect the existing building model.

If buildings can safely carry explicit:

```text
level=*
indoor=*
```

metadata, support it.

However, do not force a new level field onto every building if that would require a large architectural change.

Remember:

```text
building=*
building:levels=*
```

is not equivalent to:

```text
level=*
```

Do not convert:

```text
building:levels=3
```

into:

```text
map_level=3
```

That means the building has three floors, not that the building itself is located on level 3.

---

# 10. Preserve existing ParkingGarage level handling

Do not modify the existing semantics of:

```python
ParkingGarage.levels
```

unless inspection finds an actual bug.

The existing rules remain:

### Underground parking

```text
parking:levels=n
```

means:

```text
-n ... -1
```

when the garage is classified as underground.

### Multi-storey parking

Use the existing implementation's rules.

Do not duplicate this logic elsewhere.

If a shared parsing helper is needed, refactor the existing implementation so both systems use the same parser.

---

# 11. BIN / world-cache compatibility

Inspect how `Way` and related world objects are serialized.

If adding:

```text
map_level
indoor
```

changes the persistent representation, update the relevant:

* BIN/cache format;
* version;
* serializer;
* deserializer;
* compatibility handling.

Follow the existing cache-versioning strategy.

Do not silently load old cached data as if it contained fields that it does not contain.

If the world-cache format already stores enough metadata, reuse it.

---

# 12. Tile streaming

Make sure explicit level metadata survives:

```text
OSM
 -> build
 -> world cache
 -> tile streaming
 -> runtime world object
```

Do not add a separate level-processing pass during streaming.

Level metadata should be created during the existing OSM/build phase.

Runtime tile merging should simply carry the already-parsed value.

---

# 13. Runtime behaviour

Do NOT activate the render gate.

Do NOT change:

```text
main()
renderer
```

to hide level-specific objects yet.

Do NOT change:

```text
Car.map_level
```

from its current default of `0`.

The game should continue rendering exactly as before.

This phase only prepares the data.

---

# 14. Do not change `layer=*`

This is particularly important.

Keep these concepts separate:

```text
layer
```

and:

```text
map_level
```

Examples:

### Tunnel

```text
highway=primary
layer=-1
```

means:

```text
map_level = 0 / unset
layer = -1
```

unless the OSM object ALSO explicitly says:

```text
level=-1
```

### Garage road

```text
highway=service
level=-1
```

means:

```text
map_level=-1
```

It does not necessarily require:

```text
layer=-1
```

### Bridge

```text
highway=primary
layer=1
```

must not become:

```text
map_level=1
```

---

# 15. Parsing helper

If there is no suitable existing helper, create a small focused parser for:

```text
level=*
```

It should:

* accept clean integer levels;
* reject malformed values safely;
* not confuse multi-level syntax with a single level;
* return a representation compatible with `map_level.py`;
* be independently unit tested.

Keep it small.

Do not build a complete generic OSM level-expression parser unless the existing data actually requires it.

---

# 16. Tests

Add focused tests.

At minimum:

### Explicit negative level

```text
level=-1
=> map_level == -1
```

### Explicit positive level

```text
level=2
=> map_level == 2
```

### Ground level

```text
level=0
=> map_level == 0
```

### No level

```text
no level tag
=> map_level is unset/default
```

### Layer must not become map level

```text
layer=-1
no level
=> map_level remains unset/default
```

### Both layer and level

```text
layer=-1
level=-2
=> layer remains -1
=> map_level == -2
```

### Invalid level

```text
level=foo
=> importer does not crash
=> map_level remains unset/default
```

### Multiple levels

For example:

```text
level=-2;-1
```

must follow the documented safe behaviour.

Do not silently choose one value.

### Indoor

Test representative values such as:

```text
indoor=yes
indoor=parking
indoor=corridor
```

according to the chosen representation.

### Garage road

A synthetic:

```text
highway=service
level=-1
```

must retain:

```text
map_level=-1
```

without requiring polygon containment.

---

# 17. Real OSM test data

If the repository already contains OSM fixtures containing:

```text
level=*
indoor=*
```

use them.

If not, create minimal synthetic OSM fixtures following the project's existing fixture conventions.

Do not add large external datasets merely for this feature.

---

# 18. Performance requirements

This feature must not add meaningful per-frame cost.

All parsing must happen during:

```text
OSM import/build/cache construction
```

not during rendering.

Runtime objects should already contain their parsed level.

Do not:

* parse tags every frame;
* inspect OSM tags during rendering;
* scan garages every frame;
* perform geometry containment every frame;
* perform network requests;
* rebuild spatial grids because of level metadata.

The current render code should remain unchanged.

---

# 19. Documentation

Update:

```text
docs/parking-garages.md
```

with a concise section describing:

* `ParkingGarage.levels`;
* `map_level`;
* OSM `level=*`;
* OSM `indoor=*`;
* OSM `layer=*`;
* the fact that `layer` and `map_level` are separate;
* that level-aware rendering is not yet active;
* that garage internal roads are only level-aware when OSM explicitly provides `level=*`.

Do not document features that are not actually implemented.

---

# 20. Acceptance criteria

The task is complete when:

* OSM `level=*` can be imported into the existing `map_level` concept.
* OSM `indoor=*` metadata is preserved where appropriate.
* `layer=*` remains completely separate.
* No level is inferred from garage geometry.
* `ParkingGarage.levels` remains the single garage-level representation.
* Explicitly tagged garage/internal roads can carry `map_level`.
* Invalid level values cannot crash the importer.
* Multi-level expressions are handled conservatively.
* Cache/BIN compatibility is correctly handled if required.
* Tile streaming preserves level metadata.
* `Car.map_level` remains `0`.
* Rendering behaviour remains unchanged.
* No render gate is implemented.
* No gameplay/routing changes are made.
* All existing tests continue to pass.
* New tests cover level parsing and `layer`/`level` separation.

At the end, report:

1. Files changed.
2. New OSM metadata fields.
3. How `level=*` is parsed.
4. How `indoor=*` is represented.
5. How `layer=*` remains separate.
6. Cache/BIN changes.
7. Tests added and total test count.
8. Any OSM cases deliberately left unsupported.
9. Confirmation that the render path was not changed.
10. Any performance impact observed.
