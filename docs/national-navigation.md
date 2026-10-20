# Intercity navigation: audit and revised design

Status: implemented end-to-end, following
`.github/prompts/rrt-019-longdistance.md`: offline backbone and bounded town
approaches, background routing, route-aware streaming and final-address handoff. The
previous full-street experiment has been removed from the runtime and source.

## Existing architecture found

| Concern | Existing implementation | Integration consequence |
| --- | --- | --- |
| Long-fare selection | `taxi.py:pick_long_dropoff()` samples `municipality_points()` using population weights. Defaults currently select trips 20–100 km away. | Keep this selection policy; longer benchmark routes do not change fare-generation limits. |
| Unresolved destination | `TaxiTarget.municipality` identifies an unresolved town/landmark; `x/y` are its representative location and `address` is its display name. | An intercity anchor must be separate from these destination semantics. |
| Place resolution | `municipality_points()` combines `residents.CITY_DATA` with airport/station `WorldPlace` records. `WorldPlaces.find()` returns all matching names. | Reuse the catalogues and multilingual aliases. Do not silently select the first ambiguous name. |
| Duplicate names | `CITY_DATA` currently uses a case-folded name dictionary, so duplicate settlement names can overwrite each other. `WorldPlace` has stable IDs and OSM provenance. | Preserve fare selection, but carry an explicit catalog/place ID for intercity requests; report unresolved catalogue collisions. |
| Final address | While driving to an unresolved destination, `TaxiManager.update()` calls `_resolve_long_dropoff()` within 1,500 m. It retries at two-second intervals until a local building/road/stand is available, then updates companions too. | Keep this resolver as the sole owner of final-address selection. Distance alone is not proof that the destination tiles are ready. |
| Local navigation | `NavigationRoute` incrementally calls `TrafficWorld.plan_route_steps()` on the loaded graph, handles deviations and graph revisions, and publishes geometry plus next-turn instructions. Other map levels use existing level routing. | Reuse it for departure and final approach. Add an intercity coordinator above it. |
| Geometry/connectivity | Live `Way` objects contain projected EPSG:3067 geometry, layers and direction/access metadata. The local graph merges nearby geometry; source PBF retains exact OSM references. | Build national connectivity from source node IDs, not the local graph's geometric merging. |
| Player movement | Player controls drive existing server physics; navigation is guidance. NPC route-following belongs to existing traffic systems. | Do not add player autopilot or move a taxi through unloaded collision geometry. |
| World streaming | `AutoFetchManager` prioritizes the active player tiles and bounded velocity lookahead; `server/map_sync.py` integrates fetched data. PBF extraction uses `osmium` and optional regional indexes. | Add bounded route-aware fetch priorities through this manager, not another loader. |
| Caches/rendering | Existing raw OSM caches and `.rwc` world caches feed Python world data; `map_chunks.py` supplies Godot's render chunks. | Keep all these caches and rendering paths unchanged. Do not turn the routing dataset into render tiles. |

## Why the previous approach was rejected

Measured against the available Finland PBF in this workspace:

| Full-street experiment | Actual result |
| --- | --- |
| Stored source nodes | 10,350,705 |
| Directed edges | 20,148,927 |
| SQLite cache | 2,696 MiB (about 2.63 GiB) |
| Warm cache validation | Approximately 0.3 ms; this was a metadata check, not a full graph load |
| Oulu–Helsinki, on a connected departure road | Search exceeded the 30-second worker timeout |
| Initial city-centre probe | Nearest segment reached only three directed nodes; proximity did not establish useful access |

Those measurements do not describe the proposed graph. No size, memory or
latency claim is made for the replacement before it is built and measured.
The old generated `.pbf.roads.sqlite` was deleted at the user's request,
recovering about 2.63 GiB. The source Finland PBF and existing map caches remain.

## Revised route lifecycle

```text
Unresolved town/landmark selected by existing fare logic
  -> resolve stable origin/destination IDs and validated gateway candidates
  -> cached intercity search between gateways
  -> local departure leg to an actually reachable origin gateway
  -> major-road guidance, with bounded nearby/forward tile streaming
  -> destination approach tiles become available
  -> existing final-address resolver chooses the actual destination
  -> local navigation plans the final approach
```

The coordinator owns the phase, gateway IDs, graph version and active search.
The passenger retains its selected town/landmark throughout the intercity leg.
Only `_resolve_long_dropoff()` replaces it with the final address. Handoff is
based on the resolver producing that final target, not on arriving at an
arbitrary point on a motorway.

