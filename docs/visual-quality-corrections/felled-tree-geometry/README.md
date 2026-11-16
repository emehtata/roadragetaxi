# Felled tree trunk (VQA-018)

The felled trunk now lies along the declared fall direction, retains its intended length and round cross-section, rests on the flat support plane and intersects its crown. The historical audit is retained. Named visual acceptance passes; independent tester review follows implementation.

## Diagnosis and correction

The production path is server `knocked_trees` → `main.gd` → `map_layer.set_knocked_trees()` → `map_chunk.set_fallen()` → the tree layer's redraw → `_trees_3d()` → `tree_parts()` → `trees_node()` MultiMeshes. The cached trunk is a six-sided unit cylinder whose length lies on local Y. The existing `lying` basis already rotates that axis into the fall direction. `Basis.scaled()` then scales world axes, compressing the rotated length by `radius * 0.18` while stretching a radial direction by `trunk_top`. At radius 1.4, a birch's intended 2.24 m cylinder becomes a 0.252 m sliver with a roughly 2.24 m vertical cross-section. The defect is a scale-space error, not an incorrect server fall angle.

The three-line correction uses `scaled_local()`, sets the trunk centre to ground + radius × 0.09 (the cylinder's half-width), and brings the existing crown centre from `trunk_top + radius` to `trunk_top + radius × 0.7`. The last change allows the horizontal trunk's cap to intersect the actual tapered polygonal crown, rather than meeting the crown's horizontal bound at a different height. Crown mesh, scale, colour and vertical placement remain unchanged; the centre moves 0.3 radii toward the trunk. Standing trees, shrubs, bollards, forests, seasonal processing, meshes, material/shadow settings and lifecycle have no production changes.

The spec's original AC2 sign was corrected during implementation after checking the actual helpers: server `(cos(angle),sin(angle))` is converted into client `(cos(angle),-sin(angle))`; `to_3d(p)` returns `(p.x,height,p.y)`. The resulting Godot vector is **(cos(angle),0,-sin(angle))**. Both existing crown placement and corrected cylinder use this convention.

## Checks and inspected comparison views

- [Original regression](regression-before.log): **1,202 checks, 576 failures**. [Corrected Linux regression](regression-after.log): **1,202 checks, 0 failures**. Ground contact uses a strict 1 mm tolerance. The new checks use transformed cylinder cap endpoints, its actual mesh vertices and convex crown triangles; cap-rim vertices inside the crown prove surface intersection. They cover birch/pine/spruce, radii 0.6/1.4/2.5, four angles, translated positions, ground heights 0/17 m and near/far modes. Controls preserve standing trees, shrub/bollard output, colours, counts and shadows; existing obstacle fall/reset/reload and forest regressions run alongside.
- [Native regression](regression-native.log): **1,490 checks, 0 failures**, including the uploaded MultiMesh transforms. Dummy Linux rendering does not retain these transforms, so that extra assertion runs only with a real display driver. Existing resource/shader-cache shutdown warnings remain recorded.
- [Manifest pytest](pytest.log): **3 passed**. Changed scripts parse and `git diff --check` passes.
- All **96 comparison panels** were inspected: eight before/after angles for all three species at both near/far modes, using production `trees_node()` and its materials. They show a horizontal visible trunk entering the crown from side, three-quarter and elevated views. End views show a round cap rather than the original vertical sliver. Near and far felled models share the intended same presentation. [Birch near](review/birch_near_1.png), [birch angles](review/birch_near_2.png), [pine near](review/pine_near_1.png), [pine angles](review/pine_near_2.png), [spruce near](review/spruce_near_1.png), [spruce angles](review/spruce_near_2.png); matching far sheets are in [review](review/).

Captures use native Windows Godot 4.7.2 Forward+ Vulkan / NVIDIA GeForce RTX 5060, 400×340 panels, three completed draw frames and full bounding-box frustum checks. [Fixture](fixture.json), [before captures](before/capture-results.json), [after captures](after/capture-results.json) and [manifest](manifest.json) record the source revision, camera and framing.

## Named map scenario

`vqa_felled_tree_day` uses the surveyed Bulevardi tree at **385679.6, 6671613.9**, from `tree-knocked-topdown`. It supplies a fixed `knocked_trees` display fixture through the existing map-layer state path, retains normal map/time/weather readiness and uses the existing 3D top camera. Readiness checks actual tree MultiMesh transforms, fall angle, active 3D display, ground contact, useful trunk/crown projected sizes, frustum, HUD, building sightline and nearer dynamic bodies. Building clearance uses cached triangle BVHs of actually visible chunk meshes with the building material; terrain and road materials are excluded. This audit-only check avoids accepting hidden geometry while avoiding false positives from overestimated footprint/roof volumes. The existing flat-terrain option isolates this geometry correction; arbitrary slopes remain outside this slice. Disposable settings protect player data.

[Accepted screenshot](gameplay/final/vqa_felled_tree_day/2026-06-20T1300_20261116-194504_89f15dfa-dirty/screenshot.png) and [readiness](gameplay/final/vqa_felled_tree_day/2026-06-20T1300_20261116-194504_89f15dfa-dirty/result.json): **PASS**, both inspected. The actual mapped birch is clearly visible, with its white horizontal trunk entering the crown and resting on the pavement. Empty errors; active 3D; fall angle **0.58 rad**; radius **2.948 m**; ground **0 m**; trunk **116.5×82.1 px**, crown **172.1×165.3 px**. The 1280×720 native capture uses the renderer above. Its ground check allows at most 5 mm clearance, alongside the regression's 1 mm tolerance.

The initial footprint-only check and a later conservative footprint/height estimate rejected this open road; diagnostic inspection showed their false building obstruction. Their wrappers ended without accepted results (exit 143) and their logs are retained. The diagnostic render is explicitly excluded. A first actual-mesh-clearance run passed and was inspected; the final accepted run repeats it with the tighter 5 mm ground guard. Only the linked final run receives acceptance credit. Direct mesh measurement confirms a cylinder vertex at local z=-0.5 maps vertically down, so radius × 0.09 gives exact support contact; all final checks use this geometry.

## Reproduction

```sh
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tools/_tmp_felled_tests.gd
.venv/bin/python -m pytest -q -n auto tests/test_godot_manifest.py
.venv/bin/python tools/visual_test.py run vqa_felled_tree_day --out docs/visual-quality-corrections/felled-tree-geometry/gameplay
```

Copy [focused-runner.txt](focused-runner.txt) to `godot/tools/_tmp_felled_tests.gd` to reproduce the targeted production regressions; remove the temporary script/UID afterwards. Run the same script with native Windows Godot for the uploaded MultiMesh assertions. For close captures use `res://tools/visual_quality_audit.gd -- <fixture.json> <output-directory>`; copy [before-capture-runner.txt](before-capture-runner.txt) to a temporary Godot tool for the exact original transforms. Convert absolute paths with `wslpath -w` for native Godot.

Finnish NPC traffic-law guidance was reviewed; no simulation, collision, fall decision, routing, road maintenance or map-layer behavior changes. Other audit findings and every map/terrain/lighting combination remain outside the sampled coverage. Independent tester PASS remains required before commit.
