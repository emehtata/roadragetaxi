# Railway Taxi Phase 8 – Pre-booking

## Objective

Implement pre-booked taxi reservations for railway passengers.

A railway passenger who has taxi demand may optionally pre-book a taxi before their train arrives at the destination station.

Example:

```text
IC57
→ arrives at Oulu railway station
→ passenger has pre-booked a taxi
→ taxi pickup at the existing nearest taxi stand
→ agreed additional starting fare not including the initial startup fare: €8
```

The booking should become a concrete gameplay task for the player.

The actual passenger identification and meet & greet interaction belong to **Phase 9** and must NOT be implemented in this phase.

---

# 1. Inspect the existing implementation first

Before changing code, inspect:

* railway passenger model
* train passenger/manifest system
* train identity and scheduled service data
* train arrival/departure state
* railway station model
* station → nearest existing taxi stand association from Phase 7
* taxi-demand implementation from Phase 7
* existing taxi customer/passenger system
* phone UI
* notifications
* player job/task systems
* money/fare system
* game clock
* save/load system, if present
* existing tests

Do not assume filenames, classes, APIs, UI components or data structures.

Reuse existing systems wherever possible.

Do not create parallel systems for passengers, taxis, notifications or money.

---

# 2. Important: existing taxi stands

Taxi stands already exist in the game.

Use the station → nearest existing taxi stand association created in Phase 7.

Do NOT:

* create taxi stands
* create railway-specific taxi stands
* modify taxi stand placement
* import additional taxi stand OSM data
* move taxi stands
* create fallback pickup locations

The booking must reference the existing taxi stand associated with the passenger's destination railway station.

---

# 3. Booking data model

Introduce a lightweight taxi booking entity/state.

Conceptually:

```python
TaxiBooking
    booking_id
    passenger_id
    train_instance_id
    train_number
    station_id
    taxi_stand_id
    destination
    fare
    status
    created_at
```

Use the existing project's naming and data-model conventions.

Do not blindly copy this structure if equivalent fields already exist.

The important relationships are:

```text
booking
   ↓
passenger
   ↓
specific train journey
   ↓
destination station
   ↓
existing nearest taxi stand
```

---

# 4. Identify the exact train instance

A booking must refer to a **specific scheduled train occurrence**.

Do NOT identify a booking using only:

```text
IC57
```

because the same train number can occur on multiple dates.

Use the existing train identity mechanism if one already exists.

Conceptually:

```text
departure date
+
train number
```

or the project's existing unique scheduled-train ID.

The booking must therefore distinguish:

```text
IC57 on 2026-09-25
```

from:

```text
IC57 on 2026-09-26
```

---

# 5. Booking eligibility

Only railway passengers with:

```text
transportation intent = TAXI
```

can receive a taxi pre-booking.

Not every taxi-demand passenger must be pre-booked.

The system should support both:

```text
TAXI
├── spontaneous taxi demand
└── pre-booked taxi
```

For example:

```python
passenger.transport_intent = TAXI
passenger.pre_booked = True
```

Use an equivalent representation if the existing model makes more sense.

Do not make every TAXI passenger automatically pre-booked.

---

# 6. Generating pre-bookings

Generate a subset of taxi-demand railway passengers as pre-booked customers.

Use the existing passenger generation/randomness system.

Respect the existing deterministic random seed behaviour.

Do not introduce a separate uncontrolled random generator.

If the project already has configurable demand probabilities, use that configuration.

If it does not, introduce only a simple, clearly named constant in the existing appropriate configuration/module.

Do NOT invent environment variables.

---

# 7. Booking timing

The booking must exist **before the train arrives**.

The player should have an opportunity to see the booking and prepare for the pickup.

The exact advance notice should follow the existing game-clock/timetable architecture.

Do not create a second simulated train schedule.

The booking should be associated with the existing scheduled arrival time.

Conceptually:

```text
train scheduled
      ↓
passenger has pre-booked taxi
      ↓
booking becomes visible to player
      ↓
player has time to drive to station
      ↓
train arrives
```

---

# 8. Phone UI

Use the existing phone UI if one exists.

Do not create a second phone interface.

Add a notification/incoming booking screen appropriate to the existing UI.

