You are working on the Road Rage Taxi codebase.

Repository:
https://github.com/emehtata/roadragetaxi

We have now completed the NPC-004 phase. Before implementing further major gameplay systems, we want to begin Phase 1 of a longer-term architectural change:

# PHASE 1 — Separate Game Simulation from Rendering

The long-term goal is to make the game architecture capable of supporting:

* a headless Python simulation server
* one or more independent rendering clients
* eventually a 3D client, potentially implemented with Godot or another engine
* eventually multiplayer in a later 2.0 phase

IMPORTANT:

This phase is NOT about implementing multiplayer.
This phase is NOT about replacing Pygame.
This phase is NOT about adding 3D.
This phase is NOT about changing gameplay behaviour.

The goal is to carefully decouple the existing simulation/game-state logic from the Pygame rendering layer while keeping the current game fully playable.

---

## STEP 1 — Thoroughly inspect the existing architecture

Before modifying anything, inspect the entire relevant codebase.

Identify:

1. Main game loop
2. Pygame initialization and shutdown
3. Game state
4. World/map representation
5. Player/taxi state
6. NPC vehicles
7. Residents
8. Pedestrians
9. Traffic lights
10. Routing/pathfinding
11. Weather
12. Time system
13. Missions/passengers
14. Collision/physics
15. Camera
16. Rendering
17. Input handling
18. Audio
19. Debug functionality
20. Asset loading
21. Any global state or singleton-like objects
22. Any code where simulation logic directly depends on Pygame objects

Do not assume that a class belongs to rendering merely because it currently lives in a rendering-related module.

Trace actual dependencies.

Pay particular attention to code such as:

* pygame.Surface
* pygame.Rect
* pygame.sprite
* pygame.time
* pygame.event
* pygame.key
* pygame.mouse
* pygame.display
* pygame.draw
* pygame.transform
* pygame.image
* pygame.mixer

Determine which uses are genuinely rendering/input/audio related and which are accidentally being used as part of the simulation.

---

# STEP 2 — Define the simulation boundary

Create a clear conceptual boundary:

```
SIMULATION
      |
      | Game State
      v
RENDERING CLIENT
```

The simulation should own:

* world state
* game time
* weather state
* player state
* NPC state
* Resident state
* pedestrian state
* traffic state
* traffic-light state
* routes
* movement
* collisions
* missions
* passenger state
* gameplay rules
* spawning/despawning
* AI decisions
* economic/gameplay state

The renderer should own:

* drawing
* sprites/models
* camera
* visual effects
* screen-space UI
* animations that are purely visual
* visual interpolation
* visual particles
* Pygame-specific rendering objects

Input should eventually become another boundary:

```
Input
  |
  v
Commands
  |
  v
Simulation
```

Do not implement a network protocol yet.

---

# STEP 3 — Introduce a clean Game State representation

Create or refactor toward a central, renderer-independent representation of the current game state.

For example, conceptually:

```
GameState
  ├── world
  ├── time
  ├── weather
  ├── player
  ├── vehicles
  ├── pedestrians
  ├── residents
  ├── traffic_lights
  ├── missions
  └── other gameplay state
```

Use the existing project's architecture where possible.

Do NOT blindly create a giant new GameState class if the existing architecture already has suitable domain objects.

The important requirement is:

> The simulation state must be representable without creating a Pygame window or Pygame rendering objects.

The state should contain data, not graphical resources.

For example, a vehicle's simulation state should conceptually contain things like:

* position
* heading
* speed
* velocity
* route
* current road/lane
* state
* driver/resident information
* destination
* relevant AI state

It should NOT require a pygame.Surface merely to exist.

---

# STEP 4 — Separate simulation tick from rendering frame

The current architecture may combine these concepts.

Refactor toward:

```
simulation.update(dt)
```

and separately:

```
renderer.render(game_state, interpolation)
```

The simulation must not depend on the renderer's FPS.

The target architecture should conceptually support:

```
Simulation:
    fixed/controlled simulation tick

Rendering:
    independent frame rate
```

For now, the game can still run both from the same process.

