# godot-19 Replace 2.5D Buildings with GTA1-Style Top-Down Extrusion

## Goal

The current godot-17/18 building implementation is visually too close to an isometric/oblique projection.

Replace it with a **GTA1-style top-down building representation**.

The intended visual model is:

> The world is viewed straight from above. Building footprints remain exactly on the ground plane. Buildings are extruded vertically upward from those footprints, creating visible vertical wall surfaces. The camera itself is never tilted, and the building geometry must not be projected diagonally as if the world were isometric.

This is a rendering correction, not a gameplay or camera change.

---

## 1. Important distinction

The current implementation uses:

```text
ground_position + (-0.7, -1) * projected_height
```

Do **not** continue using this as the building-height projection model.

That makes the building appear to lean diagonally and creates an isometric/oblique visual impression.

The new implementation must instead model buildings as:

```text
ground footprint
        │
        │ vertical wall
        │
        │ building height
        ▼
raised roof
```

The map remains completely top-down.

---

## 2. Intended GTA1-style appearance

Think of a classic GTA1-style city view:

* roads are flat
* sidewalks are flat
* vehicles are flat/top-down
* pedestrians are flat/top-down
* terrain is flat/top-down
* the camera looks straight down
* buildings have a footprint on the ground
* building walls rise vertically from that footprint
* roofs sit directly above the footprint
* taller buildings have taller visible walls
* buildings do not lean toward a diagonal vanishing direction

The visual result should read as:

**top-down city + extruded buildings**

not:

**top-down city + miniature isometric buildings**

---

## 3. Coordinate model

Establish a simple, explicit rendering model.

For each building polygon:

```text
ground polygon = exact OSM/building footprint

roof polygon = same footprint translated only in screen-space by the
               chosen vertical-height representation

wall = vertical surface connecting corresponding ground and roof edges
```

The important point is that the **horizontal X/Y position of the building does not change because of its height**.

A building at map coordinate `(x, y)` must remain horizontally aligned with `(x, y)` regardless of whether it is:

* 5 m high
* 20 m high
* 100 m high

Height must not create a diagonal displacement across the map.

---

## 4. Define the vertical extrusion representation

Because Godot's 2D renderer has no literal vertical axis, define one dedicated screen-space representation for vertical building height.

Use a single configurable constant such as:

```text
BUILDING_HEIGHT_SCALE
```

where:

```text
screen_vertical_offset = building_height * BUILDING_HEIGHT_SCALE
```

The offset must be **vertical in the rendered map**, not diagonal.

Do not use:

```text
(-0.7, -1)
```

or any equivalent diagonal vector.

Do not introduce camera tilt.

Do not introduce perspective.

Do not introduce an isometric basis.

Do not introduce a player-relative projection.

---

## 5. Preserve the ground footprint

The building's ground footprint must remain exactly where it is currently rendered.

For example:

```text
ground footprint
┌──────────────┐
│              │
│   building   │
│              │
└──────────────┘
```

The roof should remain horizontally aligned with this footprint:

```text
       roof
┌──────────────┐
│              │
└──────────────┘
       │
       │ walls
       │
┌──────────────┐
│              │
└──────────────┘
      ground
```

Do not shift the roof diagonally.

---

## 6. Visible wall selection

Determine visible wall surfaces according to the actual top-down camera orientation.

Do not use the current "south and east" rule merely because it happened to match the previous projection.

Instead:

1. Establish the actual screen/up direction of the current top-down camera.
2. Determine which polygon edges face the camera's visible direction.
3. Render those vertical wall surfaces.
4. Keep the result deterministic for arbitrary polygon winding.

For a rectangular building, the viewer should see the two appropriate exterior wall sides.

For arbitrary polygons:

* concave polygons must work
* L-shaped buildings must work
* holes must not break the renderer if holes are already supported
* clockwise and counter-clockwise point ordering must produce identical visual results

Do not introduce a perspective-based visibility calculation.

---

## 7. Wall geometry

For every visible ground edge:

```text
ground A ───────── ground B
     │                 │
     │                 │
     │                 │
roof A  ─────────── roof B
```

Create a wall polygon connecting the ground edge to its corresponding raised edge.

The wall should be:

* vertical
* aligned with the ground edge
* constant height for the building
* coloured using the existing wall colour
* free of diagonal shear

The roof remains a separate top surface.

---

## 8. Building height

Continue using the server-provided building height.

Preserve the existing fallback height calculation.

Do not change the server's physical/building data model unless necessary.

The important change is purely how height is visualized.

Very tall buildings must show substantially taller walls.

Avoid the old hard diagonal projection cap unless profiling or visual testing demonstrates that a cap is required for screen readability.

If a visual cap is needed, make it a separate clearly documented rendering constant.

---

## 9. Roofs

Preserve:

* roof colour
* roof polygon
* pitched-roof flag
* roof ridge
* existing roof styles

For a flat roof:

```text
      ┌──────────────┐
      │     ROOF     │
      └──────────────┘
      █              █
      █    WALL      █
      █              █
      └──────────────┘
```

For a pitched roof, the roof geometry may have its own visual treatment, but it must still remain aligned with the building footprint.

Do not turn pitched roofs into an isometric roof projection.

---

## 10. Windows

Keep the existing window functionality.

Windows must now attach to the new vertical wall surfaces.

For each visible wall:

* determine wall length
* determine building floor count
* place windows according to the existing Pygame-derived rules
* keep deterministic building-position seeding
* preserve the current lit-window probability
* preserve night-time lighting behaviour

Windows must not float outside the wall.

Windows must not inherit a diagonal building-height projection.

At night, lit windows should continue to fade according to the existing night level.

---

## 11. Doors / entrances

Preserve the current entrance data.

A door should be attached to the corresponding visible wall.

If an entrance belongs to a wall that is not visible from the top-down camera, no door needs to be rendered there.

The door must follow the same vertical-wall geometry as the wall itself.

---

## 12. Building draw order

Preserve correct top-down occlusion.

Recommended conceptual order:

1. ground/map
2. ground-level objects
3. building walls from appropriate far-to-near order
4. roofs
5. objects that intentionally appear above buildings
6. UI

Do not solve ordering by moving the entire building diagonally.

Across chunks, retain deterministic ordering.

If overlapping building volumes exist, make the ordering deterministic and document the rule.

---

## 13. Canopies and fuel stations

Keep the existing open-roof canopy implementation.

A canopy is also a vertically extruded structure:

* posts rise vertically from their ground positions
* roof remains aligned with the canopy footprint
* pumps remain visible through the transparent/open canopy

Verify specifically:

* St1 Limingantie
* Neste station
* pumps
* price board

The price board must remain visible according to the established layering rules.

Do not allow the new building renderer to accidentally turn canopies into opaque buildings.

---

## 14. Bridges and underground levels

Do not apply the new building renderer to:

* bridges
* rail decks
* underground roads
* other elevated infrastructure

Preserve the existing bridge ordering.

Preserve the underground dark-level rendering.

Verify that buildings do not unexpectedly cover underground geometry.

---

## 15. Camera

Do not modify the camera.

The current top-down camera must remain:

* top-down
* non-tilted
* non-isometric
* non-perspective

Do not add:

* camera pitch
* camera yaw
* perspective projection
* isometric projection
* player-relative building projection

The player vehicle and roads must look exactly as they do now.

---

## 16. Performance

The current godot-17 report claimed approximately 145–151 FPS, but actual gameplay has also been observed to drop below 15 FPS.

This phase is primarily a visual geometry correction, but do not make the performance problem worse.

Building geometry should remain:

* generated when a chunk is loaded
* batched
* cached appropriately
* not regenerated every frame

Do not create one scene node per wall/window.

Do not introduce per-frame building geometry calculations.

After implementing the new geometry, record:

* average FPS
* 1% low FPS
* worst frame time
* chunk load time
* static memory
* number of buildings
* number of walls
* number of windows
* number of lit windows

If the new geometry significantly reduces or increases frame time, report why.

---

## 17. Remove the old projection model

Remove the conceptual dependency on:

```text
(-0.7, -1) × height
```

and the associated:

```text
min(0.35 × h, 11.1 m)
```

projection.

Do not leave the old projection code as a second active rendering path.

If useful for regression/debugging, the old implementation may remain temporarily in Git history, but the production renderer must use only the new GTA1-style extrusion model.

