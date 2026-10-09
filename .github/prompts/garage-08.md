# Road Rage Trip — Phase 9: Driving Through Level Connectors

You are working on the `Road Rage Trip` repository.

**Branch:** `release/0.15.0alpha`

This is **Phase 9** of the parking-garage / map-level implementation.

Phases 1–8 have established:

* `ParkingGarage`
* `Car.map_level`
* level-aware rendering
* level-aware driving networks
* level-aware collision/environment checks
* `LevelConnector`
* `world.level_connectors`
* OSM `amenity=parking_entrance` connector nodes
* connector-to-road topology through `road_osm_ids`

Phase 9 introduces the first actual **level transition while driving**.

---

# 1. Objective

Allow the player to drive through an OSM-defined parking entrance and transition between logical map levels.

The transition must be based on actual OSM topology.

The fundamental rule is:

> Being near a connector must never by itself change the player's level.

The player must actually drive through the connector, and the connected road data must provide sufficient evidence for the destination level.

After a successful transition:

```python
car.map_level
```

changes to the destination level.

Existing Phase 5–7 systems already use `Car.map_level`, so rendering, driving networks and collision behaviour should then automatically follow the new level.

---

# 2. Existing authoritative architecture

Do not replace the existing level system.

These existing rules remain authoritative:

```text
0       = surface
-1      = underground level 1
-2      = underground level 2
+1      = level above surface
```

`map_level=None` means surface world for objects that do not explicitly carry a level.

For `Car`:

```python
Car.map_level
```

is always an explicit integer.

Existing Phase 6/7 systems already select:

```text
surface road network
        OR
LevelRoadNetworks.network(car.map_level)
```

based on `Car.map_level`.

Do not duplicate this logic.

---

# 3. Existing Phase 8 connector model

Phase 8 added:

```python
LevelConnector
```

and:

```python
world.level_connectors
```

The connector contains, according to the current implementation:

```text
osm_type
osm_id
connector_type
x
y
map_level
level
parking
garage_osm_id
road_osm_ids
```

For Oulu:

```text
22 connectors
9 linked to garages
2 with known map_level
20 with unknown map_level
21 with road_osm_ids
```

The important topology field is:

```python
connector.road_osm_ids
```

These are the OSM road IDs passing through the entrance node.

Use the existing implementation rather than redesigning the connector model.

---

# 4. Critical semantic rule

Do NOT treat:

```text
connector.map_level
```

as the destination level.

The connector's own:

```text
level=-1
```

means the connector is mapped on level -1.

It does NOT necessarily mean:

```text
surface → -1
```

Likewise:

```text
level=0
```

does not necessarily mean:

```text
-1 → 0
```

The connected road topology must be inspected.

---

# 5. Multi-level road values

This is the most important part of Phase 9.

Existing roads may have:

```text
level=0
level=-1
```

or multi-level raw values such as:

```text
level=0;-1
```

The existing `parse_map_level()` intentionally does not convert:

```text
0;-1
```

to a single `Way.map_level`.

Do not change that behaviour.

Instead, Phase 9 needs a small helper that can interpret a road's **raw level value for connector topology**.

For example:

```python
road.map_level
road.level
```

may provide:

```text
map_level = 0
level = "0"
```

or:

```text
map_level = None
level = "0;-1"
```

The connector transition logic may parse the raw multi-level value into a set of explicit integer levels for topology analysis.

Conceptually:

```python
"0;-1" -> {0, -1}
```

but:

```text
"0-1"
"1.5"
"foo"
```

must not be silently converted into invented levels.

Do not modify the meaning of `Way.map_level`.

---

# 6. Build a small topology helper

Create a repository-appropriate helper, preferably in the existing map-level module or another clearly appropriate module.

Its responsibility should be approximately:

```text
Way
 ↓
explicit level information
 ↓
set of known logical levels for connector analysis
```

Examples:

```text
map_level = -1
level = "-1"

→ {-1}
```

```text
map_level = 0
level = "0"

→ {0}
```

```text
map_level = None
level = "0;-1"

→ {0, -1}
```

```text
map_level = None
level = None

→ {}
```

Do not infer level from:

```text
layer
tunnel
covered
building
garage membership
geometry
```

---

# 7. Connector topology resolution

For each connector:

```python
connector.road_osm_ids
```

