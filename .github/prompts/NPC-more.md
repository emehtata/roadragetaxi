Continue development of the NPC vehicle system.

Implement two related improvements:

1. NPC vehicles should prefer realistic and safe parking locations.
2. NPC vehicles must never intentionally drive on road curbs, sidewalks, building edges, parking boundaries, or other non-drivable roadside geometry.

The implementation must integrate with the existing Road Rage Taxi traffic, routing, OSM and Resident systems instead of creating a separate parallel traffic system.

---

# 1. Inspect the existing implementation first

Before changing code, inspect the current implementation of:

* NPC vehicle spawning
* Resident vehicle behavior
* Destination selection
* Route generation
* Road graph
* Lane handling
* Parking-space loading/rendering
* OSM data processing
* Building footprints
* Roads and road widths
* Sidewalks
* Vehicle movement
* Vehicle collision/geometry
* NPC despawning
* Existing traffic rules

Identify how parking spaces are currently represented and whether the game already has enough OSM information to distinguish:

* Dedicated parking spaces
* Parking lots
* Driveways
* Building courtyards
* Private/internal roads
* Sidewalks
* Road carriageways
* Curbs
* Building footprints

Do not duplicate information that already exists.

---

# 2. NPC parking should be destination-driven

NPC vehicles should not simply stop at an arbitrary point near their destination.

Instead, when an NPC Resident needs to park, select an actual valid parking destination.

The preferred hierarchy should be approximately:

1. Dedicated mapped parking space
2. Parking area / parking lot
3. Safe driveway or building courtyard
4. Other explicitly identified safe vehicle-accessible area
5. As a last resort, a valid legal roadside parking location if supported by the map data

Do NOT treat:

* sidewalks
* pedestrian areas
* building footprints
* road medians
* grass
* parks
* arbitrary empty terrain
* road curbs

as valid parking locations.

The system should prefer mapped parking infrastructure whenever available.

---

# 3. Parking-space selection

Create a reusable parking selection mechanism.

Conceptually:

```python
parking_spot = parking_manager.find_best_parking(
    destination=resident.destination,
    vehicle=npc_vehicle
)
```

Adapt this to the existing architecture.

The parking selection system should consider:

* Distance from destination
* Distance from the final route
* Whether the parking location is actually reachable
* Vehicle size
* Parking-space orientation
* Road access
* Building proximity
* Whether another NPC already occupies the space
* Whether the space is currently reserved
* Whether the vehicle can physically enter and leave it

Prefer a slightly farther valid parking space over a nearby invalid or dangerous location.

---

# 4. Parking reservation

Prevent multiple NPCs from selecting the same parking location.

Introduce a lightweight reservation/occupancy mechanism if one does not already exist.

A parking space should have states similar to:

```text
AVAILABLE
RESERVED
OCCUPIED
```

The reservation should be acquired before the NPC commits to the parking route.

If the NPC fails to reach the space:

* release the reservation
* select another valid location

If the vehicle leaves:

* release the occupied space

Do not permanently mark a parking location unavailable because one NPC failed to park there.

---

# 5. Parking should be a two-stage route

Do not route the NPC directly through arbitrary geometry to the parking coordinate.

Use:

```text
road route
    ↓
parking access point
    ↓
parking maneuver
    ↓
parking position
```

The vehicle should remain on the road network until it reaches a valid access point.

Only then should it enter:

* parking lot
* driveway
* courtyard
* mapped parking area

This is critical for preventing vehicles from cutting across sidewalks or building geometry.

---

# 6. Safe parking near buildings

Buildings and their surrounding areas should be used intelligently.

A building courtyard or driveway can be considered a valid parking location only if the vehicle can actually reach it.

Do NOT simply assume:

```text
empty area next to building = drivable
```

A safe parking candidate must have a valid connection to the vehicle road network.

For example:

```text
ROAD
========================
        |
        | driveway
        |
   +------------+
   |  COURTYARD |
   |     🚗     |
   +------------+
      BUILDING
```

is valid if OSM/map geometry indicates vehicle access.

But:

```text
ROAD
========================

   +------------+
   |  BUILDING  |
   |            |
   +------------+
```

must not allow the NPC to drive through the building simply because there is an empty coordinate on the other side.

---

# 7. Hard rule: never drive on curbs

NPC vehicles must not drive on road curbs.

This must be treated as a **hard movement constraint**, not merely a routing preference.

The vehicle's actual collision footprint must remain inside the drivable road/lane area.

Do not solve this by simply moving the vehicle center away from the curb.

The entire vehicle footprint must remain within the valid drivable area.

For example:

```text
SIDEWALK
--------------------------------
CURB
================================
ROAD
================================
CURB
--------------------------------
SIDEWALK
```

The vehicle must remain inside the road area.

Its sprite/collision footprint must never cross the curb during normal driving.

---

# 8. Vehicle footprint

Inspect the existing vehicle collision model.

If the game currently uses only a point/center position for road validation, improve it so that roadside validation considers the actual vehicle footprint.

At minimum account for:

* Vehicle width
* Vehicle length
* Heading
* Front/rear overhang where appropriate

