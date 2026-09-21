# Road Rage Taxi — Phase 2

## Headless Python Simulation Server + Local Client

You are continuing development of the Road Rage Taxi codebase.

Repository:

https://github.com/emehtata/roadragetaxi

Phase 1 has now been completed.

The purpose of Phase 1 was to separate the game simulation from rendering and input, while keeping the existing Pygame game functional.

Phase 2 now takes the next architectural step:

> Run the game simulation as an independent headless Python process and make the existing Pygame game a client of that simulation.

This is an architectural foundation for a future 3D client and, later, multiplayer.

---

# IMPORTANT SCOPE

This phase is deliberately limited.

DO:

* create a headless Python simulation server
* make the current Pygame game communicate with it
* define a clean local client/server protocol
* move authoritative simulation state into the server
* send player commands from client to server
* send relevant simulation state from server to client
* keep the current Pygame renderer
* preserve existing gameplay

DO NOT:

* implement multiplayer
* add Internet networking
* add Godot
* add Panda3D
* add Ursina
* replace Pygame
* redesign gameplay
* rewrite NPC systems
* rewrite Resident systems
* rewrite pedestrian systems
* rewrite traffic systems
* introduce MQTT for the game-state protocol
* serialize the entire world unnecessarily every frame
* optimize prematurely

The goal is architectural separation, not a new game engine.

---

# STEP 1 — Inspect the Phase 1 implementation

Before modifying anything:

1. Inspect the current repository.
2. Review the Phase 1 architecture.
3. Find the simulation entry point.
4. Find the GameState representation.
5. Find the command/input abstraction.
6. Find the current Pygame client.
7. Identify any remaining simulation → Pygame dependencies.
8. Identify what state the renderer currently consumes.
9. Identify what state the simulation currently mutates directly.

Do not assume Phase 1 was implemented exactly according to its intended architecture.

Verify the actual code.

Build the Phase 2 design around the implementation that actually exists.

---

# STEP 2 — Define the new process architecture

The target architecture is:

```
                     LOCAL MACHINE

             ┌────────────────────────┐
             │   Python Simulation    │
             │        Server          │
             │                        │
             │  World                 │
             │  Traffic               │
             │  NPCs                  │
             │  Residents             │
             │  Pedestrians           │
             │  Player                │
             │  Physics               │
             │  Missions              │
             │  Weather               │
             │  Time                  │
             │                        │
             │  AUTHORITATIVE STATE   │
             └───────────┬────────────┘
                         │
                   local transport
                         │
             ┌───────────▼────────────┐
             │    Pygame Client       │
             │                        │
             │  Input                 │
             │  Rendering             │
             │  Camera                │
             │  Audio                 │
             │  UI                    │
             └────────────────────────┘
```

The server must not create a graphical window.

The Pygame client must not run the authoritative simulation.

---

# STEP 3 — Create a real headless server entry point

Create a clean entry point for the simulation server.

For example:

```
python -m ...server
```

or an equivalent project-specific command.

The exact module structure should follow the existing repository conventions.

Starting the server must:

* initialize the simulation
* load the required world data
* initialize game state
* start the simulation loop
* listen for client connections/commands
* publish state to connected clients
* run without Pygame display initialization

The server must be usable on a machine without a graphical environment.

Do not import the Pygame renderer from the server.

If Pygame is still required by some simulation dependency, identify and isolate that dependency rather than silently initializing Pygame.

---

# STEP 4 — Choose a suitable local transport

For Phase 2, use a simple local IPC/network mechanism.

The architecture should be compatible with future network transport, but we do not need Internet networking yet.

Evaluate the existing project before choosing the mechanism.

Possible approaches include:

* localhost TCP
* UDP where appropriate
* Unix domain sockets on Linux
* another lightweight standard-library solution

Prefer the simplest robust solution.

Avoid introducing a large networking framework without a clear need.

The protocol must not depend on Pygame.

---

# STEP 5 — Define a versioned protocol

Create an explicit protocol boundary between client and server.

For example, conceptually:

```
CLIENT → SERVER

{
    "type": "command",
    "version": 1,
    "command": {
        ...
    }
}
```

and:

```
SERVER → CLIENT

{
    "type": "state",
    "version": 1,
    "tick": 12345,
    "state": {
        ...
    }
}
```

