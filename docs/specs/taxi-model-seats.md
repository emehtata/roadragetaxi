# Taxi model: grey seats showing above the body

Goal: the player's taxi in the 3D (third-person) view shows no grey seat/headrest blocks through or above
its yellow body; it keeps its GLB look and roof sign.

## Findings
- The taxi already IS a GLB. `entity_layer.gd:1038` calls `Buildings3D.car()`; with `opaque`
  (`--outdoor-3d`, `buildings_3d.gd:2454`) `car()` (`buildings_3d.gd:848-855`) picks
  `car_model_kind()` (`:873`, CAR_SHAPES[0] -> `saloon`/`city_car`), draws it via `place_model_car()`
  (`:884`) with the yellow paint tint (`:925-928`) and the roof sign from `model_car_details()`
  (`:1010-1014`, at `roof_height` 1.41). The procedural `car_arrays()` (`:1716`) is only the
  non-opaque fallback and draws no seats.
- The grey blocks are the GLB's `interior` surface (saloon mesh `saloon_3`: seats/headrests,
  y 0.21..1.34 m) under a paint roof shell at y 1.40 m: only 6 cm of clearance.
- Cause: `merged_model()` (`buildings_3d.gd:969-973`) merges every surface and runs
  `importer.generate_lods(25.0, 60.0, [])`. The thin roof shell (paint surface) is simplified
  independently of the interior surface, so at the chase-camera distance a coarse LOD pulls the roof
  below the headrests (or opens it) while the boxy seats survive: they read as blocks on top of the
  car. The taxi shows it worst because the chase camera looks down on it from a few metres.
  Verify first: render the scenario with `get_viewport().mesh_lod_threshold = 0.0`; if the seats
  vanish, LOD is confirmed. If not, the next suspect is the glass/roof culling; record which.

## Choice (user offline)
Keep the GLB (it already gives the taxi its look; the sign and tint stay as they are) and drop the
`interior` surface from merged car models. Why: smallest change, removes the blocks whatever the LOD
does, fewer triangles; nobody sees the interior: the dark glazing (`car_glazing`, alpha 0.9) hides
it, and in the driver-eye view the taxi body is not drawn at all (`entity_layer.gd:1026`).
Rejected: a procedural taxi (loses the GLB look); tuning LOD error per surface (fragile).

## Files to change
- `godot/buildings_3d.gd` `merged_model(kind)`: skip surfaces whose material `resource_name` is
  `"interior"` (cars only; leave bus/train/tram interiors if they rely on it: check per kind).
- `godot/tests/` new test file `taxi_model_parts.gd` (or the existing GLB vehicle test file).

## Acceptance
1. `merged_model("saloon")` and `merged_model("city_car")` have no surface with material `interior`.
2. For the taxi as drawn (`car_model_kind(CAR_SHAPES[0], taxi length)`, scaled by
   `model_scale()`), every vertex of every surface and LOD (`ArrayMesh.surface_get_arrays` plus
   `RenderingServer.mesh_surface_get_lods` indices) except the roof sign lies at or below the
   model's paint roof top + 0.01 m and within half the body width + 0.06 m (mirrors).
3. The roof sign still sits on the roof (sign box bottom within 0.05 m of the paint roof top).
4. Rendered taxi from behind and from the front in the third-person view (named scenario in
   `tools/visual_scenarios.json`, readiness checks passed, docs/visual-testing.md): no grey blocks
   above or beside the body; yellow body and lit roof sign visible. Screenshots inspected.

## Tests to add
- `godot/tests/taxi_model_parts.gd::test_no_interior_surface` - fails now: `saloon` has `interior`.
- `::test_taxi_parts_inside_body` - fails now if LOD/interior vertices exceed the roof top.
- `::test_roof_sign_on_roof` - guards the sign height against regression.

## Commands
- `make check`
- `XDG_DATA_HOME=$(mktemp -d) make godot-test`
- `godot-shot` on the new scenario, behind and front.

## Out of scope
NPC traffic behaviour, the 2D/top-down car drawing, new vehicle GLBs, a dedicated taxi model.
