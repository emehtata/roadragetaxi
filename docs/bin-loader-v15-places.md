# bin-loader-v15: world places from the Finland PBF

Developer guide: [places.md](places.md).

## 1. Existing architecture

- **`osm/pbf_source.py`:** reads local PBFs through the `osmium` CLI
  (`osmium extract` per bbox). `_parse_osm_xml` stream-parses osmium's OSM
  XML output into Overpass-shaped element dicts. No Python PBF library is
  used anywhere, so none was added.
- **`utils/pbf_index.py`:** an optional grid index of regional PBF cells,
  used for bbox streaming. Not needed here.
- **`tools/osm/`:** standalone developer tools. `build_finland_roads.py` is
  the disabled BIN road builder, which this task neither imports nor
  modifies.
- **Runtime data:** static game data lives in
  `src/theroadragetrip/assets/`, is loaded with
  `Path(__file__).with_name("assets")` (as in `residents.py`), and is
  shipped as `assets/*` package data.
- **Existing place concepts:** `osm.models.Place` holds per-city OSM
  `place=*` nodes in local metres (x/y), used for taxi addresses. It is a
  different concept, so the new runtime type is `WorldPlace` in
  `world_places.py`. There was no existing airport or station concept.
- **Geometry:** `shapely` is already a declared dependency (used by
  `render/roads.py`).

## 2. Implementation

| file | purpose |
|---|---|
| `tools/osm/places_config.py` | `PlaceCategory` and the `airport` / `railway_station` definitions |
| `tools/osm/extract_places.py` | CLI and pure core: osmium `tags-filter` pass, reuse of `_parse_osm_xml`, representative points, dedupe, deterministic JSON |
| `src/theroadragetrip/assets/places.json` | generated from the real PBF (59 KB, 244 places) |
| `src/theroadragetrip/world_places.py` | runtime loader: `load_places`, `WorldPlaces.by_type/get/find/within` |
| `src/theroadragetrip/main/__init__.py` | loads the places at world load and logs those within 50 km of the city |
| `tests/test_extract_places.py` | 14 tests |
| `docs/places.md` | developer guide |

## 3. Data model

```json
{"version": 1, "source": "finland-latest.osm.pbf", "source_timestamp": "2026-09-09T20:21:20Z", "places": [
  {"id": "airport_efou", "type": "airport", "name": "Oulun lentoasema", "lat": 64.930253, "lon": 25.349721, "osm": {"type": "way", "id": 110768423}, "names": {"sv": "Oulu flygplats", "en": "Oulu Airport"}, "iata": "OUL", "icao": "EFOU"},
  {"id": "railway_station_ol", "type": "railway_station", "name": "Oulu", "lat": 65.011332, "lon": 25.484336, "osm": {"type": "node", "id": 205329095}, "names": {"sv": "Uleåborg"}, "station_code": "Ol", "uic_ref": "1000370", "operator": "Väylävirasto"}
]}
```

- **Required fields:** `id`, `type`, `name`, `lat`, `lon` and `osm`.
- **Optional fields:**
  - `names` (other languages, when they differ)
  - category metadata
  - `osm_duplicates` (merged elements)
- **Ids:** `<type>_<first identity tag>` (ICAO, then station code), falling
  back to `<type>_<n|w|r><osm id>`.

## 4. Extraction rules

- **Airports:** `aeroway=aerodrome` with an `iata` code, or
  `aerodrome=international`, and not disused, abandoned or demolished. The
  PBF has 96 aerodromes (52 ways, 35 nodes, 9 relations):
  - 31 have IATA, and all of these are passenger or transport airports
    (Helsinki-Vantaa down to Kitee and Varkaus).
  - The rest are ICAO-only or uncoded fields: gliding (Rautavaara,
    Lapinlahti), club, private (Kiikala, Savikko), seaplane and ultralight.
  - The `aerodrome=*` tag is too sparse to use as the rule (50 of 96 lack
    it, including Kajaani and Joensuu).
- **Railway stations:** `railway=station|halt`, excluding metro, tram and
  similar systems (`station=subway/light_rail/...`), and not closed.
  - 1 station is excluded as `disused=yes` (Пялькьярви).
  - Platforms never match.
  - The 155 `public_transport=station` areas without a railway tag are bus
    stations, travel centres and station buildings. They are a future
    `bus_station` category, not railway stations.

## 5. Coordinate selection

- **Node:** its own position.
- **Closed way:** the centroid in a local equirectangular metre projection.
  If the centroid is not inside the shape, shapely's
  `representative_point()`, which is guaranteed to be inside, is used.
- **Open way:** the midpoint along its length.
- **Relation:** a `label` or `admin_centre` node member if present.
  Otherwise the outer rings are polygonized and handled like an area, with
  member lines and nodes as fallbacks.
- **Checked on real data:** every way-based airport's point lies inside its
  own polygon (22 of 22). The relation airports (Turku, Kuusamo, Utti,
  Sodankylä) land on the airfields.

## 6. Deduplication