The vehicle should be validated using an oriented footprint or equivalent geometry.

Do not use only:

```python
point_inside_road(vehicle.position)
```

because that can still allow:

```text
       ROAD
===================
       🚗
      /   \
     /     \
    /       \
=== CURB ========
```

where the vehicle center is technically on the road but part of the vehicle overlaps the curb.

---

# 9. Lane-aware driving

Integrate curb avoidance with the existing lane system.

The vehicle's target trajectory should remain within its assigned lane.

Do not allow steering/path smoothing to move the vehicle outside the lane simply because a waypoint is close to the road edge.

If the current route uses centerline/waypoints, create or derive a safe corridor around the route.

The corridor must respect:

* Road width
* Lane width
* Vehicle width
* Direction of travel
* One-way roads
* Medians
* Intersections

---

# 10. Curved turns

Pay special attention to existing curved-turn behavior.

A mathematically smooth curve can still cut across a curb.

For example:

```text
BAD:

        |
        |\
        | \
        |  \
        |   \
========    \
CURB          \
```

The generated trajectory must remain inside the legal drivable area.

When generating curved turns:

1. Generate the candidate curve.
2. Sample points along the curve.
3. Validate the vehicle footprint at each sample.
4. Reject or modify curves that cross curbs or other forbidden geometry.

Do not validate only the beginning and end points.

---

# 11. Intersections

Make sure curb avoidance does not break normal intersection behavior.

At intersections, the valid drivable area may be wider than the lane itself.

The NPC should be allowed to use the intersection's actual drivable area.

Do not create artificial restrictions that cause:

* inability to turn
* deadlocks
* vehicles stopping before intersections
* vehicles taking absurd detours

The validation should understand the difference between:

```text
normal road segment
intersection
parking access
```

---

# 12. Sidewalk protection

Treat sidewalks as non-drivable by NPC vehicles unless the OSM data explicitly identifies them as vehicle-accessible.

This should be enforced at the movement/collision level, not only during route generation.

This means an NPC cannot accidentally enter a sidewalk because of:

* steering
* curve interpolation
* collision avoidance
* spawn position
* parking maneuver
* route smoothing

If an explicit driveway crosses a sidewalk, allow the vehicle to cross the sidewalk only as part of entering/leaving that driveway.

The driveway crossing must be intentional and route-authorized.

---

# 13. Building collision protection

NPC vehicles must not drive through building polygons.

Use existing OSM building geometry where available.

Building geometry should act as hard non-drivable geometry except for explicitly supported entrances/access routes.

Validate both:

* route generation
* actual vehicle movement

against building geometry.

This prevents routing bugs from turning into visual/physical nonsense.

---

# 14. Parking maneuver

When the NPC reaches the parking access point, implement a simple controlled parking maneuver.

The maneuver does not need to simulate a perfect human driver.

It should:

* reduce speed
* align with the parking space
* enter the parking area
* stop at the parking position
* avoid curbs/buildings/other vehicles
* respect the parking space orientation where available

Avoid teleporting the vehicle into the parking space.

The vehicle should visibly drive into the parking position.

---

# 15. Parking orientation

Where OSM or existing parking data provides orientation, use it.

The final vehicle heading should preferably match the parking-space direction.

For example:

```text
Parking spaces:

+---+  +---+  +---+
| 🚗|  | 🚗|  | 🚗|
+---+  +---+  +---+
   ↑
consistent orientation
```

Avoid arbitrary final headings that leave vehicles sideways across parking areas.

If orientation is unavailable, choose a sensible heading based on:

* nearest road direction
* parking-area geometry
* access direction

---

# 16. Occupied parking spaces

NPCs should avoid parking spaces that are:

* occupied
* reserved
* blocked by another vehicle
* physically unreachable

Do not require a perfect global parking simulation.

A lightweight local occupancy check is sufficient.

---

# 17. Parking failure handling

NPC parking must be fault tolerant.

If the selected parking space becomes invalid while approaching it:

```text
parking target invalid
        ↓
release reservation
        ↓
find alternative
        ↓
continue route
```

Do not leave the NPC permanently stuck.

After a reasonable number of failed attempts, fall back to another valid destination or despawn according to the existing NPC lifecycle rules.

Never solve parking failure by driving through buildings or over curbs.

---

# 18. Spawn validation

Also inspect NPC vehicle spawning.

An NPC must never spawn:

* on a curb
* on a sidewalk
* inside a building
* inside a parking obstacle
* outside the road unless explicitly spawned at a parking location

The initial vehicle footprint must be validated against the same drivable geometry.

This is important because fixing movement alone does not prevent invalid initial states.

---

# 19. Shared vehicle movement validator

Create one central validation mechanism for NPC vehicle movement.

Conceptually:

```python
validate_vehicle_position(vehicle, position, heading)
```

or:

```python
is_vehicle_pose_valid(vehicle, pose)
```

This should answer questions such as:

```text
Is the complete vehicle footprint inside permitted drivable geometry?
Does it overlap a curb?
Does it overlap a building?
Does it overlap a forbidden sidewalk?
Does it violate a hard map restriction?
```

