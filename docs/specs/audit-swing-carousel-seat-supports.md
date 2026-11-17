# Swing-carousel seat supports

## Goal
Fix VQA-023: each swing-carousel seat visibly hangs from the existing canopy instead of floating. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: add minimal hanging supports in the `swing_carousel` branch of `attractions()`, reusing existing mesh helpers.
- `godot/tests/run_tests.gd`: add/register focused attachment and preservation tests beside the carousel tests; update the intentional swing-carousel control fingerprint.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: extend existing mapped-attraction verification only as needed for a visible swing-carousel support capture.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/swing-carousel-seat-supports/`: diagnosis, labelled comparisons, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace `prepare_theme_parks()` / `make_ride()` through chunk `attractions`, `map_chunk.prepare()`, `_structures()` and `attractions()`. Identify the seats emitted every sixth path point at 3.0–3.6 m, the canopy underside at 7.0 m and its rim at 45% of the path radius. Measure their original disconnection using actual triangles.
2. Add slender hanging rods or chain-like supports for `swing_carousel` only, with at least one support for every seat. Each support touches/overlaps the seat top and actual canopy underside within 0.005 m, forming a continuous connection through the canopy to the grounded mast. Account for the inset canopy: a vertical rod above the outer seat alone cannot connect it. Keep seats exposed and the space beneath the canopy open; no shared platform or solid pedestal.
3. Preserve seat count, positions, dimensions, heights and colours; preserve mast/canopy geometry/materials, footprint, total height, normals, winding and shadows. Preserve the repaired standard carousel, roller-coaster, Ferris-wheel and drop-tower output. Use bounded mesh generation during chunk construction with unchanged server/map contracts and 2D rendering.
4. Verify normal 49-point paths, smaller valid closed loops and irregular/translated/rotated footprints through `attractions()` and the final chunk mesh. Flat and nonzero constant ground heights retain all contacts. Preserve short-loop rejection and stable chunk rebuild/unload/reload output.
5. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated production-builder views at useful size, plus a normal-distance perspective sample. Inspect every seat-to-support and support-to-canopy connection; retain historical audit evidence unchanged.
6. Pass and inspect a named real-map daylight 3D scenario with a swing carousel from the normal mapped-ride/theme-park pipeline. Record park/ride provenance and the complete source path; accurately label representative generated geometry. Reuse the Vauhtipuisto mapped-park workflow if it produces a visible swing carousel, or document another actual source.
7. Readiness must identify the actual rendered swing-carousel path and active 3D view, require useful projected seat/hanger/canopy contact size and clear sightlines to those contacts, verify ground placement, frustum/HUD/building/dynamic-body clearance and retain normal map/time/weather/chunk checks. Reject supports hidden by their own canopy as well as absent/wrong-path/buried/offscreen targets; counts and projected bounds alone cannot qualify. Rejected attempts receive no visual credit.
8. Record revision, renderer, dimensions, contact measurements, target/scenario IDs, commands and results. Parse changed scripts; run focused attachment/preservation plus existing attraction/ground/chunk checks. Preserve player userdata and shared edits; independent tester PASS precedes atomic commit/push.

## Tests to add
- `godot/tests/run_tests.gd::test_swing_carousel_seats_connected`: inspect actual seat/support/canopy triangles and prove a contact path for every seat across the footprint/ground matrix; current floating seats must fail, as must missing seats, detached upper anchors or a platform substituted for hangers.
- `godot/tests/run_tests.gd::test_swing_carousel_geometry_preserved`: verify unchanged original vertices/colours outside added supports, distinct exposed seats, unchanged other-attraction controls, final terrain placement and stable rebuild/unload/reload output.
- Named readiness rejects missing/malformed paths, inactive/hidden or undersized contact regions; only a passing, visually inspected screenshot counts.

## Out of scope
Other audit IDs, seat/canopy redesign, real ride reconstruction, articulated chains or ride animation, new assets/data sources, gameplay/simulation, new cameras and renderer refactors. Visual coverage samples the recorded map/lighting conditions.