Entering a town region starts bounded approach prefetch early enough to reach
the existing resolver radius with useful local data. If tiles are delayed,
retain valid guidance to a validated town gateway and keep retrying; do not
invent a final address or draw a straight line through an unverified gap.

## Offline graph preparation

Use existing `osmium-tool` and projection conventions. The builder is available
as an explicit offline tool. Following the user's updated requirement, enabling
"Enable intercity fares" also authorizes the game to initialize the database
before the next session. Ordinary startup with this setting off does no work.

Default configurable road classes are exactly motorway, motorway_link, trunk,
trunk_link, primary, primary_link, secondary and secondary_link. Residential,
service and parking roads are excluded from the national backbone. Preserve
actual node references and parse the relevant restriction relations before
deciding which nodes can be collapsed.

Retain junctions, forks, access/barrier changes, restriction transition nodes,
gateway attachment points and way boundaries needed for direction, speed or
class changes. Collapse intermediate degree-two geometry chains. A segment's
geometry is stored once, with direction flags or reverse references rather
than copying its coordinates for each direction.

Artifact: a versioned SQLite database, using the Python standard
library. Store compact junction/segment tables, geometry blobs, transition
restrictions, place/gateway associations and metadata. SQLite is selected for
atomic preparation, explicit validation and indexed selective access; benchmark
it on the simplified graph before deciding whether all adjacency fits in memory.
This introduces no BIN map-data pipeline.

Metadata records source identity, extraction settings, speed assumptions,
connector policy and schema version. Runtime opens a compatible prepared graph
read-only. With intercity fares opted in, missing/stale/invalid data is rebuilt
during the visible startup initialization stage. A missing PBF offers the existing
download flow. Initialization failures prevent enabling intercity offers;
disabling the option retains normal local fares.

## Validated town gateways and limited connectors

Use existing municipality and `WorldPlace` identities, enriched with source OSM
city/town provenance during preparation. Keep aliases and type/region
disambiguation; a display name alone is not an identity.

Each gateway names an actual directed backbone segment and an attachment node.
Find suitable town approaches using topology and the town's local access
network. A nearby motorway carriageway across a river is not a gateway just
because it is geographically closest. Keep multiple approaches where they
serve different directions or components.

Departure gateways must be reachable through the currently loaded local graph.
For important towns absent from the default backbone, allow explicit per-town
connector settings: permitted lower road classes, bounded search extent and
maximum connector length. Extract only the connected path justified by that
policy; do not globally add every tertiary or residential road. Preserve the
OSM node IDs of the connector and record its provenance. Unsupported towns or
islands get an explicit missing-gateway/connectivity report.

The offline build reports weak and directed connectivity, gateway coverage,
retained connector paths and unsupported destinations. Only destinations with
bidirectional access to the main backbone component are offered.

## Search and runtime integration

Use A* with estimated driving time as edge cost. Derive it from valid speed
tags and documented class defaults. The admissible heuristic is Euclidean
distance divided by an upper bound at least as high as every effective edge
speed in the dataset. Model incoming-edge state where necessary to enforce
turn restrictions. Preserve relevant one-way, vehicle/access and closure data;
unsupported conditions must be explicit, never silently allowed.

Return origin/destination place IDs, graph version, selected gateways, ordered
segment IDs/directions, reconstructed geometry, total metres, estimated seconds
and transition/street metadata. A route is not just a town-centre polyline.

Cache bounded gateway-to-gateway results by graph version and routing profile.
Changing a fare, gateway or profile invalidates the result; normal local tile
merges do not. A deviation first identifies a connected backbone re-entry or
uses a new local departure leg. Do not search the country every tick.

Small integration points:

1. Add stable place identity to unresolved long-fare requests without changing
   how `pick_long_dropoff()` chooses a destination.
2. Add a server-side intercity coordinator alongside `NavigationRoute`; preserve
   the existing local planner and map-level handling.
3. Give `AutoFetchManager` bounded route/approach priorities while preserving
   active-player tile priority, caching and collision-safe loading behavior.
4. Detect the existing resolver's final-target replacement and hand navigation
   back to the local planner, including every fare companion.
5. Continue publishing the existing navigation geometry/instructions to Godot;
   add protocol fields only where an actual UI requirement needs them.

## Implementation and acceptance sequence

First implement and benchmark the offline backbone builder, compaction and
restriction preservation. Then validate gateways and bounded connector policies.
Only after those measurements pass should the runtime coordinator and streaming
handoff be wired into fares.

