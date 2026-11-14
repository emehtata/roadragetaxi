# Keys 1/2/3 on foot; drop the I view

## Goal
On foot the camera keys work like driving: 3 and 1 = first-person walking,
2 = top-down map. The separate I (walk-eye) key is gone; driving is unchanged.

## Starting point (uncommitted, keep)
- `godot/main.gd` `_unhandled_input`: KEY_I branch removed; KEY_1/2/3 call
  `camera_modes.handle_key()` and on foot `_set_windshield(mode != TOP, true)`.
- `godot/camera_modes.gd`: `walk_eye_key()` deleted; `KEYS` map unchanged.
- `godot/visual_test.gd`: scenario walk presses KEY_3.
- `godot/tests/camera_modes.gd`: `test_i_on_foot_only` removed.
- `tools/visual_scenarios.json` `walk_eye_i`: description says "On foot, 3".
- `README.md`, `docs/architecture/godot-client.md`: I key text removed.

## Files still to change
- `godot/tests/release_3d_default.gd`: keep the "KEY_I driving: no windshield"
  check (still valid: I does nothing); reword header line 1 only if needed.
- `godot/tests/camera_modes.gd`: add the on-foot tests below.
- `docs/specs/third-person-camera.md` (lines 12, 66, 72) and
  `docs/specs/windows-release-3d-default.md` (title, lines 5, 12, 37): mark the
  I key as superseded by this spec (one-line note; do not rewrite history).
- `docs/3rd-person.md`: untracked, user-owned. Do NOT edit; flag to the user
  that it still names I.

## Behaviour / acceptance
1. On foot, 3 -> first-person walking view (`_windshield.visible` true).
2. On foot, 1 -> first-person walking view (same as 3).
3. On foot, 2 -> top-down map (`_windshield.visible` false).
4. On foot, I -> no change to view or `camera_modes.mode`.
5. Driving: 1 third person, 2 top, 3 driver-eye, exactly as before; I does nothing.
6. The mode chosen on foot persists into the next drive (camera_modes.mode kept).
7. `grep -rn KEY_I godot/*.gd` finds nothing outside tests asserting it is inert.
8. `XDG_DATA_HOME=$(mktemp -d) make godot-test` passes in full.
9. `walk_eye_i` scenario renders with readiness checks passing; the screenshot
   (inspected) shows first-person walking, not top-down or third person.

## Tests to add (`godot/tests/camera_modes.gd` or a main-level test using the
## same harness as `release_3d_default.gd`)
- `test_on_foot_3_and_1_first_person`: on foot, press 3 then 1; windshield
  visible both times. Fails if main.gd still gates 1/2/3 on `not on_foot`.
- `test_on_foot_2_top_down`: on foot, 3 then 2; windshield hidden.
- `test_on_foot_i_inert`: on foot, press I; windshield and mode unchanged.
  Fails if a KEY_I branch is reintroduced.

## Out of scope
- Third-person walking camera, new key bindings, HUD hint redesign.
- Editing `docs/3rd-person.md`.
