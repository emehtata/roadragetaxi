# Road Rage Taxi – Godot Client Architecture Experiment

## Objective

Create a new experimental architecture for Road Rage Taxi where:

* Python remains the authoritative simulation engine.
* Godot becomes the new rendering and UI client.
* Pygame is no longer treated as a fundamental part of the simulation architecture.
* The existing gameplay and simulation logic should be preserved as much as possible.
* This work must happen in a completely separate development branch.
* Do **not** rewrite the existing game into GDScript.
* Do **not** replace the Python simulation with Godot.
* Do **not** introduce the previously abandoned BIN map format or any BIN-based architecture.

This is an architectural experiment for version:

`0.16.0g-alpha`

Use this branch:

`release/v0.16.0g-alpha`

Create the branch if it does not already exist.

---

# 1. First inspect the existing architecture

Before modifying code, inspect the repository thoroughly.

Identify:

* current application entry points
* Pygame initialization
* main game loop
* simulation/update loop
* rendering code
* input handling
* world state
* vehicle/NPC systems
* pedestrian systems
* taxi systems
* train systems
* aircraft systems
* weather
* game time
* routing
* OSM/map processing
* audio
* UI/HUD
* configuration
* tests
* existing client/server abstractions, if any

Pay particular attention to which code currently performs actual simulation and which code merely presents the simulation.

Do not assume that classes are correctly separated based on their names. Trace actual call relationships.

Before making architectural changes, document the current dependency structure.

---

# 2. Establish the new architectural boundary

The target architecture is:

```text
                 ┌──────────────────────────────┐
                 │      Python Simulation       │
                 │                              │
                 │  World state                 │
                 │  Game time                   │
                 │  NPC traffic                 │
                 │  Vehicles                    │
                 │  Pedestrians                 │
                 │  Taxi system                 │
                 │  Trains                      │
                 │  Aircraft                    │
                 │  Weather                     │
                 │  Routing                     │
                 │  Game rules                  │
                 │  Map data / OSM processing   │
                 └──────────────┬───────────────┘
                                │
                         Simulation API
                                │
                 ┌──────────────▼───────────────┐
                 │        Godot Client          │
                 │                              │
                 │  Rendering                   │
                 │  Camera                      │
                 │  Animation                   │
                 │  Audio                       │
                 │  UI / HUD                    │
                 │  Input                       │
                 │  Presentation state          │
                 └──────────────────────────────┘
```

The Python simulation must remain the authoritative source of game state.

Godot must not independently simulate game rules that belong to the Python server.

---

# 3. Important architectural rule

Do NOT perform a large rewrite.

The purpose of this branch is to establish a clean boundary between:

1. simulation
2. presentation

The existing Pygame client may temporarily remain functional.

The first milestone is successful separation, not feature completeness.

Prefer small, testable refactorings over replacing large subsystems.

---

# 4. Define a simulation API

Introduce a clear interface between Python simulation and presentation.

The initial implementation may use a simple local transport such as:

* localhost TCP
* WebSocket
* HTTP + WebSocket
* another lightweight mechanism already supported by the project

Choose the simplest robust solution that fits the existing architecture.

Do not prematurely optimize the protocol.

The API must conceptually support:

### Server → client

* world/map information required for rendering
* simulation tick
* game time
* vehicles
* pedestrians
* trains
* aircraft
* relevant player state
* weather state
* important gameplay events

### Client → server

* player input
* player movement/control
* interaction requests
* taxi actions
* UI-triggered gameplay commands

The Python simulation remains authoritative.

---

# 5. Do not send unnecessary internal state

Do not expose Python implementation details directly as the API.

For example, avoid simply serializing arbitrary Python objects:

```python
pickle.dumps(world)
```

Do not make the Godot client depend on Python class internals.

Instead define explicit transport models / DTOs / messages.

For example:

```json
{
  "type": "world_snapshot",
  "tick": 12345,
  "game_time": {
    "hour": 14,
    "minute": 37
  },
  "vehicles": [
    {
      "id": 18372,
      "x": 1234.5,
      "y": 827.1,
      "heading": 1.42,
      "speed": 13.8,
      "vehicle_type": "taxi"
    }
  ]
}
```

