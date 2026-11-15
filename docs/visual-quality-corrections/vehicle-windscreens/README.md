# VQA-001–005: vehicle front glazing

[Independent review: five numbered pages, source/crop hashes, model checklist and preservation evidence](review/README.md).

The five affected imported GLBs contained residual painted faces crossing their front glass. The same sawteeth/bands appear in the [original source and production-pool comparison](before_source-versus-pooled_front.png). The shared merge, material overrides and LOD generation in `buildings_3d.gd` are unchanged.

The repair subtracts each existing front-glass projected footprint (inset 15 mm for the painted surround) from nearby painted faces. Only the main body's affected index triangles and interpolated boundary vertices/normals change. The original glass, other primitives, material definitions, node transforms and original vertex records retain their original values; Python checks compare them against the pre-correction fingerprints in `godot/tests/data/vehicle_windscreens.json`. The saloon GLB remains byte-identical. There are no new sources or licences.

| Model | Finding | Painted triangles clipped | Geometry status |
|---|---|---:|---|
| hatchback | VQA-001 | 90 | base and all generated LOD ray checks pass |
| estate | VQA-002 | 77 | base and all generated LOD ray checks pass |
| SUV | VQA-003 | 73 | base and all generated LOD ray checks pass |
| pickup | VQA-004 | 91 | base and all generated LOD ray checks pass |
| panel van | VQA-005 | 117 | base and all generated LOD ray checks pass |
| saloon | control | 0 | source bytes unchanged |

[Before close views](before_front_three-quarter_top.png) · [After close views](after_front_three-quarter_top.png). Rows are saloon/hatchback/estate/SUV/pickup/panel van; columns are front, front three-quarter and top. Each 400×340 panel retains native capture pixels. All five corrected variants and the saloon control were inspected in these views on 2026-11-15. The original audit/report remains historical.

Perspective sheets use the existing audit runtime renderer, a 60° perspective camera and the production default mesh LOD threshold. Each samples six increasing distances; actual mesh surface LOD metadata and rendered primitive counts are retained in [the runtime results](lod/results.json): [saloon](lod/A-001_perspective-lod.png), [hatchback](lod/A-002_perspective-lod.png), [estate](lod/A-003_perspective-lod.png), [SUV](lod/A-004_perspective-lod.png), [pickup](lod/A-005_perspective-lod.png), [panel van](lod/A-008_perspective-lod.png). All sheets were inspected; distant silhouettes are too small for a material-detail claim, so the geometric regression checks every generated paint LOD index set as well.

## Named gameplay verification

Five scenarios reuse the audited Oulu city-centre square pose (`third_oulu_dense`), daytime clear/cloud 0.4. A client-only stationary NPC fixture faces the existing chase camera beside the taxi. Its ID selects the requested normal production body shape; `entity_layer.gd` and the normal pooled model placement render it. Readiness requires the expected model at the fixture position, every actual pooled-mesh AABB corner inside the 3D camera frustum, a minimum projected dimension of 80 pixels, and no projected HUD or building-footprint obstruction. Normal map/chunk/time/weather readiness is retained for 60 stable frames.

Each resolved scenario, screenshot, result, server/Godot logs and source-pixel hashes are linked in [manifest.json](manifest.json). All five passing 1280×720 images were inspected individually; the target body rectangles range from 135×100 to 137×131 px. They show clear, continuous glazing at normal gameplay scale. The close sheets provide the larger component inspection.

