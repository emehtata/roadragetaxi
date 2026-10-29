# 3D house interiors

## Existing data and lifecycle

`src/theroadragetrip/interior.py` generates local metre-scale plans on demand,
with an eight-plan cache. Room `points` are simple polygons, including concave
and rotated shapes. The generator rejects room holes and falls back to a studio
when it cannot connect rooms. `walls` is the unary union of room boundaries,
with door intervals removed: shared boundaries are already represented once.
`doors[].points` gives the actual jamb positions; `rooms` identifies the joined
rooms, with -1 for outdoors. `leaf` is the 2D swing indicator. Furniture is
separate and windows are not represented.

`home_interior.gd` draws the plan viewer; `home_walk.gd` enters the server's
cached plan and maintains the existing 2D indoor walker. `main.gd` calls its
`enter`/`leave` methods from `home_door.indoors`. Optional first-person exploration
uses the same server entry/exit state and a fresh request for its cached plan on
each visit, so changing homes cannot reuse the previous house's plan.

## Conversion

`home_interior_3d.gd` is an additional Node3D representation. Call
`load_plan(plan)` only when a 3D representation is wanted, and `clear()` or free
the node when leaving. Repeated loads replace all mesh and collision resources.
Nothing generates 3D interiors during world loading or ordinary 2D house entry.
First-person entry creates just the active house's representation.

One plan metre maps to one Godot metre: `(x, y)` becomes `(x, height, -y)`.
Each room polygon is triangulated at height zero. Wall polylines are offset with
miter joins, extruded to 2.5 m, and clipped against earlier wall footprints so
junction top faces have one owner. A combined mesh has floor and wall materials;
a separate StaticBody3D uses its triangles for static collision. There is no
house physics simulation. Wall height, thickness (0.12 m), and door height
(2.0 m) are exported properties. Door widths follow the existing source jambs
(currently 0.95 m); narrowing them to the suggested 0.8 m would change the plan.
Lintels span the source door intervals above door height, leaving the full
source opening clear below. Interior junction faces are inside the wall volume.

The source does not distinguish exterior wall materials or include windows.
This phase uses a neutral wall material throughout and generates no windows,
furniture, doors, roof or ceiling. The isolated inspection scene contains no
exterior roof that could obscure the view.

## Inspect and validate

From the repository root (use the installed Godot executable if needed):

```sh
godot --path godot --script res://tools/inspect_home_interior_3d.gd -- --index=0
godot --path godot --script res://tools/inspect_home_interior_3d.gd -- --index=4 --screenshot=/tmp/interior.png
godot --headless --path godot --script res://tests/home_interior_3d.gd
```

The geometry inspector supplies a fixed elevated camera and neutral lighting.
`--index` selects an existing plan from `tests/data/home_plans.json`;
`--plan=/absolute/path.json` accepts an exported plan dictionary or plan array.
Closing the inspector releases its scene. Screenshot mode exits after capture;
use a rendering display, not the headless dummy renderer, for capture.

`make godot-test` includes the converter test. It checks all 30 real generated
fixtures for floor area, finite dimensions, source preservation, collision
through doors and above lintels, and cleanup. A two-room example verifies that
shared-wall and junction top areas are not duplicated. Existing Python plan
validation and the 2D indoor tests remain applicable.

## First-person exploration (phase 2)

Previous Gameplay opt-ins are ignored; enable it again under Experimental.

Enable **Settings → Experimental → First-person house interiors (3D)**. The setting
is saved with the existing client settings and defaults off, preserving 2D
interiors. Indoor mouse sensitivity is adjustable in the same menu. Changing
mode while indoors restarts at the entrance. Enter with E at the selected
home's front door; the server still decides whether entry is allowed.

`home_first_person.gd` owns an isolated SubViewport/World3D on the same overlay
layer as the 2D walk. It creates `home_interior_3d.gd` and one `home_player_3d.gd`
CharacterBody3D only on entry. The surrounding map, exterior building renderers
and Camera2D are untouched; their roofs cannot obstruct the separate interior
world. Leaving, disconnecting, switching modes, or removing the game frees the
viewport, geometry, collisions and controller.

The capsule is 1.75 m high with a 0.30 m radius, and the camera is at 1.60 m.
Movement is 3.5 m/s with project-default gravity. These are exported controller
properties. WASD uses indoor Input Map actions (the exterior uses DriveInput,
so no equivalent actions existed). A/D strafe, diagonal movement is normalized,
and mouse pitch is limited to ±85 degrees. Mouse input enters through one path
in main.gd; movement uses CharacterBody3D.move_and_slide, not a separate physics
simulation. Indoor input never reaches the exterior driving or phone controls.
Captured look uses unscaled screen motion, discards the first nonzero sample
after capture, and applies accumulated motion once per rendered frame. A
two-turns-per-second limit drops excess motion without a backlog; very fast
swipes are therefore limited too.
On X11, a hidden confined cursor is sampled and recentered once per frame
instead of using captured raw input. This bypasses incorrect raw deltas from
pointing devices; desktop pointer acceleration can affect sensitivity there.

Spawn candidates start just inside the existing front door, then try farther
inward offsets and room labels. Each must lie inside a room floor and the
footprint, with capsule clearance from the source wall segments and outer edge.
The source plan guarantees room connectivity. No furniture collision shapes
exist in this phase. An invalid 3D spawn falls back to the existing 2D mode with
a visible notice. The isolated world's front door has a collision boundary at
the threshold: E near it uses the existing server exit instead of allowing the
player to walk into empty space outside the generated floor.

Escape opens the existing pause menu and releases the mouse; Resume captures
it again if exploration was active. Losing window focus stops movement and
releases the mouse; click the interior to resume. E exit restores the previous
cursor mode. Jumping, sprinting, crouching, furniture, ceilings and appearance
work remain outside this phase.

### Validation and manual checks

`make godot-test` also runs `tests/home_first_person.gd`. It checks capsule spawn
and floor contact on all 30 generated fixtures, four-way/diagonal movement,
mouse yaw and pitch limits, actual movement through internal doors and into
walls, cursor state, cleanup, real main.gd entry/exit/mode selection, fresh plan
requests, input isolation, and disconnect cleanup. Existing 2D tests still run.

For a manual check:

1. Enable 3D interiors in Experimental settings, choose a home and approach its
   front door on foot. E should show the interior facing inward.
2. Walk and strafe with WASD, look up/down with the mouse, traverse room doors,
   and walk into walls. The capsule should stay grounded and stop at walls.
3. Press Escape, navigate settings, and Resume. The cursor should be visible in
   menus and captured during exploration. Alt-tab away and back; click to resume.
4. Change the interior mode off and on while paused; both views should work.
5. Return to the front door and press E. Exterior walking, taxi controls, camera
   position/zoom, and mouse interaction should work. Repeat entry/exit several
   times, and disconnect while indoors to check cleanup.
