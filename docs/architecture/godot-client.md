# Godot client (0.16.0g-alpha experiment)

Python stays the authoritative simulation. Godot (`godot/`) is a rendering,
audio, UI and input client only. Pygame still works unchanged. There is no
BIN; the map comes from the existing OSM pipeline.

## Architecture

```text
                         Python simulation (theroadragetrip.server)
                                       │
                                simulation tick (30 Hz, one thread)
            ┌──────────────────────────┼─────────────────────────────┐
            │                          │                             │
   map chunks (map_chunks.py,   advance_simulation: traffic,   events (EventAudio,
   built + JSON-encoded once    people, trains, taxi, weather   train arrivals)
   at startup)                         │                             │
            └───────── enqueue, never write ───────────────────────────┘
                                       │                    ▲ commands (player_id),
                    per client (transport.LineJSONConnection)  read by a reader thread
               ┌───────────────────────┴───────────────────────┐
               │ FIFO: world, chunk, chunk_unload  (≤ 256)      │
               │ + one pending state (newest; events merged)    │
               └───────────────────────┬───────────────────────┘
                                 sender thread  ── partial writes, stall timeout
                                       │
                                  TCP socket (loopback, JSON lines)
                                       ▼
                                 Godot client (godot/)
   SimClient ─► MapLayer/MapChunk   StateBuffer ─► EntityLayer ─► Camera2D
                                         │
                            HUD (hud.gd) ◄┴► AudioManager (audio_events.json → game sound catalog)
                                              buses: Master > Game, Environment, UI

 Pygame client (python -m theroadragetrip [--connect]) - unchanged, same transport
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
| `command` | client→server | client-paced (Godot: 20 Hz) | `seq`, `player_id`, `command` (`throttle`, `brake`, `steer_*`, `forward`, `turn`, `engine_on`, ..., `interact`), optional `phone` request |

`events` are each sent once:
- `{"type":"sound","group":"vehicle.door_close","at"?:[x,y]}`, recorded by
  `EventAudio` in place of real audio
- `train_arrived` and `train_departed`, each with `at`, `station` and `train`
- `phone_result`, the answer to a phone request

Coordinates are world metres (x east, y north). Godot subtracts the world
`center` and flips y to stay precise in float32 (`MapMath.point`).

## Outgoing network traffic (`transport.py`)

The simulation tick never writes to a socket. Each connection
(`LineJSONConnection`, used by the server and by Pygame's `--connect` client)
has its own reader thread and its own sender thread. A slow client therefore
only ever holds up its own sender.

| server code | message | how it leaves |
|---|---|---|
| `_on_client_connect` (accept thread) | `world` | `send()`: reliable FIFO |
| `_stream_map_chunks` (tick) | `chunk_unload`, then `chunk` (pre-encoded bytes, nearest first) | `send()`: reliable FIFO |
| `_broadcast_state` (tick) | `state` | `send_state()`: the pending-state slot |

- **Reliable FIFO.** World, chunks and unloads are delivered once each, in
  queue order. The FIFO is bounded at `MAX_QUEUED_MESSAGES` (256; the
  initial map is 49). If a `send()` would overflow it, that client is
  disconnected (`ConnectionError("outgoing queue full")`).
- **State coalescing.** There is a single pending-state slot. A new state
  replaces one not yet written, and the replaced state's one-shot `events`
  are prepended to the new one's. A client that falls behind gets the
  newest state and every event; a normal client, whose sender takes each
  state before the next arrives, sees every state. The `coalesced_states`
  counter shows how often this happened.
- **Sender.** The sender waits on a condition variable. It writes every
  queued reliable message before the pending state. It writes with
  `socket.send` on a 0.25 s socket timeout, continuing partial writes from
  where they stopped.
- **Stall timeout.** If no bytes are accepted for `SEND_STALL_TIMEOUT_S`
  (10 s), the client is disconnected (`TimeoutError("client stopped
  reading")`).
- **Errors.** A socket error ends the connection and is logged. The
  connection is marked `is_closed` with `error` set, and both threads end.
- **Cleanup.** The next tick removes closed connections, their chunk
  records and their last input, and logs why each client went.
- **Memory bound per client:** 256 messages (chunks are at most 204 KiB
  each, 35 KiB on average), one state, and the kernel socket buffer.

**Ordering guarantees**
- For a new client: `world` is queued at accept, before the connection
  joins the client list. The tick after that queues its chunks and then
  sets its first state. Because the sender drains the FIFO before the
  state slot, the client sees `world → 49 chunks → state`, and is tested
  for it.
- Chunk loads and unloads for the same client share the FIFO. They arrive
  in the order Python planned them, and a chunk is never unloaded before
  it was sent.
- A state can be followed by chunks queued later, which is harmless.
- States arrive in increasing tick order; coalescing only skips ticks.
  Godot's `StateBuffer` drops anything out of order anyway.

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
  absorb late or bunched states.
- **Clock offset:** smoothed asymmetrically. A state arriving later than
  expected pulls the offset in at 50%; an early one only at 5%.
  `server_time` is simulated time, and a late server tick is never caught
  up, so the server clock slips behind for good. With 5% both ways the
  render time briefly overtook the newest state: 1–5 underrun frames of up
  to 7 ms in 6 of 10 selftests, although state gaps were only 41–62 ms.
  After the fix: 0 in 10 of 10.
- The selftest reports underrun episodes, the longest one, and the largest
  gap between arriving states.
- Events are released when the render time reaches their state, so sounds
  match the picture. Each one is released once.
- Aircraft: the simulation has none, so there is nothing to interpolate.

## Audio (`audio_manager.gd`, `audio/audio_events.json`)

All client sound goes through `AudioManager`.
- `handle_event(event)` plays an event's one-shots.
- `set_loop(key, volume, pitch, at)` drives continuous sounds from the
  shown state. Each loop is started once, then only adjusted:
  - engine: pitch rises with speed
  - city day and night ambience: crossfaded by game time
  - rain: on while the weather is rain
  - train rumble: a positional loop at the nearest moving train
- `stop_loops()` runs when the simulation disconnects.
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

Every sound the client plays is a Stable Audio Open OGG from that catalog.
In godot-03 the last three legacy Freesound effects were replaced:
- door open (a FLAC Godot couldn't load)
- the day city bed
- the pedestrian curse

See `docs/audio/stable-audio-replacements.json` (plan, reasons,
comparison) and `docs/audio/stable-audio-assets.json` (how each file was
made). The old files were deleted after the listening review passed.

How sounds are chosen:
- A sound's bus comes from its group's category.
- A one-shot picks a random variation, never the same one twice in a row
  (as `audio.py` does).
- A loop plays a fixed variation, default the first. With
  `"variation": "alternate"` it picks a new one each time it (re)starts,
  never the previous one. The day bed uses this, as Pygame does with
  `set_loop(..., variation=None)`, so its two generated loops alternate
  from one morning to the next.

`make audio-check` (`tools/validate_audio_assets.py`) fails on:
- missing, non-OGG or duplicated files
- clips that are silent (below −70 dBFS; quiet beds are fine), or much
  shorter or longer than the group's `duration_s`
- loops that aren't stereo, or one-shots that aren't mono
- groups that the game code or `audio_events.json` play but that don't
  exist or are empty
- Godot loops naming a missing variation

`make godot-test` loads every catalog file through Godot's own OGG loader.

Packaging: the Windows PyInstaller build copies `assets/` whole. The
Python wheel's `package-data` used to be `assets/*`, which left out every
subfolder: no sounds, no catalog, no announcements. It is now
`assets/**/*`, guarded by `tests/test_packaging.py`.

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

## Phone and offers (`phone.gd`, `Ui/Phone` in `main.tscn`)

The simulation owns the phone's content. `TaxiManager.phone_items()` lists
rail bookings first, then ride offers, at most 3. Offers appear on the
simulation's own timer (10–60 s) and expire after 30–90 s. Bookings follow
`rail_bookings.py`: PENDING, then ACCEPTED, then the train's progress, or
DECLINED or MISSED.

**State.** Each state carries `phone: {busy, items}`, built like Pygame's
`draw_phone_offers` shows them:
- offers: `id` "offer-N" (a stable `TaxiOffer.offer_id`), name, pickup,
  dropoff, `pickup_distance_m`, `trip_distance_m`, `time_remaining_s`
- bookings: `id` "booking-N", train, station, arrival, dropoff,
  `surcharge_cents`, status

An ordinary offer has no fare until the taximeter runs, so the UI says
"unavailable". `busy` means a fare is under way; no new offers come then.

**Requests.** A command may carry `phone: {action: accept|reject, item_id,
request_id}`; `SimClient.send_phone` sends it on top of the current
controls.
- The server queues these like enter/exit actions and applies each one
  once in the tick, using the same `accept_offer`/`reject_offer` as Pygame.
  A gone or non-pending item is refused.
- It answers with a `{"type": "phone_result", action, item_id, request_id,
  ok, reason}` event. On success it also plays `ui.accept` or `ui.reject`
  as a sound event, as Pygame does.
- Malformed requests are ignored. Requests go through the existing
  non-blocking queues, so they can't stall the tick.

**UI.** `phone.gd` is a `PanelContainer` on the right. The road stays
visible, and the simulation does not pause; Pygame does pause, see below.
- Keys are InputMap actions added by the phone: P toggles, Esc closes, 1–3
  pick a row, Enter accepts, X rejects. Buttons do the same.
- No phone key is a driving, taxi or camera key, so driving keeps working
  with the phone open.
- Opening plays `ui.phone_open` variation 0 and closing plays variation 1,
  as in Pygame.

**Updates.**
- Rows are rebuilt only when the set of rows or their statuses change.
  Values (distances, time left) and the selection update in place.
- A request disables answering that row until its `phone_result` arrives,
  or until the row disappears (expired or taken), which resolves it.
- An accepted fare closes the phone, as in Pygame.
- On disconnect the rows and pending requests are cleared and actions are
  disabled. After reconnecting, the phone shows only what new states say.

**Difference from Pygame:** Pygame stops the clock (`dt = 0`) while its
phone is open. The Godot client doesn't, because a shared server shouldn't
pause for one client's UI. Expiring offers therefore keep counting down.

**Tests:**
- `godot/tests/run_tests.gd` `test_phone`: open/close and the sound, no
  overlap with driving keys, rows and details, a single request, no
  duplicates, refusal, expiry, booking status, connection loss, no leftover
  nodes
- `tests/test_client_server_integration.py`: the phone in the state,
  reject and accept by id, a repeated accept answered "gone", malformed
  requests
- `--selftest --phone-wait 70` accepts a real Oulu offer or booking end to
  end

## Map streaming (`map_chunks.py`, `map_layer.gd`, `map_chunk.gd`)

- `ChunkIndex` buckets the world's existing OSM objects (`ways`,
  `railways`, `waters`, `buildings`) by 500 m cell. It is built and
  JSON-encoded once at server startup, so sending a chunk is only queueing
  its bytes. A feature belongs to every chunk where it
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
# audio check: server running, then
godot --path godot -- --port 8765 --audiotest /tmp/phases > log.txt
python tools/analyse_godot_audio.py log.txt
python -m theroadragetrip --connect 127.0.0.1:8765   # Pygame client on the same server
```

Python tests: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q`
(see `tests/test_client_server_integration.py`, `tests/test_slow_clients.py`
and `tests/test_map_chunks.py`).

## Measurements (Oulu, WSL2 on one machine; native Windows not measured)

**Network change (phase 3), 30 Hz paced ticks:**

| scenario | ticks | mean | p95 | max | queues |
|---|---|---|---|---|---|
| no client | 60 | 4.9 ms | 7.3 ms | 25.8 ms | – |
| normal client connects (its whole map queued) | 1 | 15.3 ms | – | 15.3 ms | 50 |
| normal client, steady | 150 | 4.2 ms | 5.8 ms | 23.6 ms | 0 |
| crossing a chunk border every 0.5 s | 150 | 3.5 ms | 5.0 ms | 15.9 ms | 0 |
| + a slow reader (400 KiB/s) | 150 | 3.6 ms | 5.2 ms | 20.5 ms | 0, 1 |
| + a client that never reads | 150 | 3.8 ms | 5.3 ms | 27.5 ms | 0, 1, 24 |
| after the non-reader's 10 s stall timeout | 400 | 3.7 ms | 5.0 ms | 21.7 ms | 0, 0 |
| no client, longer run | 1200 | 4.6 ms | 6.4 ms | 38.6 ms | – |

- **Before:** a new client's first tick took 281 ms (index build plus
  chunks sent from the tick), later connections about 100 ms. Tick max was
  38.5 ms.
