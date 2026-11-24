# Bus-stop shelter GLB

## Goal
Replace procedural 3D bus-stop shelters with Grab3D's Urban Street Bus Stop Shelter GLB at existing mapped shelter placements.

## Files to change
- `godot/assets/props/`: shelter GLB/imported textures, source notice/manifest, measured provenance; extend `SOURCES.md` using existing CC0 text.
- `godot/buildings_3d.gd`: cached shelter source surfaces and footprint-based placement in the existing structures path.
- `godot/map_chunk.gd`: main-thread source preparation before chunk workers; preserve mapped shelter rows and existing batching.
- `godot/i18n.gd`, `tools/license_inventory.json`: extend Urban Street attribution in Finnish, English and German and inventory the shipped assets.
- `godot/tests/bus_stop_shelter_glb.gd`, `godot/tests/manifest.txt`: focused source, placement and control checks.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: real-map shelter scenarios with exact feature readiness; relevant hunks only.

## Behaviour / acceptance criteria
1. Inspect the actual [Bus Stop Shelter](https://grab3d.com/models/city/bus-stop-shelter/) GLB before integration. Record source hash, child transforms, dimensions, triangle/material counts, glass, front opening, bench and ground contacts. Retain complete authored geometry, materials, textures, normals, UVs and tangents through static batching.
2. Only existing non-null `bus_stops[].shelter` polygons receive the GLB. Derive centre, long axis and roadside opening from the ordered footprint: its first edge is the road-facing edge in `bus_stop_shapes`. Keep the opening facing that edge on either road side, including rotated rows; do not infer orientation from unsigned length alone.
3. Ground-centre the model and apply one uniform scale, never enlarging it beyond authored size, to keep its complete horizontal bounds inside the existing footprint (currently 5.0 by 1.6 m). Document measured source orientation and scale. Use the established terrain adjustment, with grounded supports and no road intrusion, floating frame or lost roof/glass.
4. Remove the old roof/posts for successfully rendered shelters. Keep the shelter's authored bench once; the server already suppresses a standalone stop bench when a shelter exists. Preserve bench-only rows, unsheltered stops, bays, markings, signs and the 2D fallback. Invalid/degenerate footprints produce no malformed geometry or crash.
5. Cache immutable source geometry/materials on the main thread and reuse existing per-material chunk batches. Workers only transform prepared arrays; retain async stale-result rejection, ground adjustment, layer/shadow policy and unload/reload behavior. Add no per-frame shelter rebuild or scene/material clone per stop.
6. Keep map generation, authoritative bus stops, pedestrian waiting/activity positions, collision, bus routing and boarding unchanged. The authored seat is visual and creates no new interaction. Inspect the real-map view for conflicts with ordinary waiting positions; resolve visual placement within the existing envelope rather than changing simulation rules.
7. Record exact source/download URLs, retrieval date, unchanged SHA-256, original notice/manifest, full CC0 text reference, measured bounds/counts and runtime transform in asset docs. Extend the visible Urban Street credits in all three shipped languages. Ship only used model files; keep screenshots and visual audit reports local.
8. Add and pass a named daylight real-map scenario showing an actual normally streamed shelter, including roof, glass, front opening, bench and support contact. Add an opposite-side/rotated mapped shelter view if one scenario cannot prove both orientations; include a bench-only/unsheltered control. No injected prop or simulation changes to obtain evidence.
9. Scenario readiness must identify the actual shelter row, full source geometry/materials in the completed visible chunk, correct orientation/scale, DEM ground contact, active camera/layer and unobscured useful shelter coverage, plus normal map/weather checks. Inspect each passing screenshot and `result.json`; import/compilation alone does not verify appearance.
10. Run focused Godot/source and licence checks; independent tester PASS precedes focused commit/push. Preserve unrelated shared edits and keep audit evidence local.

## Tests to add
- `godot/tests/bus_stop_shelter_glb.gd::test_source_and_provenance`: exact complete source counts/materials/hash and retained notices, inventory and fi/en/de credits; fails on primitive substitution, lost glass/bench or missing attribution.
- `::test_footprint_placement`: translated, rotated and opposite-side rectangles verify full horizontal containment, uniform scale, opening direction and grounding; invalid footprints are skipped. Fails on flipped openings, distortion, floating supports or NaN vertices.
- `::test_controls_and_cache`: shelter replaces old roof/posts once, bench-only and absent-shelter controls remain intact, immutable source cache reused across repeated builds. Fails on duplicate seats, extra shelters or per-build source changes.
- Named real-map visual scenarios above verify actual chunk integration, readable glass/frame/seat and grounding after readiness; they fail without the GLB integration.

## Out of scope
New stop placements, bus stations/hubs, arbitrary canopy replacement, new interactive seats, traffic/pedestrian behavior, collision changes, general bench replacement, unrelated Urban Street items and historical audit rewrites.
