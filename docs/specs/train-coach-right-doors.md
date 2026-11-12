# Train coach: doors on the right side, shown in a render

## Goal
Settle that the coach the 3D view draws has doors on its right side only, and prove it
with a door-count check and an oblique render of the right face (not a top-down frame).

## Rule (docs/specs/vehicle-realism-audit.md, line 49)
> vehicle_arrays "train","tram": ... doors on both sides of a tram (the real-world line),
> on the right side of a train coach.

## Which coach drawing is used where (godot/buildings_3d.gd `vehicle()`, ~l.995)
- Close (`opaque` / --outdoor-3d and < 35 m from the windshield or view centre): the
  authored `train_coach.glb` via `place_model_car`. The procedural door strips are NOT drawn.
- Lineup: `vehicle_lineup_3d_coach_right` puts the coach a few metres from the taxi, so with
  --outdoor-3d it is the GLB too. Without `opaque` it is the procedural box at every distance.
- Far (>= 35 m, or not opaque): procedural `vehicle_arrays("train", ...)`. Its coach doors
  (l.1183-1186) are two 0.065 m dark strips per door position, on +y only. They are seams,
  not door leaves, and too thin to see at lineup zoom.
- Open: which side of the GLB has doors, and whether `place_model_car` (l.860-873,
  `along_x`) puts the GLB's door side on the vehicle's +y (right, as the lamp code assumes).

## Files to change
- `tools/visual_scenarios.json` `vehicle_lineup_3d_coach_right`: add the missing
  `"lineup_coach": [look, length, width]` (visual_test.gd l.114 reads it, so the scenario
  fails without it); add `"train_models_in_view": 1` to `requires` and
  `"server_args"`/view flags so it runs with --outdoor-3d (the GLB path).
- `godot/tests/vehicle_showcase.gd`: a `coach_right` group: the procedural coach and
  `train_coach` GLB side by side, camera oblique on the vehicle's +y face (low, about 20 deg
  above horizontal, looking at the side, not down).
- Smallest fix if the GLB doors are on the left: flip its yaw by 180 deg in
  `place_model_car` for `train_coach` only (the coach is symmetric end to end).
- Smallest fix if the procedural coach shows no door: widen each door to a 1.3 m leaf
  `_part(... door_x, door_x + 1.3, ...)` in a darker paint, still +y only. Nothing else.

## Acceptance criteria
1. `vehicle_arrays("train", 26.4, 2.89, c, 0, {"profile": "standard"})`: the door parts
   (colour Color8(42, 48, 51)) all have y > 0; count = 2 (one per door position).
2. Same call with `kind "tram"`: door parts on both y signs, 2 each.
3. Same call with `{"profile": "locomotive"}`: no door parts.
4. `vehicle_showcase.gd ... day coach_right` render, inspected by eye: both coaches show
   doors on the face towards the camera; a second render from the -y side shows none.
5. `vehicle_lineup_3d_coach_right` passes readiness (`train_models_in_view` >= 1,
   `buildings_in_view` >= 3), and in the frame the coach's doors face the taxi's side, as
   the coach sits left of the taxi heading the same way (its right side faces the camera).

## Tests to add
- `godot/tests/train_doors.gd` (headless SceneTree, like `metallic_paint_render.gd`):
  `test_coach_doors_right_only`, `test_tram_doors_both_sides`, `test_locomotive_no_doors`
  (criteria 1-3). Fails if the side list at l.1185 changes to both sides or to -y, or the
  locomotive guard at l.1183 is dropped.
- GLB side: the coach_right showcase render (criterion 4) is the check; a mesh-AABB door
  test on an authored GLB is skipped (no door node names to key on).

## Out of scope
- Tram/bus door work, pantograph, far bus bands (audit mismatch 7).
- Platform-side door logic (doors opening towards the actual platform).


## Decisions (2026-11-05)
- Criterion 5 (door evidence): accepted. The oblique showcase renders (coach_right, coach_left in godot/tests/vehicle_showcase.gd) are the door evidence. The named scenario vehicle_lineup_3d_coach_right stays top-down and shows the coach's roof only.
- The train_coach.glb model has doors on both sides. Not fixed: the close-range authored coach is accepted as is, and the right-side rule applies to the procedural coach only.
