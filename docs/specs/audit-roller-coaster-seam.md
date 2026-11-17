# Roller-coaster track seam

## Goal
Fix VQA-021: the closed roller-coaster track meets at the same height at its seam. Deliver one focused correction commit with reproducible visual evidence.

## Files to change
- `godot/buildings_3d.gd`: repair the closing endpoint height in `attractions()`'s `roller_coaster` branch using the existing strip builder.
- `godot/tests/run_tests.gd`: add focused seam and preservation checks beside the attraction geometry tests; register them.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: add the minimum actual coaster target/readiness coverage using existing cameras.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/roller-coaster-seam/`: diagnosis, labelled comparisons, passing named capture/results and commands.

## Behaviour / acceptance criteria
1. Trace `prepare_theme_parks()` / `make_ride()`'s closed 49-point path through chunk `attractions`, `map_chunk.prepare()`, `_structures()` and `attractions()` to `_sloped_strip()`. Measure the original opening using actual first/last track triangles: the height function currently evaluates the duplicated start point with index 48 instead of index 0.
2. Apply the smallest coaster-only correction so the closing point uses the start point's height. For valid closed loops with different segment counts, the first and last track endpoint heights agree within 0.001 m and their centreline endpoints coincide. The track remains continuous in height at every segment boundary, with no closing drop, missing segment or added gap-covering slab.
3. Preserve footprint coordinates, segment count, 1.2 m track width, colour, winding/normals, intermediate height samples and support positions/heights/counts. Preserve all other attraction kinds and the existing short-loop guard. Keep mesh generation bounded and retain current map/server row contracts; no server path or 2D rendering changes.
4. Verify translated/rotated and irregular closed loops, including the production 48-segment loop, through `attractions()` and the final chunk mesh. Flat and nonzero constant terrain heights retain seam agreement; chunk rebuild/unload/reload produces stable corrected output.
5. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated production-builder views at useful scale, plus a normal-distance perspective sample. Inspect the closing endpoint and neighboring segments; preserve historical audit evidence unchanged.
6. Pass and inspect a named real-map daylight 3D scenario with a coaster produced by the normal mapped-ride/theme-park pipeline. Document the real park/ride source, path and seam coordinates; if the normal pipeline generates a representative ride inside a mapped park, label that provenance accurately. Readiness must identify the actual rendered target/path in the active 3D view, require useful projected seam size, ground clearance and frustum/HUD/building/dynamic-body clearance, and retain normal map/time/weather/chunk checks. Hidden geometry or counts alone cannot qualify; rejected captures receive no visual credit.
7. Record revision, renderer, dimensions, measured endpoint heights, target/scenario IDs and commands. Parse changed scripts and run focused seam/preservation plus existing attraction/ground/chunk regressions. Preserve player userdata and shared edits; independent tester PASS precedes atomic commit/push.

## Tests to add
- `godot/tests/run_tests.gd::test_roller_coaster_track_closes`: extract red track triangles and compare first/last endpoint heights and all adjacent centreline endpoints across loop sizes/shapes/transforms; current height discontinuity must fail, as must a missing closing strip.
- `godot/tests/run_tests.gd::test_roller_coaster_geometry_preserved`: assert unchanged intermediate track/support geometry and other-attraction controls, plus final terrain placement and chunk rebuild/reload output.
- Named readiness rejects absent, wrong-path, inactive, obscured/buried/offscreen or too-small seam targets; an inspected passing screenshot is required.

## Out of scope
Other audit IDs, real coaster reconstruction, track smoothing/banking, corner-width joins, ride vehicles/animation, support redesign, new assets/data sources, gameplay/simulation, new cameras and renderer refactors. Visual coverage samples the recorded map/lighting conditions.
