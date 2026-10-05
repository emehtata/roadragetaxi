# Godot-14: Server Calendar and Day/Night State

Continue the Godot migration from the current repository state.

The previous phase, `godot-13`, is complete and pushed. Do not create or push a Git tag. You may create commits and push them to the remote.

## Goal

Implement the server-authoritative game calendar and day/night state needed by the Godot client.

This phase is deliberately limited to:

1. A server-side calendar/time-of-day representation suitable for both simulation and rendering.
2. Protocol support for sending the current calendar/day-night state to Godot.
3. Godot rendering of the resulting daylight/night state.
4. Tests and documentation.

Do **not** implement the remaining static-world objects, navigation, traffic-light range changes, fuel-price HUD, or fuel-pump rendering in this phase.

## Important architecture rule

The server remains authoritative.

Godot has no physics and must not independently simulate gameplay state. If the server already has a source of truth for game time, calendar, weather, lighting or related state, reuse it instead of introducing a second clock.

Godot should derive only presentation details that are purely visual from the authoritative state received from the server.

Do not introduce a client-side gameplay clock that can drift away from the server.

## First: inspect the existing implementation

Before changing anything:

* Inspect the current server game-time/calendar implementation.
* Inspect how ticks/state snapshots are constructed.
* Inspect `src/theroadragetrip/protocol.py`.
* Inspect `godot/main.gd`.
* Inspect the current Godot map/chunk rendering code.
* Inspect all existing tests related to time, weather, rendering and protocol state.
* Inspect `godot-pygame-rendering-parity.md` and `godot-client.md`.
* Search the repository for existing concepts such as:

  * game time
  * calendar
  * day/night
  * sunrise
  * sunset
  * lighting
  * date
  * hour
  * minute
  * seasonal rendering

Do not invent a parallel implementation if the server already contains the required concepts.

## 1. Define the authoritative calendar state

Establish exactly what information the Godot client needs from the server.

Prefer a compact authoritative representation based on the existing server game clock.

At minimum, Godot must be able to determine:

* current in-game date/calendar position
* current in-game time
* whether it is currently daytime or nighttime
* enough information to render a smooth transition around dawn and dusk if the existing game design supports such transitions

Do not send redundant data merely because it is convenient.

If the server already has a canonical game-time value from which the above can be derived, use that canonical value.

Do not create a second independently advancing clock.

## 2. Protocol changes

Add the minimum required calendar/day-night state to the existing server state protocol.

Follow the existing protocol style and backwards-compatibility conventions.

Older clients should continue to be able to ignore the new fields.

Avoid putting large or frequently changing data into map chunks.

The calendar state is global state, not chunk data.

Document:

* field names
* units
* valid ranges
* whether values are authoritative
* update frequency
* how Godot should interpret them

Do not use ambiguous fields such as `time` if the unit or meaning is unclear.

## 3. Server implementation

If the server already has the required calendar/time state:

* expose it through the protocol
* do not rewrite the existing simulation clock unnecessarily
* do not alter gameplay timing unless required for correctness

If day/night is currently derived somewhere else, consolidate the authoritative calculation rather than duplicating it.

The server should determine the authoritative day/night state.

If the existing game uses a fixed or configurable relationship between real time and game time, preserve it.

Do not silently change the game's time scale.

## 4. Godot day/night rendering

Implement the Godot visual representation of the server's day/night state.

The objective is visual parity with the current Pygame implementation, not a new lighting system.

Inspect the existing Pygame rendering carefully before implementing this.

The Godot implementation should:

* clearly distinguish daytime from nighttime
* preserve visibility of gameplay-critical objects at night
* transition smoothly if the Pygame implementation transitions smoothly
* avoid per-frame expensive work when the visual state has not changed
* not modify camera behaviour
* not modify interpolation
* not modify input
* not introduce physics

If the Pygame implementation uses a tint/overlay or another simple mechanism, reproduce its visual intent rather than building an unnecessarily complex Godot lighting architecture.

