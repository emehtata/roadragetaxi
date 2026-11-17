# Carousel seat supports

## Goal
Fix VQA-022: the standard carousel's seats visibly connect to the central ride structure instead of floating. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: add the minimum support geometry in the standard-carousel branch of `attractions()`, using existing mesh helpers.
- `godot/tests/run_tests.gd`: add and register focused support/contact and preservation checks beside the attraction tests.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse mapped-attraction path verification and existing cameras for one visible carousel scenario.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/carousel-seat-supports/`: diagnosis, labelled comparisons, accepted named capture/results and commands.

## Behaviour / acceptance criteria
1. Trace `prepare_theme_parks()` / `make_ride()` through chunk `attractions`, `map_chunk.prepare()`, `_structures()` and `attractions()`. Record the existing seat boxes at every sixth path point, their 0.9–1.6 m heights, the central mast and the canopy inset to 72% of the path radius; measure the original disconnected components from actual mesh triangles.
2. Add the smallest recognizable support arrangement for `carousel` only. Prefer a thin shared platform at the existing seat bases connecting them to the central mast, using the existing polygon builder if it handles the footprint correctly. Every seat must touch/overlap its support within 0.005 m, and the support must form a continuous connection to the grounded mast. Keep the ride open and recognizable; avoid a solid ground-to-seat pedestal or oversized blocks.
3. Preserve seat count, positions, dimensions, colours and heights; preserve the mast and canopy geometry/materials, overall footprint and top height. Preserve winding, normals and shadows. `swing_carousel`, roller-coaster, Ferris-wheel and drop-tower output remain unchanged; VQA-023 is a separate slice.
4. Verify normal 49-point paths plus smaller valid closed loops and irregular/translated/rotated footprints through `attractions()` and the final chunk mesh. Flat and nonzero constant terrain heights retain all contacts. Existing short-loop rejection, chunk rebuild/unload/reload and bounded mesh generation remain intact; server/map contracts and 2D rendering are unchanged.
5. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated production-builder views at useful size, plus a normal-distance perspective sample. Inspect every seat's support connection and central attachment; retain historical audit evidence unchanged.
6. Pass and inspect a named real-map daylight 3D scenario with a carousel from the normal mapped-ride/theme-park pipeline. Record park/ride provenance and the complete source path; accurately label representative generated geometry. Readiness must identify the actual rendered carousel/path, active 3D, useful projected seat/support size, ground clearance and frustum/HUD/building/dynamic-body clearance, plus normal map/time/weather/chunk checks. Hidden geometry or counts alone cannot qualify; rejected attempts receive no credit.
7. Record revision, renderer, dimensions, contact measurements, scenario/target IDs and commands. Parse changed scripts and run focused support/preservation plus existing attraction/ground/chunk regressions. Preserve player userdata/shared edits; independent tester PASS precedes atomic commit/push.

## Tests to add
- `godot/tests/run_tests.gd::test_carousel_seats_connected`: inspect actual seat/support/mast triangles and prove a continuous contact path for every seat across the footprint/placement matrix; current floating seats must fail, as must removed/buried seats or detached support geometry.
- `godot/tests/run_tests.gd::test_carousel_geometry_preserved`: verify unchanged original carousel vertices/colours outside added supports, other-attraction controls, final ground adaptation and stable chunk rebuild/reload output.
- Named readiness rejects absent/wrong-path/inactive, obscured/buried/offscreen or too-small seat/support targets; only an inspected passing screenshot counts.

## Out of scope
Other audit IDs, swing-carousel chains, new seat artwork/ride reconstruction, ride vehicles or animation, new assets/data sources, gameplay/simulation, new cameras and renderer refactors. Visual coverage samples the recorded map/lighting conditions.
