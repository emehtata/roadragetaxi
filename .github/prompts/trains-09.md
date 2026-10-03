# Railway Taxi Phase 9 – Meet & Greet

## Objective

Implement the physical **meet & greet** interaction for railway passengers with an accepted pre-booked taxi.

Phase 8 already provides:

```text
railway passenger
    ↓
taxi demand
    ↓
pre-booked taxi
    ↓
exact train instance
    ↓
destination railway station
    ↓
existing nearest taxi stand
    ↓
ride destination
    ↓
additional pre-booking fee €8
```

Phase 9 turns the arriving passenger into an identifiable pickup customer that the player must physically meet at the railway station taxi stand.

The intended gameplay loop becomes:

```text
phone booking
    ↓
player accepts
    ↓
player drives to railway station
    ↓
booked train arrives
    ↓
booked passenger leaves train
    ↓
passenger walks to existing taxi stand
    ↓
player identifies and meets passenger
    ↓
passenger enters player's taxi
    ↓
taxi trip can begin
```

Do NOT implement the complete taxi journey or payment system in this phase. Phase 9 ends when the passenger has successfully entered the player's taxi and the booking is ready to become an active taxi trip.

---

# 1. Inspect the existing implementation first

Before changing code, inspect:

* Phase 8 taxi booking implementation
* railway passenger identity/lifecycle
* train passenger manifest
* train arrival and passenger alighting
* station passenger pedestrian creation
* existing pedestrian/resident system
* pedestrian movement
* taxi stand waiting/queue system
* TaxiManager
* existing taxi customer pickup logic
* player's taxi state
* existing interaction/input system
* existing HUD/phone/task UI
* collision/proximity detection
* money/fare system
* save/load system, if present
* relevant tests

Do not assume filenames, classes or APIs.

Reuse existing systems wherever possible.

Do not create a parallel pedestrian, taxi passenger or interaction framework.

---

# 2. The booking is the source of truth

The Phase 8 `TaxiBooking` remains the authoritative source for the pre-booked customer.

The booking references:

```text
booking
    ↓
passenger_id
    ↓
specific train instance
    ↓
destination station
    ↓
existing taxi stand
    ↓
ride destination
```

Do NOT create a new passenger when the train arrives.

Do NOT generate a replacement NPC for the booking.

The physical pedestrian must be the existing representation of the same logical railway passenger.

---

# 3. Preserve passenger identity

The most important requirement is identity continuity.

The same logical passenger must remain identifiable through:

```text
railway passenger
    ↓
train manifest
    ↓
alighting
    ↓
station pedestrian
    ↓
taxi stand waiting passenger
    ↓
player pickup
```

Conceptually:

```text
Passenger #1842
       │
       ├── Train: IC57
       ├── Booking: #731
       └── Pedestrian entity: existing NPC representation
```

Do not solve this by matching passengers based on:

* position
* random appearance
* spawn order
* nearest pedestrian
* train carriage position

Use the existing passenger identity mechanism.

If the current pedestrian model does not retain the railway passenger ID, extend it minimally so the association survives the lifecycle.

---

# 4. When the train arrives

Use the existing railway timetable and train-state system.

Do not create another arrival simulation.

When the booked train reaches the destination station:

```text
ACCEPTED
    ↓
TRAIN_ARRIVING
    ↓
PASSENGER_WAITING
```

The existing passenger-alighting system should create the physical pedestrian when appropriate.

The booked passenger must retain:

```text
passenger_id
booking_id
taxi_booking association
```

after leaving the train.

---

# 5. Existing station/taxi-stand behaviour

Phase 7 already implemented taxi-demand passengers walking to the existing nearest taxi stand.

Reuse that behaviour.

Do NOT:

* create a new taxi stand
* create a special booking-only pickup location
* move the passenger to a new arbitrary location
* create a separate passenger queue system
* replace the existing taxi stand queue

The booked passenger should use the same existing station taxi stand as other taxi-demand passengers.