Use this validator for:

* NPC spawning
* normal movement
* steering
* curved turns
* parking approach
* parking maneuver
* collision avoidance where appropriate

Avoid implementing separate slightly-different curb checks in several locations.

---

# 20. Performance

The game can contain a large amount of OSM geometry, so do not perform expensive geometry checks against the entire map every frame.

Use the existing spatial indexing/tile/chunk system.

The validation flow should be approximately:

```text
vehicle pose
    ↓
cheap bounding-box lookup
    ↓
nearby road/curb/building geometry
    ↓
precise footprint test
    ↓
valid / invalid
```

Cache static geometry.

Do not repeatedly parse OSM data.

Do not perform global searches for every NPC on every frame.

---

# 21. Debug visualization

Extend the existing debug facilities.

When traffic debug mode is enabled, make it possible to visualize:

* NPC target parking space
* Parking reservation state
* Parking access point
* Parking route
* Vehicle footprint
* Current lane
* Drivable area
* Curbs
* Building collision polygons
* Rejected parking locations
* Reason a parking location was rejected

Useful example:

```text
NPC: CAR_42
STATE: PARKING
TARGET: PARKING_SPACE_184
DISTANCE: 31.4 m
RESERVATION: RESERVED
```

And for rejected candidates:

```text
REJECTED
reason = VEHICLE_FOOTPRINT_OVER_CURB
```

Do not enable verbose logging during normal gameplay.

---

# 22. Do not fake parking

Do not implement parking by:

* teleporting NPCs
* snapping them directly to parking coordinates
* moving them through buildings
* ignoring road connectivity
* ignoring vehicle dimensions
* allowing curb driving
* selecting the nearest empty coordinate

The parking behavior should emerge from actual reachable map geometry.

---

# 23. Regression testing

Create tests or deterministic debug scenarios for at least:

### Scenario A — Dedicated parking lot

NPC drives from road into a mapped parking lot and parks.

Expected:

```text
road → access → parking lot → parking space
```

### Scenario B — Building courtyard

NPC can reach a courtyard through a valid driveway.

Expected:

```text
road → driveway → courtyard → parking
```

### Scenario C — Building without access

NPC must not drive through a building to reach an apparently nearby parking location.

### Scenario D — Curb

NPC follows a road close to the curb.

Expected:

```text
vehicle footprint remains completely inside drivable area
```

### Scenario E — Curved turn

NPC performs a sharp turn.

Expected:

```text
entire vehicle footprint remains off curbs
```

### Scenario F — Sidewalk

NPC must not use a sidewalk as a shortcut.

### Scenario G — Occupied parking

Two NPCs target the same parking area.

Expected:

```text
NPC A → reserves space
NPC B → selects another available space
```

### Scenario H — Parking failure

Target parking space becomes unavailable.

Expected:

```text
reservation released
alternative selected
NPC does not become permanently stuck
```

### Scenario I — Spawn

NPC spawn position is validated against the vehicle footprint.

### Scenario J — Multiple NPCs

Many NPCs simultaneously search for parking.

Verify that parking selection remains performant and does not cause noticeable frame-time spikes.

---

# 24. Integration with Resident behavior

Preserve the existing Resident simulation logic.

The Resident system should determine things such as:

```text
where the Resident wants to go
why the Resident is travelling
when the Resident needs a vehicle
```

The traffic/parking system should determine:

```text
how the vehicle reaches the destination
where it can legally park
how it enters the parking location
```

Keep these responsibilities separate.

Do not hard-code specific residential buildings or coordinates.

---

# 25. Important design principle

The long-term goal is a believable city simulation.

Therefore, prefer:

```text
OSM semantics
      +
road graph
      +
drivable geometry
      +
vehicle footprint
      +
parking availability
      +
traffic rules
```

over:

```text
hard-coded coordinate exceptions
```

The system should work in new OSM areas without requiring manually configured parking coordinates.

---

# 26. Implementation process

Before making changes:

1. Inspect the existing code and identify the relevant modules/classes.
2. Explain briefly how the current NPC routing and parking system works.
3. Identify what existing OSM geometry can be reused.
4. Identify the minimum architectural changes required.
5. Implement the changes.

Do not stop after giving recommendations. Actually modify the implementation.

After implementation:

* Run the existing test suite.
* Add regression tests for parking and curb avoidance.
* Run lint/type checks if available.
* Verify that the game starts.
* Verify NPCs still spawn correctly.
* Verify NPCs still follow routes.
* Verify normal turns still work.
* Verify NPCs can reach destinations.
* Verify parking works.
* Verify NPCs do not drive on curbs or sidewalks.
* Verify NPCs do not drive through buildings.
* Verify parking reservations work.
* Check performance with many NPCs.

Finally provide a concise summary:

```text
Files changed
NPC parking architecture
Parking candidate selection
Parking reservation system
Vehicle footprint validation
Curb/sidewalk protection
Building collision protection
Tests performed
Performance impact
Known limitations
```

Do not introduce unnecessary rewrites of unrelated systems. Preserve working traffic behavior and make the new parking and drivable-area rules reusable for future NPC development.
