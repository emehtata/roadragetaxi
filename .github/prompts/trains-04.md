## Railway Phase 4 – Passenger Simulation

### Goal

Extend the existing railway system with a lightweight passenger simulation.

The railway infrastructure, timetable integration, station mapping, platform/track selection, train movement, and station dwell behavior are already implemented.

The next step is to make trains carry passengers who:

* board scheduled trains at stations
* travel with the train
* leave the train at their destination station
* wait at stations for their scheduled train

This phase should establish the foundation for later integration with taxi demand.

### IMPORTANT SCOPE LIMIT

Implement only the first passenger-simulation phase.

Do NOT implement yet:

* taxi demand
* passengers calling taxis
* taxi queues
* passenger pathfinding to/from stations
* detailed passenger behavior
* ticketing
* fares
* train reservations
* seat capacity
* passenger animations inside trains
* passenger NPCs walking inside trains
* realistic passenger counts based on actual ticket data
* real-time passenger data
* advanced passenger AI

The goal is a lightweight simulation of passenger flow between stations and trains.

---

# 1. Inspect the existing implementation first

Before modifying code, inspect:

* train entities
* train timetable integration
* station mapping
* station arrival/departure handling
* platform/track selection
* existing pedestrian NPC system
* existing Resident NPC system
* NPC spawning/despawning
* game-time handling
* any existing passenger-related concepts

Reuse existing systems where practical.

Do not invent parallel NPC systems if the existing pedestrian/resident architecture can support passengers.

Do not rewrite the working train movement implementation.

---

# 2. Passenger journey model

Introduce a lightweight passenger journey/state model.

Conceptually:

```text
PassengerJourney
    origin_station
    destination_station
    departure_train
    arrival_train
    state
```

Possible states:

```text
WAITING_AT_STATION
ON_TRAIN
ARRIVED
```

Use the repository's existing naming conventions and architecture rather than blindly copying these names.

The important thing is that a passenger has:

* an origin station
* a destination station
* a train they intend to board
* a destination where they leave the train
* a current state

---

# 3. Generate passengers for scheduled trains

When a scheduled train is created, generate a lightweight passenger manifest.

Do not attempt to reproduce real passenger counts.

Use configurable or deterministic simulated passenger counts.

For example, conceptually:

```text
Train A
    passenger count: 30

Passenger 1
    destination: Station B

Passenger 2
    destination: Station C

Passenger 3
    destination: Station D
```

The exact passenger-generation algorithm should fit the existing game architecture.

Prefer deterministic behavior during debugging if the game already supports seeded/randomized simulation.

---

# 4. Use the train's actual scheduled route

Passengers must only receive destinations that occur **later on the train's actual scheduled route**.

For example:

```text
Train route:

Station A
    ↓
Station B
    ↓
Station C
    ↓
Station D
```

A passenger boarding at Station A may have:

```text
B
C
D
```

as a destination.

They must NOT receive:

```text
Station A
```

or a station that the train will never visit.

Likewise, a passenger boarding at Station C can only select:

```text
Station D
```

in this example.

Use the existing timetable station-call sequence rather than independently calculating destinations.

---

# 5. Passenger manifest

Each train should maintain a lightweight passenger manifest.

Conceptually:

```text
Train
 ├── timetable information
 ├── route
 ├── current station
 └── passenger manifest
```

The manifest should allow the game to efficiently determine:

> Which passengers must leave this train at the current station?

Do not attach expensive NPC behavior to every passenger while they are inside the train.

Passengers inside trains should primarily exist as lightweight simulation data.

---

# 6. Passengers boarding a train

When a scheduled train arrives at a station:

1. Identify passengers waiting at that station.
2. Find passengers whose scheduled departure train is this train.
3. Board those passengers.
4. Remove them from the station's waiting population.
5. Add them to the train's passenger manifest.
6. Change their state to `ON_TRAIN`.

Only passengers whose origin station is the current station should board this train.

Do not allow passengers to magically board a train at an unrelated station.

---

# 7. Passengers leaving a train

When a train arrives at a scheduled station:

1. Identify passengers whose destination is this station.
2. Remove them from the train manifest.
3. Change their state to `ARRIVED`.
4. Create/update their station-side NPC representation.

For example:

```text
Train arrives at Oulu

Passengers:
    Helsinki → Oulu       EXIT TRAIN
    Tampere → Oulu        EXIT TRAIN
    Helsinki → Rovaniemi  STAY ON TRAIN
```

Only passengers whose destination matches the current station should leave.

---

# 8. Station waiting population

Stations should maintain a lightweight collection of passengers waiting for trains.

Conceptually:

```text
Station
 └── waiting passengers
```

These passengers should contain enough information to determine:

* their origin station
* their destination station
* which scheduled train they intend to board
* how long they have been waiting
* their current state

Do not create a full pedestrian NPC for every waiting passenger yet.

The simulation should remain lightweight.

---

# 9. Passengers should be associated with the actual train

Passenger boarding must use the actual scheduled train identity.

For example:

```text
Passenger
    origin = Station A
    destination = Station C
    departure_train = Train 123
```

When Train 123 arrives at Station A:

```text
Passenger → board
```

A different train should not automatically pick up the passenger unless that behavior is explicitly implemented later.

This provides a clean foundation for future missed-train and transfer logic.

---

# 10. Station arrival event

Use the existing train station-arrival event/state if one already exists.

Do NOT poll every passenger every frame.

The passenger system should react to events such as:

```text
TRAIN_ARRIVED_AT_STATION
TRAIN_DEPARTING_STATION
```

The exact implementation should follow the existing event/state architecture.

At station arrival:

```text
1. passengers leave train
2. waiting passengers board
3. train dwell continues
4. train departs
```

Make sure passengers leaving the train are processed before boarding passengers where this simplifies the state transitions.

---

# 11. Passenger counts

Passenger counts should be configurable.

Do not hard-code one fixed number for every train.

At minimum allow variation based on factors such as:

* train type
* train route length
* station importance
* time of day

However, do not build a complex passenger-demand model yet.

A simple configurable probabilistic or deterministic model is sufficient.

The implementation should make it easy to replace the generation logic later.

---

# 12. Passenger distribution between destinations

Passenger destinations should be distributed among later stations on the train's actual route.

For example:

```text
A → B → C → D → E
```

Passengers boarding at A could be distributed approximately across:

```text
B
C
D
E
```

Passengers boarding at C could only use:

```text
D
E
```

The distribution does not need to represent real ticket statistics.

The key requirement is that the destination is valid and later on the train's route.

---

# 13. Connecting to the existing pedestrian system

When a passenger leaves a train, prepare the system so that the passenger can later become a normal pedestrian/resident NPC.

For now, the passenger may simply remain represented as a lightweight station-side passenger.

If the existing pedestrian system can cleanly represent the passenger immediately, reuse it.

Do not force a large refactor of the pedestrian system just to accomplish this phase.

The architecture should allow:

```text
Passenger
    ↓
ARRIVED
    ↓
Pedestrian / Resident NPC
```

in a future implementation.

---

# 14. No taxi behavior yet

Do not generate taxi requests in this phase.

A passenger leaving a train should NOT automatically:

* search for a taxi
* request a taxi
* walk to a taxi rank
* create a taxi passenger
* interact with the player's taxi

Simply record that the passenger has arrived at the station.

The next phase can build:

```text
Passenger ARRIVED
        ↓
destination / travel decision
        ↓
taxi demand
```

---

# 15. Passenger simulation and accelerated game time

Use the existing game clock.

Do not introduce a second global clock.

Passenger state transitions should be based on game/timetable time and train events, not real wall-clock time.

The existing accelerated game time must not cause passengers to be processed incorrectly.

In particular:

* boarding happens when the train reaches the station
* alighting happens when the train reaches the destination station
* waiting passengers remain associated with their scheduled train
* train dwell behavior remains controlled by the existing railway timetable implementation

Do not alter the existing timetable/dwell timing system in this phase.

---

# 16. Train capacity

Do NOT implement realistic train capacity yet.

However, structure the manifest so that a capacity limit can be added later without redesigning the passenger system.

For now, generated passengers should be allowed to board unless an existing train capacity mechanism already exists.

---

# 17. Transfers

Do not implement multi-train transfers yet.

A passenger should have one:

```text
origin
→ departure train
→ destination
```

journey.

If a future passenger wants to travel:

```text
A → B → C
```