| Scenario | Image | Readiness |
|---|---|---|
| `vqa_windscreen_estate` | [image](gameplay/vqa_windscreen_estate/2026-06-20T1500_20261115-141019_838cd590-dirty/screenshot.png) | [result](gameplay/vqa_windscreen_estate/2026-06-20T1500_20261115-141019_838cd590-dirty/result.json) |
| `vqa_windscreen_hatchback` | [image](gameplay/vqa_windscreen_hatchback/2026-06-20T1500_20261115-140911_838cd590-dirty/screenshot.png) | [result](gameplay/vqa_windscreen_hatchback/2026-06-20T1500_20261115-140911_838cd590-dirty/result.json) |
| `vqa_windscreen_panel_van` | [image](gameplay/vqa_windscreen_panel_van/2026-06-20T1500_20261115-141241_838cd590-dirty/screenshot.png) | [result](gameplay/vqa_windscreen_panel_van/2026-06-20T1500_20261115-141241_838cd590-dirty/result.json) |
| `vqa_windscreen_pickup` | [image](gameplay/vqa_windscreen_pickup/2026-06-20T1500_20261115-141154_838cd590-dirty/screenshot.png) | [result](gameplay/vqa_windscreen_pickup/2026-06-20T1500_20261115-141154_838cd590-dirty/result.json) |
| `vqa_windscreen_suv` | [image](gameplay/vqa_windscreen_suv/2026-06-20T1500_20261115-141107_838cd590-dirty/screenshot.png) | [result](gameplay/vqa_windscreen_suv/2026-06-20T1500_20261115-141107_838cd590-dirty/result.json) |

The first hatchback attempt correctly failed readiness and saved no screenshot: the general lineup's 3.5 m truck envelope extended beyond the close camera. The focused readiness check now uses the real pooled mesh bounds. The failed result/log is retained, receives no visual pass, and is identified in the manifest.

All accepted gameplay runs initialize a disposable `rrt-indoor-hint-*` userdata name before startup using the existing visual-test bootstrap. Recorded directories were cleaned after exit; no player settings/save callbacks ran. The isolated diagnostic scripts instantiate only the production builders and do not load startup or player settings. Some short source/pooled and LOD diagnostics overlapped the first gameplay attempt; final model/LOD results are independent SubViewport captures and gameplay runs are sequential. No performance comparison is claimed. Native shader-cache persistence warnings under disposable userdata and existing test shutdown RID/ObjectDB warnings remain in their logs.

## Checks and reproduction

The new Godot ray regression failed for all five original models before repair ([log](regression-before.log)). It now reports zero failures for both base geometry and every generated paint LOD ([log](regression-after.log)), with at least 60 front-pane sample rays per model. Samples are restricted to upward/frontward glass triangles so roof/side panes do not misidentify intentional pillars. The preservation checks retain exact original material/transform/glass/other-primitive data and original body vertex records. Re-running the repair on corrected GLBs changes no file bytes. Selected existing model dimensions, pooled material merging, dark reflective glazing and no-range-limit checks report 40 checks/zero failures ([log](existing-model-checks.log)); existing taxi parts also pass ([log](taxi-model-parts.log)).

```sh
.venv/bin/python tools/repair_vehicle_windscreens.py
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --import
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tests/vehicle_windscreens.gd
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tests/taxi_model_parts.gd
.venv/bin/python -m pytest -q -n auto tests/test_vehicle_windscreens.py tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_windscreen_hatchback vqa_windscreen_estate vqa_windscreen_suv vqa_windscreen_pickup vqa_windscreen_panel_van
```

The repair uses the project's installed Shapely 2.1+; no dependency was added. To reproduce the isolated close sheets, invoke native Godot with `--path godot --script res://tools/vehicle_windscreen_capture.gd -- AFTER/fixture.json OUTPUT_DIRECTORY`. For the perspective/LOD run, use the existing `res://tools/visual_quality_audit_runtime.gd` with `lod/fixture.json`. `before/` is immutable pre-fix evidence; recapturing from corrected assets produces the after state. Exact camera poses, framing assertions, light setup, adapter and bounds are retained in each `capture-results.json`/`results.json`; [manifest.json](manifest.json) records source revision and final GLB hashes.

Only VQA-001–005 are covered. Other vehicles/accessories and other audit findings remain open. Exact unseen LOD thresholds, night/wet glazing combinations and performance are not certified.
