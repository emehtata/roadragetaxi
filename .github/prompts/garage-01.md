# Road Rage Trip — Render Only the Current Underground Level

Repository: `emehtata/roadragetaxi`

Branch:

`release/0.15.0alpha`

## Context

The previous development phase added the OSM parking garage data layer.

Parking garages can now be identified and represented with logical map levels such as:

```text
surface       level = 0
garage P1     level = -1
garage P2     level = -2
```

The next goal is to prepare the renderer for multi-level worlds.

For this phase, implement **level-aware rendering**.

The most important rule is:

> When the player is on an underground level, render only the current map level and do not render the other levels.

For example:

```text
player.level = 0
    -> render level 0

player.level = -1
    -> render level -1 only

player.level = -2
    -> render level -2 only
```

Do not implement underground driving, routing, ramps or parking behaviour in this task unless a minimal change is absolutely necessary to test the rendering system.

---

# 1. Inspect the existing renderer first

Before changing anything, inspect:

* the main game/render loop;
* world object rendering;
* road rendering;
* building rendering;
* pedestrian rendering;
* NPC rendering;
* train rendering;
* parking/POI rendering;
* spatial grids;
* tile rendering/culling;
* camera code;
* existing object visibility/culling mechanisms.

Find where the current world objects are selected for rendering.

Do not immediately add individual `if underground` checks throughout the renderer.

The goal is to establish a clean, centralized level-aware visibility mechanism.

---

# 2. Introduce a world/map level concept

Use the level representation introduced by the parking garage data model.

If the previous phase already created a suitable type, reuse it.

Do not create a second competing representation.

Conceptually:

```python
player.map_level = 0
```

Examples:

```text
0   surface
-1  underground level 1
-2  underground level 2
1   elevated/bridge level if ever needed
```

The implementation must not assume that only negative levels will ever exist.

---

# 3. Centralize level visibility

Create a small, efficient mechanism for deciding whether an object belongs to the currently visible map level.

Conceptually:

```python
def is_visible_on_level(obj, current_level):
    ...
```

or an equivalent mechanism matching the project's architecture.

The important principle is:

```text
object.map_level == current_level
```

for objects that have explicit level information.

However, existing world objects may not have a level yet.

Do not break them.

Define a sensible default according to the existing world model.

For example, objects without explicit level information may initially be treated as:

```text
level = 0
```

but only if that is consistent with the existing data.

Do not blindly assign level 0 to objects that can clearly belong to an underground garage.

---

# 4. Renderer behaviour

The renderer should conceptually operate like this:

```text
current_level = player.map_level

for visible world object:
    if object belongs to current_level:
        render(object)
```

The level filtering should happen **before expensive rendering work**.

Do not:

```text
draw object
then decide whether it should have been visible
```

Instead:

```text
visibility/culling
        |
        v
level filtering
        |
        v
expensive rendering
```

This is important for performance.

---

# 5. Do not render other underground levels

Suppose a garage contains:

```text
P1 = level -1
P2 = level -2
P3 = level -3
```

When the player is on P2:

```text
RENDER:
    level -2

DO NOT RENDER:
    level  0
    level -1
    level -3
```

There should be no need for:

* transparency tricks;
* hiding buildings individually;
* complex occlusion calculations;
* clipping the entire world against the garage;
* rendering underground levels and then masking them.

Simply do not submit objects from other levels to the renderer.

---

# 6. Surface world behaviour

When:

```python
player.map_level == 0
```

the existing game should behave exactly as it does today.

This is extremely important.

Do not introduce unnecessary changes to surface rendering.

Existing:

* roads;
* buildings;
* trees;
* pedestrians;
* NPC traffic;
* trains;
* street furniture;
* weather;
* lighting;

must continue to render exactly as before.

The level-aware system should effectively be a no-op for existing level-0 world data.

---

# 7. Underground rendering

When the player enters an underground level, rendering should automatically switch to that level.

For example:

```text
player.map_level = -1
```

should result in:

```text
visible:
    garage level -1 roads
    garage level -1 objects
    garage level -1 parking spaces
    player
    vehicles on level -1
    pedestrians on level -1

hidden:
    surface roads
    surface buildings
    surface pedestrians
    surface NPCs
    other underground levels
```

Only render objects that actually belong to the current level.

---

# 8. Unknown-level objects

The current game contains many existing objects that probably do not have explicit level information.

Do not make assumptions without inspecting the existing data model.

Establish a documented rule for objects without level information.

For the first implementation, a reasonable approach may be:

```text
explicit level:
    use it

no level:
    treat according to existing world semantics
```

The important thing is that the behaviour is deterministic and backwards-compatible.

Do not accidentally make existing surface objects disappear.

---

# 9. Tile streaming interaction

The level filtering must work together with the existing tile streaming system.

Do not modify the streaming system merely to implement rendering.

A streamed tile may contain:

```text
surface objects
garage -1 objects
garage -2 objects
```

All of these may exist in memory simultaneously.

That is fine.

The renderer simply selects the current level.

Conceptually:

```text
Loaded tile
├── level 0
├── level -1
└── level -2

                     ↓

             current_level = -1

                     ↓

              render level -1
```

Do not unload other levels merely because they are currently invisible.

Streaming and visibility are separate concerns.

---

# 10. Spatial culling first, level filtering second

Preserve the existing spatial culling system.

The desired order is approximately:

```text
world/tile selection
       |
       v
spatial visibility
       |
       v
map-level filtering
       |
       v
object-specific visibility
       |
       v
render
```

If the existing architecture can place level filtering earlier without duplicating work, that is also acceptable.

The important requirement is:

**Do not scan the entire world every frame just to filter levels.**

Use the existing:

* tile structures;
* spatial grids;
* visible-object lists;
* object indexes;

where appropriate.

---

# 11. Performance requirements

Performance is a hard requirement.

This feature must not cause an FPS regression.

In particular:

* Do not add an expensive full-world scan every frame.
* Do not iterate through all underground garages every frame.
* Do not calculate object levels every frame.
* Do not perform geometry calculations merely to determine level visibility.
* Do not create temporary lists unnecessarily every frame.
* Avoid allocations in the hot render path.
* Reuse existing visible-object/culling structures where possible.
* Keep level comparison extremely cheap.

The ideal operation is essentially:

```python
obj.map_level == current_level
```

inside an already existing visibility/culling stage.

---

# 12. Optimize level changes

The player's level should normally change only when the player transitions between levels.

Do not rebuild the entire world every frame based on the current level.

If useful, cache:

```text
current_map_level
```

and only invalidate relevant visibility state when it changes.

For example:

```text
level -1
    |
    | player enters ramp
    v
level 0
    |
    | level changed
    v
rebuild/recalculate visible level-specific state
```

Do not perform expensive recalculation while the player remains on the same level.

---

# 13. Debug mode

Add an optional debug display if the existing debug infrastructure supports it.

For example:

```text
MAP LEVEL: -1
VISIBLE LEVEL: -1
```

Optionally display counts:

```text
visible objects: 243
level objects: 243
filtered objects: 1,892
```

Only collect expensive diagnostic counters when debugging is enabled.

Do not add measurable overhead to normal gameplay.

---

# 14. Tests

Add tests for:

### Surface

```text
current level = 0
object level = 0
=> visible
```

### Underground

```text
current level = -1
object level = -1
=> visible
```

### Different underground level

```text
current level = -1
object level = -2
=> hidden
```

### Surface vs underground

```text
current level = -1
object level = 0
=> hidden
```

### Multiple levels

Given:

```text
level  0
level -1
level -2
```

verify that only the selected level is visible.

### Backwards compatibility

Verify that existing objects without explicit level information continue to behave correctly according to the chosen compatibility rule.

### Level transition

Verify that changing:

```text
0 → -1 → -2 → -1 → 0
```

updates visibility correctly.

---

# 15. Rendering correctness

Pay particular attention to objects that may currently be rendered through different systems.

Test at least:

