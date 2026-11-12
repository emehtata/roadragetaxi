# HUD weather label shows cloudiness

## Goal
With no precipitation the HUD weather line says "Selkeää" even under full
overcast. Make it pick clear / partly cloudy / overcast from `weather.cloud_cover`.

## Files to change
- `godot/i18n.gd`: add `weather_partly_cloudy` and `weather_overcast` to FI, EN
  and DE, next to `weather_clear` (fi "Puolipilvistä"/"Pilvistä",
  en "Partly cloudy"/"Overcast", de "Teilweise bewölkt"/"Bedeckt"). Add
  `static func sky_weather(weather_type: String, cloud_cover: float) -> String`
  that returns the key suffix (`clear`, `partly_cloudy`, `overcast` or
  `weather_type` unchanged).
- `godot/hud.gd:277`: pass
  `T.weather(T.sky_weather(type, float(weather.get("cloud_cover", 0.0))), language)`
  into `road_wet`. The wetness part stays as it is.
- `src/theroadragetrip/localization.py`: add the same two keys (fi/en/de) next
  to `weather_clear` so server and client tables match. The choice stays on the client.
- `tools/visual_scenarios.json`: add three HUD scenarios (dry, cloud 0.1 / 0.5 / 0.9),
  copying an existing day scenario that uses the `cloud` field.

## Behaviour / acceptance criteria
1. `weather_type` rain, slush, snow, thunderstorm: label unchanged whatever the cloud_cover.
2. `clear` with cloud_cover >= 0.8: "Pilvistä" (fi), "Overcast" (en), "Bedeckt" (de).
3. `clear` with 0.3 <= cloud_cover < 0.8: "Puolipilvistä" / "Partly cloudy" / "Teilweise bewölkt".
4. `clear` with cloud_cover < 0.3, or cloud_cover missing: "Selkeää" / "Clear" / "Klar".
5. HUD line format stays `"<label>, tie N% märkä"`.
6. The forecast rows (main.gd:1295) do not change; they have no cloud_cover per row.
7. A rendered HUD screenshot for each of the three scenarios shows the right
   label, and the scenario's readiness checks passed (docs/visual-testing.md).

## Tests to add
- `godot/tests/run_tests.gd` `test_hud_weather_cloudiness`: checks
  `T.sky_weather` at 0.0, 0.29, 0.3, 0.79, 0.8, 1.0 for `clear` and at 1.0 for
  `rain`, and checks the fi strings through `T.weather`. Without the fix it
  fails at 0.3 and above, which still give `clear`.
- `godot/tests/run_tests.gd` (existing i18n key-parity check, if there is
  one, otherwise in the same test): the new keys exist in FI/EN/DE.
- Python: extend the existing localization key-parity test, if there is one,
  so it covers the new keys.
- Run with `XDG_DATA_HOME=$(mktemp -d)`.

## Out of scope
- Server weather model, FMI parsing, cloud regimes.
- Cloudiness in the forecast panel rows.
- Fog/mist labels.
- The uncommitted vehicle/LOD/sky changes in the working tree: do not touch or revert them.
