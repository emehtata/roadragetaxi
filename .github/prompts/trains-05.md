## Railway Phase 5 – Visible Station Passengers

### Goal

Extend the existing railway passenger simulation so that passengers become visible NPCs when they are physically present at railway stations.

The current implementation already supports:

* railway infrastructure
* timetable-driven trains
* station mapping
* platform/track selection
* station arrival and departure
* passenger journeys as simulation data
* train passenger manifests
* passengers boarding trains
* passengers leaving trains

Passengers are currently represented only as data.

This phase connects that passenger data to the existing pedestrian/NPC system so that railway passengers become visible in the game world when they are at a station.

---

# 1. Inspect the existing implementation first

Before changing code, inspect:

* current passenger journey model
* train passenger manifests
* station waiting-passenger collections
* passenger boarding/alighting logic
* existing pedestrian NPC classes
* existing Resident NPC implementation
* pedestrian spawning/despawning
* pedestrian movement/pathfinding
* pedestrian target/destination system
* station and railway geometry
* existing NPC spatial/grid systems

Do not create a separate pedestrian simulation system if the existing pedestrian architecture can be reused.

The goal is to integrate passengers into the existing NPC system, not create a second NPC framework.

---

# 2. Passenger lifecycle

Implement the following lifecycle:

```text
Passenger journey data
        ↓
WAITING_AT_STATION
        ↓
visible station passenger
        ↓
BOARDING
        ↓
ON_TRAIN
        ↓
ARRIVED
        ↓
visible station passenger
```

The important rule is:

> A passenger must be represented either as lightweight train/station data or as a visible NPC, never both at the same time.

When a passenger is inside a train:

```text
Passenger → data only
```

When a passenger is physically at a station:

```text
Passenger → visible pedestrian NPC
```

---

# 3. Reuse the existing pedestrian NPC system

Do not create a dedicated `RailwayPassengerNPC` system unless the existing architecture genuinely requires it.

Prefer:

```text
PassengerJourney
        ↓
Pedestrian NPC
```

with passenger-specific metadata attached to the existing pedestrian entity where appropriate.

The existing pedestrian movement, rendering, animation, spatial indexing, and despawning mechanisms should remain responsible for the visible NPC.

The passenger journey remains the source of truth for railway-specific state.

---

# 4. Waiting passengers

Passengers waiting for a train should become visible in the station area.

When a passenger enters:

```text
WAITING_AT_STATION
```

create or activate a corresponding pedestrian NPC.

The NPC should be placed at a reasonable position associated with the station.

Do not require the passenger to spawn exactly on a platform unless the existing OSM data provides a reliable platform geometry.

A reasonable initial approach is:

```text
station position
      ↓
small random/controlled offset
      ↓
pedestrian spawn position
```

Do not spawn all passengers at exactly the same coordinate.

---

# 5. Station passenger spawn area

Use the existing OSM station/platform information where available.

Prefer the following hierarchy:

1. matched OSM platform geometry
2. railway station geometry
3. station coordinate
4. reasonable fallback near the station

The implementation must gracefully handle stations where platform geometry is unavailable.

Do not assume every station has:

* a mapped platform
* a building
* a pedestrian-accessible polygon
* a detailed station area

The system must work with the existing map data.

---

# 6. Avoid spawning passengers on railway tracks

A passenger must never be spawned directly on:

* railway track geometry
* railway way centerlines
* inaccessible railway areas

If platform geometry is available, use it.

Otherwise find a nearby safe position using the existing pedestrian/spatial infrastructure.

Do not introduce expensive per-frame collision searches.

Spawn-position validation should happen when the passenger NPC is created.

---

# 7. Passenger appearance

Reuse the existing pedestrian appearance system.

Passengers should look like ordinary pedestrians.

Do not create a special railway passenger sprite set yet.

If the existing NPC system supports randomized:

* appearance
* clothing
* gender
* walking animation

reuse those mechanisms.

The player should not need to know visually that an NPC is a train passenger unless debug information is enabled.

---

# 8. Passenger identity

Maintain a stable relationship between:

```text
PassengerJourney
        ↕
Pedestrian NPC
```

The passenger should have a stable internal identifier.

When the passenger boards a train:

```text
PassengerJourney
    ↓
remove/despawn pedestrian NPC
    ↓
ON_TRAIN
```

When the passenger exits the train:

```text
ARRIVED
    ↓
spawn pedestrian NPC
```

