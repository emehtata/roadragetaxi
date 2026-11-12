# GLB-only vehicle drawing

## Goal
Wherever a GLB exists for a vehicle kind, draw only the GLB; the procedural mesh stays only for kinds
with no GLB. The user sees the procedural taxi/cars beyond `MODEL_CAR_RANGE` today (66 m, set in
docs/specs/car-model-lod-pop.md to hide the swap).

## Decision on the gates
- Range gate (`MODEL_CAR_RANGE`, train 35 m): removed. With no procedural fallback it would only
  make vehicles vanish, and the original goal (no visible pop) is met better with no swap at all.
  Bounded work: the entity layer already sends only vehicles near the view, `place_model_car` pools
  nodes per kind (no per-frame instantiate after warm-up), and the cost is checked by the bench (AC 7).
  No cap or sort is added; if the bench is over budget, report and stop.
- `opaque` gate: stays, as a render-mode condition, not a LOD. GLBs need the shaded/lit path
  (`use_shaded`, line ~2201); the unshaded composite path keeps the procedural mesh.
  Implementer: confirm by grep whether `opaque == false` is still reachable for vehicles; if not, delete
  the branch and the procedural car code it alone used.

## Files to change
- `godot/buildings_3d.gd`
  - `car()`: with `opaque`, always `car_model_kind` + `place_model_car` + details; drop the distance test.
    Keep the procedural body only for `not opaque`. Drop the 35 m detail 0/1 split if only the
    procedural path used it.
  - `vehicle()`: same for bus/truck/motorcycle/camper_van/tractor/trailer/e_scooter/bicycle and train
    (locomotive/coach); remove both distance tests. The plough tractor stays procedural (GLB has no plough).
  - Delete `MODEL_CAR_RANGE`. Add `static func has_model(kind: String) -> bool` (MODEL_SCENES lookup via
    `model_variant`) so tests and the lineup scenario share one definition of "has a GLB".
- `godot/tests/run_tests.gd`: replace `test_car_model_range`, update `test_bus_model_radius_matches_car`.
- `tools/visual_scenarios.json`: new scenario `glb_only_traffic_day` (see tests).

## Acceptance criteria
1. In opaque mode a car at 10, 60, 70, 200 m from the view centre uses a GLB (`_model_used`), none procedural.
2. Same for bus, truck, motorcycle, camper_van, tractor (no plough), trailer, e_scooter, bicycle at 200 m.
3. Train locomotive/coach at 100 m use `train_locomotive`/`train_coach`.
4. Windshield view: the rule holds with `windshield_at` as centre (no distance dependence at all).
5. Kinds with no GLB (tram, plough tractor, any kind absent from MODEL_SCENES) still draw procedurally,
   at any distance, and `vehicle()` does not error on them.
6. Trees, buildings, pedestrians/animals and every other `Buildings3D` draw call are unchanged: the
   existing forest/tree/building tests pass untouched, and a frame with cars plus trees yields the
   same tree mesh count as before the change.
7. Frame cost: drive bench on native Windows Godot in a dense street; p50/p95 frame time within 10% of
   the pre-change baseline. Otherwise report numbers, do not add a cap unasked.
8. Whole test suite (all Python and Godot tests, `XDG_DATA_HOME=$(mktemp -d)`) passes, none deselected.

## Tests to add
- `godot/tests/run_tests.gd::test_car_model_has_no_range_limit`: cars at 70 m and 200 m use models
  (`_models_used == 1`); fails today (procedural beyond 66 m).
- `::test_vehicle_models_at_distance`: loop over the kinds in AC 2 and 3 at 200 m, `_model_used` of the
  mapped model == 1 and no procedural body placed; fails today for all.
- `::test_unmodelled_kinds_stay_procedural`: tram and plough tractor at 10 m place a procedural body, no
  model; guards the "no GLB" side.
- `::test_has_model_matches_scenes`: every kind drawn via `vehicle()` is either `has_model` or listed as
  procedural-only; fails if a GLB kind is forgotten.
- `::test_trees_unaffected_by_vehicle_models`: build a frame with cars and trees, tree arrays equal to a
  frame without cars (AC 6).
- Visual: scenario `glb_only_traffic_day` (3d, city-centre street with moving traffic and trees, found with
  `tools/visual_test.py find`, `drive_s` long enough to pass vehicles at 80-200 m, `requires`
  `buildings_in_view`, plus a vehicle-count readiness minimum of cars beyond 66 m). Per
  docs/visual-testing.md the screenshot counts only if readiness passed. Inspect: distant cars show GLB
  glazing/wheels, no flat procedural boxes; the taxi (also via the `windshield` option variant) is a GLB.
  Re-run `vehicle_lineup_3d_day` and compare: all modelled kinds unchanged.

## Out of scope
- Adding GLBs for tram, plough, moped/bmx (files exist but unmapped), or new kinds.
- The model branch ignoring `extra["fallen"]` for bikes (separate bug, flag it).
- LOD/impostors, per-frame caps, hysteresis, the 2D view.