For example:

```
while running:

    process_input()

    simulation.update(dt)

    renderer.render(simulation.state)
```

Do not over-engineer a fixed timestep if the existing game does not need one yet.

The important thing is that the simulation update can execute without rendering.

---

# STEP 5 — Introduce a simulation/application layer

If appropriate for the existing codebase, create something similar to:

```
game/
    simulation/
    rendering/
    input/
    world/
```

Do not reorganize the entire repository unnecessarily.

Prefer incremental refactoring.

A possible conceptual structure:

```
simulation/
    game_state.py
    simulation.py
    world.py
    traffic.py
    residents.py
    pedestrians.py
    physics.py
    missions.py

rendering/
    renderer.py
    map_renderer.py
    vehicle_renderer.py
    pedestrian_renderer.py
    effects.py
    camera.py

input/
    input_manager.py
```

The actual names and locations should follow the existing project conventions.

---

# STEP 6 — Remove accidental rendering dependencies from simulation

This is one of the most important parts of the task.

Find cases where simulation logic does things like:

* create pygame.Rect solely for collision/state
* use pygame.Vector2 as the domain representation
* query the display size from simulation code
* access camera position from AI logic
* use sprite visibility as a simulation condition
* use sprite existence as an NPC state
* use rendering coordinates as authoritative world coordinates
* use Pygame timing APIs inside simulation logic

Where practical, replace these with renderer-independent representations.

For example:

```
world position → plain numeric/vector representation

collision bounds → simulation collision representation

visibility → renderer concern
```

Do not replace every Pygame type mechanically.

If a Pygame type is harmless and replacing it would create unnecessary churn, assess it carefully first.

The goal is architectural separation, not a pointless rewrite.

---

# STEP 7 — Input must become commands

Do not allow the simulation to directly ask Pygame:

```
pygame.key.get_pressed()
```

Instead introduce an input abstraction.

Conceptually:

```
Keyboard/Input
      |
      v
PlayerCommand
      |
      v
Simulation
```

For example:

```
accelerate
brake
steer_left
steer_right
handbrake
interact
accept_mission
```

The exact command model should follow the current game controls.

For now the Pygame client remains responsible for translating keyboard/mouse input into commands.

Later another client can produce the same commands.

---

# STEP 8 — Rendering must consume state, not own the state

Rendering code should not become the authoritative source of gameplay state.

Avoid patterns such as:

```
sprite.x = ...
sprite.y = ...
simulation reads sprite.x
```

Instead:

```
simulation owns position

renderer receives position

renderer updates sprite/model position
```

The direction should be:

```
Simulation → Renderer
```

not:

```
Renderer → Simulation
```

The renderer may maintain visual-only state such as:

* animation frame
* interpolation position
* particle state
* visual effects
* sprite rotation

but gameplay state must remain in the simulation.

---

# STEP 9 — Prepare for a future headless mode

At the end of this phase it should be possible, with minimal additional work, to conceptually run:

```
python -m ... --headless
```

without opening a Pygame window.

You do NOT need to implement the final production server yet.

However, create a clean separation so that the simulation can be instantiated without:

* pygame.display.set_mode()
* graphical assets
* camera
* renderer

If some dependencies still prevent true headless execution, document them and isolate them rather than creating hacks.

---

# STEP 10 — Preserve the current game

This is critical.

After refactoring:

* The game must still start normally.
* Existing controls must work.
* NPC-004 behaviour must remain unchanged.
* Traffic behaviour must remain unchanged.
* Resident behaviour must remain unchanged.
* Pedestrian behaviour must remain unchanged.
* Traffic lights must remain unchanged.
* Collision behaviour must remain unchanged.
* Missions must remain unchanged.
* Weather must remain unchanged.
* Camera behaviour must remain unchanged.
* Rendering must remain visually equivalent unless a change is required by the refactoring.
* Performance must not regress.

Do NOT use this task as an excuse to rewrite working systems.

---

# STEP 11 — Performance requirements

This game currently has a significant number of simulated entities and has previously suffered from periodic frame stutters.

