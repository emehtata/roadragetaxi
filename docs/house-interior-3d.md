# 3D interior geometry (phase 1)

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
`enter`/`leave` methods from `home_door.indoors`. This phase adds no game mode,
entry behavior, input bindings, camera switching or controller.

## Conversion

`home_interior_3d.gd` is an additional Node3D representation. Call
`load_plan(plan)` only when a 3D representation is wanted, and `clear()` or free
the node when leaving. Repeated loads replace all mesh and collision resources.
Nothing generates 3D interiors during world loading or ordinary 2D house entry.

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

The inspector alone supplies a fixed elevated camera and neutral lighting.
`--index` selects an existing plan from `tests/data/home_plans.json`;
`--plan=/absolute/path.json` accepts an exported plan dictionary or plan array.
Closing the inspector releases its scene. Screenshot mode exits after capture;
use a rendering display, not the headless dummy renderer, for capture.

`make godot-test` includes the converter test. It checks all 30 real generated
fixtures for floor area, finite dimensions, source preservation, collision
through doors and above lintels, and cleanup. A two-room example verifies that
shared-wall and junction top areas are not duplicated. Existing Python plan
validation and the 2D indoor tests remain applicable.