The exact schema must be based on the existing project rather than invented unnecessarily.

Document the protocol.

---

# 6. Separate simulation timing from rendering timing

The simulation must have its own update/tick concept.

Do not make the Python simulation depend on the Godot frame rate.

The Godot client must be able to render at:

* 30 FPS
* 60 FPS
* higher FPS

without changing simulation correctness.

Likewise, the simulation must be able to run independently of rendering.

Design toward:

```text
Simulation tick
       ↓
state update
       ↓
state/event publication
       ↓
Godot interpolation/rendering
```

Do not require one network message per rendered frame.

---

# 7. Preserve the current map architecture

The repository's current map/OSM architecture must be retained unless a specific change is required for client/server separation.

IMPORTANT:

The old BIN map technology has been abandoned.

Do not reintroduce:

* BIN files
* BIN loaders
* BIN indexes
* BIN-specific map rendering
* BIN-specific APIs

Use the current OSM/map architecture already present in the repository.

The Python side should remain responsible for map semantics and routing.

The Godot client should receive only the geometry/rendering information it actually needs.

---

# 8. Create the initial Godot client

Create a proper Godot project inside the repository, using a clearly separated directory.

For example:

```text
godot/
```

or another structure that fits the existing repository.

Do not mix Godot project files into the Python package structure unnecessarily.

The Godot project should initially contain:

* project configuration
* main scene
* basic client controller
* simulation connection
* world state representation
* camera
* basic rendering layer
* debug UI

Use GDScript.

Do not port the Python simulation logic to GDScript.

---

# 9. First Godot milestone

The first working Godot client does NOT need to reproduce the complete game.

It must prove the architecture.

The minimum successful demonstration is:

1. Start Python simulation.
2. Start Godot client.
3. Godot connects to Python.
4. Python sends initial world state.
5. Godot receives the state.
6. Godot renders the relevant map/world information.
7. Python updates simulation state.
8. Godot receives updates.
9. At least one moving entity can be represented visually.
10. Godot camera can follow the player/entity.
11. The simulation continues independently of Godot rendering.

A simple debug representation is acceptable for the first milestone.

Do not spend time creating final graphics.

---

# 10. Keep Pygame functional where practical

Do not delete the Pygame renderer simply because Godot has been introduced.

If possible, restructure the application so that:

```text
Python simulation
       │
       ├── Pygame client
       │
       └── Godot client
```

can temporarily coexist.

This is highly desirable because the existing Pygame implementation provides a visual reference during the migration.

If the current architecture makes this impossible without a disproportionate refactor, document the limitation and implement the smallest safe separation instead.

---

# 11. Player input

Do not allow Godot to directly manipulate authoritative simulation state.

Instead use commands/events such as:

```text
player_input
player_interaction
taxi_command
```

The Python simulation validates and applies them.

For example:

```text
Godot:
    "player wants to accelerate"

        ↓

Python:
    validate command
    update vehicle state

        ↓

Godot:
    render resulting state
```

Avoid creating a second authoritative player-vehicle simulation inside Godot.

---

# 12. Rendering strategy

Do not blindly reproduce the current Pygame renderer line by line.

Take advantage of Godot's strengths:

* Node2D
* Sprite2D
* Camera2D
* CanvasItem
* animations
* particles
* audio
* UI nodes
* viewport/canvas systems

However, do not create thousands of unnecessary heavyweight Godot nodes if the existing game can contain large numbers of NPCs.

Design the rendering layer with scalability in mind.

In particular, investigate how the current project handles:

* visible roads
* vehicles
* pedestrians
* trains
* aircraft
* off-screen objects

and design an appropriate presentation representation.

The Python simulation may contain many objects that do not need to exist as active Godot rendering objects.

---

# 13. Interpolation

If simulation updates arrive less frequently than rendering frames, the Godot client should eventually interpolate moving objects.

For example:

```text
simulation state A
       ↓
simulation state B

Godot:
A ── interpolate ── B
```

Do not implement an elaborate prediction system yet.

A simple interpolation architecture is sufficient for this branch.

---

# 14. Audio

Keep audio entirely on the Godot/client side where possible.

