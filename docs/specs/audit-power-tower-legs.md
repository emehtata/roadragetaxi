# Power tower leg continuity

## Goal
Fix VQA-019: each power-tower leg forms a continuous narrowing support from ground to top, without detached upper sections. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: repair only the `power_tower` branch of `_gap_prop()`, using existing mesh construction helpers.
- `godot/tests/run_tests.gd`: add focused leg continuity and preservation tests beside the existing scenery/height checks; register them.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse `drive_power_poles_day`'s sourced Oulu towers and existing cameras; add only the target/readiness coverage needed for a clear named 3D capture.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/power-tower-legs/`: diagnosis, labelled before/after views, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace chunk `scenery_objects` → `map_chunk` ground props → `props()` → `_gap_prop()` → the built chunk mesh. Record the current three vertical sections at corner offsets 2.0/1.4/0.8 m and measure their horizontal separation at height boundaries using actual vertices/triangles.
2. Apply the smallest tower-only geometry correction. Each of the four legs narrows upward with continuous support through both section boundaries: adjacent surfaces touch/overlap within 0.005 m, with no background gap. Preserve recognizable slender legs rather than filling the tower with a solid body or adding oversized joint blocks.
3. Preserve tower height, four ground-foot locations, existing leg thickness, colour, two crossarm locations/dimensions and intended narrowing silhouette. Preserve normals/front-face visibility and shadow casting. Keep all other prop kinds and power-line geometry unchanged.
4. Verify default and explicit heights (including 10, 22 and 45 m), translated positions and multiple angles through `props()` and the final production chunk build. Both default and explicit 22 m towers must agree. Ground adaptation must not separate the repaired joints; test flat and nonzero constant ground heights.
5. Preserve map/server row contracts, terrain placement, chunk caching/rebuild/unload behavior and bounded mesh generation. This is a client geometry repair; no collision, power-line placement or simulation decisions change.
6. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated views through the production builder/material at useful scale. Inspect all four legs and both section joints; include a normal-distance perspective sample. Retain historical audit evidence unchanged and link the correction separately.
7. Pass and inspect a named real-map daylight 3D scenario based on `drive_power_poles_day` (Oulu pose 426307.2, 7209696.8, heading 1.601; sourced towers 19–21 m away), or another documented mapped tower. Identify the actual mapped target and its height/position, require active 3D, useful projected leg/joint size, grounded feet and frustum/HUD/building/dynamic-body clearance, plus normal map/time/weather/chunk readiness. Counts or projected hidden geometry alone must not qualify; rejected attempts receive no visual credit.
8. Record revision, renderer, dimensions, target coordinates/height, scenario IDs, commands and readiness results. Parse changed scripts; run focused leg/preservation and existing scenery-height, power-line and chunk-build regressions. Preserve player userdata/shared edits; independent tester PASS precedes atomic commit/push.

## Tests to add
- `godot/tests/run_tests.gd::test_power_tower_legs_connected`: independently inspect leg triangle cross-sections at both height boundaries and nearby samples; assert four continuous tapering supports, expected feet/thickness/top height and visible geometry across the height/position matrix. Current separated vertical sections must fail; deleting legs or bridging with a solid slab must also fail.
- `godot/tests/run_tests.gd::test_power_tower_geometry_preserved`: verify crossarm geometry/colour, unaffected prop/power-line controls, default-versus-explicit height, final chunk ground placement and stable rebuild output.
- Named readiness rejects missing/wrong-height/inactive, buried/offscreen/obscured or too-small targets and accepts only an inspected passing screenshot.

## Out of scope
Other audit findings, tower redesign/full lattice bracing, crossarm or wire redesign, new assets/data sources, electricity gameplay, traffic/server behavior, terrain conformance redesign, new cameras and renderer refactors. Recorded visual samples do not certify every terrain/map/lighting combination.
