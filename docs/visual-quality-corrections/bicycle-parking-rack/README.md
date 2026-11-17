# Open bicycle-parking rack (VQA-027)

The solid bar is replaced by four open metal frames. All **32 before/after panels** and the passing named screenshot were inspected.

OSM `amenity=bicycle_parking` enters `_scenery_object_kind()` in `osm/build.py`. Normal `build_ways()` snaps its position just beyond the nearest path edge and sets `direction_angle` along that path. The streamed `scenery_objects` row enters `map_chunk.prepare()` / `_structures()` as ground props, then `Buildings3D.props()` emits the final chunk deck. The former generic fallback extruded one **3.0×0.6×0.8 m** cuboid. Its surfaces filled every intended opening. The existing 2D branch draws four transverse hoops at local X **−1.2/−0.4/0.4/1.2 m**.

The rack-only branch reuses `_raised_polygon_at()` for two uprights and a cap per hoop. Each member is **0.06 m** thick, the upper bar is at **0.74–0.8 m**, and each opening is **0.48 m wide × 0.74 m high**. Uprights touch the ground and overlap the cap. Hoops are spaced **0.8 m** apart, with **0.74 m** gaps between their 6 cm members. The original oriented 3.0×0.6 m envelope, 0.8 m height and metal palette remain; the four frames occupy 2.46 m of its length. The existing static chunk material, normals/winding helpers and deck shadow path are reused. No asset/dependency/data source or per-frame geometry work is added.

## Checks

The preserved original cuboid fails **264 of 659 checks** in [the regression](regression-before.log). The initial regression was added before the geometry repair; a shadow assertion that incorrectly required the chunk's ground plane to cast shadows was corrected to check the actual rack deck. [Linux](regression-after.log) and [native](regression-native.log) final runs pass **1,539/0** each. The checks inspect actual triangle intersections: four complete connected caps/uprights, unobstructed openings and inter-hoop space, slender members, nondegenerate faces, eight grounded feet, colour and bounds. Headings **0/π÷2/π/0.73**, positions **(0,0)/(17,−23)**, flat/**13.5 m** ground, final chunk geometry, replacement/unload/reload and shadow casting are covered. The differing check counts reflect the old 30-vertex box versus 360 vertices in the repaired rack.

[Existing controls](regression-controls.log): **582/0**, including scenery, ground/chunk build, the repaired camping props and bicycle lamp/single-beam checks. [Targeted pytest](pytest.log): **31 passed**, `tests/test_build_ways.py` and `tests/test_godot_manifest.py`. The road-building tests cover normal scenery classification/alignment; all changed scripts parse and `git diff --check` passes. Existing headless shutdown warnings are retained in the controls log.

## Inspected views

Native Windows Godot **4.7.2**, Forward+ Vulkan / **NVIDIA RTX 5060** captured 400×340 panels through production `props()`/chunk mesh helpers. Every capture records three completed draw frames and full frustum containment. Eight directions before/after are retained at close orthographic scale and **20 m** normal perspective. All four frames/openings are clear in three-quarter/elevated views; end views show the nearest inverted U and the side/top views show separated members. At 20 m the framing remains recognizable but fine members are small.

- [Close ends/sides](review/rack_1.png) · [close three-quarter/top/elevated](review/rack_2.png)
- [20 m ends/sides](review/rack_20m_1.png) · [20 m three-quarter/top/elevated](review/rack_20m_2.png)
- [Before metadata](before/capture-results.json) · [after metadata](after/capture-results.json)

## Named map verification

Normal `build_ways()` on the existing cached Oulu source selects actual **OSM node 12866515228**, `amenity=bicycle_parking`, `bicycle_parking=stands`, `capacity=10`, `covered=no`. Its raw coordinates are **65.0125782,25.4684741** (EPSG:3067 **427817.84161144693,7210730.892202272**); its normal path-aligned row is **427817.42041195,7210731.164825593**, angle **0.9963534952950144 rad**. Raw node, projection, normal output and full source query are retained in [map-source.json](map-source.json) and [query runner](source-query-runner.txt). The four-hoop rendering is the existing generic rack convention, not a reconstruction of the mapped capacity/style. No synthetic rack is inserted.

Named **`vqa_bicycle_parking_rack_day`** reuses the sourced Oulu road pose **427897.3,7210634.9,2.555** and existing eye camera, positioned beside the rack at 1.35 m. The flat-terrain flag isolates geometry; real map/time/weather/chunk checks remain. Readiness extends the existing mapped-prop matcher: actual row/heading, **360 rendered vertices**, active 3D camera/display, complete rack frustum/HUD clearance, eight grounded feet, directly visible front opening and top bar, drawn-geometry BVH rays and nearer dynamic-body clearance. The opening must project to at least 12×12 px and the top bar to at least one pixel thick. It samples the nearest hoop from the camera side. Missing/wrong-angle/hidden/too-small rows are rejected.

Accepted [screenshot](gameplay/first/vqa_bicycle_parking_rack_day/2026-06-20T1300_20261117-210939_f566821c-dirty/screenshot.png) and [result](gameplay/first/vqa_bicycle_parking_rack_day/2026-06-20T1300_20261117-210939_f566821c-dirty/result.json): **193×153 px** rack, **53×108 px** opening and **91×12 px** top bar; active 3D, **360 matched vertices**, ground **0 m**, no errors. The screenshot visibly shows the mapped rack's four open frames and grounded feet, separate from the nearby tree. [Crop](review/gameplay-detail.png) enlarges the original target pixels for review. Renderer: `forward_plus on NVIDIA GeForce RTX 5060`, 1280×720, source revision `f566821c-dirty`. The first named capture passed and was inspected; no gameplay attempt was excluded. Disposable userdata was removed by the wrapper.

## Reproduction

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_rack_tests.gd
.venv/bin/python -m pytest -q -n auto tests/test_build_ways.py tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_bicycle_parking_rack_day --out docs/visual-quality-corrections/bicycle-parking-rack/gameplay
```

Focused/controls/capture/source-query runners are retained as text. Copy the Godot runners temporarily under `godot/tools/`, then delete them and generated UIDs. Capture arguments are fixture JSON and output directory, converted with `wslpath -w` for native Godot. For before reproduction, use `git show f566821c:godot/buildings_3d.gd` as `godot/tools/_tmp_rack_original.gd` and change the capture runner's B3 preload to it. To run the before geometry test, copy `godot/tests/run_tests.gd` to `godot/tools/_tmp_rack_suite_before.gd`, change its B3 preload to the original source, and use [before-runner.txt](before-runner.txt).

The Finnish NPC traffic-law guide's footprint/access guidance was reviewed. This is client geometry; server parking/access/allocation decisions, live bicycles and 2D rendering remain outside the correction and are not certified by these checks. Player userdata/shared edits are preserved. Visual gameplay coverage samples one daylight flat-terrain view; other findings and unseen map/terrain/lighting combinations remain outside this slice.
