# Third-person camera: always-on mouse look and wheel zoom (on foot and in the taxi)

## Goal
In camera mode 1 (THIRD), moving the mouse orbits the chase camera around the walker or the taxi, with no button held.
The orbit stays fixed when the walker or taxi turns. A reset key brings it back behind them smoothly. The mouse wheel zooms the chase distance (source section 9). The change is client-side
rendering only. Source: docs/3rd-person-mouse.md, which is a clear requirement and not an analysis.

## Files to change
- `godot/camera_modes.gd`: add orbit state `var orbit_yaw := 0.0` (offset from the entity heading),
  `var orbit_pitch := 0.0`, `func look(relative: Vector2, sensitivity: float) -> void`,
  `func reset_look() -> void` (eases yaw and pitch back to 0 with exp smoothing, so the result does not depend on frame rate),
  and `const PITCH_MIN/PITCH_MAX`. `_follow()` uses the world yaw `orbit_world = smoothed heading at grab + orbit_yaw`
  while looking. Once the player has looked away, the yaw is held in world space so it stays put when the entity turns.
  `chase_pose()` gets an extra `pitch := 0.0` argument that raises or lowers the eye around the look target.
  Keep CLEARANCE_M and the deck clamp.
  Zoom: `var zoom_walk := 1.0`, `var zoom_car := 1.0` (target distance scale per mode, kept separately) plus the smoothed
  `_zoom_cur`; `func zoom_step(notches: float, sensitivity: float) -> void` changes the active mode's target and clamps it to that
  mode's [min, max] distance. `_follow()` eases `_zoom_cur` toward the active target with exp smoothing and scales the back/up offset
  (CHASE_BACK_M/UP_M or WALK_BACK_M/UP_M) by it. On enter/exit taxi the target switches mode and `_zoom_cur` keeps easing from the
  current distance, so there is no jump. The zoomed eye goes through the same CLEARANCE_M ground clamp and DECK_GAP_M deck clamp.
  The walk min distance must keep the eye outside the walker capsule and the car min outside the taxi body.
- `godot/main.gd`: in `_set_windshield()`, also capture the mouse when `walk_chase` is set or when the taxi chase is on.
  This uses the same headless / visual-test / screenshot guards as walk_eye. Add a `_chase_look(event)` next to `_walk_look`
  that sends MouseMotion to `camera_modes.look()` only while the mouse is captured, and handles Esc to free and click to recapture
  the same way. Release the cursor whenever the phone, the menus or the settings open, and recapture it when they close.
  Use the existing open/close points and grep `_clear_focus` / the phone toggle. Bind the reset to a new action
  `camera_reset` (default key C, configurable through the InputMap / settings like the other keys).
  Wheel: in the existing MOUSE_BUTTON_WHEEL_UP/DOWN branch (around line 549, which today calls the 2D `_zoom`), when the mode is
  THIRD and the mouse is captured, call `camera_modes.zoom_step(+1 up / -1 down, setting)` instead. Up means closer. Mark it handled.
  Do nothing while the phone, menus or settings are open. Top-down and the 2D map keep `_zoom`.
- Settings: add `chase_zoom_sensitivity`, `chase_walk_min_m`/`chase_walk_max_m` (defaults 1.5/8) and `chase_car_min_m`/`chase_car_max_m`
  (defaults 4/20) next to `chase_mouse_sensitivity`. Add `chase_mouse_sensitivity` next to `interior_mouse_sensitivity`, with i18n keys in every shipped language
  (fi/en/de in `godot/i18n.gd`).
- `tools/visual_scenarios.json`: add 4 scenarios (see below). The file currently has an uncommitted whole-file reformat
  that belongs to the user. Stage only the added hunks (or add the entries without touching other lines), and do not commit the reformat.

## Behaviour / acceptance criteria
1. Mode THIRD, gameplay active: mouse motion with no button held changes orbit yaw and pitch. Yaw is unlimited (a full 360 degrees
   works), and pitch is clamped to [PITCH_MIN, PITCH_MAX].
2. The same code path handles the walker and the taxi. When the player enters or leaves the taxi, the orbit offset is kept and the
   existing `begin_eye_transition` glide plays. Mouse control is not lost.
