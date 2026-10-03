# Godot client (0.16.0g-alpha experiment)

Python stays the authoritative simulation. Godot (`godot/`) is a rendering,
input and UI client only. Pygame still works unchanged. There is no BIN; the
map comes from the existing OSM pipeline.

## Before and after

Before: `main()` ran the Pygame window, input, and the simulation in one loop.
`simulation.advance_simulation()` had already been split out (see
[simulation-rendering.md](simulation-rendering.md)), and a headless
`theroadragetrip.server` already broadcast `state` messages over loopback TCP.
Trains still ticked in the render section of `main()`.

After:

```text
                 Python Simulation  (theroadragetrip.server / main)
                       │
          ┌────────────┼────────────┐
          │            │            │
       World        Routing      Game Rules
  (OSM, trains,  (traffic_world)  (taxi, career,
   weather, time)                  collisions)
          │
     Simulation API   (protocol.py over transport.py, TCP + NDJSON)
          │
          ▼
     Godot Client  (godot/)            Pygame client (unchanged)
          │
    ┌─────┼─────┐
    │     │     │
 Render  Audio* UI      * events received, no playback yet
```

Trains now update inside `advance_simulation` (`RailwayManager` is built in
`_load_world`). Every simulation subsystem therefore runs in the headless
server too.

## Responsibilities

**Python:** world and OSM data, game time, NPC traffic, pedestrians, taxi
and career rules, trains, weather, routing, collisions. It validates every
command it receives.

**Godot:** drawing, camera, interpolation between states, keyboard input
turned into commands, the debug HUD. It has no game rules and no routing.

## Protocol (version 1)

Each message is one JSON object per line over a loopback TCP connection.
`protocol.py` builds explicit dicts; Python objects are never serialized
as-is.

| type | direction | when | content |
|---|---|---|---|
| `world` | server→client | once per connection | `center`, `radius_m` (2500), `roads` (`points`, `half_width_m`, `kind`, `drivable`, `layer`), `railways`, `waters`, `buildings` |
| `state` | server→client | every tick (30 Hz) | `tick`, game time, `player`, `on_foot`, NPCs, pedestrians, `trains` (`id`, `label`, `state`, `speed`, `cars` as `[x, y, heading, length, profile]`), weather, `events` |
| `command` | client→server | client-paced (Godot: 20 Hz) | `throttle`, `brake`, `steer`, `engine_on`, ..., `interact`, `seq` |

`events` are semantic and sent once each:
- `{"type":"sound","group":"vehicle.door_close"}`, recorded by `EventAudio`
  in place of real audio
- `train_arrived`, `train_departed` and the other train events, each with
  `station` and `train`

Coordinates are world metres. Godot subtracts the world `center` to stay
precise in float32.

## Lifecycle

1. The server loads the world and ticks at `--tick-rate`, whether or not a
   client is connected.
2. When a client connects, it receives `world` and then a `state` every tick.
3. The server applies the latest command at the start of each tick. It keeps
   only one shared player for all clients.
4. On disconnect the input resets to an idle command, so a held throttle
   stops. A reconnect receives `world` again. The Godot client retries
   every second.
5. A malformed line closes only that client's connection.

## Running

```bash
python -m theroadragetrip.server --preset Oulu --port 8765 --tick-rate 30
~/tools/godot/Godot_v4.7.2-stable_linux.x86_64 --path godot -- --port 8765
# automated check: add --selftest (prints a JSON report and exits)
python -m theroadragetrip --connect 127.0.0.1:8765   # Pygame client
```

Tests: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q tests/test_client_server_integration.py tests/test_server_headless.py`

## Measurements (Oulu, WSL2, one machine)

- Server tick: mean 3.9 ms, p95 5.6 ms, max 29 ms. The budget at 30 Hz is 33 ms.
- Building, encoding and sending a state with one client: 0.36 ms mean.
- `world`: 2.0 MiB (8,349 roads, 2,367 buildings), received in 0.29 s.
  Godot parses and builds it in 54 ms.
- `state`: about 19 KiB at 30/s, about 570 KiB/s. It carries 38 NPCs,
  13 pedestrians and up to 4 trains.
- Godot `state` handling: 0.5–0.6 ms. 31 fps windowed under WSLg.
- Server RSS: 207 MiB after loading, 232 MiB after 300 ticks with a client.

## Known limitations

- The game has no aircraft system, so there is nothing to send.
- The map is a one-off 2.5 km disc; there is no streaming when driving out of it.
- `state` is a full snapshot. Measured costs don't justify deltas yet.
- One shared player; not multiplayer.
- Godot has no audio playback and no real HUD. Events show only in the
  debug label.
- Interpolation uses arrival time, so jitter shows on a loaded machine.
- Map auto-fetch is disabled in server mode.

## Migration from Pygame

Keep both clients on the same server. Move one presentation feature at a
time: audio from events, then HUD, menus, and streaming map chunks. Use
Pygame as the visual reference. Retire Pygame only when the Godot client
covers everything.
