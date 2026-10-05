# Godot-17: 2.5D Building Perspective

Continue the Godot migration from the current repository state.

`godot-16` is complete and pushed. Do not create or push a Git tag. You may create commits and push them to the remote.

The static world is now considered complete. Before moving to navigation, replace the current flat top-down building presentation with a lightweight **top-down 2.5D building perspective**.

This is an intentional rendering change, not a return to the old Pygame isometric/facade renderer.

## Goal

Keep the game fundamentally top-down while giving buildings real visual depth based on their height.

The desired result is:

* roads remain top-down and geometrically undistorted
* the building footprint remains exactly where it is on the map
* the roof remains visible from above
* building height produces projected side/facade surfaces
* taller buildings visibly extend farther in perspective
* low buildings have shallow sides
* tall buildings have clearly visible sides
* the result feels spatially deep without turning the entire game into an isometric view
* the taxi, roads, pedestrians and navigation geometry remain in the existing top-down coordinate system

Think of this as:

**top-down map + projected building volume**

not:

**isometric camera**

## Critical architectural rule

Do not restore the old Pygame slanted-building renderer.

The Godot rendering architecture remains the source of truth for presentation.

The building's map footprint and height are authoritative map data.

Godot may project the building visually from that data, but it must not alter the actual map coordinates or gameplay geometry.

There must be no client-side collision introduced.

Navigation must continue to use the ground-plane representation later.

---

# 1. Inspect the current building implementation first

Before changing code, inspect:

* current Godot building rendering
* `chunk_detail.gd`
* `map_chunk.gd`
* `map_layer.gd`
* server building data
* `static_world.py`
* building protocol fields
* existing building tests
* Pygame building rendering
* current building height/roof information

Determine exactly what information is already available for each building:

* footprint polygon
* height
* roof colour
* roof style
* roof ridge
* doors/entrances
* canopy status
* building category/type
* map level if relevant

Do not add duplicate protocol fields if existing data is sufficient.

---

# 2. Define the projection model

Create one clear mathematical model for projecting building height into screen space.

The projection must be deterministic.

Conceptually:

```text
ground footprint
       ┌──────────────┐
       │              │
       │   building   │
       │              │
       └──────────────┘
          ↑
          │ height
          │
       projected
       facade
```

The vertical building displacement should have a consistent direction in screen space.

Do not independently choose a projection direction for each building.

The same world height must produce the same screen displacement everywhere.

The projection should be based on:

* building height
* camera orientation
* a configurable visual height scale

It must not depend on the building's distance from the player.

The objective is a stylised but physically understandable 2.5D representation.

---

# 3. Preserve the top-down map

Do not tilt the camera.

Do not rotate the world into an isometric projection.

Do not apply perspective distortion to:

* roads
* road markings
* pedestrians
* vehicles
* traffic islands
* railways
* terrain
* map labels

The ground plane must remain exactly as it is today.

Only elevated building geometry receives the depth projection.

This distinction is essential.

---

# 4. Building geometry

For each building footprint:

1. Draw the projected side/facade surfaces.
2. Draw the roof at the top of the projected volume.
3. Preserve the building footprint's original coordinates.
4. Use the building's authoritative height.
5. Handle arbitrary footprint polygons, not only rectangles.

For a polygon with vertices:

```text
A ───── B
│       │
│       │
D ───── C
```

create corresponding elevated vertices:

```text
A' ───── B'
│       │
│       │
D' ───── C'
```

where the primed vertices are the same ground positions plus the height projection.

Connect the appropriate edges to form the visible facade surfaces.

Do not assume every building is rectangular.

---

# 5. Visibility and face selection

Only draw facade surfaces that should be visible from the current top-down camera orientation.

Do not blindly draw every polygon edge as a wall.

The system should determine which building edges face the visible side of the world.

This must work for:

* rectangles
* L-shaped buildings
* irregular OSM building polygons
* concave footprints where supported

Avoid z-fighting between roof and facade.

Establish a deterministic rendering order:

1. ground/world
2. building facades
3. building roof/details
4. dynamic entities that should appear above the building layer

Follow the existing Pygame/Godot visual ordering where appropriate, but do not sacrifice the top-down architecture to copy implementation details.

---

# 6. Building height

Use the existing authoritative building height data.

Do not invent arbitrary heights for buildings that already have height information.

Where OSM/building data lacks a height:

* use the existing server fallback
* preserve current behaviour
* do not make the Godot client independently guess a different height

Document the fallback.

Height should visibly affect the result.

For example:

* single-storey building → shallow facade
* medium building → clearly visible facade
* high-rise → deep facade

Do not exaggerate heights so much that they obscure roads or dominate the screen.

