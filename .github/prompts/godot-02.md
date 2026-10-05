# Road Rage Taxi – 0.16.0g-alpha Phase 3

## Asynchronous network output and client audio validation

## Branch

Continue on:

`release/v0.16.0g-alpha`

Do NOT create a new branch.

Do NOT push or tag automatically.

Keep the project version:

`0.16.0g-alpha`

The Godot client architecture is now proven in practice.

The current implementation includes:

* Python authoritative simulation
* Godot rendering/UI/audio client
* 30 Hz simulation
* 100 ms client interpolation
* Godot AudioManager
* real HUD
* player identity
* 500 m map chunks
* dynamic map streaming
* TCP JSON-lines protocol
* Pygame compatibility
* headless simulation operation

The current measured Oulu performance is approximately:

* server tick mean: 4.0 ms
* server tick p95: 4.9 ms
* server tick max: 38.5 ms
* state build: 0.08 ms
* state encode: 0.16 ms
* state size: ~15.7 KiB
* Godot state handling: ~0.5 ms
* Godot interpolation + drawing: ~0.35 ms
* Godot windowed FPS under WSLg: ~64 FPS
* 0 interpolation underruns during a 6-second windowed test

The current major architectural problem is:

> Map chunks are sent synchronously from the simulation loop and can block the simulation for approximately 100–281 ms.

This must be fixed before adding substantial new client functionality.

---

# 1. First inspect the current implementation

Read the current implementation before modifying it.

Pay particular attention to:

* `simulation.py`
* `server/__init__.py`
* `protocol.py`
* `transport.py`
* `src/theroadragetrip/map_chunks.py`
* existing server/client integration tests
* `docs/architecture/godot-client.md`
* Godot `sim_client.gd`

Understand exactly:

* where the simulation tick runs
* where socket writes happen
* which code sends `world`
* which code sends `chunk`
* which code sends `chunk_unload`
* which code sends `state`
* whether Pygame uses the same transport
* how disconnects are currently detected

Do not redesign unrelated systems.

---

# 2. Primary goal: asynchronous outgoing network traffic

The simulation loop must never block on a client socket write.

The target architecture is:

```text
                    Python simulation
                           │
                     simulation tick
                           │
                           ▼
                  build outgoing messages
                           │
                           ▼
                    per-client queue
                           │
             ┌─────────────┴─────────────┐
             │                           │
        network sender              simulation
          thread/task                  continues
             │
             ▼
          TCP socket
             │
             ▼
        Godot client
```

The critical invariant is:

> A slow, disconnected or non-reading client must never stall the authoritative simulation tick.

---

# 3. Per-client send queue

Implement a dedicated outgoing queue for each connected client.

The queue must support at least:

* state messages
* map chunk messages
* map unload messages
* other server-to-client messages already defined by the protocol

Do not use one global queue for all clients.

Each client must have its own outgoing queue so that one slow client cannot block another client.

Conceptually:

```text
Client A
  outgoing queue
       ↓
   sender A
       ↓
   socket A

Client B
  outgoing queue
       ↓
   sender B
       ↓
   socket B
```

---

# 4. Sender implementation

Choose the simplest robust implementation compatible with the existing server.

A dedicated sender thread per client is acceptable if that fits the existing architecture.

An async implementation is also acceptable if the current server architecture already supports it cleanly.

Do NOT introduce a large networking framework merely to solve this problem.

The important requirement is separation:

```text
simulation thread
        ≠
socket writer
```

The sender must:

1. wait for queued messages
2. write them to the socket
3. handle partial writes correctly
4. detect disconnects
5. terminate cleanly
6. notify the server that the client has disconnected

Do not silently swallow socket errors.

---

# 5. Queue bounds and backpressure

Do not create an unbounded queue.

A client that stops reading must not cause unlimited memory growth.

Define a reasonable maximum queue size.

Think carefully about message priority.

Not all messages have equal value.

For example:

### High priority

* current state
* player-related state
* commands/results
* important gameplay events

### Lower priority

* map chunks that can be reconstructed/re-requested
* redundant intermediate state

However, do not invent complicated prioritization unless it is needed.

The simplest safe strategy is acceptable initially.

If the queue becomes persistently full:

1. detect the slow client
2. disconnect that client cleanly
3. keep the simulation running

Never allow queue growth to stall or exhaust the server.

Document the chosen policy.

---

# 6. State messages and queue behavior

The simulation currently sends state at 30 Hz.

A client should not accumulate an arbitrarily large backlog of old states.

Consider whether state messages should be coalesced for a slow client.

For example:

```text
state 100
state 101
state 102
state 103
```

If the client has not consumed any of them yet, retaining every historical state may be unnecessary.

A slow client generally needs the latest state rather than every intermediate state.

If implementing state coalescing:

* preserve required events
* do not lose one-shot events
* do not silently lose important gameplay information
* do not change behavior for normal clients

A reasonable architecture may be:

```text
per-client queue

reliable/event messages
        +
latest pending state
```

But only implement this if it remains simple and testable.

---

# 7. Map chunk delivery

Map chunks are currently the largest source of simulation stalls.

Change the architecture so that:

```text
simulation:
    determine required chunks
    enqueue chunks
    continue simulation
```

rather than:

```text
simulation:
    determine required chunks
    socket.send(chunk)
    WAIT
    socket.send(chunk)
    WAIT
    ...
```

The simulation must never wait for the map to arrive at the client.

Preserve:

* nearest-first chunk ordering
* duplicate prevention
* chunk unloading
* per-client loaded chunk tracking

Do not rebuild the map chunk system unnecessarily.

---

# 8. Ordering guarantees

The protocol currently has implicit ordering requirements.

Preserve them.

For a newly connected client, the logical order must remain:

```text
connection
    ↓
world header
    ↓
required map chunks
    ↓
state updates
```

Do not allow asynchronous sender queues to accidentally send a state before the client has received the required `world` header.

Likewise, ensure chunk unload messages do not overtake the corresponding chunk load/update messages in ways that can leave the client in an invalid state.

Document the ordering guarantees.

---

# 9. Simulation timing requirement

After this change, test that the simulation remains responsive while:

1. a normal Godot client is connected
2. a client receives a large initial map
3. a client moves across chunk boundaries
4. a client deliberately reads slowly
5. a client stops reading completely
6. a client disconnects unexpectedly

The simulation must continue ticking independently.

The 30 Hz budget is approximately:

```text
33.3 ms
```

The map transmission must no longer create 100–281 ms stalls.

---

# 10. Add a deliberately slow test client

Create a test mechanism that simulates a bad network client.

It should be able to:

* connect
* optionally read slowly
* optionally stop reading
* optionally disconnect

Use this to prove that the Python simulation remains responsive.

Do not depend on actual network slowness for the automated test.

Make the behavior deterministic.

---

# 11. Tests

Extend the existing server/client integration tests.

At minimum test:

### Normal client

* connects
* receives world header
* receives chunks
* receives states
* simulation continues

### Slow client

* client deliberately reads slowly
* simulation continues ticking
* no deadlock occurs

### Non-reading client

* client connects
* does not consume outgoing data
* simulation continues
* queue remains bounded
* client is eventually disconnected if the queue remains full

### Disconnect

* client disappears during sending
* sender terminates
* simulation continues
* client resources are cleaned up

### Ordering

Verify:

```text
world → chunks → states
```

for a newly connected client.

### Multiple clients

Connect two clients.

Make one client slow.

Verify that the other client continues receiving state updates normally.

This is particularly important.

---

# 12. Measure the result

Run the real Oulu simulation and record:

* simulation tick mean
* p95
* maximum
* tick count
* number of connected clients
* outgoing queue sizes
* map chunk send time
* sender thread/task activity
* memory usage