The distinction is in the passenger's logical booking state, not in a separate physical taxi stand.

---

# 6. Booked passenger identification

The player must be able to distinguish the booked passenger from ordinary taxi customers waiting at the same stand.

This is the central gameplay feature of Phase 9.

Use the existing pedestrian rendering/UI conventions.

Do not introduce an intrusive or unrealistic marker unless the existing game already uses such markers.

A suitable lightweight solution could be:

```text
booked passenger
    ↓
subtle visual identifier
```

and/or:

```text
BOOKED CUSTOMER
```

in the existing interaction/HUD area when the player is close enough.

The exact implementation must follow the existing game's visual language.

The identifier must be associated with the booking, not merely with the fact that the pedestrian wants a taxi.

Ordinary stand customers must NOT receive the booked-customer identifier.

---

# 7. Do not identify by appearance alone

The player should not have to guess which passenger is booked based solely on sprite appearance.

The game must have a deterministic logical connection:

```text
TaxiBooking.passenger_id
        ↓
physical pedestrian
```

Visual distinction is only the presentation of that relationship.

Do not use:

```text
nearest pedestrian == booked passenger
```

as the actual identity mechanism.

---

# 8. Player must physically meet the passenger

The booking should not complete merely because:

* the player reaches the railway station
* the player reaches the taxi stand
* the train arrives
* the passenger reaches the taxi stand

The player must physically approach the booked passenger with the player's taxi.

Reuse the existing proximity/collision/interaction system if one exists.

Define a sensible pickup interaction radius using the project's existing world-coordinate conventions.

Do not introduce arbitrary coordinate systems.

---

# 9. Meet & greet interaction

When the player's taxi is sufficiently close to the booked passenger:

```text
booked passenger
        +
player taxi
        ↓
pickup interaction available
```

The player should explicitly perform the existing pickup interaction/input.

Do not automatically pick up the passenger merely because the taxi enters the radius unless that is already how normal taxi pickups work.

The interaction should follow the existing taxi pickup controls.

---

# 10. Prevent picking up the wrong passenger

The booked pickup interaction must verify the correct passenger.

A player approaching an ordinary taxi customer must not accidentally complete the railway booking.

Conceptually:

```text
ordinary stand customer
    → normal taxi pickup flow

booked passenger
    → pre-booked pickup flow
```

The booking must only complete when the physical pedestrian corresponds to:

```text
TaxiBooking.passenger_id
```

---

# 11. Booking state after successful meet & greet

When the player successfully meets the booked passenger:

```text
PASSENGER_WAITING
        ↓
PASSENGER_MET
```

Then, when the passenger enters the player's taxi:

```text
PASSENGER_MET
        ↓
IN_TAXI
```

Use the project's existing state naming conventions if equivalent states already exist.

The booking should remain associated with the passenger and the requested ride destination.

---

# 12. Passenger entering the taxi

Reuse the existing taxi customer boarding mechanism.

Do NOT create a second boarding implementation specifically for railway passengers.

If the existing system removes/hides a pedestrian when entering a taxi, use the same mechanism.

The passenger's logical identity must remain associated with the active taxi customer.

Conceptually:

```text
Passenger #1842
    ↓
station pedestrian
    ↓
meet & greet
    ↓
existing taxi customer representation
    ↓
inside player's taxi
```

---

# 13. Preserve the requested destination

The destination was established in Phase 8.

Do NOT choose a new destination during pickup.

After boarding, the active taxi customer must still have:

```text
ride_destination
```

from the booking.

The destination must not be regenerated randomly.

Do not ask the player to choose the destination.

Do not replace the booking destination with the railway station.

---

# 14. Pre-booking fee

The booking contains:

```text
pre_booking_fee = €8
```

This is an **additional fee** and does not include the normal taxi initial/startup fare.

Phase 9 must preserve this information.

Do NOT treat €8 as:

* the complete fare
* the normal starting fare
* a replacement for the starting fare

