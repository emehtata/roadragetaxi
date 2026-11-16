# Fox forward axis (VQA-017)

The imported fox now faces local +X and its declared travel heading. The sole production change is the fox entry's source yaw, from 0 to **PI/4** in `ANIMAL_MODELS`; the GLB and shared builder remain unchanged. The historical audit is retained.

## Diagnosis and measured landmarks

The production path is `entity_layer._people_3d()`'s wildlife branch → `animal()` → `_flush_animals()` → `animal_arrays()` → `_model_arrays()` → `_animal_model()`. Wildlife headings are negated into server headings before batching. `_animal_model()` flattens source node transforms, applies the species yaw, centres the horizontal bounds, grounds the feet and divides by the rotated X extent. `_model_arrays()` then scales to the species' 0.9 m length; instance transforms apply the travel heading and elevation.

The source GLB has one identity-transform mesh node. Its fox faces diagonally **+X/+Z**, confirmed by the textured muzzle, chest, pointed ears and white tail in the source-yaw captures. It is not aligned with a cardinal axis. The original highest-quarter heuristic passed because its head already had positive X despite a lateral component. Recorded flattened vertex IDs identify chest `[1962,1734,1970]`, head `[3435,3323,3434]` and tail `[0,21,229]`. Before yaw correction, in source-normalised coordinates, their centroids are approximately chest `(-.01795,.31821,-.20124)`, head `(.35540,.72599,.15407)` and tail `(-.47918,.02828,-.39233)`. Their head-minus-chest horizontal vector is `(.37335,.35531)`, about 43.6° toward +Z; the muzzle's forward extreme is near `(.38957,.57222,.40700)`. The 45° yaw aligns the body/head with +X while retaining the model's natural head turn, ears and tail.

Correcting yaw changes the X extent used by the existing uniform normalisation. At size 1, old dimensions were about **0.900 × 0.714 × 0.736 m** (X/Y/Z); corrected dimensions are **0.900 × 0.599 × 0.338 m**. This is the expected restoration of source proportions at 0.9 m forward length, not a mesh edit. Feet remain at zero. Source SHA-256 is `f534388ca7d738eeb51a178ef4cddc28ce601cfcfae7e569e353420dbaa08da3`, asserted by the regression. Coat sampling, rotated face normals, shadows, caching, other animal yaws and the procedural fallback use the existing unchanged code.

## Checks and inspected evidence

- [Original regression](regression-before.log): **228 checks, 96 failures**, including semantic direction and batched heading. [Corrected Linux run](regression-after.log): **229 checks, 0 failures** (one source-preservation assertion added). Covers detail 0/1, sizes .6/1/1.2, stand/feed/walk_a/walk_b, length/proportions/feet/shadow, four headings, translated/elevated placement and reused batches, plus existing species/horse/rider/fallback controls.
- Dummy headless rendering does not store MultiMesh instance transforms. The permanent test checks submitted transforms there; the [native focused run](regression-native-focused.log) checks the actual uploaded instance transforms: **225 checks, 0 failures**. The [full native run](regression-native.log) had four existing person-pose hash mismatches on Windows; the Linux full animal suite passes all four. They are excluded from the focused native result, not claimed fixed.
- [Animal and licensing pytest](pytest-animal-licence.log): **9 passed**. [Manifest pytest](pytest.log): **3 passed**. Changed scripts parse and `git diff --check` passes. Existing dummy-renderer/resource shutdown and native shader-cache warnings are retained in logs.
- All **32 before/after panels** are inspected: eight angles at both details before and after. Front views now show chest/head, rear views show the tail and hindquarters, side/top views preserve proportions and foot contact. The existing production organic material and audit builder are used; the fixture uses the same audit coat tint before/after. [Detail 1 ends/sides](review/comparison_detail1_1.png), [detail 1 three-quarter/top](review/comparison_detail1_2.png), [detail 0 ends/sides](review/comparison_detail0_1.png), [detail 0 three-quarter/top](review/comparison_detail0_2.png).

## Named real-map capture

[Accepted screenshot](gameplay/vqa_fox_orientation_day/2026-06-20T1500_20261116-081855_94f790e1-dirty/screenshot.png) and [readiness](gameplay/vqa_fox_orientation_day/2026-06-20T1500_20261116-081855_94f790e1-dirty/result.json): **PASS**, independently inspected by the implementer. `vqa_fox_orientation_day` reuses the sourced Oulu road pose from `walk_bench_oulu_day`/the reflective-strip correction. A fixed IDLE fox stands 9 m along the same road and 0.9 m left, with heading **5.39659 rad**, facing the existing eye camera. Normal city/map/time/weather checks remain; DEM terrain is disabled for this isolated geometry sample, as in the preceding corrections. The real fox is clearly visible in its orange production coat, grounded and clear of the HUD. Readiness checks its actual active 3D MultiMesh instance, heading, pose/size/detail, ground clearance, full frustum, person/head size, HUD, building sightline and nearer dynamic-body clearance. Recorded full bounds **99.8×111.4 px**, head **49.8×45.1 px**, ground **0 m**, instance y **0.028 m**; empty errors, 1280×720, native Windows Godot 4.7.2 Forward+ Vulkan on NVIDIA GeForce RTX 5060. Disposable userdata is removed by the wrapper.

The first attempt (`20261116-081407`) placed the fox 5.5 m ahead. It failed frustum/HUD checks (and a nearer-body overlap at timeout), produced no screenshot, and receives no visual credit. The final scenario places it farther away on the same sourced road. No gameplay camera or wildlife behaviour is changed.

## Reproduction

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://animal_models_test.gd
.venv/bin/python -m pytest -q -n auto tests/test_godot_manifest.py
.venv/bin/python -m pytest -q -n auto tests/test_animal_models.py tests/test_license_inventory.py
.venv/bin/python tools/visual_test.py run vqa_fox_orientation_day --out docs/visual-quality-corrections/fox-orientation/gameplay
```

For close captures, run the native Windows Godot with `--path <godot> --script res://tools/visual_quality_audit.gd -- <fixture.json> <after-directory>` using Windows-converted absolute paths. For original-yaw reproduction, copy [before-capture-runner.txt](before-capture-runner.txt) to `godot/tools/_tmp_fox_before_capture.gd` and use that script; it restores just the original zero yaw in memory. [Before regression runner](before-regression-runner.txt) and [native focused runner](native-focused-runner.txt) reproduce their respective logs. Remove temporary scripts/UIDs afterwards. Source revision is `94f790e1-dirty`; [capture manifests](manifest.json) retain exact renderer/angles/bounds.

Visual verification samples daylight, both model details and one flat-terrain real-map scene. Other audit IDs, every lighting/terrain combination and server/wildlife movement remain outside this slice. Independent tester review is required before commit.
