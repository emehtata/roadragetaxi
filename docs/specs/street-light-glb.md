# Street Light GLB and suitable Urban Street objects

## Goal
Replace the procedural 3D street-lamp poles with the supplied Grab3D Street Light GLB, preserving working lighting and mapped placement. Review directly matching Urban Street objects and replace only those that fit existing uses.

## Files to change
- `godot/assets/props/`: selected GLBs/imports/textures, original notices/manifests, measured provenance and CC0 text; extend `SOURCES.md`.
- `godot/buildings_3d.gd`: cached source geometry/materials, lamp transforms/emission and existing prop/bollard routing for suitable selections.
- `godot/map_chunk.gd`: main-thread resource preparation and bounded lamp/prop batch application, preserving async lifecycle and broken-lamp filtering.
- `godot/i18n.gd`, `godot/startup.gd`, `tools/license_inventory.json`: displayed fi/en/de attribution and shipped-file coverage.
- `godot/tests/street_light_glb.gd`, `godot/tests/manifest.txt`, affected lamp/prop assertions in `run_tests.gd` and `dem_terrain.gd`: focused regression coverage.
- `godot/visual_test.gd`, `tools/visual_scenarios.json`: named real-map day/night views and selected-prop readiness, relevant hunks only.
- Local correction notes/evidence: measured selection/rejection decisions and screenshots; keep audit reports/images local.

## Behaviour / acceptance criteria
1. Inspect the actual [Street Light](https://grab3d.com/models/city/street-light/) GLB before integration; the listing states 5,280 triangles, 2K PBR textures and W/D/H 0.40/2.21/8.16m. Measure imported parts/materials, transforms, base, arm axis, panel position and emission; retain every authored source part, UV, normal/tangent and texture through batching.
2. Normal 3D street lamps use that full model, uniformly scaled to the established lamp height. Orient the curved arm toward the road using each existing row direction; its LED panel must align with the row's luminaire position and pooled light origin. Measure and document the resulting base offset rather than assuming the old 1.2m outreach. Ground the base on the existing DEM and ensure no floating head, disconnected arm or distorted pole.
3. Preserve map rows, reach, collision decisions, map-level separation, broken-lamp identities and reload/reset behavior. A broken lamp contributes neither model nor light; its neighbor remains intact. Add no client physics or inferred street equipment.
4. LED emission is dark by day and follows the existing artificial-light fade at dusk/night. Preserve pooled downward SpotLights, nearest-lamp hysteresis/fade, intensity/color/range policy and existing light queries; keep the visible panel and the actual light colocated on slopes. Do not create a light per model or rebuild geometry every light update.
5. Cache immutable source meshes/materials on the main thread; use the established per-material batch/instancing patterns. Preserve worker safety, bounded mesh upload, layers/shadows and stale-build rejection through sync/async build, replacement, knockdown, unload and reload. No per-pole scene/material clones or resource creation on workers.
6. Inspect [Urban Street](https://grab3d.com/kits/urban-street/) candidates with existing placements: Park Bench for `bench`, Bollard for mapped bollards, and Wave Bicycle Rack for `bicycle_parking`. Measure actual GLBs and select only compatible models; retain and explain each rejected kind, shipping no unused candidate assets.
7. A selected bench preserves the 1.4x0.45m seat envelope, seat height0.46m, existing heading/front side, sitter hip contact and `backrest=no` rows. Use separable source backrest only if available; retain the procedural no-backrest branch when necessary. A selected bollard preserves mapped base,0.9m height, reflectors and existing knocked-post removal. A selected rack must accommodate all four existing bicycle slots at X=-1.2,-0.4,0.4,1.2m without fabricated hoops, clipping or model distortion.
8. Retain incompatible kit items explicitly: modular road tiles cannot replace arbitrary mapped road geometry; generic shelters/traffic apparatus require corresponding authoritative placement/state. Keep previous rack/crossing rejections unless the newly inspected source resolves their precise mismatch. Add no scenery populations or traffic rules.
9. Record exact page/download URLs, retrieval date, unchanged SHA-256, original `manifest.json`/`LICENSE.txt`, full CC0 legal text, measured counts/bounds and runtime transforms. Add selected model/Grab3D/CC0 attribution in asset docs and visible Finnish, English and German credits; inventory only shipped files.
10. Pass and inspect named real-map daylight/night lamp views with the complete pole, arm and head readable; readiness verifies exact selected source geometry/materials, actual row/direction, base DEM contact, panel/light alignment, active camera/layer and useful unobscured coverage. Also verify a broken-lamp control and each selected extra prop in its real mapped use; no injected map placements.
11. Inspect source front/side/rear views and daytime/off/night emission. Run relevant source, transform, state, lifecycle, lighting-pool and licence/manifest checks. Compare the same native-GPU lamp-dense workload before/after with matching population/settings/readiness; report p50/p95/p99, draws/primitives, memory and chunk build times, investigating >10% p95 regression or streaming stalls before shipment.
12. Independent tester PASS precedes focused commit/push. Preserve unrelated shared edits and local audit evidence; if any traffic-control or interaction behavior changes become necessary, stop that expansion and obtain the project traffic-law review.

## Tests to add
- `godot/tests/street_light_glb.gd::test_source_geometry_and_placement`: exact source counts/material attributes, uniform source fit, rotated/translated/sloped DEM base and panel/light alignment; fails on primitive substitution, lost parts or floating/misaligned lamps.
- `::test_day_night_broken_and_pool_state`: day/dusk/night emission, pooled light policy and broken lamp removal without affecting neighbors; fails on always-lit panels, detached light, extra lights or state leakage.
- `::test_batch_lifecycle_and_controls`: sync/async rebuild, stale results, repeated chunks, unload/reload, immutable cache reuse and 2D controls; fails on duplicate/missing poles or per-frame resource growth.
- `::test_selected_urban_prop_fit`: selected bench/sitter/backrest, bollard and four-slot rack contracts; fails on wrong facing/seat height, clipped parked bicycles or lost knocked state.
- `::test_provenance_and_credits`: source hashes/notices/CC0/inventory and displayed fi/en/de credits; fails on unused shipped assets or missing attribution.

## Out of scope
Road/map generation, new street objects/populations, traffic-control decisions, collision/routing/parking changes, lighting-system redesign, blanket kit import and historical audit rewrites.