Conceptually the eventual trip economics are:

```text
€8 pre-booking fee
+
normal initial/startup fare
+
normal trip fare
```

Do not implement final payment calculation in Phase 9 unless the existing taxi pickup system already requires it.

---

# 15. Normal taxi customers must continue working

The new booked-passenger behaviour must not break existing taxi stand customers.

Verify that:

* ordinary taxi customers still wait normally
* ordinary taxi pickups still work
* booked customers can coexist with ordinary customers
* multiple booked customers can coexist
* passengers do not get duplicated
* a booked passenger does not become an ordinary anonymous customer
* an ordinary customer cannot accidentally complete a railway booking

---

# 16. Multiple bookings

Support multiple simultaneous bookings.

Example:

```text
IC57  → Oulu → Passenger #1842
IC274 → Oulu → Passenger #1931
```

Both passengers may eventually be present at the same taxi stand.

Each must retain its own:

```text
passenger_id
booking_id
train_instance_id
ride_destination
```

The player should be able to identify and pick up the correct customer.

Do NOT use a single global:

```text
current_booked_passenger
```

---

# 17. Passenger waiting order

Do not force the booked passenger to become the first passenger in the taxi queue.

The existing taxi stand queue should remain authoritative for ordinary stand behaviour.

The booked passenger is special because the player has a reservation with that passenger, not because the passenger has special physical priority.

If the existing taxi stand implementation already has an appropriate concept of customer selection, integrate with it rather than creating another queue.

---

# 18. Missed booking

Implement the minimum state necessary to detect a missed booking.

A booking should not remain indefinitely in:

```text
PASSENGER_WAITING
```

if the player never meets the passenger.

Use the existing game-clock conventions.

A reasonable initial state is:

```text
PASSENGER_WAITING
    ↓
MISSED
```

after a clearly defined pickup window.

Do not implement reputation penalties, customer complaints or financial penalties yet.

Those can be added later.

If the existing game has an established timeout/customer waiting mechanism, reuse it.

---

# 19. Out-of-view and streaming behaviour

Phase 7 established that passengers outside the active view may exist only as data.

Phase 9 must preserve this.

Do not force all booked passengers to spawn into the world merely because they have a booking.

When the passenger becomes physically relevant through the existing railway/pedestrian lifecycle:

```text
logical passenger
    ↓
physical pedestrian
```

the booking association must be restored automatically.

The booking must never depend on the passenger having been continuously rendered.

---

# 20. No pathfinding changes

Do not introduce a new pedestrian navigation/pathfinding system in this phase.

Use the existing Phase 7 behaviour:

* passenger walks to the existing taxi stand using the current mechanism
* if the existing safety check prevents the walk because it would cross railway tracks, preserve that behaviour
* the passenger can still have the taxi booking even if physical movement is limited

Do not modify railway track safety logic as part of Phase 9.

---

# 21. Performance

Do not introduce per-frame searches such as:

```text
for every booking:
    search every pedestrian
```

Instead, maintain direct references/IDs where the existing architecture allows it.

The desired relationship is:

```text
booking
    ↓ direct passenger identity
passenger
    ↓ existing pedestrian association
pedestrian
```

Only perform proximity checks when necessary and within the existing interaction architecture.

Do not add global O(number of bookings × number of pedestrians) scans every frame.

---

# 22. Tests

Add focused tests for:

### Identity continuity

Verify:

```text
railway passenger
→ train manifest
→ alighting
→ pedestrian
```

retains the same passenger identity.

### Booking association

Verify that the booked passenger resolves to the correct pedestrian.

### No duplicate passenger

Verify that alighting does not create a second passenger for the booking.

### Booked passenger identification

Verify that the booked passenger receives the booked-customer state/identifier.

Verify ordinary taxi customers do not.

### Pickup proximity

Verify that the booking cannot complete while the player's taxi is outside the interaction range.

### Correct passenger

Verify that approaching an ordinary taxi customer cannot complete another passenger's booking.

