# NPC Railway Traffic – Phase 2: Weekly Timetable Integration

## Goal

Extend the existing NPC railway system so that trains are generated and operated according to a **real Finnish passenger-train weekly timetable** instead of an artificial fixed spawn interval.

The existing train implementation already works well: trains follow OSM railway geometry and reverse at network endpoints.

**Keep that working.**

The goal of this phase is to connect the existing train movement system to real-world timetable data while keeping the simulation simple.

The trains do **not** need to stop at stations yet.

---

# 1. Important: Inspect the Existing Implementation First

Before changing anything, inspect the implementation created for Phase 1.

Understand:

* `RailwayManager`
* `RailwayNetwork`
* railway graph/segments
* `TrainNPC`
* train route generation
* train spawning
* train movement
* direction handling
* map boundaries
* game time
* camera/world coordinates
* OSM railway geometry
* existing configuration mechanisms

Do not replace the working railway movement implementation.

Extend it.

The existing train movement along railway geometry should remain responsible for the actual visual movement.

The timetable should primarily determine:

* **when a train exists**
* **which direction it enters from**
* **which train it represents**
* optionally its train type/number for debugging

---

# 2. Use Real Finnish Passenger Train Timetables

Use Fintraffic Digitraffic's public railway GTFS passenger dataset.

The relevant dataset is:

```text
https://rata.digitraffic.fi/api/v1/trains/gtfs-passenger.zip
```

The dataset is generated daily and contains current and future passenger trains.

Do not make a web/API request every time a train is spawned.

Instead:

1. Download the timetable dataset.
2. Parse it.
3. Convert the required data into a compact local format.
4. Store the processed timetable locally.
5. Let the game use the local timetable during gameplay.

The game itself should remain playable offline after the timetable has been downloaded.

---

# 3. Investigate the GTFS Dataset

Before implementing the importer, inspect the actual contents of the downloaded GTFS package.

Determine which files are needed, likely including:

```text
trips.txt
stop_times.txt
routes.txt
calendar.txt
calendar_dates.txt
stops.txt
```

Do not assume the exact structure without inspecting the real dataset.

Determine how to identify:

* train number
* train type
* operating days
* departure time
* arrival time
* ordered stops
* origin
* destination
* direction of travel

The importer must handle the actual Digitraffic GTFS structure rather than relying on assumptions.

---

# 4. Weekly Timetable Model

The game should ultimately have a compact representation similar to:

```text
TrainSchedule
    train_number
    train_type
    origin
    destination
    operating_days
    departure_time
    direction
```

For example:

```text
TrainSchedule
    train_number = 123
    train_type = IC
    origin = Helsinki
    destination = Oulu
    operating_days = Mon,Tue,Wed,Thu,Fri
    departure_time = 15:24
    direction = NORTHBOUND
```

Adapt the actual structure to the information available in the GTFS feed.

Do not unnecessarily retain the entire GTFS dataset in the game runtime.

---

# 5. Do Not Hard-Code Oulu

The system must remain generic.

Do not create special cases such as:

```text
if city == "Oulu":
```

or:

```text
if map == "Oulu":
```

The same system must work on any OSM map.

If a map contains railway infrastructure, the timetable system should determine which scheduled trains are relevant to that map.

---

# 6. Determine Train Direction

This is especially important.

The train must enter the map from the correct side based on its actual railway journey.

For example:

```text
Northbound train
        ↓
      MAP
        ↓
```

must enter from the **north/top edge** and travel southward through the map if the map's coordinate system and railway geometry indicate that this is the correct physical direction.

Likewise:

```text
Southbound train
        ↑
      MAP
        ↑
```

must enter from the **south/bottom edge**.

More generally:

```text
Eastbound
    → enters from west/left

Westbound
    ← enters from east/right

Northbound
    ↓ or ↑ according to the actual map coordinate convention

Southbound
    ↑ or ↓ according to the actual map coordinate convention
```

**Do not assume screen coordinates are geographic coordinates.**

Inspect the existing world coordinate system and determine the correct mapping between:

* latitude
* longitude
* world X/Y
* screen X/Y
* camera coordinates

Use actual railway geometry and geographic coordinates to determine the entry direction.

---

# 7. Direction Must Come From the Train Route

Do not determine direction merely from the train number.

Use the timetable's ordered stops/origin/destination and the geographical positions of the relevant railway locations.

For example:

```text
Helsinki
   ↓
Tampere
   ↓
Seinäjoki
   ↓
Oulu
   ↓
Rovaniemi
```

A train travelling:

```text
Helsinki → Oulu
```

is northbound.

A train travelling:

```text
Oulu → Helsinki
```

is southbound.

However, do not assume that every route is simply north/south.

The system should support:

```text
north
south
east
west
```

and preferably arbitrary railway orientations.

The important requirement is that the train enters from the physically correct end of the railway network.

---

# 8. Map Relevance

