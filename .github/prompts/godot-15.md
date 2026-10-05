# Godot-15: Complete the Static World

Continue the Godot migration from the current repository state.

`godot-14` is complete and pushed. Do not create or push a Git tag. You may create commits and push them to the remote.

The next phase is the **remaining static world**, before navigation.

## Goal

Bring the remaining static, non-navigational world scenery from Pygame to Godot while preserving the established architecture:

* The server owns authoritative world/game state.
* Godot has no physics.
* Godot renders server state.
* Static geometry belongs to map chunks where appropriate.
* Do not introduce client-side collision or gameplay simulation.

The previous phases already added:

* trees
* construction fences
* bollards
* fallen trees
* knocked bollards
* knocked street lamps
* server calendar/day-night state
* global night tint

Now complete the remaining static-world rendering that belongs before navigation.

## First: inspect the existing implementation

Before making changes:

* Inspect the current Pygame static-world rendering.
* Inspect the server map/world data structures.
* Inspect `map_chunks.py` and the current map-chunk protocol.
* Inspect Godot `map_chunk.gd`, `map_layer.gd`, `entity_layer.gd`, and `main.gd`.
* Inspect all existing static-world tests.
* Inspect `godot-pygame-rendering-parity.md`.
* Identify every remaining static-world parity item and classify it as:

  * static geometry/data that should be sent in chunks
  * dynamic state already sent by the server
  * visual-only information that can be derived client-side
  * intentionally deferred

Do not implement navigation in this phase.

## 1. Railings, walls and hedges

Implement the remaining drawing-only static objects:

* railings
* walls
* hedges

These must be rendered from authoritative map/world data.

Do not add collision shapes.

The Pygame collision architecture explicitly does not treat these objects as collidable, so Godot must not invent collision behaviour for them.

Preserve:

* geometry
* placement
* orientation
* visual dimensions
* colour/style
* chunk ownership

A long object must not accidentally be duplicated at chunk boundaries.

Follow the existing one-object-one-chunk rule.

## 2. Decorative scenery

Implement the remaining static decorative objects that are currently missing, including where applicable:

* benches
* bins
* statues
* other equivalent decorative scenery already present in the Pygame world

Do not blindly implement every missing parity entry.

Inspect the actual Pygame implementation and repository data first.

Objects that do not affect gameplay should remain purely visual.

Do not create fake gameplay interactions for them.

## 3. Street lamps

Complete the static street-lamp representation.

The server already sends knocked street-lamp state from earlier phases.

Add the standing street-lamp rendering while preserving the existing knocked-lamp behaviour.

Night behaviour must integrate with the `godot-14` calendar/day-night implementation.

At night:

* standing lamps should appear lit if Pygame shows them lit
* knocked lamps should behave as Pygame's broken lamps
* the lamp head should use the appropriate dark/broken appearance

Do not implement expensive per-lamp dynamic lighting unless the existing Pygame design requires it.

Prefer a lightweight rendering approach appropriate for thousands of static objects.

## 4. Headlights

Implement the remaining Godot headlight presentation if it belongs to the static/night-world rendering layer.

Inspect exactly how Pygame renders headlights.

The server remains authoritative for vehicle state and position.

Godot should only render the visual result.

Do not introduce client-side vehicle physics.

If headlights depend on vehicle orientation, use the authoritative/interpolated vehicle orientation already available to Godot.

Do not create a second movement calculation.

## 5. Pedestrian reflectors

Implement pedestrian reflector rendering if the Pygame world contains them as part of the night presentation.

Use the existing pedestrian/entity state.

Do not add gameplay logic.

Reflectors should become visible according to the same day/night state used elsewhere rather than using a separate hour-based approximation.

## 6. Lit windows

Investigate the existing Pygame implementation of lit building windows.

If the required window information is not currently available to Godot:

* add the minimum required server/map data
* include it in the appropriate static map representation
* keep the data compact

Do not send a complete high-resolution building texture or unnecessary per-frame data.

If buildings already contain enough information to derive the windows deterministically, prefer deriving the visual representation in Godot rather than transmitting redundant data.

The result should match the visual intent of Pygame.

## 7. Seasonal groundwork

The server now has the authoritative calendar and season.

Inspect existing Pygame seasonal rendering and identify what static-world data Godot needs.

Implement only seasonal static-world rendering that naturally belongs in this phase.

In particular, consider:

* seasonal tree colours
* snow cover
* ice
* other existing seasonal scenery

Do not invent new weather mechanics.

If snow depth is already authoritative or available from the server, expose only the required value.

If additional server state is genuinely required, add it cleanly to the protocol.

Do not make Godot simulate snow accumulation.

## 8. Do not mix in unrelated deferred work

