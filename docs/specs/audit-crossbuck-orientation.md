# Level-crossing crossbuck orientation

## Goal
Fix VQA-020: crossbuck faces are visible to traffic approaching along the road, with their X-shaped boards across the approach direction. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: correct only crossbuck board orientation in `_gap_prop()`'s `level_crossing` branch.
- `godot/tests/run_tests.gd`: replace the existing expectation that boards lie along the road; add semantic face-direction and preservation coverage, updating affected crossbuck control fingerprints explicitly.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse `drive_level_crossing_day` and existing cameras/readiness helpers; add only missing mapped-target verification.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/crossbuck-orientation/`: diagnosis, labelled comparison views, passing named screenshot/result and reproduction commands.

## Behaviour / acceptance criteria
1. Trace mapped `railway=level_crossing` → scenery `direction_angle` → chunk `scenery_objects` → `props()` → `_gap_prop()` and the final chunk mesh. Confirm the row angle describes the road direction; record how `along`, `across` and `_sloped_wall()` currently make the boards parallel to it. Use actual board triangles/normals, rather than bounds alone.
2. Apply the smallest crossbuck-only geometry correction: the broad board faces have normals parallel to road approach `(cos(angle), 0, -sin(angle))`, so both opposing approaches see a recognizable X. At angles 0, π/2, π and 0.73, the board width runs across the road and the two diagonals remain distinct, joined and attached to each post.
3. Preserve the two post centres at ±4 m across the road, post dimensions/height/colour, board lengths/thickness/heights/colour, material, face winding, normals and shadows. Preserve barrier, power-line and other prop geometry; do not rotate the whole crossing or its posts.
4. Verify translated placements and flat/nonzero constant ground heights through `props()` and the final chunk builder. Rebuild/unload/reload retains the corrected orientation without changing scenery row contracts or adding per-frame geometry work.
5. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated production-builder views at useful scale. Inspect the full X from both road approaches, attachment and ground contact; include a normal-distance perspective sample. Preserve historical audit evidence unchanged.
6. Pass and inspect a named real-map daylight 3D scenario using the mapped crossing near `drive_level_crossing_day`'s Oulu pose (428628.9, 7210670.0, heading −0.909), or another documented mapped crossing. Record target coordinates and road angle. Readiness must identify the actual rendered target, active 3D camera, useful projected board size, correct heading, ground clearance and frustum/HUD/building/dynamic-body clearance, plus normal map/time/weather/chunk checks. Counts or projected hidden geometry alone cannot qualify; rejected attempts receive no visual credit.
7. Record revision, renderer, dimensions, measurements, scenario IDs, commands and results. Parse changed scripts and run focused crossbuck plus existing scenery-height, barrier, power-line and chunk-build checks. Preserve player userdata/shared edits; independent tester PASS precedes atomic commit/push.
8. Follow `docs/finnish-npc-traffic-law.md`: this is client display geometry. Server railway safety, control applicability/direction/layer, train priority, signals and barrier decisions remain unchanged; visible signs do not certify legal behavior.

## Tests to add
- `godot/tests/run_tests.gd::test_crossbucks_face_road_approaches`: identify broad board faces and assert their normals/diagonal geometry against road direction through the heading/position/ground matrix; current edge-on geometry must fail, as must deleting or flattening the X.
- `godot/tests/run_tests.gd::test_crossbuck_geometry_preserved`: check post centres, dimensions, board attachment/extent/colour, final chunk placement/rebuild, and unchanged barrier/other-prop controls.
- Named readiness rejects absent, wrong-angle, inactive, buried/offscreen/obscured or too-small targets; only an inspected passing capture counts.

## Out of scope
Other audit findings, new crossing assets or sign artwork, moving barriers/signals, road-width or crossing-layout redesign, simulation/legal behavior, new data sources, new cameras and renderer refactors. Visual coverage samples recorded map/lighting conditions.
