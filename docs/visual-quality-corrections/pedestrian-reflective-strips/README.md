# Reflective chest bands (VQA-016)

The style-4 chest bands now follow the existing polygonal jacket instead of floating ahead of it. The call path is `entity_layer._people_3d()` → `person()` → cached `person_arrays()` → `_garment_torso()`. The normal ID hash chooses clothing variant 4. The torso has five tapered rings and either 6 or 12 angular sides. The original two cylinders ran straight across z ±0.19 m at x = 0.19 m; their ends were up to **0.094 m** ahead of the jacket in the scale-1 samples. They also did not follow the 0.012 m breathing offset.

The correction clips each band directly from the just-built torso triangles at its existing height and width, then moves it **0.001 × body scale m** outward to avoid coincident surfaces. Both bands keep the existing pale colour and 0.03 m vertical thickness. The same triangles form the body and shadow. This runs only during cached mesh construction; there are no gameplay surface queries or new per-frame work. All other geometry, colour, material-part and roof attributes are unchanged by 66 recorded mesh/shadow fingerprints, including other clothing variants and winter substitution.

## Checks

[Original regression](regression-before.log): **393 checks, 102 failures**. [Corrected regression](regression-after.log): **393 checks, 0 failures**. The targeted runner covers both detail levels, body scales 0.6/1/1.2, standing and both breathing states, all six walking/running phases, sitting/riding, band endpoints and face centres, unchanged non-band mesh/shadow attributes, four pooled headings/elevation updates, and existing head/proportion/seating/walking/arm/beard controls. The attachment test identifies the original torso triangles by their existing fabric colour and independently interpolates their front x at each band's y/z; it rejects missing or buried bands and measures their width/separation. [Manifest pytest](pytest.log): **3 passed**. Changed-script parses and `git diff --check` pass.

## Inspected close views

All **96 before/after panels** were inspected: three poses (`standing_0`, `standing_1`, `walk_1`) at both detail levels, eight directions each. Each 400×340 panel uses the production person builder and organic spatial material, with three completed draw frames and a framed chest inspection box. Windows Godot 4.7.2 Forward+ Vulkan / NVIDIA GeForce RTX 5060 rendered the captures. Both bands remain visible and seated on the jacket facets. The zipper remains its existing geometry; it is outside VQA-016.

- Detail 0, standing: [ends/sides](review/detail0_standing_0_1.png), [three-quarter/top/elevated](review/detail0_standing_0_2.png)
- Detail 0, breathing: [ends/sides](review/detail0_standing_1_1.png), [three-quarter/top/elevated](review/detail0_standing_1_2.png)
- Detail 0, walking: [ends/sides](review/detail0_walk_1_1.png), [three-quarter/top/elevated](review/detail0_walk_1_2.png)
- Detail 1, standing: [ends/sides](review/detail1_standing_0_1.png), [three-quarter/top/elevated](review/detail1_standing_0_2.png)
- Detail 1, breathing: [ends/sides](review/detail1_standing_1_1.png), [three-quarter/top/elevated](review/detail1_standing_1_2.png)
- Detail 1, walking: [ends/sides](review/detail1_walk_1_1.png), [three-quarter/top/elevated](review/detail1_walk_1_2.png)
- [Before capture readiness](before/capture-results.json), [after readiness](after/capture-results.json), [fixture](fixture.json), [manifest](manifest.json)

## Named gameplay

The [accepted screenshot](gameplay/vqa_reflective_strips_day/2026-06-20T1500_20261115-202717_f36c14c9-dirty/screenshot.png) and [result](gameplay/vqa_reflective_strips_day/2026-06-20T1500_20261115-202717_f36c14c9-dirty/result.json) pass and were inspected: **1280×720**, active 3D view, variant 4, held `standing_1`, body **116×288 px**, chest **72×46 px**, ground **0 m**, model origin **0.048 m**, and empty errors. Both bands are visible and seated on the yellow jacket. The scenario reuses the sourced Oulu dense-road pose from the earlier windscreen/two-wheeler corrections. The normal hash path picks variant 4 for the held `standing_1` pedestrian; the existing eye camera exposes its chest. The fixture disables DEM terrain to avoid a ground-elevation mismatch, and uses disposable userdata. Readiness requires the exact cached variant/pose/detail/winter mesh, active displayed 3D viewport, correct facing, ground clearance, person/chest projected size and frustum, HUD/building clearance and no nearer dynamic body over the chest. Normal server pose/time/weather/map readiness also applies. The initial 6 m placement was stopped after persistent HUD overlap and is excluded.

## Reproduction

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --check-only --script res://buildings_3d.gd
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --check-only --script res://visual_test.gd
.venv/bin/python -m pytest -q -n auto tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_reflective_strips_day --out docs/visual-quality-corrections/pedestrian-reflective-strips/gameplay
```

The [focused runner](focused-runner.txt) extends the permanent tests; copy it temporarily to `godot/tools/_tmp_reflector_tests.gd`, run headlessly with `--script res://tools/_tmp_reflector_tests.gd`, then delete it and its generated UID. The [capture runner](capture-runner.txt) extends the existing audit renderer; run it natively with `fixture.json` and the output directory as user arguments. The original builder is at `f36c14c9:godot/buildings_3d.gd`; the original-regression runner used a temporary copy of that source without reverting the shared tree. The before/after source hashes are recorded in the manifest.

This is client geometry only; no simulation or pedestrian interaction behavior changed. The Finnish traffic-law guide was read. Other findings and unrecorded map/lighting combinations remain outside this slice.
