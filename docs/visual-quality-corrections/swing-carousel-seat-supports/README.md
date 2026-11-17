# Swing-carousel hanging supports (VQA-023)

The production path is `osm/theme_parks.py::prepare_theme_parks()` → `make_ride()` → chunk `attractions` → `map_chunk.gd::prepare()` → `buildings_3d.gd::_structures()` → `attractions()`. The original standard 49-point footprint produced eight seat boxes at 3.0–3.6 m, a grounded mast and a canopy at 7.0–7.4 m inset to 45% of the path radius. There were no triangles joining the seats to the ride. On the radius-8 inspection fixture the seat centre is 8 m out, the canopy edge is 3.6 m out, and the vertical separation from seat top to canopy underside is 3.4 m. A vertical rod above the seat would miss the canopy.

The two-line production addition uses the existing `_sloped_wall()` helper to add one slender **6 cm hanging rod per seat**. Each rod slopes inward from the seat centre to 40% of the footprint radius, inside the actual canopy. Its seat end spans 3.57–3.63 m, intersecting the seat top at 3.6 m; its upper end spans 6.99–7.05 m, intersecting the canopy's bottom side walls at 7.0 m. The existing footprint vertices at every sixth sample coincide with canopy wedge boundaries, so the upper anchor intersects real canopy triangles. Both contacts overlap rather than leaving a background gap. The ride stays open beneath the canopy, without a platform or ground pedestal. Original seats, mast, canopy, colours and ordering remain unchanged outside the added rods. The added work is bounded by the existing seat loop during chunk construction; no per-frame gameplay work or new data source was added.

## Geometry checks

The tests were added before the production correction. [Original regression](regression-before.log): **53 checks / 30 failures**. [Corrected Linux](regression-after.log) and [native Windows](regression-native.log): **125 checks / 0 failures** each. Counts increase when actual support triangles are available to inspect. Tests extract rods by their distinct existing-style steel colour, identify continuous seat-to-canopy triangles, compare upper contacts against actual canopy triangle footprints, retain exposed seats, and reject missing rods, platforms and detached upper anchors. The matrix covers 4/17/48-segment irregular closed loops, translation/rotation, flat and 13.5 m constant ground, actual chunk replacement/unload/reload, and exact preservation of all original vertices/colours. Independent millimetre fingerprints preserve the repaired standard carousel, coaster, Ferris wheel and drop tower. The earlier standard-carousel test's swing fingerprint was intentionally updated for the added rods.

[Existing controls](regression-controls.log) pass **216/0** for scenery/attractions, ground adaptation and chunk replacement. [Targeted pytest](pytest.log): `tests/test_theme_parks.py` and `tests/test_godot_manifest.py`, **7 passed**. All changed GDScripts parse and scoped `git diff --check` passes. Existing dummy-renderer/resource-shutdown and native shader-cache warnings remain in the logs. Reproduction runners are retained as [focused-runner.txt](focused-runner.txt), [controls-runner.txt](controls-runner.txt) and [capture-runner.txt](capture-runner.txt); temporary copies were removed from the project.

## Inspected views

All **32 comparison panels** were inspected: eight close directions and eight default perspective views at **55 m**, before and after. Native Windows Godot 4.7.2 Forward+ Vulkan / NVIDIA GeForce RTX 5060 rendered 400×340 panels using the production builder/materials. Every panel asserts full target framing and three completed draw frames. Front/rear/both sides show thin hangers reaching seats and canopy. Three-quarter/top/elevated views verify all eight seat attachments. At 55 m, hangers remain visible as fine support lines and the open silhouette remains recognizable.

- [Close front/rear/sides](review/swing_carousel_1.png) · [close three-quarter/top/elevated](review/swing_carousel_2.png)
- [55 m front/rear/sides](review/swing_carousel_perspective_1.png) · [55 m three-quarter/top/elevated](review/swing_carousel_perspective_2.png)
- [Before captures](before/capture-results.json) · [after captures](after/capture-results.json) · [fixture](fixture.json)

## Named gameplay

`vqa_swing_carousel_supports_day` uses **Vauhtipuisto, Oulu, mapped OSM relation 1300537**. The normal `prepare_theme_parks()` pipeline generates this representative swing carousel in clear space inside the park; it is **not a reconstruction of a particular real ride**. The existing cached OSM data and normal `build_ways()` query are retained in [source-query-runner.txt](source-query-runner.txt) and [map-source.json](map-source.json). The complete 49-point path begins at **425590.942668, 7212572.911893** EPSG:3067. The taxi remains at the sourced Leiritie midpoint **425430.537875, 7212617.607420**. The existing `camera_at` and `eye` facilities hold the map over the ride and look from 5 m high, 20 m east and 8 m south of the generated ride centre. This exposes the underside/upper hanger contact as well as the seat attachment. DEM is disabled for this flat geometry sample.

Readiness requires all **49 actual source samples**, **1,422 matching rendered vertices** within 1 mm, active 3D/visible mesh, ground clearance, frustum, useful contact bounds and HUD/building/dynamic-body clearance. Cached triangle-BVH queries against the same visible ground-prop mesh reject the seat/hanger/canopy probes when hidden by the ride's own canopy or another prop. Rays end 8 cm before the contact centre to avoid self-intersecting the 6 cm rod/seat contact; the attachment geometry itself is checked independently by the focused tests. Missing/wrong/malformed paths are rejected. Normal server pose/date/time/weather/chunk checks remain active.

The final [accepted result](gameplay/accepted/vqa_swing_carousel_supports_day/2026-06-20T1300_20261117-135049_938d6e26-dirty/result.json) has empty errors, active 3D, ground 0 m and a **188×264 px** contact region. Its [1280×720 screenshot](gameplay/accepted/vqa_swing_carousel_supports_day/2026-06-20T1300_20261117-135049_938d6e26-dirty/screenshot.png) was inspected: the near red seat, sloping hanger and upper canopy contact are clear and separate from the mast. The rest of the ride has recognizable thin hangers; some peripheral seat edges lie under HUD, outside the checked contact region. Disposable userdata was removed by the runner.

Only that final off-axis capture receives acceptance credit. The first run was interrupted with exit 143 after correctly rejecting a zero-width centreline contact rectangle; it has no accepted screenshot. `gameplay/retry/` passed with a head-on view, but the checked hanger visually overlapped the mast, so it is superseded by the off-axis capture. The initial capture command used unavailable `python`, then was corrected to the project `.venv/bin/python`; the failed native launch was stopped and no output from it is accepted.

## Reproduction

```sh
# Restore focused-runner.txt as godot/tools/_tmp_swing_tests.gd only for the run, then remove it.
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_swing_tests.gd
.venv/bin/python -m pytest -q -n auto tests/test_theme_parks.py tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_swing_carousel_supports_day --out docs/visual-quality-corrections/swing-carousel-seat-supports/gameplay
```

Source revision: **938d6e26-dirty**. To reproduce original views, use its `buildings_3d.gd` in a temporary worktree with the retained capture runner/fixture. Native capture takes the fixture/output directories as Windows paths (`wslpath -w` under WSL). No shared files, saved settings or unrelated edits are reverted.

Skipped other findings and unrecorded terrain/map/lighting combinations. Named gameplay coverage samples one daylight, flat-terrain view; detailed contact geometry is covered across the recorded matrix, not every possible park footprint.
