# Driver-eye first-person view with mouse free-look

## Goal
One first-person view (key `I`) whose camera sits at the taxi driver's eyes when driving and at a
standing eye when walking, with mouse free-look in both. Today it only works in the taxi, from a guessed point.

## Findings (current code)
- `godot/main.gd` `_set_windshield()` refuses to open on foot (`entities.player_body()` is `{}` when `on_foot`).
- `godot/buildings_3d.gd` ~l.302-310: eye = car centre, 1.35 m up, 0.55 m forward; heading-locked, no look input.
  `test_eye` (`at`, `height`, `yaw`) is a test-only override set by `godot/visual_test.gd` l.139.
- `godot/home_first_person.gd` (+ `home_player_3d.gd`) is the only existing mouse-look: capture/release,
  X11 warp recentring, `mouse_sensitivity` (0.0005-0.006, `set_interior_options`). Interiors only; reuse its capture logic.
- `entities.player_position()` already follows the walker; `player_pedestrian` state has x, y, heading (blend `.z`).

## Files to change
- `godot/main.gd`: allow `_set_windshield(true)` on foot; per frame feed the 3D view the eye pose
  (taxi or pedestrian); handle mouse motion/keys for look (not while `home_first_person.visible`).
- `godot/entity_layer.gd`: `func player_eye() -> Dictionary` returning `{position, heading, ground_offset, on_foot}`
  for both modes (generalises `player_body()` for this use only).
- `godot/buildings_3d.gd`: replace the fixed offset with `eye_at/eye_heading/eye_height`, plus `look_yaw`, `look_pitch`
  applied to the camera; keep `test_eye` precedence.
- New `godot/first_person_look.gd`: `static func clamp_look(yaw, pitch, driving) -> Vector2`, mouse capture state.
- `godot/graphics_settings.gd` / settings UI + `godot/i18n.gd`: look sensitivity (reuse the interior range) and invert-Y.
- `tools/visual_scenarios.json`, `godot/visual_test.gd`: `look` key (`yaw`, `pitch`) for scenarios.

## Behaviour / acceptance criteria
1. Driving eye: driver's seat in the taxi's own frame (left-hand drive, Finland): about 0.4 m left of the centreline,
   0.1 m ahead of centre, 1.2 m above the road surface (plus `deck_height`); `forward * 0.55` and the 1.35 m constant are gone.
2. Walking eye: pedestrian position, 1.6 m above ground (plus `deck_height`), facing the walk heading.
3. `I` toggles in both modes. Leaving or entering the taxi while the view is on keeps it on and snaps the eye to the new
   pose with look reset to centre (no one-frame camera at the old pose).
4. Mouse motion while the view is on and captured: yaw += dx*sens, pitch -= dy*sens (invert-Y flips pitch).
   Default sensitivity 0.002 rad/px, setting range 0.0005-0.006.
5. Clamp: pitch -80..+80 deg on foot and driving; yaw free on foot (wraps), -135..+135 deg relative to the car while driving
   (mirror and side windows reachable, no looking through the roof pillar behind).
6. Look is relative to the body: when the taxi turns or the walker turns, the view turns with it and the look offset stays.
7. Recentre: `Home` or middle mouse click zeroes yaw/pitch (eased over <= 0.2 s); also reset on view off.
8. Mouse capture: view on -> mouse captured (reuse the X11 confined/warp path from `home_first_person.gd`); `Esc`/pause,
   focus loss, the phone, and any HUD panel release it; `Tab` toggles capture manually; clicking the view recaptures.
   While released, motion does not look.
9. Walking direction: `WASD` stays relative to the walk heading (body), not the look direction; look is camera-only.
   Driving: steering unchanged.
10. View off restores top-down camera, zoom (`_windshield_zoom`) and normal mouse mode; middle/ctrl-drag pan works again.
11. Unchanged: top-down rendering, Python simulation and its state fields, collisions, controls, replay/state hashes,
    per-frame work (no new allocations per frame beyond one Dictionary).

## Visual scenarios (docs/visual-testing.md; readiness must pass)
- Reuse `windshield_city_day` (driver eye, taxi at centre/left offset visible vs old view) and
  `forest_dense_side_window_day` (`eye.yaw` -> migrate to `look.yaw` 1.571, same picture).
- Reuse `forest_road_on_foot_day`, which today fakes the walker with `eye.at`; the new
  `walk_eye_look_city_day` replaces it with a real on-foot state (`on_foot: true`, `windshield: true`, `look: {yaw: 0.8, pitch: 0.1}`)
  at a city point from an existing city scenario's pose.
- Add `windshield_driver_look_back_day`: `windshield_city_day` pose, `look: {yaw: 2.2}` (clamped, so mirror side visible, no pillar).

## Tests to add
- `godot/tests/first_person_look.gd`: `test_pitch_clamped` (fails if pitch beyond 80 deg), `test_driving_yaw_clamped`,
  `test_walking_yaw_wraps`, `test_recentre_zeroes`.
- `godot/tests/driver_eye_pose.gd`: `test_driver_eye_left_of_centre` (fails with the old 0.55 forward / 1.35 m constant),
  `test_walking_eye_follows_pedestrian`, `test_toggle_on_foot_allowed` (fails today: `_set_windshield` returns early),
  `test_enter_exit_taxi_resets_look`.
- `godot/tests/first_person_mouse.gd` (run with `XDG_DATA_HOME=$(mktemp -d)`): `test_capture_released_on_pause`,
  `test_motion_ignored_when_released`.

## Out of scope
Head bob, a visible body or hands/steering wheel, interior (home) first-person changes, mirrors rendered as textures,
gamepad look, VR, changing 3D chunk/LOD radii, any server change.