---

## 18. Tests

Update the Godot tests to validate the new geometry.

Tests must verify:

### Footprint

The ground footprint is unchanged.

### Height

A taller building produces a taller vertical wall.

### Alignment

The roof remains horizontally aligned with the ground footprint.

Explicitly test that increasing height does **not** change the building's horizontal map position.

### Wall geometry

For a simple rectangular building:

* ground edge coordinates are correct
* raised edge coordinates are vertically displaced
* wall corners remain vertically aligned

### Point order

Clockwise and counter-clockwise polygons produce equivalent results.

### L-shape

An L-shaped building produces correct wall segments without the old diagonal projection.

### Roof

Roof remains aligned with the footprint.

### Windows

Windows remain attached to wall surfaces.

### Doors

Visible-wall doors render correctly.

Hidden-wall entrances remain hidden.

### Determinism

Two rebuilds of the same building produce identical geometry, including lit windows.

### Canopies

Canopy posts and roof use the same vertical extrusion concept without hiding pumps.

### Layering

Bridges and underground rendering remain correct.

### Collision

No client-side collision or physics is introduced.

---

## 19. Visual verification

Create or update a development test scene containing:

* one low rectangular building
* one tall rectangular building
* one L-shaped building
* one pitched-roof building
* one commercial building with many windows
* one building with an entrance
* one canopy
* roads immediately adjacent to buildings

The test scene should make the difference between:

**correct GTA1-style extrusion**

and:

**incorrect isometric/diagonal projection**

obvious.

Check the scene at multiple zoom levels.

The visual result must remain top-down at every zoom level.

---

## 20. Real Oulu verification

Run against the real Oulu server.

Check at minimum:

* St1 Limingantie
* Neste station
* Liiketulli
* dense central Oulu
* low residential buildings
* tall buildings
* L-shaped buildings where available
* buildings beside roads
* dusk
* night
* winter
* bridges
* underground roads

Specifically verify that:

1. roads remain completely top-down
2. buildings do not visually lean
3. building height appears as vertical wall height
4. taller buildings have taller walls
5. roofs stay aligned with footprints
6. windows stay attached to walls
7. doors stay attached to walls
8. canopies remain open
9. pumps remain visible
10. no old Pygame/isometric appearance has returned

---

## 21. Parity documentation

Update:

* `godot-pygame-rendering-parity.md`
* `godot-client.md`

Describe the building renderer as:

> GTA1-style top-down vertical building extrusion

Do not describe it as:

* isometric
* oblique projection
* pseudo-isometric
* perspective building projection

The existing parity status may remain "Different by design" because Godot is intentionally using a different rendering model from the old Pygame renderer.

---

## 22. Acceptance criteria

The phase is complete only when:

* Buildings no longer look isometric.
* The camera remains completely top-down.
* Roads remain completely top-down.
* Vehicles remain completely top-down.
* Building footprints remain exactly on the ground.
* Building walls rise vertically from their footprints.
* Building height controls wall height rather than diagonal displacement.
* Roofs remain aligned with the building footprints.
* Arbitrary building polygons work.
* L-shaped buildings work.
* Windows work on the new wall surfaces.
* Doors work on the new wall surfaces.
* Lit windows remain deterministic.
* Canopies remain open and do not hide pumps.
* Bridges remain correctly layered.
* Underground rendering remains correct.
* No client physics/collision/navigation is introduced.
* No old `(-0.7, -1)` building projection remains in the active renderer.
* All existing tests pass.
* New geometry tests pass.
* Real Oulu verification passes.
* Performance does not regress materially.
* The <15 FPS issue is not hidden by reducing visual quality.
* Changes are committed and pushed.
* No Git tag is created or pushed.

## Final report

Report:

1. What caused the previous isometric appearance.
2. How the new GTA1-style extrusion works.
3. Exact vertical height scale used.
4. How visible walls are selected.
5. How roofs are aligned.
6. How windows and doors were adapted.
7. St1/Neste verification results.
8. Performance before/after.
9. 1% low FPS and worst frame time.
10. Python test count.
11. Godot test count.
12. Parity count changes.
13. Any remaining visual issues.
14. Commit hash.

Do not proceed to navigation or other major visual features until this building representation has been visually verified.
