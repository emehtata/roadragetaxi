Implement a lightweight nationwide intercity routing graph for
Road Rage Taxi using the existing OpenStreetMap PBF data.

IMPORTANT: This is NOT a full street-routing implementation.

The game uses a two-stage destination system:

1. A long-distance destination is initially specified by city or
   town name.
2. The game routes the vehicle between the origin and destination
   cities using the major road network.
3. The destination city's map data is loaded when necessary.
4. The actual final destination is selected only after sufficient
   map data has been loaded.
5. Existing local navigation then handles the final approach.

The new system must support this architecture rather than replacing
it with full-resolution routing across all streets in Finland.

PROJECT CONSTRAINTS

- Inspect the existing implementation before changing anything.
- Preserve the current Python simulation server.
- Preserve Godot as the rendering client.
- Preserve the existing map tile loading and caching systems.
- Preserve the current local navigation implementation.
- Do not require destination-city map tiles to be loaded before
  calculating an intercity route.
- Do not include residential streets or the complete local street
  network in the intercity routing graph.
- Do not introduce BIN technology for map-data architecture.
- Do not add an external online routing dependency.
- Do not introduce unnecessary third-party routing engines.
- Do not create or push Git tags.
- Do not push commits or branches unless explicitly requested.
- Do not introduce arbitrary NPC count limits as a performance fix.

PHASE 1: AUDIT THE CURRENT GAME

Inspect the current implementation and identify:

- How long-distance destinations are represented.
- How city names are resolved to destination locations.
- How the game currently selects a destination within a city.
- How map loading affects destination selection.
- How local navigation works.
- How road geometry is represented.
- How vehicles follow routes.
- How routes are stored and updated.
- How OSM PBF files are currently processed.
- How the existing rendering tiles are generated and cached.

Identify the smallest integration points needed for intercity routing.

Do not replace existing destination selection or local navigation.

PHASE 2: EXTRACT THE MAJOR ROAD NETWORK

Build a separate routing dataset from the available Finland-wide
OSM PBF file.

Include these OSM highway classes by default:

- motorway
- motorway_link
- trunk
- trunk_link
- primary
- primary_link
- secondary
- secondary_link

Treat these classes as configurable.

Do not include residential streets, service roads, parking aisles,
or the complete local street network in the intercity graph.

The initial objective is a connected and efficient intercity graph,
not a street-level navigation graph.

Inspect the source data and document any connectivity gaps caused
by excluding lower road classes.

If lower-class roads are required to connect important towns to the
major road network, introduce a narrowly scoped, configurable
connection strategy instead of automatically including every road.

Respect:
- One-way restrictions.
- Access restrictions.
- Vehicle restrictions.
- Turn restrictions where they affect graph transitions.
- Road closures represented by the available data where practical.

Do not connect roads merely because their geometries are close.
Use actual OSM topology and validated connections.

PHASE 3: SIMPLIFY THE GRAPH

Create a compact graph suitable for long-distance routing.

Preserve significant nodes such as:

- Major junctions.
- Motorway interchanges.
- Branches between important roads.
- Changes in road connectivity.
- Town and city access points.
- Points required to preserve valid routing transitions.

Collapse unnecessary intermediate geometry nodes into road segments
while retaining the geometry required to reconstruct the route.

Store only the data needed for intercity navigation, such as:

- Node coordinates.
- Directed road-segment endpoints.
- Segment length.
- Estimated travel time.
- Road classification.
- Relevant speed information.
- Geometry needed for route following.
- Required routing restrictions.

Avoid duplicating complete road geometry unnecessarily.

Do not remove nodes or merge segments if doing so would invalidate
one-way restrictions, junction connectivity, or turn restrictions.

Use a compact, versioned data format appropriate for the existing
project. Follow the repository's established conventions where
possible.

Do not assume a specific storage format before inspecting the
current code and available dependencies.

PHASE 4: CONNECT CITIES TO THE GRAPH

Extract suitable city and town locations from the available OSM data.

Inspect the existing city-name resolution and destination-selection
logic before implementing a new representation.

For each supported city:

- Identify a suitable access point on the major road network.
- Ensure the access point is connected to the correct road segment.
- Preserve a stable association between the city identifier and
  its graph access point.