A train in the national timetable should only appear if its route actually intersects the currently loaded railway network.

For example:

```text
Train:
Helsinki → Oulu

Map:
Oulu

→ relevant
```

but:

```text
Train:
Helsinki → Turku

Map:
Oulu

→ not relevant
```

Do not spawn every Finnish train on every map containing railway tracks.

---

# 9. Connecting Timetable Data to OSM Railway Networks

This is the most important architectural problem in this phase.

GTFS describes railway journeys using stations/stops.

OSM describes railway geometry.

These are different datasets.

Create a robust mapping layer:

```text
GTFS station/stop
       ↓
geographical position
       ↓
OSM railway network
       ↓
railway network endpoint / direction
       ↓
TrainNPC
```

Do not require an exact OSM node match.

Use geographic proximity and existing OSM railway geometry to determine which railway network corresponds to a timetable stop.

The mapping should be cached rather than recalculated for every train.

---

# 10. Train Entry and Exit

The existing Phase 1 train behavior reverses trains at the network endpoint.

For Phase 2, change this behavior.

A scheduled train should conceptually behave like:

```text
outside map
    ↓
train enters
    ↓
travels through railway network
    ↓
leaves map
```

The train should **not automatically reverse and return** simply because it reached the visible network endpoint.

The timetable determines the service direction.

For example:

```text
northbound train:

north edge
    ↓
================ railway ================
                                      ↓
                                  south edge
```

Then the train disappears.

A separate southbound service later enters from the opposite side.

---

# 11. Do Not Yet Simulate the Entire Journey

This phase does not require simulating the train from its real-world origin all the way to its destination.

For example, an actual train may travel:

```text
Helsinki
   ↓
Tampere
   ↓
Seinäjoki
   ↓
Oulu
   ↓
Rovaniemi
```

If the player is in Oulu, simply create the train when its timetable says it should pass through the relevant area.

The train can then traverse the locally available railway network.

This is a **local visual simulation of the timetable**, not a complete national railway simulation.

---

# 12. Timetable Time vs Game Time

Use the existing Road Rage Taxi game-time system.

Do not introduce a second clock.

The timetable uses Finnish local time.

The importer/runtime must correctly handle:

* Finnish local time
* EET/EEST
* daylight saving time
* midnight crossings

Do not simply treat timetable times as UTC.

The game's existing simulation date and time should determine which timetable entries are active.

---

# 13. Weekly Schedule

The objective is to use a **weekly timetable**, not just today's trains.

Create a local representation such as:

```text
weekly_schedule.json
```

or the project's equivalent preferred format.

Conceptually:

```text
Monday
    train A
    train B
    train C

Tuesday
    train A
    train C

Wednesday
    ...

Thursday
    ...

Friday
    ...

Saturday
    ...

Sunday
    ...
```

Use the GTFS service calendar to determine operating days.

Do not manually guess weekday operation.

---

# 14. Train Identity

Each spawned train should retain its real timetable identity.

For example:

```text
TrainNPC
    train_number = 123
    train_type = IC
    scheduled_time = 14:35
    direction = NORTHBOUND
```

This is useful for debugging and future features.

Later this identity can be used for:

* station arrival
* passenger generation
* train delays
* train-specific behavior
* visual train types

Do not implement those features yet.

---

# 15. Train Appearance

Keep the existing working train appearance and movement.

Do not redesign the train rendering system unless necessary.

Optionally allow train type to influence the sprite later, but this phase does not require different visual models for:

```text
IC
Pendolino
InterCity
Commuter
etc.
```

A generic train is sufficient.

---

# 16. No Station Stops Yet

This is explicitly out of scope.

A train may pass directly through an OSM station.

It must not:

* stop
* wait for passengers
* open doors
* generate passengers
* interact with the taxi rank

For now:

```text
station
   ↓
train passes through
   ↓
continues
```

The timetable is used only to control train presence and direction.

---

# 17. No Collision Detection

Keep the Phase 1 behavior.

Do not add:

* train-to-train collision detection
* train-to-car collision detection
* train-to-pedestrian collision detection
* track occupancy logic
* signaling
* dispatching

Multiple trains may occupy the same railway segment if the timetable produces such a situation.

---

# 18. Avoid Per-Frame Pathfinding

Do not run graph searches every frame.

A scheduled train should get its local railway route once:

```text
schedule entry
      ↓
railway network
      ↓
TrainRoute
      ↓
TrainNPC
```

Then movement should remain the same lightweight geometry-following implementation that already works.

---

# 19. Timetable Import Tool

Prefer creating a separate data/import step rather than embedding the GTFS download/parsing process directly into the game's frame/update loop.

For example:

```text
tools/
    import_railway_timetable.py
```

or whatever structure fits the repository.

Conceptually:

```text
Digitraffic GTFS
       ↓
timetable importer
       ↓
compact local timetable
       ↓
Road Rage Taxi
```

The importer should be rerunnable whenever a new timetable dataset is needed.

