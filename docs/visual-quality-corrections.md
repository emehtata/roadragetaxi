# Visual quality corrections

## VQA-035–037: responsive gameplay HUD

The gameplay HUD now keeps its default fare meter clear of the scaled money/clock/weather panel, wraps oversized notice and control text within 20-pixel horizontal margins, and places the lower control hint six pixels above the OpenStreetMap credit. The meter still uses `HudLayout.place`, and its offset starts from the same responsive default during dragging. Explicit offsets/scales and player files are retained. Fonts, text, colors, notice priority and data-source notice timing are unchanged.

The [original audit](visual-quality-audit.md) and all original finding images remain unchanged. This correction covers VQA-035 (meter/status), VQA-036 (fuel instruction) and VQA-037 (control/attribution); it does not close VQA-034 or other audit findings.

Six named scenarios reuse `third_oulu_dense`: the sourced Oulu city-centre square pose, clear weather/cloud 0.4 and 2026-06-20 15:00. Their client-only HUD display fixture supplies the affected branch while the server pose, game state and camera remain under normal scenario readiness. Captures also require the exact HUD branch/text, requested viewport size, on-screen rectangles and meter/status or hint/credit separation for the normal 60 stable frames. The result retains capture-time HUD rectangles and readiness while the asynchronous server debug request runs.

All six PNGs below were visually inspected on 2026-11-15. Each result reports `passed` with empty HUD readiness errors. Native Windows Godot 4.7.2 / Forward+ Vulkan / NVIDIA GeForce RTX 5060 produced the images. The player's existing Finnish language setting is visible; isolated layout assertions additionally cover English and German.

| Scenario | Viewport | Evidence |
|---|---|---|
| `vqa_hud_fare_1280` | 1280×720 | [screenshot](visual-quality-corrections/hud-verified/vqa_hud_fare_1280/2026-06-20T1500_20261115-131651_209df9df-dirty/screenshot.png) · [readiness](visual-quality-corrections/hud-verified/vqa_hud_fare_1280/2026-06-20T1500_20261115-131651_209df9df-dirty/result.json) |
| `vqa_hud_fare_800` | 800×600 | [screenshot](visual-quality-corrections/hud-verified/vqa_hud_fare_800/2026-06-20T1500_20261115-131426_209df9df-dirty/screenshot.png) · [readiness](visual-quality-corrections/hud-verified/vqa_hud_fare_800/2026-06-20T1500_20261115-131426_209df9df-dirty/result.json) |
| `vqa_hud_fuel_stop_1280` | 1280×720 | [screenshot](visual-quality-corrections/hud-verified/vqa_hud_fuel_stop_1280/2026-06-20T1500_20261115-131738_209df9df-dirty/screenshot.png) · [readiness](visual-quality-corrections/hud-verified/vqa_hud_fuel_stop_1280/2026-06-20T1500_20261115-131738_209df9df-dirty/result.json) |
| `vqa_hud_fuel_stop_800` | 800×600 | [screenshot](visual-quality-corrections/hud-verified/vqa_hud_fuel_stop_800/2026-06-20T1500_20261115-131515_209df9df-dirty/screenshot.png) · [readiness](visual-quality-corrections/hud-verified/vqa_hud_fuel_stop_800/2026-06-20T1500_20261115-131515_209df9df-dirty/result.json) |
| `vqa_hud_house_hint_1280` | 1280×720 | [screenshot](visual-quality-corrections/hud-verified/vqa_hud_house_hint_1280/2026-06-20T1500_20261115-132010_209df9df-dirty/screenshot.png) · [readiness](visual-quality-corrections/hud-verified/vqa_hud_house_hint_1280/2026-06-20T1500_20261115-132010_209df9df-dirty/result.json) |
| `vqa_hud_house_hint_800` | 800×600 | [screenshot](visual-quality-corrections/hud-verified/vqa_hud_house_hint_800/2026-06-20T1500_20261115-131603_209df9df-dirty/screenshot.png) · [readiness](visual-quality-corrections/hud-verified/vqa_hud_house_hint_800/2026-06-20T1500_20261115-131603_209df9df-dirty/result.json) |

### Verification and reproduction

