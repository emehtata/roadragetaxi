# Binoculars in outdoor first person

## Goal
Let the player raise binoculars in either outdoor FPS view and magnify the complete view around the manually aimed centre. The Moon is one verification target; roads, vehicles, buildings, people, vegetation and sky must magnify through the same optical view.
This task is specification only; implementation is a later task.

## Files to change
- `godot/binoculars.gd` (new): activation, magnification/FOV calculation, easing and presentation state.
- `godot/main.gd`: FPS input routing, camera-only aiming, lifecycle and UI priority.
- `godot/buildings_3d.gd`: apply the active FPS optical FOV after the normal camera pose; preserve normal FOV for other views.
- `godot/i18n.gd`, `README.md`: controls, magnification hint and Finnish/English/German text.
- `godot/tests/binoculars.gd`, `godot/tests/manifest.txt`: meaningful control, projection and restoration checks.
- `godot/visual_test.gd`, `godot/visual_test_moon_roofs.gd`, `tools/visual_scenarios.json`, `docs/visual-testing.md`: input-driven binocular readiness and Moon pixel evidence at enlarged scale.

## Behaviour / acceptance criteria
1. Binoculars are available immediately in outdoor first person, both on foot (`walk_eye`) and driver-eye (`CameraModes.Mode.EYE`). Key `O` toggles the `binoculars_toggle` InputMap action; key repeats do not retrigger it. Activation in chase, top-down or house interior views has no effect.
2. Raising starts at 2×. Mouse wheel up/down and `+`/`-` (including keypad) select 2×, 4×, 6× and 8×, clamped at the endpoints; `O` lowers them. Consume zoom events only for active binoculars, respecting phone/menu/text-control ownership. Outside binocular use, retain existing zoom controls.
3. Magnification changes the existing Camera3D's vertical field of view using `2*atan(tan(base_fov/2)/magnification)`; it never scales a captured image, changes map zoom or moves the eye toward the target. Capture the ordinary FPS FOV at activation, clamp magnification to 2–8×, and ease FOV changes in at most 0.2 seconds without overshoot or frame-rate dependence.
4. The aim direction remains fixed when raising, lowering or changing magnification. Mouse look permits manual aiming at any visible scene feature, including sky objects; scale angular mouse sensitivity by inverse magnification for controllability. Use the existing outdoor walking yaw/pitch limits. Driver-eye binocular aiming is camera-only, with yaw bounded to ±135° relative to the taxi and pitch to ±80°; it does not steer the taxi or change server walking/vehicle commands.
5. There is no Moon snapping, automatic centring or tracking. The normal simulation clock continues, and sky bodies remain at their existing celestial directions. Binocular magnification applies to the complete rendered view: world geometry, vehicles, pedestrians, vegetation, terrain and sky all grow together through the same camera projection. Looking away from the Moon reveals the same magnified world and sky.
6. Show a restrained binocular vignette and the active magnification (`2×` etc.) plus a short localized lower/zoom hint. Keep the central image unobstructed, preserve normal UI interaction/F12 capture and fit the overlay at 640×360 and 1280×720; no forced stereo double image or extra scene render is required.
7. Lowering restores the exact pre-binocular FPS FOV and base look sensitivity, retaining the current aim. Switching camera mode, entering/leaving the taxi, entering a building, respawning, opening pause/phone/help, focus loss or ending a session lowers binoculars and clears optical zoom; reopening starts at 2×. No narrow FOV or overlay leaks into another view.
8. The full scene magnifies through camera projection without per-object scaling. Moon phase, texture orientation, maria/crater detail and angular geometry are magnified together. No Moon-only size/brightness changes, texture replacement or new lunar noise. Clouds, horizon, buildings and terrain occlude objects normally; binoculars cannot reveal hidden or below-horizon content.
9. Reuse the single outdoor 3D scene, sky material and full-resolution viewport with Vulkan/Forward+. No additional camera/SubViewport, per-frame texture generation, network activity or server astronomy changes. Repeated raising/lowering leaves node/resource counts bounded and does not alter map streaming zoom/radii.
10. Add `binoculars_oulu_moon_2x` and `binoculars_oulu_moon_8x` using the sourced `oulu_gibbous_moon` location/date and normal on-foot FPS input. Add a matched daytime urban scenario comparing an identifiable building/vehicle/road feature at 2× and 8×. Drive activation/zoom through the real controls, with fixed manual aim; do not set the FOV directly or use a test-only camera to pass. Readiness requires ordinary map/time/weather checks, active FPS/binocular state, expected magnification/FOV and the aimed target fully inside the view.
11. Record base/effective FOV, magnification, eye position, aim direction and projected target bounds. The 8× projected target size must match the camera-projection prediction from the 2× capture within pixel tolerance. For the Moon pair, also record phase/orientation and lit-interior contrast/clipping; show visible surface detail without clipping the disc. Adapt Moon sampling bounds to its projected size instead of the current fixed ±60-pixel scan.
12. Add lower/restore and full-overcast or building-occlusion controls. Run named scenarios with native Windows Godot explicitly using `--rendering-method forward_plus --rendering-driver vulkan`, record active renderer/GPU and inspect every accepted screenshot and Moon crop. Include existing chase zoom, camera switching and ordinary Moon/star controls; a uniform-only or empty-sky result cannot pass.

## Tests to add
- `godot/tests/binoculars.gd::test_controls_and_ui_priority`: activation/steps/key repeat, view eligibility and phone/menu consumption; fails on input conflicts or wheel changes to map zoom.
- `godot/tests/binoculars.gd::test_optical_projection_and_aim`: exact magnification/FOV relationship, clamping/easing, fixed eye/aim and scaled sensitivity; fails on image scaling, camera translation or target snapping. Verify common camera projection enlarges both a world-space target and the Moon/sky by the expected factor.
- `godot/tests/binoculars.gd::test_restore_and_transitions`: all exit paths restore FOV/sensitivity/overlay and reset to 2× on raise; fails on stuck optical zoom or changed movement/steering input.
- `godot/tests/binoculars.gd::test_resource_lifecycle`: repeated toggles/resize/session transitions preserve one outdoor viewport and bounded resources.
- Named scenarios in criteria 10–12: fail without input-driven activation, projected growth of both world geometry and the Moon/sky, visible lunar texture, ordinary occlusion and inspected Windows Vulkan/Forward+ screenshots.

## Out of scope
Purchasing/inventory, handheld models or animations, home interiors, astronomy labels/target tracking, telescope mode, planet implementation, new celestial textures, and removal of existing 2D/2.5D code.
