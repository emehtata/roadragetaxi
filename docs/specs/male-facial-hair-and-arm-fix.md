# Male facial hair and the "neck object"

## Goal
Explain and remove the orange lump at the walker's neck (screenshot 2026-11-14 14:45) and give men
deterministic facial hair styles. Women are unchanged.

## Cause of the neck object (investigated)
It is not an arm pose. Arms already hang: `godot/buildings_3d.gd:1434-1437` puts the shoulder at
y 1.30, the elbow at 1.08 and the wrist at 0.91, with only a walk swing in x. The lump is the **style 1
hood**, `godot/buildings_3d.gd:1448-1449`: a `fabric.darkened(0.12)` ellipsoid at head + (-0.07, -0.025, 0)
sized (0.09, 0.14, 0.14) × `hk`. With the comic head scale `H = (1.45, 1.7, 1.7)` (line 1399) its
half-height is 0.14·1.7 = 0.24 m, so it reaches about 0.28 m below the head centre (y ≈ 1.22),
past the neck stub (1.30-1.36) and onto the shoulder. In shirt colour, seen from the side, it looks like a
raised arm or hand at the neck. The comic head scale (commits 164370af / 5680cbdb / 81f5c1e3) scaled it up
but its size was never retuned. Variant 1 also gets long side hair (`variant % 3 == 1`, line 1450),
which overlaps it.

## Fix
- Hood: divide its size by the comic scale so it sits on the back of the head: centre
  head + (-0.06, 0.0, 0) × hk, size (0.07, 0.085, 0.085) × hk. Its lowest point stays above
  neck-stub top + 0.02 m.
- Arms: no change, but add a test that guards the hanging pose (below).

## Facial hair design
- `person_arrays(..., detail := 1, beard := 0)` and `person(..., winter, beard := 0)`. Add `beard`
  to the cache key in `person()` (line 1351).
- Styles 0-5: 0 none, 1 short beard, 2 full beard, 3 moustache only, 4 moustache + beard, 5 goatee.
  Each is 1-3 `_round_part` ellipsoids on the face front (x ≈ 0.10-0.12 × hk), drawn only if `detail > 0`:
  short beard = a thin jaw shell under the mouth (y -0.09); full beard = a bigger jaw/chin part down to
  y -0.16 plus cheek parts at ±z; moustache = a flat part at y -0.055 between the nose (line 1458) and the
  mouth (line 1459); goatee = a small chin part only. Colour = `hair` (grey for variant 7), part 2
  (the hair part id). No new assets or colours.
- Picked in `godot/entity_layer.gd:2112` (`_people_3d`):
  `beard = (absi(hash(id)) / 8) % 6` when `ped.resident.gender` is "male" (or "man"/"m"), else 0. Dividing by 8
  decorrelates it from the clothing variant (`% 8`). No resident (a thief, NPC without one) gives 0. Elves
  and santas get 0 (santa keeps his own look).

## Files
- `godot/buildings_3d.gd`: hood size, `beard` param on `person` / `person_arrays`, face parts.
- `godot/entity_layer.gd`: compute and pass `beard`.
- `godot/tests/run_tests.gd`: tests.
- `tools/visual_scenarios.json`: a close-up scenario of 3 men if the showcase cannot do it.

## Acceptance criteria
1. In "standing", "standing_1" and every "walk_N" pose, for both sides each wrist is below its elbow,
   which is below the shoulder, and |wrist.z| >= 0.15 × k (at the side, not at the neck).
2. Variant 1 (hood) has no vertex within 0.05 m of the neck stub axis below the head that is not skin.
3. `beard = 0` gives the same verts as before the change (apart from the hood).
4. Beard styles 1-5 each add vertices and give 5 different vert hashes. All extra verts are in the face's
   front half (x > 0) and below the eyes.
5. Over ids 0..63 with gender "male", the picked `beard` covers all six styles. Any female or
   missing-resident ped gets 0.
6. A rendered close-up shows 3 men with different facial hair (for example ids giving 2, 3, 5) and no lump at
   the neck. Inspect it visually.

## Tests to add (godot/tests/run_tests.gd)
- `test_person_arms_hang_in_idle_and_walk`: criterion 1. Rebuild the joints from `person_arrays` verts
  near the shoulder, elbow and wrist heights. Fails if a pose raises an arm.
- `test_person_hood_clear_of_neck`: criterion 2. Fails on the current hood.
- `test_person_beard_styles_differ`: criteria 3-4. Fails today (no `beard` param).
- `test_person_beard_pick_by_gender`: criterion 5. Needs the pick as a static helper
  `static func beard_style(ped: Dictionary) -> int` in entity_layer.gd. Fails today (no helper).

## Commands
`make check`; `XDG_DATA_HOME=$(mktemp -d) make godot-test`; render with `godot-shot` (Windows exe,
WSL paths) using the character showcase or the new scenario. Inspect the PNG.

## Out of scope
Server changes, new textures or assets, hair/beard for women, beards in the 2D view, arm pose changes.
Privacy: no real place names or coordinates in scenarios or files.

## Status
- Tester verdict: VERDICT: PASS. Arm-hang guard, hood clearance, beard styles and gender pick are covered by tests.
- Open: the normal-scene beard render is unverified. Only the character showcase was rendered.
- Open: beards show only within 40 m of the view centre.
- Follow-up: the goatee and full beard are cosmetically heavy.
