# Godot Phase 4 — Collision-Relevant Static World

## Objective

Continue the Pygame → Godot parity work after godot-12.

The next phase is:

> **Collision-relevant static world**

Implement the static world elements that can affect driving, pedestrian movement, or physical occupancy:

1. Trees
2. Other scenery objects that are collision-relevant
3. Fences and railings
4. Knocked-over posts
5. Broken lamps

The goal is to reproduce the existing Pygame/server behaviour in Godot without redesigning the collision or navigation architecture.

This is primarily a **static-map/data + collision representation** phase.

Do not continue into the remaining visual static world, calendar/day-night, or navigation work.

---

# 1. Current state

godot-12 is complete and pushed.

Commits:

```text
2c72ecc  chunks and state
0bd24d9  Godot
cdd4acb  docs
```

No Git tag was created.

Current parity:

| Status              | Count |
| ------------------- | ----: |
| Complete            |    39 |
| Partial             |    17 |
| Missing             |    43 |
| Different by design |     4 |
| Debug-only          |     3 |
| Not applicable      |     3 |

Current tests:

```text
Python: 1551 passed
Godot: 143 checks passed
make godot-test: PASS
make godot-selftest: PASS
make audio-check: PASS
```

`tests/test_packaging.py` remains excluded because this environment uses Python 3.10 and that test requires Python 3.11+.

Recent performance baseline:

```text
Godot selftest: ~145 FPS
No render backward steps
Memory: ~66 MiB
```

Preserve this baseline as closely as practical.

---

# 2. Stability constraints

The following are known stable and MUST NOT be modified as part of this phase unless a direct regression is demonstrated:

* vehicle movement
* vehicle interpolation
* camera movement
* background rendering
* camera zoom behaviour
* driving input
* accelerator release behaviour
* `StateBuffer`
* existing chunk loading/unloading
* existing traffic-light phase handling
* existing taxi stand rendering
* existing fuel station rendering
* existing roadwork rendering

Do not use this phase as an opportunity to refactor those systems.

If a collision problem exposes a genuine defect in one of them, isolate the defect and make the smallest possible correction.

---

# 3. First inspect the existing implementation

Before changing code, inspect:

* `docs/architecture/godot-pygame-rendering-parity.md`
* `docs/architecture/godot-rendering-migration.md`
* `docs/architecture/godot-client.md`
* current server map/chunk implementation
* current Godot map/chunk implementation
* existing collision handling
* Pygame collision implementation
* OSM/static-world extraction code
* tests covering collision and map objects

Search the repository for all existing implementations of:

* trees
* scenery
* fences
* railings
* posts
* lamps
* knocked-over objects
* collision masks
* static obstacles
* pedestrian obstacles
* vehicle obstacles

Do not assume that an object must be added to the protocol merely because Godot currently does not render it.

Determine whether each object is:

* static visual data
* static collision data
* dynamic state
* both visual and collision-relevant
* already represented indirectly by another map object

Reuse existing server data wherever possible.

---

# 4. Important architectural rule

The current Godot-12 architecture already supports static objects through map chunks.

Continue using:

```text
authoritative server/static map data
        ↓
map chunk
        ↓
Godot chunk representation
        ↓
visual + collision representation
```

Do not create a second map database.

Do not introduce a separate collision-map file format.

Do not reintroduce the abandoned Pygame BIN architecture.

Do not move collision authority into the Godot client if the server currently owns collision/gameplay decisions.

The purpose of this phase is to make Godot represent the existing world correctly, not to invent a new physics architecture.

---

# 5. Determine collision authority first

This is particularly important.

Before implementing collision for any object, determine where collision is authoritative today.

For each object type answer:

```text
Where does Pygame obtain the object?
Where does the server obtain the object?
Where is collision tested today?
Is collision server-side, client-side, or both?
Does the object affect vehicles?
Does it affect pedestrians?
Does it affect navigation?
Does it merely affect rendering?
```

Do not silently move authoritative collision from server to client.

If the server already performs the relevant collision test, expose the minimum data Godot needs to represent the same obstacle visually and, if necessary, locally predict it.

If collision is currently client-side in Pygame, reproduce that behaviour using the existing Godot collision architecture.

---

# 6. Trees

Implement parity for collision-relevant trees.

Inspect the existing Pygame implementation and static map data.

Determine:

* tree position
* tree type/class if applicable
* collision radius/shape
* visual size
* whether different tree types have different collision footprints
* whether trees are loaded from OSM or generated from another static source
* whether trees can be knocked over

Do not invent a new tree taxonomy.

Use the authoritative existing data.

The Godot representation should provide:

* correct visual position
* correct approximate visual size
* correct collision footprint where collision is currently relevant

Avoid individual per-frame processing.

Trees should be created/removed with their map chunk.

---

# 7. Other collision-relevant scenery

Identify all scenery categories that the current Pygame game treats as physical obstacles.

