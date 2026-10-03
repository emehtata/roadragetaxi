## NPC Railway Traffic – Phase 2: Timetable and Station Dwell Integration

### Goal

Extend the existing Phase 1 railway implementation so that trains are driven by real Finnish weekly passenger-train timetables and can stop at railway stations for the required scheduled dwell time.

The existing train movement along OSM railway geometry already works well and must be preserved.

The important new requirement is that **timetable timing must remain meaningful even though the game clock runs at accelerated speed (currently approximately 1 real second = 60 game seconds).**

Do not redesign the game's global clock.

---

## 1. Inspect the existing implementation first

Before changing code:

1. Inspect the current railway discovery/network implementation.
2. Inspect how railway geometry is represented.
3. Inspect how trains are spawned.
4. Inspect how trains follow railway geometry.
5. Inspect how game time is represented and advanced.
6. Inspect whether railway stations already exist in the OSM/map data pipeline.
7. Inspect any existing NPC timing or scheduling abstractions that can be reused.

Do not assume filenames, classes, APIs, or data structures before inspecting the repository.

Preserve the existing architecture wherever possible.

---

## 2. Use the real Digitraffic passenger timetable

Use the Finnish Transport Infrastructure Agency / Fintraffic Digitraffic GTFS passenger feed:

`https://rata.digitraffic.fi/api/v1/trains/gtfs-passenger.zip`

The implementation must inspect the actual GTFS structure before making assumptions about its contents.

Relevant GTFS files may include:

* `trips.txt`
* `stop_times.txt`
* `routes.txt`
* `calendar.txt`
* `calendar_dates.txt`
* `stops.txt`

Build a local timetable import/cache mechanism rather than downloading and parsing the complete GTFS dataset during normal gameplay.

The imported data should be compact enough for cheap runtime lookup.

---

## 3. Timetable model

Create a compact internal representation containing at least:

* train number / service identifier
* train type where available
* operating days
* origin
* destination
* ordered station calls
* scheduled arrival time
* scheduled departure time
* geographic direction
* relevant railway network/segment information

Do not hard-code Oulu or any other city.

The data model must support future expansion to:

* station stops
* passenger simulation
* taxi demand
* delays
* cancellations
* real-time train positions

But do not implement those future features now.

---

## 4. Geographic direction is mandatory

Train direction must be determined geographically.

Do NOT assume that train number or railway line orientation tells us which screen edge a train should enter from.

Examples:

* A northbound train enters from the northern/top side of the loaded railway network.
* A southbound train enters from the southern/bottom side.
* An eastbound train enters from the eastern/right side.
* A westbound train enters from the western/left side.

Take the game's actual world/screen coordinate system into account.

The direction must be derived from the ordered geographic route/stations and their coordinates.

The result must work correctly regardless of the map's orientation and regardless of which railway network is currently loaded.

---

## 5. Railway stations

Use OSM railway station data to identify stations associated with the existing railway network.

Do not require exact coordinate matches between GTFS stations and OSM stations.

Implement a geographic matching mechanism between:

* GTFS station coordinates
* OSM railway stations
* the railway geometry already used by the train system

Use a reasonable proximity-based mapping and cache the result.

The mapping must be robust enough that minor coordinate differences between GTFS and OSM do not prevent a station match.

---

## 6. Train movement and timetable interaction

Keep the existing smooth railway track-following implementation.

Do NOT replace it with a completely new train movement system.

A scheduled train should:

1. Spawn outside the relevant visible railway network.
2. Enter the map from the geographically correct direction.
3. Follow the existing railway geometry smoothly.
4. Reach mapped stations along its route.
5. Stop at stations according to the timetable.
6. Continue along the railway after the scheduled stop.
7. Eventually leave the loaded railway network.

The train does not need to simulate its complete national journey.

Only the part of its journey represented by the currently loaded railway network needs to be simulated.

---

# 7. IMPORTANT: Separate timetable time from real-time frame duration

The game clock is accelerated.

Currently approximately:

**1 real second = 60 game seconds**

Therefore a real-world timetable dwell time such as:

**2 minutes**

would otherwise become only:

**2 real seconds**

That is too short for a visible station stop.

The railway timetable system must therefore NOT simply wait using real-time seconds derived directly from the game clock.

