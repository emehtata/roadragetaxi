You are working on the Road Rage Taxi codebase.

Repository:

https://github.com/emehtata/roadragetaxi

Target branch:

release/0.15.0alpha

## Context

Phase 1 separated the gameplay simulation from the Pygame rendering code.

A subsequent client/server implementation was introduced in 0.15.0alpha.

The current implementation is NOT performing well enough.

Observed problems:

* FPS has dropped significantly compared with the previous version.
* The game now exhibits visible stuttering.
* The game has crashed multiple times during testing.
* Some crashes have already required corrective fixes.
* The current architecture introduces unnecessary overhead for the single-player game.

We are therefore introducing an intermediate architectural phase:

# PHASE 1.5 — RESTORE SINGLE-PROCESS PERFORMANCE

The goal is NOT to abandon the simulation/rendering separation.

The goal is to keep the useful Phase 1 boundary while removing the expensive client/server machinery from the normal single-player execution path.

---

# CRITICAL ARCHITECTURAL DECISION

For normal single-player gameplay, the architecture must become:

```
Pygame main loop
       │
       ├── input → PlayerCommand
       │
       ▼
advance_simulation()
       │
       │ direct in-process state
       ▼
   Pygame renderer
```

There must NOT be:

```
TCP
JSON serialization
JSON deserialization
shadow-object reconciliation
per-frame network state interpolation
background SimulationServer thread
```

in the normal single-player game loop.

The simulation and renderer remain logically separated, but they execute in the same process.

---

# WHY THIS CHANGE IS REQUIRED

The current 0.13 implementation runs SimulationServer in a Python background thread while the Pygame renderer runs in the main thread.

Both perform substantial Python work and therefore compete for CPython's GIL.

In addition, the server currently:

1. simulates the world
2. builds a complete dynamic state snapshot
3. serializes it to JSON
4. sends it through TCP
5. the client receives it
6. decodes JSON
7. reconciles shadow objects
8. interpolates state
9. renders it

This is unnecessary overhead for local single-player gameplay.

The architecture must therefore be simplified.

---

# STEP 1 — Inspect the current implementation

Before modifying code, inspect:

* simulation.py
* protocol.py
* transport.py
* server/
* main/
* render/
* performance.py
* tests related to client/server
* docs/architecture/simulation-rendering.md

Identify exactly how the current normal single-player startup reaches SimulationServer.

Do not assume the architecture.

Trace it through the actual code.

---

# STEP 2 — Restore direct simulation execution

The normal:

```
python -m theroadragetrip
```

single-player execution must call:

```
advance_simulation()
```

directly from the main gameplay loop.

The main loop should once again have this conceptual structure:

```
read Pygame input
    ↓
create PlayerCommand
    ↓
advance_simulation(...)
    ↓
render current simulation state
```

Do not duplicate simulation logic.

Do not restore the old giant inline simulation block.

Reuse the Phase 1 extraction.

---

# STEP 3 — Disable client/server transport in normal single-player mode

The normal game must NOT:

* create a SimulationServer thread
* open a TCP listener
* connect to localhost
* serialize state
* deserialize state
* apply server snapshots
* create ShadowVehicle objects for normal NPC rendering
* interpolate network state

All of these should be bypassed completely in normal single-player mode.

Do not delete the client/server implementation yet.

It may remain available for later experimentation.

---

# STEP 4 — Keep the client/server code isolated

The existing:

* protocol.py
* transport.py
* server/

may remain in the repository.

However:

> Normal single-player execution must not import or initialize them unnecessarily.

Avoid imports that cause server/client infrastructure to load during ordinary gameplay.

The future server implementation should be isolated behind an explicit entry point.

For example:

```
python -m theroadragetrip.server
```

must remain conceptually separate from:

```
python -m theroadragetrip
```

Do not make the normal game depend on the server.

---

# STEP 5 — Remove shadow-state rendering from normal gameplay

Normal single-player rendering must use the actual simulation objects:

* actual player vehicle
* actual NPC vehicles
* actual pedestrians
* actual traffic state
* actual Resident state

Do not use:

* ShadowVehicle
* ShadowPedestrian
* apply_server_state()
* interpolate_state()

for the normal single-player path.

