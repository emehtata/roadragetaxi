# Godot Parity Phase 5 — Road Rage

## Objective

Implement the next recommended phase from
`docs/architecture/godot-pygame-rendering-parity.md`: the existing Pygame
road-rage action, end to end.

When the player presses SPACE with enough rage:

1. spend the existing rage cost
2. play the existing horn cue
3. choose and show the existing five-second shout
4. provoke the single nearest eligible NPC driver ahead

Move the gameplay rule out of Pygame's event loop and into shared simulation
code so the Python server is authoritative. Godot sends one edge-triggered
press, plays the server event, and renders server state.

This phase is only road rage. Do not combine it with the later speech,
weather, station, settings, or polish phases.

---

## 1. Read the current implementation first

Before changing code, trace:

* `RAGE_SHOUTS`, `RAGE_SHOUT_COST`, SPACE handling, shout timer, and
  `draw_car()` call in `main/__init__.py`
* rage gain/decay and `PlayerCommand` in `simulation.py`
* `NPCVehicleManager.trigger_road_rage()` and the `NPC_ROAD_RAGE_*`
  constants in `npc.py`
* Pygame shout rendering in `render/vehicles.py::draw_car`
* `EventAudio`, pending one-shot commands, and tick ordering in
  `server/__init__.py`
* command/state encoding and interpolation in `protocol.py`
* Godot input/one-shot command handling in `main.gd`
* Godot taxi rendering and `_bubble()` in `entity_layer.gd`
* `vehicle.horn` in the audio catalog and `audio_manager.gd`
* the existing rage meter in `instruments.gd`
* current NPC, protocol, server integration, audio, and Godot tests

Use the current repository as the source of truth. Preserve the exact game
rule and reuse the existing NPC reaction, audio asset, bubble helper, and
one-shot command pattern.

---

## 2. Preserve the existing rule

The Pygame behaviour to preserve is:

```text
RAGE_SHOUT_COST = 0.25
RAGE_SHOUT_DURATION_S = 5.0
RAGE_SHOUTS = PRKL!, STNA!, VTTU!, HLVT!, KRPÄ!, KSPÄ!, PSKA!
```

On one accepted press:

* require `rage_power >= 0.25`
* subtract exactly `0.25`, without going below zero
* choose one text from the existing shout tuple
* start/restart the shout at five seconds
* play `vehicle.horn` at Pygame's 0.45 volume
* retain Pygame's `play_driver_line("rage", language)` call in shared logic
  where practical; the server's speech method may remain a no-op until the
  later speech phase
* call `npc_manager.trigger_road_rage(car.x, car.y, car.heading,
  traffic_mgr.sim_time)` exactly once

`trigger_road_rage()` already owns the NPC rule. Do not change it:

* only the nearest currently driving NPC ahead can react
* detection distance remains 40 m
* lateral limit remains 6 m
* the reaction remains eight simulation seconds
* the affected driver yields at the existing 1.5 m/s cap
* no NPC ahead is a valid successful shout; the rage, horn, and bubble still
  happen as they do in Pygame

With insufficient rage, do nothing: no cost, horn, shout, driver line, or NPC
reaction.

Do not change rage gain/decay, the rage meter, NPC following, or avoidance.

---

## 3. Move the action into shared simulation code

Add one boolean to `PlayerCommand`:

```text
road_rage: bool = false
```

Handle it in the shared simulation path used by both Pygame and the server.
Remove the old duplicate gameplay effects from Pygame's raw event handler;
that handler should only queue the press.

Keep presentation state minimal. The simulation result may report a newly
accepted shout to its caller; the existing Pygame loop and server can then
maintain the five-second presentation timer without duplicating rage cost or
NPC gameplay logic. Do not create a manager or event framework for this one
action.

Use the existing randomness source and shout tuple. Tests may patch the
choice, but production must not hard-code one phrase.

The action must run once per press even when the server replays its latest
held command over multiple ticks.

---

## 4. Make `road_rage` edge-triggered on the server

Follow the existing F/G pending-command pattern:

* decode `road_rage` through the normal command protocol
* strip it from `_latest_command`
* count/queue each received press
* apply at most one queued press to a simulation tick
* never replay one press on later ticks
* preserve multiple distinct presses rather than collapsing them into a held
  boolean
* clear ordinary held input on disconnect as before

Do not introduce a new message type or endpoint. The additive command field
does not need a protocol-version bump unless repository rules require it.

---

## 5. Send shout state and horn event

Add one optional additive state object:

```text
state.road_rage = {
    "text": "PRKL!",
    "timer": 5.0
}
```

Send null when no shout is active. The server owns and decrements the timer
using simulation `dt`; clamp it to zero and clear expired state. A new client
connecting during an active shout should receive the remaining state.

Treat the object as discrete presentation state under interpolation. Missing,
null, or malformed road-rage state must remain safe for older clients and
fixtures.

On an accepted action, emit exactly one existing semantic sound event for
`vehicle.horn`. Reuse the current catalog asset. Configure the existing Godot
audio mapping to match the 0.45 volume rather than adding or generating audio.

Do not add a speech event in this phase. Driver/passenger speech and subtitles
belong to the later speech phase.

---

## 6. Add the Godot SPACE press

In Godot:

* a non-echo SPACE press sets one pending road-rage action
* the next command carries `road_rage: true` once
* later commands carry false until another press
* do not send it while the phone is open, matching Pygame
* do not send it after the terminal career summary is shown
* preserve held driving input, F/G one-shots, E, V/B, N, and C behaviour