The architectural refactoring must NOT introduce:

* per-frame serialization of the entire world
* unnecessary deep copies of GameState
* excessive object creation
* unnecessary conversions between data representations
* expensive observer/event systems
* JSON serialization every frame
* network abstractions that are not currently needed

Do not build a network layer yet.

The future server/client architecture should be possible, but Phase 1 should remain lightweight.

---

# STEP 12 — Define an internal state boundary

Before finishing, document the boundary between:

## Simulation state

and

## Rendering state

Create a short architecture document, for example:

```
docs/architecture/simulation-rendering.md
```

It should explain:

1. What belongs to the simulation
2. What belongs to rendering
3. How input reaches the simulation
4. How simulation state reaches rendering
5. What dependencies are intentionally allowed
6. What dependencies are forbidden
7. How this architecture can later become client/server
8. Which parts still depend on Pygame and why

Keep the document concise and practical.

---

# STEP 13 — Tests / verification

Add or update tests where practical.

At minimum verify that:

1. Simulation/domain modules can be imported without creating a Pygame display.
2. A simulation instance can be created without opening a window.
3. Simulation update can execute without the renderer.
4. Player commands can be passed into the simulation without direct Pygame access.
5. NPC updates do not require rendering.
6. Resident updates do not require rendering.
7. Pedestrian updates do not require rendering.
8. Traffic lights do not require rendering.
9. The normal Pygame game still runs.

If the project currently has insufficient test infrastructure, do not create a huge testing framework solely for this task. Add focused tests for the new architectural boundary.

---

# IMPORTANT DESIGN PRINCIPLES

Follow these principles throughout the implementation:

### 1. Do not rewrite working gameplay.

Refactor around it.

### 2. Do not prematurely design the multiplayer protocol.

That belongs to a later phase.

### 3. Do not introduce Godot, Panda3D, Ursina or another engine yet.

The current Pygame client remains the rendering client.

### 4. Do not serialize the entire world every frame.

We are creating an architectural boundary, not a network implementation.

### 5. Simulation must be authoritative.

Rendering is a consumer of simulation state.

### 6. Keep the refactoring incremental.

Prefer several small clean changes over one enormous architectural rewrite.

### 7. Preserve performance.

The refactoring must not make the current game slower.

---

# Expected end state

The architecture should conceptually look like this:

```
                PYGAME CLIENT
                     │
         ┌───────────┴───────────┐
         │                       │
      Input                  Rendering
         │                       ▲
         ▼                       │
    Commands                     │
         │                       │
         ▼                       │
  ┌──────────────────────────────────┐
  │          GAME SIMULATION         │
  │                                  │
  │ World                            │
  │ Traffic                          │
  │ NPCs                             │
  │ Residents                        │
  │ Pedestrians                      │
  │ Player                           │
  │ Physics                          │
  │ Missions                         │
  │ Weather                          │
  │ Time                             │
  │                                  │
  │         AUTHORITATIVE STATE      │
  └────────────────┬─────────────────┘
                   │
                   ▼
             Renderable state
```

Later, this should be able to evolve into:

```
          HEADLESS PYTHON SERVER
                   │
                   │ Game State / Commands
                   │
                   ▼
             3D GAME CLIENT
```

But that is explicitly NOT part of this task.

---

## Implementation workflow

Before changing code:

1. Inspect the repository.
2. Map the current architecture.
3. Identify the largest coupling points.
4. Explain the proposed incremental refactoring plan.
5. Then implement it.

Do not stop after producing an analysis. Carry out the refactoring.

After implementation:

1. Run the existing tests.
2. Run any new tests.
3. Verify the game starts.
4. Verify the main gameplay loop.
5. Check for obvious performance regressions.
6. Review imports for unwanted simulation → Pygame dependencies.
7. Review the git diff for accidental gameplay changes.

Finally provide:

* summary of architectural changes
* files changed
* remaining Pygame dependencies in simulation and why they remain
* tests performed
* any known limitations
* recommended next architectural step

Do not proceed to Phase 2 or introduce a new rendering engine unless explicitly requested.
