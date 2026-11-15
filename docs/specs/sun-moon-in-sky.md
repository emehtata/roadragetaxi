# Sun and Moon visible in the sky

## Goal
Draw a sun disc and a moon disc in the 3D sky at the real altitude and azimuth the
server already computes for the game date, clock and location (e.g. Oulu).

## Astronomy source (reuse, no new maths)
- Sun: `calendar._solar_geometry` / `solar_position_on` in `src/theroadragetrip/calendar.py`
  (NOAA-style declination + equation of time; about 0.5 deg; no refraction).
  Already sent as `calendar.sun_altitude_deg` and `sun_azimuth_deg` (protocol.py:635).
- Moon: `moon.moon_position_at` (PyEphem, under 0.1 deg; topocentric alt/az) is already
  sent as `moon_altitude_deg`, `moon_azimuth_deg`, `moon_illumination`.
- No server change unless a field is missing from a state frame. Azimuth is clockwise from
  the map's grid north, the same convention `Daylight.sun_direction` already uses.

## Files to change
- `godot/sky_clouds.gdshader`: add `uniform vec3 sun_dir`, `uniform vec3 moon_dir`,
  `uniform float moon_illumination`, `uniform float sun_visible, moon_visible`. Draw a sun disc
  (~0.53 deg angular diameter, enlarged up to 2 deg for readability, with a soft glow) and a moon
  disc of the same size, lit fraction shaded by `moon_illumination`. Draw both behind the clouds
  (fade with cloud thickness) and not below the horizon (alt < -1 deg means hidden).
- `godot/buildings_3d.gd`: new `func set_sky_bodies(sun_alt: float, sun_az: float, moon_alt: float, moon_az: float, moon_illum: float) -> void`.
  It sets the uniforms from `Daylight.sun_direction(...)`. Use this, not `set_celestial_light`,
  because the light follows the moon at night and would move the sun disc.
- `godot/map_layer.gd`: pass `set_sky_bodies` through to the 3D layer.
- `godot/main.gd` (near line 1018): call `map_layer.set_sky_bodies(...)` every frame with the calendar values.
  It must return early if nothing changed, the same way `_sun_key` does.
- `godot/visual_test.gd`: add the readiness checks `requires.sun_in_view` / `requires.moon_in_view`.
  Each passes when that body's alt is above 0 and its direction projects inside the camera frustum
  (`Camera3D.is_position_in_frustum(cam_pos + dir * 1000)`).
- `tools/visual_scenarios.json`: add the two scenarios below.

## Behaviour / acceptance
1. With a clear sky, the sun disc's centre is within 1 deg of the server's sun direction.
   It is visible only when `sun_altitude_deg > -0.833`.
2. The moon disc's centre is within 1 deg of the server's moon alt/az. It is visible when moon
   alt > 0, also by day. Its lit fraction follows `moon_illumination`.
3. Under overcast (cloud >= 0.9), neither disc is visible.
4. The existing lighting, shadows, `--sun-altitude` override and moonlight are unchanged.
   The `--sun-altitude` override also moves the disc.
5. The work costs no extra draw calls (shader only) and needs no per-frame allocation.

## Tests to add
- `tests/test_sky_bodies.py::test_oulu_sun_position_reference`: Oulu (65.01 N, 25.47 E),
  2026-06-21 13:00 local. Compare `solar_position_on` against the NOAA calculator value
  (confirmed 2026-11-15 with the NOAA/Meeus algorithm and PyEphem's airless Sun: altitude 48.30 deg,
  azimuth 173.12 deg true; solar noon in Oulu is about 13:21 EEST, so not 180). Also check
  2026-12-21 12:30 EET: altitude 1.51 deg, azimuth 183.17 deg. `solar_position_on` gives 48.32/173.28
  and 1.50/183.22 (tolerance ±0.5 deg altitude, ±1 deg azimuth).
  Note: the azimuth is grid-north and the grid convergence at Oulu is under 1 deg.
- `tests/test_sky_bodies.py::test_oulu_moon_position_matches_ephem_reference`: check
  `moon_position_at` against a published alt/az (JPL Horizons) for one timestamp, ±0.5 deg.
  Confirmed: Horizons (airless, geodetic 25.47 E 65.01 N) 2026-10-21 18:00 UTC (21:00 EEST):
  az 170.87, alt 13.72; `moon_position_at` gives az 170.86, alt 13.78, 78% lit.
- `tests/test_sky_bodies.py::test_state_calendar_carries_sky_bodies`: a state frame carries all five
  fields. This fails if the protocol drops one.
- `godot/tests/run_tests.gd` `test_sky_bodies_uniforms`: after `set_sky_bodies(30,180,10,90,0.5)`,
  `sun_dir` equals `Daylight.sun_direction(30,180)` and `moon_dir` is set. This fails without the new function.
- Visual scenarios (Oulu city-centre pose, windshield, clear, cloud 0.0):
  - `sky_sun_oulu_day`: 2026-06-20T21:00. The sun is low in the north-west
    (confirmed: alt 11.3, az 302.0 NOAA). The camera faces az 302. `requires: {sun_in_view: true}`.
  - `sky_moon_oulu_night`: pick a night with the moon high and the sun below -6 deg
    (check with `moon_position_at`). The camera faces the moon's az. Chosen: 2026-10-20T22:50
    (moon alt 6.4, az 207.6 true / ~209 grid, 70% lit, sun about -31), so the moon hangs low
    down the open street of the windshield_oulu_day pose (camera vfov 30 deg; a 14 deg moon at
    az 171 sat behind a facade at the top edge of the frame).
    `requires: {moon_in_view: true}`, `sun_altitude_deg: [-90, -6]`.
  The screenshots count only after the readiness checks pass. Inspect them per docs/visual-testing.md.

## Out of scope
Stars, planets, eclipses, atmospheric refraction or a flattened disc at the horizon,
moon texture or libration, the 2D top-down view, and server-side changes.

## Open items
- Readiness does not detect a disc hidden behind a building. `sun_in_view` and `moon_in_view`
  only check alt > 0 and the frustum. Both renders show the disc clearly; a scenario could still
  pass with its disc behind a facade. Add an occlusion check before relying on them for new poses.