* roads;
* buildings;
* parking objects;
* vehicles;
* pedestrians;
* trains where applicable;
* street furniture;
* debug geometry.

Do not assume that everything goes through a single renderer.

If different systems have independent visibility selection, integrate the level filter at the appropriate shared layer rather than duplicating arbitrary checks.

---

# 16. No gameplay changes yet

Do not implement:

* parking garage routing;
* ramp navigation;
* automatic level changes;
* NPC underground driving;
* parking behaviour;
* garage entrance detection;
* collision changes;
* underground lighting system.

The only goal is:

> Given a world containing multiple map levels, render only the level currently occupied by the player.

If a small amount of infrastructure is needed for future phases, add it only when it is directly useful to this goal.

---

# 17. Acceptance criteria

The implementation is complete when:

1. The renderer understands the player's current `map_level`.
2. Objects can have a logical map level.
3. Only objects belonging to the current level are rendered.
4. Other underground levels are completely excluded from rendering.
5. The surface world continues to behave exactly as before.
6. Existing tile streaming continues to work.
7. Invisible levels remain loaded when appropriate; rendering and streaming remain separate concerns.
8. No expensive full-world level scan is introduced.
9. No measurable FPS regression is introduced during normal surface gameplay.
10. Switching levels does not cause unnecessary frame-time spikes.
11. Automated tests cover level visibility.
12. Debugging support is available if consistent with the existing debug architecture.

---

# 18. Performance validation

Before declaring the work complete, compare performance before and after.

Test at least:

```text
normal surface gameplay
surface with active tile streaming
underground level with active rendering
switching between levels
large number of loaded multi-level objects
```

Measure or inspect:

* average FPS;
* frame time;
* p95 frame time;
* worst frame time;
* object counts submitted to rendering;
* any allocation spikes.

The feature must not merely "work".

It must work while preserving the game's existing smooth frame pacing.

If level filtering introduces a performance regression, fix the architecture rather than accepting the regression.

---

# Expected architecture

The desired long-term structure is:

```text
                         World
                           |
              +------------+------------+
              |            |            |
           Level 0       Level -1     Level -2
              |            |            |
          surface       garage P1     garage P2
              |            |            |
              +------------+------------+
                           |
                       renderer
                           |
                    current map level
                           |
                           v
                  render matching level
```

The renderer should therefore treat `map_level` as a normal visibility dimension of the world rather than as a special-case "underground mode".

This is intentional: the same mechanism should later support bridges, tunnels, multi-level roads and other stacked map structures without requiring another rendering architecture.

## Final report

After implementation, report:

* files changed;
* how level-aware visibility was implemented;
* how existing objects without levels are handled;
* which render paths were modified;
* how the implementation interacts with spatial culling;
* test results;
* performance measurements;
* any remaining limitations.

Do not proceed to underground driving or routing in this task.
# Road Rage Trip — Level-Aware Rendering Infrastructure

Repository: `emehtata/roadragetaxi`

Branch:

`release/0.15.0alpha`

## Context

The previous phase implemented the OSM parking garage data layer.

The current implementation now has:

```python
world.parking_garages
```

containing `ParkingGarage` records.

Parking garages can have logical levels such as:

```text
0   ground
-1  underground level 1
-2  underground level 2
```

The garage data already contains:

* `levels`
* `levels_source`
* geometry
* OSM identity
* garage type
* metadata

The world cache and tile streaming already support parking garages.

The previous phase explicitly did **not** implement:

* garage entrances;
* internal garage roads;
* `level=*` / `indoor=*` OSM mapping;
* underground rendering;
* routing;
* driving inside garages.

This task is the **second phase**.

The goal is to introduce the rendering infrastructure needed for a multi-level world, while keeping the current game behaviour unchanged.

---

# 1. Important: inspect the current implementation first

Before modifying anything, inspect the actual implementation produced by the previous phase.

In particular inspect:

* `ParkingGarage`
* `world.parking_garages`
* garage loading from `.rwc`
* `AutoFetchManager` garage streaming
* current world object representation
* `Way`
* road rendering
* building rendering
* scenery rendering
* vehicle rendering
* pedestrian rendering
* train rendering
* spatial culling
* tile culling
* camera/render pipeline
* debug rendering, if present.

