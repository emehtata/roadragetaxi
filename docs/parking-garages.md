# Parking garages and map levels

The game reads underground and multi-storey parking garages from OSM, and
it has a logical map-level model: 0 is the surface, -1 and -2 are below it
and 1 and up are above it. The player's level is the only one drawn and
driven on. Nothing moves the player between levels yet; F11 (debug HUD on)
switches it for testing.

The work happens in phases, one `.github/prompts/garage-NN.md` prompt each.
"Current state" below is always up to date. The phase sections record what
each phase added, in order; a later phase can change what an earlier one
describes, and when it does it says so.

## Current state

| Area | State | Since |
|---|---|---|
| `ParkingGarage` records in `world.parking_garages` | imported, cached, streamed; never drawn | phase 1 |
| One level model: `ParkingGarage.levels`, `map_level`, `Car.map_level` | in place; `Car.map_level` is 0 during play | phase 2 |
| OSM `level=*` → `Way` / `Building` `map_level`; raw `level`, `indoor` kept | imported, cached, streamed | phase 3 |
| Underground service/track roads with `level=*` → `world.level_ways` | kept instead of dropped | phase 4 |
| Render gate: only `Car.map_level`'s world is drawn | active; F11 (debug HUD on) steps the level | phase 5 |
| Driving network per level: surface grid + route graph surface-only; player drives the current level's network | active | phase 6 |
| Route planning off the surface, building/tree collisions per level | not done | – |
| NPCs and pedestrians on levels | not done (surface-only) | – |
| `parking=entrance`, ramps, automatic level changes | not done | – |
| Garage debug overlay, spatial index for garages | not done | – |

Rules that hold throughout:

- **Level sources:** a level only ever comes from explicit OSM `level=*` or
  game data. It is never inferred from geometry (lying inside a garage
  outline), from `tunnel=*` / `covered=*`, or from `layer=*`.
- **`layer` is not a level:** `layer=*` (`Way.layer`, `Car.layer`) orders
  bridges and tunnels within the surface world. A `layer=-1` tunnel is a
  surface road.
- **No level means surface:** `map_level=None` is surface world, visible
  on level 0 only.
- **`building:levels` is not a level:** it is a building's floor count,
  never its `map_level`.

---

## Phase 1: garage data (garage-00.md, commit `048b994`, 2026-10-01)

Added the `ParkingGarage` model (`osm/models.py`) and `osm/parking.py`.

### Which OSM objects count

An element is a parking facility when it has `amenity=parking` or
`building=parking`. Its class comes from `parking=*`
(`parking_facility_type`):

| Tags | Class | Stored as a garage? |
|---|---|---|
| `parking=underground` | underground | yes |
| `parking=multi-storey` (also `multi_storey`, `multistorey`) | multi-storey | yes |
| `building=parking` with no `parking=*` | multi-storey | yes |
| `amenity=parking` with no `parking=*` | surface (the OSM default) | no |
| `surface`, `street_side`, `lane`, `layby`, `on_kerb`, `half_on_kerb`, `rooftop`, `carports`, `garage_boxes`, `sheds` | surface | no |
| any other `parking=*` value | unknown | no |

Nodes, closed ways and `type=multipolygon` relations are read. The
Overpass query gained garage nodes (`amenity=parking` + underground or
multi-storey). Surface parking is still drawn as a parking lot
(`Scenery(kind="parking")`), and so is an underground garage mapped as an
area.

### What a record holds

- **Identity:** `osm_type` (`node`, `way`, `relation`) and `osm_id`.
- **Geometry:** `points_m`, the outer ring in EPSG:3067 metres, or a
  single point for a node. Also `bbox`, and `center_m`, the mean of the
  ring's vertices.
- **Metadata,** `None` when missing: `name`, `operator`, `access`, `fee`,
  `capacity` (int), `maxheight` and `maxweight` (raw strings), and
  `opening_hours`, `covered`.
- **Raw level counts,** never merged into one: `parking_levels`,
  `building_levels`, `underground_levels`.
