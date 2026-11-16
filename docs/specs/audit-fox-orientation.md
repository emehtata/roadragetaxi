# Fox model orientation

## Goal
Fix VQA-017: the imported fox faces its declared forward/travel heading rather than a lateral axis. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: correct only the fox source yaw in `ANIMAL_MODELS` if source inspection confirms that resolves the defect.
- `godot/animal_models_test.gd`: strengthen semantic fox orientation coverage and exercise production batched transforms; reuse existing animal controls.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse the fixed wildlife fixture and cameras; add only the fox target/readiness coverage needed for a named capture.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/fox-orientation/`: diagnosis, labelled comparison views, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace the wildlife branch of `entity_layer._people_3d()` → `animal()` → `_flush_animals()` → `animal_arrays()` → `_animal_model()`. Inspect the source GLB's nose, head and tail landmarks with its node transforms applied. Record its actual nose axis and existing fox yaw; bounds and the highest-quarter centroid alone do not establish forward direction.
2. Apply the smallest fox-only source-axis correction so the semantic nose points along local +X before instance heading. At headings 0, π/2, π and an oblique angle, nose-to-body direction aligns with `(cos(h), 0, -sin(h))` and the tail remains behind. Preserve proper handedness.
3. Account for `_animal_model()` normalising by the rotated X extent: the corrected fox remains 0.9 m long at size 1, retains the source proportions and grounded feet, and scales consistently at sizes 0.6/1/1.2. Preserve coat colours, normals, shadow geometry and the original GLB bytes. Record any expected bounds change caused by correcting the formerly lateral length axis.
4. Cover detail 0/1, stand/feed/walk pose keys, multiple positions/elevations and repeated batch reuse across frames. Preserve cached model construction, batching and the missing-model procedural fallback. Other imported animals, horse riders and all procedural species retain their previous output/transforms.
5. Capture labelled before/after front, rear, both sides, three-quarter and top views through the production builder/material. Inspect semantic nose/tail direction, proportions and ground contact; retain the historical audit unchanged and link correction status separately.
6. Pass and inspect at least one named real-map daylight scenario using the existing wildlife fixture/camera patterns. Readiness must identify the actual fox instance and expected heading in the active 3D view, require useful projected fox/head size, ground clearance and frustum/HUD/building/dynamic-body clearance, and preserve normal map/time/weather/chunk readiness from `docs/visual-testing.md`. Counts or projected bounds alone must not accept a buried/hidden animal.
7. Record revision, renderer, dimensions, fixture/scenario IDs, measured landmarks and commands. Parse changed scripts and run focused orientation/batching plus existing animal scale, horse rider, fallback and licensing checks. Preserve player userdata and shared-tree edits; independent tester PASS precedes atomic commit/push.
8. Preserve wildlife movement, heading decisions, reactions, audio and 2D rendering; this correction belongs in imported 3D model normalisation.

## Tests to add
- `godot/animal_models_test.gd::test_fox_semantic_forward_axis`: independently recorded source nose/body/tail landmarks verify normalised direction, centred width, proportions and ground contact; the existing sideways fox must fail, even if its highest vertices have positive X.
- `godot/animal_models_test.gd::test_fox_batch_faces_heading`: actual MultiMesh instance transforms verify those landmarks across headings/elevations, sizes and batch reuse; retain non-fox/fallback controls.
- Extend named readiness to reject wrong heading, inactive/absent/offscreen/too-small/occluded/buried targets rather than accepting animal count alone.

## Out of scope
Other audit IDs, asset replacement, new data sources, model rigging/animation, wildlife/server behavior, pedestrian interactions, new cameras and renderer refactors. Named visual coverage samples recorded conditions, not every map or lighting combination.