Required fixtures cover degree-two compaction, reconstruction, one-way roads,
interchanges, layers, via-node/via-way turns, access restrictions, closures,
ambiguous names, missing gateways, malformed artifacts and disconnected regions.
Server tests must drive the unresolved-town to resolved-address transition
through real streaming updates, preserve companions and leave ordinary local
navigation unchanged. Add cancellation, cache invalidation and route reuse tests.

Real-data acceptance routes include Oulu–Helsinki, Oulu–Tampere and
Helsinki–Rovaniemi. Validate every segment transition against actual source
topology and report any failed pair. Measure node/segment counts, artifact size,
loading time, peak/resident memory, cold/warm route latency, returned geometry
size and repeated-request latency. Report all towns lacking usable gateways.

## Historical backbone-only baseline

`src/theroadragetrip/intercity.py` implements the offline builder, versioned
SQLite reader, lazy geometry reconstruction and travel-time A*. The game only
initializes it at startup when explicitly enabled in Settings. No dependencies
were added.

Build and test:

```sh
.venv/bin/python tools/osm/build_intercity.py \
  src/theroadragetrip/assets/osm/finland-latest.osm.pbf /tmp/finland.intercity.sqlite --backbone-only
.venv/bin/pytest -q tests/test_intercity.py tests/test_navigation_route.py
```

The source's actual OSM IDs define junctions. Per-way degree-two geometry is
collapsed, while junctions, way boundaries, repeated nodes, barriers and
via-node restrictions are retained. Each geometry is compressed once in the
artifact; forward/reverse travel times refer to it. Conditional permissions
fail closed. Unsupported restrictions exclude their incoming ways. Supported
via-way restrictions track only active restriction prefixes, avoiding an
exponential history of unrelated roads.

Missing mandatory source-node references abort preparation. The completed
artifact replaces the old output only after successful extraction and a source
identity check. Runtime reads are read-only; metadata and segment/geometry
validation reject invalid artifacts. Estimated class speeds are 100 km/h for
motorways, 80 for trunk/primary, 70 for secondary, and 40 for links, overridden
by valid explicit/directional speed tags. These are routing cost assumptions,
not assignments of legal speed limits to simulated vehicles.

Measured on the workspace's 771,221,995-byte Finland PBF, 2026-10-20:

| Measurement | Result |
| --- | --- |
| Geometry nodes on accepted source ways | 580,559 |
| Retained junction nodes | 67,145 |
| Stored segments / directed segments | 77,754 / 108,597 |
| Artifact size | 18,575,360 bytes (17.7 MiB) |
| Offline build including connectivity audit | 23.7 s |
| Peak memory of offline build process tree | 2,253,272 KiB (includes osmium subprocesses) |
| Graph opening / adjacency load | 0.308 s |
| Peak query-process memory over six searches | 113,376 KiB |
| Weak components / strong components | 50 / 1,500 |
| Nodes in largest strongly connected component | 64,661 |

There are real gaps in the selected backbone. A directed component count also
reflects legal one-way access and must not be interpreted as 1,500 separate
geographic islands. These baseline figures exclude the town approaches
implemented below.

The following are graph-node probes near the named cities, **not validated
city gateway associations**. Each returned segment sequence was checked for
continuous endpoints and geometry was reconstructed in travel order. All three
pairs were reachable; final address selection and approach legality are not
tested by these probes.

| Probe | First / repeated search | Distance | Segments / geometry points |
| --- | --- | --- | --- |
| Oulu–Helsinki | 0.336 / 0.324 s | 671.4 km | 1,486 / 7,761 |
| Oulu–Tampere | 0.130 / 0.154 s | 481.5 km | 588 / 5,442 |
| Helsinki–Rovaniemi | 0.661 / 0.644 s | 890.2 km | 1,777 / 10,943 |

Reproduce the same explicit-node probes (no automatic proximity connection):

```sh
.venv/bin/python tools/osm/benchmark_intercity.py /tmp/finland.intercity.sqlite \
  --pair Oulu-Helsinki 35242123 953049450 \
  --pair Oulu-Tampere 35242123 898047519 \
  --pair Helsinki-Rovaniemi 953049450 1651552666
```

These historical repeated measurements rerun A*, without a route-result cache.
The offline build still has a substantial memory peak despite its small output.
It is an explicit preparation operation, or a visible one-time startup step
authorized by the intercity-fares setting.

## User opt-in and initialization

Settings includes "Enable intercity fares", off by default, with a visible
explanation that the Finland PBF download and database initialization are
required. The setting takes effect next session. If no usable PBF exists,
the launcher offers its existing download screen. Choosing the online-map
fallback disables intercity fares rather than bypassing the prerequisite.