Keep these items deferred unless they are strictly required by the static-world implementation:

* fuel pumps hidden under solid canopies
* fuel-price HUD
* traffic-light phase range behaviour
* navigation
* pathfinding
* pedestrian navigation
* vehicle routing
* airport work
* aircraft schedules
* train/navigation work

Do not turn this into a navigation phase.

## 9. Rendering architecture

Respect the current chunk architecture.

Static scenery should:

* belong to exactly one map chunk
* be created/updated when the chunk loads
* disappear when the chunk unloads
* not be regenerated every frame
* not cause unrelated chunks to redraw
* not be rebuilt merely because the clock changes

Dynamic state such as knocked objects must continue to be handled separately from static geometry where appropriate.

Preserve the existing rule that a chunk redraws only when its relevant visual state changes.

## 10. Performance

Performance is a hard requirement.

The current Godot selftest is approximately:

* 145 FPS
* taxi exactly centred
* no backward rendering steps
* approximately 69–71 MiB memory depending on run

Do not accept a substantial regression.

Pay particular attention to:

* thousands of trees
* street lamps
* hedges
* walls
* railings
* decorative objects
* building windows

Avoid:

* one heavyweight Godot node per tiny decorative object if unnecessary
* per-frame iteration over every static object
* rebuilding static geometry every tick
* per-object dynamic lights
* repeated allocations
* unnecessary protocol duplication

Use the existing chunk/batching architecture where possible.

Measure before and after.

## 11. Tests

### Python

Add tests for:

* correct chunk assignment
* no duplication at chunk boundaries
* serialization of any new static-world data
* seasonal/static-world state where applicable
* preservation of existing knocked-object state

Keep tests deterministic.

### Godot

Extend the existing test suite for:

* railing rendering
* wall rendering
* hedge rendering
* decorative scenery
* standing street lamps
* knocked street lamps
* night lamp appearance
* headlights
* pedestrian reflectors
* lit windows if implemented
* seasonal rendering if implemented
* chunk load/unload
* no duplicate objects
* no unnecessary redraws

Do not weaken existing tests.

## 12. Real-server verification

Use the real Oulu server/client path.

Verify:

1. Static objects appear in the correct locations.
2. Chunk unload/reload reproduces the same scene.
3. No static objects duplicate at chunk boundaries.
4. A previously knocked street lamp remains knocked after reload.
5. Night rendering matches the server's calendar state.
6. Standing and broken lamps have the correct appearance.
7. Existing godot-13 and godot-14 behaviour remains intact.
8. Seasonal data, if implemented, comes from the server rather than a client-local clock.
9. No client-side collision has been introduced.

Use screenshots/pixel comparison where that is already part of the project's verification workflow.

## 13. The unexplained Python test failure

`godot-14` had one isolated Pygame screenshot-comparison failure that did not recur during five subsequent complete runs.

Do not change unrelated rendering code merely to address that historical failure.

If the same test fails during this phase:

* investigate it
* determine whether this phase caused it
* fix it if caused by your changes
* otherwise document the evidence rather than masking the failure

Do not weaken screenshot comparisons or tests just to obtain a green run.

## 14. Documentation

Update:

* `godot-pygame-rendering-parity.md`
* `godot-client.md`

Record:

* newly implemented static-world objects
* protocol additions
* server/client responsibilities
* seasonal data if added
* night-rendering behaviour
* performance results
* remaining static-world gaps

Update the parity table accurately.

Do not mark navigation as complete.

## 15. Acceptance criteria

The phase is complete only when:

* Remaining relevant static-world scenery is rendered in Godot.
* Railings, walls and hedges are represented without client-side collision.
* Decorative scenery is rendered where supported by the existing game.
* Standing street lamps are rendered.
* Knocked street lamps retain their existing server-authoritative behaviour.
* Night rendering integrates with the godot-14 calendar.
* Headlights/reflectors/lit windows are implemented where supported by the existing Pygame design and data architecture.
* Seasonal static-world rendering is implemented where appropriate without creating client-side simulation.
* Chunk ownership remains deterministic and duplicate-free.
* Chunk unload/reload preserves the correct visual state.
* Python tests pass.
* Godot tests pass.
* Real-server Oulu verification succeeds.
* Performance remains close to the existing baseline.
* Documentation is updated.
* Changes are committed and pushed.
* No Git tag is created or pushed.

At the end, provide a concise report containing:

1. Files changed
2. Protocol changes
3. Server changes
4. Godot changes
5. Static-world items completed
6. Tests
7. Real-server verification
8. Performance measurements
9. Updated parity counts
10. Remaining gaps
11. Commit hashes

Do not stop at an architectural proposal. Implement the phase fully.
