# Cozy Retro Cars variety

## Goal
Add suitable Grab3D Cozy Retro Cars GLBs as stable visual variants of existing ordinary cars in normal shaded 3D play, alongside the seven Cozy Cars primary styles.

## Files to change
- `godot/assets/vehicles/cozy_retro_cars/`: selected unchanged GLBs, imports/textures, original manifests/notices, full CC0 text and measured provenance.
- `godot/buildings_3d.gd`, `godot/entity_layer.gd`: reuse existing model variants, merged-mesh caches and pools; pass stable vehicle identity into ordinary-car model selection and adapt measured materials/lamp attachments.
- `godot/assets/vehicles/SOURCES.md`, `tools/license_inventory.json`, `godot/i18n.gd`, `godot/startup.gd`: source selection, runtime transforms and displayed fi/en/de attribution.
- `godot/tests/cozy_retro_cars.gd`, `godot/tests/manifest.txt`, affected existing vehicle checks: source, selection, state, fit and reuse coverage.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: relevant named fleet day/night and dense-traffic readiness/scenario hunks only.
- This spec and any visual audit reports/images remain local; preserve unrelated shared worktree edits.

## Behaviour / acceptance criteria
1. Inspect actual downloads from [Cozy Retro Cars](https://grab3d.com/kits/cozy-retro-cars/) before selection. Target one extra variant per existing ordinary body family: saloon→1980s Sedan; city_car→1990s Compact Car; hatchback→1980s Hatchback; estate→1980s Station Wagon; sports→1990s Sports Car; suv→1990s SUV; pickup→1990s Pickup Truck; panel_van→1990s Delivery Van. Evaluate the matching 1990s alternatives if a listed 1980s candidate fails fit. Record each precise rejection; ship only usable referenced assets, with at least four distinct added body families.
2. Measure imported bounds, triangles/surfaces, source forward axis, wheel contacts and material/texture layout. Listings advertise roughly 15–20k triangles and 2K PBR; do not treat “Lightweight” as a budget guarantee. Prefer an offered lighter variant only when actual source detail remains adequate.
3. Reuse `MODEL_VARIANTS`/`model_variant()` or the same small existing selection pattern. Pass actual stable NPC identity through `car()`; use a separately salted identity hash so selection is not correlated with the existing `CAR_SHAPES` hash remainder. Every selected family retains its current primary model and reaches its retro variant across representative IDs.
4. The same ordinary NPC retains its model across moving, parked, braking and redraw/reload states. Player and competitor taxis keep the existing primary saloon and roof-sign behavior. Calls without an identity retain their original primary mapping. Normal live and parked NPCs share this safe visual selection; do not infer parking/movement rules in Godot.
5. Preserve server vehicle type, identity, dimensions, pose, lamp bits and collision footprint. Use uniform source scale fitting length/width within the established 15% discrepancy rule, stable yaw, source-ground contact, existing road/deck elevation and pitch/roll. Reject a silhouette that needs distortion, oversized road intrusion or incorrect cargo/passenger role.
6. Keep every selected authored part, node transform, UV, normal/tangent and texture through cached per-material merging. Body tint affects intended paint only; keep glass, seats, two-tone/wood trim and tires intact. Measure retro material names/atlas colors rather than assuming Cozy Cars names. Record any intentional source-part exclusion and cover it with geometry checks.
7. Head/tail/brake/reverse/left/right states follow existing `LAMPS_*` bits and stay dark when off; support white or yellow authored headlamp lenses. Reuse the existing shader/overlay path with measured per-source lens masks and attachment locations. Preserve material isolation between simultaneous vehicles; avoid disconnected bumper lamps or always-emissive atlas parts.
8. Retain primary Cozy Cars mappings, static camping sources, non-car vehicle variants, explicit 2D/unshaded `car_arrays()` and taxi camera behavior. No new scene nodes/material clones per frame; warm repeated frames reuse bounded model pools and immutable meshes/materials.
9. Archive exact page/download URLs (`https://grab3d.com/dl/<slug>/<slug>.glb`), retrieval date, unchanged SHA-256, original `manifest.json`/`LICENSE.txt`, full CC0 legal text, measured counts/bounds and runtime transforms. Record selected Cozy Retro Cars/Grab3D/CC0 attribution in asset docs and displayed Finnish, English and German credits; inventory only shipped files.
10. Add named retro fleet daylight/night scenarios at the existing sourced Helsinki car-lineup location, using production `car()` identity selection. Every added model must be usefully visible across one or more captures; readiness checks actual selected pool/source geometry, requested identity, ground/heading and lamp state. Use a fixture only for client display/state checks; retain normal real-map readiness and map evidence.
11. Inspect passing named fleet screenshots and isolated front/side/rear views for every selected source; verify off/on/brake/reverse/indicator states, paint/trim and wheel/glass visibility. Retain a taxi chase control. Follow `docs/visual-testing.md`: failed readiness/cropped targets do not count.
12. Run the same native-GPU representative traffic/fleet workload before/after with fixed identities, count, resolution/settings, warmup and interval; record p50/p95/p99, draws/primitives and memory. Investigate >10% p95 regression or new pool growth/stalls before shipment; no hidden vehicle caps or dropped geometry. Run focused checks, retained Cozy Cars/taxi/vehicle controls and licence/manifest checks; independent tester PASS precedes commit/push.

## Tests to add
- `godot/tests/cozy_retro_cars.gd::test_source_geometry_and_fit`: selected source counts/material attributes, uniform fit/forward/ground and tilt/deck contacts; fails on unused imports, missing parts or distorted/floating models.
- `::test_identity_selection_and_controls`: stable independent identity selection reaches primary/retro variants for each selected family, moving↔parked/reload stability, no-ID defaults and taxi/2D/camping controls; fails on flicker, hash correlation or primary replacement.
- `::test_lamps_paint_and_pool_reuse`: dark/on/brake/reverse/side states contact source bodies, paint/trim isolation and stable nodes/meshes across mixed repeated frames; fails on state leakage, detached lights or per-frame allocations.
- `::test_provenance_and_credits`: exact hashes/manifests/CC0/inventory and displayed fi/en/de credits; fails on source drift, unused shipped files or missing attribution.

## Out of scope
New vehicle kinds/spawners, traffic or parking decisions, server physics/dimensions, emergency liveries, taxi replacement, wheel/door animation, whole-kit bulk import, new variant framework and unrelated renderer/audit cleanup.
