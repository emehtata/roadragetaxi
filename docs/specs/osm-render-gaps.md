# OSM render gaps: bench backrest tag and the major unrendered features

## Goal
Honour `backrest=*` on benches, then render the mapped features from
`docs/data/osm_map_features.json` (handling `ignored`) that are most visible at
street level and most common in Finnish towns.

## Gap ranking (chosen: 1-5; skipped listed last)
1. power=pole / minor_line / line / tower: everywhere along roads, never drawn.
2. man_made=chimney / tower / mast / communications_tower / water_tower: skyline landmarks, never drawn.
3. natural=tree_row: street and field-edge avenues; only single `natural=tree` is drawn.
4. natural=stone / rock / bare_rock: boulders and rock outcrops, very common in Finland; bare_rock is not a ground fill.
5. railway=level_crossing: barriers and crossbucks where rails meet roads (rail itself is drawn).
Skipped: aeroway (rare, airport only); natural cliff/ridge/peak/valley/hill (need terrain relief);
barrier retaining_wall / guard_rail / jersey_barrier (guardrails already partly drawn, low gain);
highway mini_roundabout / turning_circle (routing/geometry, not decoration); street_cabinet / water_tap /
survey_point / sewer_vent (tiny); power plants/substations (rare, area logic); railway signals/switches (small, rails-only).

## Files to change
- `src/theroadragetrip/osm/models.py`: `SceneryObject.backrest: Optional[bool] = None` (bench only).
- `src/theroadragetrip/osm/build.py`: `_scenery_object_kind` / `build_ways` set `backrest` from tags (`no` -> False,
  `yes` -> True, absent/`unknown` -> None); read power, man_made, tree_row, stone, level_crossing into new scenery kinds/lists.
- `src/theroadragetrip/osm/overpass.py`: add the missing queries (power, man_made, tree_row, stone, level_crossing).
- `src/theroadragetrip/map_chunks.py`: serialize bench backrest as row[4] (1 or 0; None -> 1); add lists/kinds for gaps 1-5,
  bounded per chunk (cap and deterministic order).
- `godot/map_chunk.gd`: pass the bench backrest through the `props` rows (today only camper_van gets row[3]); feed new lists.
- `godot/buildings_3d.gd`: `_bench(..., backrest: bool)` skips the two backrest slats and back uprights when false;
  new builders for poles+wires, masts/chimneys, boulders, level-crossing barriers; `PROPS` entries where fit.
- `godot/chunk_detail.gd` (and tree code): tree_row places trees at ~6 m spacing along the line; bare_rock via landuse fill colour in `map_style.py`.
- `docs/data/osm_map_features.json` regenerated; handling/notes updated for each feature rendered.

## Behaviour / acceptance criteria
1. A bench with `backrest=no` has no backrest in 3D; `yes`, `unknown` and missing keep it (default stays today's look).
2. `backrest=no` bench: sitter heading is still set across the seat (`bench_sitting.py` unchanged).
3. Every power pole node draws a pole 8-10 m tall (crossarm); consecutive poles of one `power=line|minor_line` way are joined by a
   sagging wire; `power=tower` is a lattice-style taller shape. No wires over 150 m spans.
4. A chimney/tower/mast/water_tower/communications_tower draws a vertical shape at its `height` tag (default: chimney 25 m,
   mast/tower 30 m, water_tower 20 m), capped at 80 m; area ways are drawn once at their centroid.
5. A `natural=tree_row` way yields trees along it at <= 8 m spacing through the existing tree kinds and LOD (no extra per-frame cost).
6. A `natural=stone|rock` node draws a 0.6-1.5 m boulder (size from stable id); `natural=bare_rock` areas get a grey ground fill.
7. A `railway=level_crossing` node on a road draws a barrier pair (if `crossing:barrier=yes|full|half`) else a crossbuck, aligned to the road.
8. Chunks with no such features produce empty lists; per-chunk counts stay bounded and chunk build time does not regress >10% on the PBF bench.

## Tests to add
- `tests/test_scenery_and_buildings.py::test_bench_backrest_tag_no_is_false_yes_and_unknown_true_or_none`: fails (no field) today.
- `tests/test_map_chunks.py::test_bench_row_carries_backrest_flag`: row[4] is 0 for `backrest=no`, 1 otherwise.
- `tests/test_build_ways.py::test_power_man_made_tree_row_stone_level_crossing_are_read`: one fixture each; fails (ignored) today.
- `tests/test_map_chunks.py::test_new_feature_lists_are_capped_and_empty_when_absent`.
- `godot/tests/run_tests.gd`: `B3.props` bench with backrest=0 has fewer deck vertices than with 1 and max height 0.46 m
  (no 0.85 m upright); plus one builder-output check per new builder (non-empty, height as specified).

## Visual scenarios (`tools/visual_scenarios.json`, readiness per docs/visual-testing.md)
- Backrest: reuse `walk_bench_oulu_day` (backrest=yes); add `walk_bench_nobackrest_day` on a real mapped backrest=no bench (no real names/ids in docs).
- Gaps 1-5: add `drive_power_poles_day`, `skyline_chimney_day`, `walk_tree_row_day`, `walk_boulder_day`,
  `drive_level_crossing_day`, each from real map data in a Finnish town; each requires its feature in view.

## Unchanged
Simulation rules, collisions and routing (poles, boulders, barriers are visual only; no new obstacles); traffic decisions stay on the
Python server; map-layer separation (new geometry is in its own chunk lists, not in road/landuse layers); bounded per-frame work.

## Out of scope
Everything under "Skipped"; terrain relief; collision with poles or stones; level-crossing signal behaviour or NPC stopping.
