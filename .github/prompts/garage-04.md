# Road Rage Trip — Implement the Map-Level Render Gate

Repository:

`emehtata/roadragetaxi`

Branch:

`release/0.15.0alpha`

## Context

The parking-garage and map-level data layers are now implemented.

Current architecture:

```text
ParkingGarage.levels
        |
        v
logical map levels
        |
        +-- OSM level=* -> Way.map_level
        |
        +-- OSM level=* -> Building.map_level
        |
        +-- Car.map_level
```

The level model is:

```text
0       surface / ground
-1      underground level 1
-2      underground level 2
+1      elevated level 1
...
```

`layer=*` is completely separate and must remain so.

The current player's:

```python
Car.map_level
```

is always `0`.

---

# Current underground-road architecture

Underground-looking roads that should not enter the normal surface road network are now handled separately.

A road is considered underground-looking when it has characteristics such as:

```text
level < 0
location=underground
parking=underground
parking=multi-storey
parking=sheds
parking=carports
covered=yes
covered=arcade
tunnel=yes
tunnel=building_passage
```

If such a road has a clean explicit:

```text
level=*
```

it is retained in:

```python
world.level_ways
```

with:

```python
way.map_level
```

instead of being inserted into the normal:

```python
world.ways
```

The current implementation reports:

* world-cache format 20;
* `level_ways` survives cache loading;
* `level_ways` survives tile streaming;
* 21 such roads exist in Oulu;
* they are mostly garage driveways at levels `-4` through `0`.

These roads are currently **not rendered and cannot be driven on**.

That is intentional until this task.

---

# Goal

Implement the first real **map-level render gate**.

The goal is:

```text
current_map_level = 0
    -> render surface-level world

current_map_level = -1
    -> render level -1 world
    -> do not render level 0 world roads/buildings/scenery

current_map_level = -2
    -> render level -2 world
    -> do not render level 0 or -1 world content
```

The implementation must preserve the current surface rendering behaviour when:

```text
Car.map_level == 0
```

and must not introduce significant frame-time overhead.

---

# 1. Inspect the actual renderer first

Before changing code, inspect the complete rendering path.

In particular identify:

* the world-render section of `main()`;
* road rendering;
* building rendering;
* scenery rendering;
* pedestrians;
* vehicles;
* trains;
* player vehicle;
* shadows;
* lighting;
* weather;
* debug HUD;
* camera rendering;
* tile/spatial culling;
* any cached visible-object lists.

Do not assume that all world objects are rendered from one list.

The existing architecture must determine where the gate belongs.

---

# 2. Important architectural rule

The render gate must distinguish between:

```text
world data residency
```

and:

```text
world visibility
```

Tile streaming must continue to keep data loaded even when it belongs to another map level.

Do NOT unload:

```text
level -1
```

when the player is on:

```text
level 0
```

and vice versa.

The render gate controls visibility only.

---

# 3. Existing data sources

The renderer currently has at least two relevant road collections:

```python
world.ways
world.level_ways
```

Understand exactly what each contains before modifying the renderer.

The intended conceptual result is:

```text
surface/current-level world
    |
    +-- normal world.ways
    |
    +-- appropriate level_ways
```

Do not blindly concatenate the two lists every frame.

Use the existing culling architecture.

---

# 4. Surface level must remain the fast/default path

This is critical.

When:

```python
Car.map_level == 0
```

the game should behave as it does today.

Existing surface roads, buildings, scenery and other world objects must continue rendering.

Do not force every existing object through an expensive generic level-checking function if a cheaper surface path is possible.

Prefer:

```text
level 0
    -> existing render path
    + level_0 additions where required
```

rather than rewriting the entire renderer around level checks.

---

# 5. Render level-specific roads

When:

```python
Car.map_level != 0
```

the renderer must be able to display the appropriate entries from:

```python
world.level_ways
```

For example:

```text
world.level_ways:
    Way(map_level=-4)
    Way(map_level=-2)
    Way(map_level=-1)
    Way(map_level=0)
```

At:

```text
current level = -1
```

only:

```text
map_level=-1
```

is eligible.

At:

```text
current level = -2
```

only:

```text
map_level=-2
```

is eligible.

Do not render `-1` and `-2` simultaneously.

---

# 6. Handle level 0 correctly

This is an important edge case.

The current import pipeline allows a covered/underground-looking road with:

```text
level=0
```

to end up in:

```python
world.level_ways
```

The render gate must therefore treat:

```text
map_level=0
```

as the surface level.

It must not be permanently hidden merely because the object lives in `level_ways`.

At level 0, it must be eligible for rendering.

If the existing surface `ways` collection already contains an equivalent object, avoid double rendering.

Use the existing OSM identity/deduplication mechanisms.

---

# 7. `service=parking_aisle`

There is an existing special case:

```text
service=parking_aisle
```

These roads currently remain in:

```python
world.ways
```

even when:

```text
level=-1
```

Do not break this existing import rule accidentally.

However, the render gate must respect their:

```python
way.map_level
```

