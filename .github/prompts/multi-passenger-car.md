Implement a complete **multi-passenger NPC vehicle passenger system** for the game.

The current game should support NPC vehicles carrying multiple people.

For now, every NPC vehicle has a capacity of **5 passengers/occupants**, but the architecture MUST be designed so that different vehicle types can later have different capacities.

The long-term behavior should be:

```text
Resident group
    ↓
enters NPC vehicle
    ↓
vehicle drives to destination
    ↓
vehicle parks
    ↓
passengers leave vehicle
    ↓
passengers become pedestrian entities
    ↓
pedestrians walk to nearby destination building
    ↓
pedestrians enter building
    ↓
pedestrians spend time "inside"
    ↓
pedestrians leave building
    ↓
pedestrians return to their vehicle
    ↓
all required passengers board
    ↓
vehicle continues to next destination
```

This must be implemented as a proper simulation state machine, not as a visual teleportation effect.

---

# 1. Inspect the existing NPC architecture first

Before making changes, inspect the existing implementations of:

* Resident
* NPC vehicle
* Pedestrian
* Vehicle spawning
* Vehicle routing
* Vehicle parking
* Building detection
* Building entrances
* Pedestrian spawning/despawning
* Destination selection
* Resident lifecycle
* NPC despawning
* Existing traffic state machines

Determine whether the existing Resident object already represents a person independently of the vehicle.

Reuse existing entities and lifecycle mechanisms wherever possible.

Do not create a second incompatible "passenger" system if the existing Resident/Pedestrian architecture can be extended.

---

# 2. Introduce a vehicle passenger group

An NPC vehicle must be capable of containing multiple passengers.

Conceptually:

```python id="b2g4k9"
class Vehicle:
    capacity: int
    passengers: list[Resident]
```

Adapt this to the existing architecture.

Do not hard-code:

```python id="q4sp0a"
capacity = 5
```

throughout the code.

Instead, define capacity as a property of the vehicle type.

For the current vehicle types:

```text id="0wzq2c"
capacity = 5
```

Future vehicle types should be able to define:

```text id="q3q8la"
capacity = 2
capacity = 4
capacity = 5
capacity = 7
capacity = 9
...
```

without modifying passenger-management logic.

---

# 3. Passenger group versus individual passenger

The important architectural concept is that passengers travelling together form a **trip group**.

For example:

```text id="2r5t0e"
TripGroup #123
    ├── Resident A
    ├── Resident B
    ├── Resident C
    └── Resident D

Vehicle #57
```

The group should share:

* Current destination
* Vehicle
* Parking event
* Building visit
* Return-to-vehicle event
* Next destination

However, each passenger remains an individual Resident/Pedestrian entity.

Do not merge passengers into a single entity.

---

# 4. Passenger count

A vehicle's occupancy should be explicitly tracked.

For example:

```python id="1i2o3r"
vehicle.capacity
vehicle.passengers
vehicle.available_seats
```

with:

```python id="n6m5tb"
available_seats = capacity - len(passengers)
```

Do not assume every vehicle is full.

Examples:

```text id="5yqg2p"
5-seat car
1 passenger
5 seats available → 4

5-seat car
3 passengers
5 seats available → 2

5-seat car
5 passengers
5 seats available → 0
```

---

# 5. Passenger generation

When an NPC vehicle trip is created, determine how many Residents are travelling together.

The number must never exceed vehicle capacity.

For example:

```text id="j8h0qe"
vehicle capacity = 5
group size = 3
```

The three Residents become passengers of the same vehicle.

Do not automatically fill every vehicle to capacity.

Passenger count should eventually be compatible with Resident/family simulation.

If the current Resident system already has family/group relationships, use them.

If that information is not currently available, implement a clean temporary passenger-group mechanism that can later be connected to family simulation.

---

# 6. Passenger states

Implement an explicit state machine.

For example:

```text id="h7o4p1"
PASSENGER_WAITING
    ↓
BOARDING
    ↓
IN_VEHICLE
    ↓
TRAVELLING
    ↓
VEHICLE_PARKED
    ↓
EXITING_VEHICLE
    ↓
WALKING_TO_DESTINATION
    ↓
ENTERING_BUILDING
    ↓
INSIDE_BUILDING
    ↓
LEAVING_BUILDING
    ↓
WALKING_TO_VEHICLE
    ↓
WAITING_FOR_VEHICLE
    ↓
BOARDING
    ↓
IN_VEHICLE
```

