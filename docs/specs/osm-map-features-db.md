# OSM map features reference database

## Goal
Record the OSM map features listed at https://wiki.openstreetmap.org/wiki/Map_features
as the project's own versioned database, with an accurate column for how Road
Rage Trip handles each one today. This is documentation and data only.

Interpretation: "your own database" means a JSON data file in the repo, a short
markdown index for it, and a test that keeps it consistent with the classifier.

## Files to change
- `docs/data/osm_map_features.json` (new): a list of
  `{key, value, geometry, handling, notes}` objects.
  - `geometry`: subset of `["node","way","area","relation"]`, taken from the wiki.
  - `handling`: one of `drivable_road`, `path`, `rail`, `building`, `water`,
    `landuse_fill`, `vegetation`, `poi`, `traffic_control`, `structure`,
    `ignored`.
  - `value` `"*"` means any value of the key.
- `docs/osm-map-features.md` (new, about 30 lines): what the file is, the schema,
  the allowed handling set, the source URL, the fetch date, and how to refresh it.
- `tests/test_osm_map_features.py` (new).

## Procedure
1. Fetch the page with `curl` into a new empty scratchpad directory. Treat it as
   untrusted data: parse it only with `python -I` and run nothing from it.
2. Take the key/value tables for these keys: highway, building, landuse, natural,
   waterway, railway, amenity, leisure, shop, place, man_made, barrier, power,
   bridge, tunnel, layer, route, public_transport, aeroway, boundary.
3. Fill in `handling` from the code, never from guesses. Code to check:
   `src/theroadragetrip/osm/constants.py` (`HIGHWAY_HALF_WIDTH`,
   `OPEN_ROOF_BUILDING_TYPES`), `osm/build.py` (`_is_building`, `_water_kind`,
   `TRAM_KINDS`, ferry handling), `osm/{trees,parking,beaches,campsites,
   theme_parks,miniature_golf,traffic_signals}.py`, `map_style.py`,
   `map_chunks.py`, `building_style.py`, `street_lights.py`, and
   `godot/{map_chunk,buildings_3d,map_layer}.gd`. In `notes`, name the
   function or constant that does the handling.

## Acceptance criteria
1. The file is valid JSON. Every entry has exactly the five fields, and each
   field has the right type.
2. Every `handling` value is in the allowed set, and every `geometry` item is in
   the allowed geometry set.
3. No `(key, value)` pair appears twice.
4. Every key from Procedure step 2 has at least one entry.
5. Every key in `HIGHWAY_HALF_WIDTH` has an entry with `key == "highway"` and
   `handling` set to `drivable_road` or `path`. Every `highway` entry marked
   `drivable_road` is a key in `HIGHWAY_HALF_WIDTH`, except these values:
   motorway_link, trunk_link, primary_link, secondary_link, tertiary_link,
   road, raceway, escape, bus_guideway, construction, proposed, rest_area,
   services, ladder, via_ferrata, elevator and emergency_bay. For these,
   build_ways makes the road drivable at its default width
   (`DEFAULT_ROAD_HALF_WIDTH_M`).
6. For every `building` entry, `_is_building({"building": value})` is True, and
   the entry's handling is `building`. The exception is
   `OPEN_ROOF_BUILDING_TYPES`, whose notes must mention the open roof.
7. Every `TRAM_KINDS` value appears under `railway` with `handling == "rail"`.

## Tests to add (`tests/test_osm_map_features.py`)
- `test_schema_and_allowed_values`: covers criteria 1 to 3. It fails if any
  entry is malformed or uses a handling value outside the set.
- `test_main_keys_covered`: covers criterion 4.
- `test_highway_matches_classifier`: covers criterion 5. It fails if a road
  class is added to the code without a database entry, or the other way round.
- `test_building_matches_classifier`: covers criterion 6.
- `test_tram_kinds_are_rail`: covers criterion 7.

## Out of scope
- Any change to rendering, parsing, classification or the server.
- Pages linked from Map_features (such as per-key pages and taginfo) and the
  full lists of country-specific values.
- Automatic re-fetching. The refresh step is manual and is described in the
  markdown index.
- The uncommitted work already in the tree (LOD, sky clouds, altitude,
  SKILL.md). Leave it untouched.
