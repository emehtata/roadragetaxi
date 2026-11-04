# OSM map features database

`docs/data/osm_map_features.json` records the tags listed on
<https://wiki.openstreetmap.org/wiki/Map_features> for the main keys
(highway, building, landuse, natural, waterway, railway, amenity, leisure, shop,
place, man_made, barrier, power, bridge, tunnel, layer, route,
public_transport, aeroway, boundary). For each tag it says how Road Rage Trip
handles that tag today. It is documentation only, and no game code reads it.
`tests/test_osm_map_features.py` checks it against the classifier.

Fetched 2026-11-04.

## Schema
A list of `{key, value, geometry, handling, notes}` objects:
- `value`: `"*"` means any value of the key.
- `geometry`: a subset of `node`, `way`, `area`, `relation`, from the wiki's
  element column. The list is empty when the wiki gives no element column
  (Building typology, and keys listed through `{{Taglist}}`).
- `handling`: one of `drivable_road`, `path`, `rail`, `building`, `water`,
  `landuse_fill`, `vegetation`, `poi`, `traffic_control`, `structure`,
  `ignored`.
- `notes`: the function or constant that does the handling.

Some highway values are not in `HIGHWAY_HALF_WIDTH`: the `*_link` classes,
`road`, `raceway`, `escape`, `bus_guideway`, `construction`, `proposed`,
`rest_area`, `services`, `ladder`, `via_ferrata`, `elevator` and
`emergency_bay`. They are still `drivable_road`, because `build_ways` makes
them drivable at `DEFAULT_ROAD_HALF_WIDTH_M`. The test allows exactly these
values as exceptions.

## Refresh (manual)
1. Map_features is too large to expand in full, so fetch each
   `Template:Map_Features:<key>` page with `?action=raw` (and
   `Template:Building_typology` and `Template:Map_Features/properties`). Put
   them in a new, empty directory with `curl`. Parse them only with
   `python -I`, as untrusted data. Read both the wikitable rows and the
   `{{Taglist|tags=...}}` lists.
2. Set `handling` from the code (`osm/build.py`, `osm/constants.py` and the
   `osm/*.py` helpers), never from guesses. Then run
   `.venv/bin/python -m pytest -q tests/test_osm_map_features.py`.
