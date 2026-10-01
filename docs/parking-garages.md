# Parking garages and map levels

The game reads underground and multi-storey parking garages from OSM, and
it has a logical map-level model: 0 is the surface, -1 and -2 are below it
and 1 and up are above it. The player's level is the only one drawn and
driven on. Driving through a parking entrance whose roads state both levels
moves the player between them; F11 (debug HUD on) also switches the level
for testing.

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
| Collisions and environment per level: buildings by `map_level`; level-less trees, fences, curbs, bumps, water, cameras, roadworks, ground surface-only | active | phase 7 |
| Route planning off the surface | not done | – |
| NPCs and pedestrians on levels | not done (surface-only) | – |
| Level connectors (`amenity=parking_entrance` nodes) in `world.level_connectors` | imported, cached, streamed; data only | phase 8 |
| Driving through a parking entrance changes `Car.map_level` (road-level evidence only); multi-level ramps drive on each of their levels | active | phase 9 |
| Underground roads with an explicit multi-level `level=*` (e.g. tunnel `0;-1`) kept at import | active | phase 10 |
| Cross-level routes, NPC and pedestrian level changes | not done | – |
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

## Phase 7: level-aware collision and environment (garage-06.md, commit `1524167`, 2026-10-01)

The player's collision and environment checks now use the player's own
map level. Off the surface, nothing level-less on the surface stops,
bumps or slows the car any more just because it shares the car's x/y.

- **Buildings:** `Building.map_level` exists, so `check_building_collision`
  (`taxi.py`) checks `on_map_level` on each candidate its existing grid
  returns. The grid is unchanged and reused across level switches. A
  building collides only on its own level, so a surface building doesn't
  collide underground. No building gets a level from a road beneath it,
  from `building:levels` or from garage membership.
- **Road-overlap exemption:** the building check lets the car through
  where a road crosses a building. Like the tree and bridge-edge checks,
  it now gets the player's current-level roads (`drive_ways`) instead of
  all of `world.ways`.
- **Level-less objects:** trees, construction fences, curbs, speed bumps,
  water, speed cameras, roadworks, parking bays and ground types (grass,
  sand, mud) carry no level, so they're surface world. Off the surface
  their checks don't run, which leaves their indexes alone, and the
  ground under the car counts as "hard".
- **Puddles:** the splash check uses the current level's roads. Wet-road
  drawing is a surface layer: off the surface the render gate already
  skips it, and on the surface it uses the level-0 road grid.
- **Map sync:** unchanged. The building collision index already grows
  with streamed tiles, and the road networks rebuild as in phase 6.
- **Still surface-only:** NPC traffic and pedestrians.
- **Performance** (Oulu, 2 alternating pairs of phase 6 and phase 7):
  surface averages of 27.7 and 25.6 ms before, 25.3 and 26.0 ms after.
  The `collisions` section averages about 0.17 ms per frame in all four
  runs. With level switching, levels -1 and -2 averaged 16.6 and 16.2 ms
  (worst 41 ms) against 24.4 ms on the surface.

**Limits:**
- **Level-less scenery:** trees, fences, curbs and bumps have no level, so
  nothing underground can collide with them, even when OSM maps an
  underground one.
- **Garage outlines:** never collide, as before.

## Phase 8: level connectors (garage-07.md, commit `d27b6e7`, 2026-10-01)

Added `LevelConnector` (`osm/models.py`) and `world.level_connectors`:
places where OSM says levels may connect. This is data only. Nothing
draws, drives, routes or collides with connectors, and nothing changes
`Car.map_level`, so gameplay is unchanged.

**What Oulu's OSM data contains:**
- **Parking entrances:** 23 `amenity=parking_entrance` nodes, 22 of them
  inside the benchmark area. Their `parking=*` is empty on 12, then
  `underground`, `multi-storey` or `surface`.
- **Levels:** only 2 entrances carry `level` (`0` and `-1`).
- **Topology:** most entrance nodes join an outside driveway to a covered
  or tunnel road, the inside. Some inside roads carry multi-level values
  such as `level=0;-1`.
- **Not connectors:** there are no `parking=entrance` objects. The
  `ramp=*` tags are all on stairs (wheelchair or bicycle ramps), and
  `level:ref` only appears on indoor shops. So the model covers
  `amenity=parking_entrance` nodes only.

**Record fields:**
- **Identity:** `osm_type` (`"node"`), `osm_id` and
  `connector_type="parking_entrance"`.
- **Position:** `x`, `y`.
- **Level:** `map_level`, which is `level=*` only when it is one clean
  integer (`parse_map_level`, unchanged). Otherwise it is `None`, meaning
  unknown, never assumed to be the surface. `level` keeps the raw string,
  for example `0;1`.
- **`parking`:** the raw `parking=*` value.
- **`garage_osm_id`:** set only when the entrance node is a vertex of a
  garage outline (a shared OSM node). It is never set from distance or
  containment, and a garage never gives a connector a level.
