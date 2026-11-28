# Planet sky: Mercury to Uranus

Mercury, Venus, Mars, Jupiter, Saturn and Uranus are drawn as unresolved points in the existing 3D sky shader at their real positions and brightness. The Python server computes them for the authoritative game time and the actual observer (car or on foot); Godot only turns six directions and six magnitudes into six display levels. Earth is the observer; Neptune and Pluto are out of scope.

## Provider decision

Reference: sibling `sky-api` commit `10ad0a3` (`app/providers/skyfield_provider.py`: `compute_current_ephemeris()`, `check_body_altitudes()` with `(earth + wgs84.latlon(...)).observe(...).apparent().altaz()`, inner planets by body and outer planets by barycentre). No code is imported or copied, and its HTTP API is not called; its `datetime.now()` and fixed observer are not used.

Measured (`tests/data/planet_sky_reference.json`, 53 cases over 2020-2040 at four Finnish sites incl. DST gaps/folds and dusk/dawn horizon crossings, produced by `tools/build_planet_reference.py` from Skyfield 1.55 + JPL DE421, airless apparent alt/az):

| Check | PyEphem 4.2.1 (VSOP87, already a dependency) | Skyfield + DE421 |
| --- | --- | --- |
| Worst angular error above 10 degrees | 0.013 degrees (Uranus), 0.012 Mars, 0.004 Saturn, 0.001 Venus, 0.0002 Jupiter, 0.0001 Mercury | reference |
| Visual magnitude | built in; worst difference to Skyfield/Mallama 2018: Mercury 0.54, Venus 0.50, Mars 0.19, Jupiter 0.16, Saturn 0.07, Uranus 0.03 | `planetary_magnitude` |
| Offline Windows packaging | compiled wheel, no data files, no download, already in the release | ~17 MB kernel plus timescale/leap-second files to bundle, hash and keep current |
| Cost | 0.165 ms per uncached six-body state, 4 microseconds cached | similar plus kernel reads |

PyEphem meets the 0.1-degree requirement by a factor of 7, so it is selected; Skyfield and DE421 are used only offline to generate the fixtures and are never loaded by the game. Loading cannot trigger a download: `planets.py` imports no network module and `tests/test_planet_sky.py` computes with sockets blocked. Magnitude tolerances per model (PyEphem vs the Skyfield/Mallama 2018 fixture): Mercury 0.6, Venus 0.55, Mars 0.25, Jupiter 0.2, Saturn 0.1, Uranus 0.05 magnitudes.

## Coordinates and state

`calendar.planet_sky` sits beside `calendar.star_sky`:

```
{supported, utc, observer: [lat, lon, elevation_m], source, reason?,
 bodies: [{id, alt, az, mag, dir: [x, y, z]} | {id, unavailable}]}   # mercury, venus, mars, jupiter, saturn, uranus
```

`calendar.current` (Finnish local, DST/fold handled by `finnish_utc`) gives UTC. The observer is the car or the walker, converted with the existing EPSG:3067 transform, with the DEM ground height (0 without a DEM; heights outside -500..9000 m are ignored). PyEphem returns airless apparent topocentric altitude and true azimuth (`pressure = 0`); the azimuth becomes a grid azimuth through the existing convergence (`grid_azimuth`). `dir` is the unit vector in Godot axes: +X east, +Y up, -Z grid north. The directions are apparent and topocentric, not precessed again through the J2000 star basis.

Supported 2020-2040 (inside the VSOP87 validity and the reference range). Another year, an invalid or non-finite coordinate, a non-finite body or a provider exception produces `supported: false` with a `reason` (or a body with `unavailable`), one logged warning and no coordinates; the game continues and Godot hides the body. Atmospheric refraction is omitted (airless convention for all fixtures); the sky shader instead fades each planet over 0-5 degrees of altitude and draws nothing below the horizon.

## Cache