when it is present.

For example:

```text
parking_aisle
level=-1
```

must eventually behave as a level -1 road.

It must not continue rendering on the surface merely because it happens to be stored in `world.ways`.

If necessary, modify the render selection rather than changing the import rule in this task.

---

# 8. Existing objects with `map_level=None`

The established visibility semantics are:

```text
map_level is None
    -> surface world
```

Therefore:

```text
current_map_level == 0
```

means these objects are visible.

At:

```text
current_map_level == -1
```

they are not visible as world-level objects.

Do not change this semantic.

This includes existing roads/buildings/scenery that have no explicit OSM `level=*`.

---

# 9. `layer=*` remains separate

Do not modify the existing layer rendering/order system.

For example:

```text
Way.layer = -1
Way.map_level = None
```

is still a surface-world tunnel/road ordered using the layer system.

It is NOT an underground map-level road.

Likewise:

```text
Way.layer = -1
Way.map_level = -2
```

is:

```text
logical map level = -2
render layer = -1
```

Both properties must continue to work independently.

---

# 10. Buildings

Inspect how buildings are rendered.

If a building has:

```text
map_level=-1
```

it must be treated as level -1 world content.

If it has:

```text
map_level=None
```

it remains surface content.

Do not infer a building's `map_level` from:

```text
building:levels
```

For example:

```text
building:levels=5
```

does NOT mean:

```text
map_level=5
```

---

# 11. Scenery

Inspect scenery rendering carefully.

Do not blindly apply the level rule to every scenery object.

Distinguish between:

### World geometry

Examples:

* parking geometry;
* trees;
* lamps;
* benches;
* barriers;
* terrain features.

and:

### Global rendering

Examples:

* HUD;
* weather overlays;
* UI;
* debug text;
* camera effects.

The map-level gate must not hide the HUD, UI or other global rendering.

If a scenery object has explicit:

```text
map_level
```

respect it.

If scenery currently cannot carry a map level, preserve its existing surface behaviour until the data model explicitly supports levels.

Do not invent level information.

---

# 12. Player, NPCs and pedestrians

Do not redesign gameplay entity levels in this task.

The current:

```python
Car.map_level
```

is the player's level.

The player vehicle must remain visible.

Do not accidentally hide the player because the player's `map_level` is non-zero.

For NPC vehicles and pedestrians:

* inspect their current render path;
* do not invent map levels;
* preserve current behaviour unless the entity already has an explicit map level.

The separate pedestrian/NPC level system can be implemented later.

However, do not allow the new world-level gate to accidentally remove all NPC rendering.

Document any deliberate limitation.

---

# 13. Separate world rendering from global rendering

The previous implementation notes indicate that the world-render section of `main()` should be moved into a dedicated function.

Do that if it produces a clean architecture.

For example, conceptually:

```python
render_world(...)
```

or:

```python
render_world_level(...)
```

The exact name should follow project conventions.

The important property is that:

```text
world rendering
```

can be selected based on:

```text
Car.map_level
```

without affecting:

```text
HUD
UI
debug
global effects
```

Do not blindly extract unrelated rendering code.

---

# 14. Do not scan every world object twice

Avoid an implementation such as:

```python
for obj in world_objects:
    ...
```

followed by:

```python
for obj in level_objects:
    ...
```

over large global collections every frame.

Use the existing:

* tile culling;
* spatial grids;
* visible lists;
* cached road geometry;
* camera bounds.

The level check should happen as early as reasonably possible after the existing spatial selection.

The ideal flow is:

```text
loaded data
    |
tile/spatial culling
    |
level filtering
    |
render
```

not:

```text
all world objects
    |
level filtering
    |
spatial culling
```

---

# 15. No per-frame allocations

Do not create:

```python
[x for x in ... if ...]
```

large temporary lists every frame solely for level filtering.

Do not create dictionaries or sets every frame for level selection.

Use existing structures or cached selections where practical.

If a small constant-time check is required for an already-visible object, that is acceptable.

---

# 16. Level transitions

For testing, `Car.map_level` must be able to change manually.

Test:

```text
0
→ -1
→ -2
→ -1
→ 0
```

Changing the level must NOT:

* reload OSM;
* fetch from Overpass;
* rebuild the world;
* rebuild all spatial grids;
* flush tile caches;
* trigger a full map reload.

Only rendering visibility should change.

---

# 17. Runtime tile streaming

The render gate must work with dynamically streamed `level_ways`.

If a tile containing:

```text
map_level=-1
```

arrives while the player is on:

```text
map_level=0
```

it must remain loaded but not rendered.

If the player later switches to:

```text
map_level=-1
```

the already-loaded data should become renderable without another OSM fetch.

Likewise, streamed level-specific roads must disappear visually when their tile is unloaded.

Reuse the existing tile lifecycle.

Do not create a second streaming mechanism.

---

# 18. ParkingGarage polygons

Do not make the `ParkingGarage` polygon itself into a drivable/rendered underground road surface.

The garage remains a data record.