- Avoid arbitrary nearest-node connections that can cross rivers,
  railways, or other disconnected terrain.
- Handle cities with multiple suitable access points when useful.
- Support duplicate or ambiguous place names using the existing
  destination-resolution rules.

A city access point is an intercity routing anchor. It is NOT the
final passenger destination.

Do not select a street address or final destination at this stage.

PHASE 5: IMPLEMENT INTERCITY ROUTING

Implement a lightweight routing algorithm for the simplified graph.

Start by evaluating A* with an admissible distance-based heuristic.

Use a cost function based on estimated driving time rather than
straight-line distance alone.

Respect directed edges and valid road transitions.

Do not use straight-line movement between cities as the final route.

The route must follow the connected major road network.

Return an intercity route containing:

- Origin city identifier.
- Destination city identifier.
- Ordered road-segment or graph-node sequence.
- Reconstructable road geometry.
- Estimated distance.
- Estimated driving time.
- Necessary road transition information.

If the graph proves too large or A* performance is insufficient,
measure the problem before introducing more advanced techniques.

Do not implement a full routing engine unnecessarily.

PHASE 6: INTEGRATE WITH EXISTING DESTINATION LOGIC

Integrate the new graph with the existing two-stage destination
workflow.

The intended flow is:

1. Resolve the origin and destination cities.
2. Find the corresponding intercity graph access points.
3. Calculate the major-road route between them.
4. Let the existing simulation follow that route.
5. Allow the existing map-loading system to load nearby tiles.
6. When the destination city's map is sufficiently available,
   invoke the existing destination-selection process.
7. Continue using the existing local navigation system for the
   final approach.

Do not require all tiles along the route to be loaded.

Do not change the meaning of the existing destination-selection
mechanics.

If the current vehicle movement code requires additional
information, adapt the smallest possible interface.

The server remains authoritative for vehicle movement and
simulation rules.

PHASE 7: PERFORMANCE

Measure:

- Number of graph nodes.
- Number of directed road segments.
- Prepared graph size on disk.
- Graph loading time.
- Memory usage.
- Route calculation latency.
- Route geometry size.
- Performance with repeated city-to-city requests.

Use real measurements from the available PBF.

Do not invent benchmark results.

Avoid rebuilding the graph at game startup.

Prepare the graph offline and load it using an efficient method.

Cache reusable city-to-city routes where appropriate.

Do not recalculate an unchanged route every simulation tick.

If memory usage is excessive, investigate graph simplification,
compact storage, and loading behavior before introducing unrelated
performance workarounds.

PHASE 8: VALIDATION

Add tests for:

- Graph construction.
- Graph connectivity.
- One-way roads.
- Important road junctions.
- City access points.
- Duplicate city names.
- Routes between distant cities.
- Routes within different regions of Finland.
- Missing city access points.
- Unreachable destinations.
- Invalid or incomplete graph data.
- Route geometry reconstruction.
- Compatibility with existing local navigation.
- Correct handoff to destination-city map loading.

Include representative long-distance routes, such as Oulu–Helsinki,
Oulu–Tampere, and Helsinki–Rovaniemi, provided the available PBF
contains the required network.

Validate the routes against the actual road graph. Do not rely
only on straight-line distance or successful algorithm termination.

Check that the intercity graph does not accidentally include the
full residential street network.

Check that local navigation and rendering continue to work as
before.

PHASE 9: DOCUMENTATION

Document:

- The intercity routing architecture.
- Included and excluded road classes.
- How to build the graph from the PBF.
- How city access points are selected.
- How to calculate and reconstruct routes.
- How the graph integrates with the existing destination workflow.
- How to run the tests.
- Measured graph size, loading time, memory use, and route latency.
- Known connectivity limitations.

Do not refactor unrelated systems.

Before finishing, report:

1. The existing architecture discovered.
2. The graph format and algorithm selected.
3. Files added or modified.
4. Tests executed and their results.
5. Actual performance measurements.
6. Any cities or road connections that could not be routed.
7. Remaining work.

Begin with the audit. Implement the smallest complete solution
that supports nationwide intercity routing while preserving the
existing local navigation and rendering systems.