Do NOT implement every scenery object in the repository.

Only include objects that are genuinely collision-relevant in the current game.

Examples might include:

* physical roadside objects
* large fixed obstacles
* utility objects
* barriers
* other objects that prevent vehicle/pedestrian passage

Do not assume that every decorative object needs collision.

For every category selected, document:

```text
object type
source data
collision shape
visual representation
server/client authority
chunk ownership
```

If an object is purely decorative, leave it for the later "rest of static world" phase.

---

# 8. Fences and railings

Implement fences and railings that currently affect movement/collision.

Determine whether they are:

* point objects
* line segments
* polylines
* polygons
* individual posts

Prefer the simplest collision representation that matches the existing game's behaviour.

Do not over-model the geometry.

For example, if the existing game treats a fence as a blocking segment, a blocking segment is preferable to hundreds of individual collision nodes.

Preserve orientation and position accurately.

Verify that chunk boundaries do not cause:

* missing fence segments
* duplicate segments
* gaps
* incorrect clipping

If a single fence crosses multiple chunks, ensure that each chunk owns only its intended portion or otherwise follow the existing authoritative ownership rule.

---

# 9. Knocked-over posts and broken lamps

These are specifically listed as collision-relevant parity gaps.

Inspect how Pygame represents:

* knocked-over posts
* broken lamps

Determine whether they are:

* static map objects
* consequences of gameplay events
* persistent state
* transient state

Do not convert a dynamic event into static chunk data if it is actually gameplay state.

If these objects are already part of authoritative dynamic state, expose them through the existing state mechanism rather than duplicating them in static map chunks.

If they are genuinely static data, use the chunk mechanism.

Preserve their collision relevance separately from their visual orientation.

---

# 10. Chunk lifetime

All static collision-relevant objects must follow existing chunk lifetime rules.

Verify:

1. object appears when its chunk loads
2. object disappears when its chunk unloads
3. object reappears correctly after reload
4. no duplicate collision shapes are created
5. no stale collision shapes remain after unload
6. crossing a chunk boundary does not produce collision discontinuities

This is especially important for fences and railings.

Do not keep the entire country's collision map resident in Godot.

---

# 11. Collision implementation

Use the existing Godot collision architecture.

Do not introduce a completely new physics engine or collision subsystem.

Before adding nodes/shapes, inspect how the current project represents:

* road boundaries
* buildings
* vehicles
* pedestrians
* parking structures
* other collision geometry

Reuse those conventions.

Prefer simple static collision primitives:

* circles
* rectangles
* line/segment geometry
* polygons

where they are sufficient.

Avoid extremely detailed collision meshes for trees or scenery unless the existing game genuinely depends on such precision.

The objective is behavioural parity, not geometric perfection.

---

# 12. Server/client protocol

Only add protocol data where the Godot client genuinely lacks information needed for parity.

Before adding a field, establish:

```text
field:
source:
consumer:
static/dynamic:
collision relevance:
why existing data is insufficient:
```

Prefer extending the existing map chunk representation.

Do not create one network message per object.

Do not send the entire static world every tick.

Do not add per-frame collision data.

For dynamic knocked-over/broken objects, use the existing dynamic-state mechanism if appropriate.

Maintain backwards compatibility where practical.

Do NOT introduce:

* binary protocol
* WebSocket redesign
* new map file format
* new global static-world protocol

---

# 13. Rendering

Rendering is required only to the extent necessary for parity and debugging.

Implement the appropriate top-down Godot representation.

Do not restore the old Pygame isometric building renderer.

Do not introduce 3D.

Use existing Godot chunk rendering conventions.

Static objects should not be redrawn every frame.

If the existing Godot map rendering uses redraw-on-zoom-change, follow that model.

Collision geometry may be invisible during normal gameplay.

For development/debugging, it is acceptable to add a temporary or test-only collision visualization, but do not leave an always-on debug overlay in normal gameplay.

---

# 14. Coordinate and scale validation

For every new object type verify:

* world position
* orientation
* visual scale
* collision scale
* chunk ownership

Use authoritative server/static data.

Do not compensate for coordinate errors by modifying the camera.

Do not alter the world coordinate system.

Do not change zoom.

If visual and collision positions differ, fix the object conversion rather than changing global transforms.

---

# 15. Tests

Add deterministic tests for each implemented category.

At minimum:

### Trees

* correct static data parsing
* correct chunk ownership
* correct world position
* collision shape created
* chunk unload removes collision
* reload does not duplicate collision

### Collision-relevant scenery

* correct parsing
* correct collision representation
* chunk lifecycle
* no duplicates

### Fences / railings

* segment geometry correct
* orientation correct
* chunk boundaries handled correctly
* no gaps/duplicates
* collision removed on unload

### Knocked-over posts / broken lamps

* correct classification as static or dynamic
* correct state parsing
* correct collision representation
* correct lifecycle

Also test an actual collision case for each category where practical.

