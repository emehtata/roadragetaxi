# Windows release: 3D view by default, animals packed, I key

## Goal
A release started from the in-game menu, a shortcut or the exe shows the 3D outdoor
view (3D cars, scenery, animals) with no flag, and the I (windshield) key works.

## Diagnosis
- Menu start: startup.gd `_start(mode)` launches the game in the same process as
  the exe; main.gd `_ready` (l.188-230) only sets `MapChunk.outdoor_3d` and calls
  `buildings_3d.use_shaded()` for `--outdoor-3d` / `--rtx`. No flag, no 3D: the
  installer's shortcut parameters (2a90f0b3) cover only shortcuts.
- I key: main.gd l.552 calls `_set_windshield`, which returns at once when
  `not MapChunk.outdoor_3d` (l.648). Same root cause as above; nothing else
  breaks the key. Confirm by running the release build with `--outdoor-3d`.
- Animals: buildings_3d.gd `_animal_model` (l.1421) uses `load(path)` guarded by
  `ResourceLoader.exists`. export_presets.cfg uses `all_resources`, which should
  already pack imported .glb, but this is unproven; vehicles use `preload`, which
  is certain. Make it certain for animals too, and test the exported pck.

## Files to change
- godot/main.gd: 3D on unless `--outdoor-2d` is given (new flag, replaces the
  need for `--outdoor-3d`, which stays accepted and is a no-op). Do it in one
  place before the arg loop: set `outdoor_3d = true` and `use_shaded()`.
  Keep the `graphics` setting `buildings_3d` behaviour.
- godot/buildings_3d.gd: `ANIMAL_MODELS` holds `preload("res://assets/animals/x.glb")`
  PackedScenes (or a const dict of them); `_animal_model` drops `ResourceLoader.exists`.
- godot/export_presets.cfg: all three presets keep `include_filter` plus
  `assets/animals/*.glb, assets/animals/*.png` (belt and braces).
- Makefile: `run-2d` passes `--outdoor-2d`; `run` unchanged. tools/visual_test.py:
  pass `--outdoor-2d` when `view == "2d"` instead of adding `--outdoor-3d` for 3d.
- installer/RoadRageTrip.iss: drop `Parameters: "--outdoor-3d"` (harmless to keep).

## Acceptance criteria
1. A client started with no args has `MapChunk.outdoor_3d == true` and
   `Buildings3D.opaque == true` after `_ready`, whatever start path the menu takes.
2. `--outdoor-2d` gives `outdoor_3d == false` and the old 2D view.
3. With no flags and the taxi driving, KEY_I turns the windshield view on and
   off (`_windshield.visible` toggles).
4. `Buildings3D._animal_model("fox")` returns a non-empty model without
   `ResourceLoader.exists`; no "stays procedural" warning for the five species.
5. The exported Windows pck lists every `assets/animals/*.glb` (or its `.scn`
   import) and the five palette textures.
6. Existing tests and scenarios that pass `--outdoor-3d` still pass.

## Tests to add
- godot/tests/release_3d_default.gd `test_default_is_3d`: instantiate main with
  no user args; fails today (outdoor_3d false). `test_outdoor_2d_flag`: with
  `--outdoor-2d` it is false. `test_i_key_toggles_windshield`: sends KEY_I;
  fails today because `_set_windshield` returns early.
- godot/tests/animal_models_packed.gd `test_animals_preloaded`: every
  `ANIMAL_MODELS` entry is a PackedScene without calling `load`; fails with
  the path-string version.
- tests/test_export_presets.py `test_presets_pack_animals` (pytest, no Godot):
  parse export_presets.cfg, each preset's include_filter covers assets/animals
  .glb and .png and exclude_filter does not match them; fails today.
- tools/check_export_pck.sh (run by the release workflows after export): run
  `godot --headless --path godot --export-pack "Windows Desktop" /tmp/x.pck`,
  then list it (e.g. a GDScript reading it with PCKPacker-less `ProjectSettings.load_resource_pack`
  and `ResourceLoader.exists` on all five GLBs); non-zero exit when one is missing.

## Visual scenarios (tools/visual_scenarios.json)
- `wildlife_models_day` (exists): all five animals in view as GLB models.
- `windshield_city_day` (exists): I-key view renders with no `--outdoor-3d`.
- New `menu_start_3d_day`: copy `forest_3d_day` but without the harness adding
  any 3D flag (a `"no_view_flag": true` key honoured by tools/visual_test.py);
  requires 3D cars in view. Screenshot inspected per docs/visual-testing.md.

## Out of scope
- Removing the 2D renderer; changing graphics settings UI; macOS/Linux
  installers beyond the shared preset filter; other missing-asset audits.
