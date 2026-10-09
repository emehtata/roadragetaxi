# Godot Parity Phase 8 — Settings and Remaining Controls

## Objective

Implement the next cohesive slice of phase 7, “Settings and polish,” from
`docs/architecture/godot-pygame-rendering-parity.md`:

1. an in-game ESC settings overlay
2. persisted client audio and subtitle preferences
3. lane assist (`K`)
4. manual taxi respawn (`R`)
5. trip-meter reset (`T`)

The Python server remains authoritative for driving state, lane assist,
respawning, and the trip meter. Godot owns its local overlay and presentation
preferences.

Keep this phase cohesive. Do not include historical weather, walking-player
appearance/animation, analog instruments, rendering polish, vomit, engine
layers, footsteps, or other phase-7 miscellany.

---

## 1. Trace the current implementation first

Before changing code, trace:

* `PlayerCommand`, `advance_simulation`, water respawn, and car physics in
  `simulation.py`
* `Car.lane_assist_enabled`, `lane_assist_active`, `respawn_car`, and
  `reset_trip` in `physics.py`
* the Pygame `K`, `R`, and `T` handlers, `_respawn_allowed`, settings menu,
  reset-to-defaults behaviour, and control hints in `main/__init__.py`
* settings defaults and persistence in `config.py`
* command encoding/decoding and player state in `protocol.py`
* edge-triggered action handling in `server/__init__.py`
* Godot input ownership in `main.gd`, `phone.gd`, `nav_overlay.gd`, and
  `labels.gd`
* Godot audio buses/playback, subtitle handling, HUD hints, and disconnect
  behaviour
* current protocol/server/input/Godot tests

Use current code as the source of truth. Reuse the existing command path,
`respawn_car`, `TaxiManager.handle_respawn`, `reset_trip`, audio buses, and UI
style. Do not create parallel gameplay logic in Godot.

---

## 2. Preserve the server-clock design

The Godot client must not pause the shared Python simulation. ESC opens a
modal client overlay while the server clock, traffic, trains, weather, fares,
and timers continue.

While the overlay is open:

* release/clear held driving input immediately
* send neutral controls at the normal command cadence
* do not send interact, refuel, road-rage, respawn, or trip-reset presses
* consume gameplay toggle keys so settings navigation cannot also drive the
  game
* keep receiving/presenting current state and bounded due events
* allow ESC or the Resume action to close the overlay

Do not add a pause command, block the server tick, freeze interpolation, or
buffer a burst of inputs for resume. Keep the existing intentional difference
that a networked client cannot stop the shared world.

---

## 3. Add one small Godot settings overlay

Add one reusable modal `Control`, instantiated once. Use keyboard controls
consistent with the existing UI:

* Up/Down selects a row
* Left/Right changes a value
* Enter/Space activates Resume or Reset defaults
* Escape resumes

The minimum rows are:

```text
Resume
Master volume
Game volume
Environment volume
UI volume
Speech enabled
Subtitles enabled
Reset defaults
```

Requirements:

* volumes are clamped to `0.0..1.0`, changed in `0.05` steps, and applied to
  the existing Godot audio buses immediately
* Speech enabled suppresses future driver/passenger voice playback only;
  ordinary sounds and station announcements remain enabled
* Subtitles enabled suppresses future speech subtitles independently of
  speech audio
* disabling speech stops the current voice; disabling subtitles hides the
  current subtitle immediately
* Reset defaults restores only this client's listed defaults and applies them
  immediately
* reconnecting does not reset preferences
* resize anchors and focus remain usable at the supported window sizes
* the overlay clearly states that the world continues while it is open

Do not reproduce server-owned Pygame settings here. In particular, omit
Overpass endpoints, physics realism, and historical weather. Do not add a
second audio mixer or duplicate bus volume logic.

Language is also deferred in this phase: most player-facing simulation text
is already selected by the server, so a client-only language toggle would
produce a mixed-language UI. Do not add a global server-language mutation to
an otherwise client-local settings phase.

---

## 4. Persist client preferences with Godot's native config

Use `ConfigFile` and one small file under `user://`; add no dependency and no
Python config bridge.

Persist only:

```text
master_volume
game_volume
environment_volume
ui_volume
speech_enabled
subtitles_enabled
```

