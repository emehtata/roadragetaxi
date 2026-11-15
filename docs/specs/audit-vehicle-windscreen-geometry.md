# Vehicle windscreen geometry corrections

## Goal
Fix VQA-001–005: jagged body triangles and bands interrupting the hatchback, estate, SUV, pickup and panel-van front glazing. Deliver one focused correction commit with reproducible visual evidence.

## Files to change
- `godot/assets/vehicles/{hatchback,estate,suv,pickup,panel_van}.glb`: repair only malformed windscreen/body geometry if the source meshes contain it.
- `godot/buildings_3d.gd`: change `merged_model()` only if source-versus-pooled comparison establishes a merge/LOD defect; retain its shared caching/material contract.
- `godot/assets/vehicles/SOURCES.md`: record any actual local asset processing and its reproducible method; retain current source/licence attribution.
- `godot/tests/vehicle_windscreens.gd`, `godot/tests/manifest.txt`: focused production-mesh regression and registration, reusing existing model-test helpers where practical.
- `tools/visual_scenarios.json`, `godot/visual_test.gd`: minimal named target-visible verification scenarios/readiness additions, reusing the vehicle lineup and existing cameras.
- `docs/visual-quality-corrections/vehicle-windscreens/`: source-path diagnosis, before/after sheets, named screenshots/results and commands mapping VQA-001–005 to the correction.
- A small deterministic asset repair script under `tools/` only if binary edits need it for reproduction.

## Behaviour / acceptance criteria
1. Confirm the failure in the live opaque path: `car()` selects `place_model_car()` → `merged_model()` for all five kinds; audit fixtures also use that path. Compare original imported surfaces, merged base geometry and default generated LODs before selecting the smallest root-cause fix. `SOURCES.md` already describes earlier painted-triangle removal; do not assume that processing removed every offending face.
2. All five corrected models show one continuous intended glass region bounded by body/roof/pillars, with no repeated triangular teeth, body-coloured band through the pane, unintended hole or new overlapping surfaces in front, front-three-quarter and top views matching the audit evidence.
3. Keep existing silhouette, dimensions, scale/orientation, material names/assignments, paint tinting, glass tint/reflection, normals, lamp components and non-windscreen surfaces. Do not hide artifacts by changing lighting, camera framing, glass opacity or disabling LODs/culling globally.
4. Verify the five corrected variants through production pooling at close and normal perspective distances and at sampled generated-LOD distances; no reappearance of the artifact, missing pane or silhouette pop attributable to the fix. Include an unaffected saloon as a control.
5. Reuse/add named real-map lineup scenarios with explicit expected-model and on-screen projected-bounds readiness for all five kinds. Capture affected front glazing at useful pixel size from existing chase/eye/overhead cameras as applicable; model existence outside the frame is insufficient. Preserve normal map/time/weather/chunk readiness under `docs/visual-testing.md`.
6. Render and inspect labelled close front/three-quarter/top sheets plus the passing named gameplay screenshots. Retain exact variants, distances, renderer, source revision, commands and readiness results; independent tester must inspect every corrected variant. Keep original audit evidence/register historical and link correction status separately.
7. Preserve shared-tree edits and player saves/settings. Import changed assets, parse changed scripts, run focused regressions and existing model/glazing/pooling checks before handoff. Commit only after tester PASS.

## Tests to add
- `godot/tests/vehicle_windscreens.gd` — `test_front_glazing_geometry`: exercise production merged meshes for all five kinds and assert the diagnosed invalid windscreen/body intersection or malformed boundary is absent using a meaningful geometric criterion or rendered region check; it must fail against original affected assets.
- Same file — `test_model_preservation`: compare stable bounds/material identities and unaffected geometry/control model so a blanket face/material deletion cannot pass the fix.
- Same file — `test_glazing_at_lod_distances`: rendered/mesh assertions at near and sampled default-LOD distances catch any merge/simplification-specific recurrence. Reuse existing `test_pooled_models_merge_by_material()` and `test_car_glazing_is_dark_and_reflective()` coverage.
- Named visual checks above must fail readiness for missing/offscreen affected models and retain screenshots only after readiness passes.

## Out of scope
Other vehicle accessories/orientation, bus/train fixes, other audit IDs, new model sources/dependencies, gameplay/traffic logic, new camera systems, asset redesign and renderer refactoring. Exact unseen LOD thresholds and arbitrary lighting/map combinations are not certified; report the sampled scope.