find matching roads from:

```text
world.ways
world.level_ways
```

using the existing OSM ID conventions.

Do not search roads by nearest geometry if the OSM ID is available.

The connector already tells us which roads pass through its node.

---

# 8. Determine candidate levels

For each connected road:

1. inspect `Way.map_level`
2. inspect raw `Way.level`
3. derive explicit known levels for topology purposes
4. collect them into a set

For example:

```text
outside road:
level=0

inside road:
level=0;-1
```

produces:

```text
{0, -1}
```

This gives evidence for a:

```text
0 ↔ -1
```

transition.

Another example:

```text
road A:
level=-1

road B:
level=-2
```

gives:

```text
{-1, -2}
```

and therefore potentially:

```text
-1 ↔ -2
```

---

# 9. Do not invent transitions

This is a hard rule.

A connector must NOT produce a level transition merely because:

```text
garage.levels = (-3, -2, -1)
```

or because it is physically inside a garage.

For example:

```text
connector
garage levels = {-3,-2,-1}
road levels = {-1}
```

does NOT imply:

```text
-1 → -2
```

There must be road/topology evidence.

---

# 10. Connector's own level

Use the connector's own `map_level` as supporting evidence.

For example:

```text
connector.map_level = -1

roads:
level=0
level=0;-1
```

This is consistent with:

```text
0 ↔ -1
```

But:

```text
connector.map_level = -1

roads:
level=-2
```

does not automatically prove:

```text
-1 ↔ -2
```

unless the connected topology provides both levels.

The road topology remains authoritative.

---

# 11. The actual transition rule

The player may change levels only when all of the following are true:

1. The player is on a road associated with the connector.
2. The player physically crosses the connector's transition location.
3. The connector has enough explicit road-level evidence to identify another level.
4. The destination level is different from `car.map_level`.
5. The destination level is an actual known level represented by the connected roads.

No condition may be replaced by simple proximity.

---

# 12. Do not trigger on proximity alone

This must NOT happen:

```python
distance(car, connector) < threshold
    → car.map_level = ...
```

A player driving past an entrance must not suddenly disappear underground.

Likewise:

```text
player parked next to entrance
```

must not trigger a transition.

The car must cross the connector.

---

# 13. Detect crossing, not merely overlap

Implement transition detection using the player's movement between the previous and current simulation positions.

Conceptually:

```text
previous player position
        ↓
current player position
        ↓
did movement cross the connector?
```

Do not repeatedly trigger while the player remains stationary near the connector.

A suitable method may use:

* movement segment
* connector point
* road association
* small transition radius
* previous/current distance

but use the simplest implementation compatible with the existing coordinate system.

Avoid expensive geometry operations every frame.

---

# 14. Avoid false triggers

The following must not cause a transition:

```text
car is stationary at connector
car drives near connector but stays on same road
car passes a nearby connector belonging to another road
car is on a different map level
car is on an unrelated road crossing the same area
```

Use `road_osm_ids` to establish the actual road relationship.

---

# 15. Avoid repeated transitions

A connector must not immediately toggle the player:

```text
0 → -1 → 0 → -1 → ...
```

on consecutive frames.

Introduce an appropriate transition state/cooldown/arming mechanism.

The exact implementation should follow the existing game simulation architecture.

A good conceptual state is:

```text
armed
→ crossing
→ transitioned
→ disarmed until leaving connector area
→ armed again
```

The state must not become a permanent global lock.

The player must be able to:

```text
enter garage
↓
drive around
↓
later return
↓
leave garage
```

normally.

---

# 16. Direction

Do not assume that every connector is directional.

If the OSM data does not provide a reliable direction:

```text
0 → -1
```

should be possible in one direction and:

```text
-1 → 0
```

in the reverse direction.

The transition is determined by:

```text
current level
+
connected levels
+
actual traversal
```

not by an invented entrance/exit direction.

---

# 17. Same-level roads

A connector can have roads that all resolve to the same level.

For example:

```text
road A: level=0
road B: level=0
```

This must not cause a transition.

Likewise:

```text
road A: level=-1
road B: level=-1
```

must not change the player's level.

A transition requires:

```text
current level
    !=
destination level
```

---

# 18. Ambiguous connectors

If a connector has:

```text
road levels = {0, -1, -2}
```

do not arbitrarily select:

```text
-1
```

or:

```text
-2
```

unless the current topology provides a clear destination.

For example, if:

```text
car.map_level = 0
```

and the connector clearly connects:

```text
0 ↔ -1
```

while `-2` belongs to a separate multi-level road representation, resolve only what can be proven.

If the implementation cannot determine a unique destination:

```text
no transition
```

is the correct behaviour.

---

# 19. Current-level consistency

Before triggering a transition, verify that the player's current level is represented by the connector topology.

For example:

```text
car.map_level = 0
connector roads = {-1}
```

must NOT cause:

```text
0 → -1
```

merely because `-1` is the only known level.

The connector must provide evidence for both sides or otherwise explicitly identify the current side.

This prevents unknown topology from becoming an accidental teleport.

---

# 20. Multi-level road as transition evidence

The expected Oulu pattern is:

```text
outside road
    level=0

        |
        | parking entrance
        |

inside road
    level=0;-1
```

The inside road explicitly indicates both levels.

In this situation the connector can safely establish:

```text
0 ↔ -1
```

provided the player is actually traversing the connector.

This is the primary real-world case to support.

---

# 21. Level -1 → -2

The implementation should also support deeper levels when OSM provides sufficient evidence.

For example:

```text
connector
roads:
    level=-1
    level=-1;-2
```

allows:

```text
-1 ↔ -2
```

The same logic must work for:

```text
-2 ↔ -3
```

and positive levels if such data exists.

Do not hard-code underground-only transitions.

---

# 22. Car level update

When a valid transition occurs:

```python
car.map_level = destination_level
```

must be the authoritative state change.

Do not create:

```text
current_level
render_level
physics_level
route_level
```

as separate state.

The existing architecture already uses:

```python
Car.map_level
```

for these systems.

---

# 23. Do not reload the world

Changing:

```python
car.map_level
```

must NOT:

* reload OSM
* reload the tile
* rebuild the world cache
* rebuild all scenery
* fetch Overpass
* recreate the map
* recreate the player
* recreate the car

Phase 5–7 already established level switching as an in-memory operation.

Use that architecture.

---

# 24. Driving network behaviour

After:

```python
car.map_level = -1
```

existing Phase 6 code must automatically use:

```text
LevelRoadNetworks.network(-1)
```

for the player's road queries.

Do not create a special connector-specific driving network.

Do not add connector edges to `RouteGraph`.

This phase only changes the player's level.

---

# 25. Collision behaviour

Existing Phase 7 collision logic must automatically follow:

```python
car.map_level
```

after transition.

Do not duplicate or modify building/tree/environment collision architecture unless a regression is discovered.

If a collision bug is found because some code still assumes surface level, fix that specific bug rather than creating connector-specific collision logic.

---

# 26. Rendering behaviour

Existing Phase 5 rendering must automatically follow:

```python
car.map_level
```

after transition.

Do not add special garage rendering.

Do not add entrance animations.

Do not add loading screens.

Do not add fade-to-black transitions unless the existing architecture already has a trivial transition mechanism and it has no meaningful performance impact.

For this phase, an immediate level change is acceptable.

---

# 27. Debug information

Add useful debug information only when the existing debug HUD is enabled.

For example:

```text
Level: -1
Connector: 123456
Transition: 0 -> -1
```

Do not display this in normal gameplay.

If the existing debug HUD has no suitable place, do not create a large new UI system.

---

# 28. Performance

Connector detection must be cheap.

There are currently only around:

```text
~20 connectors per city
```

so a simple list scan is acceptable.

Do not create a complicated spatial index prematurely.

However:

> Do not perform expensive road searches or geometry processing for every connector on every frame.

A good approach is:

```text
player movement
    ↓
cheap connector candidate scan
    ↓
only nearby candidates
    ↓
road/topology verification
    ↓
transition
```

Cache derived connector topology where practical.

---

# 29. Derived topology cache

It is acceptable and recommended to derive connector transition information once when map data changes.

For example:

```text
LevelConnector
    ↓
resolved_levels
```

or:

```text
LevelConnector
    ↓
possible transitions
```

Conceptually:

```python
connector.transitions
```

could contain:

```text
{0: -1}
{-1: 0}
```

But do not persist derived data in the OSM model/cache unless there is a strong reason.

Prefer deriving it during world/map synchronization.

