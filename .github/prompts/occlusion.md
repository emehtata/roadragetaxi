Implement a **robust, general-purpose occlusion system** for the game.

## Goal

Dynamic gameplay objects must be rendered correctly when they are partially or completely hidden behind static world geometry.

Examples of dynamic objects include:

* Player vehicle
* NPC vehicles
* Pedestrians
* Bicycles
* Motorcycles
* Any other moving or dynamically spawned entity
* Future dynamic entities should automatically benefit from the same system

When a dynamic object is behind an occluding world object, such as:

* Buildings
* Building walls
* Bridges
* Elevated roads
* Other solid map structures
* Any other object that should visually block the dynamic entity

the hidden parts of the dynamic object must **not be rendered normally**.

Instead, the hidden dynamic object should be represented by a **clear outline/silhouette** so the player can understand that an entity exists behind the obstruction.

The system must support:

1. Completely hidden objects
2. Partially hidden objects
3. Objects becoming visible again while moving
4. Moving camera
5. Different object sizes
6. Different elevations/heights
7. Multiple occluders
8. Dynamic objects moving behind and out from behind occluders
9. Objects entering and leaving the screen
10. Future entity types without requiring custom occlusion code for each type

---

# 1. First inspect the existing rendering architecture

Before modifying code:

* Inspect the complete rendering pipeline.
* Identify where the following are rendered:

  * map/background
  * roads
  * buildings
  * bridges/elevated structures
  * static objects
  * player
  * NPC vehicles
  * pedestrians
  * other dynamic entities
  * effects
  * UI
* Identify the coordinate systems used:

  * world coordinates
  * tile coordinates
  * screen coordinates
  * camera coordinates
* Identify sprite dimensions, anchor points and collision/geometry representations.
* Identify whether the game already has z-ordering, layers, depth information or spatial partitioning.

Do not implement a superficial per-object workaround before understanding the existing renderer.

Preserve the existing architecture wherever possible.

---

# 2. Define a proper occlusion model

Create a central concept of an **occluder**.

An occluder is a world object that can visually hide a dynamic entity.

Examples:

```text
Building
Bridge
Elevated road
Wall
Other solid structure
```

Each occluder should have enough information to determine whether it covers a dynamic object's screen/world position.

Do NOT simply use sprite rectangles if the existing geometry allows something more accurate.

Prefer existing map geometry, polygons, footprints, bounding boxes, or collision geometry where appropriate.

The occlusion system must distinguish between:

```text
dynamic entity
        +
occluding geometry
        =
visibility state
```

Avoid hard-coding checks such as:

```python
if entity.type == "car":
    ...
```

The system must operate on a generic dynamic entity interface.

---

# 3. Handle partial occlusion correctly

This is important.

Do NOT simply hide the entire sprite whenever its center point is behind a building.

For example:

```text
      BUILDING
   █████████████
   █████████████
       🚗
```

If only part of the car is hidden, the visible portion must remain normally rendered.

The hidden portion should be represented by the outline.

Conceptually:

```text
visible area     -> normal sprite
occluded area    -> outline
```

For a partially hidden entity:

```text
      building
   █████████████
   █████████████
        ╭────╮
        │ CAR│
        ╰────╯
        ↑
   hidden part becomes outline
```

Do not replace the entire sprite with an outline unless the entity is completely occluded.

---

# 4. Render ordering

Establish an explicit and deterministic rendering order.

The final order should conceptually resemble:

```text
1. Background
2. Ground/map
3. Roads
4. Static world geometry
5. Dynamic entities
6. Occlusion correction / hidden portions
7. Effects
8. UI
```

However, adapt this to the existing renderer if a different ordering is required.

The critical requirement is:

**Occluding geometry must visually appear in front of hidden portions of dynamic entities.**

Do not solve this by simply drawing all buildings after all entities if that breaks existing rendering, shadows, roads, bridges, effects, or other visual elements.

---

# 5. Use masks where appropriate

If the game uses Pygame surfaces, implement occlusion using masks or equivalent pixel/geometry masking where practical.

A robust approach is:

1. Render the dynamic entity into its own surface.
2. Determine the occluded region.
3. Render the normal sprite only where it is not occluded.
4. Generate an outline/silhouette for the occluded portion.
5. Render the outline where the entity is hidden.

The implementation should avoid modifying the original sprite.

Do not permanently alter cached sprite surfaces.

---

# 6. Outline rendering

Create a reusable outline-generation function.

For example:

```python
create_occlusion_outline(surface, ...)
```

