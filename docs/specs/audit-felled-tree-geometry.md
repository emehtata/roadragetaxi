# Felled tree trunk orientation and attachment

## Goal
Fix VQA-018: a felled tree has a horizontal trunk aligned with its fall direction and joined to its crown. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: correct the felled branch of `tree_parts()` using the existing primitive and instance path.
- `godot/tests/run_tests.gd`: add focused transform/attachment and preservation checks beside the existing tree tests; register them.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse the sourced Bulevardi tree scenario and existing cameras; add only the fixture/readiness needed for a clear named 3D capture.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/felled-tree-geometry/`: diagnosis, labelled comparison views, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace server `knocked_trees` → `map_chunk.set_fallen()` → `_trees_3d()` → `tree_parts()` → `trees_node()` MultiMeshes. Record how the unit cylinder's local Y axis, the lying basis and `Basis.scaled()` interact; verify the defect using transformed mesh vertices/endpoints rather than bounds alone.
2. Apply the smallest correction in the felled branch. The trunk's long axis lies along `(cos(angle), 0, -sin(angle))` in Godot coordinates, matching `to_3d(Vector2(cos(angle), -sin(angle)))`; its vertical endpoint difference is at most 0.001 m on flat ground. Preserve its intended length/radius rather than compressing it into a sliver.
3. The stump-side endpoint remains at the tree's position, the other end reaches into the existing crown, and the visible trunk/crown surfaces touch or overlap within 0.01 m. Preserve a recognizable horizontal trunk; no background gap, floating end or upright remnant appears in side, three-quarter or elevated views. Adjust only the minimal felled placement needed for attachment.
4. Verify birch, pine and spruce at radii 0.6/1.4/2.5, angles 0, π/2, π and 0.73, translated positions, flat/nonzero DEM heights and both near/far modes through actual MultiMesh transforms. Ground clearance remains appropriate to the existing felled presentation; no trunk is buried or left floating above its support plane.
5. Preserve standing trees, shrubs, bollards, crown meshes/colours, seasonal appearance, shadow settings, near/far selection and instance counts. Rebuilding after a fall and rebuilding/reloading back to standing must retain the existing state lifecycle. Keep cached shared meshes and bounded rebuild behavior.
6. Capture labelled before/after front, rear, both sides, three-quarter and elevated views using production `trees_node()` and materials. Inspect representative species and near/far modes at useful scale; retain the original audit unchanged and link the correction separately.
7. Pass and inspect a named real-map daylight 3D scenario based on `tree-knocked-topdown`'s sourced Bulevardi tree at 385679.6, 6671613.9, or another documented real tree. Readiness must identify the felled instance/angle in the active 3D view, require useful trunk/crown projected size, ground clearance and frustum/HUD/building/dynamic-body clearance, plus normal map/time/weather/chunk checks. A 2D capture or projected bounds of hidden geometry cannot qualify.
8. Record revision, renderer, dimensions, fixture IDs, measurements and commands. Parse changed scripts, run focused geometry and existing tree/forest/state-lifecycle regressions, preserve player userdata/shared edits, and obtain independent tester PASS before commit/push. Server collision/felling decisions, fall angle and map layers remain unchanged.

## Tests to add
- `godot/tests/run_tests.gd::test_felled_tree_trunk_alignment`: transformed cylinder endpoints/radius and actual MultiMesh geometry verify horizontal direction, intended dimensions, grounded placement and crown contact across the matrix above; the current upright/sliver result must fail.
- `godot/tests/run_tests.gd::test_felled_tree_geometry_preserved`: standing/shrub/bollard controls, colours, counts, near/far output and fall/reset chunk lifecycle remain stable.
- Named readiness rejects standing/wrong-angle/absent, inactive 3D, hidden/buried/offscreen or too-small targets; only an inspected passing capture receives visual credit.

## Out of scope
Other audit findings, whole-tree fall animation, new tree assets, terrain/slope conformance redesign, logging/removal gameplay, traffic/server collision or road-maintenance rules, 2D renderer changes, new cameras and renderer refactors. Recorded visual samples do not certify every terrain/map/lighting combination.