- **After:**
  - a new client's first tick is 14–17 ms (queueing 49 pre-encoded chunks)
  - its map is delivered in about 0.45 s, on its own thread
  - a client that never reads leaves the tick at about 4 ms mean
  - the normal client kept receiving states: 1000 of 1061 ticks, including
    the time before it connected
- **Startup:** the chunk index and its encoding now happen before any
  client connects (Oulu: server start about 2.5 s in total).
- **Sender activity:**
  - normal client: 1184 messages, 11.6 MiB, 0 states coalesced
  - slow client: 586 messages, 4.3 MiB, 163 states coalesced, no events lost
- **Memory:** RSS 308 MiB with 3 in-process test clients; their parsed
  messages count too. 8 threads in total.
- **Unexplained spikes:** in two earlier runs a single tick of 135–145 ms
  appeared. One happened with every queue empty, so it was not a socket
  write. It did not reproduce in the final run, nor in 1200 ticks with no
  client, whose maximum was 38.6 ms. The cause is unexplained.

**Phase 2 client numbers (unchanged by phase 3):**

| what | measured |
|---|---|
| State build / JSON encode | 0.08 / 0.16 ms mean |
| State message | 15.7 KiB mean, 18.1 max, 30/s (~470 KiB/s) |
| Godot state handling (parse + buffer) | 0.50 ms windowed, 0.36 ms headless |
| Godot interpolate + draw entities | 0.35 ms windowed, 0.16 ms headless |
| Godot FPS | 64 windowed under WSLg, 145 headless |
| Rendered entities / loaded chunks | about 44 / 49–56 |
| Godot static memory | 67 MiB windowed |