The actual visible underground geometry in this phase comes from level-aware world objects such as:

```text
Way.map_level
```

when such OSM data exists.

A garage with:

```text
levels=(-2,-1)
```

but no internal level-aware ways may therefore have no visible underground road geometry yet.

That is expected.

Do not generate fake roads from the garage polygon.

---

# 19. Debug support

Extend the existing debug HUD minimally if useful.

It should remain possible to see:

```text
map_level=0
map_level=-1
map_level=-2
```

when testing.

Do not add an expensive debug overlay that scans all garages or roads every frame.

A manual/debug level switch would be useful for testing if the project already has an appropriate debug-key architecture.

If adding one is trivial and consistent with existing debug controls, allow:

```text
0
-1
-2
```

to be selected in a development/debug mode.

Do not make this a normal gameplay mechanic.

---

# 20. Tests

Add automated tests for the render-selection logic.

At minimum test:

### Surface

```text
current = 0

map_level=None -> visible
map_level=0    -> visible
map_level=-1   -> hidden
map_level=-2   -> hidden
```

### Underground -1

```text
current = -1

map_level=None -> hidden
map_level=0    -> hidden
map_level=-1   -> visible
map_level=-2   -> hidden
```

### Underground -2

```text
current = -2

map_level=-2 -> visible
map_level=-1 -> hidden
map_level=0  -> hidden
```

### Layer independence

Test an object with:

```text
layer=-1
map_level=None
```

and verify it remains a surface object.

Also test:

```text
layer=-1
map_level=-2
```

and verify both pieces of information remain independent.

### `level_ways`

Verify that:

```text
world.level_ways
```

objects become visible when their level matches the player's level.

### `parking_aisle`

Test:

```text
service=parking_aisle
level=-1
```

and verify it does not incorrectly appear as a level-0 road when the level gate is active.

### Level 0 in `level_ways`

Test:

```text
map_level=0
```

and ensure it is visible on the surface.

### Transition sequence

Test:

```text
0 → -1 → -2 → -1 → 0
```

without rebuilding/reloading the world.

---

# 21. Performance benchmark

This is mandatory for this phase.

Before making the final implementation, establish a baseline using the project's existing benchmark tooling.

At minimum compare:

### A. Surface gameplay before/after

```text
Car.map_level = 0
```

### B. Active tile streaming

Surface gameplay while tiles are being fetched/merged.

### C. Level -1 rendering

Using an Oulu area or synthetic/debug data containing `level_ways`.

### D. Level switching

```text
0 → -1 → -2 → -1 → 0
```

Measure:

* average frame time;
* p95 frame time;
* worst frame time;
* FPS;
* visible/rendered object counts where available;
* allocation behaviour if existing tooling supports it.

The most important requirement is **frame-time stability**.

Do not optimize based only on average FPS.

---

# 22. Performance target

The existing game has already undergone significant frame-time optimization.

Do not accept a solution that introduces a measurable regression to ordinary surface gameplay merely to make the level system elegant.

In particular:

```text
Car.map_level == 0
```

should remain the cheap/default rendering path.

Level-aware rendering should only add meaningful work when:

```text
Car.map_level != 0
```

or when actual level-aware objects are present.

---

# 23. Do not implement gameplay

This task is rendering only.

Do NOT implement:

* underground driving;
* underground collision changes;
* underground routing;
* garage entrance transitions;
* ramps;
* NPC underground traffic;
* pedestrian underground behaviour;
* parking-space simulation;
* automatic `Car.map_level` changes;
* garage pathfinding;
* new OSM imports.

Those are later phases.

---

# 24. Acceptance criteria

The implementation is complete when:

* `Car.map_level` controls world-level visibility.
* `map_level=None` behaves as surface level 0.
* Explicit `map_level=N` objects are visible only at level `N`.
* `world.level_ways` is rendered at the appropriate level.
* `level_ways` does not render on the surface when the player is at level 0 unless its own `map_level` is 0.
* `level=0` objects in `level_ways` are not accidentally lost.
* `service=parking_aisle` with `level=-1` respects the level rule.
* `layer=*` remains independent.
* Buildings with explicit `map_level` respect the same rule.
* Existing surface rendering remains visually unchanged.
* HUD/UI/debug/global effects are not hidden by the world-level gate.
* Player rendering remains correct.
* Tile streaming remains independent from visibility.
* Changing `Car.map_level` does not reload or rebuild world data.
* No full-world scan is introduced every frame.
* No significant per-frame allocation is introduced.
* Automated tests cover the visibility rules.
* The performance benchmark shows no unacceptable regression.
* All existing tests pass.

At the end, report:

1. Files changed.
2. Where the render gate was inserted.
3. How `world.ways` and `world.level_ways` are combined/selected.
4. How `map_level=None` is handled.
5. How `layer` remains independent.
6. How `parking_aisle` is handled.
7. How buildings/scenery are handled.
8. Tests added and total test count.
9. Before/after performance results.
10. Any remaining limitations.

Do not implement underground driving, routing, entrances or automatic level transitions in this task.