Use a configurable rendering scale rather than hard-coding scattered multipliers.

---

# 7. Roofs

Preserve the roof information implemented in godot-16:

* roof colour
* flat roofs
* pitched roofs
* ridge
* existing roof styles

Adapt them to the new 2.5D representation.

A pitched roof should remain visually coherent when elevated.

Do not discard the existing roof-style implementation.

The roof should sit on top of the projected building volume rather than simply being drawn at the old ground position.

---

# 8. Building entrances and doors

Godot-16 added building entrances.

Preserve them.

Adapt their rendering to the new geometry.

An entrance should appear attached to the appropriate building surface/edge rather than floating on the ground.

However, do not implement door collision or navigation.

The server remains authoritative for any actual building-entry gameplay.

---

# 9. Windows and facade detail

This phase finally provides a valid surface for building windows.

Implement a suitable top-down 2.5D representation of windows on visible facades.

Requirements:

* windows must follow the facade surface
* windows must not float independently of the building
* lit windows should use the existing day/night state
* windows should not be individually heavyweight Godot nodes
* window rendering must remain batched or otherwise lightweight

Do not attempt to reproduce Pygame's old facade renderer pixel-for-pixel.

The goal is visual parity of intent:

* daytime windows visible appropriately
* nighttime lit windows visible
* taller buildings have more vertical facade presence

If the current server does not provide enough information for individual window placement, derive a deterministic pattern from the building footprint/height rather than adding large amounts of protocol data.

The pattern must be deterministic so the same building always looks the same after chunk reload.

---

# 10. Building shadows

Godot-15/16 currently use a height shadow.

Adapt the shadow to the new 2.5D geometry.

Avoid drawing both:

* an old flat shadow
* and a new facade projection

in a way that produces excessive darkness or doubled geometry.

The new representation should have a coherent relationship between:

* building height
* facade depth
* roof
* shadow

Do not implement real-time physically based shadows.

A lightweight stylised approximation is preferred.

---

# 11. Interaction with night lighting

Integrate the new building geometry with the existing:

* night tint
* street-light pools
* headlight beams
* lightning
* seasonal rendering

The existing night layer must remain correct.

Street lights and headlights should not suddenly illuminate only the old ground-plane building representation.

If a full physically correct interaction is too expensive, preserve the current visual model and document the deliberate approximation.

Do not introduce thousands of dynamic lights.

---

# 12. Interaction with canopies

Godot-16 fixed open-roof canopies and made fuel pumps visible.

Preserve that behaviour.

Canopies must not become opaque building volumes that hide:

* fuel pumps
* vehicles
* relevant objects underneath

If a canopy has a height, represent it as an elevated open structure rather than a solid building.

Do not regress the godot-16 fuel-station verification.

---

# 13. Bridges and other elevated structures

Do not accidentally apply the building renderer to:

* railway bridges
* road bridges
* bridge guardrails
* other existing elevated map structures

Those already have their own rendering logic.

However, make sure the new building projection does not break their z-order.

Verify scenes containing:

* buildings beside bridges
* buildings below/near elevated roads
* railway bridges
* underground levels

---

# 14. Underground levels

The building projection must respect the existing map-level system.

At underground levels:

* do not draw above-ground building geometry as if it were underground
* preserve the current level filtering
* preserve the taxi's map-level behaviour
* preserve underground roads

Do not redesign underground navigation.

---

# 15. Chunk architecture

Building geometry must remain chunk-local.

When a chunk loads:

* construct its building geometry once
* batch where possible
* do not create one heavy node per building unless absolutely necessary

When a chunk unloads:

* release its building rendering data
* do not leave orphaned facade/window nodes

A building crossing a chunk boundary must follow the existing one-owner rule.

Do not duplicate it.

If the building polygon is already owned by one chunk, its complete visual representation should remain associated with that owner.

---

# 16. Camera and zoom

The current camera behaviour must remain unchanged.

Do not alter:

* camera controls
* interpolation
* zoom semantics
* taxi centring
* input

At different zoom levels:

* building height should remain visually coherent
* geometry must not flicker
* roofs/facades must not separate
* windows must not become pathological noise

If a detail level is needed at extreme zoom levels, use deterministic LOD rather than per-frame rebuilding.

---

# 17. Performance

This is a critical part of the phase.

Godot-16 achieved:

* 145 FPS
* ~79.5 MiB static memory
* 0 backward rendering steps
* exact taxi centring
* ~0.4 ms chunk unload

The new building renderer must remain batched.

Do not create:

* one Node2D per wall
* one node per window
* one node per roof polygon
* one dynamic light per window

Prefer:

* one or a small number of drawing layers per chunk
* precomputed geometry
* compact arrays
* deterministic generation at chunk load

Measure:

* FPS
* memory
* chunk load time
* chunk draw time
* chunk unload time

Pay particular attention to Oulu, where there are many buildings.

If the initial implementation causes a large memory increase, optimize before considering the phase complete.

---

# 18. Tests

Extend the existing Godot test suite.

Add deterministic tests for:

* height projection
* known building footprints
* projected facade vertices
* face visibility
* roof placement
* pitched roof geometry
* building height differences
* windows on facades
* lit vs unlit windows
* building entrances
* chunk ownership
* chunk reload
* no duplicate geometry
* underground level filtering
* canopy visibility
* bridge z-order

Use simple synthetic building polygons for geometry tests.

Do not rely solely on screenshots for mathematical projection tests.

Python tests should be added only where server/protocol behaviour changes.

Do not change server semantics merely to support a rendering preference.

---

# 19. Visual verification

Create a deliberate test scene containing:

* a small one-storey building
* a medium building
* a tall building
* an irregular building
* a pitched-roof building
* a building with an entrance
* a building near a road
* a building near a bridge
* a building near a street light
* a canopy/fuel station

Check the scene at:

* daytime
* dusk
* night
* winter
* summer
* normal zoom
* close zoom
* distant zoom

The result should immediately communicate building height.

The roads themselves must still look flat/top-down.

---

# 20. Real-server Oulu verification

Use the real Oulu server.

Verify:

1. Existing buildings are rendered with visible height.
2. Tall buildings have visibly deeper facades than low buildings.
3. Roofs remain correctly positioned.
4. Pitched roofs remain coherent.
5. Entrances remain attached to buildings.
6. Windows are attached to visible facades.
7. Lit windows behave correctly at night if implemented.
8. Canopies still leave fuel pumps visible.
9. Buildings near bridges have correct z-order.
10. Underground levels remain correct.
11. Chunk unload/reload produces identical building geometry.
12. Existing road, taxi, pedestrian, rail and static-world rendering remains intact.
13. Night tint and street-light rendering remain intact.
14. Seasonal rendering remains intact.

Take screenshots before and after at representative Oulu locations.

---

# 21. Parity table

Update `godot-pygame-rendering-parity.md`.

The current building status is:

* building top-down roof/height representation: complete but different by design
* lit windows: partial/missing due to lack of suitable facade surface

After this phase, update the statuses according to the actual implementation.

Do not claim pixel-perfect Pygame parity.

This phase intentionally establishes a **different but more appropriate Godot representation**.

---

# 22. Documentation

Update:

* `godot-pygame-rendering-parity.md`
* `godot-client.md`

Document:

* the 2.5D projection model
* height scaling
* facade visibility
* roof projection
* window rendering
* entrance rendering
* canopy handling
* chunk ownership
* performance
* deliberate differences from Pygame

Clearly state that the game remains top-down and that only elevated building geometry receives the 2.5D projection.

---

# 23. Do not implement navigation yet

This phase must not implement:

* pathfinding
* route calculation
* navigation meshes
* road graph traversal
* pedestrian routing
* vehicle routing
* traffic AI changes

The purpose of this phase is to establish the final visual building representation before navigation.

Navigation will use the existing ground-plane world representation later.

---

# 24. Acceptance criteria

The phase is complete only when:

* The game remains fundamentally top-down.
* Buildings have visible perspective/depth based on authoritative height.
* The old flat building appearance is replaced.
* The old Pygame isometric/facade renderer is not restored.
* Arbitrary building footprints work.
* Facade visibility is deterministic.
* Roofs remain correctly positioned.
* Pitched roofs remain coherent.
* Entrances remain attached to buildings.
* Windows can now be represented on suitable visible facades.
* Lit windows integrate with the existing day/night state where implemented.
* Canopies remain open and fuel pumps remain visible.
* Existing bridges and underground levels are unaffected.
* Chunk loading/unloading remains correct.
* No client-side collision is introduced.
* No navigation is introduced.
* Performance remains close to the godot-16 baseline.
* Python tests pass where applicable.
* Godot tests pass.
* Real-server Oulu verification succeeds.
* Documentation is updated.
* Changes are committed and pushed.
* No Git tag is created or pushed.

At the end, provide a concise report containing:

1. Files changed
2. Projection model
3. Building data used
4. Godot rendering changes
5. Window/entrance changes
6. Canopy handling
7. Tests
8. Real-server Oulu verification
9. Performance measurements
10. Updated parity counts
11. Remaining gaps
12. Commit hashes

Do not stop at an architectural proposal. Implement the phase fully.
