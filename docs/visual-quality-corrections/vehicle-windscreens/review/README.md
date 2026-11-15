# Windscreen correction: five-page independent review

These five numbered pages regroup **existing captures only**. No model, production code, test, scenario or renderer was changed, and no scene was recaptured. All pages fit within 2048×2048. The [machine index](index.json) records every source file, source crop, original pixel hash, destination rectangle and scale, plus freshly evaluated per-model preservation results. All exact crops and nearest-neighbour enlargements were checked byte-for-byte against their source pixels. The second independent tester reported inspecting pages 01–05, all 36 LOD frames, all five gameplay variants/results and the preservation table. Visual completion below is attributed to that parent-provided tester verdict; it does not claim an independent rerun of the geometry script.

Open the pages at 100% scale in this order:

- [x] [01: source/before/after — saloon, hatchback, estate](01_source-before-after_close.png) — 2000×1110, three rows. Columns: original imported front, original pooled front, repaired pooled front, repaired three-quarter, repaired top. All 15 panels retain their native 400×340 pixels.
- [x] [02: source/before/after — SUV, pickup, panel van](02_source-before-after_close.png) — same layout and native pixels.
- [x] [03: every model at six actual perspective/LOD distances](03_all-models_perspective-lod.png) — 1920×1860. Rows: saloon, hatchback, estate, SUV, pickup, panel van; six increasing distances across each row. Native 320×280 crops remove only constant background from each 640×480 frame; assertions confirm the full rendered object remains inside every crop. These are the same 36 frames from the six original LOD sheets, not new or magnified LOD captures.
- [x] [04: gameplay — hatchback, estate, SUV](04_gameplay_context-and-crops.png) — 1100×1170. Each row includes its accepted full scene at 50% for context, followed by an explicitly labelled 2× nearest-neighbour target crop. Judge fine glazing from the crop or linked original, not the thumbnail.
- [x] [05: gameplay — pickup, panel van, saloon player control](05_gameplay_context-and-crops.png) — same layout. The player saloon is an unchanged rear-view context control at native crop scale; its front glazing control is on pages 01 and 03. It is not a new front-view gameplay claim.

The regular frames can still be opened at full 1280×720 from the [original correction notes](../README.md#named-gameplay-verification). The five accepted results retain map/time/weather readiness, expected model identity, actual pooled-mesh screen bounds, and HUD/building clearance. The failed initial hatchback truck-envelope attempt remains excluded.

## Per-model coverage checklist

The visual rows below are credited to the second independent tester’s reported page review. “Preservation rechecked” describes exact data comparisons performed during gallery composition; fresh independent execution of the test commands is tracked separately below.

| Review | Model / finding | Close page and row | Perspective/LOD page and row | Gameplay page and row | Preservation rechecked |
|---|---|---|---|---|---|
| [x] | saloon control | 01 row 1 | 03 row 1 | 05 row 3 (rear context) | whole GLB SHA-256 unchanged; materials, transforms, vertices and all primitives unchanged |
| [x] | hatchback / VQA-001 | 01 row 2 | 03 row 2 | 04 row 1 | materials/transforms/original body records, 23 other primitives, before/after pooled bounds identical |
| [x] | estate / VQA-002 | 01 row 3 | 03 row 3 | 04 row 2 | materials/transforms/original body records, 23 other primitives, before/after pooled bounds identical |
| [x] | SUV / VQA-003 | 02 row 1 | 03 row 4 | 04 row 3 | materials/transforms/original body records, 23 other primitives, before/after pooled bounds identical |
| [x] | pickup / VQA-004 | 02 row 2 | 03 row 5 | 05 row 1 | materials/transforms/original body records, 22 other primitives, before/after pooled bounds identical |
| [x] | panel van / VQA-005 | 02 row 3 | 03 row 6 | 05 row 2 | materials/transforms/original body records, 25 other primitives, before/after pooled bounds identical |

## Material and bounds evidence

The `preservation_checks` array in [index.json](index.json) was freshly evaluated against `godot/tests/data/vehicle_windscreens.json` and both original capture manifests. For every row, node transforms and material definitions match their original fingerprints; existing painted-body vertex/normal prefixes match; all other primitive attributes/indices, including glass, match. The captured pooled AABB position **and** size match exactly before and after. The saloon's entire GLB hash matches too. Five repaired whole-file hashes correctly differ because their body faces were repaired.

| Model | Unchanged captured pooled size (length × height × width, m) |
|---|---|
| saloon | 4.6000 × 1.4031 × 1.8004 |
| hatchback | 4.6000 × 1.4636 × 1.8004 |
| estate | 4.6002 × 1.5881 × 1.7999 |
| SUV | 4.6000 × 1.8208 × 1.8003 |
| pickup | 5.3500 × 1.8142 × 1.8002 |
| panel van | 5.3500 × 2.2631 × 1.8000 |

The geometry assertions are in `godot/tests/vehicle_windscreens.gd`: `test_front_glazing_geometry`, `test_glazing_at_lod_distances` (every generated paint index set), and `test_model_preservation` (source/merged AABB and material surfaces). [regression-before.log](../regression-before.log) records five original-model failures; [regression-after.log](../regression-after.log) records zero. [existing-model-checks.log](../existing-model-checks.log) records the 40 existing pooling/glazing/dimension/range checks with zero failures; [taxi-model-parts.log](../taxi-model-parts.log) passes the unchanged control.

- [ ] Re-evaluate `tests/test_vehicle_windscreens.py::test_only_windscreen_body_indices_and_boundary_vertices_changed` against the original fingerprints.
- [ ] Re-evaluate `tests/test_vehicle_windscreens.py::test_repair_is_idempotent`.
- [ ] Run the Godot geometry and source/pooled preservation assertions.
- [x] Inspect all rows of pages 01–05 and the five passed gameplay results — the second tester confirmed clean windscreens, all 36 LOD frames within bounds, visible gameplay crops and a valid preservation table; no new visual finding was reported.

```sh
.venv/bin/python -m pytest -q -n auto tests/test_vehicle_windscreens.py tests/test_godot_manifest.py
/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --headless --path godot --script res://tests/vehicle_windscreens.gd
```

The previous tester reported five focused pytest passes and `make check` 2969 passed / 3 skipped with timing 62 passed; this gallery-only follow-up did not change code or rerun those suites. New checks validate source-pixel composition and the per-model preservation facts above. Distant silhouettes remain small at their actual perspective distance; exact generated geometry checks complement those views. Other audit findings, night/wet combinations and performance remain outside this slice.

## Fresh geometry validation and remaining tester handoff

The implementer reran `res://tests/vehicle_windscreens.gd` after the second tester verdict using Linux Godot 4.7.2 and a disposable `XDG_DATA_HOME`. It exited **0** and reported **vehicle windscreens: 0 failed**. The [fresh log](geometry-validation.log) and [machine record](geometry-validation.json) retain the exact command, engine version, timestamp, test/GLB hashes and implementer attribution. The temporary directory was removed after exit; no job remains running.

The independent tester must rerun that command, mark the geometry/preservation execution checks above from its own results, and record the final verdict. The current independent review status is **visual review complete, fresh geometry execution pending**. The unchecked test-execution boxes deliberately do not convert the implementer log or an inspected preservation table into an independent test run.