using two different trains, that belongs to a later phase.

---

# 18. Debugging

Add useful railway passenger debug information.

At minimum make it possible to inspect:

* number of passengers on each train
* number of waiting passengers at each station
* passenger origin
* passenger destination
* assigned train
* passenger state
* passengers boarding
* passengers leaving

If the existing debug overlay can display train information, extend it rather than creating a separate UI.

Example:

```text
Train 123
Oulu → Helsinki
Passengers: 42
Next station: Tampere

Station Oulu
Waiting: 17
Boarding: 12
Leaving train: 0
```

Exact presentation should follow the existing debug system.

---

# 19. Tests

Add focused tests for:

### Passenger generation

* train generates passengers
* passenger has valid origin
* passenger has valid destination
* destination occurs later on train route
* no invalid destination is generated

### Boarding

* passenger waiting at origin station boards correct train
* passenger is removed from station waiting list
* passenger is added to train manifest
* passenger state becomes `ON_TRAIN`

### Alighting

* passenger leaves train at destination
* passenger is removed from train manifest
* passenger state becomes `ARRIVED`
* passengers whose destination is a later station remain on the train

### Multiple stations

For:

```text
A → B → C → D
```

verify that:

* A passengers can leave at B/C/D
* B passengers can leave at C/D
* C passengers can leave at D
* passengers never leave before their destination

### Multiple trains

Verify that a passenger assigned to Train A does not board Train B.

### Station event ordering

Verify that train arrival processes:

1. passengers leaving
2. passengers boarding
3. station dwell
4. departure

without corrupting the manifest.

### Regression

Verify that existing:

* train timetable
* station mapping
* platform/track selection
* station dwell
* train movement
* train direction
* startup spawning

continue to work.

---

# 20. Performance requirements

Passenger simulation must be lightweight.

Do NOT:

* update every passenger with expensive AI every frame
* perform pathfinding for passengers every frame
* scan every train against every passenger every frame
* scan every station against every passenger every frame

Use station and train ownership/indexes.

For example:

```text
station.waiting_passengers
train.passenger_manifest
```

should allow passenger transfers to happen in approximately O(number of affected passengers), not O(all passengers × all trains).

---

# 21. Future architecture

Keep the architecture extensible for the next phases.

The intended future flow is:

```text
                    ┌──→ walk away
Train arrival ──────┼──→ transfer to another train
                    └──→ request taxi

Passenger
    ↓
Station
    ↓
Train
    ↓
Station
    ↓
Travel decision
    ├── pedestrian
    ├── another train
    └── taxi
```

Do not implement these future branches now.

For this phase, only implement:

```text
Station
   ↓
waiting passenger
   ↓
scheduled train
   ↓
train passenger manifest
   ↓
destination station
   ↓
arrived passenger
```

---

# Acceptance criteria

The phase is complete when:

1. Scheduled trains can carry passengers.
2. Passengers have valid origin and destination stations.
3. Destinations are selected only from later stations on the train's actual timetable route.
4. Passengers waiting at a station can board their assigned scheduled train.
5. Passengers are removed from the station when boarding.
6. Passengers are added to the train manifest.
7. Passengers remain associated with the train while travelling.
8. Passengers whose destination is the current station leave the train.
9. Passengers whose destination is a later station remain on the train.
10. Arrived passengers are represented at the destination station.
11. No taxi behavior is implemented yet.
12. No transfer behavior is implemented yet.
13. No passenger pathfinding is required yet.
14. Existing train movement and timetable behavior remain unchanged.
15. Existing station track/platform routing remains unchanged.
16. The system has negligible impact on normal gameplay FPS.
17. Tests cover passenger generation, boarding, alighting, station sequencing, and multiple trains.

### Development approach

Work incrementally:

1. Inspect the current train/station/timetable implementation.
2. Identify the cleanest integration point for passenger events.
3. Implement the lightweight passenger journey model.
4. Implement train passenger manifests.
5. Implement station waiting passengers.
6. Implement passenger generation.
7. Implement boarding.
8. Implement alighting.
9. Add debugging information.
10. Add tests.
11. Run the existing railway and performance tests.
12. Fix regressions before proceeding.

Do not rewrite working railway systems.

Do not implement taxi demand or advanced passenger AI yet.
