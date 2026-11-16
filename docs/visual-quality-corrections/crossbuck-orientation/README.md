# Crossbucks face road approaches (VQA-020)

The crossbuck boards now run across the road, with broad face normals along its approach axis. The two posts retain their original positions. Implementation is ready for independent review; no commit was made by the implementer. Historical audit images and the finding remain unchanged.

## Cause and correction

`osm/build.py` classifies `railway=level_crossing` and `_snap_to_nearest_road()` supplies its road `direction_angle`. `map_chunks.py` sends rounded `[x,y,kind,angle]` scenery rows. `map_chunk._ground_dict()` maps the position with `MapMath.point()` and passes the angle unchanged to `props()` → `_gap_prop()`. Client along is `(cos(angle),-sin(angle))`; `to_3d()` maps that to `(cos(angle),0,-sin(angle))`.

The old branch passed `post ± along*0.6` to `_sloped_wall()`. Its actual broad triangles had normals perpendicular to road approach (absolute dot product 0); approach cameras therefore saw only 3 cm edges. The two-line correction passes `post ± across*0.6`, giving absolute broad-normal/approach dot product 1. The two X diagonals keep the same 1.2 m span, 0.03 m thickness, 0.15 m vertical board height and endpoints at 1.8/2.5 m. Posts stay 4 m either side of the road, with 0.10×0.10 m sections and 2.6 m height. Colours, materials, winding, shadow settings, barriers and wires retain their existing paths. The expected crossbuck fingerprint in the earlier tower preservation control is intentionally updated; other fingerprints are retained.

The Finnish NPC traffic-law guide was read, including its railway safety and control-direction requirements. This changes client display geometry only; no server priority, crossing applicability, barrier/signal decision or legal rule is altered. This visual correction is not a certification of crossing behavior.

## Regression and inspected views

- [Original geometry](regression-before.log): **949 checks, 194 failures** with the final regression against an isolated copy of the original production builder.
- [Corrected Linux](regression-after.log) and [native Windows](regression-native.log): **949 checks, 0 failures** each. Tests inspect actual broad-face triangle normals, dimensions, distinct diagonals, attachment cross-sections, posts, headings 0/π÷2/π/0.73, translated positions, ground 0/13.5 m, final chunk mesh, rebuild, replacement, unload and reload.
- [Existing scenery/build/ground controls](regression-controls.log): **216 checks, 0 failures**, including barriers and power lines. Existing headless dummy-renderer/resource shutdown warnings remain in the log.
- [Manifest pytest](pytest.log): **3 passed**. Changed scripts parse and `git diff --check` passes.

All **32 before/after panels** were inspected: eight directions through the production builder/material at close orthographic framing, and eight directions at a fixed **20 m**, 40° perspective FOV. Native Windows Godot 4.7.2, Forward+ Vulkan / NVIDIA GeForce RTX 5060; panels 400×340. Three draw frames and full bounds/frustum framing are required per panel. Front and rear now show full X marks; side views correctly see edges; three-quarter/top/elevated views retain attached boards and grounded posts.

- [Close front/rear/sides](review/crossbuck_close_1.png) · [close oblique/top/elevated](review/crossbuck_close_2.png)
- [20 m front/rear/sides](review/crossbuck_perspective_1.png) · [20 m oblique/top/elevated](review/crossbuck_perspective_2.png)
- [Before capture metadata](before/capture-results.json) · [after capture metadata](after/capture-results.json) · [fixture](fixture.json)

## Passing mapped gameplay capture

`vqa_crossbuck_orientation_day` uses actual mapped OSM node **1018789030**, `Henkilölaituri, pohjoispää`, at **428628.265866,7210670.781369**, source road angle **2.61975761 rad**. The server sends **428628.3,7210670.8,2.620**. The [normal Oulu map query](map-query.log) records the source; the scenario creates no crossing fixture. Its existing eye camera is at road pose **428641.0,7210663.5,2.620**. Flat terrain (`--no-terrain-dem80`) isolates this geometry sample and avoids certifying DEM behavior.

The [accepted screenshot](gameplay/retry/vqa_crossbuck_orientation_day/2026-06-20T1500_20261116-222319_0bc48d0d-dirty/screenshot.png) is inspected: both target crossbucks are fully recognizable and unobscured. The [result](gameplay/retry/vqa_crossbuck_orientation_day/2026-06-20T1500_20261116-222319_0bc48d0d-dirty/result.json) reports **passed**, empty errors, active 3D, all **132 actual mesh vertices** matched within 1 mm, ground **0 m**, expected angle **2.620**, and each board assembly **115.17×81.18 px** in a **1280×720** frame. Readiness also requires active camera/display/cull layers, useful full-board frustum/HUD clearance, face approach visibility, grounded feet, actual drawn-building BVH clearance and no nearer dynamic body over either board rectangle, plus normal map/time/weather/chunk readiness. Disposable userdata was removed.

An initial gameplay launch loaded an intermediate parse-error script and was explicitly stopped, with no result/screenshot; its logs under `gameplay/initial` are excluded. A 25° perspective framing attempt rejected the widest corrected diagonal view; the 40° captures replace it and all accepted panels pass full framing. Shader-cache persistence errors from disposable native settings are retained and do not constitute a readiness pass by themselves. No rejected attempt receives visual credit.

## Reproduction

Source revision before this slice: **0bc48d0d** (shared tree dirty). Temporary runners are retained as text and must be copied to `godot/tools/` for the run, then removed. For original source reproduction, `git show 0bc48d0d:godot/buildings_3d.gd` supplies `_tmp_crossbuck_before.gd`; the original test suite changes only its B3 preload to that copy. Captures likewise use the same production builder copy; source assets are unchanged.

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_crossbuck_tests.gd
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_crossbuck_controls.gd
.venv/bin/python -m pytest -q -n auto tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_crossbuck_orientation_day --out docs/visual-quality-corrections/crossbuck-orientation/gameplay
```

For native close capture, use `C:\Godot\Godot_v4.7.2-stable_win64_console.exe --path GODOT_PROJECT --script res://tools/_tmp_crossbuck_capture.gd -- FIXTURE_JSON OUTPUT_DIR`; paths must be Windows paths (`wslpath -w` under WSL). [Capture runner](capture-runner.txt), [focused runner](focused-runner.txt), [control runner](controls-runner.txt), and [map query](map-query-runner.txt) record exact fixture/run construction.

Gameplay coverage samples one daylight flat-terrain approach; other map, lighting, terrain and traffic combinations remain unverified. Sign artwork, crossing layout and all other audit findings are outside this slice.
