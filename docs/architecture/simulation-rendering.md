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

## Known limitations / future work (Phase 1)

- No fixed timestep - `dt` is still wall-clock-derived and clamped, as
  before. A deterministic server tick (for replay or rollback netcode)
  would need this revisited.
- The package's eager `import theroadragetrip` pulling in pygame (see
  caveat above) should eventually be trimmed if a real headless
  deployment needs to avoid a pygame dependency at import time, not just
  at runtime.

---

# Phase 1.5: restore direct single-process execution

`.github/prompts/client-server-015.md`. Phase 2 (below) made the
client/server split the *only* way to play, even for normal single-player
gameplay - every frame paid for a real loopback TCP round-trip, JSON
encode/decode, and shadow-object reconciliation, competing with the
render thread for the GIL. That caused a measurable FPS regression,
stuttering, and a class of crashes specific to `ShadowVehicle`/
`ShadowPedestrian` missing fields the real objects have (see git history
around `3743217`, `da4d61e`, `8ced23b`). Phase 1.5 keeps the Phase 1
boundary (`simulation.py`/`advance_simulation()`/`PlayerCommand` are
untouched) but makes the client/server hop opt-in rather than mandatory.

The architecture now has two modes:

## Normal single-player (default: `python -m theroadragetrip`)

```
Pygame client (main/__init__.py)
     │
     ▼
PlayerCommand
     │
     ▼
advance_simulation()   (direct, in-process call)
     │
     ▼
Renderer
```

All in one process, one thread. `main()`'s per-frame loop calls
`simulation.advance_simulation()` directly - the exact same function
`SimulationServer.tick()` and `_run_headless_ticks()` already call - and
renders the real `car`/`npcs`/`pedestrian_mgr`/etc. objects it mutated in
place. No `SimulationServer` is created, no thread is spawned, no socket
is opened, no JSON is encoded or decoded, and `protocol.py`/
`ShadowVehicle`/`ShadowPedestrian`/`interpolate_state`/
`apply_server_state` are never imported or called on this path. `main()`
no longer imports `theroadragetrip.server` at all in this mode - see
`tests/test_single_player_architecture.py`.

## Experimental / future client-server (opt-in: `--connect HOST:PORT`)

```
SimulationServer (python -m theroadragetrip.server)
      │
 loopback/remote TCP, protocol.py
      │
Pygame client (--connect)
```

Unchanged from Phase 2 below - still real, still tested
(`test_client_server_integration.py`, `test_server_headless.py`,
`test_shadow_entities_render.py`), but now reachable only by explicitly
passing `--connect`. This mode must never affect normal single-player
performance, and per the code review that closed out Phase 1.5, it
doesn't: `main()`'s default branch never references `SimulationServer`,
`Listener`, `apply_server_state`, or `interpolate_state` at all.

Why the single-player path intentionally avoids IPC/network
serialization: there is exactly one player, one process, and one
authoritative world - a socket, a wire format, and a client-side shadow
copy of every dynamic entity all exist to solve problems (multiple
independent consumers, an untrusted/remote peer, decoupled update rates)
that don't exist yet for this case. Paying that cost unconditionally,
every frame, for zero benefit is exactly what caused the regression this
phase fixes.

---

# Phase 2: headless simulation server + Pygame client

**Status as of Phase 1.5: experimental / future architecture, opt-in via
`--connect` only - see the section above. It is no longer what a normal
single-player launch does.**

`.github/prompts/client-server-02.md` takes the next step: the
`advance_simulation()` tick Phase 1 extracted can run in an independent
process - `SimulationServer` - with the Pygame app as a real network
client of it (`--connect`), never calling `advance_simulation()` itself.

```
                 SimulationServer (src/theroadragetrip/server/)
                 owns: world, car - the one authoritative state
                 loop: fixed-rate tick -> advance_simulation() +
                       apply_enter_exit_vehicle()
                              |
                    loopback TCP, newline-
                    delimited JSON, versioned
                    envelope (protocol.py)
                              |
                 Pygame client (main/__init__.py)
                 input -> PlayerCommand -> sent
                 received state -> shadow objects -> rendered
                 (never runs NPC/pedestrian/traffic AI itself)
```