The exact format is up to the implementation.

JSON is acceptable for the initial local implementation if performance measurements show it is sufficient.

However:

> Do not make the protocol architecture dependent on JSON.

The protocol should have a clean serialization layer so it can later be replaced with a binary representation if necessary.

Do not send Python objects directly across the process boundary.

Do not use pickle.

---

# STEP 6 — Define client → server commands

The client must send player actions to the server.

The server should receive semantic commands rather than raw Pygame events.

For example:

```
accelerate
brake
steer
handbrake
interact
accept_mission
cancel_mission
```

If the current game already has an input-command abstraction from Phase 1, reuse it.

Do not send:

```
pygame.KEYDOWN
```

or:

```
pygame.key.get_pressed()
```

across the boundary.

The Pygame client translates physical input into game commands.

The server interprets those commands.

---

# STEP 7 — Define server → client state

The server must provide enough state for the client to render the game.

At minimum this will likely include:

### Player

* world position
* orientation
* velocity/speed
* current vehicle state
* relevant gameplay state

### NPC vehicles

* identity
* position
* orientation
* velocity/speed
* visual/behaviour state required by the renderer

### Pedestrians

* identity
* position
* orientation
* movement state
* visual state required by the renderer

### Traffic lights

* identity
* position/reference
* current state
* relevant timing/state information

### World

Only send dynamic state that the client actually needs.

Do NOT continuously transmit static OSM data if the client can load it independently.

For example, the client may continue loading:

* map geometry
* static buildings
* roads
* static textures
* static assets

locally.

The server remains authoritative for dynamic gameplay state.

---

# STEP 8 — Static world vs dynamic state

Establish this important distinction:

## Static data

Can be loaded by the client independently:

* OSM geometry
* roads
* buildings
* parking data
* static textures
* sprite/model assets
* map metadata

## Dynamic simulation state

Must originate from the server:

* player state
* NPC positions
* NPC state
* pedestrian positions
* traffic-light state
* weather state
* game time
* missions
* passenger state
* relevant gameplay state

Do not duplicate the simulation unnecessarily in the client.

The client may cache static world data, but it must not independently simulate gameplay entities.

---

# STEP 9 — Server tick and client render rate

The server simulation and client rendering must operate independently.

Conceptually:

```
SERVER

simulation.tick()
simulation.tick()
simulation.tick()
...
```

while:

```
CLIENT

render()
render()
render()
render()
...
```

The server should run at a controlled simulation rate.

The client should render at the available frame rate.

Do not make rendering FPS the authoritative simulation clock.

Do not make the server wait for the renderer.

Do not make the renderer wait synchronously for every server tick.

---

# STEP 10 — Client-side interpolation

Because the server and renderer now operate independently, movement may otherwise appear less smooth.

Introduce a simple interpolation mechanism where appropriate.

For example:

```
server state N
       ↓
server state N+1

      ↓ interpolation

   renderer
```

The client may interpolate visual positions between received authoritative states.

IMPORTANT:

Interpolation is visual only.

The client must never modify authoritative simulation state based on interpolation.

The server remains authoritative.

Do not build client-side prediction yet unless the existing game architecture absolutely requires it.

For a local single-player game, simple interpolation should be sufficient.

---

# STEP 11 — Connection lifecycle

Implement a basic client/server lifecycle.

Server:

```
START
  ↓
WAIT FOR CLIENT
  ↓
CLIENT CONNECTED
  ↓
RUN SIMULATION
  ↓
CLIENT DISCONNECTED
  ↓
WAIT FOR CLIENT
```

Client:

```
START
  ↓
CONNECT TO SERVER
  ↓
RECEIVE INITIAL STATE
  ↓
RUN GAME
  ↓
DISCONNECT
  ↓
EXIT
```

Handle:

* server unavailable
* connection failure
* client disconnect
* malformed messages
* protocol version mismatch
* server shutdown

Failure should result in a controlled error rather than a traceback that leaves the game in an undefined state.

---

# STEP 12 — Initial state / synchronization

When the client connects, the server must provide an initial authoritative state.

This should include everything the renderer needs to establish the initial scene.

Conceptually:

```
CONNECT
   ↓
HANDSHAKE
   ↓
INITIAL STATE
   ↓
NORMAL STATE UPDATES
```

