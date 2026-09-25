# Railway Taxi Phase 10 Bug Fixes – Meet & Greet State and Station Passenger Routing

Work on the existing Railway Taxi Phase 10 implementation in the current repository and branch.

Do **not** redesign the railway passenger or taxi systems. First inspect the existing Phase 9/Phase 10 implementation and reproduce the reported bugs before making changes.

## Bug 1: Meet & Greet prompt and booking information disappear

### Current broken behavior

During a pre-booked railway taxi pickup:

* The game correctly tells the player to press `F` when the taxi driver is near the booked passenger.
* When the player reaches the passenger, the `F` interaction prompt disappears instead of allowing the meet & greet to be completed.
* The passenger can then disappear / become detached from the expected active meet & greet flow.
* The player does not have persistent information about who they are meeting.

This is incorrect.

### Required behavior

Once the player has an active railway taxi booking that has reached the passenger waiting stage, the game must maintain a clear **active meet & greet context** until the meeting is actually completed or the booking is missed.

The UI should continuously communicate:

* passenger name
* originating train
* station / pickup context
* that this is the currently active pre-booked passenger
* what interaction is currently expected

For example, while the booking is active, the UI should communicate something conceptually similar to:

> Meet: Anna Example
> Train: IC 123
> Oulu station
> Press F to greet passenger

Do not hard-code this exact wording. Use the existing localization/UI architecture.

### Important state rule

The booking information and meet & greet UI must **not disappear merely because the player reaches the passenger**.

Reaching the passenger should transition into the actual interaction state.

The expected state flow is approximately:

```text
PASSENGER_WAITING
        ↓
PLAYER_APPROACHING
        ↓
READY_TO_GREET
        ↓
MEET_AND_GREET_COMPLETED
        ↓
PASSENGER_WALKS_WITH_DRIVER_TO_TAXI
        ↓
PASSENGER_IN_TAXI
        ↓
TRIP_ACTIVE
```

Use the repository's existing state names where possible rather than creating unnecessary parallel state machines.

The important semantic rule is:

> The booking remains active until the passenger has actually been met and the passenger and driver have begun the transfer back to the taxi.

### F interaction

When the player is close enough:

* `F` must remain available until the greeting interaction is completed.
* Pressing `F` must explicitly complete the meet & greet.
* The passenger must not disappear when the prompt becomes active.
* The passenger must not be converted into an ordinary taxi customer at this point.
* The booking must remain associated with the same passenger.
* The booking destination and `surcharge_cents` must remain intact.

Do not allow the existing ordinary taxi stand pickup logic to consume the booked passenger.

### Passenger visibility after greeting

After the greeting:

* The passenger must remain physically present.
* The passenger should follow the intended meet-and-greet flow toward the taxi.
* The booking marker should remain meaningful until the passenger has actually entered the taxi.
* Do not immediately remove the passenger entity/data representation just because `MEET_AND_GREET_COMPLETED` occurred.

The passenger should disappear from the station-side pedestrian world only when the existing passenger/taxi state legitimately transfers them into the taxi.

### Meet & Greet marker

Keep the customer clearly identifiable in the crowd.

Use the Phase 10 directional arrow or equivalent existing marker.

The marker must:

* point to the actual booked passenger
* follow the passenger if they move
* remain visible throughout the active meet & greet
* not disappear simply because the player reaches the passenger
* disappear only when the booking no longer requires the station-side passenger marker

Do not restore the old Phase 9 light-blue ring/name marker unless the existing UI architecture genuinely requires it.

### Active booking information

There must be a persistent indication of the currently active booking.

It should remain visible while:

* approaching the passenger
* standing next to the passenger
* greeting them
* walking back toward the taxi
* waiting for the passenger to enter the taxi

It should disappear only when the booking has moved beyond the meet-and-greet stage, or when it becomes `MISSED`/otherwise terminal.

The information should include enough context to avoid ambiguity when several railway passengers exist.

At minimum:

* passenger name
* train number/type if already available from the booking
* pickup station

Do not invent data that does not exist in the booking model.

---

# Bug 2: Railway passengers walk through buildings

### Current broken behavior

Passengers arriving from trains are walking from the railway station toward the taxi stand using direct/straight-line movement.

As a result:

* they walk through buildings
* they do not follow the game's road/path/navigation system
* the visual behavior is clearly incorrect

This affects railway passengers walking to the existing taxi stand and potentially their post-greeting walk back toward the taxi.

### Required behavior

Railway passengers must use the game's existing pedestrian routing/navigation infrastructure wherever such infrastructure already exists.

Do **not** create a completely separate railway passenger pathfinding system.

First inspect the repository for:

* pedestrian navigation
* pedestrian routes
* road/sidewalk graphs
* navigation meshes
* waypoint systems
* existing resident pedestrian routing
* collision-aware pedestrian movement
* spatial pedestrian path systems

Reuse the existing system.

The railway passenger should behave like an ordinary pedestrian whose destination happens to be:

* the existing railway station taxi stand, or
* the taxi/driver meeting point after the meet & greet.

### Critical requirement