**As of Phase 1.5, this is opt-in only** (`--connect`) and split-process
is the only supported shape - `main()` no longer embeds a
`SimulationServer` in a background thread of its own process the way it
did between Phase 2 and Phase 1.5 (that embedding code, and the
`threading.Thread(target=server.run_forever)` call it used, were removed
entirely; `SimulationServer`/`transport`/`protocol` are simply not
imported by a normal launch at all now):

```
python -m theroadragetrip.server [world args] [--host] [--port] [--tick-rate]
```

in one terminal, then

```
python -m theroadragetrip --connect HOST:PORT [same world args]
```

in another. The client forces `--no-menu` in this mode and independently
resolves the same world from its own args - see "Known limitations." The
server process's own `server/__main__.py` just calls
`SimulationServer.run_forever()` directly, blocking its one thread - no
threading involved on the server side either.

## Server responsibilities

`SimulationServer` (`src/theroadragetrip/server/__init__.py`) owns
`world`/`car` (built via `_load_world(..., headless=True)`), runs the
tick loop, applies the latest received command (and any queued `interact`
edge-triggers) each tick, and broadcasts a state snapshot to every
connected client afterward. It never opens a Pygame display.

## Client responsibilities

`main()` still owns the Pygame window, event dispatch, menus, camera,
audio, HUD, and the full render sequence, unchanged from Phase 1. Per
frame it: reads input into a `PlayerCommand`, sends it, applies the
latest (interpolated) received state onto local shadow objects via
`protocol.apply_server_state`, and renders. It independently loads the
same static map geometry `_load_world()` always built, but immediately
discards the auto-populated starting NPCs/pedestrians - from then on
those lists are only ever mutated by state reconciliation, never by
calling a manager's own `.update()`/AI methods.

## Command flow (client -> server)

Raw Pygame input becomes a `simulation.PlayerCommand` (throttle/brake/
steer/forward/turn/sprint, plus the V/B toggles) exactly as in Phase 1,
plus one edge-triggered `interact` flag for the 'F' enter/exit action -
never a raw `pygame.KEYDOWN`/`pygame.key.get_pressed()` result.
`protocol.build_command_message` wraps it in the versioned envelope;
`transport.LineJSONConnection.send` writes it as one JSON line. The
server's per-connection reader thread decodes it and stores it as the
latest command (continuous input is latest-wins - the same shape
`pygame.key.get_pressed()` already has - while `interact` is queued so a
quick tap between ticks is never dropped).

## State flow (server -> client)

After each tick, `protocol.build_state_message` serializes exactly the
dynamic fields the renderer reads (catalogued via `render/*`'s actual
attribute access, not guessed): player car, NPCs/pedestrians by stable
id, `sim_time`, weather type/wetness, taxi/HUD fields, camera position,
rage/water HUD meters, and career-transition flags. The client blends
the last two received snapshots via `protocol.interpolate_state` (linear
position lerp, shortest-path angle lerp for headings) before applying,
for smoother-than-tick-rate rendering - visual only, never fed back as
authoritative.

## Static vs dynamic data

Static geometry (ways, buildings, waters, spatial grids, ...) is loaded
independently by each process via the ordinary `_load_world()` path and
never crosses the wire. Only dynamic gameplay state crosses it - see the
state message contents above. `protocol.py`'s `_npc_to_dict`/
`_pedestrian_to_dict`/etc. functions are the single source of truth for
exactly what's considered "dynamic" here.

## Protocol structure

`protocol.py`: a versioned envelope (`{"type", "version", ...}`) over
newline-delimited JSON. `encode`/`decode` are the only functions that
know it's JSON - a future binary encoding would only touch this module,
per the spec's explicit "don't make the protocol architecture dependent
on JSON." No pickle, no raw Python objects on the wire, ever.

## Simulation tick vs. rendering frame rate

The server ticks at a fixed configured rate (`--tick-rate`, default
30Hz) via `pygame.time.Clock`-paced `time.sleep`, independent of any
client's render rate. The client renders at whatever FPS Pygame's own
clock gives it, applying whatever the latest received (and interpolated)
state happens to be - it never blocks waiting for a tick, and the server
never waits for a render.

## Connection lifecycle

