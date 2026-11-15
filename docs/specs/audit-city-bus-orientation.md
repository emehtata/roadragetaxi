# City bus model orientation

## Goal
Fix VQA-007: the imported city bus must face the production vehicle heading, with its windshield and destination display at the forward end. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: correct the city bus source-axis turn in `place_model_car()` using the existing placement path.
- `godot/tests/run_tests.gd`: add semantic bus orientation and pooled-transform regression coverage beside the existing vehicle model checks.
- `tools/visual_scenarios.json`, `godot/visual_test.gd`: reuse existing lineup/camera/readiness facilities; add only the minimum bus-specific fixture/readiness needed for clear named captures.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/city-bus-orientation/`: record diagnosis, commands, labelled comparison views and accepted named capture results.

## Behaviour / acceptance criteria
1. Trace `entity_layer._vehicle_body()` → `vehicle("bus")` → `vehicle_model_kind()` → `place_model_car()` and inspect the GLB's windshield/destination display, rear grille and native lamp landmarks. Record the actual source nose axis and existing turn; do not infer the nose from bounds alone.
2. Apply the smallest city-bus-only placement correction so its semantic nose maps to local +X before heading rotation. At headings 0, π/2, π and an oblique angle, the nose points along `(cos(h), 0, -sin(h))`; rear landmarks point opposite. Preserve proper handedness and the door side.
3. Preserve bus dimensions, height, road contact, centre/elevation, native materials and lamp states. Production overlays/headlight direction must agree with the corrected front and rear. Reusing pooled instances across frames must update heading correctly.
4. Keep source assets unchanged if placement resolves the defect. Other imported vehicles, including the source-X train locomotive/coach, retain their previous transforms, scale and geometry; procedural and 2D buses retain their behavior.
5. Capture labelled before/after front, rear, both sides, three-quarter and top views through the production placement path. Inspect the windshield/display at the declared front and red lamps/grille at the rear; include lit lamps to confirm front/rear agreement.
6. Verify with named real-map daylight and lit-night scenarios, using the existing road lineup/camera patterns and disposable userdata. Accepted readiness must identify the city bus at the requested pose/heading, ensure useful projected size and no HUD/building/dynamic-body occlusion, and retain normal map/time/weather checks. Inspect each accepted screenshot; failed attempts do not count.
7. Record source revision, renderer, dimensions, scenario IDs and commands. Run focused orientation/pooling checks and existing model size, pooled bounds/material, vehicle-distance and lamp regressions; parse changed scripts. Independent tester PASS precedes the atomic commit and push.
8. Traffic decisions, server heading, routing, bus stop behavior and map-layer separation remain authoritative on the Python server. Preserve shared-tree edits and player settings.

## Tests to add
- `godot/tests/run_tests.gd::test_city_bus_model_faces_heading`: independently identify/record front and rear GLB landmarks; assert their positions relative to heading through `vehicle("bus")` at multiple headings/elevations. The current backward model must fail.
- Extend that test to reuse the same pooled bus on consecutive frames and check native lamp state plus front/rear overlay agreement; retain train/car transform controls to catch a shared-axis regression.
- Named visual readiness: a missing, offscreen, too-small or obscured bus must fail rather than produce accepted evidence.

## Out of scope
VQA-012 train vent and all other audit IDs, new assets/data sources, bus interior redesign, simulation or traffic-law changes, new gameplay cameras and renderer refactors. Visual acceptance covers the recorded scenarios, not every map/lighting combination.
