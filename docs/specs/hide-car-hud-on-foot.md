# Hide the car dashboard and rage meter on foot

## Goal
On foot the speedometer cluster (fuel gauge, odometer, trip, economy, K/V/N chips) and the rage
meter (Rattiraivo card with the driver portrait) are hidden; they return the moment the player is back in the taxi.

## Findings
- Client on-foot flag: `state["on_foot"]` (server snapshot); read as `state.get("on_foot", true)` in `godot/main.gd`
  (`_apply_state`, ~l.983-987) and `Hud.values()` in `godot/hud.gd` l.261.
- Both widgets are drawn by the one `Control` `$Ui/Instruments` (`godot/instruments.gd`, `_draw()` l.206):
  `_draw_speedometer` (cluster, fuel, odometer, trip, reset button), `_draw_rage`, plus the round limit sign and
  the in-water warning. `main.gd` l.987 calls `instruments.show_state(state)` every frame; l.505 hit-tests
  `instruments.trip_reset_rect` (a click on the hidden button must not reset the trip).
- `show_state` only redraws when its `values` array changes; `on_foot` is not in it.
- Water warning is on-foot-relevant (swimming), so it stays. The limit sign is a driving aid: hide it on foot.

## Files to change
- `godot/instruments.gd`: add `var on_foot := false`; `show_state` sets it from `state.get("on_foot", true)` and
  appends it to `values` (forces redraw on change); `_draw()` skips `_draw_speedometer`, `_draw_fuel`, `_draw_rage`
  and the limit sign when `on_foot`; when skipped, set `trip_reset_rect = Rect2()` and `cluster_rect = Rect2()`.
  Signature only: `static func shows_car_ui(state: Dictionary) -> bool`.
- `godot/main.gd`: no new state; guard l.505 is covered by the empty `trip_reset_rect`. Check other users of
  `instruments.cluster_rect` (grep) so an empty rect is safe (layout drag/grips in `hud_layout.gd`).
- `godot/hud.gd` l.47: `osm_credit` is offset left of the rage panel; keep as is (spec: credit stays, gap is harmless).
- `tools/visual_scenarios.json`: add `"checks"`/expect fields only if the readiness schema in `docs/visual-testing.md`
  needs them; otherwise reuse scenarios unchanged.

## Acceptance criteria
1. With `on_foot == true` the speedometer, fuel gauge, odometer, trip, economy line, chips, reset button and the
   rage meter are not drawn.
2. With `on_foot == false` all of them are drawn exactly as today (pixel-identical to `windshield_city_day` before the change).
3. Switching `on_foot` true to false (E at the door) and back redraws within one state update, no stale frame.
4. Stay visible on foot: phone, HUD messages/notices/subtitles, hint and the interaction prompt (taxi door, building,
   home door), the map and its signs, clock/money/weather, the tutorial, the in-water warning, pump readouts.
5. On foot the trip reset click (l.505) does nothing; the T key behaviour is unchanged.
6. Server and simulation untouched: no change under `src/`; the `on_foot` field is read-only on the client.
7. Default `on_foot` before the first state: dashboard hidden (matches `state.get("on_foot", true)`); no flash at start.

## Tests to add
- `godot/tests/run_tests.gd`, `test_instruments_hide_on_foot`: build `Instruments`, call `show_state` with
  `on_foot=true` then `false`; assert `cluster_rect`/`trip_reset_rect` empty then non-empty after a `_draw`
  (fails today: both always set). Also assert the `values` change triggers redraw on the flip alone.
- Same file, `test_instruments_water_warning_on_foot`: `water_elapsed > 0` and `on_foot` still draws the warning
  (guards criterion 4; drive via `shows_car_ui` plus a draw-path flag).
- Visual (AGENTS.md, `docs/visual-testing.md`): run `walk_building_prompt_day` (on-foot UI: no dashboard, no rage
  card, building prompt visible; also covers `walk_city_street_day`) and `windshield_city_day` (driver UI:
  dashboard and rage meter present). Inspect both screenshots and the JSON snapshot; readiness checks must pass.
  Run Godot with `XDG_DATA_HOME=$(mktemp -d)`; run the full Godot and Python suites.

## Out of scope
- Replacing the hidden cluster with on-foot widgets (stamina, health, items).
- Moving or re-laying out the remaining HUD, the OSM credit, or `hud_layout.cfg` saved positions.
- Hiding the HUD in the windshield view or in home interiors; changes to key bindings or the tutorial text.
- Any server, simulation, or save-format change.