The Python simulation should generate semantic events such as:

```text
train_arrived
taxi_horn
collision
rain_started
passenger_entered_taxi
```

The Godot client decides how these events are presented acoustically.

Do not make Python depend on Pygame audio APIs.

---

# 15. UI

The Godot client should eventually own:

* HUD
* taxi information
* passenger information
* money
* game time
* weather display
* train/aircraft information
* interaction prompts
* debug overlays
* menus

Do not recreate the current Pygame UI pixel-for-pixel during this first experiment.

Create a minimal but functional debug UI proving that UI state can be driven from Python simulation state.

---

# 16. Testing

Existing Python simulation tests must continue to work.

Add tests for the new boundary where practical.

At minimum test:

* server startup
* client connection
* initial state transfer
* state update
* command handling
* disconnect/reconnect behavior
* malformed messages
* simulation operation without a Godot client

The simulation must remain runnable headlessly.

A command similar to:

```bash
python ... --headless
```

should remain possible if the existing architecture supports it.

Do not make the Python simulation require Godot.

---

# 17. Performance

Do not optimize prematurely, but measure the architecture.

Record:

* simulation tick duration
* serialization time
* network/message transfer time
* Godot update time
* number of entities transferred
* approximate update frequency
* memory usage

The goal is to discover whether the proposed separation is viable before migrating the complete game.

Avoid sending full world snapshots unnecessarily if the existing world is large.

If practical, distinguish between:

```text
initial_world_state
state_delta
event
```

but do not build a complicated delta protocol unless measurements justify it.

---

# 18. Versioning

Set the project version to:

`0.16.0g-alpha`

Use the branch:

`release/v0.16.0g-alpha`

Update the appropriate existing version metadata files.

Do not modify the versioning scheme globally beyond what is required for this release branch.

---

# 19. Documentation

Add architecture documentation describing:

* current architecture
* new architecture
* Python responsibilities
* Godot responsibilities
* simulation/client boundary
* communication protocol
* message types
* lifecycle
* how to start the Python simulation
* how to start the Godot client
* how to run the tests
* known limitations
* migration strategy from Pygame

Include a diagram similar to:

```text
                 Python Simulation
                       │
          ┌────────────┼────────────┐
          │            │            │
       World        Routing      Game Rules
          │
          │
     Simulation API
          │
          ▼
     Godot Client
          │
    ┌─────┼─────┐
    │     │     │
 Render  Audio  UI
```

---

# 20. Important things NOT to do

Do NOT:

* rewrite the simulation in GDScript
* remove Python
* remove Pygame immediately
* reintroduce BIN
* create a second authoritative simulation in Godot
* make Godot responsible for routing
* make Godot responsible for NPC AI
* duplicate game rules in both Python and GDScript
* introduce a complicated networking framework without justification
* optimize the protocol before measuring it
* rewrite working gameplay systems unnecessarily
* change unrelated gameplay behavior

This is an architecture experiment, not a complete game rewrite.

---

# 21. Definition of Done for 0.16.0g-alpha

The branch is successful when:

* `release/v0.16.0g-alpha` exists.
* Project version is `0.16.0g-alpha`.
* Existing Python simulation still runs.
* Existing tests pass or any failures are explicitly explained.
* Python simulation can run independently of Godot.
* Godot project exists and starts.
* Godot can connect to the Python simulation.
* Python remains authoritative.
* Godot receives simulation state.
* Godot renders a basic representation of the world.
* At least one moving entity is synchronized.
* Basic player input can travel from Godot to Python.
* The simulation remains independent of Godot's rendering FPS.
* The architecture and protocol are documented.
* No BIN-based technology is introduced.
* No large-scale rewrite of the existing simulation has been performed.

At the end, provide a concise implementation report containing:

1. Files changed/added.
2. New architecture.
3. Simulation/client boundary.
4. Communication mechanism.
5. Protocol/message types.
6. Tests executed and results.
7. Performance measurements.
8. Known problems.
9. Recommended next step for `0.16.0g-alpha.1` or the next development phase.

Do not claim success for anything that was not actually tested.
If an architectural decision is uncertain, inspect the existing code and explain the evidence before choosing it.
