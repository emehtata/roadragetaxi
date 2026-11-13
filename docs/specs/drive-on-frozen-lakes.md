# Drive on frozen lakes (ice-thickness model)

## Goal
Lake/sea ice carries the taxi when its modeled thickness at this date and latitude reaches the car threshold;
thinner ice sinks the car. Replaces the fixed Jan-Feb idea and the `fields_frozen` bool gate (commit 44c3b4c2).

## Verified current code
- `physics.py:531` `water_ahead_speed_limit(car, waters, frozen: bool, ...)`, `:558` `water_sinks_car(car, waters, current_way, frozen: bool, dt, ...)`;
  `ICE_MONTHS` is already gone. River rule: `RIVER_KINDS`, `RIVER_ICE_BREAK_PER_S = 0.3` (`:521-522`).
- `simulation.py:521` and `:593-594` pass `getattr(world, "fields_frozen", False)`; `:543` passes it to grip (`physics.py:2055` sets ice ground on water).
- `server/__init__.py:634` `fields_frozen = look.winter >= FIELDS_FROZEN_WINTER_WEIGHT`; FMI snow at `:638` (`observed.snow_depth_cm`), test override `_test_snow_depth`.
- `climate.py:80` `typical_daily_mean_temperature(day, latitude)`; `calendar.latitude` exists.

## Model (`climate.py`, new)
Stefan's law: h = k·sqrt(s·FDD), k = 3.3 cm/sqrt(°C·day) (Pääjärvi, Finland; Wikipedia "Stefan's equation"),
s = snow factor on FDD (1.0 clear ice, 0.5 under snow: snow roughly halves growth, so ~2x FDD for the same h).
Integrated daily from 1 Sep of the ice season to the game date, T = `typical_daily_mean_temperature(d, lat)`:
- T < 0: h = sqrt(h² + k²·s·(-T))   (incremental Stefan; FDD counts from the first sub-zero day automatically)
- T >= 0: h = max(0, h - MELT_CM_PER_DEGREE_DAY·T), MELT_CM_PER_DEGREE_DAY = 0.5 (choice: simple degree-day erosion; h=0 is the reset).
- s = 0.5 by default (climatological snow); s = 1.0 when the observed/test snow depth for today is 0 cm. ponytail: today's snow applied to the whole season; per-day FMI history if it matters.
Worked example: 20 cm clear needs FDD = (20/3.3)² ≈ 37 °C·day; with snow (s=0.5) ≈ 73 °C·day.
With the climate model and s=0.5: lat 67.5 reaches 20 cm ~26 Nov and stays above until ~mid-May (80 cm late Mar);
lat 60.2 reaches 20 cm ~27 Dec, peaks ~44 cm in March, gone by ~20 Apr.

Signature: `lake_ice_thickness_cm(day: date, latitude: float, snow_factor: float = 0.5) -> float` (≤ 273 iterations, pure).
Threshold: `CAR_ICE_MIN_CM = 20.0` in `physics.py`, comment: choice for a ~1.5 t car; Minnesota DNR 20-30 cm small car,
Alberta 18 cm for 2 t; Finnish guidance 15 cm is snowmobiles only. Tune here.

## Server state
One value per world, not per lake: `world.lake_ice_cm`, recomputed in `season_weights` only when the game date
or snow factor changes (cached key `(date, snow_factor)`). All lakes in a loaded map share the calendar latitude, so per-lake
accumulators would be identical. The season integral replaces an accumulator, so time jumps/loads need no reset logic.
`world.lake_ice_holds = world.lake_ice_cm >= CAR_ICE_MIN_CM`.

## Files to change
- `climate.py`: `lake_ice_thickness_cm` + constants (k, melt).
- `physics.py`: `CAR_ICE_MIN_CM`; parameter `frozen` renamed `lake_ice_holds` in both functions (logic unchanged: lakes/sea hold, rivers keep break rule).
- `server/__init__.py`: set `world.lake_ice_cm`, `world.lake_ice_holds`; send `lake_ice_cm` in the snapshot next to `fields_frozen` (`:707`).
- `simulation.py:521,594`: pass `world.lake_ice_holds`; `:543` grip-on-water uses `lake_ice_holds` (land still uses `fields_frozen`).
- Godot water shader: ice look driven by `lake_ice_holds` instead of `fields_frozen`. Ground/snow weights unchanged.

## Acceptance criteria
1. `lake_ice_thickness_cm(date(2025,11,28), 67.5) >= 20` and `water_sinks_car(..., lake_ice_holds=True)` is False on a lake.
2. `lake_ice_thickness_cm(date(2025,11,28), 60.2) < 20`; car on that lake sinks; assist brakes before it.
3. `lake_ice_thickness_cm(date(2026,5,5), 67.5) >= 20` (leftover spring ice, drivable).
4. Thin ice: any (date, lat) with h < 20 -> sinks; `lake_ice_thickness_cm(date(2026,7,1), 67.5) == 0`.
5. `snow_factor=1.0` gives a larger h than 0.5 on the same date; worked example: FDD 37 clear ≈ 20 cm (±0.5).
6. River under holding ice still brakes and can break (`rng=lambda: 0` -> sinks).
7. Visual: lake renders as ice iff `lake_ice_holds`; the taxi stands on it with no sink countdown.

## Tests to add
- `tests/test_climate.py::test_lake_ice_north_late_november_holds`, `::test_lake_ice_south_late_november_thin`,
  `::test_lake_ice_north_may_leftover`, `::test_lake_ice_summer_zero`, `::test_stefan_worked_example` (fail: function missing).
- `tests/test_is_on_road.py::test_lake_ice_holds_drivable_thin_ice_sinks`, `::test_river_ice_still_breaks` (rename existing frozen tests).
- `tests/test_server*.py::test_season_weights_sets_lake_ice_by_latitude` (north vs south calendar on 28 Nov).
- Visual scenario `frozen_bay_north_late_november` in `tools/visual_scenarios.json` (clone of the frozen bay scenario, date 2025-11-28,
  northern map data), taxi on ice via `--screenshot-drive 3`; counts only when readiness checks pass (docs/visual-testing.md).

## Commands
- `make check`
- `XDG_DATA_HOME=$(mktemp -d) make godot-test`
- `godot-shot` on the scenario above; inspect PNG + JSON (`lake_ice_cm`, no water countdown).

## Out of scope
Per-lake latitude/size/current differences, slush and cracks, load-dependent sinking speed, NPCs on ice, Godot-side collision.

## Status
- Tester verdict: VERDICT: PASS. Criteria 1-7 met.
- Screenshots (`visual-test-results/`):
  - Oulu, `frozen_bay_north_late_november`, commit 2e8a63ea: `2025-11-28T1200_20261113-195037_2e8a63ea-dirty/screenshot.png`
  - Oulu, same scenario, commit fdbeb061: `2025-11-28T1200_20261113-200029_fdbeb061-dirty/screenshot.png`
  - Helsinki, `frozen_pond_snowless_winter_taxi_on_ice`, commit fdbeb061: `2026-01-15T1200_20261113-195714_fdbeb061-dirty/screenshot.png`
- Follow-up (not blocking): streamed-in chunks can show stale snow in 3D ground. `chunk.setup()` builds the 3D ground
  before `set_season`, and `_refresh_3d_ground` returns early when the chunk is not in the tree. Fix: set `_season`
  before `setup`, as already done for ice.
