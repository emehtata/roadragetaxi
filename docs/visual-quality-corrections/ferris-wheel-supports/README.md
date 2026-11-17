# Ferris-wheel rim supports (VQA-024)

The production path is `osm/theme_parks.py::prepare_theme_parks()` → `make_ride()` → chunk `attractions` → `map_chunk.gd::prepare()` → `buildings_3d.gd::_structures()` → `attractions()`. The original wheel had a 16-segment vertical rim with 16 coloured cabins and four A-frame members. Its hub height was `radius + 2 m`; the two frame apexes lay 0.5 m to either side of the wheel plane. There were no spoke or axle triangles joining that rim to the supports. On the radius-8 inspection fixture, the rim radius is 8 m and hub height is 10 m.

The three-line production addition builds a **30 cm thick, 1.2 m long shared axle** across both A-frame apexes and **16 evenly distributed 12 cm spokes** from the hub to the rim-segment midpoints. The midpoint anchors avoid the purely vertical endpoints that `_sloped_wall()` rejects. Spoke upper/lower bounds at the outer anchor are 4–16 cm above the rim segment base, within its existing 20 cm section; both solids share a cross-section. Inner ends span hub height ±6 cm inside the axle; the axle spans hub height ±15 cm and extends 10 cm beyond each existing frame apex. The wheel stays open. Original rim, cabins, A-frame, colours and overall bounds are retained; no source assets or server behavior changed. Construction work is bounded by the existing 16-segment loop.

## Geometry checks

Tests were added before the production fix. [Original regression](regression-before.log): **478 checks / 420 failures**. [Corrected Linux](regression-after.log) and [native Windows](regression-native.log): **1,702 / 0** each. The actual triangle checks verify all 16 continuous spoke surfaces, rim cross-sections at every anchor, shared axle cross-sections through both frame apexes, nondegenerate faces and slender geometry. Rays sample 1 mm inside the spoke end to avoid floating-point rejection exactly on a triangle boundary. Spokes at the upper/lower rim are included, so omitted vertical directions cannot pass. The matrix covers 4/17/48-segment irregular paths, translations/rotations, the minimum 3 m radius, flat/13.5 m constant ground, and actual chunk replacement/unload/reload. Independently recorded original millimetre fingerprints retain every existing vertex/colour outside the added supports; intentional Ferris-wheel fingerprints in earlier carousel controls are updated.

[All repaired attraction controls](regression-ride-controls.log) pass **6,386/0**, including the focused wheel matrix, prior coaster/carousel/swing-carousels and their preservation/lifecycle checks. [Existing controls](regression-controls.log) pass **216/0** for scenery/attractions, ground adaptation and chunk replacement. [Targeted pytest](pytest.log): **7 passed** (`tests/test_theme_parks.py`, `tests/test_godot_manifest.py`). Changed scripts parse and `git diff --check` passes. Existing dummy-renderer/resource-shutdown and native shader-cache warnings are retained in logs. The focused, ride-control, existing-control and capture runners are retained as text for reproduction; temporary project copies were removed.

## Inspected views

All **32 comparison panels** were inspected: eight close directions and eight default perspective views at **55 m**, before and after. Native Windows Godot 4.7.2 Forward+ Vulkan / NVIDIA GeForce RTX 5060 rendered 400×340 panels using the production builder/materials. Every panel asserts full framing and three completed draw frames. Broad-side and three-quarter views expose the spokes from rim to hub and the axle at the frame apexes. Edge-on/top views retain the narrow wheel silhouette. At 55 m the supports remain fine lines; some steep spokes alias into dashed-looking pixels at this scale.

- [Close front/rear/sides](review/ferris_wheel_1.png) · [close three-quarter/top/elevated](review/ferris_wheel_2.png)
- [55 m front/rear/sides](review/ferris_wheel_perspective_1.png) · [55 m three-quarter/top/elevated](review/ferris_wheel_perspective_2.png)
- [Before captures](before/capture-results.json) · [after captures](after/capture-results.json) · [fixture](fixture.json) · [manifest](manifest.json)

## Named gameplay

`vqa_ferris_wheel_supports_day` uses **Vauhtipuisto, Oulu, mapped OSM relation 1300537**. The normal `prepare_theme_parks()` pipeline generates representative Ferris-wheel geometry inside the mapped park; it is not a reconstruction of a particular real ride. The existing cached OSM dataset and normal `build_ways()` query are recorded in [source-query-runner.txt](source-query-runner.txt) and [map-source.json](map-source.json). The complete 49-point path starts at **425590.515446, 7212598.538573** EPSG:3067; its centre is **425584.017255, 7212598.538573**. The taxi stays at the sourced Leiritie midpoint **425430.537875, 7212617.607420**. Existing `camera_at`/`eye` facilities show the wheel obliquely from **425600.067407, 7212622.505053**, 10 m above ground. DEM is disabled for this flat geometry sample.

Readiness requires the complete 49-sample actual path, **1,146 matching rendered vertices** within 1 mm, active 3D/visible mesh and grounded frame feet. It checks useful projected spoke/rim/axle contact bounds, face-on visibility, frustum/HUD/building/dynamic-body clearance and cached triangle-BVH sightlines against the ride's own geometry. Rays stop 8 cm before the sampled exposed contact to avoid its surface. Independent geometry tests cover all 16 spokes and both frame apexes. Missing/wrong/malformed paths reject cleanly; normal server pose/time/weather/chunk checks remain active. Only the checked contact region must clear HUD; peripheral lower cabins extend beyond the view.

The [accepted result](gameplay/first/vqa_ferris_wheel_supports_day/2026-06-20T1300_20261117-163325_895be3e1-dirty/result.json) reports empty errors, active 3D, ground 0 m, and a **281×56 px** support region. Its [1280×720 screenshot](gameplay/first/vqa_ferris_wheel_supports_day/2026-06-20T1300_20261117-163325_895be3e1-dirty/screenshot.png) was inspected.

This first complete named run passed and its screenshot was inspected: the rim, spokes and central axle visibly join the A-frame; the upper wheel is clear against the sky. Disposable userdata was removed by the runner. No rejected gameplay attempts exist in this slice.

## Reproduction

```sh
# Restore focused-runner.txt as godot/tools/_tmp_ferris_tests.gd for the run, then remove it.
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_ferris_tests.gd
.venv/bin/python -m pytest -q -n auto tests/test_theme_parks.py tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_ferris_wheel_supports_day --out docs/visual-quality-corrections/ferris-wheel-supports/gameplay
```

Source revision: **895be3e1-dirty**. To reproduce before views, obtain that revision's `godot/buildings_3d.gd` as `godot/tools/_tmp_ferris_before.gd`, restore the capture runner under `godot/tools/` and change its `B3` preload to the temporary original. Native capture takes fixture/output directories as Windows paths (`wslpath -w` under WSL). Restore the normal preload for after views. Remove temporary scripts/UIDs after running.

Skipped other findings and unrecorded terrain/map/lighting combinations. Gameplay evidence samples one daylight, flat-terrain view; detailed attachment checks cover the recorded footprint matrix.
