# Task: Implement Phone and Offers UI in the Godot client

Work on the current branch:

`release/v0.16.0g-alpha`

The networking, Godot audio, Stable Audio asset replacement and packaging work is now complete.

Recent work includes:

* non-blocking per-client server networking
* map chunk preparation
* Godot audio catalog and playback
* Stable Audio Open OGG replacements
* deterministic audio variation selection
* audio validation
* Python wheel packaging fix
* Godot self-tests
* real-window audio verification

Do not redesign these systems.

The next feature phase is the **phone and offers UI**.

---

# 1. First investigate the existing Godot architecture

Before changing code, inspect:

* `godot/main.gd`
* existing Godot UI scenes/scripts
* `godot/audio_manager.gd`
* simulation/client message handling
* taxi/passenger state handling
* offer/passenger generation
* existing Pygame phone/offer functionality
* existing server-side offer/passenger models
* existing input handling
* existing game clock
* existing tests

The Godot client should become a presentation/input client for functionality that already exists in the simulation where possible.

Do not duplicate server-side game logic in Godot.

If the Pygame client already implements phone/offer behaviour, use it as the behavioural reference, but do not blindly copy its UI implementation.

---

# 2. Fix the existing interpolation underruns first

The latest `make godot-selftest` result reported:

```text
2 interpolation underruns in 6 seconds
```

Earlier testing had:

```text
0 interpolation underruns
```

Before implementing the UI, determine whether these two underruns are:

* a real regression
* caused by the new audio work
* caused by test timing
* caused by startup timing
* caused by rendering/load spikes
* or an existing measurement artefact

Do not simply loosen or remove the assertion.

If the underruns are reproducible and caused by a real regression, fix the underlying problem.

If they are nondeterministic and demonstrably harmless, improve the diagnostic/test so that this is documented and measurable.

Run the relevant test multiple times.

Do not make unrelated performance changes.

The final report must explicitly state:

* whether the underruns reproduce
* their cause
* whether code was changed
* final test results

---

# 3. Phone UI

Implement a phone UI in the Godot client.

The phone should be a distinct overlay/panel rather than part of the world rendering.

The UI should be usable without obscuring the entire game.

Use the existing game visual style rather than introducing a completely different UI language.

The phone should support at minimum:

* opening the phone
* closing the phone
* showing available passenger/job offers
* showing relevant offer details
* selecting an offer
* accepting an offer
* rejecting/dismissing an offer where supported by the simulation
* clearly showing when there are no offers

Use the logical audio event:

```text
ui.phone_open
```

when opening the phone, using the existing audio catalog.

Do not reference an audio filename directly.

---

# 4. Phone input

Inspect the existing key bindings before adding new ones.

Choose a sensible phone toggle key that does not conflict with:

* driving controls
* taxi interaction
* camera controls
* debug controls
* existing UI controls

Do not hard-code a key if the project already has an input/action abstraction.

The phone should also be closable using the normal UI/back mechanism where appropriate.

Opening and closing the phone must not accidentally:

* accelerate the taxi
* brake the taxi
* steer the taxi
* trigger a taxi interaction
* accept an offer

---

# 5. Offers UI

The offers screen should show enough information for the player to make a meaningful choice.

At minimum show, where available from the existing simulation:

* passenger/customer name or identifier
* pickup location
* destination
* estimated distance
* fare/reward
* relevant special requirements
* offer status

If the existing simulation exposes more useful information, use it where it makes sense.

Do not invent values in the UI.

If a value is not provided by the simulation, either omit it or clearly mark it as unavailable.

Do not calculate gameplay-critical values independently in the Godot client when the server already provides authoritative values.

---

# 6. Offer lifecycle

Follow the existing simulation's authoritative offer lifecycle.

The Godot client must not independently decide whether an offer exists.

Handle at least:

```text
offer created
offer available
offer accepted
offer rejected
offer expired
offer completed
offer cancelled
```

Only implement states that actually exist in the current simulation.

If the current server protocol does not expose enough information for the UI, extend the protocol minimally.

Do not create a second offer-management system inside Godot.

---

# 7. Phone and simulation state

Opening the phone must not pause the simulation unless the existing game design explicitly requires pausing.

Assume the simulation continues running while the phone is open.

The UI must therefore handle:

* new offers arriving while the phone is open
* offers disappearing while the phone is open
* an offer changing state
* the player accepting an offer
* connection loss
* simulation reset/reconnect

Do not leave stale offer entries visible after the authoritative state says they no longer exist.

---

# 8. Connection loss

If the simulation disconnects while the phone is open:

* show the existing connection/disconnected state
* stop allowing offer actions that require the server
* do not leave the UI in a misleading "accepted" state
* clean up any UI-specific timers or resources

Reuse the existing client connection state where possible.

Do not create a separate connection-state implementation.

---

# 9. Phone visual design

Keep the UI deliberately simple for this first implementation.

The phone should feel like an in-game device, not a desktop application.

Suggested structure:

```text
+--------------------------------+
| PHONE                          |
|                                |
| Offers                         |
|                                |
| [Customer]                     |
| Pickup → Destination           |
| Distance: ...                  |
| Fare: €...                     |
|                                |
| [ ACCEPT ]   [ DISMISS ]       |
|                                |
| ------------------------------ |
| Other available offers...      |
|                                |
|                         [ X ]  |
+--------------------------------+
```

