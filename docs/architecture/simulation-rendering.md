# Simulation / rendering boundary

Phase 1 of `.github/prompts/client-server-01.md`: separate the gameplay
simulation from Pygame rendering, incrementally, without changing
behavior. Not multiplayer, not a new renderer, not a real server yet.

## What belongs where

**Simulation** (`src/theroadragetrip/simulation.py`, plus the domain
modules it calls into - `physics.py`, `taxi.py`, `npc.py`, `pedestrian.py`,
`traffic_world.py`, `traffic_rules.py`, `weather.py`, `career.py`,
`world_cache.py`, `geo.py`, `roadworks.py`, `police.py`,
`activities/*`, `vehicles/*`): car/pedestrian physics, collisions,
camera-follow targeting, and the taxi/NPC/traffic/pedestrian manager
ticks. None of these import pygame.

**Rendering/client** (`main/__init__.py`'s `main()`, `render/*`,
`audio.py`): the Pygame window, event dispatch, menus, HUD dragging and
F-key toggles, the tile-streaming/map-sync pipeline (it pumps Pygame
events during a fetch via `_wait_for_active_tile_fetch`), the ~40-call
draw sequence, and sound (`audio.py` wraps `pygame.mixer`).

This was already close to true before this phase - an earlier audit found
every domain module pygame-free except `audio.py`. What was missing was a
*seam*: `main()` ran physics, collisions, camera follow and the manager
ticks inline in one 1875-line function, so nothing outside `main()` could
call just the simulation part. That inline block is now
`simulation.advance_simulation()`.

## Input → simulation

Raw `pygame.key.get_pressed()` state is read once per frame in `main()`
and converted into a `simulation.PlayerCommand` (throttle/brake/steer for
driving, forward/turn/sprint for walking) before crossing into
`advance_simulation()`. Simulation code never reads Pygame key constants.

## Simulation → rendering

`advance_simulation(dt, command, car, world, ...)` mutates `car` and the
manager objects on `world` in place (they already owned their own state)
and returns a small `SimulationFrameResult` for the handful of scalars
`main()` still needs (camera position, current road, a few accumulators,
and outer-loop control flags for career/city transitions). `main()`
copies those back into its own locals and the unchanged render block
reads `car`/`world`/camera/time - it only ever reads simulation state,
never mutates it, so no separate "renderer" abstraction was needed to make
that true; it already was.

`world` (a `SimpleNamespace` built by `_load_world()`, aggregating ways,
buildings, spatial grids and the four managers) is reused as-is rather
than introducing a parallel `GameState` type - it already is that object.

## Allowed / forbidden dependencies

- `simulation.py` must never `import pygame`, directly or indirectly.
  Enforced by `tests/test_simulation_boundary.py` (AST-checks its own
  import statements - see the caveat below about the package `__init__`).
- `audio.py` may import `pygame.mixer`; `simulation.py` never imports
  `audio` - it receives an `audio` object as a parameter and calls
  `audio.play(...)`/`audio.play_driver_line(...)` etc. on it, so sound
  cues stay a rendering/client-side effect triggered by simulation events,
  not a simulation dependency.
- `render/*` and `main/*` may import pygame freely; they are the client.

**Caveat:** `theroadragetrip/__init__.py` (the top-level package) eagerly
imports `.main` and `.render`, both of which import pygame - so
`import theroadragetrip` always pulls pygame into `sys.modules` today,
even if only `theroadragetrip.simulation` is needed. This predates this
refactor and wasn't touched (fixing it means restructuring the package's
public API, a separate and riskier change). A real headless deployment
would `import theroadragetrip.simulation` directly and simply requires
pygame to be *installed* (it already is, for `audio.py`), not *used*.

## Remaining Pygame coupling in the gameplay loop, and why

- `main()`'s event-dispatch loop, HUD dragging, menu sub-loops, F-key
  toggles, and the ~11 scattered `pygame.quit()`/`sys.exit()` exit paths
  in menu helpers: genuinely client-only, untouched by design (the spec
  explicitly warns against unnecessary reorganization).
- The tile-streaming/map-sync stage machine: stays in `main()` because it
  calls `_wait_for_active_tile_fetch()`, which pumps Pygame events and
  draws a loading indicator during a live fetch. It's world-loading
  infrastructure, not a per-tick simulation concern.
- Tire-track/skidmark and puddle-splash bookkeeping: kept in `main()` -
  purely visual effects with no gameplay consequence (they don't affect
  physics, scoring, or missions), and `TireTrail` is defined in
  `render/roads.py`, which itself imports Pygame-touching code from
  `render/common.py`. Importing it into `simulation.py` would have pulled
  a transitive Pygame import chain into the one module that's supposed to
  have none, for a feature with zero gameplay effect.
- Camera-follow lerp: computed inside `advance_simulation`, even though a
  future multi-client architecture would more naturally own per-viewer
  camera state on the client, not the server. Splitting it out now would
  have meant threading `viewport_bounds` (needed by the NPC/pedestrian
  manager updates for spawn/despawn culling) across two separate calls
  into `main()` for no present benefit; left as a documented future step.

## Headless proof-of-concept

`--headless N` (`main/cli.py`) runs the normal startup and world-loading
path, then instead of entering the interactive per-frame loop, calls
`advance_simulation()` N times with a no-op `PlayerCommand` and exits -
see `_run_headless_ticks()` in `main/__init__.py`. It opens no rendering
surface beyond what world-loading's progress screen already uses (running
under `SDL_VIDEODRIVER=dummy` makes that a no-op in practice). This is a
proof that the boundary holds end to end, not a production server -
there is still one process, one world, no networking.

## Known limitations / future work

- The four managers (`taxi_mgr`, `npc_manager`, `traffic_mgr`,
  `pedestrian_mgr`) still mutate themselves in place rather than through
  an explicit command/event interface - fine for one authoritative
  in-process simulation, but a real client/server split would need those
  mutations to become diff-able/replicable state, not just "call
  `.update()` and trust it mutated the right things."
- No fixed timestep - `dt` is still wall-clock-derived and clamped, as
  before. A deterministic server tick (for replay or rollback netcode)
  would need this revisited.
- Camera-follow is still simulation-side (see above) - a real multi-
  client future should move it client-side.
- The package's eager `import theroadragetrip` pulling in pygame (see
  caveat above) should eventually be trimmed if a real headless
  deployment needs to avoid a pygame dependency at import time, not just
  at runtime.
