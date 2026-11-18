# Snowfall restarts GPU particles every frame (15 fps)

## Goal
Stop `Precipitation3D` from calling `particles.restart()` (full `preprocess =
lifetime` re-simulation) on every small intensity change; restore the frame
time from before commit 49cecd21.

## Evidence
Screenshot `screenshots/screenshot_1795011901188000000.png` and its JSON: Kemijärvi,
night, snow ("Lumisadetta"), top view, car parked. 15 fps, avg 39.7 ms, p99 97.5 ms,
yet only 181 draw calls, 8 chunks drawn, 0 queued, state 1.66 ms and
interpolate+draw 1.28 ms. The CPU is mostly idle, so the cost is on the GPU.
`buildings_3d.gd:_process` calls `_precip.set_weather()` every frame. In
`precipitation_3d.gd:set_weather`, any intensity change outside
`is_equal_approx` (the weather blend ramps it continuously) now ends in
`particles.restart()`, which re-runs about `lifetime` seconds of preprocess for
`MAX_PARTICLES` on each frame. Before 49cecd21, only setting `amount` reset the
particles, and only when the integer drop count changed.

## Files to change
- `godot/precipitation_3d.gd`: in `set_weather`, change `amount`/`lifetime`
  and call `restart()` only when `kind` changes or `drop_count()` changes. For
  intensity-only drift, update uniforms only. In `_process`, keep restarting
  only when `_update_volume()` reports a teleport or volume change.
- Optional: `set_weather(...) -> bool` returns whether it restarted (for tests).

## Acceptance criteria
1. While the kind and `drop_count()` stay the same, calling `set_weather` 60
   times with the intensity changing by 0.000001 per call restarts the particles
   0 times. (The step is 0.000001, not 0.001: a 0.001 step changes
   `drop_count()` on each call, which is a legitimate restart case, so the
   drift test must stay below that threshold.)
2. A change of kind (rain to snow, or "" to snow) restarts exactly once, and
   the sky is still full at once (preprocess kept).
3. When `drop_count()` changes, `amount` updates and the particles restart
   once.
4. A teleport of more than `extent` still restarts once (behaviour kept from
   49cecd21).
5. The perf counter `precipitation_3d` and the frame avg in the named scenario
   `snow_street_day` (and `audit_snow_night_windshield`) stay within 10% of the
   same scenario with weather off. The scenario readiness checks pass, and the
   screenshot shows the snow still falling.
6. `make check` passes with nothing deselected.

## Tests to add
- `godot/tests/precipitation_3d.gd`:
  `test_intensity_drift_does_not_restart`. Count restarts (through the return
  value or a counter) across 60 small intensity steps. Without the fix it
  counts 60.
- Same file: `test_kind_change_restarts_once`. Guards against
  over-correcting.

## Out of scope
- Collision heightfield resolution and `MAX_PARTICLES` tuning.
- The chunk_buildings_build stalls and the windows count (62k).
- Benchmarking native Windows GPU performance beyond the named scenarios.