Specifically compare:

### Before

Known baseline:

```text
tick max ≈ 38.5 ms
initial map send ≈ 281 ms
subsequent chunk transmission ≈ 100 ms
```

### After

The simulation tick should no longer contain socket blocking.

Do not require a specific maximum tick number if another unrelated subsystem occasionally causes a spike.

The important measurement is that map/network transmission no longer produces the large stalls.

---

# 13. Second goal: validate actual Godot audio

After the networking work is complete, test the Godot client with real audio output.

This must be a real windowed test, not only `--selftest`.

Verify:

* engine sound
* train sounds
* positional sounds
* event sounds
* day/night ambience
* rain
* audio volume groups
* no repeated event playback
* no obvious audio leaks
* audio stops correctly when objects disappear

Use the existing game's audio catalog.

Do not invent or duplicate sound assets unnecessarily.

---

# 14. Audio behavior

Check that continuous sounds do not restart every state update.

For example:

```text
engine sound:
    start once
    update pitch/volume
    stop when appropriate
```

not:

```text
every 33 ms:
    create a new engine sound
```

Likewise, event sounds must remain one-shot.

Verify spatial sounds use the appropriate Godot coordinate system.

Document any differences between Pygame and Godot audio behavior.

---

# 15. Do not implement phone/offers UI yet

Do NOT move on to phone, offers, menus, passenger speech or station announcements in this phase.

Those are subsequent work.

First establish:

```text
stable simulation
        +
non-blocking network
        +
working Godot audio
```

Only after those are reliable should larger UI migrations continue.

---

# 16. Preserve existing functionality

Do not remove:

* Pygame client
* existing simulation functionality
* existing routing
* trains
* NPCs
* pedestrians
* weather
* taxi functionality
* existing tests

Do not change gameplay behavior unless required to fix an actual architectural problem.

Do not introduce BIN.

Do not move simulation logic to GDScript.

---

# 17. Documentation

Update:

`docs/architecture/godot-client.md`

Document:

* per-client outgoing queues
* sender architecture
* queue bounds
* backpressure behavior
* message ordering
* slow-client behavior
* state coalescing, if implemented
* map chunk delivery
* audio validation results

Include an updated architecture diagram.

For example:

```text
                         Python Simulation
                                │
                         simulation tick
                                │
                   ┌────────────┴────────────┐
                   │                         │
             world/state/events          commands
                   │
                   ▼
          per-client send queue
                   │
            dedicated sender
                   │
                   ▼
              TCP socket
                   │
                   ▼
             Godot client
             ┌─────┼─────┐
             │     │     │
          Render  Audio  UI
```

The documentation must describe the actual implementation, not future plans.

---

# 18. Definition of Done

This phase is complete when:

1. Python simulation never blocks on client socket writes.
2. Each client has bounded outgoing buffering.
3. A slow client cannot stall the simulation.
4. A non-reading client cannot cause unlimited memory growth.
5. One slow client does not prevent another client from receiving updates.
6. World/chunk/state ordering remains correct.
7. Map chunks are transmitted asynchronously.
8. Existing integration tests still pass.
9. New slow-client tests pass.
10. Real Oulu performance measurements show that network transmission no longer causes the large simulation stalls.
11. Godot audio has been tested with actual sound output.
12. Existing audio events work without duplication.
13. `docs/architecture/godot-client.md` is updated.
14. No BIN architecture is introduced.
15. No simulation logic is moved to Godot.
16. No new release branch is created.
17. Nothing is pushed or tagged automatically.

At the end, provide a concise report containing:

* files changed
* networking architecture
* queue/backpressure design
* ordering guarantees
* slow-client behavior
* tests and results
* before/after Oulu performance
* actual audio test results
* known problems
* recommended next development step

Do not claim that audio was validated unless it was actually tested with sound output.

Do not claim that network blocking is solved unless a slow/non-reading client test demonstrates that the simulation continues independently.
