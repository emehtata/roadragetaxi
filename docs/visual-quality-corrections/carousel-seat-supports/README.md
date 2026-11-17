# Carousel seat platform (VQA-022)

The standard carousel previously emitted a grounded central mast, a canopy inset to 72% of its path radius, and eight disconnected seat boxes on a normal 49-point path. The production path is `osm/theme_parks.py::prepare_theme_parks()` → `make_ride()` → chunk `attractions` rows → `map_chunk.gd::prepare()` → `buildings_3d.gd::_structures()` → `attractions()`. The boxes are 1.2 m wide (`_box3d` takes a half-width of 0.6 m), at 0.9–1.6 m height. On the radius-8 fixture the seat's inner face is 7.4 m from the centre, the mast face is 0.3 m out, and the canopy reaches only 5.76 m at a 4.5 m bottom height. There was no support surface between them.

The two-line production addition uses `_raised_polygon_at()` to make a **15 cm platform at 0.75–0.9 m**, following the existing footprint. Its top meets the actual seat wall bases exactly and crosses the mast walls. Removing the path's repeated closing point before triangulation avoids a degenerate top triangle. The platform stays open below; it does not make a solid pedestal. Original seats, mast, canopy, colours, dimensions and ordering remain identical outside the added platform. Other attraction kinds and the server/2D pipeline are unchanged. The platform adds bounded mesh work during the existing chunk build, with no new per-frame gameplay queries.

## Geometry verification

The focused regression was added before the production fix. [Original output](regression-before.log) fails the missing-platform/contact assertions. The corrected [Linux](regression-after.log) and [native Windows](regression-native.log) runs pass **221 checks / 0 failures** each. Check counts differ before/after because the missing original top has no platform triangles to examine.

The test extracts real platform top triangles and seat base-wall vertices/edges. It checks top winding, full footprint area, one connected top surface, contact with each actual seat base and mast side, 15 cm thickness and retained visible seats. It covers 4/17/48-segment irregular closed footprints, rotation, translation and flat/13.5 m constant ground through the final builder. Exact non-platform vertices/colours are compared against the original construction; independent millimetre fingerprints retain swing-carousel, Ferris-wheel, coaster and drop-tower controls. Actual chunk replacement/unload/reload is stable. [Existing controls](regression-controls.log) pass **216/0** for scenery/attraction construction, terrain placement and chunk replacement, retaining existing dummy-renderer/resource-shutdown warnings.

[Targeted pytest](pytest.log): `tests/test_theme_parks.py` and `tests/test_godot_manifest.py`, **7 passed**. Changed scripts parse and scoped `git diff --check` passes. Temporary runners are retained as [focused-runner.txt](focused-runner.txt), [controls-runner.txt](controls-runner.txt) and [capture-runner.txt](capture-runner.txt), and removed from the project after the runs.

## Inspected images

All **32 before/after panels** were inspected: eight close directions and eight default perspective samples at **55 m**, before and after. Native Windows Godot 4.7.2 Forward+ Vulkan / NVIDIA GeForce RTX 5060 rendered 400×340 panels with production builder/materials. Each capture asserts three completed draw frames and full target framing. Both side views show seat bases seated on the thin platform; three-quarter/top/elevated views show all eight seats sharing that platform with the central mast. The original open space beneath the canopy remains. The 55 m views retain the connected silhouette at normal perspective size.

- [Close ends/sides](review/carousel_1.png) · [close three-quarter/top/elevated](review/carousel_2.png)
- [55 m ends/sides](review/carousel_perspective_1.png) · [55 m three-quarter/top/elevated](review/carousel_perspective_2.png)
- [Before captures](before/capture-results.json) · [after captures](after/capture-results.json) · [fixture](fixture.json)

## Named gameplay scenario

`vqa_carousel_seat_supports_day` uses mapped **Vauhtipuisto, OSM relation 1300537, Oulu**. The existing `prepare_theme_parks()` pipeline finds unobstructed space in this mapped park and generates a representative carousel. It is **not a reconstruction of a particular real ride**. [Source query](source-query.log), [source runner](source-query-runner.txt) and [complete generated path](map-source.json) record the normal pipeline and existing cached OSM data. The first seat is at **425511.675270, 7212598.538573** (EPSG:3067). The taxi is on the sourced Leiritie segment midpoint **425430.537875, 7212617.607420**; the existing `camera_at` facility holds the top camera over the generated ride. No new data source was added.

Readiness reuses the mapped-attraction checks: all **49 source samples**, **1,704 actual rendered vertices** within 1 mm, active 3D, ground clearance, useful seat/support region, frustum and HUD/building/dynamic-body clearance, plus normal server map/time/weather/chunk readiness. A triangle-BVH query also rejects seat/support probes hidden behind the ride's own canopy or other ground props. The platform probe lies **1 m inward** from the seat centre, past the seat's 0.6 m half-width, rather than directly on the seat wall. It tests exposed platform; the seat-top probe tests the visible seat.

The clean [accepted result](gameplay/accepted/vqa_carousel_seat_supports_day/2026-06-20T1300_20261117-122902_ff579489-dirty/result.json) passes with empty errors, active 3D, ground 0 m and a **47×33 px** seat/support region. The [1280×720 screenshot](gameplay/accepted/vqa_carousel_seat_supports_day/2026-06-20T1300_20261117-122902_ff579489-dirty/screenshot.png) was inspected: the eight seats and shared platform are visible, and the checked right-hand seat/platform area is clear. Other park visitors are outside that target region. DEM is disabled for this flat geometry sample; disposable userdata is removed after capture.

Only that clean final capture receives acceptance credit. The preliminary pass lacks the final self-occlusion guard and is superseded. `gameplay/final/` correctly rejected probes on the seat-wall boundary; `gameplay/visibility/` is a superseded diagnostic pass. Neither is used as final verification. Existing native shader-cache warnings remain in the logs.

## Reproduction

```sh
# Restore focused-runner.txt as godot/tools/_tmp_carousel_tests.gd for this run, then remove it.
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_carousel_tests.gd
.venv/bin/python -m pytest -q -n auto tests/test_theme_parks.py tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_carousel_seat_supports_day --out docs/visual-quality-corrections/carousel-seat-supports/gameplay
```

The source revision is **ff579489-dirty**. To reproduce the original capture, use its `buildings_3d.gd` in a temporary worktree with the retained capture runner/fixture; the before regression removes only the two platform lines under a `try/finally` restoration. For native capture pass the fixture and output directory as Windows paths via `wslpath -w`. The fixture records both close and 55 m samples.

Gameplay verification samples one daylight, flat-terrain map view. Constant-height terrain is covered by regression; arbitrary slopes, parks and camera/lighting combinations remain unverified. VQA-023 (swing-carousel supports) is a separate finding.
