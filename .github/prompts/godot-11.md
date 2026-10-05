# Godot Parity Phase 2 — Meet-and-Greet, Road Information and Server State

## Objective

Implement the next Godot parity phase based on the completed godot-10 re-audit.

The audit explicitly recommends this as the next phase:

> Phase 2 — per-tick values the server already has.

This phase must close the following parity gaps:

1. Meet-and-greet booking state
2. Meet-and-greet panel
3. Booked rail passenger arrow
4. Current road name
5. Current speed limit
6. Speed-camera notice / flash
7. Lightning intensity / precipitation state required by the existing Godot weather rendering

The audit confirms that these values already exist in the server/simulation. The goal is therefore to expose the required state through the existing protocol and render it in Godot.

Do not redesign the simulation architecture.

---

# 1. Source of Truth

Use the current parity audit as the authoritative starting point:

```text
docs/architecture/godot-pygame-rendering-parity.md
```

The relevant godot-10 findings are:

* Meet booking exists in `taxi_mgr.meet_booking()` / `meet_context()`
* Only `current_passenger.rail_booking` is currently sent
* `current_way` contains `name` and `speed_limit_kmh`
* Speed-camera notice exists in `taxi_mgr`
* Lightning state exists in `weather.lightning_intensity` / `lightning_event_id`
* Rain precipitation state exists in the server weather state
* `sim_time` is already sent
* Navigation route is a separate architectural task and must NOT be implemented here

Do not contradict the audit without verifying the actual current code.

---

# 2. Strict Scope

## Implement

### Protocol/state

Add only the smallest state fields required for:

* meet-and-greet
* booked passenger arrow
* current road name
* current speed limit
* speed-camera notification
* lightning flash
* precipitation/rain intensity where required by the existing Godot weather renderer

### Godot rendering/UI

Implement:

* meet-and-greet panel
* booked passenger arrow
* road name / speed-limit HUD
* speed-camera notice/flash
* lightning flash
* rain intensity usage if required

### Tests

Add deterministic tests for the new protocol/state and rendering logic where practical.

---

# 3. Do NOT Implement

This phase must NOT include:

* navigation route planning
* server route ownership
* route protocol messages
* static chunk format changes
* traffic-light objects
* taxi stands
* fuel stations
* roadworks
* trees
* scenery objects
* fences
* buildings
* day/night calendar
* seasons
* temperature
* menus
* click picking
* tire tracks
* speech subtitles
* binary protocol
* camera changes
* vehicle movement changes
* interpolation changes
* performance refactoring

Do not expand the task into the next parity phases.

---

# 4. Preserve the Stability Fixes

The current camera and vehicle implementation is considered stable.

The following behavior is protected:

* vehicle does not jitter
* background/world does not jitter
* camera follows the same interpolated sample as entities
* vehicle input release works correctly
* held-key state is owned by the client
* `StateBuffer` interpolation remains unchanged
* camera update remains synchronized with the entity render sample

Do not modify:

```text
main.gd camera update
entity interpolation
StateBuffer.blend
drive_input.gd
```

unless absolutely required to expose the new UI state.

If any of these files must be touched, explain why before making the change and keep the modification strictly unrelated to movement/camera behavior.

---

# 5. First Inspect the Existing Pygame Implementation

Before coding, inspect the actual Pygame implementations for:

```text
draw_meet_panel
draw_booked_passenger_arrow
draw_hud
speed_camera_notice
lightning
rain rendering
```

Identify:

* exact displayed information
* conditions for visibility
* colours/styles
* timing
* animation
* positioning
* text
* distance/bearing calculations
* booking states

Do not invent UI semantics.

The Godot implementation should reproduce the gameplay meaning of the Pygame version while fitting the existing Godot UI architecture.

---

# 6. Meet-and-Greet State

Inspect:

```text
taxi_mgr.meet_booking()
taxi_mgr.meet_context()
```

Determine the complete booking state needed by Pygame.

At minimum investigate:

* pedestrian ID
* passenger/customer identity
* train
* station
* platform
* booking step/state
* passenger position
* whether the passenger is waiting
* whether the passenger is walking to the taxi
* whether the passenger has boarded
* any existing deadline/timing information used by the panel

Do not blindly expose the entire internal booking object.

Expose only the data required by the Godot client.

---

# 7. Protocol Design

Prefer extending the existing per-tick state rather than creating a new protocol mechanism.

Follow the existing protocol conventions.

For example, conceptually:

```text
state
 ├── taxi
 ├── player
 ├── current_passenger
 ├── current_way
 ├── meet_booking / meet_context
 ├── speed_camera
 └── weather
```

Use the project's actual naming conventions instead of blindly copying this example.

Important:

* preserve backward compatibility where practical
* provide sensible defaults for missing/old fields
* do not duplicate data unnecessarily
* do not serialize large objects every tick when a small identifier/state is sufficient

---

# 8. Current Road Name and Speed Limit

The server already maintains:

```text
current_way.name
current_way.speed_limit_kmh
```

Expose the required values in the existing state.

Godot should then display:

* current road name
* current speed limit

according to the Pygame HUD semantics.

Handle:

* no current way
* unnamed roads
* missing/zero speed limit
* transitions between roads

Do not calculate the speed limit independently in Godot.

The server is authoritative.

---

# 9. Speed-Camera Notice

Inspect the existing Pygame speed-camera notification behavior.

Determine:

* what event triggers it
* what message is displayed
* how long it remains visible
* whether a flash effect is separate from the text
* whether it has an event ID/timestamp

Expose the minimum state required.

Do not make Godot infer the event from distance to speed cameras.

The server/taxi simulation remains authoritative.

---

# 10. Lightning and Precipitation

The audit identified:

```text
weather.lightning_intensity
weather.lightning_event_id
weather.is_precipitating
weather.rain_particles
```

Inspect their exact current semantics.

Expose only the fields necessary for the existing Godot renderer.

### Lightning

Godot should react to the server event/state.

Do not generate an independent lightning event in Godot.

Avoid replaying the same lightning event every frame.

Use the event ID or equivalent existing mechanism if that is how the server distinguishes events.

### Rain intensity

If the existing Godot weather renderer already supports rain/snow particles based on `weather_type`, connect the available precipitation/intensity state without redesigning the particle system.

Do not implement a new weather architecture in this phase.

---

# 11. Meet-and-Greet Panel

Implement the Godot equivalent of:

```text
draw_meet_panel
```

The panel must only appear when the corresponding booking state requires it.

Verify the actual Pygame state machine.

Do not simply display a panel whenever `rail_booking == true`.

The panel should reflect the current booking step.

Preserve the existing Godot HUD/phone visual architecture.

Do not create a completely separate UI framework.

---

# 12. Booked Passenger Arrow

Implement the equivalent of:

```text
draw_booked_passenger_arrow
```

The arrow should point toward the booked passenger using the authoritative passenger position/state.

Reuse existing Godot navigation/target-arrow infrastructure where appropriate.

Do not implement route planning.

The arrow is a direct directional indicator, not a route.

Handle:

* passenger visible on screen
* passenger off screen
* passenger no longer valid
* booking completed/cancelled

Avoid showing stale arrows.

---

# 13. HUD Integration

Integrate road information without disturbing the existing:

* speed
* money
* fare
* fuel
* rage
* trip
* odometer
* water
* notifications

Do not redesign the entire HUD.

Prefer the smallest UI change consistent with the Pygame behavior.

---

# 14. Tests

Add deterministic tests for:

## Meet booking

Test at least:

* booking absent
* booking active
* each relevant booking step
* passenger available
* passenger no longer available
* boarding/completion state

## Road information

Test:

* named road
* unnamed road
* valid speed limit
* missing speed limit

## Speed camera

Test:

* no notification
* notification active
* notification expiration/event change

## Lightning