## Audio validation (real output, WSLg PulseAudio)

`--audiotest` runs a scripted 17-phase sequence windowed, with the real
PulseAudio driver, against the Oulu server. Each phase's Master-bus mix is
recorded to its own WAV (`AudioEffectRecord`) and measured with
`tools/analyse_godot_audio.py`. In parallel, the system output was recorded
with `ffmpeg -f pulse -i RDPSink.monitor`. That recording showed the same
sequence reaching the OS, including true silence while Master was muted.

Nobody has listened to it; these are measurements of the output.

| phase | state | L / R dBFS | result |
|---|---|---|---|
| all_muted | Game and Environment at 0 | −120 / −120 | silence: nothing bypasses the buses |
| day_ambience | Environment only | −31 / −31 | the generated day bed (the legacy one measured −45) |
| night_ambience | night | −23 / −22 | night bed |
| rain | + rain | −27 / −25 | rain loop |
| enter_taxi | Game only, engine off, F | −37 dBFS, peak 0.46 | the door-open sound alone, exactly once; −27 dBFS in the WSLg system recording |
| engine_start / idle / drive / brake | E, then 0 → 8.3 m/s | about −20 | engine start, then the engine loop: started once, pitch follows speed |
| engine_off | E | −50 | engine loop stopped; engine_stop sound |
| train_movement | rumble loop 40 m away | −19 | positional train loop |
| event_left / event_right | train_arrived ±60 m | L−R +1.6 / −1.6 dB | positional: pans to the correct side |
| repeated_events | door-open ×3, 0.8 s apart | −25 | 3 events → 3 plays; 0 one-shot players left |
| master_muted | Master 0 | silent in the OS recording | volume groups work |
| disconnect | the client hangs up | −120; 0 loops and 0 one-shots playing | cleanup (measured 0.6 s after the drop, before the 1 s reconnect) |