Requirements:

* load once during client startup, before the first sound/subtitle where
  practical
* save after an actual value change or Reset defaults, not every frame
* validate types and clamp numeric values while loading
* missing, corrupt, non-finite, or out-of-range values fall back safely
* preserve unrelated keys if the file already exists
* failure to read or write logs one useful warning and never prevents play
* tests can inject/use a temporary path rather than touching a developer's
  real `user://` file

Keep defaults aligned with the current Godot client unless an existing config
constant already defines them.

---

## 5. Extend the command contract minimally

Add these fields to `PlayerCommand` and the existing command JSON:

```text
lane_assist_enabled: bool
respawn: bool
reset_trip: bool
```

Semantics:

* `lane_assist_enabled` is continuous session state, like the existing speed
  limiter and red-light assist fields
* `respawn` and `reset_trip` are one-press actions, like refuel/road rage
* additive fields keep safe defaults for older clients
* do not bump the protocol version unless repository rules require it
* validate/coerce at the existing protocol boundary; unknown fields remain
  harmless

Godot owns the local lane-assist toggle so commands continuously report its
current value. The server owns action de-duplication so one press cannot be
lost between ticks or replayed by the latest-command loop.

Do not create separate message types for these three values.

---

## 6. Implement authoritative lane assist

On every simulation tick, apply `command.lane_assist_enabled` to the player
car before `update_car_physics` uses it. Preserve all existing physics rules
for when assist becomes active and when manual steering overrides it.

Requirements:

* Godot `K` toggles the local value once per non-echo key press
* `K` is ignored while the phone or settings overlay owns input
* the value is sent continuously, including after reconnect
* state sends both `lane_assist_enabled` and `lane_assist_active` from the
  authoritative car
* the HUD hint reports lane assist ON/OFF
* use `lane_assist_active` only as presentation feedback; Godot never computes
  whether assistance is currently steering
* Pygame continues to work through the same `PlayerCommand` path

Do not change lane-centering maths, thresholds, road selection, steering, or
physics modes.

---

## 7. Implement edge-triggered manual respawn

Godot `R` requests a manual taxi respawn. The server must count/latch presses
using the established refuel/road-rage pattern and consume each accepted
press exactly once.

Match the normal Pygame `R` behaviour, not the obsolete HOME debug respawn:

* reject/ignore the request while the driver is on foot
* otherwise call the existing `respawn_car` with the authoritative surface
  roads, waters, and taxi stands
* call `taxi_mgr.handle_respawn` at the resulting position
* reset the in-water timer
* clear/recompute server-side position-dependent cached state that would be
  invalid after teleporting, using existing teleport handling
* stop unsafe residual taxi movement as `respawn_car` already specifies
* provide a short translated authoritative notification if current Pygame
  behaviour already has one; do not invent a penalty

The client follows the next authoritative position. Do not teleport the
Godot entity locally, predict the destination, choose a spawn point, or alter
map streaming rules.

One key press must produce one respawn even if commands arrive faster or
slower than server ticks. Holding/echo must not repeat it.

---

## 8. Implement edge-triggered trip reset

Godot `T` requests `reset_trip(car)` on the server exactly once. Preserve the
odometer, fuel, fare distance, current job, balance, score, and all other
vehicle state.

Requirements:

* count/latch the press with the same action mechanism as respawn/refuel
* ignore echo/repeat and modal-owned keyboard input
* the existing `state.player.trip_m` naturally confirms the result
* update the HUD hint to name `T`
* no local optimistic reset and no new reset implementation

A repeated command carrying the last press must not reset distance accumulated
after the first reset.

---

## 9. Input ownership and lifecycle

Keep one clear priority order:

1. settings overlay
2. phone/modal UI
3. gameplay toggles/actions
4. held driving input

Opening either modal clears held driving keys. Focus loss continues to clear
input as it does now. Do not let ESC both close the phone and open settings in
one event.

On disconnect:

* clear pending one-shot actions
* clear held controls
* retain local preferences and continuous session toggles
* close transient voice/subtitle playback as already required
* choose one consistent behaviour for the settings overlay (remaining open is
  acceptable); document it in the test

The automated input test path must remain able to drive without the new modal
stealing input.

