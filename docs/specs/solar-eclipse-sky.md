# Solar eclipse in the sky

**Goal:** the server detects solar eclipses from PyEphem for the actual observer; the sky shader draws the Moon occulting the Sun and the sunlight dims by the covered area. Lunar eclipses: later.

Today: no eclipse code anywhere. Sun alt/az comes from `calendar.solar_position_on` (NOAA formula), the Moon from PyEphem (`moon.py`); both discs use a fixed 1-degree radius (`DISC_COS`), so the Moon is drawn over the Sun with `mix()` as a phase-lit texture, not as a dark occulter, and sunlight never dims.

## Files to change
- `src/theroadragetrip/eclipse.py` (new): `solar_eclipse_state(moment, latitude, longitude, elevation=0.0) -> dict`, same 10 s / observer `lru_cache` key as `planets.py`.
- `src/theroadragetrip/server/__init__.py`: publish `calendar.solar_eclipse` beside `calendar.planet_sky`, same observer (car or walker, DEM height).
- `godot/buildings_3d.gd` `set_sky_bodies`: pass `sun_radius`, `moon_radius` (radians, shared display scale) and `eclipse_obscuration`; `set_sun` multiplies `light_energy` and ambient by `1 - obscuration` (corona floor at totality).
- `godot/sky_clouds.gdshader`: disc radii from uniforms instead of `DISC_COS`; during an eclipse the Moon is an opaque dark disc that masks the Sun disc and glow; corona at totality.
- `godot/visual_test.gd`: `requires.solar_eclipse` readiness check.
- `tools/visual_scenarios.json`: two scenarios below. `docs/planet-sky.md`: short eclipse section.

## Detection (server)
Topocentric, not geocentric: the 1-degree lunar parallax moves the shadow by thousands of km, so the check runs for the observer (`ephem.Observer`, `pressure = 0`, same lat/lon/elevation as the planet sky). Sun **and** Moon positions for the eclipse come from the same PyEphem call, so they share one ephemeris.
State: `{active, phase: "none"|"partial"|"annular"|"total", separation, sun_radius, moon_radius, magnitude, obscuration}` (angles in degrees).
- `magnitude = (r_sun + r_moon - sep) / (2 r_sun)`, active when > 0 and Sun altitude > -0.833.
- `obscuration` = lens-intersection area of the two discs / Sun disc area (1.0 when `sep <= r_moon - r_sun`).
- total if `sep <= r_moon - r_sun`; annular if `sep <= r_sun - r_moon`.
- The rendered Sun direction during an active eclipse uses the PyEphem Sun (NOAA vs PyEphem differ by up to ~0.01 deg, enough to break contact geometry).

## Rendering
Displayed radii keep the true ratio `moon_radius / sun_radius` and centre offset scaled by the same factor as the 1-degree display radius (so the on-screen coverage equals `obscuration`).
1. Partial: the Sun disc shows a dark lunar bite; covered pixels are the sky colour minus the Sun, no moon texture, no glow from the covered part.
2. Total: no Sun disc pixels; dark Moon disc ringed by a corona (radial falloff to ~2 radii, peak below the clipped Sun); sky `energy` and star visibility as civil twilight.
3. Light: `_sun.light_energy` scaled by `1 - obscuration`; at totality the remaining direct light is 0 and ambient is ≤ 0.02 of normal daylight ambient.

## Acceptance criteria
The three fixed test sites SITE_A, SITE_B and SITE_C (constants in `tests/test_solar_eclipse.py`) are made up, none near a city centre.
1. Site A (eastern Finland), 2026-08-12 17:45 UTC: phase partial, magnitude 0.831 ± 0.01, Sun alt ~3 deg (PyEphem, computed for this spec; NASA catalogue, eclipse 2026 Aug 12, lists Finland in the partial zone).
2. Site B (central Spain), 2026-08-12 18:31:00 UTC: phase total, magnitude ≥ 1.0 (inside NASA's 2026 Aug 12 totality path).
3. Site C (southeastern Finland), 2025-03-29 11:38 UTC: partial, magnitude 0.29 ± 0.02 (NASA 2025 Mar 29 partial).
4. Site A, 2026-08-13 17:45 UTC: inactive, obscuration 0.
5. Obscuration matches a numerically integrated disc overlap within 0.005 over magnitudes 0..1.05.
6. No network access (sockets blocked as in `test_planet_sky.py`).
7. Rendered: measured fraction of dark pixels inside the Sun disc = server `obscuration` ± 0.05; `_sun.light_energy` ratio = `1 - obscuration` ± 0.02.

## Tests to add
- `tests/test_solar_eclipse.py::test_oulu_2026_partial`, `test_zaragoza_2026_total`, `test_helsinki_2025_partial`, `test_no_eclipse_next_day`, `test_obscuration_matches_integration`, `test_offline` - all fail today (no module).
- Scenario `eclipse_partial_oulu_2026`: Oulu centre, `start_time` 2026-08-12T20:45 (EEST), clear, camera at Sun az ~305 grid; `requires.solar_eclipse: {phase: "partial", min_obscuration: 0.75, sun_dark_fraction: [0.75, 0.9]}`. Readiness fails if state inactive or the Sun disc has no dark bite.
- Scenario `eclipse_total_forced`: same pose with a test-only server override of the eclipse state to total (Finland has no totality before 2126); requires no Sun-disc pixels, a corona ring and `light_energy < 0.01`.

## Out of scope
- Lunar eclipses (Earth's shadow on the Moon, reddening) - later.
- Shadow bands, Baily's beads, prominences, local terrain shadow cone, refraction.
- Planet/star occultation by the Moon (already masked by the disc).