This avoids stale derived information when tiles change.

---

# 30. Tile streaming

Connectors can disappear when their tile unloads.

The transition logic must handle this safely.

Do not keep stale connector references after tile unload.

If a connector is removed:

```text
world.level_connectors
```

must no longer be used by transition detection.

No dangling references.

---

# 31. Tile boundary edge case

A connector and one of its roads may originate from different loaded tiles.

Do not assume that the connector and every referenced road always arrive in the same tile.

Before resolving connector topology:

```text
road_osm_ids
```

may temporarily have missing roads.

In that situation:

```text
no transition yet
```

is preferable to inventing topology.

As additional tiles are loaded, the connector's derived topology should become resolvable during normal map synchronization.

---

# 32. Do not make level switching dependent on tile fetching

The player should never trigger:

```text
connector
→ network fetch
→ wait
→ level change
```

Level transitions only use currently loaded data.

If required road data is unavailable:

```text
no transition
```

for now.

Do not block gameplay.

---

# 33. Route graph

Do NOT implement cross-level routing.

The existing route graph remains level-specific/surface-specific.

For example:

```text
surface route
```

must not suddenly become:

```text
surface
→ parking entrance
→ underground
```

in Phase 9.

Future routing work can consume the same connector topology later.

---

# 34. NPCs

Do not implement NPC level transitions.

The player's transition is the only gameplay actor affected.

NPC traffic remains surface-only.

---

# 35. Pedestrians

Do not implement pedestrian level transitions.

Existing pedestrian behaviour remains unchanged.

---

# 36. Tests

Add focused unit tests for topology resolution.

At minimum test:

### Simple transition

```text
road A: level=0
road B: level=0;-1
current level=0

→ destination=-1
```

### Reverse transition

```text
current level=-1

→ destination=0
```

### Same-level connector

```text
road A: level=0
road B: level=0

→ no transition
```

### Unknown level

```text
road A: no level
road B: no level

→ no transition
```

### Ambiguous topology

```text
levels={0,-1,-2}

→ no arbitrary destination
```

unless the topology provides an unambiguous current/destination pair.

### Connector own level

Verify that:

```text
connector.level=-1
```

does not itself create:

```text
0 → -1
```

without road evidence.

### Layer independence

```text
layer=-1
```

must never become a map-level transition.

### No garage inference

Garage levels must not create a transition when road evidence is missing.

### Missing road

A connector referencing a road that is currently unloaded must not crash or transition incorrectly.

### Crossing

Verify that:

```text
car movement
```

through a valid connector causes exactly one transition.

### Proximity

Verify that:

```text
car near connector
```

without crossing it does not transition.

### Stationary

Verify that a stationary car near a connector does not repeatedly transition.

### Re-entry

Verify:

```text
0 → -1
drive away
-1 → 0
```

works when the connector is traversed in reverse.

### Multiple connectors

A nearby unrelated connector must not affect the current transition.

---

# 37. Simulation integration tests

Test the actual player simulation path rather than only helper functions.

At minimum verify:

```text
surface
   ↓
drive through connector
   ↓
Car.map_level = -1
   ↓
player uses level -1 road network
   ↓
rendering uses level -1
   ↓
collision uses level -1
```

Do not duplicate these systems.

The tests should verify that the existing Phase 5–7 architecture reacts correctly to the changed `Car.map_level`.

---

# 38. Oulu real-data validation

Run the implementation against the existing Oulu benchmark data.

Report:

* number of connectors
* number with resolved topology
* number producing valid level transitions
* number ambiguous
* number unresolved because referenced roads are unavailable
* examples of each important topology pattern

Do not hard-code expected counts.

The existing known data is:

```text
22 connectors
21 with roads
2 with connector map_level
20 without connector map_level
```

Use these as a sanity check, not as immutable expected values.

---

# 39. Important Oulu limitation

Phase 8 found:

> `parking=entrance` does not occur in the Oulu data.

Do not add support for it merely because it sounds useful.

Likewise:

* `ramp=*` was found on stairs
* `level:ref=*` was found on indoor shops

Do not reinterpret those tags as parking level connectors.

Keep Phase 9 based on:

```text
amenity=parking_entrance
```

and the associated road topology.

---

# 40. Garage relation limitation

Phase 8 established that:

> An entrance on a member way of a garage relation may have no `garage_osm_id`.

Do not require:

```python
connector.garage_osm_id
```

for a transition.

Road topology is the important information.

Garage association is metadata.

---

# 41. Failure behaviour

When transition evidence is insufficient:

```text
do nothing
```

Do not:

* guess
* teleport
* choose nearest level
* choose lowest level
* choose highest level
* use garage levels as fallback
* use `layer`
* use tunnel/covered
* use distance alone

A false negative is preferable to an incorrect level transition.

---

# 42. Required implementation workflow

Follow this order.

## Step 1 — Audit

Inspect:

* `LevelConnector`
* `world.level_connectors`
* `Way`
* `Way.map_level`
* `Way.level`
* `Car.map_level`
* `LevelRoadNetworks`
* player simulation/movement
* map synchronization
* tile streaming

Do not assume the architecture from this prompt. Read the current implementation.

## Step 2 — Implement level parsing for topology

Add a small helper for interpreting explicit raw multi-level road values.

Keep `Way.map_level` semantics unchanged.

## Step 3 — Resolve connector topology

Build derived transition information from:

```text
connector.road_osm_ids
+
Way.map_level
+
Way.level
```

## Step 4 — Integrate into simulation

Detect actual traversal of a connector.

## Step 5 — Change `Car.map_level`

Only after the transition has been positively identified.

## Step 6 — Regression test

Verify that Phase 5–7 systems automatically follow the new level.

## Step 7 — Real-data validation

Test against Oulu.

## Step 8 — Performance validation

Verify no significant frame-time regression.

---

# 43. Things explicitly NOT to implement

Do NOT implement:

* cross-level routing
* route graph connector edges
* NPC transitions
* pedestrian transitions
* connector physics
* ramp physics
* garage parking
* parking-space selection
* connector rendering
* automatic transition from proximity
* garage-level inference
* geometry-based level inference
* `layer` → level
* `tunnel` → level
* `covered` → level
* `parking garage levels` → transition
* network fetching during transition
* loading screens
* world reloads
* new parallel level architecture

---

# 44. Acceptance criteria

Phase 9 is complete only when:

* [ ] The existing `LevelConnector` model is reused.
* [ ] `road_osm_ids` are used for connector topology.
* [ ] `Way.map_level` semantics remain unchanged.
* [ ] Raw multi-level road values such as `0;-1` can be interpreted for connector analysis.
* [ ] Invalid/ambiguous level values are not guessed.
* [ ] Connector topology is derived from actual OSM road data.
* [ ] Garage levels are never used to invent transitions.
* [ ] Layer/tunnel/covered are never interpreted as map levels.
* [ ] A connector near the player does not trigger a transition by itself.
* [ ] Actual traversal can trigger a valid transition.
* [ ] The transition changes only `Car.map_level`.
* [ ] The destination level is unambiguous.
* [ ] Repeated transitions are prevented while remaining at the connector.
* [ ] Reverse traversal works.
* [ ] Same-level connectors do nothing.
* [ ] Missing road data fails safely.
* [ ] Tile unloads cannot leave stale connector references.
* [ ] No OSM/network fetch is triggered by a transition.
* [ ] No cross-level route graph is introduced.
* [ ] NPCs remain unchanged.
* [ ] Pedestrians remain unchanged.
* [ ] Existing rendering automatically follows the new level.
* [ ] Existing collision automatically follows the new level.
* [ ] Existing level-aware driving networks automatically follow the new level.
* [ ] Focused tests pass.
* [ ] Full test suite passes.
* [ ] Oulu real-data validation is completed.
* [ ] No significant per-frame performance regression is introduced.

---

# 45. Final implementation report

Provide a concise report containing:

1. files changed
2. topology-resolution implementation
3. how `level=0;-1` and similar raw values are handled
4. exact transition detection mechanism
5. anti-repeat/re-arm mechanism
6. how missing/unloaded road data is handled
7. Oulu transition statistics
8. tests added and results
9. full test-suite result
10. performance results
11. examples of successfully resolved transitions
12. ambiguous cases intentionally rejected
13. any remaining limitations

Clearly separate:

```text
implemented in Phase 9
```

from:

```text
intentionally deferred to later phases
```

The implementation must preserve the existing map-level architecture and must never guess a level transition from incomplete OSM information.