Do not assume the architecture from this specification.

The previous implementation report says:

* garage data has no per-frame runtime cost;
* garages are integrated through the existing streaming merge budget;
* garages currently have no spatial index;
* `ParkingGarage.levels` already exists;
* `level=*` and `indoor=*` are not currently imported.

Preserve these characteristics.

---

# 2. Do NOT create another parking-garage level model

The previous phase already created:

```python
ParkingGarage.levels
ParkingGarage.levels_source
```

Reuse this representation.

Do not create another independent:

```python
GarageLevel
UndergroundLevel
ParkingLevel
```

model unless inspection proves that the existing implementation genuinely cannot support the required rendering architecture.

There must be one coherent concept of logical map levels.

---

# 3. Important distinction: garage levels vs object levels

At this stage, `ParkingGarage` knows which levels exist.

However, most current world objects do not yet have a level.

For example, we may currently have:

```text
ParkingGarage
    levels = (-2, -1)

Way
    no level information

Building
    no level information
```

Do **not** pretend that the current OSM data already tells us which road belongs to which garage level.

That will be handled in a later OSM-import phase.

Do not invent level assignments from geometry.

Do not assign every object inside a garage polygon to an underground level.

---

# 4. Introduce a minimal world-level concept

Create the smallest possible infrastructure needed to represent the currently visible logical map level.

The player should eventually be able to have a value conceptually equivalent to:

```python
current_map_level = 0
```

where:

```text
0   surface
-1  underground level 1
-2  underground level 2
1+  elevated levels
```

Use existing project conventions.

If the project already has an appropriate world/player state representation, extend it rather than creating another parallel state.

At this phase, the player's value should remain:

```text
0
```

during normal gameplay.

Do not implement automatic underground level transitions yet.

---

# 5. Design level-aware visibility without changing current rendering

The renderer needs a future-proof way to ask:

```text
"What logical map level does this renderable object belong to?"
```

However, most current objects do not have a level.

Therefore define a minimal, backwards-compatible abstraction.

Conceptually:

```python
get_object_map_level(obj)
```

or an equivalent architecture that fits the existing renderer.

The result should distinguish between:

```text
explicit level
no level information
```

Do not invent underground levels for objects that do not explicitly have them.

For now, existing objects without level information must continue to behave exactly as they do today.

---

# 6. Do NOT add a full-world scan every frame

This is one of the most important requirements.

Do not implement:

```python
for obj in all_world_objects:
    if obj.level == current_level:
        ...
```

every frame.

Do not create a new global list of every world object just for level filtering.

Do not add an O(number of world objects) level pass to the main loop.

The game already has:

* tile culling;
* spatial grids;
* visible-object selection;
* road caching;
* incremental tile integration.

Use those mechanisms.

Level-aware rendering should be integrated into the existing visibility/culling pipeline.

---

# 7. Desired rendering pipeline

The long-term goal is:

```text
loaded world
    |
    v
spatial/tile culling
    |
    v
current map-level filtering
    |
    v
object-specific visibility
    |
    v
render
```

The exact ordering may differ if the existing renderer has a more efficient architecture.

The important requirement is:

**Do not perform expensive rendering work for objects that are known to be on another map level.**

---

# 8. Surface level must remain completely unchanged

This is a strict backwards-compatibility requirement.

When:

```python
current_map_level == 0
```

normal gameplay must look and behave exactly as before.

Do not change:

* road rendering;
* building rendering;
* scenery;
* NPC rendering;
* pedestrian rendering;
* train rendering;
* lighting;
* weather;
* camera behaviour;
* tile streaming.

The existing surface world should remain the default path.

If level-aware filtering introduces measurable overhead to ordinary surface rendering, reconsider the architecture.

---

# 9. Prepare for future underground rendering

The architecture should eventually support:

```text
current_map_level = -1
```

with:

```text
level -1 objects     -> visible
level  0 objects     -> hidden
level -2 objects     -> hidden
level +1 objects     -> hidden
```