The initial state may be larger than normal incremental updates.

Do not optimize this prematurely.

---

# STEP 13 — Full state vs delta updates

For the first implementation, prefer correctness and simplicity.

A full dynamic state snapshot at a reasonable interval is acceptable if performance remains good.

However, structure the protocol so that later it could support:

```
FULL STATE
```

and:

```
STATE DELTA
```

without rewriting the client/server architecture.

Do not implement complicated delta compression unless measurements show it is necessary.

The current goal is to establish the boundary.

---

# STEP 14 — Pygame client changes

Convert the current Pygame application into a client.

It should:

1. connect to the simulation server
2. send player commands
3. receive authoritative state
4. update its local render representation
5. render the world
6. handle local UI/audio
7. handle camera
8. handle visual interpolation

The client must NOT:

* move NPCs itself
* run Resident AI
* run pedestrian AI
* decide traffic-light states
* run authoritative collision handling
* modify authoritative game time
* independently advance the game simulation

If some existing rendering code currently performs these functions, refactor it so the server becomes authoritative.

---

# STEP 15 — Preserve visual behaviour

The current Pygame client should look and behave essentially the same as before.

Do not use this phase to redesign:

* camera
* sprites
* map rendering
* lighting
* weather visuals
* UI
* vehicle graphics
* pedestrian graphics

The only intended visible difference should be the process architecture.

---

# STEP 16 — Performance requirements

Performance is particularly important because the current game has previously suffered from frame stutters.

Do NOT introduce:

* JSON encoding of enormous static datasets every frame
* deep-copying the entire world unnecessarily
* blocking client waits in the render loop
* blocking server waits for rendering
* one network message per entity per frame
* excessive object allocation
* unnecessary conversions
* synchronous request/response for every frame

Communication should be asynchronous from the perspective of rendering.

The client should continue rendering even if a state update is slightly delayed.

The server should continue simulating even if rendering takes longer than expected.

---

# STEP 17 — Do not use MQTT

Although MQTT may be useful later for some multiplayer/backend communication, it is explicitly out of scope here.

Do not introduce MQTT as the main real-time game-state transport.

The Phase 2 protocol should be:

* lightweight
* local
* low latency
* simple
* independent of third-party infrastructure

The protocol should nevertheless be designed so that another transport could be introduced later.

---

# STEP 18 — Headless verification

Create a way to verify that the server works without the client.

For example:

```
start server
   ↓
initialize world
   ↓
run N simulation ticks
   ↓
verify state changes
   ↓
shut down
```

The test must not require a graphical environment.

At minimum verify:

* server starts headlessly
* simulation initializes
* simulation advances
* NPC simulation advances
* Resident simulation advances
* pedestrian simulation advances
* traffic lights advance
* game time advances
* weather state is available
* player commands can reach the simulation

---

# STEP 19 — Client/server integration test

Add a basic integration test where possible:

```
start server
     ↓
connect client
     ↓
receive initial state
     ↓
send command
     ↓
server processes command
     ↓
receive updated state
```

The test does not need to run the full graphical Pygame client.

Test the protocol and simulation boundary independently.

---

# STEP 20 — Documentation

Update the architecture documentation created in Phase 1.

Document:

1. Server responsibilities
2. Client responsibilities
3. Command flow
4. State flow
5. Static vs dynamic data
6. Protocol structure
7. Simulation tick
8. Rendering frame rate
9. Connection lifecycle
10. Current transport
11. Why MQTT is not used
12. How this architecture can later support another client
13. What would need to change for a remote multiplayer server

Include a simple architecture diagram.

---

# STEP 21 — Future 3D client compatibility

The resulting architecture must make this possible:

```
Python Simulation Server
         │
         │ protocol
         ▼
   ┌──────────────┐
   │ Pygame       │
   │ Client       │
   └──────────────┘
```

and later:

```
Python Simulation Server
         │
         │ same protocol
         ▼
   ┌──────────────┐
   │ 3D Client    │
   │ Godot/etc.   │
   └──────────────┘
```

The server must have no knowledge of whether the client uses:

* Pygame
* Godot
* Panda3D
* another engine

This is the key architectural objective of Phase 2.

---

# STEP 22 — Future multiplayer compatibility