Tests should verify behaviour rather than merely checking that a node exists.

---

# 16. Regression tests

Preserve the existing godot-12 tests.

In particular, do not break:

* traffic-light phase matching
* chunk ownership
* taxi stand rendering
* fuel station rendering
* roadwork rendering
* zoom redraw behaviour
* chunk unload/reload

Run all existing tests after the new tests.

---

# 17. Real-server verification

Run against the real Oulu server.

Verify representative examples of:

* tree collision
* roadside scenery collision
* fence/railing collision
* knocked-over/broken object if such an object can be encountered naturally

For each relevant category verify both:

1. visual location
2. collision behaviour

Force chunk unload/reload by travelling sufficiently far away and returning.

Verify that collision behaviour is identical before and after reload.

If a rare dynamic object cannot be encountered naturally, use a deterministic scripted state or existing test mechanism.

Do not alter the real production configuration to perform tests.

Use a scratch configuration/data override if required.

---

# 18. Performance

Use godot-12 as the baseline:

```text
~145 FPS selftest
~66 MiB memory
0 render backward steps
```

Do not materially regress this.

Avoid:

* per-frame scans over all trees
* per-frame collision reconstruction
* rebuilding all chunk collisions every frame
* unnecessary node creation/destruction
* global static-world searches
* OSM processing in Godot
* per-tick static object protocol traffic

Collision objects should be constructed when their chunk loads or when their relevant state changes.

---

# 19. Explicitly out of scope

Do NOT implement:

* remaining decorative/static world
* landuse rendering
* parking rendering unless required directly by collision work
* curbs
* pedestrian crossings
* generic signs
* labels
* building-detail parity
* rail bridges
* map-level visual work
* open-roof fuel station canopies
* fuel-price HUD
* traffic-light state beyond what godot-12 already implemented
* traffic-light bandwidth redesign
* day/night calendar
* seasonal system
* weather rendering
* navigation
* route planning
* pathfinding
* route protocol
* airport work
* railway gameplay changes
* vehicle physics redesign
* camera changes
* interpolation changes
* input changes
* binary protocol
* network architecture redesign

Do not opportunistically implement the remaining static-world rows.

Record them for the next appropriate phase.

---

# 20. godot-12 deferred issues

Do not accidentally lose these known issues:

### Fuel station canopy

Fuel pumps are currently hidden by Godot's solid building roof.

This belongs to the later open-roof-canopy/static-world work.

Do not redesign building rendering in this phase.

### Fuel price HUD

The nearest fuel station is not currently sent each tick.

Leave the fuel-price HUD work deferred.

### Distant traffic lights

Traffic-light phase state is intentionally limited to lights within 600 m.

Do not redesign that bandwidth policy in this phase.

---

# 21. Documentation

Update:

`docs/architecture/godot-pygame-rendering-parity.md`

Update the relevant architecture documentation if the collision/static-chunk architecture changes.

For each implemented parity row, record whether it is:

* Complete
* Partial
* Missing
* Different by design
* Debug-only
* Not applicable

Also identify whether remaining portions are:

* rendering
* protocol/data
* simulation
* collision
* architecture

Do not mark an item complete merely because its visual representation exists if its collision behaviour is still missing.

---

# 22. Validation commands

Run:

```bash
make godot-test
make godot-selftest
make audio-check
```

Run the relevant Python test suite.

Confirm the existing Python 3.10 packaging-test limitation remains understood and is not caused by this phase.

---

# 23. Git workflow

Keep the changes focused.

Suggested commits:

1. server/static collision data or protocol, if required
2. Godot collision/static-world implementation
3. tests and documentation

Push the commits to the current branch.

Do NOT create or push Git tags.

Do not rewrite unrelated commits.

---

# Definition of done

This phase is complete only when:

* collision-relevant trees are represented correctly
* collision-relevant scenery is represented correctly
* fences/railings are represented correctly
* knocked-over posts/broken lamps are correctly classified and represented
* collision behaviour matches the existing game's authoritative behaviour
* chunk loading/unloading works correctly
* no duplicate collision shapes occur
* no stale collision shapes remain after unload
* chunk boundaries do not create obvious collision gaps
* deterministic tests cover the new functionality
* existing godot-12 tests remain passing
* real-server verification has been performed
* vehicle/camera/background stability remains intact
* performance has not materially regressed
* `make godot-test` passes
* `make godot-selftest` passes
* `make audio-check` passes
* relevant Python tests pass
* parity documentation is updated
* changes are committed and pushed
* no Git tag is created

At the end, report:

1. exact files changed
2. protocol changes
3. server-side changes
4. Godot-side changes
5. collision architecture used
6. tests added
7. real-server verification performed
8. performance results
9. updated parity counts
10. remaining collision/static-world gaps
11. deferred issues
12. commit hashes

Do not claim an item complete if only its rendering is implemented while its collision behaviour remains incomplete.
