# godot-18: Lightweight 3D Building Layer Prototype

## Goal

The current 2D 2.5D building renderer has become too complex and produces visible snapping when the facade direction changes relative to the screen.

Stop extending the current radial 2D facade-projection implementation.

Instead, prototype a fundamentally different architecture:

> **2D/top-down game + an extremely lightweight 3D building layer**

The goal is to determine whether Godot's 3D renderer with an orthographic camera can reproduce the desired GTA1/GTA2-style building appearance smoothly, while leaving the actual game world fundamentally top-down and 2D.

This phase is a **prototype/evaluation phase**, not yet a full migration of all buildings.

---

# 1. Reference visual target

The supplied GTA-style reference screenshots remain the visual target.

The desired result has:

* a top-down map
* top-down roads
* top-down vehicles
* top-down gameplay
* buildings with real vertical height
* visible building facades
* roofs above those facades
* smooth changes in visible facade geometry as the camera/world moves
* no sudden switching between predefined facade directions

The building layer should visually resemble classic GTA-style city rendering.

Do NOT try to reproduce the appearance by manually switching between 2D facade polygons.

The purpose of using 3D is specifically to make the building visibility and facade transitions continuous.

---

# 2. Important architecture

The prototype must separate:

## Existing 2D gameplay world

Keep:

* map
* roads
* terrain
* road markings
* vehicles
* pedestrians
* traffic lights
* trains
* signs
* HUD
* gameplay
* server state

in the existing 2D/top-down architecture.

Do not convert the entire game to 3D.

## New 3D building layer

Use Godot's 3D renderer only for:

* building volumes
* building roofs
* building facades
* building windows if practical
* other building-specific vertical geometry

The 3D building layer is a visual overlay.

It must not become the gameplay simulation layer.

---

# 3. Camera

Use a dedicated Godot 3D camera for the building layer.

The camera should initially be:

* orthographic
* top-down
* fixed orientation relative to the game world
* no perspective distortion
* no camera roll
* no dynamic camera rotation

The existing 2D gameplay camera remains authoritative for gameplay.

The 3D camera must be synchronized with the 2D camera's:

* position
* zoom/scale
* viewport
* orientation

so that map coordinates line up precisely.

---

# 4. Do NOT tilt the entire game

The following must remain completely unaffected:

* roads
* terrain
* vehicles
* pedestrians
* map labels
* HUD
* gameplay coordinates

Do not replace the existing 2D camera.

Do not rotate the entire world.

Do not introduce an isometric projection to the gameplay map.

The 3D layer exists only to render buildings.

---

# 5. Coordinate mapping

Establish a deterministic mapping between the existing 2D world coordinates and the 3D building world.

For example:

```text
2D world:

(x, y)

        ↓ deterministic mapping

3D:

(x, 0, y)
```

Use a consistent Godot 3D axis convention.

Do not modify server coordinates.

Do not modify map data.

Do not introduce a second coordinate system in the server.

The same building footprint must occupy exactly the same ground position in both renderers.

---

# 6. Building geometry

For each building footprint:

1. Read the existing polygon.
2. Convert it into a 3D polygon at ground level.
3. Extrude it vertically using the server-provided building height.
4. Generate the roof from the upper polygon.
5. Generate side faces between corresponding ground and roof edges.

Conceptually:

```text
             ROOF
        ┌──────────────┐
       /              /|
      /              / |
     └──────────────┘  |
     │                │ |
     │                │ |
     │                │ |
     └────────────────┘
            GROUND
```

The building must be a real 3D volume.

Do not manually calculate screen-space facade direction.

Do not use the previous radial projection.

Do not use:

```text
(-0.7, -1) * height
```

or any equivalent 2D projection.

---

# 7. Building height

Use the existing server-provided building height.

Preserve the current fallback height.

A 10 m building must physically be approximately twice the rendered height of a 5 m building.

A tall building such as Liiketulli must visibly have substantially deeper facades than a low building.

Do not artificially move the entire building footprint.

---

# 8. Camera experimentation

The key prototype task is finding the correct camera configuration.

Test an orthographic 3D camera with a small controlled tilt/elevation if required to reproduce the reference appearance.

This is the one place where a camera angle may be used.

However:

> The 2D gameplay world itself must remain top-down.

Only the building layer may use the elevated 3D camera.

Try to find the smallest camera elevation that produces the desired GTA-style facade visibility.

Do not use a conventional modern 3D-game camera.

