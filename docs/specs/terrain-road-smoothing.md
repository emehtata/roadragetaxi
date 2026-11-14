# Terrain and road smoothing (render only)

Goal: smoother DEM terrain shading and smoother road curves in the 3D view, with the DEM profile, road
alignment, server geometry and simulation unchanged. Brief: docs/road-smoothing.md. Read alongside:
AGENTS.md, .github/copilot-instructions.md, docs/visual-testing.md.

## Audit findings
- T1 Flat normals cause most of the faceting: buildings_3d.gd:2013-2015 run `flat_normals()` (:2183) on every key,
  `ground` and `road` included, so each 14-20 m triangle has one shade and every crease shows.
- T2 The geometry is not aligned to the grid: `_ground` (:2450) emits the whole chunk as one quad and
  `subdivide()` (:2553) halves the longest edge down to 20 m (DEM_EDGE_M :2548). The vertices land off the
  20 m nodes, so the triangles cut across the bilinear cells (`ground_height` :2590) and the creases follow no
  grid line. Result: geometry is a secondary cause, normals the primary one.
- T3 Source data: 80 m DEM, block-averaged, 26x26 samples per 500 m chunk (map_chunks.py:680-693, step 20 m,
  corners shared with neighbours). A mesh finer than 20 m adds no elevation data; it only samples the bilinear
  saddle inside each cell (cm-scale differences).
- T4 Key `ground` also holds kerbs, bus-bay kerbs and fences (`_raised_strip(..., "ground")` :2496, :2510), so
  smooth normals applied to the whole key would round off vertical faces.
- T5 Seams: no normal can be continuous today; a grid with no neighbour samples has only one-sided gradients
  at the chunk edges. `ground_heights` is used only by map_chunks.py (grep src/), so it is render data.
- R1 Roads are one quad per OSM segment: `_ground` road loop :2459-2479 calls `_ribbon` (:3281). There are no
  joins, so every bend leaves an open wedge on the outside and a doubled overlap on the inside.
- R2 2D roads: map_chunk.gd `_draw_roads` :1481 strokes the same `road["points"]`. Snow plough clipping
  (:1496) and markings (:2465-2477) use the same points; puddles and `bridge_ends` come from the raw message
  (:306-307). Bridge decks: :803-807.
- R3 Each chunk receives whole ways in world coordinates; `_compact` (:424) shifts them to the chunk origin and
  `_clip_to_bounds` (:472) cuts them at the border. Smoothing the whole way before both steps gives every
  chunk the same curve, so the border needs no extra handling.

## Commit 1: terrain
- map_chunks.py `_ground_heights`: add a 1-sample apron (cols+2, origin -step). The current samples stay
  identical; nothing on the server uses this data.
- buildings_3d.gd `_ground`: when a grid exists, emit the base ground as a regular grid at 20 m spacing aligned
  to the grid nodes (diagonal always NE-SW) instead of one quad. Without a grid: unchanged.
- New `static func terrain_normal(grid: Dictionary, at: Vector2) -> Vector3`: central-difference normals at the
  grid nodes (they use the apron), bilinearly interpolated between nodes.
- Normals pass (:2013): for `ground` and `road`, a vertex whose pre-drape y < 0.05 (flat layer, same test as
  DEM_GAP_SCALE) gets `terrain_normal`; all other vertices (kerbs, bumps, walls) keep flat normals. Other keys
  stay unchanged.
- Spacing: 20 m by default. Measure 10 m and 5 m too (const TERRAIN_STEP_M); move to 10 m only if the
  dem80 screenshot still shows creases and the build-time budget below holds.
  Indexed vertex/triangle counts per chunk: 20 m 676/1250, 10 m 2601/5000, 5 m 10201/20000. As triangle
  soup (the current pipeline): 3750 / 15000 / 60000 vertices. The current subdivided quad is about 2500 tris.

## Commit 2: roads
- map_chunk.gd: new `static func smooth_road(points: Array, fixed: Dictionary) -> Array`, run on every road's
  world points before `_compact` (whole way, world coords, deterministic). Every consumer gets the result
  through `road["points"]`: 2D strokes, snow, markings, 3D ribbon, bridge decks.