And:

```text
current_map_level = -2
```

with:

```text
level -2 objects     -> visible
everything else     -> hidden
```

However, **do not attempt to make this work by assigning levels to current OSM roads based on the garage polygon**.

There are no reliable garage internal road levels yet.

Build the visibility infrastructure so that it can consume explicit object levels when those objects are introduced later.

---

# 10. ParkingGarage rendering in this phase

Do not turn parking garages into a normal visible underground world yet.

The current `ParkingGarage` geometry may represent:

* an area;
* a node;
* a relation-derived polygon.

It does not yet represent the internal road network.

Do not render the garage as if its polygon were an underground driving surface.

Instead, if useful, add **debug-only visualization**.

For example:

```text
PARKING GARAGE
type: underground
levels: -2,-1
```

The debug representation can show the garage footprint.

This must be:

* disabled by default;
* cheap;
* integrated with existing debug infrastructure if available.

---

# 11. Add a temporary test/debug level

Because the actual garage road network does not exist yet, create a minimal way to test the level-aware renderer without modifying real OSM semantics.

Prefer an existing test/debug mechanism.

For example, in a development/debug scenario only, create a few synthetic renderable objects:

```text
level  0
level -1
level -2
```

and verify that selecting:

```text
current_map_level = -1
```

only displays:

```text
level -1
```

Do not add synthetic objects to normal game data.

Do not make this a gameplay feature.

---

# 12. Rendering only the current level

When explicit level-aware renderable objects become available, the renderer must use this rule:

```text
object has explicit level:
    render only if object.level == current_map_level

object has no explicit level:
    preserve existing behaviour
```

Do not use:

```text
object is inside garage polygon
=> underground
```

That would be incorrect.

Do not use:

```text
garage has -1
=> everything nearby is -1
```

That would also be incorrect.

Level membership must ultimately come from OSM or explicit game-world data.

---

# 13. No underground occlusion hacks

Do not implement underground rendering using:

* alpha transparency;
* rendering the entire surface world and masking it;
* arbitrary building hiding;
* screen-space clipping;
* expensive polygon clipping;
* depth hacks;
* per-object distance tests against garage polygons.

The intended solution is **logical visibility filtering**.

If the player is on level -1, level 0 objects should simply not be submitted to the relevant rendering stage.

---

# 14. Tile streaming compatibility

The current tile streaming system already handles garage records.

Do not change the streaming architecture unnecessarily.

A tile may eventually contain:

```text
level 0 objects
level -1 objects
level -2 objects
```

All of these may remain loaded in memory.

That is intentional.

**Streaming decides what data is resident.**

**Rendering decides what resident data is visible.**

Do not unload level -2 simply because the player is currently on level -1.

Do not confuse visibility with memory residency.

---

# 15. Avoid per-frame allocations

The render loop is performance-sensitive.

Do not create temporary lists such as:

```python
visible_level_objects = [
    obj for obj in objects
    if obj.level == current_level
]
```

every frame unless the existing renderer already uses this exact pattern and it has been proven harmless.

Prefer:

* existing visible-object lists;
* existing spatial grids;
* cached visibility;
* cheap comparisons;
* level-aware indexing if it becomes necessary.

Do not introduce a new spatial index just for this phase unless measurements demonstrate that it is required.

---

# 16. Level changes must be cheap

The player's map level will eventually change when entering/exiting ramps.

For now, create the infrastructure for:

```text
level 0 → level -1
level -1 → level -2
level -2 → level -1
level -1 → level 0
```

but do not implement the actual transitions.

When the level changes in a test/debug environment:

* invalidate only the relevant visibility state;
* do not rebuild the entire world;
* do not reload OSM data;
* do not rebuild spatial grids unnecessarily;
* do not trigger tile streaming.

---

# 17. Performance requirements

This feature must preserve the existing performance characteristics.

The current parking garage implementation has:

> no per-frame cost

according to the previous implementation report.

Do not turn that into a significant per-frame cost.

### Hard requirements