Test:

* no lightning
* new lightning event
* same event does not retrigger continuously

## Weather

Test the state translation used by Godot.

Avoid screenshot-based tests.

Avoid real-time timing tests where a deterministic state test can be used instead.

---

# 15. Performance

This is per-tick state, so keep the payload small.

Do not send:

* full objects
* complete train schedules
* static world geometry
* large passenger structures

Prefer compact state.

The audit specifically notes that nearby traffic-light phases can later be scoped to a radius; do not implement traffic lights in this phase.

Measure nothing unless necessary to validate that the added state is negligible.

---

# 16. Validation

Run:

```bash
make godot-test
make godot-selftest
make audio-check
```

Also run the relevant Python tests.

The existing baseline from the audit was:

```text
make godot-test: 108 checks, PASS
make godot-selftest: PASS
make audio-check: PASS
Python: 1543 passed with tests/test_packaging.py excluded on Python 3.10
```

Do not treat the Python 3.10 `tomllib` issue as caused by this phase.

If Python tests fail for an unrelated pre-existing reason, report it clearly.

---

# 17. Manual Verification

Run the actual Godot game against the real server.

Verify:

### Meet-and-greet

* create/accept a meet-and-greet booking
* panel appears at the correct state
* passenger arrow appears
* arrow points to the correct passenger
* passenger state changes correctly
* boarding removes the appropriate UI
* completed/cancelled booking does not leave stale UI

### Road information

Drive across several roads.

Verify:

* road name changes
* speed limit changes
* unnamed roads behave correctly
* no visible flicker

### Speed camera

Trigger a speed-camera event if practical.

Verify:

* notice appears
* flash appears if applicable
* notice disappears correctly
* event is not repeated every frame

### Weather

Test precipitation.

Verify:

* rain/snow state follows the server
* intensity does not create duplicated effects

Test lightning if reproducible.

### Stability

During all of the above verify:

* vehicle remains stable
* background remains stable
* camera remains stable
* no regression of accelerator release
* no interpolation jitter

---

# 18. Documentation

Update:

```text
docs/architecture/godot-pygame-rendering-parity.md
```

Mark only the features actually implemented as complete/partial.

Update the godot-10 roadmap/status section so that the document remains the canonical current parity status.

Do not rewrite the entire audit unnecessarily.

Record any deliberate deviations as:

```text
different by design
```

where appropriate.

---

# 19. Git

Create focused commits.

Prefer:

1. protocol/server state
2. Godot UI/rendering
3. tests/documentation

However, if the repository's existing workflow favors a single focused commit for this phase, use one commit.

Push the branch to the remote if permitted by the repository workflow.

**Do not create or push Git tags.**

Do not include unrelated changes.

---

# 20. Final Report

Report:

## Implemented

List every feature completed.

## Protocol changes

List every new state field and its purpose.

## Godot changes

List the affected files and UI/rendering changes.

## Tests

```text
make godot-test: PASS/FAIL
make godot-selftest: PASS/FAIL
make audio-check: PASS/FAIL
Python tests: PASS/FAIL/SKIPPED
```

## Manual verification

Report the actual scenarios tested.

## Parity status

Give the updated:

```text
complete
partial
missing
different by design
debug-only
not applicable
```

counts.

## Remaining roadmap

Do not redesign the roadmap.

State which existing next phase should follow.

The likely next phases remain:

1. static gameplay points in chunks
2. collision-relevant static world
3. server calendar/day-night
4. remaining static world
5. navigation architecture

Only change this ordering if the actual implementation reveals a concrete reason.

---

# Final Constraints

This is **Godot parity Phase 2**.

The goal is to expose and render server state that already exists.

Do not solve unrelated parity gaps.

Do not implement navigation.

Do not add static chunk data.

Do not change camera behavior.

Do not change vehicle movement or interpolation.

Do not change the stable jitter fix.

Keep the implementation small, deterministic, testable, and consistent with the existing server-authoritative architecture.