Instead, implement a clear distinction between:

### Timetable time

The real-world clock represented by the timetable.

Example:

`12:34 arrival`

`12:36 departure`

### Simulation time

The accelerated game clock used by the rest of the game.

The train timetable system must know both concepts.

---

## 8. Scheduled station dwell must be preserved

When a train reaches a station, calculate the scheduled dwell interval:

`scheduled_departure - scheduled_arrival`

For example:

```text
Arrival:   12:34
Departure: 12:36
Dwell:      2 minutes
```

The train must remain stopped for the **full timetable dwell interval as represented by the railway simulation**, rather than allowing the global 1:60 game-speed multiplier to reduce it to approximately two real seconds.

The station stop therefore needs its own timing semantics.

The implementation should allow a timetable dwell of several minutes to remain a clearly observable station stop even while the rest of the game continues using accelerated time.

Do not solve this by changing the global game clock.

Do not slow down the entire game while a train is at a station.

Do not block the game loop.

---

## 9. Do not over-engineer departure-time synchronization yet

For this phase, do NOT attempt to build a full railway traffic simulation that guarantees real-world departure punctuality.

The immediate requirement is:

> Once a scheduled train is running, it follows its timetable through the local railway network and performs the required station dwell times, independently of the game's accelerated clock speed.

The train may continue through the local map according to the timetable even if the relationship between game time and real elapsed time is accelerated.

Do not implement:

* delay propagation
* recovery time
* missed connections
* cancellation handling
* timetable conflict resolution
* platform allocation
* railway signalling
* dispatching

Those can be future phases.

---

## 10. Recommended timing abstraction

Introduce a dedicated railway timetable/simulation timing abstraction rather than embedding timing calculations directly into train rendering or movement code.

For example, conceptually:

```text
TimetableClock
    timetable_time
    simulation_time
    time_scale

TrainSchedule
    station_calls[]

StationCall
    station_id
    arrival_time
    departure_time

TrainState
    RUNNING
    DWELLING
    DEPARTING
    LEAVING_NETWORK
```

These are conceptual examples only.

Use the repository's existing architecture and naming conventions rather than blindly copying these names.

The key requirement is that the timing responsibility is clearly separated from rendering and track movement.

---

## 11. Station arrival/departure behavior

When the train reaches a station:

1. Detect the scheduled station associated with the current railway position.
2. Transition the train into a dwelling/stopped state.
3. Stop all train movement.
4. Keep the train rendered normally.
5. Maintain the train's position on the railway.
6. Keep the train's identity and timetable state available for debugging.
7. Hold the train for the required scheduled dwell.
8. Transition back to railway movement.
9. Continue following the existing railway geometry.

The train must not jump forward when leaving the station.

Movement should resume smoothly from the stopped position.

---

## 12. Timetable schedule matching

The timetable must respect:

* weekday
* service calendar
* calendar exceptions
* Finnish local time
* EET/EEST daylight-saving changes
* times crossing midnight

Do not create a second unrelated game clock.

Use the existing game-time system as the source of the current simulated date/time where appropriate, but convert between timetable time and simulation time explicitly.

---

## 13. Train route relevance

Only create a scheduled train when its route is relevant to the currently loaded railway network.

For example, if the loaded map contains only a local section of a railway route, the game should simulate the portion of a national train journey that crosses that local railway network.

Do not attempt to load or simulate the entire Finnish railway network.

---

## 14. Spawn and exit behavior

Scheduled trains should enter the loaded railway network from the geographically correct edge.

They should not simply appear at the center of the map.

Likewise, trains should leave the local railway network naturally when their route exits the loaded area.

Do not reverse the train automatically at the end of the map as the Phase 1 prototype may currently do.

Scheduled timetable direction takes precedence over the old back-and-forth demonstration behavior.

---

## 15. Performance requirements

The railway timetable must have negligible impact on normal gameplay performance.

Do not:

* download GTFS data during gameplay
* parse the complete GTFS dataset every frame
* perform expensive geographic searches every frame
* perform pathfinding every frame
* repeatedly search all timetable entries every frame

Preprocess and index the timetable.

Runtime train scheduling should use cheap indexed lookups.

Station detection should use the existing railway geometry/network structures where possible.

---

