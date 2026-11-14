# On foot: third-person chase camera (key 1)

## Goal
On foot, key 1 shows the walker from behind (third-person chase); key 3 stays
first person, key 2 stays top-down. Driving cameras are unchanged.

## Files to change
- `godot/camera_modes.gd`: walker constants `WALK_BACK_M := 3.0`, `WALK_UP_M := 1.8`,
  `WALK_LOOK_AHEAD_M := 3.0`, `WALK_LOOK_UP_M := 1.2` (a 1.75 m figure fills ~1/3 of
  the height at 3 m, FOV 60). Give `chase_pose` optional params
  `back := CHASE_BACK_M, up := CHASE_UP_M, ahead := LOOK_AHEAD_M, look_up := LOOK_UP_M`
  (driving callers pass nothing). Add
  `func walk_chase(at: Vector2, heading: float, delta: float, height: Callable, covered: Callable, layer := 0) -> Transform3D`
  reusing `smooth_heading`, deck/clearance logic from `chase`.
- `godot/main.gd`:
  - KEY_1/2/3 branch on foot: `_set_windshield(mode != TOP, true)` stays; inside
    `_set_windshield`, `chase` becomes `on and mode == THIRD` (walking or not);
    `walk_eye` becomes `on and walking and mode == EYE`. Add `var walk_chase := false`
    (= `on and walking and mode == THIRD`).
  - `entities.first_person = walk_eye` (unchanged), so the player figure is drawn in
    walk_chase. Mouse capture and `_walk_look` only when `walk_eye`.
  - `_process` (line ~775): new branch `elif walk_chase:` — if no longer on foot,
    `_set_windshield(mode != TOP)` as the walk_eye branch does; else
    `at = entities.player_position()` (server position, interpolated),
    `heading = float(shown_state().player_pedestrian.facing)` falling back to
    `.heading` (same source the figure is drawn with, entity_layer.gd:1990);
    set `buildings_3d.chase_transform = camera_modes.walk_chase(...)`,
    `windshield_at/heading/elevation` as the walk_eye branch.
  - Line 788 (stepping out of the taxi): `_set_windshield(mode != TOP, true)` so
    leaving the car from 1 gives the walker chase, from 3 first person.
  - Eye height/ahead: walk_chase uses `chase_on`, so `eye_height`/`eye_ahead` are irrelevant.
- `tools/visual_scenarios.json`: add scenario `walk_chase_1` (below).

## Behaviour / acceptance
1. On foot, key 1: `buildings_3d.chase_on == true`, `walk_eye == false`,
   `entities.first_person == false`, mouse not captured.
2. Camera sits `WALK_BACK_M` behind the walker along `facing`, `WALK_UP_M` above
   ground, never below ground + `CLEARANCE_M`, under a bridge deck when covered.
3. Key 3 on foot: identical to today (walk_eye, mouse look, no own figure).
4. Key 2 on foot: top-down, as today.
5. Leave taxi in mode 1 -> walker chase; in mode 3 -> first person; re-enter taxi
   -> the driving camera for the kept mode (taxi chase params 7.5/3.2 unchanged).
6. Driving, phone UI, F interaction, and the server untouched.
7. Scenario `walk_chase_1` renders with readiness checks passing; the screenshot
   shows the pedestrian from behind in the lower centre.

## Tests to add
- `godot/tests/camera_modes.gd`: `test_walk_chase_pose_behind_walker` — pose eye is
  3.0 m behind/1.8 m up for heading 0 and PI/2; fails without `walk_chase`.
  `test_chase_pose_defaults_unchanged` — driving pose still 7.5/3.2.
- `godot/tests/walk_camera_keys.gd` (new): fake on-foot state, send KEY_1 / KEY_3 /
  KEY_2, assert criteria 1, 3, 4; fails today because KEY_1 sets walk_eye.
- Run: `XDG_DATA_HOME=$(mktemp -d) make godot-test` (whole suite must pass).

## Visual scenario
Copy `walk_eye_i` (Helsinki pose 385325.8, 6671757.1, 0.59, same time, weather,
`requires`) to id `walk_chase_1`, camera `1`, description "On foot, 1: third-person
walker chase". `tools/visual_scenarios.json` carries the user's uncommitted
whole-file reformat: stage only the new scenario hunk (`git add -p`, or apply the
addition to a `git show HEAD:` copy in a temp worktree); never commit the reformat.

## Out of scope
Collision of the walker camera with building walls, zoom/orbit with the mouse in
third person, any server/protocol change, traffic law (no NPC behaviour changes).