`lru_cache(maxsize=128)` on `(10-second UTC bucket, latitude and longitude rounded to 0.0001 degrees, elevation rounded to 10 m)`: every provider input is in the key, so travel, a car/on-foot switch, a hill, a time jump, a save load or the second pass through a DST fold miss and recompute, while the same bucket is served from memory. The ten-second bucket costs at most 10 s of Earth rotation (0.042 degrees). No kernel is read per tick and Godot does no astronomy per frame: `set_planets` re-evaluates only when the UTC, observer, pollution or Sun/Moon inputs change (`game-mechanics-optimizations/04_dirty_flags.md`).

## Rendering

One fixed `vec4 planet_dir[6]` (direction and display level) and `vec3 planet_color[6]` in `sky_clouds.gdshader`, outside the radiance cubemap pass: no planet nodes, lights, generated textures or per-frame allocations, shared across all pixels (`41_2d_sprite_batching.md` principle, no 2D path). Each planet is a Gaussian of 0.8 pixels sigma measured with `dFdx(EYEDIR)`, so a planet is a small antialiased point of constant pixel size at every resolution and FOV (including 8x binoculars) and never a disc, ring or surface. It is added behind the clouds, so overcast hides it, and masked by the opaque Sun and Moon discs; below the horizon the sky branch is not reached. No light is added to the world.

Display brightness: `flux = 0.12 * 2.5118864^((6 - mag) / 2)` (the stars' 0.2 dex per magnitude slope) compressed to `flux / (1 + flux)` so Venus (about 0.93) never clips to white and the order Venus > Jupiter > Saturn/Mars/Mercury > Uranus is strictly monotonic. Footprint limit: one point, about 3-5 pixels above 10 percent of peak, checked at 320x180 to 1280x720 and 5 to 75 degrees FOV.

Colour: the naked-eye colour of a reflected-sunlight point is its broadband B-V. B-V values come from Mallama, Krobusek and Pavlov 2017, *Comprehensive wide-band magnitudes and albedos for the planets* (Icarus 282, doi 10.1016/j.icarus.2016.09.023, arXiv 1609.05048), Table 3 reference magnitudes (B minus V; the Sun is 26.10 - 26.75 = 0.65): Mercury 0.97, Venus 0.70, Mars 1.36, Jupiter 0.86, Saturn 1.07, Uranus 0.50. B-V gives a blackbody temperature (Ballesteros 2012), the CIE 1931 chromaticity (Wyman, Sloan and Shirley 2013 analytic fit) gives linear sRGB, and the Sun's white is balanced to 1: Venus (1.00, 0.98, 0.95) almost white, Jupiter (1.00, 0.92, 0.80) cream, Mercury (1.00, 0.88, 0.71) pale yellow, Saturn (1.00, 0.84, 0.64) yellow, Mars (1.00, 0.75, 0.47) orange, Uranus (0.85, 0.90, 1.00) pale blue-green. `tests/test_planet_sky.py::test_colours_follow_published_b_minus_v` recomputes them and fails on drift; the native test and readiness measure the rendered pixels against them.

## Visibility

`PlanetSky.limiting_magnitude` replaces the stars' night multiplier: the dark-sky limit by solar altitude (smooth, piecewise by smoothstep through -18: 6, -12: 4, -6: 1.5, 0: -3, +6: -5), reduced by the same local pollution and Moon-light losses as the stars (6 minus the stars' limit). A planet is drawn once its magnitude is below the limit (fully 0.4 magnitudes inside it), times a 0-5 degree horizon fade. Faint planets therefore go first (Uranus at pollution 1, Mercury before Venus), bright Venus survives sunset and Jupiter civil twilight, the day sky (+6 degrees and above) hides all, and nothing is drawn below the horizon. Clouds, full overcast, terrain/buildings in the 3D layers and the Sun/Moon discs occlude. A server without `planet_sky` (older save or server) gives an empty state and the layer stays hidden.

## Sources, rights and reproduction

