# Scooter rider legs; pedestrian leg swing in 3D

## Goal
(A) The e-scooter rider stands on the deck with bent-knee legs. (B) Walking
pedestrians visibly swing their legs in the 3D view.

## Cause of (B)
Static trace of the 3D path found no break in the render side:
`EntityLayer.person_pose` (godot/entity_layer.gd:2136) -> `Buildings3D.person`
(buildings_3d.gd:1209, cache key includes `pose`, so each of 6 phases is its
own mesh) -> `person_arrays` swing (buildings_3d.gd:1243-1257) all use the
phase. The phase comes from `animation_time`, and that is frozen for many walkers:
- `Pedestrian.animation_time += update_dt` runs only at
  src/theroadragetrip/pedestrian.py:3080, in the ordinary-walk branch.
- Walkers handled earlier in the same loop `continue` before it. Their walks
  (activity walk-to, linked-driver trip-group walks, thief, taxi stop) all
  step through `_walk_route_to`, so the fix there covers them; the rest of
  `_update_activity` (performing: standing/sitting) and `_update_linked_driver`
  (waiting, in a vehicle) are not walking and stand still by design. Also
  thief/taxi-stop/vehicle-approach walks (`_walk_route_to` at 922, the
  approach block ~2984-2993, ~3000). They move and set `animation_state =
  "walking"` but `animation_time` stays constant, so `person_pose` returns one
  fixed `walk_N` (often `walk_0`, swing 0 = legs together).
- 2D has the same frozen value, but `sin(animation_time*10)` of a frozen time
  looks like a pose, not a missing animation, so 3D is where it shows.
STEP 1 (before editing): log `person_pose` for 5 s of a walker that is
mid-route in a named scenario and confirm the string changes for an ordinary
walker and stays constant for an activity/route walker. If ordinary walkers
also stay constant, find that cause first (screenshots of the user's report in
screenshots/ with their JSON snapshot) and amend this spec.

## Files to change
- src/theroadragetrip/pedestrian.py: advance `animation_time` wherever a
  pedestrian moves with `animation_state = "walking"`: move the increment
  into `_walk_route_to` and the approach-vehicle step (smallest: add
  `pedestrian.animation_time += update_dt` beside each `animation_state =
  "walking"` that follows a move step).
- godot/buildings_3d.gd: `_rider(...)` e-scooter case gets legs; new
  `static func _rider_legs(out: Dictionary, x0: float, x1: float, hip: float, deck: float, trousers: Color) -> void`
  built from `_round_limb` / `_round_part` exactly as the `person_arrays` legs
  (thigh 0.094 -> 0.075 radius, shank 0.073 -> 0.046, shoe box at the ankle).
  Pass `deck` as a new const `SCOOTER_DECK_Y := 0.12`; hip = `SCOOTER_RIDER_SEAT`.
- godot/tests/run_tests.gd: tests below.

## Acceptance
1. A walker taking a route step (`_walk_route_to`) advances `animation_time` by dt.
2. Two `person_pose` calls on its time 0.1 s apart differ (phase advances):
   walking runs at `EntityLayer.WALK_POSES_PER_S = 10.5` poses/s (6 per
   stride, 1.75 strides/s), so every 0.1 s step shows the next pose; the old
   `10/TAU*6` = 9.55/s missed ~5 % of steps. Dodging walkers
   (`dodge_timer > 0`) also advance `animation_time`, and so does every
   `_walk_route_to` step including the snap onto a route node. A dodging
   walker is not rolled for a new activity (`_consider_activities` skips
   `dodge_timer > 0` before its `random.random()` draw), so in seeded runs a
   dodging pedestrian no longer consumes a draw and later pedestrians' draws
   shift: the same seed can pick different activities than before.
3. `person_arrays(..., "walk_1", ...)` and `"walk_4"` produce different vertex
   sets, and neither equals `"walk_0"` (swing visible in the mesh).