- **`road_osm_ids`:** the roads through the entrance node, in OSM order.

There are no from/to levels: an entrance's `level=*` says where the
entrance is, not what it connects to, and the other side is never
invented.

**Storage:**
- **World cache:** section `connects` (format 22).
- **Overpass:** the query now fetches `amenity=parking_entrance` nodes
  (Overpass cache version `v0.15.0alpha.2`).
- **Tile streaming:** an `AutoFetchManager` world section, de-duplicated
  by OSM id and unloaded with its tile.
- **Not anywhere else:** connectors are never added to `ways`,
  `level_ways` or `LevelRoadNetworks`, and there is no cross-level route.
- **Build cost:** one C-level set check per way. Oulu still builds in
  about 25.5 s, and connectors have no per-frame cost.

**Oulu, through `build_ways`:**
- **Connectors:** 22 `parking_entrance` connectors.
- **Garage links:** 9 linked to a garage, all of them imported
  `ParkingGarage` records.
- **Levels:** 2 with a known level (`0`, `-1`); the other 20 are unknown.
- **Roads:** 21 have roads through them: 13 have two, 7 have one and 1 has
  three.

**Where phase 9 hooks in:**
- **Finding connectors:** `world.level_connectors`. With about 20 per
  city, a list scan near the car is fine.
- **Connector to road:** `road_osm_ids`, matched to `Way.osm_id` in `ways`
  and `level_ways`.
- **Resolving levels:** from the connector's own `map_level`, and the
  `map_level` or raw `level` of the roads in `road_osm_ids`; an inside
  road with `level=0;-1` is the typical evidence.
- **Changing level:** set `car.map_level`. Rendering, driving and
  collisions already follow it (phases 5–7).

**Limits:**
- **Nodes only:** ramps or entrance ways are not modelled, because none
  occur in the data.
- **Garage relations:** an entrance on a member way of a garage relation
  gets no `garage_osm_id`.

## Phase 9: driving through level connectors (garage-08.md, commit `b727e37`, 2026-10-01)

The player now changes level by driving through a parking entrance.
Everything level-aware (drawing, driving, collisions) follows
`Car.map_level`, so nothing else needed changing for it.

- **`explicit_levels(way)`** (`map_level.py`): the levels a road
  explicitly states. That is its `map_level`, or each integer of a clean
  multi-level raw `level=*` such as `0;-1`. Values such as `0-1`, `1.5`
  or `0;x` give nothing. `parse_map_level` moved to `map_level.py`,
  unchanged, so there is one definition; `Way.map_level` is unchanged.
- **Multi-level ramps:** a road like `level=0;-1` is now also in the
  `LevelRoadNetworks` network of each off-surface level it names, so the
  car can drive it from either end. It stays in the surface network
  because its `map_level` is `None`. This changes phase 6, where each road
  belonged to exactly one level. `draw_level_ways` draws such a ramp on
  those levels too.
- **Topology** (`level_transitions.resolve_connectors`): for each
  connector, the levels of the roads in `road_osm_ids` are combined.
  - **Rejected:** a connector with no roads, with a referenced road that
    isn't loaded (it waits for the tile), with fewer than two levels, or
    whose own `map_level` contradicts its roads.
  - **Never counted:** garage levels, `layer`, `tunnel` and `covered`.
  - **Destination:** for the car's level L, it is the single other level.
    If L isn't among the levels, or two or more others remain (say
    `{0, -1, -2}`), there is no transition.
  - **When:** resolved at startup (`_load_world`) and at every map sync,
    never per frame.
- **Transition** (`LevelTransitions.update`, called from
  `advance_simulation` after the car moves): it fires only when all of
  these hold.
  - The car was driving on one of the connector's roads.
  - This frame's movement passes the entrance node: the node lies between
    the last and the current position, within 4 m of the path.
  - The destination is unambiguous.

  It then sets `car.map_level` and disarms the connector until the car is
  10 m away. Being near an entrance, standing on it, wobbling over it, or
  passing on another road never fires it. Driving back through reverses
  the change. The debug HUD shows `map_level` and the last
  `level_transition`.
- **Oulu:** of 22 connectors, 2 resolve.
  - **`636848833`:** an outside aisle and a `level=0;-1` tunnel ramp, so
    0 ↔ -1.
  - **`4116535367`:** a `level=0;-2` ramp, so 0 ↔ -2.

  A simulated drive through each, with the game's own road lookup and
  layer update, changes level once on the way in and once on the way
  out. The other 20 can't resolve: 12 have roads with no level at all, 7
  reference a tunnel road the import dropped because it has no clean
  `level=*` (phase 4), and 1 has no roads.

- **Performance** (Oulu, 2 alternating pairs of phase 8 and phase 9):
  surface averages of 25.9 and 21.8 ms before, 26.8 and 20.4 ms after,
  which is within noise. The per-frame cost is a scan over the resolved
  connectors, 2 in Oulu.

**Limits:**
- **Few usable entrances:** most entrances lack road-level evidence in
  OSM, so they can't be driven through.