Do not introduce perspective unless the reference cannot reasonably be reproduced with orthographic projection.

Prefer orthographic.

---

# 9. Critical visual requirement

The prototype must demonstrate that facade visibility changes **continuously**.

As the camera/world scrolls:

```text
building moves through viewport
        ↓
visible facade changes continuously
        ↓
no discrete wall switching
        ↓
no snapping
```

This is one of the primary reasons for using 3D.

There must be no code such as:

```text
if building_is_at_top_of_screen:
    show_north_wall
else:
    show_south_wall
```

or equivalent directional state switching.

Let the 3D renderer determine visible surfaces naturally.

---

# 10. Roofs

Generate roofs as actual 3D top surfaces.

For a flat roof:

```text
top polygon at building height
```

For pitched roofs:

* preserve the existing pitched-roof information
* create a simple roof volume or roof geometry
* keep the roof aligned with the building footprint

Do not over-engineer roof geometry in this prototype.

The first goal is correct overall appearance and smooth facade transitions.

---

# 11. Windows

Do not immediately port the entire existing window system.

First establish whether the 3D building representation works visually.

For the prototype, use simple deterministic facade window geometry/materials.

Possible implementations:

* small emissive/bright quads slightly above facade surfaces
* simple window textures
* batched window geometry

Avoid one Godot node per window.

Night-time lit windows must remain possible, but full parity can be handled after the prototype succeeds.

---

# 12. Doors

For the prototype:

* preserve entrance positions
* place a simple door marker/quad on the corresponding building facade
* ensure it follows the 3D building surface

Full parity is not required until the 3D architecture is accepted.

---

# 13. Materials

Keep materials extremely simple.

Prefer:

* untextured materials
* existing building colours
* simple roughness
* no expensive PBR effects
* no dynamic shadows initially

Do not introduce:

* realistic reflections
* ambient occlusion
* complex shaders
* expensive post-processing

The visual target is a stylized classic game, not modern 3D graphics.

---

# 14. Lighting

Do not use expensive real-time lighting initially.

The building colour should primarily come from:

* existing roof colour
* existing wall colour
* current global day/night state

If necessary, use a simple directional light or unshaded/simple materials.

The existing 2D night layer must remain compatible with the building layer.

Test:

* noon
* dusk
* night
* winter

---

# 15. Shadows

Do not initially enable expensive real-time building shadows.

If a simple shadow is required for visual evaluation, implement the cheapest practical solution.

The prototype must first establish:

> Does lightweight 3D solve the visual problem?

before adding secondary effects.

---

# 16. Rendering integration

The 3D building layer must visually integrate with the existing 2D renderer.

Investigate the cleanest Godot approach for:

* rendering 3D buildings behind/in front of the appropriate 2D layers
* preserving 2D HUD
* preserving vehicle rendering
* preserving map labels
* correct depth ordering

Possible approaches may include:

* SubViewport
* texture-based 3D building layer
* dedicated CanvasItem/Viewport composition
* another Godot-native composition method

Choose the simplest solution that provides reliable alignment.

Document the choice.

---

# 17. Prototype scope

Do NOT convert all existing buildings yet.

Create a controlled prototype containing at least:

1. simple rectangular low building
2. tall rectangular building
3. L-shaped building
4. irregular polygon building
5. pitched-roof building

Place them on a simple top-down test map containing roads.

The prototype must make it immediately obvious whether the desired visual effect works.

---

# 18. Camera movement test

Move the 2D game camera continuously across the prototype.

Verify:

* building footprints remain aligned with the map
* roads remain unchanged
* facades remain smooth
* no snapping occurs
* no sudden wall selection changes occur
* roof alignment remains correct
* building height remains stable
* buildings do not visually "jump"

Also test the same buildings near:

* top of viewport
* bottom of viewport
* left side
* right side
* centre

The result should remain smooth.

---

# 19. Zoom test

Use the existing camera zoom mechanism if available.

If the current startup client has no user-facing zoom control, create a development-only zoom test.

Verify:

* 3D buildings scale consistently with the 2D map
* roofs remain aligned
* walls remain aligned
* no positional drift occurs
* no perspective distortion appears if using orthographic projection

---

# 20. Performance experiment

This is explicitly a performance prototype.

Measure:

* FPS
* frame time
* 1% low FPS
* worst frame time
* memory
* number of 3D building objects
* number of surfaces
* number of draw calls if available

Compare:

### Current 2D building renderer