The player should be able to understand the job without opening developer/debug information.

Example information:

```text
PRE-BOOKED TAXI

Passenger
IC57 → Oulu

Arrival
18:42

Pickup
Oulu Railway Station
Taxi Stand

Fare
€8
```

The exact visual design must follow the existing game's UI style.

Do not hard-code "Oulu" or "IC57" into the UI.

All displayed information must come from the booking/train/passenger data.

---

# 9. Accept / reject booking

The player should be able to decide whether to accept the booking.

The exact controls should follow the existing phone/job interaction conventions.

Conceptually:

```text
NEW BOOKING
    ↓
ACCEPT / DECLINE
```

If the player declines:

```text
booking → DECLINED
```

The passenger remains a railway passenger/taxi-demand passenger but is no longer assigned to the player's taxi.

Do not create penalties, reputation effects or financial consequences for declining yet.

Those can be implemented later.

---

# 10. Accepted booking

When the player accepts:

```text
booking → ACCEPTED
```

The booking becomes an active task for the player.

The player should be able to see the relevant pickup information:

```text
Train: IC57
Station: Oulu
Pickup: nearest existing taxi stand
Arrival: 18:42
Fare: €8
```

Use existing task/mission/HUD mechanisms where available.

Do not create an entirely separate mission framework.

---

# 11. Booking and passenger identity

The booking must reference the existing railway passenger ID.

Do NOT create a second passenger object.

The relationship must remain:

```text
TaxiBooking.passenger_id
        ↓
existing railway Passenger
```

This is important for Phase 9.

When the passenger eventually leaves the train, Phase 9 must be able to identify exactly which pedestrian corresponds to the booking.

---

# 12. Booking and taxi stand

The booking must reference the existing station → nearest taxi stand association.

Conceptually:

```text
Passenger
    ↓
destination station
    ↓
nearest existing taxi stand
    ↓
TaxiBooking.pickup_location
```

Do not perform a fresh search for taxi stands every frame.

The booking should retain the resolved stand reference.

---

# 13. Fare

The agreed pre-booking fare is:

```text
€8
```

Store the fare as booking data.

Do not implement dynamic pricing.

Do not charge the player when accepting the booking.

The €8 represents the customer's agreed fare and should eventually be awarded when the trip is successfully completed.

The actual payment/completion logic can be finalized in a later taxi-trip phase.

---

# 14. Booking state machine

Implement a clear state machine.

At minimum, support:

```text
PENDING
    ↓
ACCEPTED
    ↓
TRAIN_ARRIVING
    ↓
PASSENGER_WAITING
```

Also support:

```text
PENDING → DECLINED
```

and:

```text
ACCEPTED → MISSED
```

if the player fails to collect the passenger later.

Phase 8 does not need to implement the final missed-pickup mechanics in detail.

The important requirement is that the booking has explicit state rather than a collection of unrelated booleans.

---

# 15. Train integration

Use the existing railway train state/timetable.

When the booked train approaches the destination station, the booking can transition from:

```text
ACCEPTED
```

to:

```text
TRAIN_ARRIVING
```

When the train actually arrives, the booking can transition to:

```text
PASSENGER_WAITING
```

However, the actual passenger alighting and physical meet & greet belong to Phase 9.

Do not duplicate the railway arrival system.

Do not alter train movement or timetable logic unless strictly necessary to expose an existing event/state.

---

# 16. Multiple bookings

Support multiple active bookings.

Example:

```text
18:20  IC57 → Oulu → €8
18:35  IC274 → Oulu → €8
19:05  IC36 → Oulu → €8
```

Each booking must remain independently associated with:

* passenger
* train instance
* station
* taxi stand
* fare

Do not use a single global "current booking".

---

# 17. Phone notification timing

The booking notification should appear with enough time for the player to react.

Do not spam the phone continuously.

A booking should generate a notification once and then remain accessible through the existing phone UI/task list if such a mechanism exists.

If the project has no persistent notification list, implement only the minimum necessary state to keep accepted/pending bookings visible.

---

# 18. Save/load

Inspect the existing save system.

If the game already persists gameplay state, integrate bookings into it using the existing mechanism.

Do not create a new save system solely for taxi bookings.

If the game currently has no save system, keep booking state runtime-only and document that limitation.

