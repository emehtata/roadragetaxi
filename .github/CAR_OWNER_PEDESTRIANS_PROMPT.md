# NPC Vehicle ↔ Pedestrian Integration Using Existing OSM Parking Spaces

Extend the existing NPC traffic and pedestrian systems so that NPC vehicles and pedestrians can interact naturally through the **existing OSM parking-space data**.

IMPORTANT:

The game already imports OSM parking-space data and already renders the individual parking spaces in the game.

**Do NOT create a new parking-area or parking-slot system.**
**Do NOT duplicate or replace the existing OSM parking-space representation.**

First inspect the repository and identify:

* the existing OSM parking-space data structure
* how parking spaces are stored
* how parking spaces are rendered
* how their position and orientation are represented
* whether parking spaces already have IDs
* how nearby world entities are queried
* the existing TrafficManager
* the existing CarAI
* the existing PedestrianManager
* the existing PedestrianNetwork
* the existing SpatialHash/spatial indexing

Build this feature on top of those existing systems.

## 1. Existing OSM parking spaces become usable game objects

Treat the existing OSM parking spaces as the authoritative source for parking locations.

Each existing parking space should be able to expose enough information for NPC vehicle placement, such as:

```text
parking_space_id
position
orientation
occupied
reserved
vehicle_id
```

Only add fields that are actually missing from the existing implementation.

Do not introduce a second parking-space representation.

The existing rendered parking space should remain the same.

## 2. NPC cars can occupy existing parking spaces

NPC vehicles should be able to use the existing OSM parking spaces.

A vehicle can transition:

```text
DRIVING
    ↓
SEARCHING_FOR_PARKING
    ↓
PARKING
    ↓
PARKED
```

When a vehicle becomes parked:

* select an available existing OSM parking space
* reserve it before beginning the parking maneuver
* drive into the parking space
* align the vehicle with the parking-space orientation
* mark the parking space occupied
* associate the vehicle with that parking space
* switch the vehicle to a low-cost `PARKED` state

The vehicle should visually sit inside the existing rendered parking space.

Do not generate a separate parking marker or replacement parking geometry.

## 3. Populate the city with parked NPC cars

Allow the TrafficManager or an appropriate existing system to populate existing OSM parking spaces with NPC cars.

Parking density should be configurable.

For example:

```text
parking_density = 0.0 ... 1.0
```

Do not fill every parking space.

Parking occupancy should look naturally distributed.

Some areas can have:

* almost no parked vehicles
* moderate occupancy
* high occupancy

Use the existing OSM parking-space distribution rather than inventing new parking locations.

## 4. Parked vehicles are real NPC vehicles

A parked NPC car is not merely decorative.

It should:

* have a normal vehicle entity
* have collision geometry
* be visible according to normal rendering/LOD rules
* exist in the SpatialHash
* be discoverable by pedestrians
* be enterable by a pedestrian
* be able to transition back into normal CarAI driving

However, while parked it should use a very cheap simulation state.

For example:

```text
PARKED:
    no steering updates
    no pathfinding
    no traffic-light processing
    no normal driving AI
    minimal state updates
```

## 5. Pedestrians can use parked NPC vehicles

A pedestrian should be able to decide that they need a vehicle.

The pedestrian can then search for a suitable parked NPC vehicle using the existing SpatialHash.

Do not scan every vehicle in the world.

The initial search should be spatially local.

A candidate vehicle should generally be:

```text
PARKED
not reserved
not occupied
not being despawned
accessible to pedestrians
```

## 6. Pedestrian does NOT need a predefined vehicle

Do not hard-code relationships such as:

```text
pedestrian #15 → vehicle #15
```

A pedestrian should be able to enter **any suitable NPC parked vehicle**.

If a future ownership system exists, it may give preference to an associated vehicle.

For now, vehicle selection should be based primarily on:

1. vehicle availability
2. pedestrian accessibility
3. walking distance
4. reasonable location
5. vehicle state

This should be implemented as a modular selection/scoring system so that ownership can be added later.

## 7. Vehicle reservation

Once a pedestrian selects a vehicle, immediately reserve it.

For example:

```text
vehicle.state = RESERVED
vehicle.reserved_by = pedestrian.id
parking_space.reserved = true
```

This prevents another pedestrian from selecting the same vehicle.

Reservations must be released if:

* the pedestrian changes destination
* the pedestrian cannot reach the vehicle
* the vehicle disappears
* the vehicle becomes invalid
* the interaction is cancelled
* the pedestrian is removed

Never leave stale reservations.

## 8. Walking to the vehicle

The pedestrian must walk to the vehicle using the existing PedestrianNetwork.

Do not teleport the pedestrian to the car.

The route should use the same pedestrian-path system already used by normal pedestrians.

The pedestrian should approach a sensible vehicle entry position.

Use:

* vehicle position
* vehicle orientation
* nearest accessible side/door
* nearby pedestrian paths

The exact door geometry does not need to be physically perfect for the top-down game, but the interaction should look believable.

## 9. Entering the vehicle

Add an explicit pedestrian interaction state, using the existing state-machine architecture if one exists.

Conceptually:

```text
WALKING
    ↓
APPROACHING_VEHICLE
    ↓
ENTERING_VEHICLE
    ↓
IN_VEHICLE
```

During entry:

* stop pedestrian movement
* prevent the pedestrian from being selected by another system
* hide or visually move the pedestrian into the vehicle
* transfer driver control to the pedestrian
* change vehicle state from `PARKED`/`RESERVED` to `OCCUPIED`
* remove the parking-space reservation
* keep the parking space occupied until the vehicle actually leaves it

Do not create duplicate pedestrian or vehicle entities.

## 10. Vehicle leaving the parking space

Once the pedestrian has entered:

```text
vehicle.state = OCCUPIED
vehicle.current_driver_id = pedestrian.id
```

The vehicle should then:

1. leave the OSM parking space
2. perform the necessary parking-lot/parking-area maneuver
3. connect to the road network
4. activate normal CarAI
5. continue driving normally

The existing CarAI must remain responsible for driving.

Do not implement a separate driving system for vehicles that were entered by pedestrians.

## 11. Parking-space release

The existing OSM parking space should remain marked as occupied while the vehicle is physically in it.

Only release it when the vehicle has actually left the space.

Conceptually:

```text
PARKED
parking_space.occupied = true

vehicle starts leaving
        ↓
parking_space.occupied = false

vehicle joins road network
```

This prevents another NPC vehicle from attempting to use the same space while the first vehicle is still leaving.

## 12. Pedestrian exits vehicle

The reverse interaction must also work.

When an NPC vehicle reaches its destination:

```text
DRIVING
    ↓
SEARCHING_FOR_PARKING
    ↓
PARKING
    ↓
PARKED
```

The vehicle uses an existing OSM parking space.

After the vehicle is safely parked:

```text
vehicle.current_driver_id = None
pedestrian.state = EXITING_VEHICLE
```

Then:

```text
EXITING_VEHICLE
    ↓
WALKING
```

The pedestrian should appear beside the vehicle and continue using the existing pedestrian system.

The vehicle remains parked in the OSM parking space.

## 13. Parking without a pedestrian

NPC vehicles must also be able to remain parked without an active pedestrian.

This is required for simply populating the city with parked traffic.

For example:

```text
NPC vehicle spawned
        ↓
existing OSM parking space
        ↓
PARKED
```

There does not need to be a simulated pedestrian associated with every parked vehicle.

This is important for scalability.

## 14. Pedestrian leaving a parked vehicle later

A pedestrian who has exited a vehicle should not necessarily permanently lose the relationship with it.

Keep the architecture flexible enough to support:

```text
pedestrian
    ↓
vehicle
```

as an optional association.

However, the **current driver relationship** must always be explicit and separate.

For example:

```text
vehicle.current_driver_id
pedestrian.current_vehicle_id
```

Use the existing entity/reference conventions in the repository rather than introducing a completely new object model unnecessarily.

## 15. "Any car" interaction

The system must support this scenario:

```text
Pedestrian A
     ↓
sees parked Vehicle X
     ↓
Vehicle X was originally spawned for another purpose
     ↓
Vehicle X is currently unoccupied
     ↓
Pedestrian A can reserve it
     ↓
Pedestrian A walks to Vehicle X
     ↓
Pedestrian A enters Vehicle X
     ↓
Vehicle X becomes Pedestrian A's active vehicle
```

Do not assume that a parked NPC vehicle can only be used by the pedestrian that originally generated it.

The vehicle should be treated as a reusable world entity.

## 16. Player interaction

The existing player interactions must continue to work.

If the player can:

* collide with NPC vehicles
* steal vehicles
* destroy vehicles
* otherwise interact with NPC vehicles

make sure NPC reservations do not prevent valid player interactions.

If the player takes a reserved NPC vehicle:

* cancel the pedestrian reservation
* safely transition the pedestrian to another valid state
* never leave a ghost reservation behind

Use the existing player/gameplay architecture rather than creating special-case hacks.

## 17. Despawn rules

A parked NPC vehicle may normally be eligible for despawning according to the existing TrafficManager/LOD system.

However, NEVER despawn a vehicle while:

```text
reserved by pedestrian
being entered
occupied
being exited
actively driving
```

Similarly, never despawn a pedestrian while:

```text
approaching vehicle
entering vehicle
exiting vehicle
```

unless the existing game explicitly forces entity removal.

If forced removal occurs, clean up all references.

## 18. SpatialHash integration

Use the existing SpatialHash to find:

* nearby parked vehicles
* nearby pedestrians
* vehicle entry positions
* potential interaction candidates

Do not introduce another spatial indexing system.

Example:

```text
Pedestrian
    ↓
SpatialHash query
    ↓
nearby vehicles
    ↓
filter PARKED vehicles
    ↓
score candidates
    ↓
reserve selected vehicle
```

## 19. LOD integration

Integrate this with the existing NPC LOD system.

Nearby:

* full pedestrian simulation
* visible enter/exit interaction
* normal vehicle behavior

Medium distance:

* simplified interaction simulation

Far away:

* preserve logical state without requiring visible animation

For example, an off-screen pedestrian may logically complete:

```text
walking to vehicle
→ entering
→ driving
```

without requiring the full entry animation.

Do not unnecessarily simulate parked vehicles at full AI frequency.

## 20. OSM data is authoritative for parking locations

The existing OSM parking-space data is the source of truth for where NPC cars may park.

Do not:

* create duplicate parking spaces
* infer arbitrary parking spaces from parking polygons if individual spaces already exist
* render replacement parking spaces
* maintain a second independent parking database

Only extend the existing parking-space representation with the minimum runtime state required by NPC simulation.

## 21. Debug visualization

Extend the existing debug tools if available.

Useful debug information:

```text
OSM parking space ID
occupied/free
reserved/free
vehicle ID
vehicle state
pedestrian ID
current driver ID
```

Also visualize:

* pedestrian → selected vehicle
* pedestrian walking route to vehicle
* vehicle entry point
* vehicle parking-space association

Example:

```text
Pedestrian #142
      ↓
Vehicle #57
      ↓
OSM Parking Space #8932
```

## 22. Failure handling

Handle cases where:

* the selected vehicle disappears
* another system moves the vehicle
* player takes the vehicle
* the vehicle becomes occupied
* the pedestrian cannot reach it
* the vehicle cannot leave the parking location
* the parking space is removed/reloaded
* the pedestrian is removed
* the vehicle is destroyed

Always clean up:

```text
vehicle reservation
parking-space reservation
pedestrian vehicle reference
vehicle driver reference
```

No stale references or permanent reservations may remain.

## 23. Implementation approach

Before coding:

1. Inspect the existing parking-space implementation.
2. Identify exactly how OSM parking spaces are represented.
3. Identify how they are rendered.
4. Identify how their position/orientation are stored.
5. Identify the existing vehicle architecture.
6. Identify the existing pedestrian architecture.
7. Identify SpatialHash usage.
8. Identify CarAI and TrafficManager.
9. Identify the existing LOD system.
10. Integrate into those systems.

Then implement incrementally:

### Phase 1

Make existing OSM parking spaces track runtime occupancy.

### Phase 2

Allow NPC vehicles to occupy existing parking spaces.

### Phase 3

Add efficient `PARKED` vehicle state.

### Phase 4

Allow pedestrians to discover nearby parked NPC vehicles.

### Phase 5

Add vehicle reservation.

### Phase 6

Implement pedestrian → vehicle walking and entry.

### Phase 7

Activate CarAI and leave the parking space.

### Phase 8

Implement vehicle → pedestrian exit.

### Phase 9

Add LOD and performance optimization.

### Phase 10

Add debugging and robust failure handling.

## Acceptance criteria

The following scenario must work:

```text
Existing OSM parking space
        ↓
NPC vehicle parks there
        ↓
Parking space becomes occupied
        ↓
Pedestrian decides to use a car
        ↓
Pedestrian finds the parked NPC vehicle
        ↓
Vehicle is reserved
        ↓
Pedestrian walks to the vehicle
        ↓
Pedestrian enters it
        ↓
Vehicle leaves the existing OSM parking space
        ↓
Parking space becomes available
        ↓
Vehicle joins the normal road network
        ↓
Existing CarAI takes over
        ↓
Vehicle drives normally
        ↓
Vehicle finds another existing OSM parking space
        ↓
Vehicle parks
        ↓
Pedestrian exits
        ↓
Vehicle remains parked
        ↓
Pedestrian continues as a normal pedestrian
```

Also verify:

* existing OSM parking spaces remain unchanged visually
* no duplicate parking-space system is created
* multiple pedestrians cannot reserve the same vehicle
* parked vehicles have very low simulation cost
* parked NPC vehicles can be used by arbitrary pedestrians
* vehicles can leave parking and seamlessly transition to normal CarAI
* vehicles can return to parking
* pedestrians can exit vehicles
* player interactions continue to work
* SpatialHash is used for nearby vehicle discovery
* LOD remains functional
* no stale reservations or entity references remain

The key architectural principle is:

**The existing OSM parking spaces are the authoritative parking infrastructure. NPC vehicles occupy those spaces, and pedestrians interact with vehicles as reusable world entities. Do not create a parallel parking system.**
