# Hill visible in the first-person view (test hill)

## Goal
With terrain on, the windshield and on-foot views at the test hill (EPSG:3067 427666.0, 7210769.1) show the DEM slope.

## Root cause (measured)
- The DEM is fine: `load_ground(~/.cache/RoadRageTrip, "oulu", True)` gives a Dem80 instance with 3-16 m within 200 m
  (6.4 m at the point, 10.9 m at +100 m and 15.5 m at +200 m along the street, heading -0.576: about 4.5 m rise per 100 m).
- The game in the screenshot is the Windows Godot build. Its server runs `.venv-windows/Scripts/python.exe`, so
  `osm/cache.default_cache_root()` returns `%LOCALAPPDATA%\RoadRageTrip`. That folder has no `dem80/` and no
  `oulu.dem.json`, so `load_ground` returns None. The server then sends no `ground_heights`, `deck_height` returns 0 and the view is flat.
  The Linux settings.cfg mentioned in the task is not the one in use. The Windows one
  (`%APPDATA%\Godot\app_userdata\Road Rage Trip (Godot client)\settings.cfg`) is.
- The client path is correct once a grid arrives: `map_chunks._ground_heights` → `map_chunk.prepare` → `map_layer.deck_height` →
  `windshield_elevation` (car and on foot, main.gd 764-784) and the vertex lift in `buildings_3d.gd` ~1946.
- The scenario `terrain_testhill_walk_dem80` has `"city": "Helsinki"`, and its `why` text was copied from windshield_city_day. Its walk
  (4 s forward, min 3.5 m) moves the pose off the point.
- A missing DEM is silent: nothing is logged when terrain is requested but `load_ground` returns None.

## Fix
1. `osm/elevation.py load_ground`: when `dem80_enabled` and `<cache_root>/dem80/dem80.json` is missing, also try the
   `THEROADRAGETRIP_DEM80_DIR` env var. If none is found, log one warning that names the paths tried.
2. `tools/dem80.py` / Makefile: add `make dem80-windows`. It copies `~/.cache/RoadRageTrip/dem80` to
   `/mnt/c/Users/<user>/AppData/Local/RoadRageTrip/dem80` (the user found via `cmd.exe /c echo %LOCALAPPDATA%`).
   `make run` calls it on WSL when the target is missing.
3. `tools/visual_scenarios.json`: set `terrain_testhill_walk_dem80` to `"city": "Oulu"` and write an accurate `why`.
   Change the walk to `{"s": 3, "forward": 0.0, "turn": 0.0, "min_m": 0}` (stand at the point and look at the heading)
   with the pose heading up the street (east-south-east, uphill). Add `terrain_testhill_flat` with the same pose and terrain off.

## Files to change
- `src/theroadragetrip/osm/elevation.py`: `load_ground(cache_root, city, dem80_enabled) -> Ground | None`, adding the env fallback and the warning.
- `Makefile`, `tools/dem80.py`: add the `dem80-windows` sync target.
- `tools/visual_scenarios.json`: fix the existing scenario and add the flat one.
- `godot/visual_test.gd`: if a walk has `min_m: 0`, it does not need to move.

## Acceptance criteria
1. On Windows Godot via `make run`, the server log has no "no DEM ground" warning, and the debug snapshot at the point
   reports non-flat ground under the vehicle (`requires.dem_ground` readiness passes).
2. `godot-shot terrain_testhill_walk_dem80` renders a first-person view at 427873.5, 7210792.8 (heading -0.591), and the readiness checks pass.
   At the test point itself the walker faces a wall and a lamp post a few metres ahead, so the on-foot and raised-eye
   scenarios use this central street about 200 m east of it: the DEM rises about 4.7 m over its next 100 m.
   The ground visibly rises up the street, and the eye is within 0.5 m of the DEM height plus the eye height.
3. `godot-shot terrain_testhill_flat` renders the same pose with flat ground, for side-by-side comparison.
   `terrain_testhill_eye_dem80` / `_eye_off` are the same pair from a 4 m raised eye; with terrain on the street climbs to a crest,
   with it off it runs level. `terrain_testhill_dem80` stays at the test point and only checks that DEM ground is loaded.
4. Starting with terrain on and no dem80 anywhere logs exactly one warning and the ground stays flat (no crash).

## Tests to add
- `tests/test_dem_ground.py::test_testhill_chunk_grid_not_flat`: builds the chunk ground grid from a small synthetic
  Dem80 fixture that copies the measured samples around the point. At least one sample within 100 m differs from the
  point by at least 2 m. It fails if `_ground_heights` flattens or returns None.
- `tests/test_dem_ground.py::test_load_ground_env_fallback_and_warning`: with an empty cache_root,
  `THEROADRAGETRIP_DEM80_DIR` → Dem80. With no env var set → None, plus one warning in the log (caplog). It fails without fix 1.
- `godot/tests/dem_terrain.gd::test_eye_follows_ground`: builds a grid with 6 m at the point and 12 m at +100 m E, and sets
  `windshield_elevation = Buildings3D.deck_height(at, 0, [], grid)`. The camera y is checked against the
  ground plus eye_height at both points. It fails if the eye ignores the grid.

## Test commands
`make check`; `XDG_DATA_HOME=$(mktemp -d) make godot-test`; `godot-shot` for both scenarios.

## Out of scope
Finer DEM than 80 m, slope physics for the car, and bundling dem80 in releases.
