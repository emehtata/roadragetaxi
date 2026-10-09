# godot-20: GTA1/GTA2-Style Building Facades

## Goal

The previous godot-18 implementation interpreted "GTA1-style" incorrectly.

The resulting buildings still look like an isometric/2.5D projection. That is NOT the intended result.

The attached reference screenshots are the visual target for this phase.

The target is the classic **GTA1/GTA2-style top-down city rendering**, where:

* the ground/map remains top-down
* roads remain top-down
* vehicles remain top-down
* the camera remains fixed and top-down
* building footprints remain aligned with the map
* building height creates visible facade depth
* facades extend from the roof/footprint toward the camera-facing side
* buildings visually open toward the surrounding streets
* tall buildings have deep facades
* the result looks like a top-down game with extruded building facades

It must NOT look like an isometric game.

---

# 1. Reference images are authoritative

Use the two attached reference screenshots as the visual target.

The important characteristic is visible in both screenshots:

### Buildings at the top of the screen

Their facades extend **downward toward the visible play area**.

### Buildings at the bottom of the screen

Their facades extend **upward toward the visible play area**.

### Buildings at the left/right sides

Their visible facades extend toward the play area according to the corresponding camera-facing direction.

This creates the characteristic GTA visual:

```text
                 SCREEN TOP

        ┌─────────────────────┐
        │       ROOF          │
        └─────────────────────┘
          ╲
           ╲  FACADE
            ╲
             ╲
              ───────────────
                    STREET

                 SCREEN BOTTOM
```

The exact geometry depends on the building edge and camera-facing direction.

Do NOT interpret this as:

> "Move every roof vertically upward on screen."

That was the mistake in the previous implementation.

---

# 2. The fundamental rendering model

The correct model is:

```text
MAP / GROUND PLANE
        │
        │ building height
        ▼
BUILDING VOLUME
        │
        ▼
VISIBLE FACADE
        │
        ▼
ROOF
```

But because this is a 2D renderer, the vertical world dimension must be represented by a **fixed oblique screen-space projection**, just like classic GTA.

The important distinction is:

### Ground geometry

Remains completely top-down.

### Building volume

Uses a dedicated vertical projection.

### Camera

Does NOT become isometric.

Do not tilt the entire world.

---

# 3. Do not use the previous model

The previous implementation used:

```text
(-0.7, -1) × height
```

This must be removed from the active building renderer.

That model applies one global diagonal displacement to the entire building.

It does not reproduce the reference images.

Do not replace it with:

```text
(0, -1) × height
```

either.

That would simply create vertically displaced buildings and again fail to reproduce the reference.

---

# 4. Correct projection concept

Define a fixed **building vertical projection vector**.

For example conceptually:

```text
BUILDING_VERTICAL_VECTOR = Vector2(vx, vy)
```

This vector represents how one metre of real-world building height appears in the 2D game.

However:

**The vector is only applied to the vertical building dimension.**

It is NOT applied to:

* roads
* terrain
* vehicles
* pedestrians
* map coordinates
* building footprints

The ground footprint remains untouched.

---

# 5. Critical: facade direction

The reference screenshots show that visible facade surfaces are selected according to the side of the building facing the camera/play area.

For each building edge:

1. Determine its ground-plane direction.
2. Determine its outward normal.
3. Compare that normal with the camera-facing direction.
4. Select the visible facade edges.
5. Extrude those edges using the building vertical projection.

For a rectangular building, this normally produces two visible facade sides.

For example:

```text
              NORTH

        ┌──────────────┐
        │              │
        │    ROOF      │
        │              │
        └──────────────┘
         ╲            ╱
          ╲          ╱
           ╲        ╱
            ╲      ╱
             FACADE

              STREET
```

The exact visible sides must be determined geometrically, not hard-coded as "south and east".

The algorithm must work regardless of polygon winding.

---

# 6. Building volume geometry

For every visible building edge:

```text
ground A ---------------- ground B
   │                          │
   │                          │
   │      VERTICAL            │
   │      BUILDING            │
   │      HEIGHT              │
   │                          │
roof A -------------------- roof B
```

But the **roof edge is displaced using the fixed building-height projection vector**, not by moving the entire building footprint.

Thus:

```text
ground edge
      \
       \
        roof edge
```

The displacement represents the visible height of the wall.

The wall polygon connects:

```text
ground edge
     ↓
projected roof edge
```

