# Godot client (0.16.0g-alpha experiment)

Python stays the authoritative simulation. Godot (`godot/`) is a rendering,
audio, UI and input client only. Pygame still works unchanged. There is no
BIN; the map comes from the existing OSM pipeline.

## Architecture

```text
                 Python simulation (theroadragetrip.server)
                                │
     ┌──────────────┬───────────┼────────────┬──────────────┐
     │              │           │            │              │
 OSM world →   advance_simulation:  taxi, career,   events (EventAudio,
 map_chunks.py  traffic, people,    fares, weather,  train arrivals)
 (chunk grid)   trains, physics     game time
     │                          │                           │
     └──────── TCP, one JSON message per line (protocol.py) ┘
                                │
                                ▼
                 Godot client (godot/)
   SimClient ── world / chunk / state / chunk_unload ──┐
      ▲                                                │
      │ command (player_id)              ┌─────────────┼──────────────┐
      │                                  ▼             ▼              ▼
   main.gd ◄── input             MapLayer        StateBuffer      (events)
      │                          + MapChunk      (interpolation)      │
      ├── Camera2D follows ◄──── EntityLayer ◄───────┘                ▼
      ├── HUD (hud.gd) ◄──────── shown state                    AudioManager
      └── F3 debug readout                                (audio_events.json →
                                                            game sound catalog)

 Pygame client (python -m theroadragetrip [--connect]) - unchanged, reference
```

Before this experiment, `main()` ran the Pygame window, input and the
simulation in one loop. `simulation.advance_simulation()` had already been
split out (see [simulation-rendering.md](simulation-rendering.md)), and a
headless server already broadcast states. Phase 1 moved trains into
`advance_simulation`. Phase 2 added interpolation, audio, the HUD, map
streaming and player identity.

## Responsibilities

**Python:** world and OSM data, which map chunks a client needs, game time,
NPC traffic and AI, pedestrians, taxi and career rules, fares, trains and
timetables, weather, routing, collisions. It validates every command and
emits semantic events.

**Godot:** drawing, camera, interpolation, sound, HUD, and turning keys into
commands. Godot never decides a route, a collision, a fare, a schedule,
the weather or the time. It only displays what the state says.

## Protocol (version 1)

Each message is one JSON object per line, over loopback TCP. `protocol.py`
and `map_chunks.py` build explicit dicts; Python objects are never
serialized as-is.

| type | direction | when | content |
|---|---|---|---|
| `world` | server→client | once per connection, first | `center` (map origin), `chunk_size_m` (500), `player_id` |
| `chunk` | server→client | when the player's chunk changes | `chunk_id` (`"ix_iy"`, ix = floor(x/500)), `bounds`, `roads` (`points`, `half_width_m`, `kind`, `drivable`, `layer`), `railways`, `waters`, `buildings` |
| `chunk_unload` | server→client | same | `chunk_id` |
| `state` | server→client | every tick (30 Hz) | `tick`, `server_time` (simulation seconds), `state`: `player_id`, game time, `player`, `player_pedestrian`, `on_foot`, `npcs`, `pedestrians`, `trains` (`id`, `label`, `state`, `speed`, `cars` as `[x, y, heading, length, look]`), `weather`, `taxi`, `events` |
| `command` | client→server | client-paced (Godot: 20 Hz) | `seq`, `player_id`, `command` (`throttle`, `brake`, `steer_*`, `forward`, `turn`, `engine_on`, ..., `interact`) |

`events` are each sent once:
- `{"type":"sound","group":"vehicle.door_close","at"?:[x,y]}`, recorded by
  `EventAudio` in place of real audio
- `train_arrived` and `train_departed`, each with `at`, `station` and `train`

Coordinates are world metres (x east, y north). Godot subtracts the world
`center` and flips y to stay precise in float32 (`MapMath.point`).

## Interpolation (`state_buffer.gd`, `entity_layer.gd`)

- Each state goes into a buffer keyed by `server_time`. Duplicate and
  out-of-order ticks are dropped. The buffer holds 16 states.
- The client estimates the offset between server and local clocks and
  smooths it, so arrival jitter doesn't move the timeline. It snaps the
  offset after a jump of more than 0.25 s, such as a server restart.
- Every frame draws at `render_time = now + offset − delay`, between the
  two states around it:
  - position is linearly interpolated
  - heading uses `lerp_angle`, which turns the short way across ±π
  - each train car is interpolated when the car count is unchanged
  - pedestrians, NPCs, the taxi and the walking player are all interpolated
- Discrete values come from the earlier state: whether an entity exists,
  colour, train composition, HUD text, weather.
- Past the newest state, the picture holds still and counts an underrun.
  There is no extrapolation or prediction.
- **Delay:** 100 ms by default, set with `--interp-delay-ms`. States come
  every 33 ms. One interval is needed to have the next state; two more
  absorb late or bunched states. Measured: 0 underruns in 6 s windowed,
  2 in 6 s headless (about 870 frames).
- Events are released when the render time reaches their state, so sounds
  match the picture. Each one is released once.
- Aircraft: the simulation has none, so there is nothing to interpolate.

## Audio (`audio_manager.gd`, `audio/audio_events.json`)

All client sound goes through `AudioManager`.
- `handle_event(event)` plays an event's one-shots.
- `set_loop(key, volume, pitch)` drives continuous sounds from the shown
  state:
  - engine: pitch rises with speed
  - city day and night ambience: crossfaded by game time
  - rain: on while the weather is rain
- `set_bus_volume(bus, linear)` sets a bus volume.

Buses are created at start: Master > Game, Environment, UI.

