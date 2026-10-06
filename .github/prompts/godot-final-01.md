# Godot Parity Phase 1 — Refueling

## Objective

Implement the missing **refueling gameplay feature** identified as P0 in the current Godot/Pygame Parity Audit 2.

The current Godot game must gain functional fuel-station refueling while preserving the already working vehicle, camera, rendering, networking, and 3D building systems.

This is a focused feature implementation. Do not combine it with unrelated parity work.

---

## 1. Read the current implementation first

Before changing code, inspect the repository and the current implementation of:

* the Pygame refueling/fuel-station implementation
* the current Godot fuel state and HUD
* vehicle fuel consumption
* fuel-station/world data
* player interaction/input handling
* client/server protocol
* server-side authoritative vehicle state
* Godot rendering of fuel stations
* existing tests related to fuel, vehicles, interactions, and stations

Use the current repository as the source of truth.

Do not assume that the old Pygame implementation maps directly to the Godot architecture.

Do not invent protocol fields, server endpoints, node names, scene names, or configuration variables.

---

## 2. Preserve the current Godot architecture

The current game architecture is:

* Godot client
* existing Python/server gameplay architecture
* 2D/top-down gameplay
* lightweight 3D building layer
* authoritative gameplay state from the existing server
* existing network/protocol model

Do NOT:

* introduce a new game architecture
* migrate gameplay logic into the 3D building layer
* convert the game to full 3D
* introduce BIN map technology
* replace the existing networking model
* rewrite the vehicle system
* modify the camera system unless absolutely required for refueling UI
* modify vehicle movement/physics
* modify the working camera/background jitter fixes

The vehicle and camera are currently stable. Treat them as protected systems.

---

## 3. Establish exact Pygame behaviour

Trace the old Pygame implementation and document what refueling actually does.

Determine:

* how fuel stations are represented
* how a station is detected
* what proximity/interaction rules are used
* whether the vehicle must be stopped
* how refueling is started
* whether the player explicitly interacts or refueling is automatic
* how fuel amount changes
* whether fuel is restored gradually or instantly
* how fuel cost is calculated
* how money/balance is affected
* what happens if the player cannot afford the fuel
* what happens when the tank is already full
* whether there is any refueling UI
* whether there are sounds
* whether there are messages/prompts
* what state is authoritative
* what edge cases are handled

Do not redesign these rules.

The goal is behavioural parity with the existing game unless the current Godot architecture requires a technically different implementation.

---

## 4. Trace the complete Godot data flow

Follow the complete path:

```text
player input
    ↓
Godot client
    ↓
existing interaction/request mechanism
    ↓
server
    ↓
authoritative fuel / money state
    ↓
network state
    ↓
Godot client
    ↓
fuel HUD / interaction UI / feedback
```

If the existing protocol already contains sufficient information, reuse it.

If a protocol addition is genuinely required:

1. identify the exact missing field/message
2. implement the smallest possible protocol addition
3. keep it backward-compatible where practical
4. add tests for serialization/deserialization
5. update the relevant protocol documentation

Do not add speculative protocol fields.

---

## 5. Implement refueling

Implement the complete missing refueling feature.

The implementation should cover, as applicable to the existing Pygame behaviour:

* fuel-station interaction
* correct proximity detection
* correct vehicle/station relationship
* refueling action
* authoritative fuel increase
* fuel capacity handling
* fuel cost handling
* player money/balance handling
* inability to refuel when requirements are not met
* full-tank handling
* appropriate user feedback
* appropriate audio feedback if the existing audio system supports it
* correct HUD updates

Use the existing game systems wherever possible.

Avoid creating parallel implementations of fuel, money, interaction, or vehicle state.

---

## 6. Rendering and UI

The existing fuel HUD already works.

Do not replace it.

Only add the UI required to make refueling understandable and usable.

Examples of potentially required UI:

* refueling prompt
* refueling status
* fuel price/cost
* insufficient-money feedback
* tank-full feedback

Only implement elements that are supported by the existing Pygame behaviour or clearly required by the current Godot implementation.

Do not add unnecessary UI polish in this phase.

---

## 7. Audio

The Parity Audit identified audio gaps separately.

Do not turn this task into a general audio migration.