- Algorithm: centripetal Catmull-Rom (alpha 0.5). Knots that stay exactly where they are: both endpoints, every
  point shared with another way (intersection, collected per chunk message), points where the bend exceeds 45 deg
  (protected corners) and layer/bridge change points. Only runs between protected knots whose bends are
  between 3 and 45 deg are splined. Adaptive sampling: subdivide until each sub-step turns <= 4 deg or is
  <= 2 m long, with at most 16 samples per segment.
- Overshoot guard: if any sample lies more than min(0.5 m, 0.25 * half_width) from the original polyline,
  that segment stays straight.
- buildings_3d.gd: new `static func _road_strip(out, points, half, h, color, uv, uv2)` replaces the
  per-segment `_ribbon` for asphalt. It offsets one continuous strip, mitres each joint with a limit of
  2 x half, and falls back to a bevel triangle beyond that. Markings, rails and kerbs keep `_ribbon`
  along the smoothed points.
- Puddles and `bridge_ends` stay on the raw points (endpoints preserved; puddles within 0.5 m). This is a known limitation.

## Acceptance criteria (brief numbering)
1. dem80 screenshot: no visible triangle facets; at any grid node, mesh height equals the sample within 1 mm.
2. Every smoothed sample lies within min(0.5 m, 0.25 * half_width) of the OSM polyline; endpoints are exact.
3. Shared intersection points stay at bit-identical positions in all ways that share them.
4. Terrain vertices and normals on a shared chunk edge agree within 1e-4 between neighbours; road strip
   ends at a border coincide within 1 mm.
5. dem_terrain road-on-slope check still passes (road 4-8 cm above ground); no z-fighting in screenshots.
6. Marking samples lie on the strip centreline; snow and wet use the same points (2D/3D screenshots).
7. No change under src/ except `_ground_heights`; `make test` and the traffic tests pass unchanged.
8. `make test` and `make godot-test` (with XDG_DATA_HOME=$(mktemp -d)) pass in full.
9. The scenarios below pass and their screenshots have been inspected, before and after, under the same conditions.
10. Chunk 3D build time +<=15 %; frame p95/p99 within +5 % of the baseline in each scenario.

## Tests to add
- godot/tests/dem_terrain.gd `test_terrain_normals_smooth_and_continuous`: on a sloped grid, the normals of
  adjacent triangles at a shared vertex are equal and neighbour-chunk edges match. Fails today (flat normals).
- dem_terrain.gd `test_kerb_keeps_flat_normals`: kerb side faces stay horizontal.
- godot/tests/road_strokes.gd `test_smooth_road_keeps_endpoints_and_corners`, `test_smooth_road_bounded_deviation`,
  `test_road_strip_no_wedge_gap`: the union of the strip covers a 30 deg bend with no hole. Fails today
  because of the per-segment quads.
- tests/test_map_chunks.py `test_ground_heights_apron`: cols = 28, and the inner samples are unchanged.

## Visual scenarios and performance
- `terrain_oulu_dem80` and `terrain_oulu_dem80_off` (existing).
- Add `terrain_oulu_curve`: the public main road Ylikiimingintie in mid-bend at pose [453287.5, 7201166.4, -1.884],
  taken from `visual_test.py find --city Oulu` output (not invented), same other fields as terrain_oulu_dem80. Add a
  `_snow` variant (weather snow) for the plough and snow alignment checks.
- Take the measurements before and after each commit: `stats.triangles` and the ground/road vertex counts from
  `meshes()`, the chunk build time (chunk worker timing log), and result.json frame p50/p95/p99 and FPS.
- Commands: `.venv/bin/python tools/visual_test.py run terrain_oulu_dem80 terrain_oulu_dem80_off terrain_oulu_curve`,
  `... compare A B`, `make test`, `XDG_DATA_HOME=$(mktemp -d) make godot-test`.

## Out of scope
Python physics, server road geometry, routing, collision and traffic rules; building or kerb normals; finer DEM
data; per-frame spline work.

## Status
- Tester verdict: PASS. Gaps closed by the implementer: docs in 4c54dc88; performance 2 % lower median on the hill walk.
- Chunk-edge view (criterion 4) is clean but top-down, and partly under trees; no side-on check of the seam.
- 10 m terrain spacing was not measured. Not needed: no creases appear at the 20 m grid.
