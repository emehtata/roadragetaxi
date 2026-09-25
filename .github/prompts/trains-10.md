# Railway Taxi Phase 10 – Driver Meet & Greet

## Objective

Replace the Phase 9 automatic pre-booked passenger pickup with a physical **driver meet & greet** interaction.

Phase 9 currently allows an accepted booked passenger to be picked up by the existing taxi stand pickup mechanism:

* stop the taxi within 15 m
* remain there for 2 seconds
* the booked passenger is picked deterministically
* the passenger walks to the taxi and enters it

This behaviour must be changed for **pre-booked railway passengers**.

The player must now leave the taxi, walk to the booked passenger, identify themselves with a small white name card, explicitly greet the passenger, and only then may the passenger board the taxi.

The intended gameplay loop is:

```text
player accepts booking
        ↓
booked train arrives
        ↓
passenger walks to existing taxi stand
        ↓
player drives to station
        ↓
player parks taxi
        ↓
player exits taxi
        ↓
driver walks toward booked passenger
        ↓
driver carries small white card
        ↓
booked passenger is clearly highlighted
        ↓
driver reaches passenger
        ↓
player explicitly greets passenger
        ↓
passenger becomes ready to board
        ↓
passenger enters player's taxi
        ↓
driver returns to taxi
        ↓
normal taxi trip can begin
```

The key gameplay rule is:

> **The passenger cannot enter the taxi and the trip cannot begin until the driver has physically greeted the passenger.**

---

# 1. Inspect the existing Phase 9 implementation first

Before changing code, inspect the implementation described by the Phase 9 report.

In particular inspect:

* `rail_bookings.py`
* `station_passengers.py`
* `taxi.py`
* `trains.py`
* `render/pedestrians.py`
* `localization.py`
* `tests/test_rail_bookings.py`
* `tests/test_rail_meet_greet.py`

Also inspect:

* player taxi entity
* player vehicle exit/entry system
* player-on-foot movement, if present
* existing interaction/input system
* pedestrian rendering
* taxi stand pickup
* taxi customer lifecycle
* booking state machine

Do not assume filenames or APIs beyond the implementation already found in the repository.

Reuse existing systems.

Do not create a parallel taxi customer, pedestrian or booking system.

---

# 2. Replace the current automatic pickup for booked passengers

The current Phase 9 behaviour is:

```text
booked passenger
    ↓
taxi within 15 m
    ↓
wait 2 seconds
    ↓
automatic deterministic pickup
```

This must no longer complete a railway pre-booked pickup.

For a pre-booked railway passenger, the 15 m / 2 s stand-pickup mechanism must NOT allow the customer to enter the taxi before the driver has greeted them.

Ordinary taxi stand customers must retain their existing pickup behaviour.

Therefore distinguish clearly between:

```text
ordinary taxi customer
    → existing automatic stand pickup

pre-booked railway customer
    → Phase 10 driver meet & greet
```

Do not remove or break the ordinary taxi pickup system.

---

# 3. The player must leave the taxi

The player must physically exit the taxi before the booked passenger can be greeted.

Required sequence:

```text
taxi
 ↓
player exits
 ↓
driver is on foot
 ↓
driver walks to passenger
```

Use the existing vehicle exit mechanism.

Do not teleport the player.

Do not automatically move the driver to the passenger.

Do not complete the booking merely because the taxi is within 15 m.

---

# 4. Player-on-foot movement

Reuse the existing player movement system if one exists.

The player must manually walk toward the booked passenger.

If the current game does not yet have a suitable on-foot player representation, implement the smallest extension necessary to support this feature.

Do not create a general-purpose pedestrian controller.

Do not refactor the existing pedestrian architecture unnecessarily.

---

# 5. Driver's white name card

During an active pre-booked meet & greet, the driver carries a small physical white card.

The card represents the passenger's name.

The passenger's actual name does **not** need to be rendered.

A simple white rectangular card is sufficient.

Conceptually:

```text
driver
  └── [ WHITE CARD ]
```

Requirements:

* small
* clearly visible
* attached to the driver
* follows the driver while walking
* does not require readable text
* does not need the passenger name rendered

Do not introduce unnecessary text rendering for the card.

---

# 6. Card visibility

The card should only appear while the player is actively performing a pre-booked meet & greet.

For example:

```text
normal driving
    → no card

normal walking
    → no card

active pre-booked meet & greet
    → white card visible

greeting completed
    → card hidden
```

Use the existing rendering architecture.

---

# 7. Replace the Phase 9 booked-passenger marker

Phase 9 currently displays:

* a light-blue ring around the booked passenger
* the booking name above the passenger

