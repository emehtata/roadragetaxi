# Road Rage Taxi – Godot Client Phase 2

## Branch

Continue development on:

`release/v0.16.0g-alpha`

Do NOT create a new branch.

The current `0.16.0g-alpha` architecture experiment is already implemented and tested. Extend the existing implementation rather than redesigning it.

The current architecture is:

```text
Python simulation
        │
        │ TCP / JSON-lines
        ▼
Godot client
```

Python remains the authoritative simulation.

Godot is responsible for rendering, audio, UI, input and presentation.

Pygame remains available as a legacy/reference client.

Do NOT move simulation logic into Godot.

Do NOT reintroduce the abandoned BIN map format.

---

# Current baseline

The current implementation has already demonstrated:

* Python server starts successfully.
* Godot connects successfully.
* The map is received before state updates.
* State updates arrive at 30 Hz.
* Godot renders the Oulu map.
* Vehicles, pedestrians, trains and the player taxi are represented.
* Godot input controls the Python simulation.
* Python remains authoritative.
* The server can run without a client.
* Reconnect works.
* Events are already included in state messages.
* The Godot client currently interpolates only according to arriving states and can show visible jitter.
* Godot currently has no real sound playback.
* Godot currently has only a debug display instead of a proper HUD.
* The map is currently a fixed 2.5 km area around the starting position.

Existing measured Oulu performance:

* Server tick mean: ~3.9 ms
* Server tick p95: ~5.6 ms
* Server tick maximum: ~29 ms
* State size: ~19 KiB
* State frequency: 30 Hz
* Godot state handling: ~0.5–0.6 ms
* Godot windowed performance under WSLg: ~31 FPS

Do not optimize the protocol prematurely.

Full state updates are currently acceptable.

---

# Phase 1 of this task: inspect before changing

First inspect the existing Godot implementation and documentation.

Read:

* `docs/architecture/godot-client.md`
* `godot/`
* `protocol.py`
* `server/`
* `simulation.py`
* existing integration tests
* existing transport implementation
* current event handling

Determine exactly how the existing implementation works before making changes.

Do not assume the architecture from this prompt is identical to the code.

Preserve existing working behavior.

---

# Phase 2: proper client-side interpolation

This is the first priority.

The current client renders according to the latest state received from the server. This causes visible jitter because:

* server updates at 30 Hz
* rendering may occur at a different frame rate
* network/message arrival is not perfectly uniform

Implement a proper client-side interpolation buffer.

The conceptual model is:

```text
Python simulation:

S100 -------- S101 -------- S102 -------- S103
               33 ms          33 ms

Godot:

received states
       ↓
interpolation buffer
       ↓
render between two known states
```

The renderer should not simply snap to the newest received state.

Use a small interpolation delay/buffer so that two consecutive states are normally available for interpolation.

For example:

```text
render_time = latest_server_time - interpolation_delay
```

Do not hard-code an arbitrary delay without documenting the reasoning.

A reasonable initial value can be derived from the 30 Hz server tick, but make it configurable.

---

## Interpolation requirements

Interpolate at least:

* vehicle position
* vehicle heading
* pedestrian position where applicable
* train position
* aircraft position if/when aircraft are introduced

Use appropriate interpolation for angles so that heading does not rotate the long way around at the ±π boundary.

Do NOT interpolate discrete state such as:

* vehicle type
* passenger identity
* train composition
* weather category
* event names
* interaction state

Those should switch according to the appropriate state boundary.

Do not introduce client-side prediction yet.

Do not make Godot authoritative.

---

# Phase 3: Godot AudioManager

The server already emits semantic events.

Examples include:

```text
vehicle.door_close
train_arrived
```

Build a proper Godot-side audio event system.

The architecture should be approximately:

```text
Python simulation
       │
       │ event
       ▼
Godot event dispatcher
       │
       ▼
AudioManager
       │
       ├── vehicle sounds
       ├── train sounds
       ├── environment
       └── future radio/music
```

The Python server must NOT play audio.

Godot decides how an event is presented acoustically.

---

## Audio requirements

Create a clean abstraction for:

* one-shot sound effects
* positional sounds where appropriate
* looping sounds where appropriate
* sound categories/buses
* master/game/environment/UI volume

Do not create ad-hoc audio playback calls throughout unrelated scripts.

Use Godot's audio system properly.

If the expected game audio assets already exist in the repository, inspect and reuse them.

Do not invent filenames.

If an event has no corresponding sound asset yet:

* keep the event functional
* log/debug it appropriately
* do not fake a nonexistent asset

Create a small configuration mechanism mapping semantic events to sound resources.

Keep this data-driven.

---

# Phase 4: real Godot HUD

Replace the current debug-only display with the first real HUD.

The HUD must consume server state.

Do not duplicate game rules in GDScript.

At minimum display information that is already available in the simulation state, such as:

* current money
* vehicle speed
* game time
* weather
* taxi/passenger status
* relevant current service state
* useful interaction information

Use Godot UI nodes and keep presentation logic separate from the simulation model.

Do not attempt to reproduce the entire existing Pygame UI yet.

The purpose is to establish the new client UI architecture.

---

# Phase 5: map streaming architecture

After interpolation, audio and HUD work, implement the first version of dynamic map streaming.

The current client receives a fixed 2.5 km map around the starting position.

This must evolve into a player-centered map.

The target architecture is:

```text
                    Player position
                          │
                          ▼
                 Python map manager
                          │
             determine required chunks
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
          chunk A      chunk B      chunk C
             │            │            │
             └────────────┼────────────┘
                          ▼
                    Godot client
```

Do not implement an unnecessarily complicated streaming system.

---

## Map chunk requirements

Define an explicit map-chunk representation.

A chunk should have a stable identifier.

Conceptually:

```json
{
  "chunk_id": "x_y",
  "roads": [...],
  "railways": [...],
  "buildings": [...],
  "water": [...]
}
```

The exact schema must be based on the existing map representation.

Do not invent a second map data model if the current map structures can be adapted cleanly.

The server should determine which chunks are required around the player.

The client should:

* request/load missing chunks
* retain nearby chunks
* unload distant chunks
* avoid rebuilding unchanged chunks

---

## Important map rule

Do NOT reintroduce BIN.

The abandoned BIN map format must not appear anywhere in the new architecture.

Continue using the current OSM/map processing architecture.

---

# Phase 6: player identity abstraction

The current implementation has:

> All clients share one player.

Do not implement multiplayer yet.

However, remove assumptions in the protocol that there can only ever be one player.

Introduce an explicit player identity concept.

For example:

```text
player_id
```

The exact implementation should fit the existing architecture.

For now there may still be exactly one player:

```text
player_id = local_player
```

The purpose is only to avoid making the protocol permanently single-player.

Do not implement accounts, matchmaking or multiplayer synchronization.

---

# Phase 7: preserve authoritative simulation

This rule is critical.

Godot must NOT:

* calculate NPC routes
* run NPC AI
* decide collisions
* decide taxi fares
* decide passenger behavior
* decide train schedules
* decide weather
* update authoritative game time
* modify authoritative world state directly

Godot may:

* render
* animate
* interpolate
* play audio
* display UI
* capture input
* send commands

The architecture must remain:

```text
Godot:
"I want to accelerate."

        ↓

Python:
"Input accepted."

        ↓

Python simulation:
vehicle state changes

        ↓

Godot:
"Render the resulting state."
```

---

# Phase 8: tests

Extend the existing tests.

Do not remove existing tests.

Add tests for:

### Interpolation

* two states interpolate correctly
* heading interpolation handles wraparound
* missing/late state does not crash rendering
* duplicate state does not corrupt the buffer
* state sequence/order is handled safely

### Audio

* known event resolves to an audio action
* unknown event does not crash
* event is not played repeatedly when the same event is received only once

### HUD

* valid state produces expected UI values
* missing optional fields do not crash the UI

### Map streaming

* initial chunks load
* entering a new area requests/adds required chunks
* distant chunks can be removed
* duplicate chunks are not loaded twice

### Player identity

* commands contain the correct player identity
* existing single-player behavior remains unchanged

---

# Phase 9: performance measurements

After implementation, measure the actual system.

At minimum record:

* Python server tick mean/p95/max
* state generation time
* state serialization time
* network/message size
* Godot state processing time
* interpolation processing time
* Godot FPS
* number of active rendered entities
* number of loaded map chunks
* memory usage

Test using the real Oulu environment.

Do not use only a synthetic empty test map.

If possible, measure both:

1. WSL2/WSLg
2. native Windows Godot

Do not claim native performance if it was not measured.

---

# Phase 10: versioning

Remain on:

`release/v0.16.0g-alpha`

Do not create a new release branch for this task.

Keep version:

`0.16.0g-alpha`

Do not tag or push automatically.

The repository owner will decide when to push/tag.

---

# Phase 11: documentation

Update:

`docs/architecture/godot-client.md`

Document:

* interpolation architecture
* audio architecture
* HUD architecture
* map streaming architecture
* player identity
* current protocol
* responsibilities of Python vs Godot
* known limitations

Include a current architecture diagram.

The documentation must describe the implementation that actually exists, not an aspirational design.

---

# Scope control

Do NOT:

* rewrite the simulation
* rewrite routing
* rewrite NPC AI
* rewrite the train system
* rewrite the taxi system
* introduce BIN
* replace Python with GDScript
* introduce multiplayer
* introduce client-side prediction
* introduce delta-state networking unless measurements show it is necessary
* rewrite working Pygame gameplay merely for consistency
* remove Pygame yet
* add aircraft functionality when the simulation does not currently have aircraft

If an existing subsystem is insufficient for this architecture, make the smallest change required and document why.

---

# Definition of Done

This task is complete when:

1. Existing Godot/Python integration still works.
2. Proper client-side interpolation reduces visible movement jitter.
3. Godot has a reusable AudioManager driven by simulation events.
4. At least the currently available sound events can be routed through the audio system.
5. Godot has a real initial HUD driven by server state.
6. The map architecture supports player-centered chunk loading without BIN.
7. Player identity exists in the protocol without implementing multiplayer.
8. Existing simulation tests remain passing except for the already-known abandoned BIN integration failures.
9. New tests cover the new functionality.
10. Oulu performance is measured.
11. `docs/architecture/godot-client.md` reflects the actual implementation.
12. No unrelated gameplay behavior is changed.

At the end, provide a concise report containing:

* files changed
* architecture changes
* interpolation implementation
* audio implementation
* HUD implementation
* map streaming implementation
* player identity implementation
* tests and results
* Oulu performance measurements
* known problems
* recommended next step

Do not claim anything was completed unless it was actually implemented and tested.
