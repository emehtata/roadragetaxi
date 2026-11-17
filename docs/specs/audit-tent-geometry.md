# Tent profile and entrance

## Goal
Fix VQA-026: the static tent has a recognizable fabric profile and entrance instead of a flat-topped cuboid. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: replace only the `tent` cuboid in `props()` using existing triangle/quad helpers.
- `godot/tests/run_tests.gd`: add/register focused tent geometry and preservation checks; explicitly update the tent fingerprint in the caravan preservation control.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse camping target matching and existing cameras for an actual mapped tent with visible roof and entrance.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/tent-geometry/`: diagnosis, labelled comparisons, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace `populate_camp_pitches()` → streamed `scenery_objects` → `map_chunk.prepare()` ground props → `_structures()` → `props()` and the final chunk mesh. Record the generic cuboid cause, current 2.4×2.0×1.3 m client dimensions and authoritative 3.2×2.4 m `CAMPING_SIZES` envelope. Compare the existing 2D tent's ridge, two fabric faces and entrance convention.
2. Give the tent a pitched fabric roof with a ridge along the row's length and a distinct entrance on its forward end. A simple ridge tent and dark inset doorway/opening are sufficient. Front, sides and elevated views must read as a tent; a flat roof, box with painted markings or invisible/buried entrance does not qualify.
3. Preserve the row centre/heading, existing 2.4×2.0 m base and 1.3 m maximum height; all geometry stays inside the server's oriented 3.2×2.4 m envelope. Fabric panels meet the ridge/end surfaces within 0.005 m, the base meets flat ground, and the entrance remains visible without z-fighting. Use the existing tent palette; keep normals/winding valid and triangles nondegenerate.
4. Reuse static mesh construction and existing helpers. Preserve shadows, row contracts, server pitch/access decisions, 2D output, the repaired caravan-with-car and all other props/live vehicles. Keep geometry generation bounded with no per-frame work, new assets or dependencies.
5. Verify headings 0, π/2, π and 0.73, translated positions and flat/nonzero constant ground through `props()` and the final chunk build. Footprint containment, ridge profile and entrance orientation survive transformation; chunk rebuild/unload/reload retains stable geometry.
6. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated production-builder views plus a normal-distance perspective sample. Inspect roof/entrance recognizability, panel contacts, grounding and shadow visibility; retain historical audit evidence unchanged.
7. Pass and inspect a named real-map daylight 3D scenario with an actual `tent` row from normal mapped camp-pitch generation. Reuse Nallikari's sourced camping pose if suitable; record actual pitch ID/provenance, coordinates, angle and footprint. Label generated equipment accurately; no synthetic tent receives mapped-target credit.
8. Readiness must match the actual rendered tent geometry and row, active 3D, useful projected roof/ridge and entrance size, pitch containment, ground placement and clear frustum/HUD/building/dynamic-body sightlines. Retain normal map/time/weather/chunk checks; counts or projected hidden geometry do not qualify. Exclude rejected captures.
9. Record revision, renderer, dimensions, measured profile/footprint, commands and results. Parse changed scripts; run focused geometry/preservation plus existing camping/scenery/ground/chunk checks. Preserve player userdata/shared edits; independent tester PASS precedes atomic commit/push. Follow the traffic-law guide's footprint/access guidance without changing or certifying allocation/parking behavior.

## Tests to add
- `godot/tests/run_tests.gd::test_tent_profile_and_entrance`: inspect actual triangles for sloped fabric planes, raised ridge, distinct forward entrance, nondegenerate visible faces, contacts, grounding and oriented footprint across the placement matrix; the current cuboid must fail.
- `godot/tests/run_tests.gd::test_tent_geometry_preserved`: verify other-prop/live-vehicle controls, original dimensions/palette, final terrain placement and stable chunk rebuild/unload/reload. Update the intentional tent control hash only after the new geometry assertions pass.
- Named readiness rejects absent/wrong-kind/wrong-angle, inactive, hidden/buried/offscreen or undersized roof/entrance targets; only an inspected passing screenshot counts.

## Out of scope
VQA-027–033 and other findings, detailed tent interiors, poles/guy ropes/artwork, tent entry/gameplay, new assets/data sources, camping allocation/access/routing changes, terrain conformance redesign, new cameras and renderer refactors. Visual evidence samples recorded map/lighting conditions.