* No full-world scan every frame.
* No full garage scan every frame.
* No geometry calculations every frame for level visibility.
* No OSM processing during rendering.
* No network operations during rendering.
* No cache access during rendering.
* No large allocations in the render hot path.
* No full world rebuild when changing levels.
* No FPS regression during ordinary surface gameplay.
* No visible frame-time spike when switching logical levels.

The renderer must remain capable of maintaining stable frame pacing while tile streaming is active.

If there is a choice between a more sophisticated level system and a cheaper implementation, prefer the cheaper implementation unless the more sophisticated system is clearly necessary for correctness.

---

# 18. Tests

Add tests using the project's existing testing conventions.

At minimum test the level visibility abstraction with synthetic objects.

### Same level

```text
current = 0
object = 0
=> visible
```

### Underground

```text
current = -1
object = -1
=> visible
```

### Different underground level

```text
current = -1
object = -2
=> hidden
```

### Surface vs underground

```text
current = -1
object = 0
=> hidden
```

### Multiple levels

Given:

```text
0
-1
-2
```

verify that only the selected level is visible.

### No explicit level

Verify that existing objects without level information retain their existing rendering behaviour.

### Level transitions

Test:

```text
0 → -1 → -2 → -1 → 0
```

using synthetic/debug objects.

---

# 19. Performance validation

Before implementation, establish a baseline if suitable benchmark tooling already exists.

After implementation compare:

1. Normal surface gameplay.
2. Surface gameplay with active tile streaming.
3. Debug/test scene containing multiple logical levels.
4. Switching between levels.
5. Large numbers of loaded objects.

Pay attention to:

* average FPS;
* frame time;
* p95 frame time;
* worst frame time;
* allocations if measurable;
* render object submission counts.

The most important metric is **frame-time stability**, not merely average FPS.

Do not accept a solution that makes the game feel less smooth.

---

# 20. Keep this phase deliberately limited

Do NOT implement:

* OSM `level=*` parsing;
* OSM `indoor=*` parsing;
* `parking=entrance` handling;
* garage internal roads;
* garage road generation;
* ramp detection;
* underground driving;
* underground routing;
* A* changes;
* NPC underground traffic;
* parking-space behaviour;
* underground lighting;
* underground collision changes.

Those are later phases.

This phase should establish only the rendering infrastructure required to make them possible.

---

# 21. Future architecture

The intended long-term architecture is:

```text
                         OSM world
                            |
                 +----------+----------+
                 |          |          |
              level 0    level -1   level -2
                 |          |          |
              surface     garage P1   garage P2
                 |          |          |
                 +----------+----------+
                            |
                       loaded world
                            |
                  spatial/tile culling
                            |
                    current map level
                            |
                            v
                   visible world objects
                            |
                            v
                         renderer
```

Later, OSM internal garage roads will provide explicit levels:

```text
highway=service
level=-1
```

and those roads will naturally participate in the same visibility system.

The renderer should therefore be designed around **explicit logical map levels**, not around a special "underground garage mode".

---

# 22. Acceptance criteria

The implementation is complete when:

* The existing `ParkingGarage.levels` representation is reused.
* No duplicate garage-level data model is introduced.
* A logical current map level exists.
* The renderer has a clean mechanism for level-aware visibility.
* Existing objects without explicit levels remain fully compatible.
* No level is inferred from garage polygon geometry.
* The surface world renders exactly as before.
* The architecture supports rendering only the current level once explicit level-aware objects exist.
* No underground rendering hacks are introduced.
* Tile streaming remains independent from visibility.
* No full-world scan is introduced into the game loop.
* No significant per-frame allocation is introduced.
* Automated tests cover the visibility rules.
* Performance remains stable.

## Final report

After implementation, report:

* files changed;
* how the current map level is represented;
* how level-aware visibility is integrated into the renderer;
* how objects without explicit levels behave;
* how the implementation interacts with tile/spatial culling;
* tests added and results;
* performance measurements;
* any remaining limitations.

Do not proceed to OSM internal road parsing, garage entrances, underground driving or routing in this task.