The renderer should directly consume the authoritative in-process simulation objects.

---

# STEP 6 — Preserve the Phase 1 boundary

Do NOT undo the useful architectural work from Phase 1.

Keep:

```
PlayerCommand
```

and:

```
advance_simulation()
```

and the conceptual separation:

```
INPUT
   ↓
SIMULATION
   ↓
RENDERING
```

Simulation code must still not depend on Pygame rendering.

Do not move the simulation back into main.py.

The objective is:

```
clean in-process architecture
```

not:

```
revert to the pre-Phase-1 architecture.
```

---

# STEP 7 — Eliminate unnecessary per-frame state conversion

The normal single-player path must not perform:

```
simulation object
    ↓
dict
    ↓
JSON
    ↓
dict
    ↓
shadow object
```

The renderer should use the existing objects directly.

Do not create duplicate representations of NPCs or pedestrians unless they are genuinely required for rendering.

---

# STEP 8 — Camera handling

Keep camera behaviour visually identical to the current game.

However, the camera is client/rendering state rather than authoritative multiplayer state.

For the single-player path:

* camera may directly follow the simulation state
* camera interpolation may remain local
* no camera state needs to cross a protocol

Do not introduce network synchronization for camera state.

---

# STEP 9 — Preserve existing gameplay

This refactoring must NOT change:

* NPC-004 behaviour
* NPC driving
* Resident behaviour
* pedestrian behaviour
* traffic lights
* traffic rules
* physics
* collisions
* missions
* weather
* game time
* passenger behaviour
* rage system
* camera behaviour
* map rendering
* lighting
* audio
* UI

Only the execution architecture should change.

---

# STEP 10 — Investigate the current performance regression

Do not merely disable the server and declare success.

Measure the difference.

Use the existing performance/profiling infrastructure.

Compare:

```
0.12.x / pre-client-server behaviour
```

against:

```
0.15.0alpha current behaviour
```

and:

```
0.13.x Phase 1.5 result
```

Where possible measure:

* FPS
* frame time
* simulation time
* rendering time
* NPC update time
* pedestrian update time
* physics
* collisions
* map rendering
* lighting
* weather
* serialization
* interpolation

The final single-player implementation should contain no serialization/interpolation/network cost.

---

# STEP 11 — Investigate stuttering

The target is not merely higher average FPS.

We need stable frame times.

Look specifically for:

* periodic spikes
* GC/object-allocation spikes
* state conversion
* JSON serialization
* TCP operations
* thread scheduling
* shadow-object reconciliation
* interpolation allocations
* repeated dictionary construction
* unnecessary copies
* repeated list construction

Use the existing frame profiler.

If a remaining spike exists after removing client/server overhead, identify its actual subsystem before changing it.

Do not make speculative optimizations.

---

# STEP 12 — Crash stability

Review all recent client/server-related crash fixes.

Look for errors caused by:

* stale shadow objects
* missing NPC IDs
* state arriving in an unexpected order
* disconnected clients
* protocol state
* server/client shutdown
* None values
* rendering objects being created before state exists

Once the normal single-player path no longer uses server/client synchronization, remove or isolate crash-prone code that is no longer necessary for that path.

Do not hide exceptions with broad:

```
except Exception:
    pass
```

or similar constructs.

Failures must remain diagnosable.

---

# STEP 13 — Do NOT delete the future server architecture

The client/server code may remain as an experimental architecture.

But make its status explicit:

```
Experimental / future architecture
```

It must not affect normal single-player performance.

The future architecture should eventually be:

```
Python Simulation Server
         │
         │ optimized protocol
         ▼
    3D Client
```

But this is NOT Phase 1.5.

---

# STEP 14 — Do not introduce multiprocessing yet

Do NOT solve the current problem by simply moving SimulationServer into a multiprocessing process.

That would remove the GIL contention, but it would still leave:

* state serialization
* IPC
* state copying
* duplicated world data
* snapshot construction
* client reconciliation
* protocol overhead

We first need to establish a fast and stable in-process architecture.

A future real server/client implementation can use a separate process when it actually becomes necessary.

---

# STEP 15 — Keep the protocol implementation available

Do not rewrite protocol.py during this phase unless required to remove unwanted imports or startup dependencies.