---

# 19. Performance

Do not poll every train/passenger every frame unnecessarily.

Use existing train/passenger state transitions or event mechanisms.

Booking lookup should be efficient.

Do not repeatedly search all passengers to find the booked passenger if a direct passenger ID/reference is available.

Do not perform taxi stand searches during the per-frame update.

---

# 20. Tests

Add tests for:

### Booking creation

A taxi-demand passenger can become a pre-booked passenger.

### Eligibility

A WALK or TRAIN_TRANSFER passenger cannot receive a taxi booking.

### Partial taxi demand

Not every TAXI passenger must become pre-booked.

### Passenger identity

The booking references the existing passenger ID.

### Train identity

The booking references the correct scheduled train instance.

Verify that:

```text
IC57 on date A
```

cannot be confused with:

```text
IC57 on date B
```

### Taxi stand

The booking references the existing nearest taxi stand associated with the destination station.

### Fare

Verify:

```text
fare == €8
```

or the project's equivalent monetary representation.

### Accept

Verify:

```text
PENDING → ACCEPTED
```

### Decline

Verify:

```text
PENDING → DECLINED
```

### Train arrival

Verify the booking follows the existing train state:

```text
ACCEPTED
→ TRAIN_ARRIVING
→ PASSENGER_WAITING
```

### Multiple bookings

Verify that several bookings can coexist without overwriting each other.

### Deterministic generation

Verify that booking generation respects the existing random seed.

### No regression

Run existing railway, passenger and taxi tests.

---

# 21. Do NOT implement Phase 9 yet

This phase must NOT implement:

* passenger identification in the crowd
* special visual marker for the booked passenger
* meet & greet interaction
* passenger entering the taxi
* taxi trip start
* taxi route to destination
* €8 payment completion
* customer dialogue
* customer rating
* tips
* reputation
* penalties for missing the passenger

Phase 8 ends when the booking exists, is visible to the player, can be accepted/declined, follows the booked train, and becomes ready for the Phase 9 meet & greet interaction.

---

# 22. Implementation workflow

Work incrementally:

1. Inspect existing passenger, train, taxi, phone and job systems.
2. Identify the existing passenger identity mechanism.
3. Identify the existing unique train-instance identity.
4. Identify the existing station → nearest taxi stand association from Phase 7.
5. Implement the booking data model.
6. Implement pre-booking generation for a subset of TAXI passengers.
7. Implement the €8 fare.
8. Associate each booking with passenger, train instance, station and existing taxi stand.
9. Implement booking state transitions.
10. Integrate booking notifications with the existing phone UI.
11. Implement accept/decline.
12. Integrate train arrival state.
13. Add tests.
14. Run the existing railway/passenger/taxi test suites.
15. Run a gameplay test with multiple railway trains and multiple bookings.
16. Review the diff and remove unnecessary changes.

---

# Acceptance criteria

Phase 8 is complete when:

* railway taxi-demand passengers can become pre-booked customers
* pre-booking occurs before the train arrives
* the booking references the exact passenger
* the booking references the exact scheduled train instance
* the booking references the destination railway station
* the booking uses the existing nearest taxi stand
* no taxi stands are created or modified
* the booking fare is €8
* the player receives the booking through the existing phone/UI system
* the player can accept or decline the booking
* accepted bookings remain active until the train arrives
* the booking follows the existing railway timetable/train state
* multiple bookings can coexist
* no expensive per-frame polling is introduced
* existing railway/passenger/taxi functionality continues to work
* tests pass
* there is no meaningful FPS regression

At the end, report:

* files changed
* booking data model
* booking generation rules
* train-instance identification
* passenger association
* taxi stand association
* phone UI changes
* booking state machine
* tests executed
* performance impact
* limitations to address in Phase 9

# Phase 8 corrections

Apply the following corrections to the Phase 8 implementation specification.

## 1. Pre-booking must have a ride destination

A pre-booked taxi passenger must have a known **ride destination when the booking is created**.

Do NOT defer destination selection until the passenger is physically picked up.

The booking therefore represents an actual requested taxi journey:

```text
Railway passenger
    ↓
destination railway station
    ↓
existing nearest taxi stand
    ↓
pre-booked taxi
    ↓
ride destination
```

