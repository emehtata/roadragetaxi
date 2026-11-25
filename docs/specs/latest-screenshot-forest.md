# Forest missing from the latest screenshot

## Goal
Render the mapped Oulu woodland in `screenshot_1795634645578000128.png` with the shipped Cozy Nature GLB trees, fixing the dense forest path that currently bypasses the available source models.

## Files to change
- `godot/map_chunk.gd`: forest mask/preparation, row generation or async lifecycle only where the reproduction establishes the fault.
- `godot/buildings_3d.gd`: route near forest batches through cached Cozy Nature GLBs; preserve bounded distant LOD.
- `godot/assets/nature/SOURCES.md`: document the corrected dense-forest GLB boundary.
- `godot/tests/cozy_nature.gd`: require GLB source geometry in the forest path and retain seasonal/far controls.
- `godot/tests/forest_trees.gd`: focused regression for the identified failure, through the affected public pipeline.
- `godot/visual_test.gd`: readiness and result counts for visible forest geometry in a requested mapped target area.
- `tools/visual_scenarios.json`: named scenario `oulu_screenshot_forest_day` at the screenshot location; retain existing forest scenarios.
- `docs/visual-testing.md`: document any new forest readiness field.

## Behaviour / acceptance criteria
1. Reproduce from the newest PNG and matching JSON: taxi `[425360.4558, 7216744.0155, -3.31216944]`, Oulu, 2026-06-20 about 13:44, chase view. Validate this pose against the real road and preserve the reported viewing direction. Capture the faulty baseline or record the failing focused regression before fixing it.
2. Trace actual streamed woodland through landuse input, raster mask, prepared rows, finished forest batches, camera layers and LOD. Identify the first incorrect stage; do not infer the cause from a green ground fill or global tree count. The screenshot's Windows cache has a 16,155 m² forest whose visible part contains `[425319.37,7216782.75]`; revalidate that mapped interior and record its target bounds from real data.
3. The reported target is a mapped forest polygon with no surveyed tree rows. Its near path explicitly passed `kit=false`, so earlier primitive-crown captures did not verify the requested GLBs. The normally streamed forest at that target must contain deterministic rows and finished, visible `nature_kind` instances of the full Cozy Nature source meshes. The chase screenshot shows a wooded stand in the previously bare foreground/middle ground; a distant tree line alone does not satisfy the fix.
4. Preserve map-defined forest/wood boundaries and existing road, building, water and parking clearances. Respect real mapped clearings and nested landuse. Use existing cached GLB MultiMeshes, species, season and DEM transforms. Select GLBs only within a 72 m circle around a stable 32 m world camera cell; retain existing crowns for the remaining rows and simple far LOD beyond 400 m, with shared bounds so the ranges agree. Refresh only intersecting chunks on cell crossings, keep generation guards for stale workers, and release unpublished results on unload. Selected GLB visuals use the original crown meshes as shadows-only proxies to preserve the previous forest shadow cost and silhouettes. Measure native GPU dense woodland before/after with identical forest population, settings, pose, resolution and interval. Investigate >10% p95 regression before accepting the range. Prepare source resources on the main thread; workers read immutable caches.
5. Forests remain client-generated visual instances: no new simulation trees, collision objects, network tree records, forestry placements or traffic changes. Keep existing 2D rendering, surveyed GLB trees, felling and the forest graphics setting's current contract intact.
6. Loading, replacing and unloading/reloading the affected chunk restores the same forest population; season changes retain positions. Completed stale async work cannot replace newer state or attach to a freed chunk. Build/cache work remains bounded per chunk with no new per-frame tree generation or full-world scans.
7. Scenario readiness requires real target woodland, nonzero expected rows there, completed matching GLB source instance population and correct source transforms, active render layer, applicable visibility range and useful on-screen crown coverage in that target. Require normal map/camera/weather/terrain readiness too; global loaded-tree counts, non-trunk primitive crowns or test-forced `_trees_3d()` rebuilds do not establish production readiness. Record exact source counts, active layers/ranges and useful projected GLB coverage.
8. Run the named scenario using native Windows Godot; inspect its passing screenshot and `result.json`. Verify a representative existing dense-forest scenario and an open-ground/road control so the fix neither removes other forests nor fills clearings. Keep all screenshots, baseline captures and audit evidence local.
9. Pass focused forest and affected source checks, scenario JSON validation and `git diff --check`; independent tester PASS precedes focused commit/push. Preserve unrelated shared changes.

## Tests to add
- `godot/tests/forest_trees.gd::test_reported_forest_pipeline`: a small real-data-derived target fixture through prepare/setup and the faulty stage; fails on the demonstrated missing/hiding-forest defect, not merely on a helper signature.
- `godot/tests/forest_trees.gd::test_forest_clearance_and_lifecycle`: meaningful road/building/clearing control and affected replacement/reload regression; fails if the correction expands forest or loses its population during streaming.
- `tests/test_visual_scenarios.py::test_reported_forest_scenario_requires_target_geometry`: validates the real pose, target evidence and forest readiness contract; fails if a bare scene can pass on unrelated distant/loaded trees.

## Out of scope
New vegetation datasets or models, new tree models or placements, density/style redesign, wildlife, traffic/pedestrian logic, broad map-cache rewrites and historical audit changes.