The new production-HUD regression script first failed with 33 layout failures on the original code. A separate first-drag regression then caught and removed a default-position jump. Final assertions pass for en/fi/de, both sizes, repeated 1280→800→1280 resizing, custom meter/status offsets and scales, full fuel text, reset to short/empty notices, and house/home/building hint priority and credit clearance.

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tests/hud_responsive_layout.gd
.venv/bin/python -m pytest -q -n auto tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_hud_fare_800 vqa_hud_fuel_stop_800 vqa_hud_house_hint_800 vqa_hud_fare_1280 vqa_hud_fuel_stop_1280 vqa_hud_house_hint_1280
```

The headless script reports zero failures; targeted pytest reports three passed. Changed GDScripts pass Linux Godot `--check-only`, and `git diff --check` passes. Both window sizes use an unsaved `HudLayout.new(false)` for the assertions and display fixtures; no player layout file is saved or migrated.

The initial capture-metadata attempt was discarded because the server debug wait let the live HUD replace fixture metadata after capture. The corrected sequential wrapper exited 143 after five successful cases; no child process remained, and the final 1280 hint case was rerun individually and passed. Native renderer/ObjectDB cleanup warnings are retained in logs after successful captures; no HUD runtime script error occurred. This slice does not verify unrelated rendering defects, arbitrary saved panel placements or window sizes below those specified.


## VQA-034: responsive indoor control hint

The shared HomeFirstPerson hint now wraps within 12-pixel horizontal margins and grows upward from its existing 12-pixel bottom clearance. Its natural minimum height is reapplied after each composed prompt update, so the shorter hint and wider window recover their height. Translations, font, shadow, alignment, mouse filtering, camera and input behavior are retained. The original audit evidence remains unchanged.

The named `vqa_indoor_hint_640` and `vqa_indoor_hint_1280` scenarios first satisfy the existing Oulu pose/map/weather/camera checks, then instantiate the actual HomeFirstPerson/HomePlayer3D view over a recorded compact L-shaped house footprint. Fixture `footprint:compact-L1` is `tests/data/home_plans.json` index 32, generated from `tests/test_home_interior.py::COMPACT_L_HOUSES[0]`; the footprint is mapped, the interior is generated and the real address is withheld. No server entry request is fabricated. The player settles on the floor at the entrance, with choose-home and click-to-resume prompts active.

Indoor readiness requires requested viewport size, loaded nonempty floor mesh, current existing indoor camera, floor contact, exact complete localized prompt, unclipped text bounds/lines and stable frames. A tiny verification bootstrap changes the project userdata name before startup instantiates, so player settings and saves are not read by the accepted captures. The Python runner deletes its disposable settings folder afterward. Results retain its unique name and capture-time hint/camera metadata while the exterior debug request completes.

All four images were visually inspected on 2026-11-15. German is rendered at both sizes; English and Finnish wrapping at 640×480 is additionally rendered. At 640×480 the full prompt is two lines in all three locales; at 1280×720 German is one line. Headless assertions cover all locales at both sizes.

| Named scenario | Locale | Viewport | Visible lines | Evidence |
|---|---|---|---|---|
| `vqa_indoor_hint_640` | en | 640×480 | 2 | [image](visual-quality-corrections/indoor-hint/accepted/en/vqa_indoor_hint_640/2026-06-20T1500_20261115-134529_169c2ecd-dirty/screenshot.png) · [readiness](visual-quality-corrections/indoor-hint/accepted/en/vqa_indoor_hint_640/2026-06-20T1500_20261115-134529_169c2ecd-dirty/result.json) |
| `vqa_indoor_hint_640` | fi | 640×480 | 2 | [image](visual-quality-corrections/indoor-hint/accepted/fi/vqa_indoor_hint_640/2026-06-20T1500_20261115-134617_169c2ecd-dirty/screenshot.png) · [readiness](visual-quality-corrections/indoor-hint/accepted/fi/vqa_indoor_hint_640/2026-06-20T1500_20261115-134617_169c2ecd-dirty/result.json) |
| `vqa_indoor_hint_1280` | de | 1280×720 | 1 | [image](visual-quality-corrections/indoor-hint/accepted/vqa_indoor_hint_1280/2026-06-20T1500_20261115-134429_169c2ecd-dirty/screenshot.png) · [readiness](visual-quality-corrections/indoor-hint/accepted/vqa_indoor_hint_1280/2026-06-20T1500_20261115-134429_169c2ecd-dirty/result.json) |
| `vqa_indoor_hint_640` | de | 640×480 | 2 | [image](visual-quality-corrections/indoor-hint/accepted/vqa_indoor_hint_640/2026-06-20T1500_20261115-134340_169c2ecd-dirty/screenshot.png) · [readiness](visual-quality-corrections/indoor-hint/accepted/vqa_indoor_hint_640/2026-06-20T1500_20261115-134340_169c2ecd-dirty/result.json) |

Verification: the new production-view checks first produced 15 failures on the original fixed-width hint. They now pass all eight exit/home/mouse prompt combinations for en/fi/de, repeated 1280→640→1280 resizing, long→short restoration and stable repeated layout. Existing lifecycle/controller checks across 35 plans also pass. Relevant manifest pytest passes three tests. Linux Godot imports and changed-script parsing pass.

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tests/home_first_person.gd
.venv/bin/python -m pytest -q -n auto tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_indoor_hint_640 vqa_indoor_hint_1280
```

