# E-scooter in the top-down view

## Goal
From above, an e-scooter should read as a scooter with a rider: one white front
lamp at the stem/handlebar and one red rear lamp at the deck tail, not car lamps.

## Finding
- The user's info panel confirms the object is an NPC e-scooter. It is the
  small object next to the taxi, with a grey stem and deck, a rider, and two
  RED lamps on the handlebars.
- The top-down view is 3D-opaque. `Buildings3D.vehicle()`
  (godot/buildings_3d.gd ~972) treats `e_scooter` as `modelled`. It places
  `e_scooter.glb` and adds `model_car_details(length, width, 0, lamps, 0.8, false)`.
  That routine makes a car's paired head lenses at `+hl`, paired red tail
  lenses at `-hl` (each 0.20 m wide, at ±0.68·hw), reverse lamps and corner
  indicators.
- Red lamps showing at the handlebars means the glb's stem points to `-hl` in
  the details frame. The model and the lamp frame are flipped relative to each
  other, and possibly relative to the heading. Check which way the scooter
  travels before fixing.

## Files to change
- `godot/buildings_3d.gd`, `vehicle()`: for `e_scooter`, skip
  `model_car_details`. Build a scooter-specific details mesh instead:
  - one white/warm front lamp, centred and no wider than `width * 0.32`, at the
    stem end of the model
  - one red rear lamp, centred and the same width limit, at the deck tail
  - the red rear lamp brightens with `LAMPS_BRAKE`; the front lamp is lit
    with `LAMPS_ON`
  - keep the rider
  - if the glb faces opposite to the heading, fix the yaw for `e_scooter` in
    `place_model_car` so the stem leads in the direction of travel
  - Signature: `static func scooter_details(length: float, width: float, lamps: int) -> Dictionary`
- `tools/visual_scenarios.json`: add `e_scooter_top_down_night`, a top-down
  (non-windshield) pose that reuses an existing scenario's city-centre pose.
  Spawn a moving, ridden e-scooter within 10 m of the camera, using the
  scenario runner's existing server_args or NPC hook. Use generic wording, with
  no street names or new coordinates.
- Scenario runner (where `requires` is checked, see docs/visual-testing.md):
  add `requires.npc_kinds_in_view: {"e_scooter": 1}`.

## Acceptance criteria
1. `scooter_details` has exactly one front lamp and one rear lamp, and no
   indicator or reverse lenses. Each lamp is no wider than `width * 0.32`.
2. The front lamp sits at `+x` (direction of travel) and is white/warm. The
   rear lamp sits at `-x` and is red.
3. In the 3D view the glb's stem/handlebar is on the travel-direction side, so
   the white lamp sits on the stem.
4. The footprint stays 1.2 x 0.5 m (VehicleDefinition `e_scooter`). The glb
   scales from MODEL_SIZE (0.482 x 0.844).
5. Cars, buses, trucks, motorcycles and the taxi render the same as before.
6. `e_scooter_top_down_night` runs with every readiness check passing,
   including `npc_kinds_in_view`. Inspect the screenshot: it must show a deck,
   a stem and a rider, a white lamp at the front of the stem, a red lamp at the
   tail, and the scooter clearly smaller than the nearest car.
7. The full suite passes. Run Godot tests with `XDG_DATA_HOME=$(mktemp -d)`.

## Tests to add
- `tests/test_vehicle_definitions.py::test_e_scooter_is_scooter_sized`: checks
  length <= 1.5 and width <= 0.6. This guard passes today.
- `tests/test_godot_render_style.py::test_e_scooter_lamps_white_front_red_rear`
  (headless Godot, or a source check like the existing ones in that file):
  - asserts the e-scooter details mesh has exactly two lamp boxes, a white one
    at `x > 0` and a red one at `x < 0`, each no wider than `width * 0.32`
  - fails today, because `model_car_details` gives paired car lenses plus
    indicators
- If the yaw is fixed: `tests/test_godot_render_style.py::test_e_scooter_model_stem_leads`
  asserts the placed glb's stem lies on the heading side. It fails without the
  yaw fix.

## Out of scope
- The 2D-only (non-opaque) e-scooter drawing in `entity_layer.gd`, which is
  already scooter-shaped.
- NPC e-scooter spawning, routing and traffic-law behaviour.
- Bicycle and motorcycle lamps.