- **`levels`:** the garage's logical levels, with `levels_source` naming
  the tag they came from.
  - **Underground:** `parking:levels=n` gives `-n … -1`. Without it,
    `building:levels:underground=n` gives the same.
  - **Multi-storey:** `parking:levels=n` gives `0 … n-1`. Without it,
    `building:levels` and `building:levels:underground` give
    `-under … above-1`, which is justified because the whole building is a
    parking structure.
  - **Nothing usable tagged:** `()`. Levels are never guessed.

### Storage

- **World cache:** a `.rwc` section `garages` (format 18).
- **Tile streaming:** `parking_garages` is an `AutoFetchManager` world
  section, merged within the per-frame budget and unloaded with its tile.
- **Prebuilt city `.bin`:** not involved; it only holds roads and is off by
  default.
- **Per-frame cost:** none.
- **Oulu:** 57 garages, 48 multi-storey and 9 underground.

**Limits:**
- **Relations:** a garage relation with several outer rings keeps only its
  largest ring.
- **Node garages:** keep no footprint.
- **Spatial index:** none.

## Phase 2: map-level model (garage-01.md, commit `150a30b`, 2026-10-01)

Added `theroadragetrip.map_level` and `Car.map_level` (0), and a
`map_level` line in the debug HUD.

- **`visible_on_level(obj, level)`:** an object with a `map_level` is
  visible only when it equals `level`. Without one, the object is surface
  world.
- **`surface_visible(level)`:** true on level 0.

Rendering was unchanged in this phase. The gate followed in phase 5.

## Phase 3: OSM `level=*` and `indoor=*` (garage-02.md, commit `17d4a35`, 2026-10-01)

`Way` and `Building` gained `map_level`, plus the raw `level` and `indoor`
strings (world cache format 19, carried through streaming).

- **`parse_map_level`** (`osm/build.py`): `level=*` becomes `map_level`
  only when it is one clean integer (`-1`, `0`, `2`, `+1`). Values such as
  `0;1`, `0-2`, `1.5` or junk leave `map_level=None` and keep the raw
  string.
- **`indoor=*`:** stored raw, with no meaning attached yet.
- **Oulu:** 122 of the 170 ways with `level=*` parse; the rest are
  multi-level values like `0;1`. 193 ways have `indoor=yes`, and 8
  buildings have a single-number level.

Back then, underground service/track roads were still dropped at import
whatever their `level`. Phase 4 changed that.

## Phase 4: keep levelled underground roads (garage-03.md, commit `cec6a37`, 2026-10-01)

The import has long kept underground-looking `service` and `track` roads
out of the surface road network (`ways`), so they don't draw or route as
surface roads. A road counts as underground when it has `level<0`,
`location=underground`, `parking=underground|multi-storey|sheds|carports`,
`covered=yes|arcade` or `tunnel=yes|building_passage`.

- **Before:** all such roads were dropped.
- **Now:** one with a clean `level=*` is kept in `world.level_ways` with
  its `map_level` (world cache format 20, carried through streaming).
  Without one, it is still dropped.
- **Parking aisles:** `service=parking_aisle` was already exempt and stays
  in `ways`, even with `level=-1`.
- **Oulu:** 21 roads are kept this way, mostly garage driveways at levels
  -4 to 0.

## Phase 5: render gate (garage-04.md, commit `43c7053`, 2026-10-01)

`Car.map_level` now decides what is drawn (`main()`).

- **Surface layers:** the level-less layers draw only on level 0. That
  covers the static layers from grass to speed cameras, NPC cars,
  pedestrians other than the on-foot player, open roofs, bridge track,
  trains, fuel signs, lit windows, street lights, rain and labels. Off the
  surface, a plain backdrop replaces them.
- **Always drawn:** the player's car and headlights, the HUD, the debug
  overlays and the day/night overlay. The railway simulation keeps
  running underground; only its drawing is skipped.
- **Surface road cache:** `draw_ways` skips ways explicitly on another
  level, such as a `level=-1` parking aisle. The check runs only when its
  cache rebuilds.
- **Level roads:** `draw_level_ways` draws the current level's roads from
  `level_grid`, a `SpatialWayGrid` over `level_view_ways`: all of
  `level_ways` plus the `ways` tagged off the surface. The grid is rebuilt
  when a map sync finishes. On level 0 it draws the covered `level=0`
  roads from `level_ways`.
