# Mountain bike size: explicit override, no silent squeeze

## Goal
Render mountain_bike.glb at its real-world size through a per-model override
table (as MODEL_HEIGHT does for the e-scooter), not by squeezing its bars to the sim width.

## Current squeeze
`model_scale("mountain_bike", 1.8, 0.6)` = (0.6/0.78, 1.0, 1.8/1.885) = (0.769, 1.0, 0.955).
Rendered 0.60 x 1.80 m: the bars (source 0.78 m, the widest part) are 23 % narrower
than the model, the frame is squeezed with them. test_model_sizes_match_sim passes
(10 % vs sim) and docs/specs/vehicle-model-variants.md records it as an exception.

## Decision
Keep the sim footprint 0.6 x 1.8 m (collision, lanes, parking: server side, unchanged).
Change the rendered width target to the model's own 0.78 m. Why: real MTB flat/riser
bars are 0.70-0.78 m, so 0.78 is realistic, and 0.6 m is the footprint of a bicycle
body, not its bar width (the realism table's 0.6 gives no bar width). The bar
overhang is a render-only 0.09 m per side, as a car's mirrors. Length stays on the
sim (1.8 m; model 1.885, 4.5 % stretch, within real 1.75-1.85 m). Height stays 1.08 m
(source; real 1.05-1.10 m).

## Files to change
- `godot/buildings_3d.gd`
  - add `const MODEL_WIDTH := {"mountain_bike": 0.78}` beside MODEL_HEIGHT, comment: rendered width in metres, replaces the sim width for the model.
  - `model_scale(kind, length, width)`: `if kind in MODEL_WIDTH: width = MODEL_WIDTH[kind]` before the return. Signature unchanged.
- `godot/tests/run_tests.gd`, `test_model_sizes_match_sim`: for variants in MODEL_WIDTH compare rendered width to MODEL_WIDTH[variant] (3 %), all others to the sim (10 %); length to 1.8 for all (10 %, mountain bike 3 %).
- `docs/specs/vehicle-model-variants.md` (line ~49) and `docs/specs/vehicle-realism-audit.md` (bicycle row/line 30): replace the "squeezed 23 %, recorded exception" text with the override and its numbers; the exception is closed.

## Acceptance criteria
1. `model_scale("mountain_bike", 1.8, 0.6).x` = 1.0 (+-0.001); `.z` = 1.8/1.885; `.y` = 1.0.
2. Rendered mountain_bike AABB width is 0.78 m +-3 %, length 1.80 m +-3 %.
3. `bicycle` (0.617 source) still renders 0.6 x 1.8 m (+-10 %); no other kind's scale changes.
4. MODEL_WIDTH holds only models whose source width is over 15 % off the sim width; the docs name this rule next to the table.
5. The server sim size (bicycle 1.8 x 0.6, tests/test_vehicle_definitions.py) is unchanged.
6. The realism spec and variants spec no longer list the mountain bike as a squeeze exception.
7. Render check: `vehicle_lineup_bikes_day` passes readiness; by eye the mountain bike's bars are wider than the city bicycle's, wheels round, frame not narrowed.
8. Full suite passes (Godot tests with `XDG_DATA_HOME=$(mktemp -d)`).

## Tests to add
- `godot/tests/run_tests.gd::test_mountain_bike_keeps_its_width` (new, called from the runner list): instantiates the model, applies `model_scale("mountain_bike", 1.8, 0.6)`, asserts criteria 1-2. Fails on the old squeeze (width 0.60, x scale 0.769).
- Extended `test_model_sizes_match_sim` as above; the old squeeze fails its 3 % width check.
- `tests/test_vehicle_definitions.py::test_bicycle_sim_size_unchanged`: bicycle stays (1.8, 0.6) (guard, passes today; criterion 5).

## Out of scope
- Sim footprint, collision, lane width for bikes; bmx_bike (not wired).
- Other models' scale rules, height overrides, new bike variants.
- Procedural top-down bicycle drawing in entity_layer.gd.