The server option `--intercity-fares` (configuration `game.intercity_fares`)
checks the local PBF and prepares `finland.intercity.sqlite` in the existing
writable runtime cache root, displaying an initialization stage. A matching
source identity/schema/road-class profile reuses the database. New intercity
offers stay disabled unless opted in and initialization succeeds. This
initialization includes the gateways and connectors, not just the major roads.

## Completed runtime lifecycle

`intercity_places.py` prepares the existing fare catalogue with stable,
coordinate-disambiguated IDs. It temporarily extracts eligible local roads
inside 6-km town regions, using the same OSM-ID topology, access rules and turn
restrictions as the backbone. Only actual directed connector paths, at most
8 km each, survive in the final database; the temporary local graph is deleted.
The town regions are merged into one spatial extract before local road classes
are filtered, so unrelated residential and service streets elsewhere in Finland
never enter the XML parser or temporary routing graph.
Anchor candidates must connect in both directions to the mainland backbone.
Public streets take priority over service/parking roads. Town anchors are within
1 km of the existing destination centre; landmark anchors are within 800 m.
Disconnected regions and places with no legal bounded approach are reported,
not connected by geographical proximity. Connector extent and path-length
limits are explicit keyword parameters of `attach_gateways`; defaults above
are the game's preparation policy.
The offline tool also accepts `--town-connectors policies.json`, keyed by
stable catalogue ID, with per-town `classes`, `extent_m` and `max_length_m`.
Classes must be a subset of the allowed connector classes (tertiary/link,
unclassified, residential, living_street, service), extent cannot exceed 6 km,
and connector length cannot exceed 20 km. This cannot turn local streets into
a national street graph. The chosen policy is stored in the artifact.

The `places` table stores destination IDs, actual road anchors and gateway OSM
node IDs. `gateway_report` records supported/missing places and both directed
connector lengths. `place_aliases` preserves existing landmark aliases, source
catalogue IDs and OSM provenance. Imported segments keep source way/node IDs and geometry;
turn restrictions are preserved across the backbone/connector boundary.
Source identity, road classes, catalogue digest, schema/gateway versions,
speed defaults and connector policy are recorded in metadata. Preparation
publishes atomically, leaving an earlier database intact on failure.

`IntercityPlanner` owns one background worker, a read-only graph and a 64-entry
LRU route cache. Departure uses a committed local-graph snapshot and the
existing planner in strict mode: no off-road fallback. Joins require the actual
loaded OSM way, matching geometry and layer. The approach way is carried into
national turn-restriction state; an unprovable via-way history fails closed.
Searches have a ten-second worker deadline and support cancellation. Changing
the fare or handing off to the final address cannot publish a stale result.
Local map revisions do not invalidate a successful national route. Deviations
start a new connected departure; failed plans retry after map changes or after
the taxi moves 100 m.

The coordinator advances through a bounded route window (128 candidate segments,
at most 257 published points). National geometry reconstruction, simplification
and remaining-distance calculation happen in the worker. The existing phone
receives the same navigation protocol; no new renderer or autopilot is added.

`AutoFetchManager` accepts at most three route/approach priorities, sampling
the next 5 km even on long straight segments. The normal player 3×3 tile window
always has fetch priority. Destination-centre prefetch starts within 6 km.
Cancellation and final-address handoff remove route priorities. Raw/world/render
caches, collision loading and normal streaming integration are unchanged.

The existing taxi resolver alone chooses the final address and updates every
companion. A new distance guard rejects its old out-of-region fallback when
destination data is not loaded. Until resolution succeeds, the city destination
is retained; afterwards ordinary local navigation takes over. Intercity mode
requires automatic streaming and is not available on the sample map.

## Verification

`tests/test_intercity_lifecycle.py` exercises actual background planning, cached
repeated requests, unloaded-departure rejection, incoming turn restrictions,
fare cancellation, bounded streaming priorities, atomic initialization failure,
and the real taxi/map-sync final-address handoff with companions. Existing
navigation, PBF, traffic-world, level-routing and server/client tests are retained.

The rendering check is reproducible with:

```sh
godot --path godot --display-driver x11 --rendering-driver opengl3 \
  --script res://tests/intercity_render.gd
```

The settings and navigation screenshots were captured and visually inspected
at 1280×720. Godot's regression suite reports 3,183 checks, zero failures
(existing shutdown resource warnings remain).