This is not the desired final presentation.

Replace that presentation with a clear directional arrow pointing toward the booked passenger.

The booked passenger must be distinguishable from the surrounding crowd at a glance.

Do NOT render the passenger's name above them.

The required visual concept is:

```text
            ↓
      booked passenger
```

or an equivalent directional indicator consistent with the game's rendering style.

The arrow must identify the actual booked passenger.

---

# 8. Passenger identity remains unchanged

Keep the Phase 9 identity mechanism.

Phase 5 already associates:

```python
pedestrian.rail_passenger
```

with the logical railway passenger.

Phase 9 added:

```python
waiting_booking(pedestrian)
```

which resolves the booking through that relationship.

Continue using this identity chain.

Do NOT identify the passenger by:

* nearest pedestrian
* nearest taxi customer
* position
* appearance
* spawn order
* random selection

The target must remain:

```text
TaxiBooking
    ↓
passenger_id
    ↓
Railway Passenger
    ↓
pedestrian.rail_passenger
    ↓
physical pedestrian
```

---

# 9. The arrow must follow the actual passenger

The arrow must be attached logically to the booked passenger.

If the passenger moves:

```text
passenger moves
    ↓
arrow target moves
```

Do not place a static arrow at the taxi stand.

Do not select the nearest passenger.

Do not scan every pedestrian every frame if the existing booking → pedestrian relationship can be used directly.

Reuse the existing Phase 9 `waiting_booking(pedestrian)` relationship or an equivalent direct lookup.

---

# 10. Only show the arrow for the active booking

The player may have multiple bookings.

Only the booking currently being handled by the player should receive the meet & greet target indicator.

Do not create a forest of arrows for all future bookings.

Conceptually:

```text
Booking A = active
    → arrow points to Passenger A

Booking B = pending
    → no meet & greet arrow
```

Use the existing job/task selection mechanism if available.

Do not create a new global "current passenger" system if the existing booking system already provides an equivalent concept.

---

# 11. Explicit greeting

The player must explicitly greet the booked passenger.

When the driver gets sufficiently close, show the existing style of interaction prompt.

For example:

```text
Greet passenger
[Interact]
```

Use the project's existing interaction/input conventions.

Do not automatically greet merely because the driver enters the interaction radius.

The player must perform an explicit action.

---

# 12. Greeting is the hard prerequisite

This is the most important state change from Phase 9.

Phase 9 currently does:

```text
PASSENGER_WAITING
    ↓
PASSENGER_MET
```

when the passenger starts walking toward the taxi.

That is too early for the new gameplay.

Change the semantics so that:

```text
PASSENGER_WAITING
    ↓
driver approaches
    ↓
player explicitly greets
    ↓
PASSENGER_MET
```

`PASSENGER_MET` must mean that the driver and passenger have actually completed the meet & greet.

It must NOT mean merely:

* passenger is walking toward the taxi
* taxi is nearby
* passenger has started a pickup animation

---

# 13. Passenger cannot board before greeting

Before `PASSENGER_MET`:

* passenger cannot enter the taxi
* existing 15 m / 2 s automatic pickup cannot complete the booking
* passenger cannot become `IN_TAXI`
* taxi trip cannot start
* destination navigation cannot start

This must be enforced in the state logic, not merely through UI.

Even if the player's taxi is parked directly beside the passenger, the passenger must remain waiting until the driver has greeted them.

---

# 14. Passenger boarding after greeting

After:

```text
PASSENGER_WAITING
    ↓
PLAYER_GREETS
    ↓
PASSENGER_MET
```

the passenger becomes eligible to board.

Reuse the existing Phase 9 boarding/customer mechanism.

Do not create a separate railway passenger boarding implementation unless the existing mechanism cannot support the required state.

The desired sequence is:

```text
PASSENGER_MET
    ↓
passenger can board
    ↓
IN_TAXI
```

---

# 15. Driver must return to the taxi

After greeting the passenger, the driver must return to the taxi.

Do not teleport the driver back into the vehicle.

Use the existing vehicle-entry interaction.

The intended gameplay is:

```text
exit taxi
    ↓
walk to passenger
    ↓
greet passenger
    ↓
passenger is ready/boards
    ↓
walk back to taxi
    ↓
enter taxi
```

If the existing passenger boarding system causes the passenger to walk to the taxi automatically after the greeting, that is acceptable.

The driver must still return to the taxi normally.

---

# 16. Trip cannot begin while the driver is on foot

The taxi trip must not start until:

```text
driver is inside taxi
+
passenger is inside taxi
+
greeting completed
```

Therefore:

```text
greeting completed
    ↓
passenger may board
    ↓
driver returns to taxi
    ↓
driver enters taxi
    ↓
TRIP_READY
```

Use existing taxi state conventions where available.

Do not implement the complete taxi journey in this phase.

---

# 17. Preserve Phase 9 destination handling

Phase 9 already correctly preserves the booking's destination rather than generating a new random destination.

Keep this behaviour.

The destination must survive:

```text
booking
    ↓
waiting passenger
    ↓
greeting
    ↓
boarding
    ↓
active taxi customer
```

Do not choose a new destination at pickup.

Do not replace it with the railway station.

---

# 18. Preserve the €8 pre-booking surcharge

Phase 9 correctly stores the €8 as:

```text
surcharge_cents
```

and carries the booking with the taxi customer.

Keep that implementation.

The €8 is:

> an agreed additional pre-booking fee, not including the normal initial/startup fare.

The normal taxi meter starts normally.

Do NOT:

* replace the startup fare with €8
* treat €8 as the total fare
* charge €8 twice
* discard `surcharge_cents`

Charging the surcharge at drop-off remains outside the scope of Phase 10.

---

# 19. Missed booking behaviour

Phase 9 currently has:

```text
PASSENGER_WAITING
    ↓
MISSED
```

after 20 game minutes.

Driving away mid-pickup also causes `MISSED`.

Preserve this behaviour unless the new physical meet & greet lifecycle requires a minimal adjustment.

When the booking becomes `MISSED`:

* remove the meet & greet arrow
* hide the driver's white card
* prevent greeting
* prevent boarding as the booked customer

Do not add reputation or financial penalties yet.

---

# 20. Track-blocked passenger behaviour

Phase 7 established that a passenger may fail to walk directly to the taxi stand when a track blocks the direct route.

Phase 9 currently allows such a passenger to wander off while the booking marker remains visible.

Do not introduce new pedestrian pathfinding in Phase 10.

However, the meet & greet system must continue to target the actual booked passenger wherever the existing pedestrian system places them.

The arrow must follow the actual passenger rather than assuming they are standing at the taxi stand.

---

# 21. Off-screen passenger behaviour

Phase 9 supports passengers that temporarily exist only as data when their station is outside the active world/view.

Preserve this behaviour.

Do not force an off-screen passenger to spawn merely because the booking is active.

When the pedestrian becomes physically instantiated again, the booking → passenger → pedestrian relationship must continue to work.

The arrow should only target an actual physical passenger when one exists.

---

# 22. Ordinary taxi customers

Do not break the existing ordinary taxi stand flow.

Ordinary customers should continue to use:

```text
taxi within stand pickup range
+
existing pickup delay
```

or whatever the existing system currently uses.

The new driver meet & greet applies only to accepted pre-booked railway passengers.

An ordinary taxi customer must never:

* receive the booked-passenger arrow
* cause the driver to display the white card
* require a greeting
* accidentally complete a railway booking

---

# 23. Multiple bookings

Multiple bookings must continue to coexist.

Example:

```text
IC57
    → Passenger A
    → Oulu
    → Booking A

IC274
    → Passenger B
    → Oulu
    → Booking B
```

The player handles one active meet & greet at a time.

Completing Booking A must not modify Booking B.

Do not introduce a single global passenger variable that replaces the existing booking identities.

---

# 24. Performance

Preserve the Phase 9 performance improvements.

Phase 9 checks waiting bookings approximately once per second rather than scanning all pedestrians every frame.

Do not regress this.

The arrow should use the already-resolved passenger/pedestrian relationship.

Do not implement:

```text
every frame
    ↓
scan all pedestrians
    ↓
find booked passenger
```

Likewise, do not perform global pedestrian searches to update the driver card.

The driver card follows the player directly.

---

# 25. Tests

Update the Phase 9 tests and add focused Phase 10 tests.

### Existing automatic pickup disabled

Verify that a booked railway passenger is NOT picked up merely because:

```text
taxi within 15 m
+
2 seconds elapsed
```

before the driver has greeted them.

### Driver must exit taxi

Verify that the meet & greet cannot complete while the player remains inside the taxi.

### Passenger identity

Verify that the arrow and interaction target the correct passenger through the existing booking identity.

### Arrow

Verify:

```text
accepted booking + passenger waiting
    → arrow visible

booking missed
    → arrow hidden

greeting completed
    → arrow hidden
```

### No name rendering

Verify that the new target presentation does not depend on rendering the passenger's name above them.

### White card

Verify:

```text
active meet & greet
    → white card visible

normal gameplay
    → white card hidden

greeting completed
    → white card hidden
```

### Greeting

Verify that explicit player interaction is required.

### Greeting state

