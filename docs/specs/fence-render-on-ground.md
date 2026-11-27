# Fence and hedge render: 3D railings stand on the DEM ground

## Goal
OSM fences, walls, hedges and boards drawn in the 3D view stand on the DEM
terrain (on by default, `game.terrain_dem80`). They should not be buried below it.

## Evidence
- A wooden fence (`barrier=fence`, `material=wood`, no `layer`, an open 3-node line, no
  gate nodes) is kept by `build_ways` as a `Railing(kind="wood_fence", layer=0)` with
  3 points; `_split_at_openings` does not split it.
- `map_chunks.py:359` streams it to the chunk of its first point. The client's
  `_draw_railings` maps `wood_fence` to the `fence` style and passes it to
  `B3.railings_node(rows)`. No layer filter applies.
- Root cause: `buildings_3d.gd railings_node` calls
  `_sloped_wall(out, a, b, thick, 0.0, 0.0, tall, color)`, so the base is at y=0.
  With DEM terrain the ground is at its real height (tens of metres on hilly ground),
  so every railing sits under the ground: missing from first person and from above.
  Lamps were fixed the same way in 5febd239 (`ground_height(grid, p)`).
  Trees get `ground_heights`; railings do not.

## Files to change
- `godot/buildings_3d.gd`: `static func railings_node(rows: Array, grid := {}) -> MeshInstance3D`.
  Pass `ground_height(grid, line[i])` and `ground_height(grid, line[i+1])` as `ha`/`hb`
  to `_sloped_wall`, so the wall follows the slope.
- `godot/map_chunk.gd` `_draw_railings`: `B3.railings_node(rows, ground_heights)`.
- `godot/tests/dem_terrain.gd`: new test (below).

## Acceptance criteria
1. With a DEM grid, each vertex of a railing segment has its lowest y within 0.05 m
   of `ground_height(grid, endpoint)`, interpolated along the segment.
2. With an empty grid the mesh is unchanged: base 0.0, top = style height
   (fence 1.2, wall 1.5, hedge 1.3, boards 1.1).
3. Broken wooden fences and hedges (the `_hedge_damage` fragments) are lifted too,
   because they go through the same rows.
4. 2D (non-3D) drawing is unchanged.
5. Render check (not committed): a first-person and a top render with terrain on, over
   hilly ground with a wooden fence beside a building, with the scenario's readiness
   checks passing. Before the fix the fence is missing; after it the fence stands
   beside the building. Screenshots stay out of the repo and out of PRs.
6. Public check: a public terrain scenario with roads shows roadside fences above the
   ground wherever its view contains railings.

## Added after review
- `railings_node` samples the ground at most every `RAILING_SAMPLE_M` (4 m) along a span, at most 64 pieces a span, so a long fence follows a hill between its ends. Empty grid: one piece, as before.
- `map_chunk.railing_rows()` builds the rows (leftover pieces of broken hedges and wooden fences); tests: long fence over a hill, broken fence on the ground.

## Tests to add
- `godot/tests/dem_terrain.gd::test_railing_stands_on_ground`: grid
  `{"origin":[0,0],"step":100,"cols":2,"heights":[6,12,6,12]}` prepared via
  `MapChunk.prepare`. `B3.railings_node([["fence", PackedVector2Array([Vector2(10,-10), Vector2(60,-10)])]], ground)`.
  The minimum y near each endpoint is about `ground_height`, so about 6.x, not 0.
  This fails without the fix: the minimum y is 0.0.
- In the same file: `railings_node(rows)` with no grid still has its minimum y at 0.0
  and its maximum y at 1.2 (criterion 2).
- No pytest change is needed: the server path is correct. Optional: add
  `tests/test_railings.py::test_wood_fence_without_gate_kept_whole`, a synthetic
  synthetic 3-node `barrier=fence, material=wood` line. It must give one `Railing` of kind
  `wood_fence`, layer 0, with 3 points.

## Out of scope
- Chunking railings by first point only (a long fence that crosses a chunk edge
  draws from one chunk). It is not the cause here.
- Fence style, posts or colour in 3D. Bridge/tunnel `layer` railings.
- The flaky NPC trip-cycle test.