`transport.connect()` raises a plain `socket.error` if the server is
unreachable (a controlled failure, not a bare traceback further up the
stack - callers should catch it, though `main()` doesn't yet wrap this
in a user-facing error message, see limitations). A malformed or wrong-
protocol-version message closes just that one connection
(`LineJSONConnection._read_loop` catches `protocol.ProtocolError`) rather
than crashing the read thread. A closed/dropped connection is pruned
from the server's client list on the next tick.

## Current transport, and why

Loopback TCP (`transport.py`, stdlib `socket`+`threading`+`queue`) rather
than a Unix domain socket, so the exact same code works on Windows (this
project ships Windows builds) without a platform branch, and is already
"compatible with future network transport" by construction - promoting
it to a real remote server later only means changing the host argument
from `127.0.0.1`.

## Why not MQTT

MQTT is a pub/sub broker protocol meant for many independent subscribers
and at-least-once delivery guarantees over an unreliable network - this
is one client on localhost needing the *newest* state, not a guaranteed
delivery log of every one. It would add a broker dependency and a
heavier per-message envelope for no benefit here; the spec explicitly
scopes it out. Nothing here precludes adding it later for something it's
actually suited to for a specific future need (e.g. cross-machine
matchmaking metadata), just not as the real-time game-state transport.

## Supporting a future non-Pygame client

`SimulationServer` has no idea what's on the other end of a connection -
it only ever sees `PlayerCommand`-shaped dicts in and sends dynamic-state
dicts out. A Godot/Panda3D/whatever client would implement its own
`protocol.py`-equivalent decoder in its own language and connect the same
way; nothing server-side would change.

## What a real remote multiplayer server would still need

This phase deliberately doesn't build: per-client authentication/
identity, more than one player's command stream being merged into one
authoritative tick (today: one active command slot, "latest wins"),
per-client visibility/relevance filtering (today: every connected client
gets the same full dynamic snapshot), reconnection/session resumption,
and a transport that tolerates real network latency/loss/reordering (TCP
buys ordering and delivery already; interpolation exists but there's no
lag compensation or client-side prediction). The versioned envelope and
the static/dynamic split are the parts meant to survive that future work
unchanged.

## Known limitations (Phase 2)

- **Auto-fetch/live map expansion is disabled server-side.** The tile-
  streaming pipeline's `_wait_for_active_tile_fetch` has its own Pygame
  loading-screen dependency, not yet isolated the way `_load_world`'s
  was - `SimulationServer` forces `args.auto_fetch = False`. The world
  stays fixed to whatever bbox was initially loaded.
- **Audio, dialogue, and subtitles are not wired across the boundary.**
  `advance_simulation`'s audio cues (crash sounds, driver/passenger
  lines) are called against the server's `NullAudio` stub, a pure no-op
  - the client's own `AudioManager` never hears about them. Fixing this
    would mean recording which cues fired server-side each tick and
    replaying them client-side, not yet built.
- **Some `taxi_mgr` visual-only state isn't synced**: vomit puddles,
  fallen-tree state, and speed-camera flash timing stay at their freshly-
  constructed client-side defaults, since `protocol.py` only syncs the
  fields HUD/target rendering actually reads.
- **Career-mode session-end city transitions aren't fully wired.** The
  server computes `should_stop`/`city_summary` correctly and sends them,
  and the client will show the summary and end its session, but it won't
  automatically reconnect to a freshly reloaded next city the way the
  single-process game used to loop - the split-process (`--connect`)
  case in particular has no way to tell a separately-running server
  process to load a different city at all yet.
- **F6 NPC camera-follow debug toggle is inert** in client/server mode -
  `SimulationServer` hardcodes `npc_follow=False`; wiring a debug-only
  toggle through the command protocol wasn't judged worth the surface
  area this phase.
- **`--connect` requires matching world-selection args on both
  processes** (bbox/preset/use-sample/etc.) - there's no handshake where
  the server tells a connecting client which world to load; the operator
  is responsible for starting both with the same flags.
- Camera-follow lookahead is still computed server-side and sent as
  `camx`/`camy` (see Phase 1's note above) - a real multi-client future
  should move this client-side, where per-viewer camera state actually
  belongs.
- A `--connect` target that's unreachable (wrong host/port, server not
  started yet) is caught in `main()` and logged as a clear error before
  exiting, rather than a raw traceback.