- PyEphem (MIT, rhodesmill.org/pyephem): runtime provider, already bundled and in `tools/license_inventory.json`; displayed credit `credits_planet_sky` in Finnish, English and German (Credits screen).
- Fixtures: Skyfield 1.55 (MIT) with JPL DE421 (NASA/JPL, US-government public data); only numbers derived from them are stored in `tests/data/planet_sky_reference.json`; nothing of Skyfield, the kernel or its timescale files ships. Rebuild: `python -m venv /tmp/sf && /tmp/sf/bin/pip install skyfield==1.55 skyfield-data==7.0.0 && PYTHONPATH=src /tmp/sf/bin/python tools/build_planet_reference.py`.
- Colours: B and V reference magnitudes (facts) from the paper above; citation only, no text or figure is reproduced.
- Sibling sky-api commit `10ad0a3`: only the call pattern was inspected; no code or data reused, so no sibling licence applies.

## Native scenarios and evidence

Ten real-map scenarios (`tools/visual_scenarios.json`, ids `planets_*`) were chosen from the computed ephemerides and passed on native Windows Godot 4.7.2, Forward+ on Vulkan, NVIDIA GeForce RTX 5060 at 1280x720 on 27-28 November 2026 (frozen game dates inside the last year; rural scenarios share the pinned rural test segment of `stars_dark_rural_night`, city scenarios the segment of `stars_city_night`). Readiness requires the ordinary map readiness, planet UTC/observer/source equal to the star state, pollution in range, then paired planet-on, planet-off and forced renders of the 3D view and of the window the screenshot shows; a visible planet needs linear contrast above 0.015 in both and its rendered colour within 0.2 of its table colour; a hidden control needs zero contrast and, forced at its own brightness under a cloudless override, contrast in both images (so terrain, buildings or the HUD do not hide it and the control cannot pass falsely), except below the horizon where forced contrast must stay zero. Normal rendering is restored before capture. Measured (contrast of the 5x5 peak, 0-1 linear; screen position in the 1280x720 window):

| Scenario (local time) | Body, magnitude, altitude | Screen px | Contrast | Forced | Rendered colour (expected) |
| --- | --- | --- | ---: | ---: | --- |
| `planets_dark_rural_uranus` 2026-09-08 02:00 | Uranus 5.68, 29.5 | 632,371 | 0.087 | 0.099 | 0.84 0.89 1.00 (0.85 0.90 1.00) |
| `planets_dark_rural_outer` 2026-11-15 01:00 | Mars 0.72, 16.6 | 494,414 | 0.363 | 0.363 | 1.00 0.75 0.47 (1.00 0.75 0.47) |
| | Jupiter -1.95, 15.4 | 505,441 | 0.583 | 0.583 | 1.00 0.91 0.80 (1.00 0.92 0.80) |
| `planets_rotated_view` same time, camera turned | Uranus 5.59, 46.1 | 640,215 | 0.115 | 0.115 | 0.85 0.90 1.00 |
| `planets_time_shift` 02:00, same camera as outer | Mars, 22.9 | 801,263 | 0.402 | 0.402 | 1.00 0.75 0.46 |
| | Jupiter, 21.8 | 814,290 | 0.630 | 0.630 | 1.00 0.92 0.81 |
| `planets_twilight_inner` 2026-11-15 08:00, Sun -4.7 | Mercury 0.27, 7.6 | 502,414 | 0.527 | 0.527 | 1.00 0.87 0.71 (1.00 0.88 0.71) |
| | Venus -4.35, 11.9 | 788,314 | 0.856 | 0.856 | 1.00 0.98 0.94 (1.00 0.98 0.95) |
| `planets_urban_bright` 2026-09-24 04:30, pollution 1, limit 2 | Saturn 0.35, 25.2 | 635,353 | 0.434 | 0.434 | 1.00 0.85 0.64 (1.00 0.84 0.64) |
| `planets_urban_faint` 2026-11-09 03:30, pollution 1, limit 2 | Uranus 5.59, 44.2 (hidden) | 647,353 | 0.000 | 0.110 | - |
| `planets_below_horizon_control` 2026-11-15 04:00 | Venus -4.35, -9.2 (hidden) | 753,373 | 0.000 | 0.000 | - |
| | Mercury 0.31, -15.6 (hidden) | 491,526 | 0.000 | 0.000 | - |
| `planets_day_control` 2026-06-20 13:00, limit -5.1 | Venus -3.95, 36.2 (hidden) | 483,393 | 0.000 | 0.700 | - |
| | Jupiter -1.67, 40.6 (hidden) | 704,295 | 0.000 | 0.659 | - |
| | Mercury 0.86, 42.7 (hidden) | 806,238 | 0.000 | 0.430 | - |
| `planets_overcast_control` cloud 1 | Mars (hidden) | 494,414 | 0.000 | 0.363 | - |
| | Jupiter (hidden) | 505,441 | 0.000 | 0.584 | - |

