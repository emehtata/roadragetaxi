# Open bicycle-parking rack

## Goal
Fix VQA-027: the static bicycle-parking prop reads as an open row of rack hoops rather than an opaque bar. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: replace only the `bicycle_parking` cuboid in `props()` using existing mesh helpers.
- `godot/tests/run_tests.gd`: add/register focused rack openness, attachment and preservation tests beside scenery tests.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse actual mapped-prop matching and existing cameras for one visible bicycle rack.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/bicycle-parking-rack/`: diagnosis, labelled comparisons, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace OSM `amenity=bicycle_parking` through `_scenery_object_kind()`, path alignment, streamed `scenery_objects`, `map_chunk.prepare()`, `_structures()` and `props()` into the final chunk mesh. Record why the generic 3.0×0.6×0.8 m cuboid obscures rack openings; compare the existing 2D convention of four hoops spaced along the row.
2. Replace the bar with four slender inverted-U hoops or equivalent open frames, spaced along the row with their spans across it. Each has two grounded uprights joined to a top bar within 0.005 m; leave clear space below the top bars and between hoops. Existing rectangular mesh helpers are sufficient; curved tubing is unnecessary.
3. Preserve row centre/heading, existing 3.0×0.6 m envelope, 0.8 m maximum height and metal palette. Keep members at most 0.08 m thick and each hoop opening at least 0.35 m wide and 0.55 m high. All vertices remain in the oriented envelope; no enclosing slab, filled panel or ground-to-top pedestal qualifies. Geometry has valid winding/normals, nondegenerate triangles and appropriate shadows.
4. Keep static chunk construction bounded. Preserve mapped position/direction and server parking/access decisions, row contracts, 2D rendering, live/parked bicycles and every other prop, including the repaired camping props. Do not add parked bicycle fixtures to production or per-frame mesh work.
5. Verify headings 0, π/2, π and 0.73, translated positions and flat/nonzero constant ground through `props()` and the final chunk build. Openings and connected members retain their dimensions/ground contact; chunk rebuild/unload/reload is stable.
6. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated production-builder views plus a normal-distance perspective sample. Inspect all four open hoops, contacts, ground placement and recognizable rack silhouette; retain historical audit evidence unchanged.
7. Pass and inspect a named real-map daylight 3D scenario containing an actual mapped bicycle-parking row from the normal pipeline. Record OSM ID, raw and aligned coordinates, row angle and source provenance. Reuse an existing sourced road/camera pose where feasible; a synthetic fixture does not receive mapped-target credit.
8. Readiness matches the actual rendered rack and row, active 3D view, useful projected member/opening size, ground placement and unobscured frustum/HUD/building/dynamic-body sightlines. Include at least one directly visible opening; counts or projected hidden geometry alone do not qualify. Retain normal map/time/weather/chunk checks and exclude rejected captures.
9. Record revision, renderer, dimensions, opening/contact measurements, commands and results. Parse changed scripts; run focused geometry/preservation and existing scenery/ground/chunk checks. Preserve player userdata/shared edits; independent tester PASS precedes atomic commit/push. Follow the traffic-law guide's footprint/access guidance; this display correction does not implement or certify bicycle parking behavior.

## Tests to add
- `godot/tests/run_tests.gd::test_bicycle_parking_rack_is_open`: inspect actual triangles/cross-sections for four open frames, clear openings, slender connected members, grounding and oriented bounds across the placement matrix; the current solid bar must fail, as must missing hoops or filled openings.
- `godot/tests/run_tests.gd::test_bicycle_parking_geometry_preserved`: verify palette/dimensions, unchanged other props/live bicycles, final ground placement and stable chunk rebuild/unload/reload.
- Named readiness rejects absent/wrong-kind/wrong-angle, inactive, hidden/buried/offscreen or undersized rack/opening targets; only an inspected passing screenshot counts.

## Out of scope
VQA-028–033 and other findings, exact reconstruction of mapped rack styles/capacity, bicycle placement/locking interactions, new assets/data sources, parking/allocation/access/routing changes, terrain conformance redesign, new cameras and renderer refactors. Visual evidence samples recorded map/lighting conditions.