or an equivalent abstraction appropriate for the existing codebase.

The outline should:

* Clearly indicate the hidden entity
* Be visually lightweight
* Preserve the entity's recognizable shape
* Work with different sprite sizes
* Work with transparent sprites
* Work with all dynamic entity types

Do not create a separate implementation for cars, pedestrians, bicycles, etc.

The outline should be generated from the entity's actual rendered silhouette rather than from a generic rectangle.

If the project already has an outline/highlight implementation, reuse it instead of creating a second incompatible system.

---

# 7. Completely hidden entities

If an entity is completely behind an occluder, the entity should not disappear completely.

Instead:

```text
normal entity:
      🚗

completely occluded:
      outline of 🚗
```

The outline should remain visible enough to communicate the entity's presence without incorrectly rendering the hidden sprite itself.

This is especially important for:

* Player vehicle
* NPC vehicles
* Pedestrians

The player must never become impossible to locate merely because the vehicle drives behind a building or bridge.

---

# 8. Buildings and other map geometry

Do not assume that every map polygon is an occluder.

Explicitly identify which existing world objects are visually solid/occluding.

For example:

```text
Building wall       -> occluder
Bridge structure    -> occluder
Road surface        -> normally not an occluder
Sidewalk            -> normally not an occluder
Ground              -> not an occluder
Decorative marking  -> not an occluder
```

For bridges/elevated roads, take elevation/layer information into account.

A bridge should be capable of hiding an entity that is physically below it, while an entity on top of the bridge should remain visible.

Do not blindly apply 2D rectangle overlap when the map contains elevation or layer information.

---

# 9. Camera movement

The occlusion system must work correctly with the game's existing camera system.

Do not cache occlusion results in screen coordinates.

Occlusion calculations should preferably operate in world coordinates and only be transformed into screen coordinates during rendering.

The system must remain correct when:

* Camera moves
* Player moves
* NPCs move
* Camera follows the player
* Zoom changes, if supported

Avoid introducing frame-to-frame visual lag caused by using stale camera coordinates.

---

# 10. Performance

This is a real-time game, so do not implement an O(all static objects × all dynamic objects) algorithm every frame if it can be avoided.

Use the game's existing spatial partitioning/tile/chunk system where possible.

Only test dynamic entities against occluders that are potentially relevant.

For example:

```text
visible dynamic entities
        ↓
nearby/relevant occluders
        ↓
precise occlusion test
        ↓
render result
```

Do not scan the entire Finland OSM dataset for every vehicle every frame.

Use:

* Spatial indexing
* Visible tiles
* Cached building geometry
* Chunk/tile lookup
* Bounding-box rejection
* Other existing spatial structures

Perform cheap rejection tests before expensive mask/polygon operations.

---

# 11. Avoid unnecessary per-frame allocations

Pay particular attention to the existing game's performance characteristics.

Avoid:

* Creating large temporary surfaces unnecessarily
* Rebuilding masks for static geometry every frame
* Parsing OSM geometry every frame
* Recreating unchanged building masks every frame
* Excessive Python object creation
* Recalculating static geometry that can be cached

Static occluder geometry should be cached.

Only dynamic information should be recalculated when necessary.

---

# 12. Sprite anchor points

Correctly account for sprite anchor/origin positions.

Do not assume:

```text
sprite center == entity world position
```

The existing game may use:

* bottom-center
* center
* vehicle origin
* pedestrian foot position
* custom sprite offsets

Use the game's actual coordinate conventions.

This is particularly important for pedestrians and vehicles because the point touching the ground should determine their world position and layer relationship.

---

# 13. Layer/elevation handling

Where the game has information such as:

* bridge layer
* road layer
* building height
* elevated road
* tunnel
* ground level

use it.

The system should conceptually determine:

```text
Is entity A physically behind occluder B?
```

rather than merely:

```text
Do their rectangles overlap?
```

For a bridge:

```text
bridge
████████████

car below
   🚗

=> car can be occluded
```

But:

```text
bridge
████████████
   🚗

=> car on bridge remains visible
```

Use the existing map semantics if available rather than inventing arbitrary elevation values.

---

# 14. Visibility transitions

Test situations where an entity:

```text
visible
   ↓
partially hidden
   ↓
completely hidden
   ↓
partially hidden
   ↓
visible
```

The transition must be continuous and must not flicker.

Pay particular attention to:

* Entity moving along building edges
* Entity moving parallel to a building
* Camera moving past a building
* Entity moving underneath a bridge
* Entity emerging from behind a building
* Multiple overlapping buildings