All six bodies are covered: Mercury and Venus (twilight), Mars and Jupiter (outer, time shift, overcast control), Saturn (city), Uranus (rural, rotated, city control). The time shift moves Mars from (494,414) to (801,263) and Jupiter from (505,441) to (814,290) over one hour with the same camera. Every accepted screenshot was inspected and the faint and low points were enlarged: points of 1-2 pixels, Mars orange, Jupiter and Venus near white, Mercury pale yellow, Saturn yellow, Uranus blue-green; the controls show a plain day sky, a horizon with nothing above it, a flat overcast sky and a city sky with a building and no planet. Existing controls rerun on the same build: `stars_dark_rural_night` 108 stars (82 faint), `stars_time_shift_night` 120 (82), `stars_city_night` 1 (0), `stars_overcast_night` 0, `stars_day_control` 0, the gibbous-Moon scenario passed with the lunar disc intact; the native `moon_phase.gd` and `star_sky.gd` tests pass.

## Profile (native Windows, same pose, date, weather, resolution and 8 s measurement, 30 s warmup)

Baseline is commit `06f5656a` in a separate worktree with only the scenario file copied; values are frame milliseconds. `planets_profile_rural` is `planets_dark_rural_outer`, `planets_profile_city` is `planets_urban_bright`.

| View | Version | p50 | p95 | p99 | Worst | Draw calls | 3D GPU ms | VRAM MiB | Static MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rural | Before | 3.288 | 3.333 | 3.333 | 3.83 | 105 | 1.085 | 2984.4 | 293.4 |
| Rural | After | 3.333 | 3.704 | 3.704 | 7.25 | 105 | 1.110 | 2984.4 | 294.2 |
| City, 3 runs | Before | 8.5-11.1 | 11.1-12.5 | 14.3-16.7 | 44-59 | 400-407 | 1.05-1.19 | 4251.9 | 347.9 |
| City, 3 runs | After | 11.2-11.7 | 12.5-15.0 | 14.0-16.7 | 17-55 | 404-411 | 1.15-1.20 | 4242.4 | 349.1 |

No new draw calls (rural identical, city within the baseline's own 400-407 spread from moving traffic), no lights, no new resources (identical forest population: 78,515 rows rural, 825 city; VRAM equal), 3D GPU time +2 percent rural and inside the baseline range in the city. Rural p95 moved one 300 Hz frame quantum (3.333 to 3.704 ms, +11 percent; every percentile of both runs is within 0.4 ms). The city p95 mean rose from 11.8 to 13.6 ms (+16 percent) and p50 from 10.1 to 11.5 ms; this exceeds the 10 percent investigation threshold, so it was investigated: GPU time and draw calls did not move, the server adds 0.165 ms per ten game seconds (cache hit 4 microseconds, tick p99 well under 33 ms), tail frames above 33 ms fell from 6 to 1 across the runs, and the baseline's own run-to-run spread (p95 11.1-12.5, p50 8.5-11.1) overlaps the after range, so the measured difference is at the noise level of this machine and cannot be attributed to the planets with three runs. It is recorded as a measured quality/performance tradeoff, like the star layer's, with no low-end GPU measurement. A session restart or time jump creates no resources: `godot/tests/planet_sky.gd` runs 600 time jumps and three scene reloads with the node, material and object counts unchanged, and the server cache stays at its 128-entry bound.