The resulting wall must look like the facades in the reference screenshots.

---

# 7. Roof vs ground footprint

This distinction is essential.

The building has two representations:

### Ground footprint

The exact OSM building polygon.

Used for:

* map position
* world alignment
* ground-level relationships

### Raised roof polygon

The same footprint after applying the building-height projection.

Used only for:

* roof rendering
* connecting visible facades

Do NOT distort the ground footprint.

Do NOT rotate it.

Do NOT shear it.

Do NOT change its scale.

---

# 8. Why the reference looks different from isometric

The target is NOT an isometric projection.

There is:

* no isometric grid
* no 30°/30° world projection
* no rotated map
* no perspective camera
* no vanishing point
* no player-relative camera
* no transformation of roads

The ground plane stays orthographic/top-down.

Only the building's vertical dimension receives the special projection.

This is exactly the kind of selective 2.5D rendering used by classic GTA-style games.

---

# 9. Building height

Use the existing server-provided building height.

Do not change the server data model.

The visual height must scale approximately linearly:

```text
visual_facade_depth = building_height × BUILDING_HEIGHT_SCALE
```

Do not use the old arbitrary 11.1 m cap unless profiling/visual testing proves that a cap is necessary.

Tall buildings should visibly have much deeper facades.

The Liiketulli building is an important test case.

---

# 10. Perspective direction must remain fixed

The projection direction is a property of the **game camera**, not of the player.

It must not depend on:

* taxi position
* building position
* distance to camera
* chunk
* zoom
* map latitude/longitude

Every building uses the same building-height projection basis.

---

# 11. Visible facades and screen position

The visual effect should reproduce this relationship:

```text
                 TOP OF SCREEN

          ┌───────────────┐
          │     ROOF      │
          └───────────────┘
             ╲
              ╲
               ╲ FACADE
                ╲
                 ╲
              STREET


              STREET

                 ╱
                ╱
               ╱ FACADE
              ╱
             ╱
          ┌───────────────┐
          │     ROOF      │
          └───────────────┘

               BOTTOM
```

This is the visual relationship to reproduce.

Do not make every building extend in the same screen direction regardless of its location.

The visible facade is determined by the building edge orientation and the fixed camera projection.

---

# 12. Arbitrary polygons

The implementation must work for:

* rectangles
* L-shaped buildings
* concave polygons
* irregular OSM building footprints
* clockwise point ordering
* counter-clockwise point ordering

For every polygon:

1. construct ground edges
2. calculate outward normals
3. identify camera-visible edges
4. project their upper endpoints
5. construct facade polygons
6. construct roof
7. sort visible facade geometry correctly

Do not assume every building is rectangular.

---

# 13. Facade ordering

Visible facades must be drawn in deterministic far-to-near order.

The ordering must be based on geometry and camera direction, not arbitrary chunk ordering where that produces visible incorrect overlaps.

For example:

```text
far facade
     ↓
near facade
     ↓
roof
```

The roof should cover the appropriate upper parts of the facades.

Buildings from neighbouring chunks must still produce visually correct ordering.

Do not introduce per-frame global sorting.

Build the ordering when static chunk geometry changes.

---

# 14. Windows

Preserve the existing window system.

Windows must be attached to facade surfaces.

Their positions must be derived from:

* facade endpoints
* facade direction
* floor index
* horizontal window index

The window must move together with the facade when building height changes.

Do not place windows directly in map coordinates independently of the wall geometry.

Preserve:

* floor count
* deterministic seed
* window probability
* lit-window probability
* night fade
* deterministic rebuild behaviour

---

# 15. Doors

Doors must be attached to the appropriate visible facade.

For an entrance:

1. determine which building edge contains the entrance
2. determine whether that edge is visible
3. place the door on that facade
4. project it using the same building-height geometry

A hidden entrance must remain hidden.

---

# 16. Pitched roofs

Preserve pitched roofs.

The roof geometry must sit on the raised footprint.

The ridge must follow the existing roof rules.

Do not create an isometric roof.

The roof is still a top-down polygon with the building-height projection applied to its elevation.

---

# 17. Canopies

Canopies are also elevated structures, but remain open.

Preserve:

* vertical posts
* raised canopy roof
* transparent/open roof
* visible pumps
* price boards

Specifically verify:

* St1 Limingantie
* Neste

The canopy must not become an opaque building.

---

# 18. Bridges and underground rendering

Do not apply this building renderer to:

* rail bridges
* road bridges
* bridge decks
* underground roads
* other infrastructure

Preserve the current layering.

Buildings must not unexpectedly cover underground roads.

---

# 19. Camera must NOT change

Do not modify the current camera.

Do not add:

* camera pitch
* camera yaw
* perspective
* isometric projection
* camera-relative world rotation

The player, road markings, sidewalks and terrain must remain visually identical to the current top-down renderer.

---

# 20. Performance

The current project has a separate serious performance issue where real gameplay has been observed below 15 FPS.

Do not solve this phase by removing building detail.

Do not solve it by disabling facades.

Do not solve it by reducing building height.

Do not solve it by disabling windows.

Keep the renderer batched and static.

Building geometry must be generated only when required:

* initial chunk load
* chunk rebuild
* relevant static-state change

Never regenerate all building geometry every frame.

---

# 21. Visual test scene

Create a deterministic visual test containing:

1. Low rectangular building.
2. Tall rectangular building.
3. L-shaped building.
4. Pitched-roof building.
5. Tall commercial building with many windows.
6. Building with entrance.
7. Canopy.
8. Road surrounding the buildings.

The scene should resemble the reference screenshots when viewed from the current camera.

The most important visual test is:

> Can a viewer immediately recognize the building style as classic GTA1/GTA2 rather than isometric?

If not, continue adjusting the building projection before considering the phase complete.

---

# 22. Real Oulu verification

Run against the real Oulu server.

Verify:

* central Oulu
* Liiketulli
* St1 Limingantie
* Neste
* tall buildings
* low buildings
* irregular buildings
* dense building areas
* night
* dusk
* winter
* bridges
* underground roads

Pay special attention to buildings bordering roads.

The facade should visually occupy the space between the building roof and the surrounding street in the same way as the reference screenshots.

---

# 23. Tests

Update/add Godot tests for:

* projection vector
* ground footprint unchanged
* roof projection
* facade projection
* visible-edge selection
* clockwise polygon
* counter-clockwise polygon
* L-shaped polygon
* height scaling
* window attachment
* door attachment
* deterministic rebuild
* canopy geometry
* bridge layering
* underground layering

The tests must explicitly verify that:

### Ground footprint

Does not move when building height changes.

### Roof

Does move according to the building-height projection.

### Facade

Connects ground edge to projected roof edge.

### Height

Increasing height increases facade depth.

### Horizontal world position

Does not change.

---

# 24. Acceptance criteria

The phase is complete only when:

* The current isometric-looking building result is gone.
* The result visibly resembles the supplied GTA1/GTA2 screenshots.
* Roads remain top-down.
* Terrain remains top-down.
* Vehicles remain top-down.
* The camera remains unchanged.
* Building footprints remain exact.
* Building height creates facade depth.
* Facades project in the correct GTA-style direction.
* Top and bottom screen buildings produce the characteristic facade relationship visible in the reference screenshots.
* Tall buildings have deeper facades.
* Arbitrary polygons work.
* L-shaped buildings work.
* Windows attach correctly to facades.
* Doors attach correctly to facades.
* Pitched roofs remain correct.
* Canopies remain open.
* Pumps remain visible.
* Bridges remain correct.
* Underground rendering remains correct.
* No client physics/collision/navigation is introduced.
* The old `(-0.7, -1)` projection is gone from the active building renderer.
* Existing tests pass.
* New geometry tests pass.
* Real Oulu verification passes.
* Performance does not materially regress.

---

# 25. Documentation

Update:

* `godot-pygame-rendering-parity.md`
* `godot-client.md`

Describe the renderer as:

> GTA1/GTA2-style top-down building facade extrusion.

Do not describe it as:

* isometric
* pseudo-isometric
* oblique world projection
* perspective camera

---

# 26. Git

When complete:

* commit the changes
* push the branch
* do NOT create a Git tag

---

# Final report

Report:

1. How the previous implementation differed from the reference.
2. The exact new building projection model.
3. The building vertical projection vector.
4. How visible facade edges are selected.
5. How roof and ground footprints relate.
6. How windows and doors are attached.
7. Real Oulu verification.
8. St1/Neste verification.
9. Performance measurements.
10. Python test count.
11. Godot test count.
12. Remaining visual differences from the supplied screenshots.
13. Commit hash.

The supplied screenshots are the visual authority for this phase. If the result still looks isometric, the phase is not complete.