Do not create a duplicate passenger object.

The same logical passenger should retain their journey identity across:

```text
station → train → station
```

---

# 9. Boarding behavior

When the scheduled train arrives:

1. Identify passengers assigned to that train.
2. Find their visible pedestrian NPCs.
3. Mark them as boarding.
4. Move them toward the appropriate station/platform area if the existing pedestrian movement system supports this cleanly.
5. Once boarding is completed, remove/despawn the pedestrian representation.
6. Add/retain the passenger in the train manifest.
7. Set state to `ON_TRAIN`.

For the first implementation, boarding does not need to be visually synchronized with individual train doors.

A simple station/platform boarding interaction is sufficient.

Do not block train departure indefinitely because a pedestrian cannot reach the platform.

---

# 10. Boarding timing

The train's existing timetable dwell system remains authoritative.

Passenger boarding must happen within the existing station dwell.

Do not extend the train's scheduled dwell just because passengers have not reached the train.

The railway simulation must remain deterministic.

If the pedestrian system cannot complete a visual boarding animation before departure:

```text
train departure
    ↓
remaining boarding passengers
    ↓
complete boarding state transition
    ↓
remove pedestrian representations
```

The passenger simulation must never make the train miss its timetable because of pedestrian movement.

---

# 11. Passengers leaving a train

When a train arrives at a passenger's destination station:

1. Remove the passenger from the train manifest.
2. Change the journey state to `ARRIVED`.
3. Spawn/activate the passenger's pedestrian NPC.
4. Place the NPC at the appropriate station/platform area.
5. Assign a pedestrian destination.

The passenger should now exist visibly in the game world.

---

# 12. Initial destination after leaving the train

Do not implement sophisticated passenger destination selection yet.

For now, assign a simple station-area destination.

Possible behavior:

```text
station/platform
      ↓
walk away from railway
      ↓
station exit / nearby pedestrian area
```

If the existing pedestrian system already supports destination selection, reuse it.

A reasonable initial target can be:

* station exit
* nearby road-accessible pedestrian location
* nearby map position away from railway infrastructure

Do not make the passenger search for a taxi yet.

---

# 13. Passenger movement

Passengers should use the existing pedestrian movement system.

Do not implement:

* railway-specific pathfinding
* indoor station navigation
* platform navigation meshes
* complex crowd simulation

If the current pedestrian system cannot find a path from the station, gracefully fall back to a simple nearby walking target or idle behavior.

The railway passenger system must not crash because an OSM station has poor pedestrian data.

---

# 14. Waiting passenger behavior

Waiting passengers should behave like normal pedestrians while waiting.

They may:

* stand
* perform idle animations
* walk short distances around the station area

Do not require them to continuously move.

Avoid creating artificial crowd movement just to make the station look busy.

The primary purpose of this phase is to make passenger presence visible.

---

# 15. Passenger despawning

Use the existing NPC lifecycle and spatial management.

Do not keep every passenger rendered indefinitely.

If a passenger leaves the active simulation area and the existing pedestrian system supports despawning, use that system.

However:

> Despawning a passenger NPC must not delete the underlying PassengerJourney.

The journey data remains authoritative.

If the passenger later needs to interact with a train, the visible NPC representation can be recreated.

---

# 16. Interaction with the existing Resident NPC system

Inspect how Resident NPCs currently work.

If residents already have:

* pedestrian movement
* spawning
* despawning
* navigation
* spatial indexing
* animation

reuse those mechanisms.

Do not duplicate them for railway passengers.

A passenger is essentially a pedestrian with an additional travel-state component.

Conceptually:

```text
Pedestrian
    +
PassengerJourney
```

rather than:

```text
Pedestrian system

RailwayPassenger system
```

---

# 17. Passenger-specific state

Keep railway-specific state separate from generic pedestrian state.

For example, conceptually:

```text
PassengerJourney
    passenger_id
    origin_station
    destination_station
    assigned_train
    state

Pedestrian
    position
    movement
    animation
    visibility
```

Do not put railway timetable logic into generic pedestrian movement code.

The railway system owns passenger journey state.

The pedestrian system owns physical representation.

---

# 18. Station crowd limits

Do not introduce a hard global passenger limit unless the existing NPC system requires one for performance.

The number of visible passengers should naturally follow the number of simulated railway passengers.

If performance becomes a concern, use the existing NPC visibility/spatial management mechanisms rather than introducing a railway-specific arbitrary cap.