Do not make the game download hundreds of megabytes of GTFS data at startup.

---

# 20. Cache the Timetable

Store the processed timetable locally.

Include metadata such as:

```text
source
downloaded_at
valid_from
valid_until
```

This allows debugging and makes it clear which timetable version the game is using.

If the timetable cannot be downloaded:

* use the existing cached timetable if available
* do not prevent the game from starting
* report the problem clearly

---

# 21. Performance

The runtime timetable lookup should be cheap.

Do not scan every timetable entry every frame.

Pre-index schedules by:

```text
weekday
time
railway network
direction
```

or another suitable structure.

At runtime:

```text
current game date/time
        ↓
active timetable entries
        ↓
spawn/despawn decisions
```

The exact implementation should fit the existing architecture.

---

# 22. Debugging

Extend the existing railway debug information.

Useful debug information:

```text
Railway networks: 1
Loaded timetable entries: 137
Today's scheduled trains: 42
Active trains: 2
```

For each active train:

```text
Train 123
Type: IC
Direction: NORTHBOUND
Scheduled: 14:35
Network: 0
```

Also add a way to visualize the selected entry/exit side if the existing debug system supports it.

Do not spam the console every frame.

---

# 23. Testing

Add tests for at least:

### No railway

```text
railway networks = 0
active trains = 0
```

### Railway but no matching timetable

No trains should spawn.

### Matching timetable

A scheduled train should spawn at the appropriate simulation time.

### Weekday filtering

A Monday-only service should not appear on Sunday.

### Direction

A northbound service must enter from the geographically correct side.

A southbound service must enter from the opposite side.

### East/west services

Verify that the system does not assume every railway is north/south.

### Train leaves the map

The train should disappear rather than reverse.

### Multiple scheduled trains

Several trains can coexist without the number growing indefinitely.

### Midnight

Services around midnight must use the correct operating date.

### Finnish daylight saving time

Verify that timetable local time remains correct during EET/EEST transitions.

### Offline mode

A previously downloaded timetable must still work when the network is unavailable.

---

# 24. Preserve Phase 1 Behavior Where Possible

The existing Phase 1 railway implementation already provides:

* OSM railway discovery
* railway network construction
* railway geometry
* train movement
* train rendering
* camera integration

Reuse all of this.

The main architectural change should be:

```text
BEFORE:

timer
  ↓
spawn train
  ↓
reverse at network end


AFTER:

weekly timetable
       ↓
scheduled train event
       ↓
determine local railway network
       ↓
determine travel direction
       ↓
spawn train at correct side
       ↓
follow railway
       ↓
leave map
```

Do not rewrite working train movement unnecessarily.

---

# 25. Future Architecture

Prepare the system for future phases:

```text
Phase 1
OSM railway
    ↓
visual trains


Phase 2
GTFS timetable
    ↓
scheduled trains


Phase 3
stations
    ↓
train arrival/departure events


Phase 4
passengers
    ↓
passenger generation


Phase 5
taxi rank
    ↓
taxi demand


Phase 6
real-time data
    ↓
delays / cancellations
```

Do not implement phases 3–6 yet.

---

# Implementation Order

1. Inspect the existing Phase 1 railway implementation.
2. Download and inspect the current Digitraffic `gtfs-passenger.zip`.
3. Determine the exact GTFS fields required.
4. Implement the timetable importer.
5. Implement the compact local weekly timetable format.
6. Implement Finnish local-time handling.
7. Implement timetable/network matching.
8. Implement geographic train direction detection.
9. Modify train spawning to use timetable events.
10. Modify network-end behavior so scheduled trains leave the map instead of automatically reversing.
11. Keep the existing railway geometry-following movement.
12. Add debug information.
13. Add tests.
14. Run the existing test suite.
15. Test with an actual Oulu map containing railway tracks.
16. Verify that trains approach from the correct geographic directions and that their frequency corresponds to the real timetable.

---

# Acceptance Criteria

The feature is complete when:

1. The game can import the current Finnish passenger train timetable.
2. The timetable is stored locally and can be used offline.
3. The game knows which trains operate on each weekday.
4. A train only appears on a map if its scheduled route is relevant to that railway network.
5. Scheduled trains enter the map from the correct geographical direction.
6. Northbound/southbound/eastbound/westbound traffic is handled correctly.
7. The existing smooth railway movement remains intact.
8. Trains travel through the map without stopping at stations.
9. Trains leave the map instead of automatically reversing.
10. No train collision system is introduced.
11. No passenger or taxi logic is introduced.
12. Existing NPC vehicle traffic continues to work.
13. The implementation does not introduce significant per-frame performance overhead.

The most important principle is:

> **Use real timetable data to decide when and from which direction trains appear, while keeping the existing OSM-based railway movement system responsible for actually moving the trains.**

Do not over-engineer this phase. The next major feature will be station interaction, so keep the timetable/network integration clean and extensible.
