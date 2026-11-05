# drawn_campers grows without bound

## Goal
Stop `MapChunk.drawn_campers` accumulating stale entries, keeping the camper length
readiness check (`visual_test.gd`) working.

## Growth path
`godot/map_chunk.gd` ~line 1502 (`_draw_scenery_object`, `"camper_van"`):
`drawn_campers[at] = 6.0 * stretch.x`. `at` is `MapMath.point(_origin, x, y)`. The dict
(declared ~line 1479) is never cleared. Redrawing unchanged data overwrites the same key,
but whenever the chunk's `_data` or `_origin` changes (reload of the chunk via the
`_data = message; _origin = origin` path near line 120, camper rows moving or removed), old
keys stay. Only the camper branch writes it; no other site reads or resets it.

## Fix (smallest)
Call `drawn_campers.clear()` at the top of `_draw_scenery(node: Node2D)` (~line 1436),
the single place that loops `scenery_objects` and calls `_draw_scenery_object`. Every
redraw therefore rebuilds the record from the rows it draws. Skipped: a per-frame key,
which adds state for no gain.

## Files to change
- `godot/map_chunk.gd`: the one `clear()` line in `_draw_scenery`.
- `godot/tests/run_tests.gd`: new test (below).

## Acceptance criteria
1. After `_draw_scenery` runs twice on one chunk with N camper rows, `drawn_campers.size() == N`.
2. After the chunk's `_data` is replaced by rows at different positions and `_draw_scenery`
   runs again, no key from the old rows remains.
3. `test_camper_drawn_length_matches_row` still passes (it calls `_draw_scenery_object`
   directly, so the clear must not live inside that function).
4. `visual_test.gd` `_campers_in_view` is unchanged and still reads the drawn body length
   for campers in view (a camper drawn this frame reports its length, not the 0.0 "not drawn").
5. A chunk whose camper rows were removed has an empty record after redraw.

## Tests to add
`godot/tests/run_tests.gd`, `test_drawn_campers_cleared_per_draw`: build a `MapChunk`, set
`_data = {"scenery_objects": [[3, 4, "camper_van", 0.0, 6.2], [10, 4, "camper_van", 0.0, 7.0]]}`
and `_origin`, call `_draw_scenery(Node2D.new())` twice, assert size 2 (check 1); replace
`_data` with one row elsewhere, redraw, assert size 1 and old key absent (checks 2, 5).
Without the fix, the second assertion fails: size is 3 with the old key present.
Run with `XDG_DATA_HOME=$(mktemp -d)`; run the whole suite.

## Out of scope
- `tools/visual_scenarios.json` (parked roadworks entry) and anything roadworks-related.
- Changing camper drawing, scale, or the readiness check logic.
- Other per-chunk caches.
