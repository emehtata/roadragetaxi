# Terrain and road smoothing (render only)

Spec: docs/specs/terrain-road-smoothing.md. Commits: de198485 (terrain), 5c7aedac (roads).
Nothing on the server changed except a one-sample border on the render grid; the simulation, routing,
collision and traffic rules still use the raw OSM geometry.

## Terrain
- Mesh: a regular 20 m grid (`Buildings3D.TERRAIN_STEP_M`) laid on the `ground_heights` nodes, each cell
  split along its NE-SW diagonal. 25 x 25 cells per 500 m chunk: 1250 triangles (3750 vertices, triangle
  soup), down from about 4096 triangles of the old subdivided quad. 10 m and 5 m were not measured: the
  80 m DEM has no detail finer than 20 m and no creases showed at 20 m.
- Normals: central differences at the grid nodes (`terrain_gradients`), bilinear between them
  (`terrain_normal`). Only level flat-layer triangles of the `ground` and `road` keys (all three corners at
  the same height, under 0.05 m) take them; kerbs, bumps, walls and every other key keep flat normals.
- Seams: `map_chunks._ground_heights` sends 28 x 28 samples, origin one step outside the chunk. The 26 x 26
  inner samples are unchanged. Neighbours share border nodes and slopes, so edge heights and normals agree
  (godot/tests/dem_terrain.gd checks within 1e-4).

## Roads
- `MapChunk.smooth_road` runs on each whole way in world metres before `_compact`, so every chunk and
  every consumer (2D strokes, snow, markings, 3D asphalt, bridge decks) gets the same points.
- Centripetal Catmull-Rom (alpha 0.5) through knots that bend 3-45 deg. These knots stay bit-identical:
  the endpoints, points shared by two ways in the chunk message, corners over 45 deg and every original
  point. Each segment gets up to 16 samples, about 4 deg of turn or 2 m each. A segment whose curve would stray more
  than min(0.5 m, half width / 4) from it stays straight.
- `Buildings3D._road_strip`: one continuous strip per road, mitred joints up to 2 x half width, a bevel
  triangle in each wedge beyond that, capped by half width past both ends (as before). Markings, rails and
  kerbs keep `_ribbon`.

## Measurements
Headless benchmark (synthetic sloped 500 m chunk, 10 roads, `Buildings3D.build`, mean of 5): build
74 ms before, 72-74 ms after the terrain commit, 64 ms after the roads commit. Visual scenarios on the
RTX 5060 (terrain_oulu_dem80, _off, _curve, _curve_snow): 490-550 fps average, p99 1.9-3.0 ms.
terrain_testhill_walk_dem80, 3 runs each after a warm-up, both checkouts in the same kind of worktree:
17bb84b3 median 80.5 fps (worst 61.2), p99 median 22.2 ms (worst 32.0); 5c7aedac median 78.9 fps
(worst 78.1), p99 median 22.1 ms (worst 23.1). The median fps is 2 % lower, within run-to-run noise.
A top-down view across a chunk border (y = 7201000 m on the Oulu hill road) shows no crack, seam
or step in the ground or road.

## Known limitations
- Puddles and bridge ends use the raw OSM points (endpoints match; puddles within 0.5 m).
- Junctions are collected per chunk message: a junction just across a chunk border may be missing from
  the neighbour's message, so that chunk can curve the way slightly differently near it.
- Snow and plough alignment along the smoothed points is not proven: terrain_oulu_curve_snow renders at
  +6 C with no ground snow.
- The scenario screenshots are top-down over forest; tests, not screenshots, prove the terrain smoothing.
