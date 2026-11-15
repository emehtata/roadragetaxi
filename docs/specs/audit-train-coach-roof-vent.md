# Train coach roof vent attachment

## Goal
Fix VQA-012: attach the train coach roof vent to its intended roof mount, removing the visible background gap. Deliver one focused correction commit with reproducible evidence.

## Files to change
- `godot/assets/vehicles/train_coach.glb`, `godot/assets/vehicles/SOURCES.md`: repair only the affected source component if the gap exists in the imported asset; document reproducible local processing.
- `godot/buildings_3d.gd`: change `merged_model()` or placement only if source-versus-production comparison proves the defect originates there; preserve the shared model contract.
- `godot/tests/` and its existing registration: add a small focused coach attachment/preservation regression, reusing model helpers.
- `tools/visual_scenarios.json`, `godot/visual_test.gd`: reuse the coach lineup and existing cameras, adding only missing roof-visible target readiness.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/train-coach-roof-vent/`: diagnosis, before/after views, accepted named screenshots/results, and commands.
- A deterministic repair script under `tools/` only if binary geometry processing needs one for reproduction.

## Behaviour / acceptance criteria
1. Trace `vehicle("train", ..., {"profile":"standard"})` → `place_model_car("train_coach")` → `merged_model()`. Compare the imported source, merged base mesh and generated LODs; identify the actual vent and roof surfaces geometrically, since source nodes are merged by material and their names do not identify individual components reliably. Record the measured gap and its cause before fixing it.
2. Apply the smallest correction at the diagnosed source. The vent base touches or overlaps its intended roof/mount within 0.01 m, with no background gap in front, both side, three-quarter and elevated views. Retain a recognizable vent without burying it in the roof or removing it.
3. Preserve coach dimensions, silhouette outside the repaired component, roof/body/wheel/door/window geometry, materials and paint tinting, orientation, scale, rail contact and placement elevation. Preserve locomotive/car controls and procedural train behavior. Do not mask the gap with lighting or disable LODs/culling.
4. Verify attachment through the production merged and pooled path at multiple headings/elevations and after pool reuse. Check base mesh and sampled generated LODs; the fix must not reintroduce a gap or detach the roof at normal/far sampled distances.
5. Capture labelled before/after front, both sides, three-quarter and elevated views at useful size using production placement. Inspect every view; include a default-LOD distance sample. Keep the original audit/register historical and link correction status separately.
6. Run at least one named real-map daylight coach scenario with the roof vent clearly visible using an existing camera. Readiness must identify the requested pooled coach at its fixture pose, require useful projected coach/vent size and clearance from HUD/buildings/dynamic bodies, and retain normal map/time/weather/chunk checks from `docs/visual-testing.md`. Model existence alone is insufficient. Inspect the passing screenshot; rejected attempts do not count.
7. Record source revision, renderer, dimensions, fixture/scenario IDs, commands and readiness results. Import any changed asset, parse changed scripts, and run focused attachment/preservation plus existing model size/pooling and train-door regressions. Preserve player userdata and unrelated shared-tree edits; independent tester PASS precedes commit/push.

## Tests to add
- `godot/tests/train_coach_roof_vent.gd::test_vent_attaches_to_roof`: independently recorded vent/base and roof measurements exercise production merged geometry; fails on the current gap and guards against deleting/burying the vent. Cover pooled heading/elevation/reuse and sampled generated LODs.
- Same file, `test_coach_geometry_preserved`: assert stable bounds/material identities and unchanged geometry outside the repaired component; include an unaffected locomotive control.
- Named visual readiness must reject a missing/offscreen/too-small or obscured target and accept only a roof-visible coach capture.

## Out of scope
Other audit IDs, train doors/interiors, new assets/data sources, simulation/routing/traffic decisions, new cameras and renderer refactors. Exact unseen LOD thresholds and every map/lighting combination are outside the sampled visual coverage.