Do not solve this by merely adding more collision checks to the existing straight-line walk.

The desired behavior is actual route following.

Conceptually:

```text
Railway station
    ↓
pedestrian navigation graph
    ↓
walkable route
    ↓
existing taxi stand
```

not:

```text
Railway station
    ↓
straight line
    ↓
taxi stand
```

### Preserve existing railway restrictions

Passengers must still:

* never walk onto railway tracks
* not be routed through obviously inaccessible areas
* retain their existing booking/passenger identity
* retain their taxi intent
* retain their booking destination where applicable

If the existing pedestrian navigation system already handles these constraints, use it rather than duplicating the logic.

### Track crossing

The existing Phase 7 behavior included a safety fallback when a straight-line route would cross railway tracks.

After integrating real pedestrian routing, use the navigation system's walkable route instead.

Do not simply remove the track-crossing protection without replacing it with a proper route.

If no valid pedestrian route exists:

* do not send the passenger through buildings
* do not send the passenger onto tracks
* use the existing safe fallback behavior
* log enough diagnostic information to identify why no route was found

Do not create an arbitrary new route through OSM geometry.

---

# Performance requirements

This is a performance-sensitive game.

Do not introduce:

* global per-frame scans of all pedestrians
* a new pathfinding calculation every frame
* repeated route searches while the passenger is walking
* repeated nearest-stand searches
* repeated full-map navigation rebuilds

A route should normally be calculated:

* when the passenger receives a destination, or
* when their current route becomes invalid

Then follow the route incrementally.

If the existing pedestrian system already caches routes or uses navigation state, integrate with that mechanism.

The active booking lookup should remain targeted to the existing booking/passenger relationship.

---

# Reproduce before changing

Before implementation:

1. Inspect the current Phase 10 code.
2. Identify exactly why the `F` prompt disappears.
3. Identify exactly what state transition causes the passenger to disappear or become detached.
4. Identify how the current railway passenger walk is implemented.
5. Identify the existing pedestrian routing/navigation system.
6. Reproduce both bugs if possible.
7. Add focused regression tests before or alongside the fixes.

Do not guess at the cause.

---

# Regression tests

Add tests covering at least:

## Meet & Greet

* active booking retains passenger identity
* active booking retains train information
* active booking retains station information
* meet & greet prompt remains available when player reaches passenger
* pressing `F` completes the greeting
* passenger does not disappear when the prompt becomes active
* passenger remains present after greeting
* passenger remains associated with the booking until entering the taxi
* booking destination is preserved
* `surcharge_cents` is preserved
* marker follows the actual passenger
* marker does not disappear prematurely
* booking information disappears only after the appropriate state transition
* ordinary taxi customers retain their existing pickup behavior

## Passenger routing

* railway passenger receives a pedestrian route to the existing taxi stand
* passenger follows route waypoints/navigation rather than a straight line
* route does not pass through buildings
* route does not pass through railway tracks where the navigation system can avoid them
* passenger reaches the existing taxi stand when a valid route exists
* invalid/unavailable routes use a safe existing fallback
* route is not recalculated every frame
* no global pedestrian scan is introduced

If the repository already has a pedestrian navigation test framework, extend it instead of inventing a parallel test abstraction.

---

# Important implementation constraints

* Do not create new taxi stands.
* Use the existing station-associated taxi stand.
* Do not create a second railway passenger AI system.
* Do not replace the existing taxi customer system.
* Do not change the €8 pre-booking fee semantics.
* Keep `surcharge_cents` separate from the normal taxi startup fare and trip fare.
* Do not change the booked ride destination.
* Do not remove the existing missed-booking logic unless required to fix an identified bug.
* Do not make the passenger automatically board the taxi before the meet & greet.
* Do not make `PASSENGER_MET` happen merely because the player is within pickup distance.
* Do not let ordinary taxi pickup logic bypass the railway booking flow.
* Do not add per-frame global scans.
* Do not perform broad unrelated refactoring.

---

# Validation

After implementation:

1. Run focused railway taxi / station passenger tests.
2. Run the complete test suite.
3. Report any pre-existing failures separately from failures caused by these changes.
4. Perform a real gameplay test if possible.

The gameplay test must verify this complete sequence:

```text
Train arrives
→ passenger leaves train
→ passenger follows walkable pedestrian route
→ passenger reaches existing taxi stand
→ player receives clear booking information
→ arrow identifies the passenger
→ player approaches passenger
→ F remains available
→ player greets passenger
→ passenger remains present
→ passenger and driver proceed together toward taxi
→ passenger enters taxi
→ booking destination remains correct
→ normal taxi trip can begin
```

Also test the failure path:

```text
Train arrives
→ passenger walks using pedestrian route
→ player does not meet passenger
→ booking eventually becomes MISSED
→ passenger is handled by the existing missed-booking behavior
```

At the end, report:

* root cause of the disappearing `F` interaction
* root cause of the passenger walking through buildings
* files changed
* state transitions changed
* navigation system reused
* tests added/updated
* full test result
* any remaining limitations

Do not commit anything unless explicitly asked.
