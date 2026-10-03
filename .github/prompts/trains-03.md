## Railway Phase 3 – Station Routing and Track Selection

### Goal

The trains now run successfully along railway geometry and are integrated with the weekly timetable.

The next priority is **station-aware railway routing**.

Before implementing sophisticated railway signalling or collision avoidance, make sure that scheduled trains can identify the correct railway track through a station and follow the correct track so that opposing or parallel train movements do not accidentally use the same track.

For this phase:

* Focus primarily on stations and correct track selection.
* Do NOT implement a full railway signalling system yet.
* Do NOT implement passenger boarding.
* Do NOT implement train collisions.
* Do NOT redesign the existing smooth train movement system.
* At game startup, trains are allowed to spawn directly inside the visible viewpoint if necessary to keep them aligned with their timetable.

---

# 1. Inspect the existing implementation first

Before changing code, inspect the current railway implementation and identify:

* railway network construction
* railway way/node representation
* railway geometry
* railway track connectivity
* railway station discovery
* GTFS timetable/station mapping
* train route selection
* train spawning
* train movement along railway geometry
* train direction handling
* station arrival/dwell implementation

Determine how multiple parallel railway tracks are currently represented.

Do not assume that a railway network is a single line.

The implementation must distinguish between:

* separate parallel tracks
* junctions
* connected railway ways
* station approaches
* station platforms/tracks where OSM data allows this

Preserve existing working code wherever possible.

---

# 2. Make stations the primary routing anchors

A timetable train already has an ordered sequence of scheduled stations.

Use that information to determine the railway path the train should follow.

Conceptually:

```text
Train
  ↓
Scheduled station A
  ↓
Railway network
  ↓
Station B
  ↓
Railway network
  ↓
Station C
```

The train should no longer simply select an arbitrary connected railway path through the local map.

Instead, its route should be constructed around the ordered station sequence from the timetable.

---

# 3. Match GTFS stations to OSM railway stations

Reuse the station mapping implemented in the previous phase.

For each timetable station:

* identify the corresponding OSM railway station
* associate it with the relevant railway geometry
* determine which railway tracks connect to the station
* retain geographic coordinates
* retain the railway network/segment identity

Do not require exact coordinate equality.

Use the existing proximity-based matching approach where possible.

If the repository already contains a reliable station mapping mechanism, extend it instead of creating a second unrelated implementation.

---

# 4. Determine the correct track through a station

This is the most important part of this phase.

A railway station may contain multiple parallel tracks.

The train must select a track that:

1. connects to the railway network before the station
2. passes through the station area
3. connects to the railway network after the station
4. is consistent with the train's travel direction
5. does not arbitrarily switch to another parallel railway track

For example:

```text
             Station
      =====================
North ---> ===================== ---> South
      =====================
```

If the timetable route is travelling north → south, the train should remain on a compatible north → south track.

Do not select the nearest railway way at every update.

Track selection must be based on connectivity.

---

# 5. Build a station approach/exit model

Introduce a lightweight internal representation for station railway routing.

Conceptually:

```text
Station
    geographic position
    railway network
    connected tracks
    approach connections
    departure connections

StationRoute
    incoming track
    station track
    outgoing track
    travel direction
```

These are conceptual structures only.

Follow the repository's existing naming and architecture.

The important requirement is that a train can answer:

> "Given where I came from and which station I am approaching, which connected railway track should I use through this station?"

---

# 6. Preserve travel direction

The route must remain directionally consistent.

A train travelling:

```text
North → South
```

must not accidentally select a track that sends it:

```text
South → North
```

Likewise:

```text
East → West
```

must remain:

```text
East → West
```

Use actual railway geometry and geographic coordinates.

Do not derive track direction solely from OSM way ordering, because OSM way direction is not necessarily the same as railway travel direction.

The train's logical travel direction and the geometry's direction must be handled separately.

---

# 7. Handle parallel tracks

This phase must explicitly support railway stations with multiple parallel tracks.

Do not collapse all nearby railway ways into one logical centerline.

For example, if OSM contains:

```text
Track 1  =========================
Track 2  =========================
Track 3  =========================
```

the routing system must retain the distinction between them.

A train route should select one compatible track and remain on it until a legitimate connection/junction changes the route.

Do not randomly switch between parallel tracks.

---

# 8. Avoid collision-prone routing

Full collision detection is NOT part of this phase.

However, routing should already avoid obviously invalid situations such as:

* a train switching to an opposing track without a junction
* a train entering a dead-end track
* a train selecting an unrelated parallel railway
* a train reversing direction unintentionally
* two railway segments that merely pass close to each other being treated as connected

Physical proximity is not sufficient to establish railway connectivity.

Use actual topology/connectivity wherever possible.

---

# 9. Station stopping

The existing timetable-aware station stopping behavior should remain intact.

When a train reaches a scheduled station:

1. Follow the selected railway track.
2. Enter the station.
3. Stop at the appropriate station position.
4. Remain stopped for the scheduled dwell time.
5. Continue onto the selected outgoing railway track.

Do not implement platform-level passenger simulation yet.

The exact stopping position can initially be the mapped railway/station position or another existing station anchor already available in the code.

The important requirement is that the train remains on the correct railway track.

---

# 10. Startup spawning exception

Change the previous spawning requirement.

