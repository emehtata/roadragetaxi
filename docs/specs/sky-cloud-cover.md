# Sky clouds driven by FMI cloud cover

## Goal
Draw noise clouds in the 3D sky so the visible coverage follows `cloud_cover`
(0 clear .. 1 overcast). Keep today's `Daylight.sky_color` as the base colour.

## Files to change
- `godot/daylight.gd`: add `static func cloud_coverage(cloud_cover: float) -> float`.
  It maps cover to the shader's coverage threshold and is the only place that mapping lives.
- `godot/sky_clouds.gdshader` (new): a `shader_type sky;` shader with one pass and
  no extra subpasses (do not use `AT_HALF_RES_PASS` or `AT_QUARTER_RES_PASS`).
  Its uniforms are `sky_top_color`, `sky_horizon_color`, `coverage`, `wind_offset`
  and `energy`. It uses `LIGHT0_DIRECTION` for the sun.
  It samples 2-3 octaves of value noise on a plane projected along `EYEDIR.y`, with
  no raymarching. The bottom half of the sky is ground colour.
- `godot/buildings_3d.gd`:
  - Line 86: replace `ProceduralSkyMaterial` with a `ShaderMaterial` that uses the new shader.
  - `set_sky_color(color)` (~334): set the same top and horizon colours as shader parameters.
  - Add `set_cloud_cover(cover: float)`, which sets `coverage` through `Daylight.cloud_coverage`.
  - `set_light` (~346): `energy_multiplier` becomes the `energy` uniform.
  - Advance `wind_offset` once per frame from wind and delta. This is O(1).
- `godot/main.gd` (~834): call `map_layer.buildings_3d.set_cloud_cover(cloud)` next to `set_sky_color`.
- `tools/visual_scenarios.json`: add `sky_clouds_clear_day`, `sky_clouds_broken_day` and
  `sky_clouds_overcast_day`. They are windshield scenarios at cloud 0.0, 0.5 and 0.9.
  Copy the pose and time from `windshield_kamppi_day`, set sun altitude to about 30 deg,
  and give them readiness `requires` like the existing windshield entries.

## Behaviour / acceptance criteria
1. `cloud_coverage(0.0)` returns the threshold for no cloud pixels: the sky looks the same
   as today's gradient.
2. `cloud_coverage(0.3)` gives scattered patches, about 20-40% of the upper hemisphere.
3. `cloud_coverage(c)` for c >= 0.8 gives at least 90% of the upper hemisphere covered.
4. The mapping is monotonic and clamps input outside 0..1.
5. Clouds have brighter tops and sunlit edges toward the sun direction and darker undersides.
   Their tint follows the sky colour, so night clouds are dark rather than glowing white.
6. Clouds drift slowly. They move visibly over about 30 s and do not jump between frames.
7. Wet-road and water reflections still use the same sky through `REFLECTION_SOURCE_SKY`.
   The non-windshield top-down view, which uses `BG_COLOR`, is unchanged.
8. There is one sky pass and no per-frame CPU work beyond setting the uniforms.
   Frame cost is measured with the windshield scenario at cloud 0.9, comparing
   ProceduralSky with the cloud shader. The result is recorded in the commit message
   and labelled "WSL Mesa".
9. Renders of the three new scenarios have passed their readiness checks and have been
   inspected visually, following docs/visual-testing.md.

## Tests to add
- `godot/tests/run_tests.gd` gets `test_cloud_coverage_mapping`. It checks
  criteria 1-4 against `Daylight.cloud_coverage`. It also checks that the coverage
  fraction from a CPU copy of the shader's threshold test, run on a fixed 64x64 noise
  sample, meets the 0 / 0.3 / 0.8 bounds.
  Without the fix this fails because the function does not exist.
- The same file gets `test_sky_material_takes_cloud_cover`: build a `Buildings3D` with
  `opaque` set, call `set_cloud_cover(0.9)`, and check that the sky material's `coverage`
  parameter equals `cloud_coverage(0.9)`. It fails without the fix because the material
  is a ProceduralSkyMaterial with no such parameter.
- Run the tests with `XDG_DATA_HOME=$(mktemp -d)`.

## Out of scope
- RTX path (`make run-rtx`) sky lighting and any special handling for it.
- The overhead 2D map. It has no sky.
- Volumetric or raymarched clouds, cloud shadows on the ground, and rain shafts.
- Server-side changes. `cloud_cover` already arrives in the protocol.
- Keep the uncommitted car, GLB, LOD and showcase changes in the tree untouched.