The protocol is future infrastructure.

It should simply no longer be part of the normal single-player hot path.

---

# STEP 16 — Tests

Update tests to reflect the new architecture.

At minimum verify:

1. Normal game startup does not create SimulationServer.
2. Normal game startup does not open a TCP listener.
3. Normal game loop calls advance_simulation directly.
4. Normal gameplay does not use apply_server_state().
5. Normal gameplay does not use interpolate_state().
6. Normal gameplay does not create ShadowVehicle objects.
7. PlayerCommand still crosses the input/simulation boundary.
8. Simulation remains Pygame-independent.
9. Existing simulation tests continue to pass.
10. Existing NPC tests continue to pass.
11. Existing pedestrian tests continue to pass.
12. Existing traffic tests continue to pass.

Keep the client/server integration tests separately available for future use.

---

# STEP 17 — Performance acceptance criteria

Compare the resulting build against the last known good single-process version.

The following must be true:

* No measurable TCP/JSON overhead in the normal gameplay loop.
* No background SimulationServer thread during normal gameplay.
* No shadow-state reconciliation during normal gameplay.
* No network interpolation during normal gameplay.
* No obvious FPS regression caused by Phase 1/1.5.
* Frame pacing should be at least as stable as before the client/server experiment.
* No new recurring frame spikes introduced by this refactoring.

Do not define success purely as "average FPS increased".

Stable frame times are more important.

---

# STEP 18 — Documentation

Update:

```
docs/architecture/simulation-rendering.md
```

Explain that the architecture now has two modes:

## Normal single-player

```
Pygame client
     │
     ▼
PlayerCommand
     │
     ▼
Simulation
     │
     ▼
Renderer
```

All in one process.

## Experimental future client/server

```
SimulationServer
      │
      ▼
  protocol
      │
      ▼
  external client
```

The second mode must not affect the first.

Explain why the single-player path intentionally avoids IPC/network serialization.

---

# STEP 19 — Final code review

Before completing the task:

Search the normal startup path for:

* SimulationServer
* transport
* protocol
* socket
* ShadowVehicle
* interpolate_state
* apply_server_state
* JSON serialization

Verify that none of these are part of the normal gameplay hot path.

Also verify that:

```
advance_simulation()
```

is still the single authoritative simulation update function.

There must not be two different simulation implementations.

---

# Expected final architecture

The normal game should look like:

```
                PYGAME PROCESS

┌─────────────────────────────────────┐
│                                     │
│              INPUT                  │
│                │                    │
│                ▼                    │
│         PlayerCommand               │
│                │                    │
│                ▼                    │
│       ┌─────────────────┐           │
│       │   SIMULATION    │           │
│       │                 │           │
│       │ NPC             │           │
│       │ Residents       │           │
│       │ Pedestrians     │           │
│       │ Traffic         │           │
│       │ Physics         │           │
│       │ Weather         │           │
│       │ Taxi            │           │
│       └────────┬────────┘           │
│                │                    │
│                │ direct state       │
│                ▼                    │
│       ┌─────────────────┐           │
│       │    RENDERER     │           │
│       │                 │           │
│       │ Map             │           │
│       │ NPCs            │           │
│       │ Pedestrians     │           │
│       │ Lighting        │           │
│       │ Weather         │           │
│       │ UI              │           │
│       └─────────────────┘           │
│                                     │
└─────────────────────────────────────┘
```

The future architecture remains:

```
┌──────────────────┐
│ Python Simulation│
│     Server       │
└────────┬─────────┘
         │
    future protocol
         │
         ▼
┌──────────────────┐
│ 3D Client        │
│ Godot/Panda3D/etc│
└──────────────────┘
```

Do not implement the future architecture in this task.

---

# Final report

When finished, report:

1. What caused the Phase 1/0.13 performance regression.
2. What was removed from the normal hot path.
3. Whether the SimulationServer still exists.
4. How the normal game now reaches advance_simulation().
5. FPS/frame-time comparison before and after.
6. Any remaining performance spikes.
7. Crash/stability findings.
8. Tests executed.
9. Any remaining architectural concerns.
10. What you recommend as the next step.

Do not start a new client/server implementation after completing this task.