## 16. Local timetable cache

Create a dedicated import/update tool, for example:

```text
tools/import_railway_timetable.py
```

The exact location and name must follow the repository's existing tooling conventions.

The tool should:

1. Download the current GTFS passenger timetable.
2. Validate the archive.
3. Parse the relevant GTFS files.
4. Match stations to OSM railway data.
5. Build the compact internal timetable representation.
6. Save the processed timetable locally.

Include metadata such as:

* source
* download timestamp
* timetable validity period
* processing version

The game should use the processed local timetable at runtime.

If the network is unavailable, an existing valid local timetable cache should remain usable.

---

## 17. Debugging support

Add useful railway debug information.

At minimum make it possible to inspect:

* loaded railway networks
* matched railway stations
* imported timetable entries
* current simulated timetable time
* active trains
* train number
* train direction
* current railway segment
* current station
* scheduled arrival
* scheduled departure
* remaining dwell time
* train state

Do not create a large UI system just for this.

Existing debug overlays/logging mechanisms should be reused.

---

## 18. Tests

Add focused tests for:

1. No railway data.
2. No matching timetable.
3. Matching timetable.
4. Weekday filtering.
5. Calendar exceptions.
6. Station matching.
7. Geographic direction.
8. Northbound train entering from the north/top.
9. Southbound train entering from the south/bottom.
10. Eastbound train entering from the east/right.
11. Westbound train entering from the west/left.
12. Train reaching a station.
13. Train entering dwelling state.
14. Train remaining stopped for the scheduled dwell.
15. Train leaving the station smoothly.
16. Train leaving the local railway network.
17. Multiple scheduled trains.
18. Midnight-crossing schedules.
19. Finnish DST/EET/EEST handling.
20. Offline operation using the local timetable cache.

Most importantly, include a regression test proving that increasing the global game-time speed does **not accidentally shorten the railway station dwell according to the intended railway simulation semantics**.

---

## 19. Preserve Phase 1 functionality

Do not break the existing railway implementation.

Preserve:

* railway discovery
* railway network construction
* railway geometry
* train rendering
* train movement along tracks
* smooth train interpolation
* camera integration
* existing railway performance characteristics

Change primarily:

* train spawning
* train scheduling
* route direction
* station detection
* station dwell behavior
* train exit behavior

Avoid unrelated refactoring.

---

## 20. Explicitly do NOT implement yet

Do NOT implement:

* passenger simulation
* passengers boarding trains
* taxi demand generated by trains
* taxi ranks
* train collisions
* railway signalling
* realistic delays
* real-time Digitraffic train positions
* cancellations
* platform selection
* full national railway simulation
* multiplayer railway synchronization

Those belong to later phases.

---

# Acceptance criteria

The implementation is complete when:

1. The game can import the current Finnish passenger-train weekly timetable from Digitraffic.
2. The timetable is cached locally and usable offline.
3. Trains are spawned according to the timetable.
4. Only trains relevant to the loaded railway network are simulated.
5. Train direction is determined geographically.
6. Northbound trains enter from the north/top side of the map.
7. Southbound trains enter from the south/bottom side.
8. Eastbound and westbound trains use the corresponding map edges.
9. Existing smooth railway movement remains intact.
10. A train can identify and reach a scheduled railway station.
11. The train stops at the station.
12. The train remains stopped for the required timetable dwell.
13. The accelerated global game clock does not incorrectly collapse the station dwell into an almost invisible pause.
14. The train resumes movement smoothly after the dwell.
15. The train eventually leaves the loaded railway network.
16. No station passenger, taxi, collision, signalling, delay, or real-time systems are introduced yet.
17. Normal game FPS is not materially affected.

### Development approach

Work incrementally:

1. Inspect the existing Phase 1 railway implementation.
2. Implement/import the timetable cache.
3. Implement GTFS → internal schedule conversion.
4. Implement GTFS station → OSM station matching.
5. Implement geographically correct train direction.
6. Integrate timetable-driven train spawning.
7. Integrate station detection.
8. Implement timetable-aware station dwelling.
9. Implement correct train exit behavior.
10. Add tests.
11. Run the existing railway and performance tests.
12. Only then clean up or optimize code where measurements justify it.

Do not replace working Phase 1 systems unnecessarily.
