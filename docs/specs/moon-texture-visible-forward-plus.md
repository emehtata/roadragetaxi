# Visible Moon surface texture in Forward+

## Goal
Render the downloaded lunar surface map with visible maria and crater contrast in the real Windows Vulkan/Forward+ game view, correcting the washed-out Moon disc.

## Files to change
- `godot/sky_clouds.gdshader`: keep sampled lunar albedo within a useful displayed brightness range.
- `godot/tests/moon_phase.gd`: verify texture contrast inside the illuminated disc without including its limb or background.
- `godot/visual_test_moon_roofs.gd`: measure surface contrast separately from the spherical phase mask in the actual gameplay render.
- `tools/visual_scenarios.json`: require texture evidence in `oulu_gibbous_moon`.
- `docs/moon-surface-texture.md`: record the rendered verification and retained source/licence.
- Existing Moon asset, binding, licence inventory and FI/EN/DE credits changes: retain them in this delivery.

## Behaviour / acceptance criteria
1. The surface uses `godot/assets/moon/2k_moon.jpg`; visible features come from this image, without generated lunar noise.
2. A Windows Godot launch explicitly using `--rendering-method forward_plus --rendering-driver vulkan` reports those active settings.
3. `oulu_gibbous_moon` passes readiness on that renderer and its inspected screenshot clearly shows the lunar map at the scenario's normal resolution.
4. Texture evidence samples only the confidently lit interior, excluding the limb, terminator and sky; it requires measurable contrast and rejects a clipped, near-uniform white disc.
5. Full/new, crescent, quarter and gibbous phases retain their correct illuminated area, orientation and curved terminator; contrast changes must not alter the phase geometry.
6. Cloud occlusion and the below-horizon visibility flag still hide the Moon as before.
7. The original image, licence text, source URL/hash, attribution documentation, licence inventory and in-game FI/EN/DE credits are present.

## Tests to add
- `godot/tests/moon_phase.gd` — illuminated interior texture contrast: catches the existing false pass caused by sampling outside the disc or counting the phase edge as surface detail.
- `godot/visual_test_moon_roofs.gd` — gameplay Moon texture evidence: fails for the current washed-out disc and records interior contrast/clipping measurements in scenario results.
- `tools/visual_scenarios.json` — `oulu_gibbous_moon`: run natively on Windows with Vulkan/Forward+, inspect its readiness-passed screenshot and result; keep existing phase assertions.

## Out of scope
- Removing the game's 2D/2.5D rendering paths or changing launch/menu flows.
- New lunar coordinates, libration, normal maps, disc size or astronomical phase calculations.
- Changing global exposure, HUD brightness, stars or other sky appearance to fix the Moon.
