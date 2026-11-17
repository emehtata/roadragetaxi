# Caravan with towing car

## Goal
Fix VQA-025: the static `caravan_with_car` prop reads as a towing car joined to a separate caravan, with recognizable vehicle silhouettes. Deliver one focused correction commit.

## Files to change
- `godot/buildings_3d.gd`: replace only this prop's generic cuboid in `props()` using existing procedural mesh helpers; align its envelope with the server's camping footprint.
- `godot/tests/run_tests.gd`: add/register focused combination geometry and preservation checks beside scenery tests.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: reuse camping scenarios/cameras; add actual mapped combination target and visible-geometry readiness.
- `docs/visual-quality-corrections.md`, `docs/visual-quality-corrections/caravan-with-car/`: diagnosis, comparisons, accepted named capture/results and reproduction commands.

## Behaviour / acceptance criteria
1. Trace `populate_camp_pitches()` → streamed `scenery_objects` → `map_chunk.prepare()` ground props → `_structures()` → `props()` and final chunk mesh. Record why the generic 10.5 m cuboid loses both vehicles; compare `_draw_caravan()` and existing procedural vehicle helpers. Record the authoritative `CAMPING_SIZES` envelope of 9.4×2.5 m and the current client mismatch.
2. Replace the combination with a pale caravan body and visibly shorter/lower towing car along the existing row angle, joined by a slender drawbar/hitch. Include visible wheels, caravan window/roof detail, and car cabin/glazing so front, sides and elevated views distinguish both vehicles. Keep the space between their bodies open above the hitch; no single enclosing slab or ground-to-roof pedestal.
3. Keep the row centre/heading and contain every vertex, including wheels/hitch, within the server's oriented 9.4×2.5 m camping envelope; retain the existing 2.5 m maximum height. Use the existing camper/caravan palette and deterministic car-colour convention where practical. Wheels meet the flat support plane, bodies sit above it, and the hitch touches both vehicle assemblies within 0.01 m.
4. Reuse existing mesh helpers and static chunk-building patterns. Preserve normals, winding, shadows and bounded construction; preserve standalone caravan/camper/tent/other props, live vehicle output, 2D rendering, row contracts and server pitch/obstacle placement. No per-frame model construction or new assets/dependencies.
5. Verify headings 0, π/2, π and 0.73, translated positions, flat/nonzero constant ground and final production chunk placement. Rebuild/unload/reload produces stable geometry; combination bounds stay inside the authoritative footprint after transformation.
6. Capture labelled before/after front, rear, both sides, three-quarter, top and elevated production-builder views plus normal-distance perspective. Inspect recognizability, six or more visible wheel placements across the assemblies, hitch contact, ground contact and body separation; preserve historical audit evidence unchanged.
7. Pass and inspect a named real-map daylight 3D scenario with an actual `caravan_with_car` row from normal mapped camp-pitch generation. Reuse Nallikari if a mapped pitch produces the combination, or document another actual source. Record pitch provenance, complete footprint, target coordinates/angle and normal generation; do not insert a synthetic combination and label it mapped.
8. Readiness must match actual rendered combination geometry at that row, active 3D, useful projected car/caravan/hitch size, pitch containment, ground placement and frustum/HUD/building/dynamic-body clearance, retaining normal map/time/weather/chunk checks. Hidden geometry or counts alone cannot qualify; rejected attempts receive no credit.
9. Record revision, renderer, dimensions, footprint/contact measurements, commands and results. Parse changed scripts; run focused geometry/preservation plus existing camping/scenery/ground/chunk checks. Preserve player userdata/shared edits; independent tester PASS precedes atomic commit/push. Follow the traffic-law guide's footprint/access guidance; this display fix does not alter or certify parking decisions.

## Tests to add
- `godot/tests/run_tests.gd::test_caravan_with_car_recognizable_geometry`: independently inspect actual triangles for distinct caravan/car heights, open body separation, cabin/glazing/wheels, hitch contacts, grounding and authoritative oriented footprint across placement cases; the current cuboid must fail.
- `godot/tests/run_tests.gd::test_caravan_with_car_geometry_preserved`: unchanged other-prop/live-vehicle controls, static chunk ground placement and rebuild/unload/reload; reject missing components, out-of-pitch geometry or synthetic slab substitutes.
- Named readiness rejects absent/wrong-kind/wrong-angle, inactive, hidden/buried/offscreen or undersized targets; only a passing inspected screenshot counts.

## Out of scope
VQA-026–033 and other findings, standalone caravan redesign, detailed interiors/artwork, real vehicle reconstruction, new assets/data sources, live towing/parking/routing behavior, camping allocation changes, terrain conformance redesign, new cameras and renderer refactors. Visual evidence samples recorded map/lighting conditions.
