# Pedestrian reflective strip attachment

## Goal
Fix VQA-016: both reflective chest strips on clothing/body variant 4 follow the curved jacket front without a visible gap. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: correct the style-4 strip geometry in `person_arrays()`, reusing the actual `_garment_torso()` surface/profile rather than a fixed front plane.
- `godot/tests/run_tests.gd`: add focused strip attachment/preservation coverage beside the existing person geometry tests and register it.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse fixed pedestrian fixtures and existing cameras; add only the variant selection and visible-target readiness needed for a named capture.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/pedestrian-reflective-strips/`: diagnosis, labelled before/after views, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace `entity_layer._people_3d()` → `person()` → `person_arrays()` → `_garment_torso()` and the style-4 strips. Record how the torso's tapered polygon rings differ from the current straight cylinders at x=0.19, and measure the separation in the original variant-4 geometry.
2. Make the two pale horizontal strips follow the jacket front over their visible width. Their attachment surface must touch/overlap the actual polygonal jacket within 0.005 m at scale 1, including the ends; no background gap appears in front, side, three-quarter or top views. Keep both strips visible and recognizably distinct rather than deleting or burying them.
3. Attachment holds for detail levels 0 and 1, scales 0.6/1.0/1.2, standing/breathing, all six walk/run phases, sitting and riding. Strip geometry follows the same torso offsets and breathing movement. Verify transformed placement at multiple headings/elevations and pooled reuse.
4. Preserve existing strip colour and approximate height/width, jacket shape/material, body proportions, other clothing variants, winter style substitution, limbs, faces, costumes and animation. Preserve shadow geometry consistency and the existing cached/bounded mesh-building path; do not add per-frame surface queries.
5. Capture labelled before/after front, both sides, three-quarter and top views at useful size through the production builder/organic material. Inspect both detail levels and representative standing/breathing/walk poses; preserve the historical audit and link the correction separately.
6. Run a named real-map daylight scenario with a deterministic pedestrian ID selecting variant 4 through the normal hash path and an existing camera exposing the chest. Readiness requires the actual active 3D target, expected variant/pose, useful projected person/chest size, ground clearance, frustum and HUD/building/dynamic-body clearance, plus normal map/time/weather checks. Inspect its passing screenshot and result; projected bounds alone or a buried/occluded target do not qualify.
7. Record revision, renderer, dimensions, fixture IDs, measurements and commands. Parse changed scripts and run focused attachment plus existing person proportion, seating/riding, walking animation and variant regressions. Preserve player userdata/shared edits; independent tester PASS precedes atomic commit/push.
8. This is client geometry only: preserve server pedestrian interactions, movement, priority, map layers and safety decisions under `docs/finnish-npc-traffic-law.md`.

## Tests to add
- `godot/tests/run_tests.gd::test_reflective_strips_follow_jacket`: identify strip vertices by their existing colour and compare attachment against independently extracted jacket triangles across the poses/scales/detail levels above; the current straight strips must fail, while missing/buried strips also fail.
- `godot/tests/run_tests.gd::test_reflective_strip_geometry_preserved`: verify unchanged non-strip geometry and other variants/winter controls, strip visibility/extent, shadow agreement and production pooled transforms.
- Named scenario readiness rejects absent, wrong-variant, hidden, too-small or below-ground targets; only an inspected passing capture receives visual credit.

## Out of scope
Other audit findings, zipper redesign, new clothing/assets/data sources, reflector lighting semantics, pedestrian/server behavior, new cameras and renderer refactors. Recorded visual samples do not certify every map/lighting combination.
