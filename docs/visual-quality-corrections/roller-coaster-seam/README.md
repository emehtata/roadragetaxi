# Roller-coaster seam (VQA-021)

The source path is closed, but the former renderer sampled its closing duplicate at index 48 instead of 0. The production 48-segment path therefore ended at **5.014972 m**, above its **4.500000 m** start: an opening of **0.514972 m**. The one-line fix wraps only the closing endpoint's sample index. It keeps all other samples, supports, footprint coordinates, segment count, width, colours and other attraction branches unchanged. It adds no new runtime work beyond one modulo per segment during the existing chunk mesh build.

The production path is `osm/theme_parks.py::prepare_theme_parks()` → `make_ride()` (48 interpolated samples and duplicate start) → `map_chunks.py::ChunkIndex`'s `attractions` row → `map_chunk.gd::prepare()` → `buildings_3d.gd::_structures()` → `attractions()` → `_sloped_strip()`. No server path or 2D rendering changed.

`test_roller_coaster_track_closes` examines actual red strip triangles, corner/width retention and centreline endpoints at every junction. It covers 4/17/48/64 segments, rotation and translation. The preservation test independently reconstructs original intermediate strips/supports, compares all unaffected geometry and closing footprint coordinates, tests flat/13.5 m ground through the final builder, the short-path guard and actual chunk replacement/unload/reload.

- Original: [4,338 checks, 8 failures](regression-before.log), one closing-seam failure for every count/heading combination.
- Corrected: [Linux 4,338/0](regression-after.log) and [native Windows 4,338/0](regression-native.log).
- Existing building/scenery/attraction, grounded deck and chunk replacement controls: [216/0](regression-controls.log). Existing dummy-renderer/shutdown resource warnings are retained in the log.
- [Targeted pytest](pytest.log): `tests/test_theme_parks.py` and `tests/test_godot_manifest.py`, **7 passed**.
- Changed production/test/readiness scripts parse; scoped diff check passes.

All **32 comparison panels** were visually inspected: eight isolated directions before/after and eight normal-distance perspective views before/after at **55 m**, with normal production materials. Native Windows Godot 4.7.2 Forward+ Vulkan / NVIDIA GeForce RTX 5060 rendered 400×340 panels. Each capture requires three completed draw frames and a fully framed target. The closing height discontinuity is removed; the nearby strips and supports remain. Track corner-width joins and support redesign remain outside this correction.

- [Close front/rear/sides](review/coaster_1.png) · [three-quarter/top/elevated](review/coaster_2.png)
- [55 m front/rear/sides](review/coaster_perspective_1.png) · [three-quarter/top/elevated](review/coaster_perspective_2.png)
- [Before manifest](before/capture-results.json) · [after manifest](after/capture-results.json) · [fixture](fixture.json)

## Named scenario

`vqa_roller_coaster_seam_day` uses mapped **OSM node 287563015, Pikajuna, Linnanmäki**. The existing normal `prepare_theme_parks()` node footprint and `make_ride()` algorithm generate a representative closed 49-point track; this is representative geometry, not a reconstruction of real Pikajuna. The first/closing point is **385678.910470, 6674083.753879** (EPSG:3067). The sourced drivable Tivolikuja segment midpoint **385812.594401, 6674274.718709** holds the taxi; the existing `camera_at` facility holds the top camera on the actual mapped ride centre. [Source query](source-query.log), [normal-pipeline query runner](source-query-runner.txt), [building containment check](source-building-check.log) and [source paths](map-source.json) retain provenance. The source is the existing cached OSM dataset already attributed in game; no new source is added.

Readiness compares all 49 source path samples, matches every actual track/support vertex within 1 mm in the rendered chunk mesh, and identifies the requested first/closing point. It requires active 3D, a useful projected first/last strip region around the seam, visible top faces, ground clearance and frustum/HUD/building/dynamic-body clearance, plus all standard map/weather/time checks. Building occlusion reuses existing cached triangle BVHs. The scenario disables DEM for this flat geometry sample and uses disposable client settings.

The Pikajuna run passed with **768 matched mesh vertices**, **49 path points**, **38×45 px seam region**, **active 3D**, **0 m ground**, and **empty errors**. Its screenshot was inspected: the right-hand seam and adjacent red strips are clearly visible and meet. A translucent nearby structure partly overlays other track sections, but the checked seam region is exposed. The final guard revision also passed with no script errors; its [accepted screenshot](gameplay/accepted/vqa_roller_coaster_seam_day/2026-06-20T1300_20261117-080844_6187be40-dirty/screenshot.png) was inspected against the [readiness result](gameplay/accepted/vqa_roller_coaster_seam_day/2026-06-20T1300_20261117-080844_6187be40-dirty/result.json). Native runtime retains existing shader-cache/shutdown warnings in its log.

Excluded attempts: an initial standalone server map query was externally terminated (exit 143) before producing source results, then the bounded cached-source query completed. The first Ukko named run had an in-flight scenario revision mismatch: the runner rewrote its original spec without the newly added path key, and its readiness exception incorrectly yielded a pass. That entire run and screenshot are rejected. Missing/invalid path guards now reject cleanly. Two subsequent Ukko attempts were stopped after readiness correctly reported offscreen framing and a genuinely occluding building; source geometry confirms that the representative Ukko seam is inside a mapped building. The final scenario uses uncovered Pikajuna instead. None of the Ukko or diagnostic attempts receives visual credit.

## Reproduction

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --check-only --script res://buildings_3d.gd
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_coaster_tests.gd
.venv/bin/python -m pytest -q -n auto tests/test_theme_parks.py tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_roller_coaster_seam_day --out docs/visual-quality-corrections/roller-coaster-seam/gameplay
```

The temporary focused/control/capture scripts are retained as `*-runner.txt`; copy them under `godot/tools/` for reproduction and remove them afterwards. For before geometry, run the capture on `6187be40`'s builder in a disposable worktree. The capture runner takes fixture/output paths; native Windows execution requires `wslpath -w`. Historical audit images/register remain unchanged.

Visual coverage samples these views, one daylight map scenario and constant ground heights. It does not certify every park, terrain slope, camera or lighting combination.