3. When the entity turns 90 degrees after the player has looked away, the world-space camera yaw stays the same: no auto-snap behind.
4. With orbit 0, the result is the same as today's chase pose. The existing `godot/tests/camera_modes.gd` cases pass unchanged.
5. `camera_reset` brings the orbit back to 0 smoothly. After 1 s in total, the yaw is within 1 degree, whether the time is split
   into 30 fps or 144 fps deltas.
6. Opening the phone or a menu sets MOUSE_MODE_VISIBLE, and mouse motion then does not rotate the camera. Closing it recaptures the mouse.
7. Walking direction (W/S/A/D and the server command) does not depend on orbit yaw in THIRD. The server stays authoritative and
   gets no new command fields.
8. Sensitivity comes from the setting, and doubling the setting doubles the yaw from the same `relative`.
9. In THIRD, wheel up shortens and wheel down lengthens the eye-to-target distance, walking and driving, no button held.
   The distance eases (no single-frame jump over 30% of the change), and doubling the zoom sensitivity doubles the target change per notch.
10. Distance never goes below the mode's min or above its max, however many notches arrive. The walker and taxi limits are separate.
11. Rotating (look) does not change the distance; zooming does not change the orbit yaw or pitch.
12. Entering or leaving the taxi at any zoom level moves the distance smoothly to the other mode's stored target, with no one-frame jump.
13. While the phone, a menu or the settings are open, the wheel does not change the camera distance.
14. At max zoom over a slope or under a deck, the eye stays at least CLEARANCE_M above the ground and DECK_GAP_M below the deck.
    At min zoom the eye is outside the walker or taxi body.

## Tests to add
- `godot/tests/camera_modes.gd`:
  - `test_look_orbits_without_button`: `look(Vector2(100,0), s)` changes the yaw of the chase transform. Fails today because there is no `look`.
  - `test_pitch_clamped`: a large y motion is clamped to PITCH_MAX.
  - `test_orbit_held_when_heading_turns`: after a look, `chase()` with heading +90 degrees gives the same eye bearing. Fails today
    because the heading is followed.
  - `test_reset_frame_rate_independent`: running 30 vs 144 fps deltas over 1 s gives the same yaw within 1 degree.
  - `test_sensitivity_scales`.
  - `test_zoom_in_out_walk` / `test_zoom_in_out_car`: wheel up moves the eye closer, down farther. Fails today because there is no `zoom_step`.
  - `test_zoom_limits`: 100 notches either way clamp to min/max per mode.
  - `test_zoom_smooth`: the distance eases over several frames instead of jumping.
  - `test_zoom_kept_while_rotating`: look() after a zoom keeps the distance.
  - `test_zoom_enter_exit_smooth`: switching walker to taxi at min and at max zoom gives no frame-to-frame jump above the threshold.
  - `test_zoom_clearance`: max zoom over raised ground or under a deck still obeys CLEARANCE_M / DECK_GAP_M.
- `godot/tests/walk_camera_keys.gd`:
  - `test_chase_captures_mouse_and_phone_releases`: run with `XDG_DATA_HOME=$(mktemp -d)`.
  - `test_wheel_zooms_chase_not_when_phone_open`: a wheel event changes the zoom target in THIRD and leaves it unchanged with the phone open.
- Visual: `chase_look_side_day` (taxi, orbit +90 degrees, the side of the taxi is visible) and `walk_chase_look_back_day`
  (walker, orbit 180 degrees, the walker's front is visible). Both start from existing city-centre poses and set the orbit through a
  scenario field (for example `"orbit_deg"`) that visual_test.gd applies. The screenshots count only after the readiness checks pass,
  and they must be inspected.
- Visual zoom: `chase_zoom_min_day` and `chase_zoom_max_day` (taxi, from the same pose, set through a `"zoom"` field of `"min"`/`"max"`).
  At min, the camera is close behind the taxi with no body clipping. At max, the taxi is small and the camera is above the ground.

## Acceptance check
The full Godot and pytest suites pass. All four new scenarios pass their readiness checks. Their screenshots show the taxi side, the walker front, the close zoom and the far zoom.
Each step gets its own atomic commit with the required trailer: camera_modes plus tests, then main.gd input plus settings plus i18n,
then the scenarios.

## Out of scope
Changes to first-person (EYE) or top-down camera behaviour, gamepad right-stick look, camera collision against buildings (zoom clamps only against the ground and the deck), zoom in EYE/TOP,
and any server/Python change.
