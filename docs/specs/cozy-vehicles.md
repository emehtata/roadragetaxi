# Cozy Vehicles: tractor and plough body

## Goal
Replace the remaining procedural plough-tractor body with Grab3D Cozy Vehicles' Tractor GLB, also using that source for ordinary tractors. Preserve the existing working blade, beacon and server-owned vehicle state.

## Files to change
- `godot/assets/vehicles/cozy_vehicles/`: selected Tractor GLB, import/texture sidecars, source manifests/notices, measured provenance and full CC0 text.
- `godot/buildings_3d.gd`: cached tractor source, measured fitting/material/lamp data, GLB routing for plough tractors and attachment-only plough/beacon details.
- `godot/assets/vehicles/SOURCES.md`, `tools/license_inventory.json`, `godot/i18n.gd`, `godot/startup.gd`: selection/provenance and visible Finnish, English and German credits.
- `godot/tests/cozy_vehicles.gd`, `godot/tests/manifest.txt`, affected tractor assertions in `godot/tests/run_tests.gd`: source, placement, state, reuse and compatibility coverage.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: bounded tractor/plough readiness and named views using existing sourced map poses.
- Local correction notes/evidence: measurements and rejected candidates; keep audit reports/images local and preserve unrelated shared edits.

## Behaviour / acceptance criteria
1. Record the current inventory accurately: ordinary road vehicles already use GLBs in shaded 3D; true remaining procedural bodies include plough tractors, trams and road ferries. This kit has no compatible tram or open-deck road ferry; retain those rather than substituting Steam Train or Fishing Boat. Do not import unrelated cars, emergency vehicles or machines without an existing matching role.
2. Inspect the actual [Tractor](https://grab3d.com/models/vehicles/tractor/) download from [Cozy Vehicles](https://grab3d.com/kits/cozy-vehicles/), listed at 32,784 triangles/2K textures. Measure dimensions, forward axis, wheel contacts, child transforms, materials and source lamp locations; use an offered lighter variant only after verifying retained details. Select it only if uniform scale fits the existing 4.0×2.2 m tractor footprint within the established 15% discrepancy rule without oval wheels or road intrusion.
3. Both ordinary and ploughing shaded-3D tractors use the selected complete GLB through existing merged-mesh caches/pools. Remove the plough exception that routes the whole body through `vehicle_arrays`; retain only its functional blade/beacon geometry as GLB attachments. Keep the explicit unshaded/2D fallback and other model mappings intact.
4. Preserve all authored mesh parts, node transforms, UVs, normals/tangents and textures. Tint intended paint only; keep cab glass, cream roof, tires, engine and trim distinct. Native lamp masks/overlays follow existing on/brake/reverse/indicator bits, remain dark when off and sit on measured source lenses.
5. Preserve Python vehicle dimensions, position, heading, road/deck elevation, identity, motion, plough flag and beacon phase. Blade keeps the current six-segment angled form, width, reach and near-ground height; roof beacon contacts the selected roof and follows only existing `extra.beacon`. Source body, lamps and attachments remain aligned at translated/rotated/elevated poses. No client decisions about clearing roads or traffic priority.
6. Reuse cached immutable source meshes/materials and bounded pools; mixed ordinary/plough tractors with different colors/lamp states do not leak state, duplicate bodies, create resources every frame or leave attachments visible after switching off/unloading.
7. Archive exact page/download URLs, retrieval date, unchanged GLB SHA-256, original `manifest.json`/`LICENSE.txt`, CC0 legal text, measured counts/bounds and runtime transforms. Add selected source attribution to asset docs and displayed fi/en/de credits; inventory only shipped files.
8. Pass named daylight ordinary/plough and winter/night plough views at existing real-map road poses. Client display fixtures may supply tractor visual state, but normal map/time/weather/chunk readiness must pass. Readiness proves exact source triangle/material counts, vehicle transform/grounding, attached blade/beacon, requested light bits, useful unclipped coverage and current camera/layer. Inspect screenshots plus isolated front/side/rear views with beacon off/on and blade off/on.
9. Run focused tractor/source/state/reuse checks, existing vehicle/taxi/Cozy Cars controls and licence/manifest checks. Measure a matched native-GPU primary-versus-kit tractor/plough workload with identical count/IDs, map/settings/resolution/warmup/interval; report p50/p95/p99, draws/primitives and memory, investigating >10% p95 regression or pool growth before shipment.
10. Obtain tester PASS before atomic commit/push. Since the changed visual path includes ploughing, obtain the project traffic-law review confirming it draws existing server state and preserves the guide's road-maintenance/light policies.

## Tests to add
- `godot/tests/cozy_vehicles.gd::test_tractor_source_and_fit`: exact selected source geometry/materials, uniform scale, forward/ground contacts at translated/elevated headings; fails on primitive body, missing parts or distortion.
- `::test_plough_attachments_and_live_state`: blade/beacon geometry/contact and on/off/lamp isolation across ordinary↔plough transitions; fails on duplicate body, floating beacon, detached blade or stale state.
- `::test_tractor_pool_and_controls`: stable cached resources through repeated mixed frames and retained unshaded/2D/other-vehicle controls; fails on per-frame allocations, leaked attachments or unintended mapping changes.
- `::test_tractor_provenance_and_credits`: hashes/manifests, CC0/inventory and fi/en/de displayed attribution; fails on missing source records or unused imported assets.

## Out of scope
New vehicle types/spawning/variants, tram or ferry redesign, emergency liveries, physics/collision/traffic/plough-clearing changes, wheel/door animation, whole-kit imports and renderer refactors. If the actual Tractor fails suitability, report its measurements and retain the corrected fallback instead of shipping an unused model.
