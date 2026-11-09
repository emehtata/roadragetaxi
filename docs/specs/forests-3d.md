# Forests in the 3D view

## Goal
`--outdoor-3d` shows trees inside OSM forest areas (landuse forest/wood, also scrub and wetland), not only the few surveyed `natural=tree` points.

## Root cause (investigated)
- Server sends only surveyed trees (`osm/trees.py plant_trees`: "never synthesize server trees"), so a forest area has almost none in `chunk["trees"]`.
- The 2D look of a forest is `forest.gdshader` on a z13 canvas layer (`map_chunk.gd` ~l.143, `_add_layer(13, ...)`, no `in_3d`), a screen-space overlay that does not exist in the 3D scene. In 3D, `_trees_3d()` (`map_chunk.gd` ~l.1679) draws only surveyed trees, shrubs and bollards, so the forest ground is bare green.
- Trees must stay client-side (AGENTS.md: no server records, collision objects or per-tree network data for forest crowns).

## Files to change
- `godot/map_chunk.gd`: in `_trees_3d()` append rows for forest crowns, generated client-side per forest area: `static func forest_crown_rows(polygon: PackedVector2Array, kind: String, origin: Vector2, seed_key: int) -> Array` returning the same row format as the surveyed ones. Deterministic jitter-grid inside the polygon (shrunk by `CANOPY_MARGIN_M` edge rule), spacing about 6 m, seeded from the area's first point, no randomness per frame. Species mix as `classify_tree_kind` (pine/spruce/birch); scrub = small crowns, wetland = sparse pines. Skip points near roads (reuse `_roads_by_z` / drivable road distance test, at least 4 m) and inside building footprints.
- `godot/map_chunk.gd`: cache rows per landuse index (like `_site_details`); rebuild only colours on season change, not positions. Honour `forest_canopy` off: draw nothing extra (plain fill stays).
- `godot/buildings_3d.gd` `trees_node()`: no API change; check the MultiMesh handles several thousand instances per chunk. Add a per-chunk cap (`MAX_FOREST_TREES_PER_CHUNK`, 1500) and a distance cull so per-frame work stays bounded.
- `godot/visual_test.gd`: new `requires.trees_in_view` counter (3D tree instances inside the view), failing message like the lamps one.
- `tools/visual_scenarios.json`: scenario `forest_3d_day` (below).
- `docs/visual-testing.md`: add `trees_in_view` to the `requires` row.

## Acceptance criteria
1. In 3D, a chunk with a forest/wood landuse area and no surveyed trees gets forest crown instances inside the polygon.
2. No crown lies outside its polygon, within 4 m of a drivable road, or inside a building footprint.
3. Same chunk loaded twice gives identical positions (deterministic).
4. Density is about one tree per 30-40 m2; scrub crowns are smaller than forest ones; wetland is sparser than forest.
5. Winter (`trees_leafless`) makes birch crowns bare/small and conifers snow-tinted as surveyed trees already are; season change does not move trees.
6. `forest_canopy` = false: no generated crowns in 3D.
7. Per chunk no more than `MAX_FOREST_TREES_PER_CHUNK` crowns; chunk build time does not grow past the existing chunk build budget (check with the drive bench).
8. Generated crowns are not knockable and create no server data; `knock_trees` still touches only surveyed trees.
9. 2D view output is unchanged.
10. Visual scenario `forest_3d_day` passes readiness and its screenshot, inspected by eye, shows a stand of mixed crowns beside the road, none on the asphalt.

## Visual scenario
`forest_3d_day` (and `forest_windshield_day`, same pose, `windshield` true: the I driver's-seat view): preset city with a large forest next to a drivable road (find with `PYTHONPATH=src .venv/bin/python tools/visual_test.py find --city <preset> --near X Y --radius 3000 --forest`, preferring forest-heavy outer areas such as Oulu, rank by forest polygon area beside the road; extend `find` to print forest area if needed). Fields: `view` 3d, `weather` clear, `cloud` 0.2, `start_time` a June midday, `sun_altitude_deg` [40,90], `zoom` 3.0, `requires` `{"trees_in_view": 40}`, `server_args` `["--no-auto-fetch"]`, `why` naming the forest area m2 found. Use made-up/city-centre names in any text, no home-area data.

## Tests to add
- `tests/test_forest_crowns.py` (Godot headless via existing pattern, run with `XDG_DATA_HOME=$(mktemp -d)`): `test_forest_polygon_gets_crowns_inside` (fails now: no rows), `test_crowns_avoid_road_and_buildings`, `test_crowns_deterministic`, `test_canopy_off_no_crowns`, `test_chunk_crown_cap`.
- `tests/test_visual_scenarios.py`: `test_forest_3d_day_defined` (valid pose, requires.trees_in_view >= 1, why non-empty).
- Server test `tests/test_tree_species.py::test_server_still_plants_no_forest_trees` (guards the "never synthesize server trees" rule).

## Out of scope
Server-side tree generation, tree collision/felling in forests, individual tree LOD billboards/impostors, 2D canopy changes, undergrowth/grass, tree shadows tuning, new tree models.