### Successful meet & greet

Verify:

```text
PASSENGER_WAITING
→ PASSENGER_MET
→ IN_TAXI
```

or the project's equivalent states.

### Destination preservation

Verify that the Phase 8 ride destination survives:

```text
booking
→ passenger waiting
→ pickup
→ active taxi customer
```

without being regenerated.

### €8 preservation

Verify that the additional pre-booking fee remains €8 and is not confused with the normal starting fare.

### Multiple bookings

Verify multiple booked passengers can exist simultaneously.

### Missed booking

Verify the booking can transition to `MISSED` according to the existing timeout mechanism.

### Ordinary customers

Verify existing taxi stand customers continue to work.

### Out-of-view passenger

Verify that a booking remains valid while the physical pedestrian does not exist because the passenger is outside the active world/view.

### Performance

Verify that no per-frame global pedestrian/booking scan has been introduced.

Run the complete existing test suite.

---

# 23. Do NOT implement Phase 10 yet

This phase must NOT implement:

* full taxi route navigation
* destination pathfinding
* trip distance/time fare calculation
* final payment
* customer rating
* tips
* reputation changes
* customer dialogue system
* advanced passenger animation
* dynamic taxi pricing
* new taxi stands
* new pedestrian navigation
* multiplayer

Phase 9 ends when:

```text
player accepts booking
        ↓
train arrives
        ↓
booked passenger alights
        ↓
passenger reaches existing taxi stand
        ↓
player identifies booked passenger
        ↓
player performs meet & greet
        ↓
passenger enters player's taxi
```

The resulting taxi customer must retain the Phase 8 ride destination and pre-booking fee so that the next phase can start the actual taxi journey.

---

# 24. Implementation workflow

Work incrementally:

1. Inspect Phase 8 booking implementation.
2. Trace the complete railway passenger lifecycle.
3. Identify how the physical pedestrian is linked to a railway passenger.
4. Identify the existing taxi stand waiting/queue system.
5. Identify the existing taxi pickup interaction.
6. Implement the booking → pedestrian identity bridge.
7. Make the booked passenger distinguishable.
8. Implement proximity/interaction using the existing taxi pickup mechanism.
9. Transfer the booked passenger into the existing taxi customer representation.
10. Preserve ride destination and pre-booking fee.
11. Implement minimal missed-booking state.
12. Add focused tests.
13. Run railway, passenger and taxi tests.
14. Run the full test suite.
15. Perform a real gameplay test with:

    * one booked passenger
    * ordinary taxi customers
    * multiple bookings
    * a train arriving outside the current view
16. Check performance.
17. Review the diff and remove unnecessary changes.

Do not perform unrelated refactoring.

---

# Acceptance criteria

Phase 9 is complete when:

* a Phase 8 booking survives until the passenger leaves the train
* the logical passenger identity remains unchanged
* the physical pedestrian is the existing representation of that passenger
* the booked passenger walks/waits using the existing taxi stand system
* no taxi stand is created, moved or duplicated
* the player can distinguish the booked passenger from ordinary taxi customers
* the booked passenger cannot be confused with another pedestrian
* the player must physically approach the booked passenger
* the existing pickup/interaction mechanism is used
* successful interaction transfers the passenger into the player's taxi
* the Phase 8 ride destination is preserved
* the €8 additional pre-booking fee is preserved separately from the normal initial/startup fare
* multiple bookings can coexist
* ordinary taxi customers continue to work
* out-of-view passengers remain valid as logical data
* no new pedestrian navigation system is introduced
* no expensive per-frame global scans are introduced
* tests pass
* there is no meaningful FPS regression

At the end, report:

* files changed
* passenger identity mechanism used
* booking → pedestrian association
* booked-passenger visual/interaction implementation
* pickup interaction used
* state transitions
* destination preservation
* pre-booking fee handling
* missed-booking handling
* tests executed
* performance impact
* limitations intentionally left for Phase 10