---

## 10. Scope and protected systems

Do not change:

* lane-assist physics or road/path algorithms
* respawn-point selection or water-respawn timing
* trip/odometer accumulation formulas
* speed limiter or red-light assist semantics
* phone behaviour, navigation, labels, speech selection, or announcements
* server clock, interpolation, camera, chunks, or map loading
* Pygame's existing settings UI/config format
* server launch configuration

Do not add a UI framework, settings abstraction, input action registry, or
dependency. One overlay, one native config helper if needed, and the existing
command/action paths are sufficient.

---

## 11. Tests

Add the smallest deterministic checks at the owning layer.

### Python/protocol/server

Cover at least:

1. new command fields encode/decode and absent fields retain safe defaults
2. continuous lane-assist state reaches `car.lane_assist_enabled` before
   physics and both enabled/active facts reach player state
3. one respawn press is applied exactly once despite latest-command replay
4. respawn is rejected on foot and uses the existing authoritative helper in
   the taxi
5. respawn calls `handle_respawn` and clears the water timer
6. one trip-reset press sets only `trip_m` to zero and is consumed once
7. malformed/unknown command data remains safe
8. Pygame command construction retains its current `K`, `R`, and `T` behaviour

### Godot settings/input

Cover at least:

1. ESC opens/closes one overlay and clears held driving controls
2. modal input sends neutral movement and no queued actions
3. each volume row clamps, applies immediately, persists, and reloads
4. malformed/missing config values use defaults without crashing
5. speech and subtitle toggles act independently and immediately
6. Reset defaults changes only the listed client preferences
7. `K` is continuous; `R` and `T` are one-shot and cleared after send
8. echo, phone-owned input, settings-owned input, focus loss, and disconnect
   do not leak or repeat actions
9. HUD hints show lane assist status and the new controls
10. older state without lane-assist fields remains safe

Run at minimum:

```bash
pytest -q tests/test_protocol.py tests/test_server_headless.py tests/test_client_server_integration.py tests/test_main.py tests/test_physics.py
make godot-test
make godot-selftest
make audio-check
```

Run any narrower new test file as well. Distinguish unrelated pre-existing
failures from regressions.

Manually verify:

1. opening settings while accelerating immediately releases the taxi while
   traffic, trains, weather, and fare time continue
2. every bus slider is audible immediately and survives restart
3. speech/subtitles can be independently disabled and re-enabled
4. `K` changes real lane-assist behaviour and HUD status
5. one `R` press respawns only in the taxi without a second teleport
6. `T` clears the trip meter but not the odometer or active fare
7. phone, navigation, labels, speech, announcements, and reconnect still work

---

## 12. Performance and acceptance

This phase must be effectively idle-cost-free:

* one overlay tree created once
* no per-frame config reads/writes
* no polling filesystem or settings rebuild
* no extra server work without an action beyond assigning one boolean
* no new unbounded queue
* no material regression in Godot self-test or ordinary driving benchmark

No new media assets are needed.

---

## 13. Documentation

Update only the relevant rows and phase history in
`docs/architecture/godot-pygame-rendering-parity.md`:

* pause/settings, noting explicitly that the server world does not pause
* lane assist
* manual respawn
* trip reset
* command/state fields and client preference persistence
* `godot-final-08` tests and manual validation

Leave language, historical weather, walking-player animation, appearance,
render/audio polish, and the other incomplete rows open. Do not rewrite or
re-audit the whole document.

---

## 14. Git workflow

Work on the current branch:

```text
release/v0.16.0g-alpha
```

Preserve unrelated worktree changes. Create clear commits and push them after
implementation and validation. Do not create or push a Git tag.

---

## Final report

Report:

### Implementation

* overlay behaviour and why it does not pause the server
* persisted keys/defaults and validation
* exact command/state additions and one-shot handling
* lane assist, respawn, and trip-reset authoritative paths

### Tests

* exact commands and results
* manual scenarios checked
* unrelated failures

### Performance

* bounded nodes/actions and confirmation of no per-frame persistence work
* self-test/benchmark comparison if measured

### Git

* commit hash(es)
* confirmation that the branch was pushed
* explicit confirmation that no Git tag was created

Do not start the next parity phase automatically.
