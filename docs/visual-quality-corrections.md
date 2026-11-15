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
