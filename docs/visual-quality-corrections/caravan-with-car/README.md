# Caravan and towing car (VQA-025)

The `caravan_with_car` prop now has a separate pale caravan and shorter, lower car, six visible wheel placements, dark glazing, a caravan side window and roof hatch, and an exposed drawbar. The car reuses `car_arrays()` at its existing low detail level; `_wheel()` and `_car_box()` build the caravan. The pair is built with the static chunk mesh and shares its existing material and shadow path. No new asset, dependency or data source is added.

The production trace is `osm/campsites.py::populate_camp_pitches()` → `scenery_objects` → `map_chunk.prepare()` / `_structures()` ground `props` → `Buildings3D.props()` → final ground mesh. Previously, `props()` sent this kind through `_raised_polygon_at()` as a single **10.5 × 2.3 × 2.5 m** box; it lost both silhouettes and exceeded the server's authoritative `CAMPING_SIZES` **9.4 × 2.5 m** envelope. `_draw_caravan()` in the 2D renderer already distinguishes the pale caravan from its blue/red towing car. The new 3D branch reuses that palette and deterministic `posmod(hash(at),2)` car-colour choice.

The static `PROPS` envelope is now **9.4 × 2.5 × 2.5 m**. Actual geometry is x **−4.600 to +4.685 m**, across **−1.244 to +1.244 m**, y **0 to 2.500 m**, entirely inside the server footprint. Caravan body: x −4.6 to 0.2 m, y 0.35 to 2.4 m; car: existing 3.5 m body centred at x 2.9 m, 1.5 m high. The 0.1 m wide drawbar spans x 0.19 to 1.4 m at y 0.4–0.5 m, overlapping both bodies; the space above it remains open. Existing car/caravan tyre geometry has its six contact points at y=0. The caravan wheel faces were moved 1 cm inward so their existing 4 mm face lift also fits the 2.5 m envelope. Source row centre, angle and server allocation remain authoritative.

## Verification

The [initial regression](regression-before.log) failed **96 of 119 checks** on the original box. Final [Linux](regression-after.log) and [native](regression-native.log) focused tests pass **136 checks, 0 failures**. They inspect the actual triangles for body separation, six tyre contacts, cabin/glazing/roof detail, thin hitch contacting the actual car/caravan faces, and oriented footprint at headings 0, π/2, π, 0.73 and translated positions. Final build checks cover 0/13.5 m constant ground, stable regeneration and actual chunk replacement/unload/reload. Fingerprints independently recorded from `7afdf542` preserve standalone caravan, camper, tent, bench and live car/trailer output. Readiness spatial matching has positive sub-mm roundtrip and negative wrong/empty-target tests.

[Existing scenery/ground/chunk controls](regression-controls.log): **216 checks, 0 failures**. [Targeted pytest](pytest.log): **12 passed** (`tests/test_campsites.py`, `tests/test_godot_manifest.py`). All changed scripts parse and `git diff --check` passes. Existing dummy-renderer/resource shutdown warnings and native shader-cache write warnings are retained in logs.

All **32 before/after panels** were inspected: eight production-builder angles at close orthographic framing plus eight perspective views at 55 m, for both versions. Native Windows Godot 4.7.2 Forward+ Vulkan / NVIDIA GeForce RTX 5060, 400×340 panels; metadata verifies three completed draw frames and full bounds framing. The pair is recognizable from the sides and elevated views; the front resolves the car windshield and bonnet, rear resolves caravan/tyres, and top resolves separated roofs and drawbar. At 55 m it remains a car beside a taller caravan; fine wheel/window detail is small.

- [Close ends and sides](review/caravan_with_car_1.png) · [close three-quarter/top/elevated](review/caravan_with_car_2.png)
- [55 m ends/sides](review/caravan_with_car_55m_1.png) · [55 m three-quarter/top/elevated](review/caravan_with_car_55m_2.png)
- [Before results](before/capture-results.json) · [after results](after/capture-results.json) · [manifest](manifest.json)

## Named gameplay acceptance

`vqa_caravan_with_car_day` uses actual mapped Nallikari **pitch 148, OSM node 2450243248** at **425641.6101064687, 7212631.056993239**, with normal `populate_camp_pitches()` output `caravan_with_car`, angle **4.4189276055 rad**. The source query calls the normal `build_ways()` pipeline over the existing cached OSM data; it found 22 combinations and retains the selected pitch, row and complete oriented server footprint in [map-source.json](map-source.json). Point pitches use the existing documented five-metre envelope. The taxi stays on the previously sourced service-road pose 425646.3, 7212617.6, heading 2.848; existing top camera is held over this pitch. No synthetic combination or pitch is inserted. `--no-terrain-dem80` isolates this static geometry on flat ground.

The accepted capture is **[passing named screenshot](gameplay/roof-probe/vqa_caravan_with_car_day/2026-06-20T1300_20261117-170507_7afdf542-dirty/screenshot.png)**. It passed all normal map/time/weather checks plus active 3D, expected kind/heading, actual mesh vertex membership, six wheel ground checks, pitch containment, frustum/HUD clearance, actual drawn building/prop BVH clearance and nearer dynamic-body clearance for separate caravan/car/hitch regions. The probe uses the actual car roof plane at 1.5 m; a below-roof probe is explicitly rejected in the previous run. Spatial buckets keep the initial mesh membership check bounded by actual vertex counts, cached per mesh; this is audit-only code.

[Accepted readiness](gameplay/roof-probe/vqa_caravan_with_car_day/2026-06-20T1300_20261117-170507_7afdf542-dirty/result.json): **1,818 matched vertices**, active 3D, ground **0 m**, no errors. Combination **150×309 px**; caravan **120×175 px**, car roof **39×34 px**, hitch **9.5×22.3 px**. Its server footprint is **4.906 m** from the original pitch centre at the farthest corner after stream rounding, below the 5 m envelope. The screenshot was inspected: car and caravan roofs, body separation, connecting drawbar and clear pitch are visible. Native renderer: Forward+ / NVIDIA RTX 5060; 1280×720. Fixture lamp bits are 0. The run uses disposable userdata; the wrapper removes it.

Excluded attempts: the first gameplay launch stalled in quadratic audit vertex matching and was explicitly stopped, without a screenshot; the spatial-match retry correctly failed because its car probe was 5 cm below the roof. Neither receives visual credit. An initial isolated capture launch missed fixture names; its process was stopped, and the successful complete before output supersedes it. Every accepted panel has successful capture metadata.

## Reproduction

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_caravan_tests.gd
.venv/bin/python -m pytest -q -n auto tests/test_campsites.py tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_caravan_with_car_day --out docs/visual-quality-corrections/caravan-with-car/gameplay
```

The focused, control, source-query and capture runners are retained as text alongside this README. Copy runners temporarily under `godot/tools/`, then remove them and generated UIDs. Capture arguments are fixture JSON and output directory, converted with `wslpath -w` for native Godot. To reproduce the original box, obtain `git show 7afdf542:godot/buildings_3d.gd` as `godot/tools/_tmp_camp_original.gd` and change only the capture runner's B3 preload to that path. Player settings and unrelated shared edits are preserved.

The Finnish NPC traffic-law guide was reviewed, including full-footprint and access guidance. This change keeps rendered vertices within the already allocated server camping envelope; it does not alter or certify parking/access decisions. Other audit findings, slope conformance and every unrecorded map/lighting combination remain outside this slice. Gameplay visual coverage samples one daylight flat-terrain view.