- **Dropped tunnels:** underground-looking service roads without a clean
  level are still dropped at import, which leaves 7 entrances with a
  missing road.
- **Abrupt change:** the level changes at once at the node, with no fade.
- **Surface-only actors:** no cross-level routing, and no NPC or
  pedestrian level changes.
- **Simulation test:** the level change is tested through
  `LevelTransitions` and the level-aware systems it drives, not through a
  full `advance_simulation` run.

## Phase 10: level-relevant underground roads (garage-09.md, commit `d4cc242`, 2026-10-01)

Phase 9 left 7 Oulu parking entrances unresolved because a referenced road
had been dropped at import. This phase audited each of them.

**The 7 dropped roads:** every one is the same 2-node stub,
`highway=service` + `service=driveway` + `tunnel=yes`, often with
`maxheight`. None has `level`, `layer`, `covered`, `location` or `indoor`.
One end joins the outside driveway, which also has no level. The other
joins a building outline, or an untagged multipolygon member. Nothing
within two hops carries a road level; the only nearby `level` is an
indoor shopping corridor (`level=1`).

| Entrance | Dropped road | Building at the other end | Level evidence | Result |
|---|---|---|---|---|
| 610923431 | 1040047770 | `building=yes` | none | still unresolved |
| 610923442 | 48052870 | `building=parking` | none | still unresolved |
| 2242755062 | 1188512815 | `building=garage` | none | still unresolved |
| 5538973244 | 946022115 | `building=retail` (S-market) | none | still unresolved |
| 9581169915 | 1040595425 | untagged member way | none | still unresolved |
| 9581169916 | 1040623885 | untagged member way | none | still unresolved |
| 11138414092 | 1201361712 | `building=yes` (OYS Kuuraparkki) | none | still unresolved |

These roads are physically underground or covered but have no logical
level: the spec's category 2. They stay dropped. Keeping them with
`map_level=None` would make them surface roads, and no tag gives them a
level. A building's or garage's levels are not road levels.

**What the audit did find:** the phase 4 import filter also dropped
underground-looking service and track roads whose `level=*` is an
explicit multi-level value, such as a `tunnel=yes` ramp tagged `0;-1`.
Phase 9's working Oulu ramp only survived because it is a
`parking_aisle`, which is exempt from that filter.

**Rule implemented** (`osm/build.py`, using the new `parse_level_list` in
`map_level.py`, which `explicit_levels` now also uses): an
underground-looking road is kept when its `level=*` is one clean integer
(as before) or a clean multi-level list.
- **The list names level 0** (`0;-1`): the road goes to `ways`, where it
  is drivable on the surface and, through `explicit_levels`, on each other
  level it names. These are the same semantics as phase 9's ramps.
- **The list doesn't name level 0** (`-1;-2`): the road goes to
  `level_ways`. Its `map_level` is `None`, but it never enters the surface
  network, which reads only `ways`.
- **No clean level:** still dropped. `tunnel`, `covered`, `layer`,
  `location`, garage levels and building floors are never evidence, and
  `parse_map_level` is unchanged.

World cache format 23.

**Oulu, before → after:**
- **Roads:** `ways` 30244 → 30245. The one added road is `848810277`, a
  `service` tunnel tagged `level=-1;0`, which also joins the level -1
  network (25 → 26 roads). The other multi-level tunnels were already
  kept as parking aisles.
- **Connectors:** unchanged at 2 of 22 resolved; the same 7 still miss
  their dropped stub.
- **Phase 9 regression:** a drive through `636848833` (0 ↔ -1) and
  `4116535367` (0 ↔ -2) still changes level once in and once out.
- **Build time:** 17.7 / 19.1 s before, 17.4 / 18.6 s after, the same.
- **Frame time** (Oulu driving benchmark, warm cache): 19.7 ms average
  (p95 34) before, 20.6 ms (p95 36) after, within noise. The first run
  after the format bump also rebuilds the world cache in the background
  (25.7 ms average then), a one-time cost.

**Limits:**
- **Currently unresolved entrances:** the 7 audited Oulu entrances stay
  unresolved. Their tunnel stubs carry no explicit `level=*`, and the
  surrounding OSM topology gives no unambiguous level evidence today.
- **Not blocked by design:** they could resolve in a later phase if OSM
  gains an explicit level on the road itself, or if another unambiguous,
  semantically valid level-bearing topology becomes available.
- **No level from physical structure:** `tunnel`, `covered`, `layer`,
  building type, garage membership, building floor counts and closeness
  to a road with a level never set `map_level` on their own.
- **Future topology work is possible:** a later phase could check whether
  some unresolved entrance paths can resolve from explicit level-bearing
  OSM topology without giving the tunnel road itself an inferred level.
  That needs a precise rule and its own tests, not a generic "take the
  nearest level" mechanism.
- **Current behaviour is intentional:** until such evidence exists, the 7
  roads stay out of the road networks rather than being wrongly treated
  as surface roads.

