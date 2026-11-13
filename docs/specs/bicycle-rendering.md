# Bicycle rendering: one head lamp, one rear lamp

## Goal
In the 3D view, ridden bicycles look like bicycles: a frame, two wheels and a rider, with one
white lamp at the front and one red lamp at the back. Right now they show car-style lamp pairs at both ends.

## Current behaviour and cause
- `godot/entity_layer.gd:902-906` sends every kind in `VEHICLES_3D` (bicycle included) to `Buildings3D.vehicle()`.
- `godot/buildings_3d.gd:1085-1089`: bicycle has a GLB model (`bicycle.glb` / `mountain_bike`, :509), so it goes through
  `place_model_car` + `model_car_details(length, width, 0, lamps, 0.8, kind in ["truck","motorcycle","camper_van"])`.
- `bicycle` is not in that `native_lights` list, so `model_car_details` (:969-993) adds a **car lamp set**: 2 headlights at
  ±hw*0.68 (each 0.20 m wide) at the front, 2 tail lights at the back, reverse lamps and 4 indicators. On a 0.62 m bike
  these lamps cover the whole width at both ends, so the bike reads as "two lights both ways".
- `headlight_sources()` (`entity_layer.gd:555`) also gives riding NPC bikes a car headlight **pair** (width_m spacing).
- The procedural fallback (:1220) and the 2D drawing (`entity_layer.gd:911`) are already bike-shaped; leave them as they are.

## Design (reference: low-poly side and top views of a diamond-frame bicycle)
- Proportions stay as they are (server `length_m`/`width_m`; model sizes at :524): wheelbase ~1.05 m, wheels 0.66–0.7 m, bars ~0.6 m.
- Lamps: one front lamp, 0.06 m wide, at x = +hl*0.80, height 0.85 m (under the bars), centred (z = 0). One rear lamp,
  0.05 m wide, at x = -hl*0.80, height 0.75 m (under the saddle), centred. No reverse lamps or indicators.
- Colours follow the existing bits: front lit `LAMPS_ON` warm white, otherwise grey; rear `LAMPS_ON` dim red,
  `LAMPS_BRAKE` bright red (same colours as cars).
- Light beam: a bike gives at most one narrow spot, centred, never a pair.

## Files to change
- `godot/buildings_3d.gd`: add `static func _bike_lamps(out: Dictionary, hl: float, lamps: int) -> void`. For
  `kind in ["bicycle","e_scooter"]`, call `model_car_details` with native_lights = true, skip its indicator and reverse
  lenses (new param `two_wheeler := false`), then call `_bike_lamps`. The procedural `"bicycle"` branch (:1220) calls it too.
- `godot/entity_layer.gd`: in `headlight_sources()`, a source whose kind is in `TWO_WHEELERS` gets a single centred beam
  (flag in the vehicle entry). The set_headlights consumer reads that flag.
- `tools/visual_scenarios.json`: reuse `vehicle_lineup_bikes_night`. Add `vehicle_bike_riding_night`: one NPC cyclist
  riding on a Helsinki-centre road at night, zoom close.

## Acceptance criteria
1. `model_car_details` arrays for a riding bicycle contain exactly 2 LAMP-part boxes (1 front, 1 rear), both |z| < 0.05.
2. A car (`sedan`) still gets its 2+2 lamps and its indicators (the test fails if the car path changes).
3. For a riding bicycle, `headlight_sources()` returns at most one entry, centred on the bike.
4. In `vehicle_bike_riding_night` and `vehicle_lineup_bikes_night` (readiness checks passed), each bike shows a frame,
   two wheels in line and a rider, with one white point at the front and one red point at the back. Inspect the screenshot.
5. `vehicle_bike_close_day` looks the same as before, apart from the small unlit lamps.
6. `make check` and `XDG_DATA_HOME=$(mktemp -d) make godot-test` pass with no tests deselected.

## Tests to add
- `godot/tests/run_tests.gd`: `test_bicycle_lamps_single_pair`. It fails now because there are 4 lamp lenses plus indicators.
- `godot/tests/run_tests.gd`: `test_bicycle_headlight_single_beam`. It fails now because a bike gets a beam pair.

## Commands
    make check
    XDG_DATA_HOME=$(mktemp -d) make godot-test
    tools/godot-shot --scenario vehicle_bike_riding_night   # then vehicle_lineup_bikes_night, vehicle_bike_close_day

## Out of scope
New bike meshes, 2D top-down drawing, motorcycle lamps, any server/simulation changes (lamp bits already come from the server).

## Status
- Implemented in a7562c0f, 14bc6450, 1d406951. Tester verdict: VERDICT: PASS.
- Screenshots (one front and one rear light, inspected):
  `visual-test-results/vehicle_bike_riding_night/2026-10-20T2230_20261113-214938_1d406951-dirty/screenshot.png`,
  `visual-test-results/vehicle_lineup_bikes_night/2026-10-20T2230_20261113-215103_1d406951-dirty/screenshot.png`.
- Gap: AC5 (daytime `vehicle_bike_close_day` unchanged) was not re-run for this verdict.