Prepare the complete artifact (use `--backbone-only` only for isolated graph
benchmarks), then benchmark town approaches:

```sh
.venv/bin/python tools/osm/build_intercity.py SOURCE.pbf OUTPUT.intercity.sqlite
.venv/bin/python tools/osm/benchmark_intercity.py OUTPUT.intercity.sqlite \
  --town-pair Oulu Helsinki --town-pair Oulu Tampere --town-pair Helsinki Rovaniemi
```

`--town-pair` selects municipality entries, not similarly named stations.
Ambiguous or unsupported names are rejected; `--pair LABEL START_NODE END_NODE`
accepts explicit `places.anchor` IDs for landmark or other probes. Runtime fare
routing always uses stable IDs, never the first name match.

### Completed Finland validation, 2026-10-20

| Measurement | Result |
| --- | --- |
| Final junctions / stored segments / directed edges | 73,179 / 84,638 / 120,653 |
| Final artifact, including 351 landmark aliases/source cross-references | 20,365,312 bytes (19.4 MiB) |
| Supported catalogue destinations | 397 of 412 |
| Directed approach pairs retained | 1,180 |
| Weak / strong components; largest strong component | 50 / 1,437; 70,761 nodes |
| Graph open / compatible startup reuse | 0.275 / 0.344 s |
| Peak query-process resident memory | 121,296 KiB |
| Full preparation run before spatial town prefiltering, including temporary town extraction | 6 min 33 s; 2,336,968 KiB peak process memory |
| Full preparation with spatial town prefiltering | 5 min 00 s; 2,328,152 KiB peak process memory |
| Final gateway-policy validation, reusing that temporary extract and rebuilding the backbone | 39.5 s; 2,264,256 KiB peak process memory |

The spatial prefilter saved 1 min 33 s (about 24%) on the same machine, but did
not materially reduce peak memory: building the 3.5-million-element temporary
town graph remains the dominant cost. The earlier full preparation timing
preceded the spatial town prefilter and final anchor prefilter improvements;
the final validation reused its extracted town graph, not a second national
street cache. Temporary extracts are not part of the final artifact. Offline
preparation is memory-intensive and may take several minutes; it is not done
on the simulation tick or on ordinary startup with intercity fares disabled.

All required town-to-town pairs passed ordered-source-segment and reconstructed
geometry continuity checks:

| Town route | First / repeated A* | Distance | Segments / geometry points |
| --- | --- | --- | --- |
| Oulu–Helsinki | 0.248 / 0.257 s | 670.8 km | 1,481 / 7,706 |
| Oulu–Tampere | 0.116 / 0.127 s | 483.2 km | 581 / 5,394 |
| Helsinki–Rovaniemi | 0.569 / 0.547 s | 889.2 km | 1,801 / 10,946 |

The actual background coordinator was also exercised with departure roads
reconstructed from the source OSM geometry and real local `TrafficWorld`
snapshots. First/cached requests took 0.588/0.049 s, 0.155/0.042 s and
0.517/0.060 s respectively. Cached requests still validate the current local
departure and prepare the published route; they are not just dictionary lookups.

The 15 unsupported catalogue entries are Hartola, Hollola, Inari, Simo, Ypäjä,
Kajaanin lentoasema, Mariehamns flyplats, Kiiala, Kylänlahti, Misi,
Pihlajavesi, Vuonislahti, Вяртсиля, Кивиярви and Светогорск. Their current
centres have no validated bidirectional approach under the bounded policy.
They are excluded from offers; this is not a claim that their roads are absent
from OSM. No required acceptance pair failed.

Verification is automated plus rendered UI inspection, not a manual physical
drive over every kilometre. Existing local-planner traffic-law limitations
remain those documented in `finnish-npc-traffic-law.md`; this change does not
certify all local traffic behavior.

Final combined Python regression run: 242 passed, including alias/provenance
and per-town connector-policy regressions. Compilation and
`git diff --check` pass. The temporary town extracts and superseded benchmark
databases were removed after verification; the PBF source is retained.

Implementation files: `intercity.py`, `intercity_places.py`,
`intercity_navigation.py`, `navigation_route.py`, `taxi.py`, `traffic_world.py`,
`osm/autofetch.py`, `world_loader.py`, `game_args.py`, `config.py`,
`server/__init__.py`, Godot `startup.gd`/`i18n.gd`, the two `tools/osm`
intercity tools, and the intercity/lifecycle/render regression tests.
No required implementation stage remains pending; unsupported destinations
and manual full-distance driving remain the limitations listed above.
