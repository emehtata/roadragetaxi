# 2D camper pitch: drawn length matches the streamed length

## Goal
Verify the 2D camp pitch rendering at Nallikari camping (Oulu, public, free to use) in a
named scenario, and fix the camper being drawn ~3 % shorter than its streamed length.

## Finding the pitch
Local OSM extract of the Oulu preset (the one `tools/visual_test.py` loads). Select
elements with `tourism=camp_site` named Nallikari and the `tourism=camp_pitch` elements
inside its outline. Run `osm/campsites.py populate_camp_pitches` on them and keep a pitch
that got a `camper_van` row (`scenery_objects` row `[x, y, "camper_van", angle, length]`).
Write only that pitch's EPSG:3067 coordinates and the name Nallikari into files: no OSM
ids, no street names (public repo rule). If no pitch there yields a camper (variation
picks tent/caravan), pick the nearest Nallikari pitch that does and say so in `why`.

## Cause (confirmed by reading, to be confirmed by the render)
`godot/map_chunk.gd` `_draw_scenery_object`, `"camper_van"`: scale is `extra / 6.2`, but
the opaque body is `Rect2(-3,-1.15,6,2.3)`, i.e. 6.0 m (lights span -3.0..2.95 = 5.95 m).
Only the translucent shadow rect is 6.2 m. So the visible camper = 0.968 x streamed length.

## Files to change
- `godot/map_chunk.gd`: smallest fix, in the camper branch only: use the body length as the
  design size, i.e. scale `(extra if extra > 0.0 else 6.0) / 6.0`, and fix the comment
  ("drawn 6.0 m long"). Leave shadow, wheels and lights as they are. No change to
  `campsites.py` / `vehicles/base.py` (6.2 m stays the streamed length).
- `tools/visual_scenarios.json`: add scenario `camp_pitch_2d_nallikari` ONLY by appending
  an entry (the file has uncommitted roadworks edits: do not touch or commit them; use
  `git add -p`).

## Scenario (view 2d, city Oulu, pose = chosen pitch, zoom ~3, day, clear)
Readiness checks (in `godot/visual_test.gd`, parked edits there: add via `git add -p`;
a failed check fails the run, no screenshot counts):
1. `requires.camper_pitch_in_view >= 1`: a chunk `props` row of kind `camper_van` lies in
   the camera rect.
2. Drawn length within 10 % of streamed: measured from the draw call data (scale.x * 6.0
   of the camper transform), compared to the row's length. Expect ratio 1.00 after fix,
   0.968 before.

Deviation (accepted by the user, 2026-11-05): the taxi cannot stand on the pitch (it would cover
the camper and stand off the road), so the scenario's `pose` is the campsite service road
and a new `camera_at` field holds the camera on the camper's pitch area (between the camper
and caravan pitches, 4 m from the camper's). `pitches` lists each pitch `[x, y, 5 m]`
(campsites.py's point-pitch envelope); readiness checks each row's footprint inside it and
records the fit in result.json. Zoom 5 instead of ~3 so the 0.24 m lights resolve.

## Acceptance
1. Scenario passes its readiness checks (run per docs/visual-testing.md).
2. Inspect the captured frame yourself: the camper is a white box with blue cab, red tail
   lights and yellow head lights, sits inside its pitch, does not overlap roads or
   buildings, orientation matches the pitch. Measure it on the frame (m per pixel from
   zoom): 6.2 m +/- 3 %. Compare with a pre-fix frame: about 6.0 m.
3. Tents/caravans on the same frame unchanged.

## Tests to add
- `tests/test_campsites.py::test_camper_row_carries_vehicle_length`: the camper row's
  length equals `vehicle_definition("camper_van").length_m` (guards the streamed side).
- Godot headless check (existing godot test dir, pattern of other map_chunk tests)
  `test_camper_drawn_length_matches_row`: draw a camper with extra=6.2 on a recording
  node, assert the body extent (x scale * 6.0) is 6.2 +/- 0.05. Fails before the fix
  (6.0 * 6.2/6.2 = 6.0).
- Run with `XDG_DATA_HOME=$(mktemp -d)`; run the whole suite.

## Out of scope
3D camper model, caravan sizes, pitch placement logic, the other CAMPING_SIZES, the
roadworks scenario and the parked edits in `cli.py`.