The ride destination is separate from the railway station and taxi stand.

For example:

```text
Passenger arrives at Oulu railway station
    ↓
walks/waits at existing station taxi stand
    ↓
has a pre-booked taxi
    ↓
requested taxi destination = specific destination
```

Inspect the existing taxi/customer destination system first.

If the existing system already has a suitable destination representation, reuse it.

Do NOT create a second destination framework.

The destination must be stored as part of the booking so it remains available after the passenger leaves the train.

---

## 2. Booking must not depend on a physical pedestrian

A `TaxiBooking` is a logical gameplay object and must exist independently of the physical pedestrian entity.

The booking must remain valid when the passenger is:

* still waiting for the train
* represented only as train-manifest data
* inside the train
* outside the currently loaded/viewable world
* temporarily not represented by a pedestrian

The relationship should be:

```text
TaxiBooking
    ↓
passenger_id
    ↓
Railway Passenger
```

and separately:

```text
Railway Passenger
    ↓
physical pedestrian entity
```

when the existing railway passenger lifecycle creates one.

Do NOT create a new pedestrian specifically for the booking.

Do NOT require a pedestrian entity to exist when the booking is generated.

This is especially important because Phase 7 already established that out-of-view railway arrivals can exist as passenger data without a physical pedestrian.

When the passenger eventually alights and becomes a pedestrian, the existing passenger identity must allow Phase 9 to identify that pedestrian as the booked customer.

---

## 3. €8 is an additional pre-booking fee

The €8 amount is **not the taxi's normal starting fare**.

It is the customer's agreed **additional pre-booking fee**, charged on top of the normal taxi initial/startup fare.

Use terminology that makes this distinction explicit.

Prefer an existing project-compatible field such as:

```python
pre_booking_fee = 8.0
```

rather than:

```python
fare = 8.0
```

unless the existing monetary model has a more appropriate equivalent.

The intended pricing model is:

```text
Pre-booking fee       €8
+
Normal initial/startup fare
+
Normal trip fare
```

The €8 must therefore NOT:

* replace the normal taxi starting fare
* include the normal taxi starting fare
* represent the total trip price
* determine the distance/time fare

Phase 8 only needs to store and display the €8 pre-booking fee.

The actual payment calculation can remain part of the later taxi-trip implementation.

---

## 4. Updated conceptual booking model

The conceptual model is therefore:

```text
TaxiBooking
    ├── booking_id
    ├── passenger_id
    ├── train_instance_id
    ├── train_number
    ├── station_id
    ├── taxi_stand_id
    ├── ride_destination
    ├── pre_booking_fee = €8
    └── status
```

Use the project's existing types and naming conventions rather than blindly implementing these exact field names.

The important requirement is that the booking independently contains enough information to answer:

* Which passenger?
* Which exact train occurrence?
* Which railway station?
* Which existing taxi stand?
* Where does the customer want to go?
* What additional pre-booking fee was agreed?
* What is the current booking state?

---

## 5. Updated phone presentation

The phone notification should communicate that €8 is an **additional pre-booking fee**, not the complete taxi fare.

For example:

```text
PRE-BOOKED TAXI

Passenger
IC57 → Oulu

Arrival
18:42

Pickup
Oulu Railway Station
Taxi Stand

Destination
[requested destination]

Pre-booking fee
€8
+ normal taxi fare
```

Use the existing UI style and terminology where appropriate.

Do not hard-code the station, train, passenger or destination.

All values must come from the booking and existing game systems.

---

## 6. Updated Phase 9 handoff

Phase 8 ends with a complete logical booking:

```text
TaxiBooking
    ↓
Passenger #1842
    ↓
IC57 / exact train instance
    ↓
Oulu railway station
    ↓
existing nearest taxi stand
    ↓
requested ride destination
    ↓
additional pre-booking fee €8
```

When the train arrives, Phase 9 can use `passenger_id` to connect the logical booking to the passenger's physical pedestrian representation.

Phase 9 will then implement:

```text
PASSENGER_WAITING
       ↓
identify booked passenger
       ↓
meet & greet
       ↓
passenger enters player's taxi
       ↓
taxi trip starts
```

Do not implement those interactions in Phase 8.
