# Frozen water in snowless thermal winter

## Goal
Lakes, ponds and rivers draw as ice whenever it is thermal winter, even with
0 cm snow, the same way sports fields already freeze (`fields_frozen`).

## Current behaviour (verified)
- `server/__init__.py` `season_weights()` sets `world.fields_frozen` from the
  thermal look (`look.winter >= FIELDS_FROZEN_WINTER_WEIGHT`) *before*
  `appearance_with_snow_depth` overrides `look`; `season[0]` is therefore 0
  on a snowless winter day (e.g. Kemijärvi 2026-11-13, -3.1 °C, 0 cm).
- The client already receives `calendar.fields_frozen` (`main.gd:892` ->
  `map_layer.set_fields_frozen` -> `map_chunk.set_fields_frozen`, which
  redraws `_season_layers`, incl. water and shore, and the 3D ground).
- `map_chunk.gd` takes ice only from `_season[0]`: `_draw_water` (~1326),
  `_draw_shore_waves` (~1316), 3D water areas (~792).

## Design
No new server value: `fields_frozen` already is the thermal-winter ice flag.
Add one helper in `godot/map_chunk.gd`:
`func water_ice() -> float` = `maxf(clampf(_season[0], 0, 1), 1.0 if fields_frozen() else 0.0)`
and use it in the three places above instead of `_season[0]`.
Ground snow, trees, buildings, pitch lines keep using `_season[0]`.

## Files to change
- `godot/map_chunk.gd`: add `water_ice()`; use it in `_draw_water`,
  `_draw_shore_waves`, and the 3D water areas block.
- `godot/tests/run_tests.gd`: Godot test below.
- `tests/test_server_headless.py` (or where `fields_frozen` is tested): Python test.

## Acceptance criteria
1. Server: thermal-WINTER date with observed snow depth 0 -> `season_weights()[0] == 0`
   and `world.fields_frozen is True` (and state `calendar.fields_frozen` true).
2. Server: summer date -> `fields_frozen` false.
3. Client: chunk with `_season = [0,0,0,1]` and `set_fields_frozen(true)` ->
   `water_ice() == 1.0`; water colour equals the ice colour `Color8(232,240,244)`;
   shore waves not drawn (liquid 0).
4. Client: `set_fields_frozen(false)`, `_season[0] = 0` -> `water_ice() == 0`, open water.
5. Client: 3D water area for frozen chunk uses the ice colour and is not flagged liquid.
6. Rendered screenshot (godot-shot / visual scenario per docs/visual-testing.md,
   readiness checks passed) of a pond on a snowless thermal-winter date shows
   white-grey ice, while ground stays snowless. Add a scenario to
   `tools/visual_scenarios.json` from real map data if none fits (use
   city-centre coordinates, not home-area ones).

## Tests to add
- `tests/test_server_headless.py::test_snowless_thermal_winter_freezes_fields`
  (criteria 1-2; guards the snow override from leaking into `fields_frozen`).
- `godot/tests/run_tests.gd` `test_water_freezes_in_snowless_thermal_winter`
  (criteria 3-4); fails today because `_draw_water` ignores `fields_frozen`.

## Tests to run
- `make check`
- `XDG_DATA_HOME=$(mktemp -d) make godot-test`

## Out of scope
- Gradual ice-up/thaw (ice is binary on the 0.5 thermal threshold).
- Ice physics/driving on lakes; snow on ice; changing the 4-weight season array.

## Status
- Tester verdict: VERDICT: PASS (partial).
- Criterion 5 (3D ice water area) is verified by code reading only. The windshield
  screenshot shows just a sliver of water, so it is not visual proof.
- Revert-proof result: not recorded in the tester report handed to ship; needs a rerun
  to confirm the new tests fail without the fix.
- 2D screenshot (criterion 6): visual-test-results/frozen_pond_snowless_winter/2026-01-15T1200_20261113-181352_197b1f87-dirty/screenshot.png
- Windshield screenshot: visual-test-results/frozen_pond_snowless_winter_windshield/2026-01-15T1200_20261113-181837_197b1f87-dirty/screenshot.png
- Build used for screenshots is 197b1f87, which predates 0b2c3af8 (wider view and windshield variant commit).
