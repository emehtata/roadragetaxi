# Lake ice from observed weather

## Goal
Lake ice thickness follows the real FMI weather, not the climate curve. Oulu,
28 Nov 2026, after a mild autumn: about 0 cm of ice, and the car sinks.

## Verified current behaviour
- `climate.lake_ice_thickness_cm(day, lat, snow_factor)` grows ice from 1 Sep using
  only `typical_daily_mean_temperature`. At 65.0° N on 28 Nov it gives 15.1 cm with
  s=0.5. `server._update_lake_ice` sets s=1.0 when the observed snow depth is 0, which
  gives ~21 cm, so `lake_ice_holds` is true and the car drives on the lake. That is the
  user's case.
- `WeatherHistory` keeps hourly `temperature_c` and `snow_depth_cm` only for chunks
  that were requested. The server requests about now-6 h .. now+48 h, so the season
  since 1 Sep is not loaded.

## Files to change
- `src/theroadragetrip/climate.py`: add `lake_ice_from_daily(days: Iterable[tuple[float, float | None]]) -> float`.
  It takes (daily mean °C, snow cm or None) per day, oldest first, and applies the same
  per-day Stefan update and melt rule. `lake_ice_thickness_cm` keeps its signature and
  feeds it typical means with a constant snow factor, so it remains the fallback.
- `src/theroadragetrip/weather_history.py`: add `WeatherHistory.daily_means(start: date, end: date) -> list[tuple[date, float | None, float | None]]`.
  It returns observed (not forecast) daily mean temperature and mean snow depth, reading
  memory plus the sqlite cache without blocking. A day with fewer than 12 hourly
  temperatures gives None.
- `src/theroadragetrip/server/__init__.py`: change only `_update_lake_ice`, plus one
  `request(season_start, now)` made when the date changes. It builds the daily series
  from 1 Sep. For each day it uses the observed mean, or the typical mean if that day is
  missing. Snow factor per day: 0.5 if the observed snow is >= 1 cm, 1.0 if it is 0, and
  0.5 if it is unknown.
- `tests/test_climate.py` and `tests/test_lake_ice_observed.py` (new).

## Behaviour / acceptance
1. Ice grows only on days with a daily mean below 0 °C: h = sqrt(h² + k²·s·FDD_day),
   with k = 3.3. On thaw days it melts by 0.5 cm per °C·day. `CAR_ICE_MIN_CM` stays 20.
2. Observed days take priority over the climate curve day by day. With no observations
   at all (history None, or the visual tests with FMI disabled), the result equals
   today's `lake_ice_thickness_cm`, so the visual ice scenarios (Helsinki January, Oulu
   late November) still show ice.
3. Cache key: `(date, latitude, n_observed_days, round(sum of observed means, 1), snow-day signature)`.
   Ice is recomputed when new observed days arrive, and at most once per change, never
   on every frame.
4. Oulu (65.0° N) on 28 Nov, observed means from +6 down to -1 °C, 0 cm snow: under 1 cm
   of ice, `lake_ice_holds` is false, and `water_sinks_car` sinks the car on a lake.
5. Oulu on 28 Nov after 25 observed days at -8 °C: 20 cm or more, and the ice holds.
6. When the season history is missing, the server does no network I/O on the tick.
   `request()` only queues the fetch, and the ice moves from fallback toward the observed
   value as days load.

## Tests to add
- `tests/test_lake_ice_observed.py::test_mild_late_november_oulu_has_no_ice`: a fake
  WeatherHistory with mild days. It fails today, because the climate curve with 0 snow
  gives ~21 cm.
- `::test_freezing_late_november_oulu_holds`: 25 cold days give >= 20 cm.
- `::test_no_observations_falls_back_to_climate`: equals `lake_ice_thickness_cm`.
- `::test_ice_recomputes_when_observed_days_arrive`: adding days changes the key and
  the value.
- `tests/test_climate.py`: the existing lake ice tests stay unchanged and pass.
- Checks: `make check` and `XDG_DATA_HOME=$(mktemp -d) make godot-test`. Run one Oulu
  ice visual scenario per docs/visual-testing.md.

## Out of scope
- Ice per lake, effects of lake depth or size, and sea ice versus lake ice.
- Startup and transport files (the free-port work runs in parallel).
- Client rendering changes: it already follows `lake_ice_holds`.

## Status
- Tester verdict: PASS. `make check` on this tree: 2845 passed, 2 skipped; timing marker 61 passed.
- Revert proof: with the new tests run against the old code, 3 of 4 fail
  (`tests/test_lake_ice_observed.py`), as the Behaviour section predicts for the mild-Oulu case.
- Observed path: checked against the real history cache with the fetch disabled, so the
  observed days come only from cached data. No network I/O on the tick.
- Open gaps (not blocking):
  (a) `water_sinks_car` is not exercised by a new test directly. It reads `lake_ice_holds`, which is tested.
  (b) No visual scenario for the observed-weather path. Visual tests disable FMI history, so Oulu/Helsinki ice scenarios cover only the fallback.
  (c) If `request()` is skipped by `_retry_after`, observed data is not retried until the next date. Ice stays on fallback or partial data until then.
