# Road / ground visibility (terrain through 3D road)

**Goal:** At-grade road and flat-layer triangles sit above the DEM terrain mesh at every point, not
only at their own vertices. Rendering only; the server stays as it is.

## Cause (failure mode: terrain penetration, the road and the ground use different height sources)
- The terrain mesh is planar triangles on the 20 m grid nodes, each cell split NE-SW
  (`godot/buildings_3d.gd:2620-2630` `_terrain_grid`). Inside a cell the ground is linear per triangle.
- Road vertices come from `_road_strip` (`buildings_3d.gd:3378`) at `h = ROAD_M + 0.002*rank`
  = 0.012-0.028 m (`:2466`, `:2490`). They are only split to edges of 20 m or less, at arbitrary positions
  (`subdivide`, `:2012`, `:2581`), then lifted by bilinear `ground_height` (`:2026-2027`, `:2676`).
  The DEM gap x3 makes the road 0.036-0.084 m above the ground *at its vertices*.
- Between road vertices the road is a chord. The terrain mesh has its own creases at the grid lines and
  diagonals, and its triangle surface differs from the bilinear surface by up to the twist
  (h00+h11-h01-h10)/4 at mid-cell. A road triangle that crosses a crest, or a cell with twist, sinks under
  the ground mesh. With slope change ds over a 20 m chord the gap is ds*L/4 (5 % gives 0.25 m). A 1 m twist
  gives 0.25 m. Both are 3-6 times the 0.036-0.084 m lift. This is the green floor and snow inside the
  grey road in screenshot_1794678419263000064 (forest road on a slope, 2026-11-14).
- Not the cause: z-fighting (the gap is centimetres, but the ground actually comes out on top), chunk seams
  (the grid comes from the server with an apron, `terrain_gradients` comment `:2633`), or missing triangles.
- The existing test `tests/dem_terrain.gd:62` checks only road vertices on a linear slope. It cannot catch this.

## Fix (geometry-correct)
1. `static func terrain_mesh_height(grid: Dictionary, at: Vector2) -> float` in buildings_3d.gd: the
   height of the `_terrain_grid` triangle under `at` (same NE-SW split, same nodes).
2. `static func split_to_terrain(out: Dictionary, key: String, extras: Array, rect: Rect2) -> void`:
   clip the triangles of `out[key]` along the grid lines x, y = node + k*20 m and the cell diagonals,
   with the attributes interpolated as in `subdivide`. Use it instead of `subdivide` for "road" and "ground"
   (`:2011-2012`).
3. The "ground"/"road" keys take `terrain_mesh_height` in the drape loop (`:2027`). Every road triangle then
   lies inside one terrain triangle, parallel to it at the layer offset. DEM_GAP_SCALE/LIFT stay
   as they are (they keep the layers in their order).
4. Decks, bridges and kerbs keep their current path. Bridges ride their deck. Tunnels and level != 0 are unchanged.

## Files
- `godot/buildings_3d.gd`: the two functions above, and the drape loop in `build()`.
- `godot/tests/dem_terrain.gd`: the new test.
- `tools/visual_scenarios.json`: a new scenario, `road_ground_oulu_slope`.

## Acceptance
1. `test_road_above_terrain_mesh_everywhere`: grid with a crest and a twisted cell (heights e.g.
   `5*sin(c*0.7)+r*c*0.05`), a curved 3-point road crossing nodes. At the road's sample points (each
   triangle's vertices, edge midpoints and centroid, 1 m along the strip edges) road y >= ground mesh y
   (`terrain_mesh_height`) + 0.03 m. It fails today (gap < 0 at crest midpoints).
2. `test_road_lies_on_sloped_ground` and the rest of dem_terrain.gd still pass, and so does `make godot-test` in full.
3. Use the registry scenario `terrain_oulu_dem80` (Ylikiimingintie hill), plus a new `road_ground_oulu_slope`.
   Its pose comes from `visual_test.py find --city Oulu --near <public hill road, city coordinates>`.
   Take before and after screenshots from the same pose in third-person (key 1), top-down (2) and driver
   eye (3). The readiness checks must pass, and no ground colour may show inside the road.
4. Chunk build time (`stats`) is within +20 % of before on the same scenario.

## Commits
1. Test: road above the terrain mesh at its sample points (fails).
2. Buildings3D: drape road and flat layers on the terrain mesh triangles.
3. Visual scenario road_ground_oulu_slope.

## Commands
- `XDG_DATA_HOME=$(mktemp -d) make godot-test`
- `PYTHONPATH=src .venv/bin/python tools/visual_test.py find --city Oulu --near X Y --radius 800`
- `PYTHONPATH=src .venv/bin/python tools/visual_test.py run terrain_oulu_dem80 road_ground_oulu_slope`

## Out of scope
Trees and lamps on bilinear heights, server physics, the DEM resolution, and a global road offset.

## Status (2026-11-14)
- Verdict: PASS (tester). `test_road_above_terrain_mesh_everywhere` fails on the old geometry and passes on the new.
- Commits 0e98e15f (test), 33b4217f (drape), ec585432 (scenario) are on origin/release/v0.22.0beta.
- Top-down (key 2): the olive ground showing through the road was the bug; fixed.
- Third-person (key 1) and driver-eye (key 3): do not show the bug in the chosen poses (no regression seen).
- Build cost: +9 % on `stats` (limit +20 %).
- `make check` and `XDG_DATA_HOME=$(mktemp -d) make godot-test`: green.