This is only a structural example.

Use the project's existing Godot UI style and typography.

Do not spend the majority of this task on visual polish.

Functionality and correct state handling are more important.

---

# 10. Offer interaction feedback

When the player accepts an offer:

* immediately reflect the pending/accepted state in the UI
* wait for authoritative confirmation where the protocol requires it
* do not allow duplicate acceptance requests
* handle rejection/error responses cleanly

When an offer is rejected/dismissed:

* remove or mark it according to the actual simulation behaviour
* do not silently invent a new offer

If the existing simulation has no explicit rejection operation, do not invent one just for the UI.

---

# 11. Audio

Use the existing logical audio events only.

At minimum:

```text
ui.phone_open
```

If suitable existing UI sounds exist in the catalog, use them.

Do not generate new audio assets as part of this task unless an actual missing event is required.

Do not modify the audio system.

The recently regenerated:

```text
vehicle.speed_bump
taxi.meter_start
ui.phone_open
```

assets have already passed audio validation.

---

# 12. Godot scene architecture

Prefer a clean separation such as:

```text
Main
 ├── World
 ├── HUD
 └── PhoneOverlay
      ├── Header
      ├── OfferList
      └── Details
```

The exact node structure should follow the existing project architecture.

Do not create an unnecessarily deep scene hierarchy.

Avoid putting large amounts of UI logic into `main.gd`.

Create focused scripts for the phone/offer UI if appropriate.

---

# 13. Protocol changes

Only extend the network protocol if the Godot client genuinely lacks information required by the UI.

If protocol changes are necessary:

* document the new message/event
* keep the format backward-compatible where practical
* preserve existing message ordering guarantees
* do not introduce blocking socket operations
* do not bypass the per-client queues
* do not make the simulation wait for UI clients

A UI request must never be able to stall the simulation tick.

---

# 14. Pygame compatibility

Do not break the existing Pygame client.

If shared server-side offer logic is changed:

* update both clients where required
* keep the logical simulation state authoritative
* avoid Godot-specific assumptions in shared simulation code

The Godot client is the focus of this task, but the server must remain compatible with the existing Pygame client.

---

# 15. Tests

Add Godot tests for:

### Phone

* phone starts closed
* phone opens
* phone closes
* `ui.phone_open` is triggered exactly once
* opening the phone does not trigger driving input
* closing the phone does not trigger driving input

### Offers

* available offers are displayed
* correct offer data is displayed
* selecting an offer displays its details
* accepting an offer sends exactly one request
* duplicate acceptance is prevented
* authoritative state changes update the UI
* expired/cancelled offers disappear or update correctly
* no-offer state is displayed correctly

### Connection

* connection loss disables server-dependent offer actions
* reconnect/reset clears stale UI state
* no orphaned timers/resources remain

### Audio

Verify that opening the phone produces exactly one logical:

```text
ui.phone_open
```

event.

Do not rely solely on audio waveform analysis for this test.

---

# 16. Regression testing

Run:

```text
make audio-check
make godot-test
make godot-selftest
```

and the complete Python test suite.

The existing expected Python baseline is:

* all normal tests passing
* only the 3 known BIN map-format failures may remain

Do not modify the BIN/map system to make those tests pass.

Also run the real-window Godot test if it is part of the current test workflow.

---

# 17. Performance

The phone UI must not introduce noticeable simulation or rendering overhead.

Do not:

* poll the server continuously from the UI
* create/destroy large numbers of nodes every frame
* perform expensive layout operations every frame
* perform filesystem operations during gameplay
* decode audio during every phone opening
* add per-frame network requests

Update the UI only when relevant state changes.

---

# 18. Documentation

Update the relevant Godot client architecture documentation.

Document:

* phone UI ownership
* offer data flow
* input handling
* connection-loss behaviour
* any protocol changes
* tests

Keep the documentation concise and factual.

---

# 19. Git discipline

Do not push or tag.

Keep the work on:

```text
release/v0.16.0g-alpha
```

Use focused commits.

Prefer separate commits for:

1. interpolation-underrun investigation/fix
2. phone UI
3. offers integration/tests

Do not mix unrelated refactoring into these commits.

---

# Acceptance criteria

The task is complete when:

* the two interpolation underruns have been investigated and explained
* any real regression has been fixed
* the phone can be opened and closed reliably
* phone opening uses the existing `ui.phone_open` logical audio event
* offers are displayed from authoritative simulation state
* offer details are accurate
* offer actions follow the existing simulation lifecycle
* duplicate requests are prevented
* connection loss is handled correctly
* Pygame compatibility is preserved
* no blocking network operations are introduced
* Godot tests cover the new functionality
* `make godot-test` passes
* `make godot-selftest` passes with the final justified interpolation result
* Python tests pass except for the three known BIN map-format failures
* no direct audio filenames are introduced into gameplay code
* no unrelated map/network/audio architecture changes are made

At the end, provide a concise implementation report containing:

1. files changed
2. protocol changes, if any
3. phone UI behaviour
4. offer lifecycle integration
5. interpolation underrun findings
6. test results
7. commit hashes


