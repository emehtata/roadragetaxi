# Low-poly CC0 animal models

## Goal
Replace the procedural 3D shapes of fox, small_bird, roe_deer and horse with four CC0 low-poly GLBs from grab3d.com. All other species keep the procedural shape. Python simulation, 2D drawing and animal audio are untouched.

## Species mapping
| Game species | Source | Note |
| --- | --- | --- |
| fox | `low-poly-fox` | direct |
| small_bird | `low-poly-bird` (European robin) | direct; wildlife.gd BIRDS member |
| roe_deer | `low-poly-deer` | substitute (deer, not strictly roe); accepted |
| horse | `low-poly-horse` | `animal_arrays("horse")` mount at buildings_3d.gd:1302 and stand-alone horses |
| hare | `low-poly-rabbit` | substitute (rabbit); added at the user's request |
| squirrel, pigeon, moose, crow, duck, gull, dog | procedural | no CC0 low-poly found; do not substitute another species |

Excluded: `crow-on-perch` (user rejected), `fox` (high-detail, manifest only), any non-CC0 model.

## Files to change
- `godot/assets/animals/{fox,small_bird,roe_deer,horse}.glb` (renamed copies of the downloaded `low-poly-*.glb`) plus Godot `.import` files.
- `godot/assets/animals/SOURCES.md`: per model local file, grab3d URL slug, `CC0-1.0`, download date, triangles, and a "CC0 needs no attribution; credit grab3d.com as courtesy" note. Also record that grab3d's manifest says the models are AI-assisted derivatives (Meshy base mesh, reduced in Blender), `ai_content: true`.
- `godot/assets/animals/<name>.manifest.json`: verbatim copy of each grab3d manifest.json (licence record per model).
- `godot/buildings_3d.gd`: `animal_arrays(species, color, pose, size, detail)` (line 1362) and the `animal()` row batching (line 1272). Add `const ANIMAL_MODELS := {...}` (preload per species, as vehicles do at line 487) and a `static func _model_arrays(species, color, pose, size) -> Dictionary` that flattens the GLB mesh into the same array dictionary the procedural path returns.
- `docs/license-open-items.md`: add the four entries or link to SOURCES.md.

## Loading approach
1. `preload` once per species at script load; no per-frame file access.
2. Flatten the GLB's MeshInstance3D surfaces once, cached by key `species|color|pose|size|detail` (the existing `_animal_rows` key), and append to the existing batched rows, so there is no new node per animal.
3. detail 1 (within 40 m of the view centre): model arrays. detail 0 (far): keep the existing procedural low-detail shape, so no per-animal triangle cost beyond 40 m (about 3k tris each; budget below).
4. Missing or unparseable GLB: fall back to procedural, with one warning per species.
5. Palette texture: use the GLB's own colours; `color` (coat) tints only via vertex colour multiply when the species has coat variation (fox, deer, horse); the bird is untinted.

## Scale and orientation (normalisation step, done once at load)
Manifest dimensions are `x(width) x y(length) x z(height)` as grab3d lists them but axes must be read from the mesh AABB, not trusted. The bird's `0.052 x 0.139 x 0.095` is plausible for a robin only if 0.139 is length; verify.
- Rotate so the nose points along the same local axis the procedural shapes use (heading rotates about UP), feet at y=0.
- Scale to the procedural body length from the table at buildings_3d.gd:1388 times `size`: fox about 0.9 m long, roe_deer about 1.2 m, horse 2.0 m body (about 1.45 m shoulder), small_bird 0.3 m long (the old procedural bird size, so it reads on screen; real robin proportions kept, the mesh is 0.139 m long).
- Horse mount: a ridden horse keeps the procedural shape (the model's back is 0.3 m lower at 2.0 m length), so the rider's seat stays at the existing saddle offset; only unmounted horses use the GLB.

## Acceptance criteria
1. fox, small_bird, roe_deer, horse render from the GLB at detail 1; all other species render exactly as before.
2. Each model's post-normalisation AABB length is within 10% of the target length and its minimum y is within 1 cm of ground.
3. The nose points along the travel heading (a FLEE animal moves head first).
4. A horse mount (procedural) still seats the rider within 5 cm of the previous saddle height.
5. Same-key animals are batched: N foxes of one key add one row group, not N nodes.
6. A frame with 30 animals in view adds under 100k triangles at detail 1 and no extra per-frame allocation after the first frame.
7. Deleting a GLB makes that species fall back to procedural with one warning and no error.
8. SOURCES.md and a manifest copy exist for every shipped GLB, each stating `CC0-1.0`; a test fails if a shipped GLB has no CC0 record.

## Tests to add
- `tests/test_animal_models.py`: `test_every_animal_glb_has_cc0_manifest` (fails if a GLB lacks a manifest or the licence is not `CC0-1.0`); `test_sources_lists_every_glb`.
- Godot headless `godot/animal_models_test.gd` (follow the existing `*_test.gd` pattern; run with `XDG_DATA_HOME=$(mktemp -d)`): `test_model_aabb_scale` (criterion 2, fails if the bird is left at 0.05 m or the horse at 2.4 m), `test_model_faces_heading` (3), `test_unmodelled_species_use_procedural` (1), `test_missing_glb_falls_back` (7), `test_rows_batched_per_key` (5).

## Visual scenarios (tools/visual_scenarios.json; no wildlife scenario exists)
- Add `wildlife_models_day`: city or rural pose with the four species placed in front of the camera within 40 m (spawn via the server `--no-auto-fetch` test hook or a debug argument), `requires` the animal count in view. Readiness must pass per docs/visual-testing.md.
- Regression: `walk_city_street_day` and `drive_power_poles_day` must be unchanged (no animals), proving no cost without wildlife.
- Inspect the screenshot and JSON snapshot; check scale next to a car or person and the horse with rider.

## Out of scope
Animation or rigging, procedural substitutes for missing species, replacing squirrel/pigeon/hare/moose/crow/duck/gull/dog, any non-CC0 or high-poly model, crow-on-perch, 2D sprites, server behaviour, audio.
