# Horse riders seated in the saddle

Goal: a 3D horse rider sits on the GLB horse's back with hips on the saddle and legs astride,
not standing on stiff legs with the hips above the horse.

## Current behaviour
- `godot/buildings_3d.gd:1368` `pose == "riding"` lifts the whole standing figure by `offset = 0.68`:
  hips at `0.87 + 0.68 = 1.55` m (`:1380`).
- `:1381-1383` riding legs are the standing legs: knee at `0.45 + 0.68 = 1.13`, ankle at `0.82`, all at
  `z = ±0.11..0.121`, straight down, so they sit inside the horse's body and read as standing.
- `:1373-1376` the mount is `animal_arrays("horse", ...)`, the GLB (`ANIMAL_MODELS["horse"]`, 2.0 m long, `:1436`).
  Measured from `_model_arrays("horse", ..., 1.0)`: back top ~1.17 m at x=-0.2, ~1.23 m at x=0,
  half-width ~0.23 m at x=0, withers rising to 1.37 m at x=+0.2.
- 2D (`entity_layer.gd:1273`) draws a top-down ridden marker; no seat height, out of scope.

## Cause
The 0.68 m riding offset dates from the procedural horse (`ba724d4e`, body_y 1.15). Commit `cdbfe222`
swapped the mount to the CC0 GLB without retuning it, and the riding pose never had its own leg joints:
it reuses the standing leg chain, so hips float ~0.3 m over the back and straight legs pass through the body.
`animal_models_test.gd` `test_horse_saddle_height` checks only that the mount is the GLB, not the height.

## Change (`godot/buildings_3d.gd` only)
1. Add `const HORSE_SADDLE_Y := 1.25` (GLB back at x=0 plus saddle) with a comment saying it was measured
   from the horse GLB at size 1.
2. Riding `offset` becomes `HORSE_SADDLE_Y - 0.87`, so hips sit on the saddle at `HORSE_SADDLE_Y * k`.
   The torso, arms and head follow, since they already use `offset`.
3. Riding legs get their own joints (a `static func riding_leg_joints(side: float) -> Array` returning
   [hip, knee, ankle] at k=1, the same shape as `rider_leg_joints`): hip z ±0.11; knee x +0.15,
   y ~HORSE_SADDLE_Y-0.3, |z| 0.30 (outside the 0.23 m half-width); ankle x +0.05, y ~HORSE_SADDLE_Y-0.65,
   |z| 0.27. Other poses are unchanged.

## Acceptance criteria
1. `person_arrays(..., "riding", 1.0, ...)`: the lowest torso vertex is within 0.08 m of the horse GLB's
   top at x in [-0.2, 0.2]: no gap and no sinking below the back.
2. Both riding knees and ankles have |z| > the horse half-width at their x: legs astride, outside the body.
3. Each riding ankle is below and ahead of its hip and above 0.45 m: the feet hang, they don't reach the ground.
4. Sitting, standing, walking and swimming leg vertices are byte-identical to the current output.
5. Visual scenario `wildlife_models_day` (has the rider, 5-13 m ahead) passes its readiness checks. The
   screenshot is inspected, and the rider sits on the horse's back with legs down its sides.
   If it is too far away to judge, add `horse_rider_closeup_day` (the same setup, rider 4 m ahead, 3D low camera).
6. `make check` and `XDG_DATA_HOME=$(mktemp -d) make godot-test` pass with nothing deselected.

## Tests (`godot/animal_models_test.gd`)
- Extend `test_horse_saddle_height`: criterion 1. It fails now because of the 1.55 m hips, about 0.3 m above the 1.23 m back.
- `test_horse_rider_legs_astride`: criteria 2-3. It fails now because the knees are at |z| 0.121, inside the body.
- `test_other_poses_unchanged`: criterion 4. It guards the shared leg loop against regressions.

## Commands
```
cd /home/ubuntu/work/roadragetaxi
XDG_DATA_HOME=$(mktemp -d) make godot-test
make check
godot-shot --scenario wildlife_models_day   # per docs/visual-testing.md
```

## Out of scope
2D top-down rider drawing; horse gait animation; server-side horse movement; other GLB animals.

## Status
- Tester verdict: PASS.
- Screenshot: `visual-test-results/horse_rider_closeup_day/2026-06-20T1300_20261113-225131_5c777a48-dirty/screenshot.png`
- Test gap: `test_horse_rider_legs_astride` checks the `riding_leg_joints()` values, not the vertices that `person_arrays` draws. Reverting only the drawn legs would not fail it. The screenshot check covers the visual result.
