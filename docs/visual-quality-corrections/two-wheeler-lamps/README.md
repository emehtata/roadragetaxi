# Two-wheeler lamp attachments (VQA-006, VQA-009–011, VQA-013–015)

The live imported-model overlay used generic bicycle/scooter dimensions after a concrete model had been selected. Motorcycle overlays also inherited car front/rear/reverse lights and indicators. The correction passes the selected model into the overlay builder and its geometry cache key. Four small model-local mount tables use the same scale and source-axis turn as the imported mesh; motorcycle white/red native lenses retain the existing material-state path, and amber overlays sit in the original indicator housings. Model assets, rider geometry, single-beam headlight behavior and server lamp state are unchanged.

## Scope and source measurements

All five live models are covered: motorcycle, bicycle, mountain_bike, e_scooter and e_scooter_grab3d. Both parked and ridden fixtures are rendered. Source +Z is forward; production placement turns it to +X and applies `model_scale`. Independently recorded mount AABBs in `tests/run_tests.gd::TWO_WHEELER_MOUNTS` describe existing stem, handlebar, rear rack/seat, scooter deck and native motorcycle indicator housings. Production lenses overlap those measured mounts within 0.02 m, checked after translation, rotation and elevation.

The changed shared calls are `vehicle()` → `model_vehicle_details(..., model_kind)` → `_model_lens()`. The audit fixture passes its selected model too, and positions its detail mesh at the production road offset. Existing procedural fallback `_bike_lamps()` stays in its existing path. Alternating both model variants in either order across three frames tests cache separation. The existing `run_tests.gd` manifest registration runs the new attachment and cache checks.

| Finding | Corrected source/model state |
|---|---|
| VQA-006 | motorcycle parked: native front/rear lenses and mounted amber indicators |
| VQA-009 | e_scooter_grab3d parked: stem-front/deck-rear pair |
| VQA-010 | bicycle parked: basket/frame-front and rear-rack mounts |
| VQA-011 | mountain_bike parked: handlebar/front and seat-post/rear mounts |
| VQA-013 | motorcycle ridden: same indicator geometry and native lenses |
| VQA-014 | bicycle ridden: same model-specific pair |
| VQA-015 | both scooter ridden variants: same stem/deck pair |

## Close evidence

Before/after manifests retain 160 asserted 400×340 panels each: five models × two riding states × two lighting conditions × eight directions. Native Windows Godot 4.7.2 Forward+ on NVIDIA GeForce RTX 5060 rendered them. Every capture asserts nonempty geometry, framing and three completed draw frames. The original audit remains historical. Day and night diagnostic rigs include all lamp bits (31); single-bit on/off/brake/side/reverse behavior is separately asserted by the production tests.

The following comparison/day/night contact sheets were inspected at native size. Before/after pages use side and front three-quarter comparisons. Day/night pages show front, left, right, front three-quarter and top views. Six further native-size pages cover every rear, rear-three-quarter and elevated panel (60 panels), so all 160 corrected raw views were visually inspected. These are indexed in `review/rear-elevated-index.json`.

- [Comparison 01: motorcycle and bicycle, parked/ridden](review/before_after_01.png)
- [Comparison 02: mountain bike and scooter, parked/ridden](review/before_after_02.png)
- [Comparison 03: Grab3D scooter, parked/ridden](review/before_after_03.png)
- [Day 01](review/after_day_01.png) · [Day 02](review/after_day_02.png) · [Day 03](review/after_day_03.png)
- [Night 01](review/after_night_01.png) · [Night 02](review/after_night_02.png) · [Night 03](review/after_night_03.png)
- [Rear/elevated day 01](review/after_day_rear-elevated_01.png) · [02](review/after_day_rear-elevated_02.png) · [03](review/after_day_rear-elevated_03.png)
- [Rear/elevated night 01](review/after_night_rear-elevated_01.png) · [02](review/after_night_rear-elevated_02.png) · [03](review/after_night_rear-elevated_03.png)
- [Before capture manifest](before/capture-results.json) · [After capture manifest](after/capture-results.json)

## Regression and reproduction

The tests were added before the production change: [before log](regression-before.log) records 112 failures. The resumed [after log](regression-after-resumed.log) records 4,242 checks and zero failures, covering attachment, all lamp bits, native motorcycle material state, alternating model cache, existing lamp pair/single beam, model dimensions and rider feet. Only the two new test functions and adjusted shared lamp-pair expectations are required production regressions. The temporary focused runner was removed after execution; its calls are recorded in the verification manifest.

```sh
.venv/bin/python -m pytest -q -n auto tests/test_godot_manifest.py
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tests/run_tests.gd
.venv/bin/python tools/visual_test.py run vqa_lamps_motorcycle_day vqa_lamps_motorcycle_night --out docs/visual-quality-corrections/two-wheeler-lamps/gameplay
```