against:

### Lightweight 3D building prototype

Do not optimize prematurely.

First determine whether the 3D approach is fundamentally viable.

Then identify obvious expensive choices.

The prototype must not create one Node3D per building wall if a batched representation can be used.

Prefer:

* ArrayMesh
* MultiMesh where appropriate
* shared materials
* batched geometry
* static geometry

over large numbers of scene nodes.

---

# 21. Server architecture

Do not modify server gameplay architecture.

The server continues sending:

* building footprint
* building height
* roof information
* wall colour
* floor count
* category
* entrances

No server-side 3D coordinates should be introduced.

The conversion to 3D is entirely a client-rendering responsibility.

---

# 22. Existing building renderer

Do not delete the existing renderer immediately.

Keep the current implementation available behind a development/debug switch during the prototype.

For example:

```text
Building Renderer:
    2D legacy
    3D prototype
```

This allows direct visual and performance comparison.

Once the 3D approach is proven, the old renderer can be removed in a later phase.

Do not maintain two production rendering paths indefinitely.

---

# 23. Tests

Add Godot tests for:

* 2D → 3D coordinate conversion
* footprint conversion
* building height conversion
* roof height
* rectangular building extrusion
* L-shaped building extrusion
* irregular polygon extrusion
* deterministic geometry generation
* camera/map alignment

Add a development test that verifies:

```text
2D footprint position == 3D ground footprint position
```

within an appropriate floating-point tolerance.

Do not add client physics tests.

---

# 24. Acceptance criteria

This phase succeeds if the prototype demonstrates all of the following:

* Godot can render buildings as lightweight 3D geometry.
* The game world remains fundamentally 2D/top-down.
* Roads remain unchanged.
* Vehicles remain unchanged.
* Terrain remains unchanged.
* The existing gameplay architecture remains unchanged.
* Building footprints align exactly with the map.
* Building height produces real facade depth.
* Tall buildings visibly have taller facades.
* The building appearance changes smoothly as the camera/world moves.
* There is no discrete facade switching.
* There is no visible snapping.
* Orthographic rendering is sufficient if at all possible.
* The result is visually much closer to the supplied GTA1/GTA2 reference screenshots than the current 2D radial implementation.
* The 3D layer does not require client-side physics.
* The 3D layer does not require navigation.
* Performance is measured against the current renderer.
* No major performance regression is introduced.
* Existing tests remain passing.

This phase does NOT require:

* complete window parity
* complete door parity
* complete roof parity
* all Oulu buildings migrated
* navigation
* collision
* gameplay changes

The purpose is to answer one question:

> **Can a lightweight orthographic 3D building layer provide the desired GTA-style visual result smoothly and efficiently while keeping the rest of Road Rage Taxi as a 2D/top-down game?**

---

# 25. Real Oulu smoke test

If the prototype succeeds with the controlled test scene, render a small subset of real Oulu buildings.

Use:

* several residential buildings
* one tall commercial building
* one irregular building
* one pitched-roof building
* St1 Limingantie
* Neste

Verify alignment with the existing Oulu map.

Do not migrate the entire Oulu building dataset yet.

---

# 26. Documentation

Update:

* `godot-client.md`
* `godot-pygame-rendering-parity.md`

Document:

* the 2D + lightweight 3D architecture
* coordinate mapping
* camera setup
* rendering composition
* performance results
* known limitations

Clearly mark the 3D building layer as a prototype if it has not yet replaced the production renderer.

---

# 27. Git

When the prototype is complete:

* commit the implementation
* push the branch
* do NOT create or push a Git tag

---

# Final report

Report:

1. Whether the lightweight 3D approach successfully reproduces the desired GTA-style appearance.
2. Camera type and exact camera orientation.
3. Whether orthographic projection was sufficient.
4. How the 2D and 3D coordinate systems are aligned.
5. How the 3D buildings are generated.
6. How the 3D layer is composited with the 2D game.
7. Prototype screenshots/results.
8. Performance compared with the current 2D renderer.
9. FPS and 1% low FPS.
10. Worst frame time.
11. Memory usage.
12. Number of 3D objects/surfaces.
13. Real Oulu smoke-test results.
14. Remaining technical problems.
15. Recommendation: continue with 3D buildings or abandon the approach.
16. Python test count.
17. Godot test count.
18. Commit hash.

Do not migrate the complete building renderer until the prototype has demonstrated that the visual result and performance are both acceptable.
