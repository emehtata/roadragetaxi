# Ferris-wheel rim supports

## Goal
Fix VQA-024: connect the Ferris-wheel rim visibly through spokes and a hub/axle to its existing grounded A-frame. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: add the minimum spokes and hub/axle connection in the Ferris-wheel branch of `attractions()`, using existing mesh helpers.
- `godot/tests/run_tests.gd`: add/register focused contact and preservation checks; update intentional Ferris-wheel fingerprints in earlier attraction controls.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: extend existing mapped-attraction verification only as needed for a visible wheel-support scenario.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/ferris-wheel-supports/`: diagnosis, labelled comparisons, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace `prepare_theme_parks()` / `make_ride()` through chunk `attractions`, `map_chunk.prepare()`, `_structures()` and `attractions()`. Record the 16-segment vertical rim/cabins, hub height `radius + 2`, wheel plane and the two A-frame apexes offset 0.5 m to either side; measure the absent connections using actual triangles.
2. Add slender, evenly distributed radial spokes and a small hub/axle connection for the Ferris wheel only. Spokes join the actual rim to a shared hub; the hub/axle joins both existing A-frame apexes. Each contact touches/overlaps within 0.005 m, forming a continuous path from rim to grounded supports. Keep the wheel open and recognizable; no solid disc or oversized joint blocks.
3. Preserve all original rim, cabin and A-frame vertices/colours, cabin count, wheel axis/radius, footprint and overall bounds. Preserve normals, winding, materials and shadows; preserve the repaired carousel, swing carousel, roller coaster and drop tower. Avoid degenerate spokes: `_sloped_wall()` rejects coincident horizontal endpoints, including a purely vertical spoke.
4. Verify normal 49-point paths, smaller valid closed loops, the minimum 3 m radius and irregular/translated/rotated footprints through `attractions()` and the final chunk mesh. Flat and nonzero constant ground retain all contacts. Preserve short-loop rejection, stable chunk rebuild/unload/reload, bounded construction work, map/server contracts and 2D output.
5. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated production-builder views at useful size, plus a normal-distance perspective sample. Inspect rim/spoke/hub/axle/apex contacts and open spaces; retain historical audit evidence unchanged.
6. Pass and inspect a named real-map daylight 3D scenario with a Ferris wheel from the normal mapped-ride/theme-park pipeline. Reuse mapped Vauhtipuisto if suitable or document another actual source. Record park/ride provenance and the complete source path; label representative generated geometry accurately.
7. Readiness identifies the actual rendered wheel/path and active 3D view, requires useful projected spoke/hub/apex contact size and clear sightlines to those contacts, verifies ground placement and frustum/HUD/building/dynamic-body clearance, and retains normal map/time/weather/chunk checks. Reject contacts hidden by cabins/frame/ride geometry as well as absent, wrong-path, buried or undersized targets; rejected attempts receive no credit.
8. Record revision, renderer, dimensions, contact measurements, target/scenario IDs, commands and results. Parse changed scripts and run focused contact/preservation plus existing attraction/ground/chunk checks. Preserve player userdata and shared edits; independent tester PASS precedes atomic commit/push.

## Tests to add
- `godot/tests/run_tests.gd::test_ferris_wheel_rim_connected`: inspect actual triangles to prove distributed rim-to-hub and hub-to-both-apex contact across the footprint/ground matrix; current unsupported rim fails, as do omitted/degenerate spokes or a detached axle.
- `godot/tests/run_tests.gd::test_ferris_wheel_geometry_preserved`: verify original geometry/colours remain, supports are slender and nondegenerate, other rides unchanged, final ground adaptation and stable chunk reload output.
- Named readiness rejects malformed/missing paths, inactive/hidden targets and undersized contact regions; only a passing, visually inspected screenshot counts.

## Out of scope
Other audit IDs, rim/cabin/A-frame redesign, real ride reconstruction, animation/rigging, new assets/data sources, gameplay/simulation, new cameras and renderer refactors. Visual coverage samples recorded map/lighting conditions.