Do not hide the passenger simulation behind a `MAX_VISIBLE_RAILWAY_PASSENGERS` constant without evidence that one is required.

---

# 19. Debugging

Extend existing debug information.

For a selected passenger, it should be possible to see:

```text
Passenger ID
Origin
Destination
Assigned train
Passenger state
Visible NPC ID
Current station
```

For a station:

```text
Station
Waiting passengers
Visible passengers
Boarding passengers
Passengers leaving trains
```

For a train:

```text
Train
Passenger count
Boarding count
Alighting count
```

If practical, add a simple debug marker/color or label for railway passengers.

Do not change normal passenger appearance solely for debugging.

---

# 20. Tests

Add focused tests for:

### Passenger → pedestrian

* waiting passenger creates a visible NPC
* passenger retains its journey identity
* passenger has a valid station position

### Safe spawning

* passenger is not spawned on railway geometry
* passenger uses platform geometry when available
* station-coordinate fallback works

### Boarding

* passenger NPC exists before boarding
* passenger NPC is removed after boarding
* passenger remains in train manifest
* passenger state becomes `ON_TRAIN`

### Alighting

* passenger is removed from train manifest
* passenger state becomes `ARRIVED`
* pedestrian NPC is created
* passenger is placed at destination station

### Multiple passengers

* passengers with different destinations behave independently
* passengers remaining on the train stay data-only
* only passengers whose destination is the current station leave

### Train timing

* passenger movement cannot extend train dwell
* train still departs according to timetable
* boarding/alighting state remains consistent if visual movement is incomplete

### Despawn/recreate

* pedestrian NPC can despawn without deleting PassengerJourney
* passenger representation can be recreated when required

### Regression

Verify that existing:

* train movement
* timetable
* station routing
* platform/track selection
* station dwell
* passenger manifest

continue to work.

---

# 21. Performance

This phase must not introduce per-frame expensive passenger processing.

Do not:

* pathfind every passenger every frame
* search every passenger against every station every frame
* scan all trains for every passenger every frame
* repeatedly search all railway geometry for passenger spawning

Use event-driven transitions:

```text
train arrives
    ↓
process alighting/boarding

train departs
    ↓
finalize boarding

passenger created
    ↓
create pedestrian representation

passenger arrived
    ↓
create pedestrian representation
```

The existing pedestrian system handles per-frame movement.

---

# 22. No taxi behavior yet

Do NOT implement any taxi interaction in this phase.

Specifically do not:

* generate taxi requests
* search for taxi stands
* select a taxi
* call the player's taxi
* create taxi passengers
* assign passenger fares

The next phase can build on:

```text
Passenger
    ↓
ARRIVED_AT_STATION
    ↓
travel decision
```

---

# 23. Acceptance criteria

The phase is complete when:

1. Passengers waiting for trains can become visible pedestrian NPCs.
2. Passengers use the existing pedestrian/NPC rendering system.
3. Passengers do not require a separate NPC simulation framework.
4. Passengers are not spawned directly on railway tracks.
5. Platform geometry is preferred when available.
6. Passengers boarding a train disappear from the station world representation.
7. Passengers inside trains remain lightweight data only.
8. Passengers leaving trains become visible NPCs at the destination station.
9. Passenger journey identity survives the transition:

   * station → train → station.
10. Passengers use the existing pedestrian movement system after leaving a train.
11. Boarding/alighting cannot delay scheduled train departure.
12. Existing train timetable and station dwell behavior remain unchanged.
13. Passenger despawning does not destroy passenger journey data.
14. Station passenger populations are visible in the game.
15. No taxi functionality is implemented yet.
16. No significant FPS regression is introduced.

### Development approach

Work incrementally:

1. Inspect the current passenger and pedestrian implementations.
2. Identify the clean integration point between PassengerJourney and Pedestrian NPC.
3. Implement visible waiting passengers.
4. Implement safe station/platform spawning.
5. Implement boarding transitions.
6. Implement visible alighting passengers.
7. Implement basic station-area pedestrian targets.
8. Integrate existing NPC despawning/spatial management.
9. Add debugging information.
10. Add tests.
11. Run existing railway, NPC, and performance tests.
12. Fix regressions before adding further passenger behavior.

Do not implement taxi demand or advanced passenger AI in this phase.

Do not rewrite the existing railway or pedestrian systems.
