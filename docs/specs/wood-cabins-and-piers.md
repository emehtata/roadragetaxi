# Wood cabins and piers

Goal: cabins/huts render with a wood-plank wall texture; OSM piers render as
wood decks on posts over water. User offline; choices recorded below.

## Current behaviour and cause
- Cabins: `building=cabin` is only a house type (`src/theroadragetrip/building_style.py:115`);
  `hut` is not even that. `static_world.py:183-188` sends a window category
  (0 plain, 1 house, 2 shop, 3 wall, 4 retail hall) and a flat wall colour;
  `godot/buildings_3d.gd:2296-2338` puts it in CUSTOM0.z and
  `godot/building_snow.gdshader:120-` only draws windows. No material path
  knows "wood", so cabins get a flat painted colour.
- Piers: never loaded. The Overpass query (`osm/overpass.py:161`) asks only
  for skyline `man_made` values, and `osm/build.py:444,896-898` keeps only
  `_SKYLINE_HEIGHTS_M` man_made ways. `man_made=pier` is dropped in the parser,
  so nothing reaches map_chunks or the 3D pipeline (the only "pier" code,
  `buildings_3d.gd:2574,2782-2796`, is bridge support columns).

## Chosen fix
1. Cabins: new category 5 `CATEGORY_WOOD_HOUSE` = house windows (as 1) plus
   procedural plank grain in `building_snow.gdshader`: horizontal boards every
   ~0.2 m along UV2.y, darker seam lines, per-board hash tint and a low-freq
   grain stripe along UV2.x, multiplied into COLOR. No texture asset (no
   download/licence issue). `static_world.py` sends 5 for building types
   `{"cabin","hut"}` (new `WOOD_BUILDING_TYPES` in building_style.py; add `hut`
   to `HOUSE_BUILDING_TYPES`). Wall colour from the Finnish palette is kept
   (falu red / brown cabins stay coloured, just grained). Roofs unchanged.
2. Piers: parse `man_made=pier` ways in `osm/build.py` (linear: buffer by
   `width` tag else 2.5 m, flat cap; closed area: polygon as is) into
   `world.piers` (list of shapely polygons); add `man_made=pier` to the
   Overpass query; check `osm/pbf_source.py` keeps the tag. `map_chunks.py`
   clips piers per chunk like rail decks (`static_world.rail_bridge_decks`) and
   ships them as `piers` polygons. `buildings_3d.gd` adds `_pier(out, poly)`:
   a 0.25 m wood-plank slab (procedural grain, colour ~Color8(120,95,65))
   at terrain/water height + 1.0 m (`PIER_DECK_M`), posts 0.2 m square every
   3 m along the outline down to terrain height - 1 m. Same chunk mesh +
   shadow-caster path as bridge decks; bounded work (posts capped per chunk).
   Render only; no physics/driving on piers.

## Files
- src/theroadragetrip/building_style.py, static_world.py (category 5)
- src/theroadragetrip/osm/overpass.py, osm/build.py, osm/models.py (piers), map_chunks.py
- godot/building_snow.gdshader (plank grain for category 5), godot/buildings_3d.gd
  (`CATEGORY_WOOD_HOUSE := 5`, windows treat 5 as 1; `static func _pier(out: Dictionary, poly: PackedVector2Array, origin: Vector2) -> void`)
- tools/visual_scenarios.json: `oulu_cabin`, `oulu_pier` (public places found
  in the loaded Oulu map, e.g. a pier at the city-centre shoreline; no home data)

## Acceptance criteria
1. A `building=cabin` or `hut` gets category 5; other houses keep 1.
2. Category-5 walls show visible horizontal boards in a rendered scenario
   (`oulu_cabin`, readiness checks passed, screenshot inspected).
3. Category-5 window counts equal category-1 counts for the same wall.
4. A `man_made=pier` way (linear and area) yields a pier polygon in the world
   and in the chunk payload of the chunk it lies in.
5. `oulu_pier` render shows a wood deck on posts over water; screenshot inspected.
6. Per-chunk pier posts are capped; no change to frame budget in the drive bench.

## Tests
- tests/test_building_style.py::test_cabin_and_hut_get_wood_category (fails: gets 1/0)
- tests/test_osm_build.py::test_pier_way_becomes_polygon (fails: no `piers`)
- tests/test_map_chunks.py::test_chunk_ships_piers (fails: key missing)
- godot/tests/wood_and_piers.gd: `test_wood_category_keeps_house_windows`,
  `test_pier_produces_deck_and_posts` (fails: `_pier` missing / 0 verts)

## Commands
make check; XDG_DATA_HOME=$(mktemp -d) make godot-test; godot-shot on both scenarios.

## Out of scope
Walking/driving on piers, boats, image wood textures, log-cabin corner geometry,
floating docks (`man_made=pier` + `floating=yes` rendered the same).

## Status
VERDICT: PASS (tester, after fix round).
- Cabin wood boards readable at 13 m. The wood grain is subtle at a distance.
- Piers render over water only. Piers are not drawn in 2D.
- Explicit-height test now discriminates.
- Cabin scenario uses a public camp site.
- Street name removed from all history being pushed.
