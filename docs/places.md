# World places (`places.json`)

`src/theroadragetrip/assets/places.json` is the game's list of fixed, named
world locations: currently airports and railway stations. The game uses it
to know where Oulu airport or Tampere station is without reading OSM at
runtime.

**It is generated data. Don't edit it by hand;** regenerate it instead.

## Build-time input, runtime output

```text
Finland OSM PBF  ->  tools/osm/extract_places.py  ->  assets/places.json  ->  theroadragetrip.world_places
```

The PBF is only an input for developers. The game never needs it for
places, makes no network calls for them, and doesn't touch the (disabled)
BIN road pipeline.

## Regenerating

You need `osmium-tool` (`osmium`) and the project's Python environment.

```bash
python tools/osm/extract_places.py \
    src/theroadragetrip/assets/osm/finland-latest.osm.pbf \
    src/theroadragetrip/assets/places.json
```

A run takes about 15 s: one streaming osmium pass, and the PBF is never
loaded into Python. The same PBF and configuration produce a byte-identical
file. When Geofabrik publishes a new Finland extract, replace the PBF, rerun
the command and review the diff. The file has one place per line, and
`source_timestamp` shows which extract it came from.

## Categories

Categories are defined in `tools/osm/places_config.py`, one `PlaceCategory`
each:

| field | meaning |
|---|---|
| `type` | JSON `type` and id prefix |
| `osmium_filters` | coarse `osmium tags-filter` pre-selection |
| `matches(tags)` | the exact rule |
| `metadata` | JSON key → OSM tag, copied when present |
| `identity_tags` | tags whose equal values mean "the same place"; the first one present forms the id |
| `dedupe_radius_m` | distance within which the same name means the same place |
| `element_preference` | which duplicate element represents the place |

| category | rule |
|---|---|
| `airport` | `aeroway=aerodrome` with an `iata` code, or `aerodrome=international`; not disused, abandoned or demolished |
| `railway_station` | `railway=station` or `halt`, excluding `station=subway/light_rail/tram/monorail/funicular/miniature`; not disused, abandoned or demolished |

Platforms (`railway=platform`) and `public_transport=station` areas without
a `railway` tag (bus stations, travel centres) are not railway stations.
The ~60 Finnish aerodromes with only an ICAO code are gliding, club and
private fields, so they are not destinations.

**Adding a category** (bus station, ferry terminal, harbour, landmark)
means appending one `PlaceCategory` and rerunning the tool. The extractor
code never names a category; `tests/test_extract_places.py` checks this
with a ferry-terminal category.

## One coordinate per place

- **Node:** its own position.
- **Closed way (area):** the area's centroid, computed in local metres. If
  the centroid falls outside the shape (an L-shaped airfield), a point
  guaranteed to be inside is used instead.
- **Open way:** the point halfway along its length.
- **Relation:** a `label` or `admin_centre` node member wins. Otherwise a
  multipolygon's outer rings are assembled into polygons and handled like an
  area. Other relations use their member areas, lines or nodes, in that
  order.

Coordinates are WGS84 `lat`/`lon`, rounded to 6 decimals (about 0.1 m). The
source element is always kept in `osm` (`type`, `id`).

## Deduplication

Within a category, candidates are grouped with union-find when they:

1. share a value of an identity tag (ICAO/IATA; station `railway:ref` or
   `uic_ref`), at any distance, or
2. share any name (`name`, `name:fi`, `name:sv` or `name:en`,
   case-insensitive, exact) and are within `dedupe_radius_m` (airports
   5 km, stations 1 km).

Similar but different names never merge ("Oulu" and "Oulun satama" stay
separate). Each group becomes one place. The representative element is
chosen by `element_preference` (airports prefer the area, stations the
station node), then by the most metadata, then the lowest OSM id. Metadata
missing on the representative is filled in from the others. Merged elements
are listed in `osm_duplicates`, so nothing disappears silently. Unnamed
matches and matches without geometry are reported in the tool's summary.

Output order is `type`, then name (case-insensitive), then `id`.

## Runtime

```python
from theroadragetrip.world_places import load_places

places = load_places()                      # assets/places.json; empty if missing
places.by_type("airport")
places.get("airport_efou")
places.find("Oulu", "railway_station")      # any of the place's names
places.within(lat, lon, 50_000)             # nearest first
```

A `WorldPlace` has `id`, `type`, `name`, `lat`, `lon`, `osm` and `names`
(language → name). Category fields such as `iata` or `station_code` are in
`metadata`. Places belong to the world, not to taxis: any vehicle or network
can use them.