If the existing refueling implementation has a corresponding audio event and the current Godot audio system already has the required asset/event infrastructure, wire it up.

If an audio asset is missing, document that fact rather than generating unrelated audio assets as part of this task.

Do not redesign the audio architecture.

---

## 8. Performance requirements

Refueling must have negligible impact on normal gameplay performance.

In particular:

* do not add per-frame expensive searches through all fuel stations
* use the existing spatial/world lookup mechanisms
* do not introduce polling loops that scale with the total number of stations
* do not add unnecessary allocations every frame
* do not modify the rendering pipeline
* do not modify the 3D building renderer
* do not modify camera behaviour

Interaction detection should be efficient and consistent with existing world/entity lookup patterns.

---

## 9. Tests

Add deterministic regression tests for the new behaviour.

At minimum, cover the cases that exist in the current game rules:

1. vehicle can refuel at a valid fuel station
2. fuel increases correctly
3. fuel cannot exceed tank capacity
4. refueling from a full tank behaves correctly
5. fuel cost is calculated correctly
6. money/balance changes correctly
7. insufficient money is handled correctly
8. invalid/out-of-range interaction is rejected
9. authoritative server state is correct after refueling
10. Godot receives and displays the resulting fuel state correctly

If the current architecture makes some of these tests belong in a different layer, place them at the appropriate layer rather than creating artificial UI tests.

Do not weaken existing tests.

---

## 10. Regression protection

The following existing behaviour must remain unchanged:

* vehicle acceleration/braking
* accelerator release
* vehicle transform stability
* vehicle rendering
* camera following
* background rendering stability
* camera/background jitter fixes
* fuel consumption while driving
* existing fuel HUD
* existing 3D building rendering
* 3D building camera alignment
* day/night rendering
* existing networking behaviour

If any regression appears, fix the regression before considering this phase complete.

Do not work around regressions by adding visual hacks.

---

## 11. Validation

Run the relevant test suites.

At minimum:

```bash
make godot-test
make godot-selftest
make audio-check
```

Run the relevant Python/server tests as well.

If there are known unrelated failures, distinguish them clearly from failures introduced by this work.

Also perform a manual gameplay validation of:

1. drive to a fuel station
2. approach the station
3. perform the expected interaction
4. refuel
5. verify fuel HUD
6. verify money/cost
7. drive away
8. verify normal fuel consumption continues
9. repeat with a nearly empty tank
10. test full tank
11. test insufficient money
12. test leaving the station before/without refueling

Verify normal driving and camera behaviour after the test.

---

## 12. Documentation

Update the relevant parity documentation to mark refueling as implemented.

Do not rewrite the entire parity audit.

Record:

* implementation status
* important architecture/protocol changes
* test coverage
* any intentionally deferred behaviour

If the implementation differs from Pygame because of an existing Godot architectural constraint, document the difference explicitly.

---

## 13. Scope control

This phase is ONLY:

> P0 — Refueling

Do NOT implement the other Parity Audit 2 items yet, including:

* navigation route calculation/display
* live taximeter/fare-distance/happiness
* road rage
* career city summary
* rain/snow particles
* score
* speech/subtitles
* station announcements
* next-train panel
* speed limiter/red-light assist
* lane assist
* manual respawn
* historical weather
* fuel price as a separate feature
* pedestrian animation
* pause/settings
* vehicle outline under bridges

If investigation reveals that one of these is a prerequisite, make the smallest necessary compatibility change and document it. Do not implement the feature itself.

---

## 14. Git workflow

Work on the current branch:

```text
release/v0.16.0g-alpha
```

Create normal commits with clear messages.

Push the commits to the remote when the implementation is complete and validated.

Do NOT create or push a Git tag.

---

## Final report

At the end, report:

### Implementation

* what was implemented
* how the Godot implementation maps to the existing Pygame behaviour
* any protocol/server changes

### Tests

* exact test commands
* results
* any pre-existing unrelated failures

### Manual validation

* scenarios tested
* any remaining limitations

### Performance

* whether refueling introduced any measurable runtime/per-frame cost
* any performance-sensitive implementation choices

### Git

* commit hash(es)
* confirmation that the branch was pushed
* explicitly confirm that no Git tag was created

Do not start the next parity phase automatically.
