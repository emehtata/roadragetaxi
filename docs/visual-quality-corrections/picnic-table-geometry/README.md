# Picnic-table geometry (VQA-028)

The solid block is replaced by a raised tabletop, two bench seats and grounded supports. All **32 before/after panels** and the final named map screenshot were inspected.

OSM `leisure=picnic_table` enters `_scenery_object_kind()` and normal path alignment in `osm/build.py`. The streamed `scenery_objects` row enters `map_chunk.prepare()` / `_structures()` as ground props; `Buildings3D.props()` emits its final chunk deck. Previously the generic fallback extruded one **1.8×1.5×0.75 m** cuboid, filling every leg/seat opening. The existing 2D branch draws a **1.6×0.9 m** wood rectangle; the separate biergarten builder emits a central table and two bench blocks. Both are preserved.

The picnic-only branch reuses `_raised_polygon_at()` for **eleven rectangular members**: a **1.8×0.7 m** tabletop at **0.69–0.75 m**, two **1.8×0.25 m** seats at **0.38–0.44 m**, four tabletop legs and four seat legs. All supports are **0.08×0.08 m**. Their upper faces touch the slabs and all eight feet meet the support plane. Tabletop legs at transverse ±0.275 m leave **0.47 m** between their inside faces and **0.69 m** below the tabletop; the middle remains open along the row. Bench seats are centered at ±0.625 m, leaving visible gaps beside the tabletop. The original **1.8×1.5 m** oriented envelope, **0.75 m** height and wood palette are retained. Shared mesh winding/normals and shadow paths are reused; no assets, dependencies or per-frame work are added.

## Checks

Tests were added before the production change. The preserved cuboid fails **240 of 501 checks** in [the original regression](regression-before.log). Final [Linux](regression-after.log) and [native](regression-native.log) runs pass **1,301/0** each. Different counts reflect the original 30 versus repaired 330 vertices. The tests inspect actual triangle intersections, tabletop and separate bench heights, 6 cm slab thickness, grounded support/contact paths, the unfilled knee space, nondegenerate triangles, wood colour and oriented bounds. They cover headings **0/π÷2/π/0.73**, positions **(0,0)/(17,−23)**, flat/**13.5 m** terrain, final chunk placement, stable rebuild and replacement/unload/reload. The final table legs were moved 2.5 cm outward to make the transverse opening unambiguously wider than 45 cm; all final evidence reflects this geometry.

[Existing controls](regression-controls.log) pass **2,100/0**, including generic scenery/ground, repaired rack/tent/caravan geometry, chunk state and unchanged biergarten geometry. [Targeted pytest](pytest.log) passes **31 tests**, `tests/test_build_ways.py` and `tests/test_godot_manifest.py`. Changed scripts parse and `git diff --check` passes. The control runner explicitly disables asynchronous chunk construction as the ordinary suite does. Existing headless material/resource shutdown warnings and native shader-cache warnings are retained in logs.

## Inspected views

Native Windows Godot **4.7.2**, Forward+ Vulkan / **NVIDIA GeForce RTX 5060** captured 400×340 panels through production `props()`/chunk material helpers. Each panel records three drawn frames and full geometry frustum containment. Eight directions before/after are retained at close orthographic scale and **20 m** perspective. Close ends/sides show the open supports; three-quarter/elevated views show both distinct benches, contacts and grounded feet. At 20 m the overall table/bench silhouette remains recognizable while individual members are small.

- [Close ends/sides](review/picnic_1.png) · [close three-quarter/top/elevated](review/picnic_2.png)
- [20 m ends/sides](review/picnic_20m_1.png) · [20 m three-quarter/top/elevated](review/picnic_20m_2.png)
- [Before metadata](before/capture-results.json) · [after metadata](after/capture-results.json) · [fixture](fixture.json)

## Named map verification

Normal `build_ways()` from the existing cached Oulu dataset selects actual **OSM node 10053759118**, `leisure=picnic_table`. Raw coordinates are **65.0145209,25.4860926**, projected **428653.2773732978,7210927.349539287**. The normal path-aligned row is **428650.4975534305,7210925.380210311**, angle **0.019297309075672852 rad**. [Map-source data](map-source.json) and [source query](source-query-runner.txt) retain the raw node and normal output. This is a representative simple wooden table; the mapped design is not reconstructed. No synthetic table is inserted.

Named **`vqa_picnic_table_geometry_day`** reuses the sourced Oulu road pose **427897.3,7210634.9,2.555** and the existing eye camera beside the mapped table at **1.15 m**. Flat terrain isolates the geometry; normal map/date/time/weather/chunk readiness remains. Existing mapped-prop verification matches all **330 rendered vertices**, the actual row and heading; it requires the active 3D view, full model frustum/HUD clearance, all eight feet grounded, a useful directly visible end opening, outer bench/support contact and tabletop region, drawn-geometry BVH sightlines and nearer dynamic-body clearance. The opening must be at least 12×12 px; the seat/support region must be at least 2 px in both directions.

The final [screenshot](gameplay/final/vqa_picnic_table_geometry_day/2026-06-20T1300_20261117-213514_bf92fa4d-dirty/screenshot.png) and [readiness result](gameplay/final/vqa_picnic_table_geometry_day/2026-06-20T1300_20261117-213514_bf92fa4d-dirty/result.json) pass with **299×120 px** whole table, **46×42 px** opening and **16×26 px** seat/support region, active 3D, ground **0 m** and no errors. Inspection shows both seats, tabletop and grounded supports without the former filled block or clipping by the eye-view mask. A separate mapped lamp behind the table is visible above it. [Detail crop](review/gameplay-detail.png) enlarges the original target pixels. Renderer: `forward_plus on NVIDIA GeForce RTX 5060`, 1280×720, revision `bf92fa4d-dirty`. Disposable userdata was removed by the runner.

Excluded attempts: `gameplay/first` correctly failed because the initial probe sat beneath the bench lip; its replacement covers the visible outer support/seat join. `gameplay/retry` reported an empty-error pass but was visually rejected because the near feet fell below the existing eye-view mask edge. The eye camera was moved farther away; `gameplay/accepted` framed the whole table but was superseded by the final leg placement. **Only `gameplay/final` receives visual acceptance.** No visibility condition was relaxed for final capture.

## Reproduction

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_picnic_tests.gd
.venv/bin/python -m pytest -q -n auto tests/test_build_ways.py tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_picnic_table_geometry_day --out docs/visual-quality-corrections/picnic-table-geometry/gameplay
```

Focused/control/capture/source-query runners are retained as text. Copy Godot runners temporarily under `godot/tools/` for reproduction and delete them and generated UIDs afterwards. Native capture arguments are the fixture JSON and output directory, converted with `wslpath -w` under WSL. To reproduce original geometry, obtain `git show bf92fa4d:godot/buildings_3d.gd` as `godot/tools/_tmp_picnic_original.gd`, change the capture runner's B3 preload to that path, and for regression copy `run_tests.gd` as `_tmp_picnic_suite_before.gd` with the same B3 preload change, using [before-runner.txt](before-runner.txt).

Shared edits/player userdata are preserved. Seating/activity decisions and 2D/biergarten rendering are untouched. Visual coverage samples one daylight flat-terrain view; other findings and unseen terrain/map/lighting combinations remain outside this slice.
