# Complete visual quality audit

## Goal
Deliver the evidence-based audit required by `docs/3d-render-audit.md`: discover every renderable asset type, inspect feasible types systematically, and document genuine defects and explicit coverage gaps before corrective work.

## Files to change
- `docs/visual-quality-audit.md`: methodology, complete source-linked inventory, per-type coverage/status, defect register, summary, reproduction commands and limitations.
- `docs/visual-quality-audit/`: grouped PNG evidence, gallery index and machine-readable inventory/capture manifest; keep evidence available with the report.
- `godot/tools/visual_quality_audit.gd` and `tools/visual_quality_audit.py` (only if needed): isolated inspection/capture orchestration using existing production mesh builders/scenes; reuse existing showcase scripts where accurate.
- `tools/visual_scenarios.json`: append named real-map audit scenarios only where existing scenarios cannot cover a required gameplay view; preserve unrelated edits.
- No production asset, material, shader, scene, camera system or rendering implementation changes.

## Behaviour / acceptance criteria
1. Trace actual scene creation and drawing from `main.gd`, `map_layer.gd`, `map_chunk.gd`, `buildings_3d.gd`, `entity_layer.gd`, interiors, effects and UI into procedural generators, imported assets and dynamic variants. Record each individual semantic asset type, renderer/method, source and reachability; explain deduplication of cosmetic/animation variants and distinguish unused assets from live renderables.
2. Inventory all categories in the request, including vehicles/components, people, animals, buildings, roads/markings, terrain/vegetation, infrastructure/signs/lights, taxi/interactive props, construction, parking, water/shorelines, effects, interiors and other visible 2D/UI objects. Record absent categories with source-search evidence. Do not infer completeness from one directory.
3. Give each type a stable ID and one status: passed, defects, partially inspected, uninspected or unused/not reachable. Every inspected type links evidence and angle/lighting/distance coverage; missing coverage has a concrete reason. A representative category image cannot pass unshown asset types.
4. Generate legible grouped contact sheets with per-object IDs and descriptive category/angle/condition filenames. Each relevant 3D type receives front, rear, left, right, front/rear three-quarter, top and elevated views unless an individual angle is explicitly inapplicable. Complex/asymmetric types receive additional views as needed. No pass from one angle.
5. Use actual gameplay cameras for representative third-person driving views and existing first-person/cockpit/free/debug cameras where available. Inspect normal viewing and close distances; record applicable LOD/distance limitations. Do not introduce a gameplay camera.
6. Capture representative daylight, overcast, night and artificial-light conditions selected to expose material, visibility, light/shadow and transparency defects. Record which types each condition covers; do not claim an unrendered combination was checked.
7. Gameplay evidence must come from passing named scenarios in `tools/visual_scenarios.json`, with `result.json` readiness evidence under `docs/visual-testing.md`. Isolated sheets use explicit audit readiness assertions (expected instances, loaded resources, nonempty geometry, camera framing and completed draws), recording results separately from gameplay readiness. Failed captures are limitations, never passing evidence; attempt an alternative inspection method and record its outcome.
8. Inspect geometry/proportions/components/normals, materials/textures, lighting/shadows, alignment/grounding, culling/transparency/clipping and LOD. Judge against intended stylized realism; simple geometry alone is not a defect. Separate visual observation from suspected cause and artistic preference.
9. Every defect has a unique `VQA-NNN` ID, category/type ID, severity (Critical/High/Medium/Low), defect category (Geometry/Materials/Textures/Lighting/Shadows/Orientation/Camera/visibility/LOD/Other), observed angle/conditions, clear description, exact screenshot/panel and identifiable source/scene. No defect is asserted solely from code inspection.
10. Summary counts reconcile with inventory: discovered types, inspected types (including partial separately), passed types, types with defects, uninspected types, defects by severity/category and unresolved categories/reasons. Preserve raw captures or sufficient grouped evidence to independently assess findings.
11. Record commands, seeds/fixtures, camera poses, lighting, renderer/GPU, resolution, source revision and dirty-tree limitations. Preserve player saves/settings. Bound and clean up capture processes; remove throwaway scripts while retaining enough audit-only tooling/data to reproduce evidence.
12. Tester independently views the generated images, challenges passes, checks all inventory sources/categories and evidence coverage, verifies counts and documents additional defects in the register (or returns specific corrections). A documented limitation is honest coverage reporting, not permission to skip feasible categories. Final diff must contain no production rendering/asset changes and no unrelated shared-tree edits.

## Tests to add / checks
- `tools/visual_quality_audit.py --check` (or equivalent existing tooling): validate unique inventory/defect IDs, referenced files/panels, required metadata, coverage/status rules and reconciled counts; fail on missing evidence, a one-angle pass or inconsistent totals.
- Audit capture readiness assertions: fail on absent intended assets, unloaded resources, empty meshes or unframed objects rather than silently writing a successful capture.
- Run relevant existing named visual scenarios and inspect screenshots plus readiness results; the independent tester must inspect every evidence sheet and report coverage gaps.
- No corrective regression tests or production changes are part of this phase.

## Out of scope
Fixes, redesigns, asset replacements, new data sources, simulation/traffic decisions, new gameplay cameras, renderer refactors and performance benchmarking. Existing shared-tree changes are inputs/limitations, not owned edits.