Adapt these states to the existing pedestrian/Resident architecture.

The state machine must prevent impossible situations such as:

* passenger walking away while still marked as inside vehicle
* vehicle leaving while passengers are still boarding
* passenger returning to a different vehicle
* passenger being spawned twice
* passenger disappearing permanently
* vehicle driving away while passengers are inside a building

---

# 7. Boarding the vehicle

Passengers should visibly board the vehicle.

Do not simply make them disappear when the vehicle starts.

The exact visual implementation can remain simple:

```text id="4gq1w6"
pedestrian approaches car
    ↓
boarding
    ↓
pedestrian removed/hidden from pedestrian world
    ↓
Resident becomes passenger
```

The important thing is that the simulation state remains explicit.

The vehicle should not start moving until all required passengers have boarded or the trip logic has explicitly decided that a passenger is no longer participating.

---

# 8. Parking triggers passenger exit

When the vehicle reaches its destination and successfully parks:

```text id="g0w6v5"
vehicle parked
    ↓
passengers disembark
```

All passengers belonging to that trip group should exit.

Do not randomly select only one passenger.

The group should remain logically together.

---

# 9. Convert passengers into pedestrians

When passengers leave the parked vehicle:

```text id="v4qj8s"
Vehicle passenger
        ↓
Resident
        ↓
Pedestrian world entity
```

The pedestrian should spawn at a sensible position next to the parked vehicle.

Do not spawn pedestrians:

* inside the vehicle sprite
* inside buildings
* inside roads
* inside other vehicles
* on curbs
* on invalid geometry

Use the existing pedestrian spawning/placement validation.

---

# 10. Group pedestrian movement

Passengers from the same vehicle should be able to walk as a group.

For example:

```text id="3p0w9n"
        BUILDING
     ┌───────────┐
     │           │
     └─────┬─────┘
           ↑
       A   B   C
        \  |  /
          🚗
```

They should generally:

* leave the vehicle
* walk toward the same destination
* remain reasonably close to one another
* enter the same destination building

Perfect formation is not required.

Avoid making pedestrians move in a rigid formation.

---

# 11. Selecting the destination building

The trip destination should resolve to an actual building or valid destination area.

Use existing OSM building data and building entrances where possible.

The destination should not simply be an arbitrary coordinate inside a building polygon.

Prefer:

```text id="7s1xk3"
building
    +
valid entrance
    ↓
pedestrian destination
```

The entrance should be reachable by the pedestrian routing system.

Do not make pedestrians walk through walls.

---

# 12. Building entry

When pedestrians reach the building:

```text id="q5k3w1"
pedestrian
    ↓
building entrance
    ↓
ENTERING_BUILDING
    ↓
INSIDE_BUILDING
```

Once inside, the pedestrian may be removed from normal world rendering.

However, the Resident must remain alive in the simulation.

Do not destroy the Resident.

The Resident is merely changing representation/state.

---

# 13. "Inside building" simulation

While inside the building, the passenger should spend a configurable amount of simulated time there.

Examples:

```text id="k3j9q7"
shopping
work
visit
service
errand
other activity
```

The initial implementation does not need detailed interior simulation.

It is sufficient to model:

```text id="m6b2r0"
INSIDE_BUILDING
    +
activity duration
```

The duration should be configurable and preferably randomized within a sensible range.

For example:

```python id="v2z6pk"
activity_duration = random_between(min_time, max_time)
```

Use the game's simulation clock rather than real-world wall-clock time.

---

# 14. Different passengers may eventually have different activities

Design the system so that future passengers can have individual activities.

For now, passengers in one trip group may share the same destination and activity.

However, do not architect the system so that this becomes impossible later.

A useful conceptual model is:

```text id="m0r1cx"
TripGroup
    ↓
Activity
    ├── destination
    ├── activity type
    └── duration
```

Later this can be extended to individual passenger activities.

---

# 15. Returning from the building

When the activity duration ends:

```text id="9k2p3s"
INSIDE_BUILDING
    ↓
LEAVING_BUILDING
    ↓
WALKING_TO_VEHICLE
```

The pedestrian should exit through the same or another valid building entrance.

Then walk back toward the vehicle.

Do not teleport the pedestrian directly to the vehicle.

---

# 16. Remember the exact vehicle

This is critical.

When a passenger leaves the vehicle, store a reference/identifier to the vehicle they belong to.

For example:

```python id="x7p1m3"
passenger.vehicle_id
passenger.trip_group_id
```

When returning:

```text id="r4w9q2"
pedestrian
    ↓
find assigned vehicle
    ↓
walk to that vehicle
```

Do NOT simply find the nearest NPC vehicle.

Otherwise passengers can accidentally board another vehicle.

---

# 17. Vehicle remains parked

While passengers are inside the building, their vehicle must remain parked.

The vehicle should not:

* despawn
* select another destination
* resume driving
* be reassigned to another Resident
* be selected as another parking target

The vehicle is effectively reserved by its trip group.

Conceptually:

```text id="p8x4v0"
PARKED_WAITING_FOR_PASSENGERS
```

---

# 18. Parking occupancy integration

Integrate this with the parking system.

The vehicle must retain:

* parking-space reservation
* parking-space occupancy
* trip-group ownership

while its passengers are inside.

The parking location must not become available to another NPC.

---

# 19. Returning passengers board

When passengers return:

```text id="c1y5q8"
pedestrian
    ↓
vehicle
    ↓
boarding
```

The vehicle should wait until the required passengers have boarded.

If there are five passengers:

```text id="6x0q4v"
Passenger 1 → boarded
Passenger 2 → boarded
Passenger 3 → boarded
Passenger 4 → boarded
Passenger 5 → boarded
                    ↓
               continue trip
```

Do not make the vehicle leave after the first passenger returns.

---

# 20. Handling delayed passengers

Allow passengers to return at slightly different times.

The vehicle should wait for the expected group.

However, prevent an infinite wait.

Implement a configurable timeout.

If a passenger fails to return:

1. Determine why.
2. Keep the vehicle waiting for a reasonable period.
3. Apply existing NPC fallback/despawn logic if necessary.
4. Never leave the simulation in a permanently blocked state.

Do not silently lose the passenger.

---

# 21. Continue to next destination

Once the required passengers have boarded:

```text id="v5k2m7"
all passengers onboard
        ↓
release parking reservation
        ↓
select next destination
        ↓
find parking
        ↓
drive
```

This creates the intended lifecycle:

```text id="1kq8m4"
Destination A
    ↓
park
    ↓
passengers visit building
    ↓
return
    ↓
Destination B
    ↓
park
    ↓
passengers visit building
    ↓
return
    ↓
Destination C
```

The same vehicle and Residents remain associated throughout the journey.

---

# 22. Vehicle occupancy and rendering

The vehicle itself does not need to visually display five people.

Do not add unnecessary passenger sprites inside vehicles at this stage.

However, the simulation must know:

```text id="8m2r5v"
who is inside
how many passengers
vehicle capacity
trip group
current activity
```

This information will be useful for future features.

---

# 23. Interaction with existing pedestrians

Do not create a second pedestrian implementation specifically for passengers.

When passengers leave vehicles, use the existing pedestrian entity and navigation system.

The pedestrian should behave like a normal pedestrian for:

* movement
* sidewalk usage
* crossing roads
* building entrances
* despawning/rendering
* collision avoidance

The only special state should be its association with the trip group and vehicle.

---

# 24. Interaction with existing Resident simulation

Preserve the distinction between:

```text id="a5g7v1"
Resident
    =
persistent simulated person
```

and:

```text id="s4k9p2"
Pedestrian
    =
current world representation of that Resident
```

and:

```text id="d7h3q8"
Vehicle passenger
    =
Resident currently travelling inside a vehicle
```

A Resident should therefore be able to transition between representations:

```text id="b8n4x0"
IN_VEHICLE
    ↕
PEDESTRIAN
    ↕
INSIDE_BUILDING
```

without being destroyed/recreated as a completely unrelated person.

---

# 25. Save/restore considerations

If the game already has save/load functionality, make the passenger state serializable.

At minimum preserve:

* Resident ID
* Trip group ID
* Vehicle ID
* Vehicle capacity
* Passenger list
* Current activity
* Destination building
* Parking location
* Passenger state
* Remaining activity time

If save/load does not yet exist, keep the architecture compatible with future serialization.

---

# 26. Debug visualization

Extend the existing NPC debug tools.

For a selected NPC vehicle, show:

```text id="g3r8k1"
VEHICLE: CAR_42
CAPACITY: 5
OCCUPANTS: 4
TRIP GROUP: 183
STATE: PARKED_WAITING_FOR_PASSENGERS
DESTINATION: BUILDING_918
PARKING: SPACE_1234
```

For a passenger:

```text id="n5v2x7"
RESIDENT: 817
GROUP: 183
VEHICLE: CAR_42
STATE: WALKING_TO_VEHICLE
ACTIVITY: SHOPPING
DESTINATION: BUILDING_918
```

Debug visualization should make it possible to follow the complete lifecycle.

---

# 27. Failure handling

The system must gracefully handle:

### Vehicle cannot find parking

```text
drive
 ↓
no parking
 ↓
select another parking location
```

### Passenger cannot reach building

Do not leave the passenger permanently stuck.

### Passenger cannot return to vehicle

Do not let the vehicle wait forever.

### Vehicle disappears unexpectedly

Passengers must receive a valid fallback state.

### Building becomes inaccessible

Select an alternative destination or use existing NPC fallback behavior.

### Vehicle is destroyed/crashes

Passengers must not remain permanently associated with a non-existent vehicle.

Adapt these cases to the game's existing failure handling.

---

# 28. Performance

This system may eventually involve many Residents.

Do not perform expensive global searches every frame.

Use:

* entity IDs
* direct references where safe
* spatial indexing
* existing pedestrian navigation
* existing building lookup
* existing parking lookup

A passenger walking to its assigned building or vehicle should not scan every building/vehicle in the world each frame.

---

# 29. Deterministic and testable state transitions

Make passenger state transitions explicit and testable.

At minimum test:

### Test 1 — One passenger

```text
spawn → board → drive → park → exit → building → wait → return → board → drive
```

### Test 2 — Five passengers

All five passengers successfully complete the complete lifecycle.

### Test 3 — Partially occupied vehicle

For example:

```text
capacity = 5
occupants = 2
```

The vehicle must work correctly.

### Test 4 — Vehicle capacity

Attempt to assign six passengers to a five-seat vehicle.

Expected:

```text
6th passenger rejected/reassigned
```

Never allow:

```text
occupants > capacity
```

### Test 5 — Parking

Passengers only leave after the vehicle has reached a valid parking location.

### Test 6 — Building entrance

Pedestrians reach an actual valid building entrance rather than walking through the building polygon.

### Test 7 — Return

Passengers return to their exact assigned vehicle.

### Test 8 — Multiple nearby vehicles

Passengers must never accidentally board another vehicle.

### Test 9 — Delayed passenger

Vehicle waits for the group without becoming permanently stuck.

### Test 10 — Multiple trip groups

Several parked NPC vehicles have passengers visiting different buildings simultaneously.

Groups must remain independent.

### Test 11 — Different vehicle capacities

Create test vehicles with:

```text
2 seats
5 seats
7 seats
```

The passenger system must work without changing the underlying passenger logic.

---

# 30. Important architectural rule

Do NOT hard-code the current five-seat assumption into the passenger state machine.

The correct abstraction is:

```text id="4k1r8z"
Vehicle
    ├── capacity
    ├── passengers
    └── trip_group

TripGroup
    ├── members
    ├── vehicle
    ├── destination
    └── activity

Resident
    ├── trip_group
    ├── vehicle
    └── current_state
```

The exact class names should follow the existing codebase.

---

# 31. Implementation process

Before coding:

1. Inspect the existing Resident implementation.
2. Inspect NPC vehicle lifecycle.
3. Inspect pedestrian lifecycle.
4. Inspect parking implementation.
5. Inspect building/entrance representation.
6. Inspect destination generation.
7. Identify where passengers can be integrated without duplicating existing logic.
8. Describe the proposed state machine briefly.

Then implement the complete system.

Do not stop at creating data structures. The full lifecycle must actually work in the game.

After implementation:

* Run existing tests.
* Add regression tests for passenger lifecycle.
* Test with 1–5 passengers.
* Test partially occupied vehicles.
* Test multiple simultaneous vehicles.
* Test parking and building visits.
* Test return-to-exact-vehicle behavior.
* Test vehicle capacity abstraction.
* Verify that existing NPC traffic still works.
* Verify that existing pedestrians still work independently.
* Verify that parking reservations remain correct.
* Verify that passengers cannot become permanently stuck.

Finally provide a concise report:

```
Files changed
Passenger architecture
Trip-group architecture
Vehicle capacity handling
Boarding implementation
Parking → pedestrian transition
Building visit lifecycle
Return-to-vehicle implementation
Vehicle continuation logic
Failure handling
Tests performed
Known limitations
```

Keep the implementation compatible with the existing OSM-based world, parking system, pedestrian navigation and Resident simulation. Avoid rewriting unrelated traffic systems.
