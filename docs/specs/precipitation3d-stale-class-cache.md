# Precipitation3D not found: stale class cache

## Goal
`res://main.gd` compiles after pulling commit ea1ab8fa. `Precipitation3D` must resolve in
`buildings_3d.gd` without a manual re-import.

## Diagnosis (reproduced with Godot 4.7.2, headless)
- `class_name Precipitation3D` exists at `godot/precipitation_3d.gd:5`. File, name and
  path are all correct. Nothing was renamed or is missing.
- Cause: `godot/.godot/global_script_class_cache.cfg` (gitignored) predates the new
  script, so it has 0 entries for `Precipitation3D`. `buildings_3d.gd:54` and `:89`
  use the bare class name and fail to parse. The failure cascades to
  chunk_detail.gd, map_chunk.gd and main.gd.
- The Makefile `godot/.godot/import-stamp` rule depends only on `*.import`
  sidecars. Adding a `class_name` script re-triggers nothing, so `make run` skips the re-import.
- `godot --headless --path godot --import` fixes it: the cache gains the entry and
  the `--quit` run has 0 errors.
- `docs/traffic-spawn-fix.md` is untracked and unrelated.

## Files to change
- `Makefile` (import-stamp rule, ~line 114-120): add every `godot/**/*.gd` that
  declares `class_name` as a prerequisite, e.g. `CLASS_SCRIPTS := $(shell grep -rl
  '^class_name' godot --include=*.gd --exclude-dir=.godot)`. Update the comment.
- No GDScript change. A `preload` in buildings_3d.gd would work but diverges from the
  13 other `class_name` scripts. Keep the convention.

## Acceptance criteria
1. `/home/ubuntu/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --version` prints 4.7.2.
2. With `godot/.godot/global_script_class_cache.cfg` and `import-stamp` deleted,
   `make godot/.godot/import-stamp` runs the import, and the cache then contains `Precipitation3D`.
3. After that, `godot --headless --path godot --quit` prints no `SCRIPT ERROR` or `ERROR`
   lines, and `res://main.gd` loads.
4. Touching a `class_name` script (`touch godot/precipitation_3d.gd`) makes
   `make -n godot/.godot/import-stamp` list the import command. Before the fix it printed nothing to do.
5. The existing Godot test runner (`godot/tests/run_tests.gd`, including
   `test_precipitation_3d`) and `pytest -n auto` pass.

## Tests to add
- No new GDScript test. The existing `godot/tests/precipitation_3d.gd` uses a
  `preload` and so passes even with a stale cache. That is why it missed this.
- Add a shell check `tools/check_class_cache.sh`, run from the Makefile test target:
  every `class_name X` in `godot/*.gd` appears in `global_script_class_cache.cfg`.
  It fails without the fix when the stamp is stale (criterion 4 scenario).

## Out of scope
- Converting `class_name` uses to `preload`.
- Committing `.godot/` to git.
- `docs/traffic-spawn-fix.md` and any traffic behaviour.