Candidates within one category are grouped with union-find when they share
an identity tag value (ICAO/IATA; `railway:ref`/`uic_ref`), or share an
exact name (any of name, name:fi, name:sv or name:en, case-insensitive)
within 5 km (airports) or 1 km (stations). Neighbours are found through a
grid sized to that radius, so there is no all-pairs scan.

- **Representative element:** chosen by element preference (airports: the
  area; stations: the node), then the most metadata, then the lowest id.
- **Merged elements:** listed in `osm_duplicates`, and their metadata fills
  gaps.
- **Different names:** never merged.
- **Output order:** `type`, then name (case-insensitive), then `id`. A
  second run gives a byte-identical file (verified on the real PBF and in
  the tests).
- **Real data:** 0 duplicates. Finnish stations are one node each (the
  Väylävirasto import), and every airport is a single aerodrome element. No
  two stations are within 500 m of each other and no names repeat. The rule
  is a safeguard that the tests exercise (Oulu as a way, a node and a coded
  halt collapses to one place; "Oulun satama" stays separate).

## 7. Real Finland PBF results

`finland-latest.osm.pbf`, replication timestamp 2026-09-09T20:21:20Z;
extraction took 14 s:

| | count |
|---|---:|
| total places | 244 |
| airports | 31 (22 way, 5 node, 4 relation) |
| railway stations | 213 (all nodes) |
| unnamed | 0 (none matched) |
| duplicate candidates merged | 0 |
| with OSM source | 244 |
| airports with IATA / ICAO | 31 / 31 |
| bbox | lat 59.83–68.61, lon 19.90–30.64 |

- **Required airports**, all present with codes: Helsinki-Vantaa (EFHK),
  Oulu (EFOU), Rovaniemi (EFRO), Tampere-Pirkkala (EFTP), Turku (EFTU,
  relation), Kuopio (EFKU) and Vaasa (EFVA).
- **Major stations**, all present with station codes: Helsinki (`HKI`; codes are Väylävirasto's mixed-case abbreviations, e.g. Oulu `Ol`),
  Pasila, Tikkurila, Tampere, Turku, Oulu, Kuopio, Jyväskylä, Lahti,
  Kouvola, Seinäjoki, Pori, Joensuu, Rovaniemi, Kajaani, Vaasa, Riihimäki,
  Hämeenlinna, Lappeenranta, Kemi, Kokkola, Ylivieska and Mikkeli.
- **Kept but notable (not discarded):**
  - museum railways: Porvoo ×5 and Jokioinen ×2
  - HKL commuter stations: Malminkartano, Kannelmäki and Pohjois-Haaga
  - three stations over the border that the Geofabrik Finland extract
    includes: Вяртсиля and Светогорск in Russia (RZD), and Кивиярви
  - Hedenäset, on the Swedish side of the Tornio river
  - smaller IATA airports with little or no scheduled traffic (Halli, a
    military airfield; Hyvinkää; Kauhajoki; Kitee; Varkaus; Utti)

  Filtering these would need a country or traffic rule, and a later
  category or query can apply one.

## 8. Validation

- `tests/test_extract_places.py`: 14 passed. They cover:
  - node and area extraction
  - representative point (centroid, L-shape inside, multipolygon, label
    node)
  - category matching (airfields, platforms, metro, closed, bus stations,
    unnamed)
  - dedupe (identity tag, name within radius, different name kept, far
    same-name kept)
  - deterministic order
  - OSM source and optional airport metadata
  - a new category through configuration only
  - invalid, missing and unsupported input, missing output directory and
    osmium failure
  - end-to-end CLI on a generated PBF with a byte-identical rerun, loaded
    through `load_places`
  - a loader that tolerates bad files
  - the committed file containing the required places
- Full suite: 1195 passed.
- `git diff --check`: clean.
- Game run (Oulu, headless benchmark): places load at world load, and
  within 50 km the game finds Oulu (station), Oulun lentoasema, Kempele,
  Muhos and Ruukki. `load_places()` takes 1.35 ms.

## 9. Runtime integration

`theroadragetrip.world_places.load_places()` reads `assets/places.json`
(a missing or invalid file gives an empty set with a warning, never a
crash). It returns `WorldPlaces` with `by_type`, `get`, `find` (any name)
and `within(lat, lon, radius_m)`. `_load_world` loads it once and logs the
nearby places. No routing yet: the next step is place → nearest routable
road node → route planner.

## 10. Future extensions

Add a `PlaceCategory` to `places_config.py` and regenerate. Sketches:

- **`bus_station`:** `amenity=bus_station`, or `public_transport=station`
  with `bus=yes` and no railway tag. Dedupe on name within about 300 m.
- **`ferry_terminal`:** `amenity=ferry_terminal`.
- **`harbour`:** `harbour=yes`, or `landuse=port` areas (prefer the area).
- **`landmark`:** a curated `tourism=attraction` or `historic=*` subset
  with a significance rule, e.g. a `wikidata` tag.

The extractor needs no changes for any of these; the ferry test proves it.

## 11. Explicit non-goals

The BIN architecture was intentionally not used, re-enabled or modified,
and no BIN format was added. The game does not need a PBF, makes no network
calls for places, and has no hard-coded coordinates. There is no routing to
places, no threading and no new dependency.
