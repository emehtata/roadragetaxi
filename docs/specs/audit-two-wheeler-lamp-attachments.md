# Two-wheeler lamp attachments

## Goal
Fix VQA-006, VQA-009–011 and VQA-013–015: live lamp/indicator blocks float clear of motorcycle, bicycle and scooter models. Deliver one focused correction commit with reproducible visual evidence.

## Files to change
- `godot/buildings_3d.gd`: correct imported-model lamp anchors in `vehicle()`, `model_vehicle_details()` and their shared placement helpers; include the selected model in any geometry cache key whose contents depend on it.
- `godot/tests/run_tests.gd`: extend the existing bicycle lamp/state/control tests for actual imported-model attachment and variant pooling.
- `godot/tools/visual_quality_audit.gd`: pass the actual selected model to its lamp fixture if the production helper contract changes; preserve historical audit images.
- `tools/visual_scenarios.json`, `godot/visual_test.gd`: reuse existing bicycle/scooter lineups and target-visible readiness; add only missing motorcycle/model/state coverage.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/two-wheeler-lamps/`: diagnosis, per-finding correction links, labelled before/after sheets, named screenshots/results and commands.

## Behaviour / acceptance criteria
1. Trace `entity_layer._vehicle_body()` → `vehicle()` → `place_model_car()` and the overlay. `vehicle()` currently selects a concrete GLB but calls `model_vehicle_details()` with only its generic kind; `_bike_lamps()` uses generic length fractions, and motorcycles inherit generic car indicator/reverse overlays. Verify each offending block's source before fixing it.
2. Cover all five live source models: motorcycle, bicycle, mountain bike, e_scooter and e_scooter_grab3d, both parked and ridden where reachable. Cover the seven scoped findings individually; VQA-012 is the train vent and is excluded.
3. Derive small explicit anchors from each existing model's frame/stem/bar/saddle/deck or native lamp housing, transformed with the same `model_scale()` and source-axis rotation as its mesh. Each added lens touches/overlaps its intended mount within 0.02 m; no background gap or detached blocks remain in front, both sides, three-quarter and top views. Reuse native lenses where suitable rather than adding a duplicate assembly.
4. Bicycles/scooters retain one centred white front lens and one centred red rear lens; rear scooter lenses attach to the deck. Motorcycle indicators attach to their existing housings. Preserve current on/off, brake and side-indicator semantics and the existing single-beam headlight behavior; the server remains authoritative for light state.
5. Preserve model files, scale/orientation, wheel/frame/rider geometry, materials, imported-mesh bounds and non-two-wheeler lamp output. If a shared helper also serves procedural fallback geometry, preserve that path or adjust only its explicit matching anchors with regression coverage.
6. Drawing both variants of a kind in either order and on consecutive frames must retain their own anchors, with no cached overlay from another model. Translate/rotate/elevate models through the production path and verify the attachment transform remains correct.
7. Render labelled close front/side/three-quarter/top sheets for all five models and their relevant ridden states in daylight and with lamps lit at night. Reuse named real-map bike/scooter scenarios and add minimal motorcycle coverage using existing cameras; readiness must confirm requested model identity, projected bounds at useful size and unobscured target, plus normal map/time/weather readiness.
8. Independently inspect every corrected model/state and the named gameplay screenshots. Record source revision, renderer, dimensions, lamp bits, fixture IDs and commands. Import/parse relevant scripts and run focused attachment, existing lamp-count/single-beam/variant/size/rider regressions. Preserve player userdata and unrelated shared-tree edits; commit only after tester PASS.

## Tests to add
- `godot/tests/run_tests.gd::test_two_wheeler_model_lamp_attachments`: use independently recorded model-local mount measurements and actual pooled transforms; fail for current detached lenses/indicators, pass at multiple headings/elevations and both riding states.
- `godot/tests/run_tests.gd::test_two_wheeler_variant_lamp_cache`: draw alternating bicycle/scooter variants in both orders across frames and assert each overlay matches its own transformed mounts; fails if generic-kind caching hides variant differences.
- Extend `test_bicycle_lamps_single_pair` and `test_bicycle_headlight_single_beam`: retain counts/colours/state transitions and car controls while replacing generic-position expectations with model-specific attachment checks; keep procedural/rider checks passing.
- Named visual readiness: absent/offscreen/too-small requested variants must fail rather than produce accepted evidence.

## Out of scope
VQA-007 bus orientation, VQA-012 train vent, other audit IDs, new model assets/data sources, rider redesign, headlight optics, traffic decisions, new gameplay cameras and renderer refactors. Arbitrary map/lighting combinations are not certified; report sampled coverage.
