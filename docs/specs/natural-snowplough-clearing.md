# Natural snowplough clearing

## Goal
Plough tractors clear a lane that follows the path they drove, about one blade wide
with soft edges. Today they clear whole 10 m grid squares (screenshot_1794596659220999936).

## Current behaviour / cause
- `src/theroadragetrip/weather.py:387-399` `plow_road` samples the move every 2 m and marks
  the whole **10 m world-grid cell** as cleared (`plowed_cells[(floor(x/10), floor(y/10))]`).
- `weather.py:383` `road_snow_at` looks up that cell. `protocol.py:667` sends `plowed_cells`.
- `godot/map_chunk.gd:1385-1409` `set_road_snow` and `:1435-1446` `_draw_roads` (2D) restroke
  each road's `snow_segments` clipped to the cell, at the full road width.
- `map_chunk.gd:926-950` `_road_snow_3d` (3D) writes one R8 texel per 10 m cell, and
  `road.gdshader:17,120` samples it with `filter_nearest`. Both views show hard
  axis-aligned 10 m squares that step across junctions and both carriageways.

## Design (choices)
- Blade width **3.5 m** (`PLOUGH_BLADE_M = 3.5` in weather.py), centred on the tractor path.
- Server: `plowed_cells` is replaced by `plowed_paths`, a bounded `deque(maxlen=2048)` of swept
  segments `(x0, y0, x1, y1, level)`. A tick that moves less than 1 m extends the last segment
  instead of adding one. `road_snow_at` uses the segments within 2 m of the point (2 m blade
  half-width plus the feather), found through a dict that maps 10 m cells to segment indices.
  The cells are only an index; they are never rendered.
- Protocol: `plowed_paths: [[x0,y0,x1,y1,level], ...]` replaces `plowed_cells`. Values are
  rounded to 0.1 m.
- 2D: for each path inside the chunk, draw a polyline of width 3.5 m in the cleared-snow colour,
  clipped to drivable roads (drawn in the road layer, above the snowy road and below the markings).
  Add round caps or soft ends so the strip has no square ends.
- 3D: build the chunk's `snow_cells` mask at **1 m per texel** (at most 256x256, so 1 m texels
  for chunks up to 256 m across) by rasterising each segment as a capsule with radius 1.75 m
  and a 0.5 m linear feather. Switch the shader sampler to `filter_linear`.
- Budget: rebuild the mask only when the chunk's set of paths changes (as today). At most
  64 segments are rasterised per chunk per frame; the rest carry over to the next frame.
- Snow decay in `weather.py:448-451` (`min(cleared_at, road_snow)` and `clear()`) applies to
  `plowed_paths` in the same way.

## Files to change
- `src/theroadragetrip/weather.py`: `plow_road`, `road_snow_at`, the decay at 448, the new deque and index.
- `src/theroadragetrip/protocol.py:667`: send `plowed_paths`.
- `godot/map_layer.gd:15,344,541`: rename to `plowed_paths` and pass them on.
- `godot/map_chunk.gd`: `set_road_snow(depth, paths)`, `_draw_roads` strip, `_road_snow_3d` 1 m mask.
- `godot/road.gdshader`: `filter_linear`, with `cell_map` scaled for 1 m texels.
- `godot/tests/road_snow_render.gd`: update the tests for paths.
- `tools/visual_scenarios.json`: add the scenario below.

## Acceptance criteria
1. A plough driving 50 m diagonally (at 30 degrees) gives `road_snow_at` == 0 on the path and
   at 1.5 m from it, and the full `road_snow` at 3 m from it, including inside the same 10 m cell.
2. No cleared point lies more than 2 m from the plough path. Because a diagonal corridor has
   no axis-aligned rectangle, this rules the 10 m squares out.
3. Before and after a junction turn, the cleared area follows the turn; the opposite lane of
   the same road stays snowy.
4. `plowed_paths` never exceeds 2048 entries, and the payload contains no `plowed_cells`.
5. The 3D mask texel at the path centre is 0 cover, the one 3 m off is full cover, and the
   one 2 m off is a value between them (the feather).
6. Visual: scenario `snowplough_cleared_lane` shows a dark lane with soft edges along the
   tractor's track and no grid squares. The screenshot counts only after its readiness checks
   pass, and it must be inspected.

## Tests to add
- `tests/test_weather.py::test_plough_clears_corridor_not_grid_cells`: covers criteria 1-2. It fails
  today because the whole 10 m cell is cleared.
- `tests/test_weather.py::test_plough_keeps_opposite_lane_snowy`: covers criterion 3.
- `tests/test_weather.py::test_plowed_paths_bounded_and_serialised`: covers criterion 4 (with protocol).
- `godot/tests/road_snow_render.gd::test_plough_mask_is_feathered_corridor`: covers criterion 5.
- `tools/visual_scenarios.json` `snowplough_cleared_lane`: real city-centre roads,
  `--test-snow-depth 10`, a tractor ploughing for 20 s with `--screenshot-drive`.

## Commands
`make check`; `XDG_DATA_HOME=$(mktemp -d) make godot-test`;
`godot-shot --scenario snowplough_cleared_lane`, then inspect the PNG and its JSON.

## Out of scope
Plough routing, NPC traffic rules, snow banks or windrows at the road edge, sidewalk clearing,
and the tractor model.

## Status
- Implemented in 943caec0. Tester verdict: VERDICT: PASS. `make check` passes.
- Screenshot: `visual-test-results/snowplough_cleared_lane/2026-01-15T1200_20261113-211929_a22a7996-dirty/screenshot.png`
  (inspected: dark lane with soft edges, no 10 m squares).
- Four departures from this spec were judged acceptable by the tester.
