# Power-tower leg continuity (VQA-019)

The source was three vertical square posts per corner, centred at offsets 2.0, 1.4 and 0.8 m from the tower centre. At each height boundary their 0.24 m square cross-sections were shifted 0.6 m in both horizontal axes. The nearest corners therefore had a **0.509 m surface gap** (`sqrt(2) * (0.6 - 0.24)`), confirmed by triangle-plane cross-sections and the original views.

The tower branch now builds one square post per corner and shears its upper end inward. It runs continuously from the existing offset 2.0 m feet to the existing offset 0.8 m top, retaining the 0.24 m horizontal thickness and requested height. All four supports are slender, with no joint blocks or solid infill. The two crossarms are byte-identical. Final chunk construction computes normals after the shear and keeps normal shadow casting. Geometry decreases from 396 to 156 vertices (12 leg posts become four); no per-frame work is added.

The production path is server `ChunkIndex` → `scenery_objects` → `map_chunk._build_3d()` ground prop rows → `Buildings3D.build()` → `_ground()` / `_structures()` → `props()` → `_gap_prop("power_tower")` → final chunk deck mesh. The row contract, ground adaptation, material and power-line path are unchanged. Other audit findings and full tower lattice/bracing design are outside this slice.

## Regression evidence

- [Original](regression-before.log): **3,625 checks, 480 failures**, including broken cross-sections at both section boundaries. The count changes with topology because every final triangle is checked.
- [Corrected Linux](regression-after.log): **2,185 checks, 0 failures**.
- [Native Windows](regression-native.log): **2,185 checks, 0 failures**.
- [Existing controls](regression-controls.log): **216 checks, 0 failures**, covering scenery heights, power lines, building/chunk replacement and ground-height behavior. Existing dummy-renderer/ObjectDB shutdown warnings remain in this control log.
- [Manifest pytest](pytest.log): **3 passed**. Changed scripts parse and `git diff --check` passes.

`test_power_tower_legs_connected` intersects actual leg triangles at the former boundaries, just above/below them and near both ends. It checks four .24 m cross-sections and their independent expected taper, preventing missing legs, detached sections or thick infill from passing. Coverage includes heights 10/22/45 m, default/explicit 22 m, positions (0,0)/(17,-23), angles 0/π/2/0.73, flat and constant 13.5 m ground. Preservation checks retain crossarms exactly, verify nondegenerate triangles/unit normals, record unaffected prop/wire fingerprints at 1 mm precision, and exercise actual chunk replacement/unload/reload plus shadow settings. The 1 mm fingerprints accommodate tiny platform trigonometry differences in existing round props; tower attachment is checked geometrically.

## Inspected comparison views

All **64 panels** were inspected: before/after front, rear, both sides, both three-quarter, top and elevated views for heights 10/22/45 m, plus a 22 m tower at **80 m** with perspective FOV 25°. Each capture checks three draw frames and complete bounds framing. Native Windows Godot 4.7.2 Forward+ Vulkan on NVIDIA GeForce RTX 5060 rendered the 400×340 panels with the production builder/material. The repaired views show four continuous supports; existing crossarms and tower colours retain their appearance.

- 10 m [ends/sides](review/tower_10_1.png), [three-quarter/top/elevated](review/tower_10_2.png)
- 22 m [ends/sides](review/tower_22_1.png), [three-quarter/top/elevated](review/tower_22_2.png)
- 45 m [ends/sides](review/tower_45_1.png), [three-quarter/top/elevated](review/tower_45_2.png)
- 80 m perspective [ends/sides](review/tower_22_perspective_1.png), [three-quarter/top/elevated](review/tower_22_perspective_2.png)
- [Fixture](fixture.json), [before captures](before/capture-results.json), [after captures](after/capture-results.json), [manifest](manifest.json)

## Named real-map gameplay

The named scenario `vqa_power_tower_legs_day` reuses `drive_power_poles_day`'s sourced Oulu service-road pose **426307.2,7209696.8, heading 1.601**. [Map query](map-query.log) identifies actual OSM power=tower node **3748249674** at **426325.0388,7209689.2828**, 19.4 m away. The server rounds its wire row to 426325.0,7209689.3. It has no height tag, so the existing production default is **22 m**. The query initially loaded only the start cache subset; normal tile-cache preparation supplied the mapped tower, without constructing a gameplay fixture.

Readiness matches all 156 expected vertices against the actual drawn chunk deck mesh within 1 mm (to allow the mesh float roundtrip), requires active displayed 3D, mapped identity/height, frustum/HUD clearance, useful whole-tower and leg-joint size, exact terrain foot clearance within 5 mm and unobscured joint sightlines through actual building meshes. Nearer dynamic body bounds must be clear. Normal map/time/weather/chunk readiness is retained. The existing top camera is used; `--no-terrain-dem80` isolates this geometry check, and disposable userdata preserves player settings. A passing screenshot is inspected before this slice receives visual credit.

**PASS and inspected:** [accepted screenshot](gameplay/accepted/vqa_power_tower_legs_day/2026-06-20T1500_20261116-220301_1e1e36e7-dirty/screenshot.png) and [readiness](gameplay/accepted/vqa_power_tower_legs_day/2026-06-20T1500_20261116-220301_1e1e36e7-dirty/result.json). The mapped tower is visibly clear and continuous in the actual 1280×720 gameplay view: **126.9×191.8 px** bounds, minimum projected leg/joint width **5.30 px**, all **156 vertices matched**, active 3D, ground **0 m**, empty errors. Native renderer is Forward+ on NVIDIA GeForce RTX 5060.

Three earlier attempts are retained and excluded. The first exact-float membership comparison rejected the mesh roundtrip; the next 1 mm bucket comparison still rejected bucket-boundary roundoff. The final cached distance comparison matches within 1 mm. A third attempt correctly rejected the initial readiness ground check, which accidentally used the road surface's 2 cm lift; tower feet stand on the terrain, so the final check calls `deck_height(..., road=false)`. None of these failed attempts produced accepted evidence. Isolated native userdata causes existing shader-cache write errors in the logs; scene rendering and accepted readiness pass.

## Reproduction

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_power_tests.gd
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_power_existing.gd
.venv/bin/python -m pytest -q -n auto tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_power_tower_legs_day --out docs/visual-quality-corrections/power-tower-legs/gameplay
```

Copy [focused-runner.txt](focused-runner.txt) and [controls-runner.txt](controls-runner.txt) to the temporary paths above for those runs; remove them afterwards. [capture-runner.txt](capture-runner.txt) is the production audit capture script with the additional 80 m perspective fixture support. Run it with fixture/output directory arguments using native Windows Godot under WSL. For original capture reproduction, use the tower branch from source revision `1e1e36e7`; preserve unrelated work in an isolated checkout. [map-query-runner.txt](map-query-runner.txt) records the data lookup. No original audit image or finding is overwritten.

Visual coverage samples the listed heights and one daylight flat-terrain map view. Sloping terrain, every viewpoint/lighting combination and full structural bracing are not certified by these samples.