- **No restarts or duplicates:** loop starts were `engine 1`, `city_day 1`,
  `city_night 1`, `rain 1`, `train_running 2` (the train stopped and left
  again). They are not restarted per state.
- **Each event plays once:** 10 events were presented and each played
  once. The three train events matched the brakes, doors and horn counts.
- **No leaks:** 0 one-shot players were alive at the end; they free
  themselves when finished.
- **Coordinates:** placed sounds use the same map coordinates as drawing
  (`MapMath.point`, y flipped). The camera is the 2D listener.

**Differences from Pygame audio**
- Engine: Godot uses the idle loop pitched by speed; Pygame crossfades rev
  layers.
- Train rumble: Godot plays one loop for the nearest moving train; Pygame
  plays the loudest intercity and commuter trains as two layers.
- Distance: Godot uses its own attenuation curve up to the same "silent
  beyond" ranges. Pygame uses inverse distance with a soft fade-out.
- Door sound when getting in: getting in now plays `vehicle.door_open` in
  both clients; it was `door_close` before godot-03. Passengers boarding
  still get `door_close`.
- Measurements are not listening. Every check above is about levels,
  panning, timing and counts. The new sounds also passed a manual
  listening review (2026-10-03).
- No station announcements or passenger speech yet; that is a later phase.

## Known limitations

- **Spikes:** occasional 20–39 ms ticks, plus the unexplained 135–145 ms
  ticks above. They are not caused by socket writes, but they show the
  simulation itself still has spikes.
- **Map memory:** the whole map's chunks are held encoded in memory, about
  6.6 MB for Oulu.
- **Two threads per client.** That's fine for a few local clients, not for
  many.
- **Long roads:** a road with no vertex inside a chunk it crosses isn't
  drawn there.
- **Water overdraw:** chunks of a large water polygon overlap each other.
- **Map extent:** there is no map beyond the loaded OSM area, and
  `--auto-fetch` is off in server mode.
- **Single player only**, though identified by `player_id`.
- **HUD:** basics plus the phone; no menus or settings yet.
- **Missing sounds:** no station announcements or passenger speech in
  Godot. The pedestrian curse is generated and validated but wasn't
  triggered in the scripted test.
- **Native Windows** performance and audio were not measured.

## Migration from Pygame

Keep both clients on the same server. Move one presentation feature at a
time, with Pygame as the visual reference:
1. phone and offer UI
2. station announcements
3. sprites
4. menus

Retire Pygame only when the Godot client covers everything.
