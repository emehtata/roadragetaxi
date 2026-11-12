# Car model / procedural LOD pop

## Goal
Stop the visible jump from the procedural car mesh to the authored GLB model when a car crosses the
switch distance while driving. It used to be 22 m for cars and 16 m for buses.

## Chosen fix
Push the swap out to one distance where it is hard to see: `MODEL_CAR_RANGE` (66 m). Cars and
vehicles closer than that to the view centre (or `windshield_at` in the windshield view) draw their
GLB model. Farther ones draw the procedural mesh. Buses and the other modelled vehicles use the same
range. There is no per-frame cap and no rank sort. Cars draw without a stable id, so hysteresis or
crossfade would need per-car state, and that is out of scope.

Trade-off: the swap still happens, now at 66 m, where a car is small. Work scales with the number of
cars in range, not a fixed cap. Item 6 measures that cost.

## Files to change
- `godot/buildings_3d.gd`
  - `const MODEL_CAR_RANGE := 66.0`.
  - `car()` and `vehicle()`: replace the 22 m / 16 m tests with
    `at.distance_to(windshield_at if windshield_on else view_centre) < MODEL_CAR_RANGE`.
  - Leave the procedural detail 0/1 switch at 35 m alone.
  - Train (35 m) unchanged.
- `godot/tests/run_tests.gd`: the tests below.
- `tools/visual_scenarios.json`: a scenario where cars come close and pass the camera in daylight, so
  the swap at 66 m can be checked. The current `car_lod_pass_day` drives too little distance and
  shows no cars near the switch, so it must be replaced or extended.

## Acceptance criteria
1. A car within 60 m of the view centre draws its model. A car at 70 m draws the procedural mesh.
2. A bus at 20 m draws its model, same as cars.
3. Taxi/windshield view: the same rule applies with `windshield_at` as the centre.
4. Uncommitted glazing, windscreen and showcase-sky changes in the tree are kept as they are.
5. Frame cost: the drive bench (memory: drive-bench recipe) at a dense street gives p50/p95 frame
   time and the `car`/`vehicle` draw time, before and after. Each is within 10% of the pre-change
   baseline, measured on native Windows Godot, not WSL Mesa. If it is not within 10%, report the
   numbers and stop; do not add a cap without asking.
6. Visual check: a named scenario with readiness passed, and frames of a car crossing 66 m on old
   and new code (car at ~75 m, ~60 m and ~20 m). Look at them. On the new code the car changes
   representation once, at about 66 m, and it is small there. On the old code the swap is at 22 m
   and is visible.

## Tests to add (`godot/tests/run_tests.gd`)
- `test_car_model_range`: a car at 60 m uses its model; a car at 70 m is procedural. Fails on old
  code (procedural past 22 m, so the 60 m check fails).
- `test_bus_model_radius_matches_car`: a bus at 20 m uses its model. Fails on old code (16 m).
- Run the whole suite with `XDG_DATA_HOME=$(mktemp -d)`. The known Python failures are
  `test_license_inventory` and `test_motorway_result_has_spawn_rejections`.

## Out of scope
- Crossfade or dither LOD transitions, and per-car hysteresis state.
- A per-frame cap on models. Add it only if item 5 fails, and ask first.
- Building/pedestrian LOD (the 40 m switches near `buildings_3d.gd` line 1154).
- Train model range.
- MultiMesh instancing of models.