Normally trains should enter the railway network from the appropriate geographic edge.

However, **when the game starts**, this restriction does not apply.

If a scheduled train should already be somewhere inside the currently loaded railway network when the game starts, it is allowed to spawn directly at its appropriate timetable position, including inside the currently visible viewpoint.

The purpose is to prevent the simulation from creating trains that are permanently late simply because they would otherwise need to travel into the map from outside.

For example:

```text
Game starts at 12:00

Train timetable:
11:58 Station A
12:04 Station B
12:08 Station C
```

If the train should already be between A and B at 12:00, spawn it directly on the appropriate railway section.

Do not wait for it to enter from the map edge.

This startup exception applies only to initial simulation state.

Once the game is running normally, retain the existing timetable-driven spawning behavior.

---

# 11. Initial train position

If a train must be spawned inside the map at startup:

1. Determine its current timetable position.
2. Determine the previous and next scheduled stations.
3. Determine the railway route between them.
4. Find a position along that route corresponding approximately to the current timetable time.
5. Spawn the train on that railway geometry.
6. Give it the correct travel direction.
7. Continue normal train movement from there.

If exact timetable interpolation is not yet available, implement the simplest reliable approximation that keeps the train on the correct railway track.

Do not create a large new simulation system solely for startup placement.

---

# 12. Do not solve signalling yet

This phase is NOT a full railway traffic-control system.

Do not implement:

* block signalling
* signal aspects
* interlocking
* switches controlled by trains
* train reservations
* dispatching
* automatic collision avoidance
* dynamic path replanning
* platform allocation
* railway traffic management

The purpose of this phase is to establish **correct railway topology and station routing**, which will provide the foundation for those systems later.

---

# 13. Performance

Station routing and track selection should be calculated when a train's route is created or when it reaches a routing decision.

Do NOT perform expensive route searches every frame.

Do NOT search every railway way every frame.

Cache:

* station mappings
* station track connections
* station route decisions
* railway connectivity
* train route segments

Existing smooth per-frame train interpolation should remain lightweight.

---

# 14. Debugging

Extend the existing railway debug facilities.

Make it possible to see/log:

* station position
* matched GTFS station
* matched OSM station
* available railway tracks at the station
* selected incoming track
* selected station track
* selected outgoing track
* train travel direction
* current route segment
* next scheduled station

A simple debug visualization of the selected railway route would be very useful if an existing debug rendering system makes this easy.

Do not build a complex new debug UI.

---

# 15. Tests

Add focused tests for:

### Station mapping

* GTFS station maps to correct OSM station
* nearby unrelated railway stations are not selected

### Track selection

* single-track station
* two parallel tracks
* multiple parallel tracks
* correct incoming track
* correct outgoing track
* correct travel direction

### Connectivity

* connected railway ways are routable
* nearby but disconnected railway ways are not treated as connected
* dead-end track is not selected as the through route

### Station movement

* train approaches station on selected track
* train stops at station
* train remains on the selected track
* train resumes on the selected outgoing track

### Startup

* train already in the local railway network can spawn directly on the correct track
* train can spawn inside the visible viewpoint
* initial position corresponds reasonably to timetable progress
* train direction is correct after startup spawning

### Regression

Verify that existing:

* railway rendering
* smooth train movement
* timetable integration
* station dwell timing
* train direction
* performance

continue to work.

---

# 16. Future architecture

Design this phase so that future railway traffic control can build on it.

The eventual system may need:

```text
Timetable
    ↓
Train Route
    ↓
Station Route
    ↓
Railway Track
    ↓
Railway Block / Signal
    ↓
Train Reservation
```

Do not implement the lower layers yet.

For now, establish the correct relationship:

```text
Timetable station
       ↓
OSM station
       ↓
Railway track
       ↓
Train movement
```

This is the foundation for later collision-free railway traffic.

---

# Acceptance criteria

The phase is complete when:

1. Trains continue to use the existing smooth railway movement.
2. Timetable stations are mapped to the correct OSM railway stations.
3. Stations with multiple tracks preserve their individual railway tracks.
4. A train selects a connected track through the station.
5. A train does not randomly jump between parallel tracks.
6. A train maintains its logical travel direction.
7. A train stops on the correct railway track at a scheduled station.
8. The existing timetable dwell behavior continues to work.
9. The train resumes onto the correct outgoing track.
10. Disconnected railway ways are never treated as connected merely because they are geographically close.
11. At game startup, trains may spawn directly inside the loaded map/viewpoint when necessary to keep their timetable state.
12. Startup-spawned trains are placed on the correct railway route and with the correct direction.
13. No full signalling or collision system is introduced yet.
14. No passenger/taxi functionality is introduced.
15. No significant FPS regression occurs.

### Development approach

Work incrementally:

1. Inspect the current railway and timetable implementation.
2. Inspect real OSM railway topology around stations.
3. Verify how parallel tracks are currently represented.
4. Improve station-to-track mapping.
5. Implement station approach/through-route selection.
6. Integrate it with the existing train route.
7. Implement startup timetable positioning.
8. Verify station stopping and departure.
9. Add tests.
10. Run existing railway/performance tests.
11. Only optimize after measuring actual bottlenecks.

Do not rewrite the working train movement implementation.

Do not implement signalling or collision avoidance yet.
