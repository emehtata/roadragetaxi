# Car glass: dark and reflective on close-range models

## Goal
Windows on close-range GLB cars read darker than the body paint and show a
visible sheen/reflection, matching the far procedural cars (car.gdshader part 2).

## Files to change
- `godot/buildings_3d.gd` `static func car_glazing(original: Material) -> StandardMaterial3D`:
  besides the dark albedo, set glass PBR so it reflects: metallic ~0.55
  (same as car.gdshader glass), roughness <= 0.08, specular 0.5+, keep
  transparency but high enough alpha (>= 0.85) that body paint behind the
  pane does not tint it to body colour. Do not change the shared GLB material
  (duplicate stays). Verify the result actually has a reflection source
  (scene environment / reflection probe in use); if close cars get no
  environment reflection, fix that in the same function's material (e.g.
  enable rim/clearcoat) rather than adding a new system.
- `godot/tests/vehicle_showcase.gd`: already calls `B3.car_glazing`; no change
  unless needed to light the scene like the game.
- `godot/car.gdshader`: only if the far-car glass shows the same problem in
  the render (check it; otherwise unchanged).

## Behaviour / acceptance criteria
1. `car_glazing` returns a duplicate whose metallic >= 0.5, roughness <= 0.08,
   albedo luminance below 0.05; the original material is unmodified.
2. In the rendered vehicle_showcase, every car's window pixels are darker than
   its body paint pixels (mean luminance, sampled from a light-coloured car).
3. Windows show a visible highlight/sky reflection gradient (not a flat
   colour) in the day render of `metallic_vehicle_paint_day`.
4. Far procedural cars look unchanged (or fixed, if they shared the issue),
   checked in the same scenario.
5. Screenshots taken via the named scenario / godot-shot with readiness checks
   passed, per docs/visual-testing.md, and inspected visually.

## Tests to add
- `godot/tests/` existing unit test file for buildings_3d (or new
  `test_car_glazing.gd`): `test_car_glazing_is_dark_and_reflective` — builds
  a StandardMaterial3D like the GLB "glass", asserts criterion 1. Fails
  today: metallic stays 0.15.

## Out of scope
- New reflection probes, screen-space reflections, interior car meshes.
- Body paint, lamps, the far-car LOD switch distance.