- **Debug:** with the debug HUD on, F11 steps the level 0 → -1 → -2 → 0.
  Nothing reloads or rebuilds.
- **Performance** (Oulu driving benchmark): surface frame times are
  unchanged within run-to-run noise. Levels -1 and -2 average about 17 ms
  against about 24 ms on the surface, and switching levels causes no spike.

**Limits:**
- **Drawing only:** physics, NPC traffic, pedestrians and routing still
  use the whole surface network, so a hidden `level=-1` aisle is drivable
  on the surface. Nothing drives on `level_ways` yet.
- **Partial road check:** the street-light, label and wet-road passes
  don't check road levels.
- **Entities:** NPCs and pedestrians have no level; they are simply hidden
  below ground.
- **Garage outlines:** never drawn. A garage with no tagged internal roads
  is an empty backdrop underground.

## Phase 6: level-aware driving network (garage-05.md, commit `17e0b32`, 2026-10-01)

Each road is drivable only on its own logical level, via `on_map_level`
in `map_level.py`: its `map_level`, or level 0 when that is `None`.
Levels share no roads, so nothing connects across levels.

- **Surface network:** the road `spatial_grid` is now built with
  `SpatialWayGrid(map_level=SURFACE_LEVEL)`, so it indexes only level-0
  roads. Every surface query uses it: the player, NPC traffic, the
  wrong-way and footpath checks. The filter runs at insert time, so
  queries cost nothing extra. `indexed_way_count` still counts the whole
  list, which keeps map sync's staleness check consistent. The route
  graph's default filter (`RouteGraphBuild`, used for player navigation
  and NPC routes) now also takes surface car roads only.
- **What left the surface network:** off-surface roads that the import
  keeps in `world.ways`. In Oulu that is 22 car roads: parking aisles at
  levels -3, -1 and +1, and a few driveways. Before this phase they were
  drivable and routable on the surface. `layer` doesn't matter here: a
  `layer=-1` tunnel without `level` is still a surface road.
- **Covered `level=0` roads:** these now go to `world.ways` and the
  surface network, because level 0 is the surface (world cache format
  21). This changes phase 4, which put them in `level_ways`; in Oulu
  that's 3 roads.
- **Off-surface networks:** `LevelRoadNetworks` (`map_level.py`) holds,
  for each explicit off-surface level, its roads and a `SpatialWayGrid`
  built from `level_view_ways`. It is rebuilt at startup and when a map
  sync finishes, never per frame. It replaces phase 5's mixed
  `level_grid`, and `draw_level_ways` now draws from the current level's
  grid. In Oulu the levels run from -4 to +2, with 1 to 52 roads each.
- **Player:** `advance_simulation` and `main()`'s road lookups use the
  surface network on level 0, and otherwise
  `world.level_roads.network(car.map_level)`. A level with no roads gives
  an empty network, never the surface as a fallback. Switching level is a
  lookup: nothing is fetched, reloaded or rebuilt.
- **Navigation:** no route is planned off the surface, and a surface
  route is dropped when the player leaves level 0. There is no route graph
  per level yet.

- **Performance** (Oulu driving benchmark, 4 runs each of phase 5 and
  phase 6, alternating): the machine was noisy, with run averages of
  27.6–66.6 ms for phase 5 and 32.0–59.1 ms for phase 6. Phase 6 came out
  better in three of the four pairs, so there is no measurable surface
  regression. Surface cost is a build-time filter only, plus one tuple
  pick per frame. Level switching (0/-1/-2 every 150 frames): levels -1
  and -2 averaged 17.1 and 18.2 ms against 23.5 ms on the surface. Their
  one spike over 100 ms is the `taxi` section after a 7.8 s tile load,
  a spike the phase 5 runs also have (up to 80 ms there).

**Limits:**
- **Still surface-only:** building and tree collisions, puddles, and the
  taxi's road-overlap checks still use the surface world on any level.
- **Pedestrians:** the pedestrian network still includes off-surface
  footways, such as Oulu's 52 `level=1` walkways, as surface paths.
- **NPCs:** traffic stays surface-only.

