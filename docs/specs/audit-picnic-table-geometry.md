# Picnic-table tabletop, seats and supports

## Goal
Fix VQA-028: the picnic-table prop has a raised tabletop, two bench seats and grounded supports with open space beneath, instead of one solid block. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: replace only the `picnic_table` cuboid in `props()`, reusing existing rectangular mesh helpers.
- `godot/tests/run_tests.gd`: add/register focused table/support/openness and preservation checks beside scenery tests.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse mapped-prop verification and existing cameras for an actual visible picnic table.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/picnic-table-geometry/`: diagnosis, comparisons, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace OSM `leisure=picnic_table` through `_scenery_object_kind()`, path alignment, streamed `scenery_objects`, `map_chunk.prepare()`, `_structures()` and `props()` into the final chunk mesh. Record the generic cuboid cause and existing 1.8×1.5×0.75 m dimensions. Compare the actual 2D prop and separate biergarten-table builder without changing either.
2. Add a thin tabletop along the row's length, a lower bench seat on each long side and slender grounded legs/frames. Every tabletop and seat has a continuous contact path through supports to ground within 0.005 m. Leave recognizable knee/leg space beneath the tabletop and clear gaps between tabletop and seats; no enclosing slab, full-height solid panel or floating bench qualifies.
3. Preserve row centre/heading, the 1.8×1.5 m oriented envelope, 0.75 m maximum height and existing wood palette. Keep tabletop/seat thickness at most 0.10 m, bench tops between 0.38–0.46 m and a clear central opening at least 0.45 m wide and 0.30 m high. All vertices remain inside the envelope, supports meet flat ground, and normals/winding/shadows remain valid with no degenerate triangles.
4. Reuse bounded static chunk construction. Preserve mapped position/direction, scenery row contracts, 2D rendering, all other props (including repaired rack/camping props), biergarten details and pedestrian activity decisions. No new assets/dependencies or per-frame mesh work.
5. Verify headings 0, π/2, π and 0.73, translated positions and flat/nonzero constant ground through `props()` and final chunk construction. Contacts, openings and dimensions survive placement; chunk rebuild/unload/reload remains stable.
6. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated production-builder views plus a normal-distance perspective sample. Inspect tabletop, both seats, grounded supports and open spaces; retain historical audit evidence unchanged.
7. Pass and inspect a named real-map daylight 3D scenario containing an actual mapped picnic-table row from the normal pipeline. Record OSM ID, raw/aligned coordinates, row angle and provenance. Reuse a sourced road/camera pose where suitable; label the simple table geometry as representative rather than reconstructing the mapped design.
8. Readiness must match the actual rendered table/row, active 3D, useful projected tabletop/seat/support size, ground placement and unobscured frustum/HUD/building/dynamic-body sightlines. Require a directly visible opening and at least one visible seat-to-support connection; hidden projected geometry or counts alone cannot qualify. Retain normal map/time/weather/chunk checks and exclude rejected captures.
9. Record revision, renderer, dimensions, contact/opening measurements, commands and results. Parse changed scripts; run focused geometry/preservation plus existing scenery/ground/chunk checks. Preserve player userdata/shared edits; independent tester PASS precedes atomic commit/push.

## Tests to add
- `godot/tests/run_tests.gd::test_picnic_table_has_seats_and_open_supports`: inspect actual triangles/cross-sections for distinct tabletop/two seats, open leg space, support contact paths, grounding and oriented bounds across the placement matrix; the current cuboid must fail, as must removed/floating seats or filled openings.
- `godot/tests/run_tests.gd::test_picnic_table_geometry_preserved`: verify dimensions/palette, unchanged other props/biergarten geometry, final ground placement and stable chunk rebuild/unload/reload.
- Named readiness rejects absent/wrong-kind/wrong-angle, inactive, hidden/buried/offscreen or undersized table/opening targets; only an inspected passing screenshot counts.

## Out of scope
VQA-029–033 and other findings, exact mapped table styles/capacity, seating interactions/animation, biergarten redesign, new assets/data sources, pedestrian/server behavior, terrain conformance redesign, new cameras and renderer refactors. Visual evidence samples recorded map/lighting conditions.