Do not implement multiplayer.

However, make sure the architecture does not make multiplayer impossible.

The server should conceptually support:

```
Server
  │
  ├── Client A
  ├── Client B
  └── Client C
```

in the future.

For now there may be exactly one client.

Do not implement multiple players, accounts, authentication, matchmaking, Internet transport or persistence.

---

# IMPORTANT: authoritative state

After Phase 2:

> The Python simulation server is the single source of truth.

The client is a view and command source.

This distinction must be maintained rigorously.

Bad:

```
Client moves car
    ↓
Server accepts resulting position
```

Good:

```
Client:
    "steer right"

    ↓

Server:
    calculates movement

    ↓

Server:
    authoritative position

    ↓

Client:
    renders position
```

---

# IMPORTANT: do not duplicate simulation

Do not create a second version of:

* NPC AI
* traffic AI
* Resident AI
* pedestrian AI
* physics
* traffic-light logic

inside the client.

If rendering needs information, obtain it from server state.

---

# Expected project architecture

The exact directory names should follow the existing project, but conceptually the architecture should resemble:

```
roadragetaxi/
│
├── simulation/
│   ├── game_state.py
│   ├── simulation.py
│   ├── world.py
│   ├── traffic.py
│   ├── residents.py
│   ├── pedestrians.py
│   ├── physics.py
│   └── ...
│
├── server/
│   ├── server.py
│   ├── protocol.py
│   └── transport.py
│
├── client/
│   ├── client.py
│   ├── protocol.py
│   ├── input.py
│   └── ...
│
├── rendering/
│   ├── renderer.py
│   ├── camera.py
│   └── ...
│
└── tests/
```

Do not force this exact structure if the current repository has a better organization.

---

# Development workflow

Before changing code:

1. Inspect the current Phase 1 implementation.
2. Map the actual simulation/client dependencies.
3. Identify the minimum state that must cross the process boundary.
4. Design the protocol.
5. Explain the proposed implementation plan.
6. Then implement it.

Do not stop after analysis.

---

# Acceptance criteria

Phase 2 is complete when all of the following are true:

### Server

* [ ] Python simulation can run headlessly.
* [ ] Server does not initialize a graphical Pygame display.
* [ ] Server owns authoritative simulation state.
* [ ] Server advances simulation independently of rendering.
* [ ] Server accepts semantic player commands.
* [ ] Server publishes simulation state.
* [ ] Server handles client disconnect cleanly.

### Client

* [ ] Pygame client connects to server.
* [ ] Pygame input becomes semantic commands.
* [ ] Client sends commands to server.
* [ ] Client receives authoritative state.
* [ ] Client renders server state.
* [ ] Client does not independently simulate NPCs.
* [ ] Client does not own authoritative player state.
* [ ] Rendering remains smooth.

### Architecture

* [ ] Simulation has no dependency on the Pygame renderer.
* [ ] Protocol has no dependency on Pygame.
* [ ] Server has no dependency on rendering.
* [ ] Static and dynamic data are clearly separated.
* [ ] Protocol is versioned.
* [ ] Transport is isolated behind an abstraction.
* [ ] No MQTT dependency has been introduced.
* [ ] No multiplayer functionality has been implemented.

### Quality

* [ ] Existing tests pass.
* [ ] New server tests pass.
* [ ] Protocol/integration tests pass.
* [ ] Game still starts normally.
* [ ] NPC-004 behaviour remains intact.
* [ ] No obvious FPS regression.
* [ ] No new periodic stuttering caused by communication.
* [ ] Architecture documentation is updated.

---

# Final review

Before finishing, inspect the complete diff.

Pay particular attention to accidental changes in:

* NPC behaviour
* Resident behaviour
* pedestrian behaviour
* traffic lights
* routing
* collisions
* player physics
* missions
* weather
* game time

If any gameplay behaviour changed unintentionally, fix it before completing Phase 2.

Finally report:

1. Architecture implemented
2. Server entry point
3. Client entry point
4. Transport selected and why
5. Protocol design
6. State sent server → client
7. Commands sent client → server
8. Tests performed
9. Performance observations
10. Remaining Pygame dependencies
11. Known limitations
12. Recommended Phase 3

Do NOT implement Phase 3.

The next phase will be decided separately.