Other pairs follow `vqa_lamps_{bicycle,mountain_bike,e_scooter,e_scooter_grab3d}_{day,night}`. Named scenarios use the existing sourced Oulu road pose and existing eye camera. An exact selected model is placed 9 m along that road and 0.9 m left. Normal server pose/time/weather/chunk readiness stays active; the actual pooled mesh must project at least 80 px in both dimensions, stay inside the frame, avoid building footprints/HUD and nearer dynamic bodies, and match parked/ridden lamp bits. Every accepted raw screenshot is visually inspected; natural pedestrian occlusion rejects evidence even when earlier framing checks passed.

Player settings are isolated with the existing per-run verification bootstrap and cleaned afterwards. Native shader-cache persistence warnings under renamed temporary userdata are retained in logs; no lamp script/readiness error is waived. One initial target placement at 5 m/2.7 m failed framing/HUD readiness. Early motorcycle-night and bicycle-day frames had a pedestrian across the model and receive no visual credit. One multi-case wrapper exited 143 during the mountain-bike map build; no child remained and that case was rerun. Failed/unaccepted attempts remain documented; no screenshot from an incomplete run is counted.

Gameplay result table, exact source revision, hashes and inspection states are in [manifest.json](manifest.json). Independent tester approval is a separate ship step.

Unverified: arbitrary weather/map combinations, headlight optics and other audit findings. Bright player headlights can wash out fine lens detail in night gameplay; native-size close sheets and geometric attachment checks supplement those views.

The Grab3D scooter rear lens is attached at its measured deck mount and is visible only as a small red sliver above the native wheel/fender in a direct rear view. This fix does not enlarge or redesign the model lamp optics. Existing eye-camera cockpit masks can cover a wheel tip in scooter gameplay; both front and rear lens locations remain visible, and the eight-direction isolated sheets inspect the whole vehicle.

## Accepted named gameplay evidence

All ten accepted screenshots were inspected by the implementer. Day is parked/off; night is ridden/on. The following model crops retain source pixels; scene thumbnails are at50% solely for context.

[Gameplay page01](review/gameplay_01.png) · [page02](review/gameplay_02.png) · [page03](review/gameplay_03.png)

| Scenario | Model bounds (px) | Evidence |
|---|---|---|
| `vqa_lamps_motorcycle_day` | 345×209 | [image](gameplay/vqa_lamps_motorcycle_day/2026-06-20T1500_20261115-184714_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_motorcycle_day/2026-06-20T1500_20261115-184714_24f28efb-dirty/result.json) |
| `vqa_lamps_motorcycle_night` | 345×209 | [image](gameplay/vqa_lamps_motorcycle_night/2026-10-20T2250_20261115-185143_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_motorcycle_night/2026-10-20T2250_20261115-185143_24f28efb-dirty/result.json) |
| `vqa_lamps_bicycle_day` | 297×206 | [image](gameplay/vqa_lamps_bicycle_day/2026-06-20T1500_20261115-185230_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_bicycle_day/2026-06-20T1500_20261115-185230_24f28efb-dirty/result.json) |
| `vqa_lamps_bicycle_night` | 297×206 | [image](gameplay/vqa_lamps_bicycle_night/2026-10-20T2250_20261115-185000_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_bicycle_night/2026-10-20T2250_20261115-185000_24f28efb-dirty/result.json) |
| `vqa_lamps_mountain_bike_day` | 292×203 | [image](gameplay/vqa_lamps_mountain_bike_day/2026-06-20T1500_20261115-185324_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_mountain_bike_day/2026-06-20T1500_20261115-185324_24f28efb-dirty/result.json) |
| `vqa_lamps_mountain_bike_night` | 292×203 | [image](gameplay/vqa_lamps_mountain_bike_night/2026-10-20T2250_20261115-185412_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_mountain_bike_night/2026-10-20T2250_20261115-185412_24f28efb-dirty/result.json) |
| `vqa_lamps_e_scooter_day` | 283×219 | [image](gameplay/vqa_lamps_e_scooter_day/2026-06-20T1500_20261115-185554_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_e_scooter_day/2026-06-20T1500_20261115-185554_24f28efb-dirty/result.json) |
| `vqa_lamps_e_scooter_night` | 283×219 | [image](gameplay/vqa_lamps_e_scooter_night/2026-10-20T2250_20261115-185642_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_e_scooter_night/2026-10-20T2250_20261115-185642_24f28efb-dirty/result.json) |
| `vqa_lamps_e_scooter_grab3d_day` | 281×206 | [image](gameplay/vqa_lamps_e_scooter_grab3d_day/2026-06-20T1500_20261115-185752_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_e_scooter_grab3d_day/2026-06-20T1500_20261115-185752_24f28efb-dirty/result.json) |
| `vqa_lamps_e_scooter_grab3d_night` | 281×206 | [image](gameplay/vqa_lamps_e_scooter_grab3d_night/2026-10-20T2250_20261115-185948_24f28efb-dirty/screenshot.png) · [readiness](gameplay/vqa_lamps_e_scooter_grab3d_night/2026-10-20T2250_20261115-185948_24f28efb-dirty/result.json) |