Event-to-sound mapping is data. `audio_events.json`:
- maps `train_arrived` to brakes plus doors open, and `train_departed` to
  doors closing plus horn, the same as Pygame's `_play_rail_sounds`
- passes every `sound` event straight through to the catalog group of
  that name
- assigns catalog categories to buses
- copies the hearing ranges from `audio.py`'s `SPATIAL_RANGES_M`

Files come from the game's own catalog
(`src/theroadragetrip/assets/audio/audio_catalog.json`, 118 generated
`.ogg` files). They are loaded at runtime from there, not copied into
`godot/`.

Placement:
- Sounds with `at` are `AudioStreamPlayer2D` nodes at that spot, silent
  beyond the configured range. The camera is the listener.
- The taxi's own sounds (`vehicle.`, `taxi.`, ...) without `at` come from
  the player.
- An event with no sound is counted in `unhandled` and logged once. It is
  never faked.

## HUD (`hud.gd`, `Ui/Hud` in `main.tscn`)

Godot `Control`, `Label` and container nodes.
- `values(state)` is a pure state-to-text mapping: clock, money, speed,
  weather and wetness, the fare (pick up, walking or drive to, built from
  the server's taxi state and passenger), the simulation's notice, and an
  interaction hint.
- Every field is optional; missing ones show placeholders.
- It shows the same state the picture shows.
- F3 toggles the developer readout: tick, fps, buffer and underruns,
  timings, chunks, sounds, recent events.

## Map streaming (`map_chunks.py`, `map_layer.gd`, `map_chunk.gd`)

- `ChunkIndex` buckets the world's existing OSM objects (`ways`,
  `railways`, `waters`, `buildings`) by 500 m cell. It is built once, the
  first time a client needs it. A feature belongs to every chunk where it
  has a vertex.
- Each tick, the server finds the player's cell. When it changed for a
  connection, `plan()` works out what that client needs:
  - send every chunk within 3 cells (7×7, at least 1.5 km in each
    direction), nearest first
  - unload chunks more than 4 cells away; the gap stops chunks reloading
    back and forth at a border
- The server tracks which chunks each connection has, so nothing is sent
  twice. A reconnect starts from empty.
- The client adds and removes chunks as told. Each chunk is its own
  canvas item, drawn once, so the others never redraw. A duplicate chunk
  is ignored.
- Water is drawn one z-level below roads and buildings, so another
  chunk's lake can't cover a bridge.
- The client doesn't request chunks; Python decides, because it knows
  the player position.

## Player identity

- The `world` header assigns `player_id`; today that is always
  `local_player`.
- Commands carry `player_id`. The server ignores commands for any other
  player. A command without one, from an older client, counts as
  `local_player`.
- States say whose `player` and `taxi` they describe.
- There is no multiplayer, no accounts, and no second player.

## Running

```bash
make run-godot-all                      # server (PRESET=Oulu PORT=8765) + Godot window
make run-server   /   make run-godot    # separately
make godot-selftest                     # server + headless Godot: drive 6 s, JSON report
make godot-test                         # Godot unit tests, no server
python -m theroadragetrip --connect 127.0.0.1:8765   # Pygame client on the same server
```

Python tests: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q`
(see `tests/test_client_server_integration.py` and `tests/test_map_chunks.py`).

## Measurements (Oulu, WSL2 on one machine; native Windows not measured)

| what | measured |
|---|---|
| Server tick (600 ticks, one client) | mean 4.0 ms, p95 4.9 ms, max 38.5 ms (budget 33 ms) |
| State build / JSON encode | 0.08 / 0.16 ms mean |
| State message | 15.7 KiB mean, 18.1 max, 30/s (~470 KiB/s) |
| Chunk index build (once) | 177 ms; 187 chunks have content; 35 KiB mean, 204 KiB max |
| First tick with a new client | 281 ms (index build plus 49 chunks sent in the tick) |
| Server RSS | 207 MiB loaded, 240 MiB after 600 ticks |
| Godot state handling (parse + buffer) | 0.50 ms windowed, 0.36 ms headless |
| Godot interpolate + draw entities | 0.35 ms windowed, 0.16 ms headless |
| Godot FPS | 64 windowed under WSLg, 145 headless |
| Rendered entities | 44 (2 trains, 6–8 NPCs, ~35 pedestrians, taxi) |
| Loaded map chunks | 49 at start, 56 after crossing a chunk border |
| Godot static memory | 67 MiB windowed, 58 MiB headless |
| Underruns (6 s, while driving) | 0 windowed, 2 headless |

Full snapshots stay: about 16 KiB per tick costs well under a millisecond on
both sides. Deltas aren't justified yet.

## Known limitations

- **A new client stalls the tick loop.** Chunks are sent from it with
  blocking `sendall`: 281 ms on the very first connection, about 100 ms on
  later ones. A client that stops reading would block the simulation;
  this was already true for states.
- A road with no vertex inside a chunk it crosses isn't drawn there. This
  needs a very long OSM segment.
- Chunks of a large water polygon overlap each other (drawn more than once).
- No map beyond the loaded OSM area; `--auto-fetch` is off in server mode.
- Single player only, though identified by `player_id`.
- Engine sound is the idle loop pitched by speed, simpler than Pygame's
  rev layers.
- No station announcements or passenger speech in Godot yet.
- No aircraft in the game.
- The HUD covers basics only: no phone, offers, bookings, menus or map
  overlay.
- Godot audio played in headless tests (dummy driver); it hasn't been
  listened to.
- Native Windows performance not measured.

## Migration from Pygame

Keep both clients on the same server. Move one presentation feature at a
time, with Pygame as the visual reference:
1. phone and offer UI
2. station announcements
3. sprites
4. menus

Retire Pygame only when the Godot client covers everything.