Avoid single-pixel or floating-point boundary instability that causes rapid visibility toggling.

Use a small, well-defined tolerance if necessary.

---

# 15. Multiple occluders

An entity can be behind several objects simultaneously.

For example:

```text
building A
building B
bridge
   ↓
  CAR
```

The system must combine occlusion information correctly.

Do not stop after finding the first occluder if other occluders affect the visible area.

The resulting visible/hidden mask should represent the union of all applicable occluders.

---

# 16. Generic dynamic entity API

Introduce a clean interface so every dynamic entity can participate automatically.

Conceptually:

```python
class DynamicEntity:
    def get_render_surface(self):
        ...

    def get_world_position(self):
        ...

    def get_render_rect(self):
        ...

    def get_occlusion_bounds(self):
        ...
```

Adapt this to the existing architecture instead of blindly introducing a new base class if one already exists.

The goal is to centralize occlusion logic rather than duplicate it.

---

# 17. Debug mode

Add a debug visualization that can be enabled through the game's existing debug mechanism.

When enabled, visualize:

* Occluder bounds
* Occluder polygons/masks
* Dynamic entity bounds
* Entity world position
* Entity visibility state
* Which occluder(s) currently affect the entity

For example:

```text
ENTITY: NPC_CAR_17
VISIBILITY: PARTIAL
OCCLUDERS: building_342
```

This will make future occlusion bugs much easier to diagnose.

Do not leave verbose debug logging enabled in normal gameplay.

---

# 18. Important rendering correctness rules

The implementation must NOT:

* Make roads occlude cars simply because they overlap
* Make sidewalks hide pedestrians
* Make decorative map elements hide entities
* Hide an entire sprite when only a small part is occluded
* Permanently modify source sprites
* Depend on hard-coded screen coordinates
* Depend on specific vehicle sprite dimensions
* Introduce separate occlusion implementations for every entity type
* Break camera movement
* Break NPC spawning/despawning
* Break pedestrian rendering
* Break bridge rendering
* Break existing map rendering
* Cause noticeable FPS degradation

---

# 19. Tests

Add or improve tests for at least these scenarios:

### Test 1 — Fully visible

Entity is not behind an occluder.

Expected:

```text
100% normal sprite
0% outline
```

### Test 2 — Partially occluded

Part of entity overlaps an occluding building.

Expected:

```text
visible portion = normal sprite
hidden portion = outline
```

### Test 3 — Fully occluded

Entity is completely behind building.

Expected:

```text
normal sprite = hidden
outline = visible
```

### Test 4 — Bridge

Entity below bridge.

Expected:

```text
entity = occluded
```

Entity on bridge.

Expected:

```text
entity = visible
```

### Test 5 — Pedestrian

Pedestrian behind building.

Expected:

```text
pedestrian = correctly outlined
```

### Test 6 — NPC vehicle

NPC vehicle behind building.

Expected:

```text
vehicle = correctly outlined
```

### Test 7 — Player

Player drives behind building.

Expected:

```text
player remains identifiable through outline
```

### Test 8 — Camera movement

Move camera while entity remains behind an occluder.

Expected:

```text
occlusion remains spatially correct
```

### Test 9 — Multiple occluders

Entity overlaps multiple occluders.

Expected:

```text
combined occlusion is correct
```

### Test 10 — Performance

Run a realistic scene containing:

* Many buildings
* Multiple NPCs
* Multiple pedestrians
* Moving camera

Verify that the new system does not introduce noticeable frame-time spikes.

---

# 20. Implementation strategy

Before coding, explain briefly:

1. Where occlusion will be integrated into the current renderer
2. Which existing classes/functions will be reused
3. What will represent an occluder
4. How partial occlusion will be calculated
5. How outlines will be generated
6. How spatial filtering will prevent unnecessary calculations
7. How bridges/elevation will be handled
8. How the implementation avoids performance regressions

Then implement the solution.

Do not stop at identifying the problem.

Actually modify the code.

After implementation:

* Run the existing test suite.
* Add appropriate regression tests.
* Run lint/type checks if the project uses them.
* Verify the game starts successfully.
* Verify player, NPC vehicles and pedestrians all use the same occlusion system.
* Check for rendering regressions.
* Check frame-time/performance impact.

Finally, provide a concise summary of:

```text
Files changed
Architecture used
Occlusion algorithm
Outline implementation
Performance considerations
Tests performed
Any remaining limitations
```

The implementation should be **general and extensible**, not a one-off fix for the currently observed building/bridge bug.
