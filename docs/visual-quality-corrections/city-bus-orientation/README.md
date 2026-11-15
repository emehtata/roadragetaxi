# City bus faces its vehicle heading (VQA-007)

The source bus nose faces **−X**: the `Destination sign: 12  CENTRAL` landmark is at (−5.9801464, 2.827, 0), beside the front windshield/fog lamps, while `Rear high-mount stop light red lens` is at (+5.936, 2.862, 0), above the rear window/grille. Source node names, coordinates and the inspected front/rear views establish orientation independently of bounds. The existing source-X path applied only the production heading, so the nose faced backward. `place_model_car()` now adds π only for `city_bus`.

The production call path is `entity_layer._vehicle_body()` → `vehicle("bus")` → `vehicle_model_kind("bus") == "city_bus"` → `place_model_car()`. Generic live overlays already put white front lamps and headlight beams along the server heading; rotating only the body brings them into agreement. The source GLB, dimensions, scale, materials, road/elevation offset and simulation are untouched. A proper rotation preserves handedness; the passenger doors rotate with their body. Trains keep their source-X transform, and source-Z cars keep their existing quarter turn.

## Regression

`test_city_bus_model_faces_heading()` was added before the fix: [initial failure](regression-before.log) records eight semantic landmark failures. Its final version also checks headings 0, π/2, π and 0.73 at a translated/elevated pose, off/on/all lamp bits, instance reuse on consecutive frames, proper handedness, white-front/red-rear overlay placement, the normal bus headlight source, and train/car transform controls. [After log](regression-after.log): **732 checks, zero failures**, including existing size, bus distance, vehicle-distance, merged-material and lamp-pair regressions. Existing headless dummy-renderer/ObjectDB shutdown warnings remain in the log. Manifest pytest passes 3 tests; changed scripts parse and `git diff --check` passes.

The temporary runners were removed after verification; their exact content is retained as [focused-runner.txt](focused-runner.txt) and [capture-runner.txt](capture-runner.txt). To reproduce, copy the focused runner under `godot/tools/` and run it with Linux Godot:

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_bus_orientation.gd
.venv/bin/python -m pytest -q -n auto tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_city_bus_day vqa_city_bus_night --out docs/visual-quality-corrections/city-bus-orientation/gameplay
```

## Inspected close views

The [fixture](fixture.json) uses the complete production `vehicle("bus")` path, including overlays with all bits (31), under the existing audit renderer. Native Windows Godot 4.7.2 Forward+ Vulkan / NVIDIA GeForce RTX 5060 captured 400×340 front, rear, both sides, both three-quarter, top and elevated panels before and after, in day and night light (32 panels total). Three completed draw frames, nonempty geometry and full-frustum framing are asserted per panel. Camera and bounds are recorded in each capture manifest.

All four native-size comparison sheets were visually inspected. The corrected declared front has the windshield/display and white lamps; the rear has its grille/red lenses. Both side views retain the geometry and passenger doors. Night all-bits fixtures intentionally include lit reverse lamps.

- [Day front/rear/sides](review/day_1.png) · [day three-quarter/top/elevated](review/day_2.png)
- [Night front/rear/sides](review/night_1.png) · [night three-quarter/top/elevated](review/night_2.png)
- [Before capture manifest](before/capture-results.json) · [after capture manifest](after/capture-results.json)

## Named gameplay

The scenarios reuse `vehicle_lineup_3d_day`'s real Eerikinkatu, Helsinki pose (385325.8, 6671757.1, heading 0.59). A fresh [map query](map-find.log) independently confirms Eerikinkatu and the same pose, with 12 nearby lamps, 13 buildings, four colour groups and one commercial building. The target is 28 m ahead/0.9 m left, its heading the pose heading + 0.95π, exposing its nose/side in the existing eye camera. These are client-only visual fixtures; the Python simulation still owns normal traffic headings and decisions.

Readiness requires the exact pooled city bus at that point, its source −X nose aligned with the requested heading, lamps on, a fully framed model at least 80 px on both axes, HUD/building footprint clearance and no nearer dynamic body intersecting its projected rectangle. Normal server pose/time/weather/map checks must settle for 60 frames and remain true during measurement. Full screenshots and result paths are indexed in [manifest.json](manifest.json). Accepted raw screenshots were visually inspected.

An initial Oulu placement was rejected for HUD/building overlap; its day run was stopped and its immediately started night run interrupted before capture. They receive no visual credit. Disposable userdata is used and removed; native cache-write errors caused by changing the runtime userdata name are retained in logs. No script/readiness failure is waived.

Only the recorded day/night street and close fixtures are verified. Other findings, bus stop behavior and source model redesign are outside this correction; night headlight glare can reduce fine detail.

| Accepted scenario | Bounds (px) | Inspected evidence |
|---|---|---|
| `vqa_city_bus_day` | 237×244 | [screenshot](gameplay/vqa_city_bus_day/2026-06-20T1500_20261115-191146_a4728169-dirty/screenshot.png) · [readiness](gameplay/vqa_city_bus_day/2026-06-20T1500_20261115-191146_a4728169-dirty/result.json) |
| `vqa_city_bus_night` | 237×244 | [screenshot](gameplay/vqa_city_bus_night/2026-10-20T2250_20261115-191335_a4728169-dirty/screenshot.png) · [readiness](gameplay/vqa_city_bus_night/2026-10-20T2250_20261115-191335_a4728169-dirty/result.json) |