The en/fi images use the same named 640 scenario with only `indoor_hint.language` changed via `tools.visual_test.run_one`; their exact resolved scenario JSON is retained alongside each result. The bootstrap uses disposable `rrt-indoor-hint-*` userdata, which causes native shader-cache write errors after the runtime name change; these affect cache persistence, and no hint script error or readiness failure occurred. Logs retain those errors. A preliminary APPDATA-based isolation was ineffective on Windows and was replaced; a linked temporary-project attempt could not load the scene through Windows UNC symlinks and is retained only as a failed startup log. None of those preliminary captures is accepted evidence. Headless shutdown retains existing fallback-test and ObjectDB warnings.

This correction does not verify smaller viewports, other audit defects, surveyed interior layouts or runtime rendering performance.

## VQA-001–005: continuous vehicle windscreens

Residual painted triangles were clipped from the existing front-glass footprint in the hatchback, estate, SUV, pickup and panel-van GLBs. Source-versus-pooled comparison confirms the artifacts were present in the imported geometry. Glass, materials, model transforms, other primitives and shared rendering/LOD behavior remain unchanged. [Correction notes, before/after contact sheets and five passing named gameplay captures](visual-quality-corrections/vehicle-windscreens/README.md) retain the diagnosis, deterministic repair, preservation checks and inspected evidence. The original audit remains historical.

## VQA-006, VQA-009–011, VQA-013–015: attached two-wheeler lights

The selected bicycle/scooter model now controls its live lens anchors and overlay cache key. Motorcycle white/red native lenses retain their existing state path; amber indicators sit in their native housings instead of inheriting detached generic car lamps. Existing models, rider geometry, fallback lamps and single-beam behavior are retained. [Diagnosis, before/after sheets, production regressions and exact-model named gameplay evidence](visual-quality-corrections/two-wheeler-lamps/README.md) cover the five source models, parked/ridden daylight and lit night states. Original audit findings remain historical; the independent ship review passed.

## VQA-012 — train coach roof vent

The existing source HVAC assembly was 0.32 m above its roof. Only its 914 vertex
heights are lowered; preservation, attachment, pooled transforms and sampled LOD
regressions pass. All 48 comparison panels and a passing named flat-terrain
Helsinki gameplay capture are inspected. Earlier failed attempts and a buried
coach false positive are explicitly excluded. See
[diagnosis, evidence and coverage](visual-quality-corrections/train-coach-roof-vent/README.md).

## Reflective chest bands (VQA-016)

Variant 4 now clips its existing pale bands from the actual jacket triangles, removing the fixed-plane gap while retaining the cached body/shadow path. [Diagnosis, checks and visual evidence](visual-quality-corrections/pedestrian-reflective-strips/README.md) include 393 focused checks with zero failures (102 original failures), 66 preservation fingerprints, all 96 inspected before/after panels and the inspected passing `vqa_reflective_strips_day` gameplay capture. The historical audit is unchanged.

## Fox forward axis (VQA-017)

The fox source yaw now turns its diagonal +X/+Z body/head direction onto local +X before the production heading. [Diagnosis, regression and visual evidence](visual-quality-corrections/fox-orientation/README.md) record 229 passing Linux animal checks, 225 passing native checks, 12 passing targeted Python tests, all 32 inspected comparison panels and an inspected passing `vqa_fox_orientation_day` capture. Source GLB bytes and shared animal code remain unchanged.

## VQA-018: horizontal attached felled-tree trunk

The felled-tree branch now scales its rotated cylinder on local axes, grounds its true radius and moves its existing crown 0.3 radii inward so the surfaces intersect. Standing trees and server fall decisions retain their existing paths. [Diagnosis, geometry/native regressions, 96 comparison panels and passing named Bulevardi capture](visual-quality-corrections/felled-tree-geometry/README.md) record the correction and sampled coverage.
