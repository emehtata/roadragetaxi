# Precipitation that falls from sky to ground

## Goal
Rain and snow are a 2D screen overlay today (`weather_layer.gd`: 220 dots/streaks
in screen fractions, same speed for all, no depth, no ground, no buildings). Draw
them in the 3D view as world-space particles that fall from above to the ground.

## Files to change
- `godot/precipitation_3d.gd` (new): `class_name Precipitation3D extends Node3D`; owns one
  `GPUParticles3D` box emitter (follows camera x/y, top at `EMIT_HEIGHT_M`) and one
  `GPUParticlesCollisionHeightField3D`. Signatures:
  `func set_weather(kind: String, intensity: float, wind_mps: Vector2) -> void`,
  `static func drop_count(kind: String, intensity: float) -> int`,
  `static func fall_velocity(kind: String, layer: float, wind_mps: Vector2) -> Vector3`.
- `godot/precip_rain.gdshader`, `godot/precip_snow.gdshader` (new, `shader_type spatial`,
  unshaded, billboard): rain = velocity-stretched streak quad; snow = round soft flake with
  per-particle sway (sin of age and a random phase) and slow spin.
- `godot/buildings_3d.gd`: add the node to the 3D world next to the camera; in `_process`
  call `set_weather` (reuse the `sky_wind` hookup and the existing weather state feed).
- `godot/weather_layer.gd`: keep `falling(state)`, `wind_vector()`, ripples, splashes, mud.
  When the 3D view is active hide the 2D `precipitation` overlay (no double rain).
  The overlay stays as the fallback when 3D is off.

## Behaviour / acceptance criteria
1. Drops spawn at `EMIT_HEIGHT_M` (>= 25 m above ground) and move down to y=0; none
   spawn or hover at screen height.
2. Fall speed: rain 6-9 m/s, snow 0.8-1.6 m/s (not scaled by zoom or frame rate).
3. Drift: horizontal velocity = server `wind_vector_mps` times a factor
   (rain 0.5, snow 0.9), so streaks lean downwind; zero wind falls straight down.
4. Depth layering: a per-particle `layer` in 0..1; near layer is up to 2x larger and
   1.3x faster than far; far drops are smaller and dimmer. Sizes are metres, so they
   scale with camera height.
5. Rain is a streak aligned to its velocity, length = velocity * 0.35 s (0.05 s was
   near-invisible from the top-down camera). Snow is a
   round flake with sideways sway 0.2-0.5 m amplitude, 0.5-1.5 Hz, random phase.
6. Density per intensity (same for both kinds): count = `MAX_PARTICLES` * intensity,
   intensity = 0.35 (light), 0.7 (rain/snow), 1.0 (heavy/thunderstorm); slush uses the
   rain streak at snow speed (3 m/s). Count never exceeds `MAX_PARTICLES` (8000).
7. Per-frame cap: `amount` is set only when the kind or intensity step changes, never
   per frame; no per-particle GDScript. Perf label `precipitation_3d` stays under 1 ms.
8. Ground and buildings: drops die at the ground, and at roof height over a footprint
   (height-field collision on the building layer); no drop is visible inside a building
   or below a roof. A drop landing on the ground may spawn a splash only through the
   existing `weather_layer` splash pool (no new per-drop nodes).
9. No change to simulation weather: no new server fields, `weather.py` and
   `protocol.py` untouched; the node only reads the `state["weather"]` dict.
10. Underground (`map_level != 0`) or `kind == ""`: node hidden, emitting off.
11. `graphics.precipitation == false` hides the node as well.

## Tests to add
- `godot/tests/precipitation_3d.gd` (register in `run_tests.gd`):
  - `test_fall_velocity_down_and_with_wind`: y is negative in range of AC2, x/z follow
    wind; fails if drops fall up, sideways or against wind.
  - `test_layers_near_faster`: `fall_velocity(kind, 1.0)` is faster than `(kind, 0.0)`.
  - `test_drop_count_matches_intensity_and_cap`: same count for rain and snow at the same
    intensity, monotonic, <= 8000; fails with the old fixed 220.
  - `test_hidden_when_underground_or_clear`.
  - `test_overlay_hidden_when_3d_active`: `weather.precipitation.visible == false`.
- `tests/test_weather.py` untouched; add a check there only if a server field is added (it is not).

## Visual scenarios (`tools/visual_scenarios.json`, rules in docs/visual-testing.md)
- `wet_asphalt_night` (existing, rain): streaks lean with wind, lit by lamps and headlights,
  none inside the 4 buildings in view.
- `snow_street_day` (new, copy `wet_asphalt_night` pose, `"weather": "snow"`, daytime
  January start_time, cloud 0.9, wetness range matching snow): flakes drift and flutter;
  needs `buildings_in_view` 4. Check two screenshots 0.5 s apart: flakes moved down.

## Out of scope
- 2D-only view particles; server weather model; rain audio; wet-surface shading;
  snow accumulation; lightning; windshield drops; per-building interior checks.
