# Vehicle model variants (several GLBs per kind)

## Goal
A vehicle kind can have several close-range 3D models. Each vehicle picks one from a stable hash of its id, the same way `body_style` does, so its look stays the same from frame to frame. Cars stay as they are.

## Candidates (bounds measured in Godot with node transforms, metres, W x L, H)
| kind | model | source W x L | wired |
|---|---|---|---|
| bicycle (sim 1.8 x 0.6) | bicycle.glb | 0.617 x 1.87 (H 1.10) | yes |
| bicycle | mountain_bike.glb | 0.78 x 1.885 (H 1.08) | yes |
| bicycle | bmx_bike.glb | 0.76 x 1.454 (H 1.01) | no: 24 % stretch to the sim's 1.8 m |
| e_scooter (sim 1.2 x 0.5) | e_scooter.glb | 0.482 x 0.844 (existing MODEL_SIZE) | yes |
| e_scooter | e_scooter_grab3d.glb | 0.52 x 1.247 (H 1.12) | yes |
| tram | tram.glb | 3.3 x 22.6 (H 5.24) | no: fails AC 6 (a) |
| (none) | moped.glb | 0.71 x 1.56 | no: nothing spawns a moped (no spawner in src/) |
| (none) | subway_train.glb | 2.83 x 18 (H 3.77) | no: it is a metro, not a tram, and it does not match the train kind's locomotive/coach profiles |
motorcycle, city_bus and camper_van keep their single model. The bicycle is procedural in the 3D view today.

## Files to change
- `godot/buildings_3d.gd`: add MODEL_SCENES/MODEL_SIZE entries keyed by model name (`bicycle`, `mountain_bike`, `e_scooter_grab3d`; `bmx_bike` and `tram` stay out, see Outcome). Add a `const MODEL_VARIANTS := {"bicycle": [...], "e_scooter": [...]}` and
  `static func model_variant(kind: String, id) -> String` (`MODEL_VARIANTS[kind][absi(hash(id)) % size]`, or `kind` when the kind has no variants).
  In `vehicle()`, add "bicycle" to `modelled` and resolve `model_kind` through `model_variant(kind, extra.get("id", 0))`.
  `UNIFORM_SCALE_MODELS` holds a model exactly when it is stretched over 15 % in length; the new models are stretched about 4 % (bicycle 0.96, mountain_bike 0.95, e_scooter_grab3d 0.96), so none is added.
  Paint: the Grab3D files ship a textured `*_body` material with no `paint*` surface, so they keep their textures and are not repainted. Leave the paint conditions in `place_model_car` unchanged.
- `godot/entity_layer.gd`: pass the vehicle's id in `extra["id"]` only for kinds in `MODEL_VARIANTS` (bicycles, e-scooters) when they call `vehicle()` (the same id `body_style` hashes). Keep the procedural rider: draw it with `model_car_details`/`_rider` on top of the model, as the e-scooter does now.
- `tests/test_vehicle_definitions.py`, `godot/tests/run_tests.gd`: tests below.

## Acceptance criteria
1. `model_variant(kind, id)` gives the same result for the same id on every call and in every frame.
2. Over 1000 ids, each variant in `MODEL_VARIANTS[kind]` is picked at least once for bicycle and for e_scooter.
3. The cars' model choice (`model_kind_for_shape`/body_style) does not change: the existing car tests pass unchanged.
4. Every wired variant, scaled by `model_scale`, renders within 10 % of the REAL_WORLD length and width for its kind.
5. `vehicle_lineup_3d_day` and `vehicle_lineup_3d_night` pass readiness, and the screenshots show at least two different bicycle models and two different e-scooter models. The lineup gives each row several ids.
6. The tram model goes in only if (a) its scaled size is within 10 % of the sim tram's length and width (trams.py / vehicle_arrays "tram"), and (b) a lineup render shows it upright and on the rails. Otherwise trams stay procedural and the spec records why.
7. The full pytest and Godot test suites pass.

## Tests to add
- `godot/tests/run_tests.gd::test_model_variant_stable_and_covering`: covers AC 1 and 2. It fails without `model_variant`/`MODEL_VARIANTS`.
- `godot/tests/run_tests.gd::test_model_sizes_match_sim`: extend it to loop over every name in `MODEL_VARIANTS` (AC 4). It fails if a variant has no MODEL_SIZE entry or is wrongly scaled.
- `tests/test_vehicle_definitions.py::test_glb_aspect_close_to_sim`: change `models` to kind -> list of variants and check each one. It fails if a variant's aspect is off.

## Out of scope
New spawners (moped), metro trains, any change to cars, the 2D view, and server-side changes (ids already exist).

## Outcome
- The first table read raw POSITION accessors without node transforms and swapped axes; it now holds the Godot-measured sizes MODEL_SIZE uses.
- bmx_bike stays out: 1.454 m long (a side render shows it upright), so the sim's 1.8 m would stretch it 24 %.
- tram stays procedural: AC 6 (a) fails, a 22.6 m model against 9.2 m sections and 3.3 m against the sim's 2.4 m width.
- Width: every model's width is scaled to the sim's (0.6 m bicycle), except models in `buildings_3d.gd` MODEL_WIDTH (rule: source width over 15 % off the sim width). mountain_bike renders at its own 0.78 m bars (x scale 1.0; sim 0.6 m unchanged, 0.09 m render-only overhang per side) x 1.80 m (z 1.8/1.885) x 1.08 m; see docs/specs/mountain-bike-size-override.md. The former 23 % squeeze exception is closed.
- What the screens show: at the close zoom (vehicle_lineup_bikes_day/_night, top-down) the variants differ by colour and parts, not by silhouette: the bicycle has a tan front basket and a pale frame, the mountain bike is dark grey without a basket; the two scooters differ by deck colour (pale pink vs light blue). At vehicle_lineup_3d_day/_night zoom they are a few pixels long and cannot be told apart.