4. Rider legs: two legs, each hip at y >= SCOOTER_RIDER_SEAT - 0.05 and above
   the deck; lowest foot vertex y within 0.02 of SCOOTER_DECK_Y; knee x ahead
   of the straight hip-to-ankle line (bent), feet staggered along x within the
   deck, z within +-0.2. Foot rule: ankles within x0..x1 (back ankle at
   x0, front at x1); the shoe box (as person_arrays: centre 0.06 m ahead of
   the ankle, half-length 0.12) makes the feet reach x0 - 0.06 .. x1 + 0.18,
   which must lie inside the deck (procedural: -0.72..0.62 of the
   half-length). Knee rule: >= 0.05 m ahead of the hip-ankle line.
5. The torso stays at `seat` (no change to body or head positions).
6. Render: a walking pedestrian at two phases (walk_1, walk_4) and the scooter
   rider from the side, inspected by eye, for both the procedural scooter
   and the GLB models used in game. Deck tops (mesh bounds after the node
   transforms at the 1.2 x 0.5 m sim size): `e_scooter` grip tape
   (kick-scooter-steel) is one box, 36 vertices / 8 corners, x -0.060..0.060,
   z -0.427..0.427, y 0.1175..0.1225: a flat top at 0.1225 =
   SCOOTER_DECK_Y + 0.0025 over the whole foot span (no vertex lies under
   the feet, the corners are at the box ends, so the earlier per-bin probe
   found none). The tape is 0.12 m wide; the shoes (z 0.1 +- 0.072) overhang
   it sideways onto the charcoal frame;
   `e_scooter_grab3d` body under the feet (length -0.2..+0.2 m) top
   0.132..0.158, i.e. 0.012..0.038 above SCOOTER_DECK_Y. Those are the
   per-0.1 m length bins (vertices with |x| <= 0.12, y < 0.6, z snapped to
   0.1 m) z-0.2: 0.138, z-0.1: 0.132, z+0.0: 0.138, z+0.1: 0.138, z+0.2: 0.158;
   the z+0.3 bin (0.25..0.35 m, where the front toe ends at 0.348) tops at
   0.465 (stem base) and z+0.4 at 0.453; behind, z-0.3: 0.250 (fender). Decision: one SCOOTER_DECK_Y for both models;
   on grab3d the soles sit up to 0.04 m into the deck and the front toe
   touches the stem base, accepted (seen from the side, not visible at play
   zoom). Per-model feet only if that shows in game.
   In-game check (godot-shot, Helsinki daytime, a walker and a scooter
   rider in view): NOT VERIFIED. One shot at the default top-down zoom
   showed pedestrians only as few-pixel figures and no scooter rider, so
   neither the swing nor the rider's legs could be judged in game. A second
   shot at zoom 6 showed only the player on foot, seen straight from above:
   the game camera is top-down, so leg swing is not legible in game; the
   side-view showcase frame is the evidence. No named scenario has a
   readiness check for pedestrians or scooters in view, so this is the
   `character_showcase.gd ... day legs` frame. For a named scenario in
   tools/visual_scenarios.json, readiness checks must pass; otherwise a
   tests/character_showcase.gd frame.

## Tests to add (godot/tests/run_tests.gd)
- `test_walk_pose_phase_changes_mesh`: fails today only if the swing mesh is
  identical across phases; guards acceptance 3.
- `test_scooter_rider_feet_on_deck`: calls the `vehicle_arrays`/detail build
  with `extra {"riding": true}`; fails now (no leg vertices below `seat`).
- tests/ (pytest) `test_route_walker_animation_time_advances`: a pedestrian
  stepped through `_walk_route_to` for 1 s has `animation_time` ~ 1.0; fails
  now (stays 0.0).

## Out of scope
Running/sitting poses, arm swing, bicycle and motorcycle rider legs, the 2D
drawing, horseback legs, new walk-cycle shapes.
