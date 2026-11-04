# OSM altitude in 3D rendering

## Goal
Make real ground elevation visible in the 3D view (hills, road grades) while
keeping the existing layer/bridge/tunnel deck heights, with flat ground as the
fallback. Render-only: the simulation stays 2D.

## Findings (wiki.openstreetmap.org/wiki/Altitude)
- OSM stores height only as tags: `ele` (EGM96 geoid, metres) and `ele:wgs84`,
  mostly on sparse nodes (peaks, survey points, stations). The wiki says
  point `ele` is not rendered anywhere because it gives no continuous
  coverage; renderers use a DEM (SRTM, Viewfinder Panoramas) for terrain.
- `layer`/`bridge`/`tunnel` are relative stacking, not altitude. The project
  already uses them: `osm/build.py` parses `layer`, `map_chunk.bridge_ends_of`
  finds ramp ends, `buildings_3d.deck_height` lifts decks by `layer * DECK_M`.
- No `ele` or DEM handling exists in `src/theroadragetrip` or `godot/`.

## Decision
- Terrain source: an external DEM (Copernicus GLO-30 or NLS Finland 10 m),
  sampled offline into a per-map raster next to the cached map data.
  OSM `ele` nodes are not used for the ground (too sparse); skip them.
- `layer`/bridge/tunnel stay as today, added on top of the ground height.

## Files to change
- `src/theroadragetrip/osm/elevation.py` (new): `load_dem(path) -> Dem | None`,
  `Dem.height_m(x_m, y_m) -> float` (bilinear, relative to map-origin height).
- `src/theroadragetrip/map_chunks.py`: add a coarse `"ground_heights"` grid
  (e.g. 16 m spacing, float list + origin + step) to each chunk message;
  omitted when no DEM.
- `godot/map_chunk.gd` (`prepare`): read the grid; helper
  `static func ground_height(grid: Dictionary, at: Vector2) -> float`.
- `godot/buildings_3d.gd`: ground mesh, road ribbons, building bases and
  `deck_height` results get `+ ground_height(...)`; bridge ramp ends use the
  ground at the end point. Car/pedestrian nodes sample the same grid.
- `tools/visual_scenarios.json`: scenario `terrain_hill_bridge_day` at a real
  hilly spot with a road bridge (city-centre coordinates only).

## Acceptance criteria
1. No DEM file: chunk messages have no `ground_heights`; 3D output is
   byte-identical to today (flat ground, existing decks).
2. With DEM: `height_m` at a raster cell centre equals the cell value; between
   cells it is bilinear; outside raster returns the nearest edge value.
3. Neighbouring chunks share edge samples, so ground and roads have no seams
   or steps at chunk borders.
4. A layer-1 bridge deck sits `DECK_M` above interpolated ground and ramps to
   ground at its ends; a tunnel stays below ground.
5. Chunk build time does not regress by more than 5% (bounded per-frame work).
6. Scenario `terrain_hill_bridge_day` passes its readiness checks and the
   screenshot shows a visibly sloped road and a deck above sloped ground,
   inspected per docs/visual-testing.md.

## Tests to add
- `tests/test_elevation.py::test_bilinear_and_edge_clamp` - fails without
  `elevation.py` (criterion 2).
- `tests/test_map_chunks.py::test_ground_heights_absent_without_dem` and
  `::test_ground_heights_shared_at_chunk_edge` (criteria 1, 3).
- `godot/tests/run_tests.gd`: `test_deck_height_adds_ground` - deck at layer 1
  on a 10 m grid equals `10 + DECK_M` (criterion 4).

## Out of scope
- Physics, routing, speed or fuel effects of slopes (sim stays 2D).
- Rendering OSM `ele` points, contour lines, hillshading.
- `incline` tags, `level`, building `min_height`/`roof` changes.
- Downloading DEMs at runtime; DEM fetching is a manual/offline tool step.
- Uncommitted car glazing, GLB, car LOD and sky cloud work in the tree.