The client must not check or spend rage locally. It may send a press with an
empty meter; the authoritative simulation decides that nothing happens.

Add `SPACE road rage` to the existing compact driving hint if it still fits.
Do not redesign the HUD in this phase.

---

## 7. Render the shout bubble in Godot

Render the active server-provided shout above the player taxi in world space.
Reuse `entity_layer.gd::_bubble()` and the current taxi sample; do not add a UI
panel or separate scene.

Match Pygame's presentation:

* white bubble
* red text and border
* positioned above the taxi
* constant readable screen-pixel text size across zoom levels
* fully visible until the last 0.5 seconds
* fades linearly during the final 0.5 seconds
* drawn after the taxi body and before NPC vehicles, matching `draw_car`

Only render trusted valid state: a non-empty string and a finite positive
timer. Missing, null, malformed, non-finite, or expired values must not draw
or crash.

Do not choose text, start timers, spend rage, or provoke NPCs in Godot.

---

## 8. Scope and protected systems

Do not change:

* rage accumulation/decay or the rage gauge
* NPC road-rage selection and reaction constants
* NPC general driving, avoidance, routing, or population logic
* vehicle movement or physics
* taxi fare, fuel, score, or career rules
* navigation routing from `godot-final-04`
* camera following, interpolation, or jitter fixes
* map chunks or 2D/3D rendering
* phone behaviour beyond suppressing SPACE while it is open

Do not implement speech/subtitles, additional horn controls, NPC speech,
weather, stations, settings, or other parity items.

No new dependency or audio asset is needed.

---

## 9. Tests

Add the smallest deterministic checks at the layer that owns each rule.

### Shared simulation and NPC behaviour

Cover at least:

1. exactly 0.25 rage accepts one press and reaches zero
2. less than 0.25 does nothing
3. enough rage spends exactly 0.25, chooses a valid shout, starts the
   five-second effect, and emits one horn
4. one accepted press calls `trigger_road_rage()` exactly once with the
   taxi position, heading, and current simulation time
5. no eligible NPC still spends rage, horns, and shouts
6. the nearest eligible NPC ahead receives the existing eight-second reaction
7. parked, crashed, behind, too-far, and too-lateral NPCs are not selected
8. Pygame's shared path no longer duplicates the cost or trigger

Reuse and extend existing NPC tests rather than retesting the whole NPC
system.

### Protocol and server

Cover at least:

1. `road_rage` command encode/decode and false default
2. one press followed by ordinary commands is applied exactly once
3. distinct queued presses are preserved
4. insufficient rage emits no horn or shout state
5. an accepted press changes authoritative rage, emits one `vehicle.horn`,
   and publishes the shout text/timer
6. the timer decreases, expires, clamps, and clears
7. a connecting client receives the remaining active shout
8. road-rage state remains discrete under interpolation
9. missing/malformed state is backward-compatible

### Godot

Cover at least:

1. non-echo SPACE is sent once; echo and held commands do not repeat it
2. SPACE is suppressed while the phone is open and after the summary
3. F/G, E, V/B, N, and C regressions remain covered
4. valid state renders the exact server text above the taxi
5. alpha is full above 0.5 seconds and fades correctly below it
6. expired, empty, missing, malformed, and non-finite state does not draw
7. the bubble remains constant-sized and follows the interpolated taxi
8. one horn event resolves to `vehicle.horn` at the intended volume
9. the driving hint names SPACE

Run at minimum:

```bash
pytest -q tests/test_npc.py tests/test_protocol.py tests/test_server_headless.py tests/test_client_server_integration.py
make godot-test
make godot-selftest
make audio-check
```

Run any directly affected shared-simulation tests. Distinguish unrelated
pre-existing failures from regressions.

Manually verify with the real Oulu server:

1. press SPACE below 25% rage and confirm nothing happens
2. build at least 25% rage and press SPACE once
3. confirm the meter drops by exactly 25 percentage points
4. confirm one horn and one randomized five-second bubble
5. confirm the nearest moving NPC ahead yields while other NPCs do not
6. confirm no NPC ahead still produces the cost, horn, and bubble
7. hold SPACE and confirm it does not repeat
8. press SPACE twice as distinct presses when enough rage is available
9. open the phone and confirm SPACE does not trigger road rage
10. drive and zoom while the bubble remains aligned and readable

---

## 10. Documentation

Update only the relevant rows and phase history in
`docs/architecture/godot-pygame-rendering-parity.md`:

* road-rage gameplay
* rage shout bubble
* horn event
* command and state shapes
* `godot-final-05` implementation and tests

Update protocol documentation if it enumerates commands or state fields. Do
not rewrite or re-audit the whole parity document.

---

## 11. Git workflow

Work on the current branch:

```text
release/v0.16.0g-alpha
```

Preserve unrelated existing worktree changes. Create clear commits and push
them when implementation and validation are complete. Do not create or push a
Git tag.

---

## Final report

Report:

### Implementation

* shared authoritative action and exact preserved rules
* edge-triggered command handling
* shout state, horn event, and Godot bubble
* any existing contract that differed from this prompt

### Tests

* exact commands and results
* manual Oulu scenarios checked
* any unrelated failures

### Regression and performance

* confirmation that rage gain, NPC driving, navigation, input, camera, and
  rendering remain unchanged
* measured or reasoned per-press/per-frame cost

### Git

* commit hash(es)
* confirmation that the branch was pushed
* explicit confirmation that no Git tag was created

Do not start the next parity phase automatically.
