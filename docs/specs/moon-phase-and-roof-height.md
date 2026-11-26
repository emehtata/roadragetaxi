# Moon phase and open-roof height corrections

## Goal
Fix the straight-edged gibbous Moon and oversized car-shelter roofs reported in the latest Oulu screenshots, covering the shared rendering rules that caused both.

## Files to change
- `godot/sky_clouds.gdshader`: render the illuminated part of a spherical Moon with a curved terminator.
- `src/theroadragetrip/building_style.py`: give all untagged open-roof types a low canopy default.
- `tests/test_static_world.py`, `tests/test_map_chunks.py`: cover open-roof heights and chunk output.
- `godot/tests/moon_phase.gd` (or existing focused sky test) and manifest: verify actual rendered phase shape and controls.
- `tools/visual_scenarios.json`, minimal visual-test readiness helpers: reproduce the real mapped roofs and reported Moon.

## Evidence
- Inspect `screenshots/screenshot_1795715707667000064.png` and matching JSON: Oulu, 2026-11-26 22:08, gibbous Moon with a flat bright-side cutoff.
- Inspect `screenshots/screenshot_1795715727612999936.png` and JSON: 22:28, camera centre `(425228.28, 7216577.13)`, EPSG:3067.
- The shader currently calls its terminator a straight chord; `TYPE_HEIGHT_M` covers `carport` but omits `roof` and `canopy`, which inherit footprint-based building heights.
- Cached source `bbox_65p0525_25p38123_65p07953_25p44535.json` has roof-only ways `133638606` (centre ≈425235.5,7216607.4; bounds 15.7×22.6 m) and `133638621` (≈425233.1,7216629.8; 20.4×14.3 m), suitable real targets.

## Behaviour / acceptance criteria
1. The Moon's projected spherical surface and sun-facing illumination produce a curved terminator for crescent and gibbous phases; only a half Moon has a straight terminator. Preserve a smooth circular outer limb.
2. Projected lit area follows the server's `moon_illumination` within a documented raster tolerance. Test 0, 0.25, 0.5, 0.75 and 1; the reported near-full phase has a curved dark sliver rather than a flat clipped edge.
3. The bright side faces the projected Sun for waxing/waning orientations, including rotated views. Full/new and near-aligned Sun/Moon directions remain finite and stable, without seams or NaNs.
4. Preserve celestial positions/angular size, cloud occlusion, below-horizon hiding, radiance behavior and catalog-star occultation by the whole lunar disk.
5. `building=roof`, `canopy` and `carport` without explicit height or levels use the same 2.5 m render height regardless of footprint area. Existing valid tagged height/level precedence remains intact; no global cap reduces explicitly tall canopies.
6. Both target roofs retain their exact OSM footprint, orientation and ground placement; lower the roof/posts to the canopy height without shrinking mapped plan dimensions. Open sides remain open and each footprint has one chunk owner.
7. Fix the shared style/chunk path so existing cached maps also receive the corrected height; invalidate caches only if derived persisted contents would otherwise retain the bad result. Preserve unrelated building type defaults.
8. Add named `oulu_gibbous_moon` and `oulu_roof_shelters` native visual scenarios based on the screenshots/source data. Readiness must verify requested phase/time and Moon visibility/shape samples, and both target footprints plus actual emitted roof/post heights, respectively; loaded unrelated buildings do not satisfy the roof check.
9. Both scenarios pass normal map/camera/weather readiness; inspect screenshots for a curved lunar boundary and plausible vehicle-height shelters. Keep screenshot/debug evidence local. A daytime roof control should make footprint, posts and clearance readable.

## Tests to add
- `tests/test_static_world.py::test_open_roof_defaults_do_not_scale_with_footprint`: parameterize roof/canopy/carport, small/large footprints, and explicit height/levels; roof/canopy currently inherit tall defaults.
- `tests/test_map_chunks.py::test_open_roof_chunk_height_and_footprint`: real-target shaped fixtures preserve coordinates/owner and emit 2.5 m canopy heights; fails on the current fallback.
- `godot/tests/moon_phase.gd::test_rendered_phase_masks`: sample actual shader output for lit-area fraction, curved row boundaries in crescent/gibbous phases, both orientations and full/new stability; a CPU-only copy cannot establish the shader fix.
- Run focused sky/building/chunk tests, changed-script parser checks, and both named visual scenarios; existing Sun/cloud/star controls must pass.

## Out of scope
Ephemeris changes, lunar texture/detail assets, changing physical footprints, parking or traffic behavior, roof model redesign, unrelated buildings and broad map/style refactoring.