Do not add thousands of individual lights just to imitate a global day/night effect.

## 5. Calendar-dependent presentation

If the existing game calendar already affects visual presentation, connect that existing authoritative information to Godot where appropriate.

Examples may include:

* seasonal appearance
* daylight duration
* night duration

However, do not implement the unfinished seasonal tree colours from godot-13 unless the existing calendar implementation already makes them trivial to support.

The following godot-13 tree features remain intentionally deferred:

* tree shake when hit
* falling leaves
* wind lean
* seasonal tree colours

Do not expand this phase into a tree-rendering phase.

## 6. Performance requirements

The Godot client must remain lightweight.

Avoid:

* rebuilding the whole map every tick
* redrawing static chunks every tick
* allocating large temporary arrays every frame
* per-object lighting calculations for thousands of objects
* unnecessary scene-tree churn

A global day/night effect should preferably be represented by a small number of rendering operations.

Preserve the current selftest performance baseline.

The existing selftest is approximately 145 FPS. Do not accept a meaningful regression merely because day/night rendering was added.

If performance changes, measure it and report:

* FPS
* frame-time behaviour
* memory
* startup cost if affected

## 7. Tests

### Python tests

Add or update tests for:

* calendar state generation
* day/night state generation
* protocol serialization
* boundary conditions around day/night transitions
* backwards-compatible protocol behaviour

Use the real server clock/calendar implementation.

Do not write tests against duplicated test-only time logic.

### Godot tests

Add tests covering:

* receiving the calendar state
* correct interpretation of day/night state
* daytime rendering
* nighttime rendering
* transition behaviour if applicable
* no unnecessary full-map redraw caused by a time update
* state updates after reconnect/reset if the protocol supports those paths

Keep the tests deterministic.

Do not use real wall-clock time in tests.

## 8. Real-server verification

After implementation, run the real Oulu server/client path.

Verify that:

1. Godot receives the server's current calendar/time state.
2. The displayed day/night state matches the server.
3. Changing the server/game time across the day/night boundary changes Godot correctly.
4. Reconnecting or reloading does not reset Godot to a client-local time.
5. Existing map chunks continue to behave exactly as before.
6. Object state from godot-13 remains intact across chunk unload/reload.

If there is an existing way to accelerate or manipulate game time for testing, use that rather than modifying production behaviour.

## 9. Do not fix unrelated deferred issues

The following remain deliberately deferred from godot-12:

* fuel pumps hidden under the solid canopy
* fuel-price HUD
* traffic-light phases only sent within 600 m

Do not solve these in this phase.

Also do not implement:

* railings
* walls
* hedges
* benches
* bins
* statues
* other missing scenery
* navigation
* airport/aircraft work
* tree hit animation
* seasonal tree colours

Those belong to later phases.

## 10. Documentation

Update:

* `godot-pygame-rendering-parity.md`
* `godot-client.md`

Record:

* the new authoritative calendar/day-night state
* protocol fields
* server/client responsibilities
* rendering approach
* known limitations
* tests
* performance measurements

Update the parity table accurately.

Do not mark unrelated partial or missing items as complete.

## 11. Acceptance criteria

The phase is complete only when:

* The server has one authoritative calendar/time source.
* Godot receives the required calendar/day/night state.
* Godot does not maintain an independent gameplay clock.
* Day/night rendering matches the existing Pygame behaviour closely.
* Transitions are correct and deterministic.
* Existing godot-13 static-object state remains correct.
* Python tests pass.
* Godot tests pass.
* Real-server Oulu verification succeeds.
* No significant performance regression is introduced.
* Documentation is updated.
* Changes are committed and pushed.
* No Git tag is created or pushed.

At the end, provide a concise report containing:

1. Files changed
2. Protocol changes
3. Server changes
4. Godot changes
5. Tests
6. Real-server verification
7. Performance measurements
8. Updated parity counts
9. Remaining gaps
10. Commit hashes

Do not stop at an architectural proposal. Implement the phase fully.
