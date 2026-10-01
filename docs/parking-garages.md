# Parking garages (data layer)

The game reads underground and multi-storey parking garages from OSM and
keeps them as `ParkingGarage` records in `world.parking_garages`. This is
data only: nothing draws them, drives into them or routes through them yet.

## Which OSM objects count

An element is a parking facility when it has `amenity=parking` or
`building=parking`. Its class comes from `parking=*`
(`theroadragetrip.osm.parking.parking_facility_type`):

| Tags | Class | Stored as a garage? |
|---|---|---|
| `parking=underground` | underground | yes |
| `parking=multi-storey` (also `multi_storey`, `multistorey`) | multi-storey | yes |
| `building=parking` with no `parking=*` | multi-storey | yes |
| `amenity=parking` with no `parking=*` | surface (the OSM default) | no |
| `surface`, `street_side`, `lane`, `layby`, `on_kerb`, `half_on_kerb`, `rooftop`, `carports`, `garage_boxes`, `sheds` | surface | no |
| any other `parking=*` value | unknown | no |

Nodes, closed ways and `type=multipolygon` relations are all read. The
Overpass query fetches garage nodes (`amenity=parking` + underground or
multi-storey); parking ways and relations were already fetched. The local
PBF path reads everything.

Surface parking is unchanged: it is still drawn as a parking lot
(`Scenery(kind="parking")`). An underground garage mapped as an area is
also still drawn that way, because this phase doesn't change rendering.

## What a record holds

- **Identity:** `osm_type` (`node`, `way`, `relation`) and `osm_id`.
- **Geometry:** `points_m`, the outer ring in EPSG:3067 metres, or a
  single point for a node. `bbox`, and `center_m`, the mean of the ring's
  vertices.
- **Metadata,** as tagged and `None` when missing: `name`, `operator`,
  `access`, `fee`, `capacity` (int), `maxheight` and `maxweight` (raw
  strings, because OSM units vary), `opening_hours`, `covered`.
- **Raw level counts,** never merged into one number: `parking_levels`
  (`parking:levels`), `building_levels` (`building:levels`),
  `underground_levels` (`building:levels:underground`). Values that aren't
  a non-negative whole number are dropped.

## Levels

`levels` is a tuple of logical map levels: 0 is ground, -1 and -2 are
below it, 1 and up are above it. Later phases can use it to tell a surface
road apart from garage level -1 at the same x/y. `levels_source` names the
tag the levels came from.

- **Underground:** `parking:levels=n` gives `-n … -1`. Without it,
  `building:levels:underground=n` gives the same.
- **Multi-storey:** `parking:levels=n` gives `0 … n-1`. Without it,
  `building:levels` and `building:levels:underground` give
  `-under … above-1`. `building:levels` only counts as parking levels here
  because the garage class already says the whole building is a parking
  structure.
- **Nothing usable tagged:** `levels` is `()`. A level is never guessed,
  not even -1 for an underground garage.

## Storage and runtime

- **Built in:** `build_ways` (`osm/build.py`), in the same single pass over
  OSM elements as everything else, so nothing extra runs at game time.
- **World cache:** the `.rwc` world cache stores garages in their own
  `garages` section. Format 18 added it; an older file fails the version
  check and is rebuilt. A cached area therefore loads its garages without
  any network access.
- **Prebuilt city `.bin`:** not involved. It only supplies road `Way`s
  (`osm/bin_source.py`) and is disabled by default.
- **Tile streaming:** `parking_garages` is one of `AutoFetchManager`'s world
  sections. Streamed garages are merged within the existing per-frame merge
  budget, de-duplicated, and removed when their tile is unloaded.
- **Per-frame cost:** none. No code touches garages while the game runs.

## Not supported yet

- **Spatial index:** none. Queries such as "garages near the player" can
  scan the list for now (Oulu has 57 garages), or reuse a `SpatialWayGrid`
  once a later phase needs them.
- **Multi-part relations:** a relation with several outer rings keeps only
  its largest ring.
- **Entrances, debug overlay, rendering:** `parking=entrance` nodes,
  `level=*` / `indoor=*` mapping inside garages, and any debug overlay are
  not read or drawn.
- **Garage polygons for nodes:** none are inferred. Underground garages are
  often mapped only as a node, and their footprint stays unknown.

## Map levels

There is one level model: integers, with 0 for ground, negative numbers
below it and positive numbers above it. `ParkingGarage.levels` lists the
levels a garage has. `map_level` is the single level an individual object
is on.

### Where levels come from

- **OSM `level=*`:** `Way` and `Building` carry `map_level`, plus the raw
  `level` and `indoor` tag values. `parse_map_level` (`osm/build.py`) turns
  `level=*` into a map level only when it is one clean integer (`-1`, `0`,
  `2`, `+1`). Values such as multi-level `0;1`, ranges `0-2`, fractions
  `1.5` or junk leave `map_level` as `None` and keep the raw string in
  `level`. In Oulu, 122 of the 170 ways with `level=*` parse, and the rest
  are multi-level values like `0;1`.
- **OSM `indoor=*`:** kept as its raw value (`yes`, `room`, `corridor`,
  `parking`, ...), or `None` when untagged. No meaning is attached to it
  yet.
- **OSM `layer=*`:** stays separate. `Way.layer` / `Car.layer` order bridges
  and tunnels within the surface world. A `layer=-1` tunnel keeps
  `map_level=None`, and `layer` never feeds into `map_level`.
- **`building:levels`:** counts a building's floors (`Building.levels`). It
  is not where the building sits, so it never sets `map_level`.
- **Nothing else:** no level is ever inferred from geometry, such as a road
  lying inside a garage outline.
- **Pipeline:** the values are parsed once in `build_ways`. They are stored
  in the world cache (format 19) and carried through tile streaming
  unchanged.

### Visibility rule (`theroadragetrip.map_level`)

- **The player's level:** `Car.map_level`. It is always 0 for now, and the
  debug HUD shows it as `map_level`.
- **`map_level` set:** the object is visible only when that equals the
  player's level.
- **`map_level` is `None`:** surface world, visible on level 0 only. That
  covers every existing object, and any whose `level=*` didn't parse.
- **Not active yet:** no render pass applies the rule, so a footway tagged
  `level=-1` still draws on the surface exactly as before. Turning the
  rule on means moving the world-layer stretch of `main()`'s render code
  into its own function, skipping it when `surface_visible()` is false,
  and drawing that level's objects using `visible_on_level()`.

### Garage internal roads

A garage road only gets a level when OSM gives it `level=*`; nothing is
derived from garage geometry. One existing import rule still applies: a
`service` or `track` road that looks underground (`level<0`,
`tunnel=yes`, `parking=underground`, `covered=yes`, ...) is dropped, so
garage aisles don't draw over the surface map. They will be kept, with
their `map_level`, once the render gate exists. Footways and other roads
with a negative `level` are imported with it today.