Verify:

```text
PASSENGER_WAITING
    → PLAYER_GREETS
    → PASSENGER_MET
```

and that simply approaching the passenger does not produce `PASSENGER_MET`.

### Boarding prerequisite

Verify that:

```text
PASSENGER_WAITING
```

cannot transition to:

```text
IN_TAXI
```

without greeting.

### Trip prerequisite

Verify that the trip cannot start while the driver is outside the taxi.

### Destination

Verify that the Phase 8 destination remains unchanged after greeting and boarding.

### Surcharge

Verify that `surcharge_cents` remains attached to the active taxi customer and is still separate from the normal startup fare.

### Multiple bookings

Verify independent targets and state.

### Missed booking

Verify that a missed booking cannot subsequently be greeted or boarded.

### Ordinary customer regression

Verify that ordinary taxi customers retain their existing pickup behaviour.

### Off-screen passenger

Verify that an off-screen booked passenger does not cause unnecessary pedestrian spawning and reconnects correctly when instantiated.

### Performance

Verify that no per-frame global pedestrian scan has been introduced.

Run the complete test suite.

---

# 26. Do NOT implement the complete taxi journey

Phase 10 ends after the meet & greet and boarding sequence.

Do NOT implement:

* charging the €8 surcharge
* normal trip fare calculation changes
* drop-off payment
* tips
* reputation
* customer rating
* customer complaints
* advanced dialogue
* new taxi stands
* new pedestrian pathfinding
* multiplayer
* unrelated refactoring

The next phase can handle the actual taxi journey and final fare settlement.

---

# 27. Implementation workflow

Work incrementally:

1. Inspect the actual Phase 9 implementation.
2. Identify exactly where the current 15 m / 2 s booked pickup occurs.
3. Disable that automatic completion only for pre-booked railway customers.
4. Preserve it for ordinary taxi customers.
5. Inspect the existing player vehicle exit/entry implementation.
6. Inspect existing player-on-foot movement.
7. Implement the active meet & greet state.
8. Replace the Phase 9 light-blue ring/name marker with a directional passenger arrow.
9. Implement the driver's small white card.
10. Require the player to exit the taxi.
11. Require the player to physically walk to the passenger.
12. Add explicit greeting interaction.
13. Make greeting the only transition to `PASSENGER_MET`.
14. Allow boarding only after `PASSENGER_MET`.
15. Require the driver to return to the taxi.
16. Preserve the existing booking destination and `surcharge_cents`.
17. Preserve missed-booking behaviour.
18. Add/update tests.
19. Run the complete test suite.
20. Perform a real gameplay test with:

    * one booked arrival
    * ordinary taxi customers
    * several pedestrians around the stand
    * an off-screen arrival
    * the player exiting the taxi
    * walking to the customer
    * greeting
    * returning to the taxi
    * boarding
21. Check performance.
22. Review the diff and remove unnecessary changes.

Do not perform unrelated refactoring.

---

# Acceptance criteria

Phase 10 is complete when:

* the Phase 9 automatic 15 m / 2 s pickup cannot complete a booked railway pickup before greeting
* ordinary taxi customers retain their existing pickup behaviour
* the player must leave the taxi
* the player must physically walk to the booked passenger
* the driver visibly carries a small white card during the active meet & greet
* the passenger's name does not need to be rendered
* the booked passenger is clearly distinguishable from the surrounding crowd
* a directional arrow identifies the correct booked passenger
* the arrow follows the actual passenger
* the existing passenger identity relationship is used
* the player must explicitly greet the passenger
* approaching the passenger alone does not count as greeting
* `PASSENGER_MET` means the greeting actually happened
* the passenger cannot enter the taxi before greeting
* the taxi trip cannot start before greeting
* the player must return to the taxi normally
* the driver must be inside the taxi before the trip can start
* the Phase 9 destination remains intact
* `surcharge_cents` remains intact and separate from the normal startup fare
* missed bookings cannot be completed after expiry
* off-screen passenger behaviour continues to work
* multiple bookings remain independent
* no new taxi stands are created
* no new pedestrian navigation system is introduced
* no expensive per-frame global pedestrian scan is introduced
* existing taxi customers continue to work
* the full test suite passes
* there is no meaningful FPS regression

At the end, report:

* files changed
* exact Phase 9 automatic pickup path that was replaced
* player exit/walking implementation
* driver white-card implementation
* passenger-arrow implementation
* greeting interaction
* state transitions
* boarding prerequisite
* destination preservation
* `surcharge_cents` preservation
* missed-booking handling
* tests executed
* real gameplay test result
* performance impact
* limitations intentionally left for the next taxi phase
