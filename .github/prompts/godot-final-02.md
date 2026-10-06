# Godot Parity Phase 2 — Core Controls and Economy

## Objective

Finish the remaining **Core controls and economy** work from
`docs/architecture/godot-pygame-rendering-parity.md`:

1. V toggles the speed limiter and shows its status.
2. B toggles the red-light assist and shows its status.
3. The HUD shows `taxi.total_score`.
4. Godot shows the career city summary when `should_stop` is true.

Refuelling was completed in `godot-final-01`; do not reimplement it.

This is client-only work. The command and state fields already exist. Do not
change the Python simulation, server, protocol, vehicle physics, camera, or
rendering architecture unless investigation proves the documented contract is
wrong.

---

## 1. Read the current implementation first

Before editing, trace the relevant paths in the current repository:

* Pygame V/B input and HUD status in `main/__init__.py` and `render/hud.py`
* Pygame city summary in `render/menus.py::draw_city_summary`
* `PlayerCommand.speed_limiter_enabled` and
  `PlayerCommand.red_light_assist_enabled` in `simulation.py`
* command handling in `server/__init__.py`
* `taxi.total_score`, `should_stop`, and `city_summary` in `protocol.py`
* Godot input and `command_for()` in `godot/main.gd`
* Godot HUD formatting and nodes in `godot/hud.gd` and `godot/main.tscn`
* existing Godot checks in `godot/tests/run_tests.gd` and
  `godot/input_test.gd`

Use the current repository as the source of truth. Reuse its existing UI
styles and test patterns. Do not invent protocol fields, messages, nodes, or
game rules.

---

## 2. Existing contracts to reuse

The server already consumes these continuously reported command fields:

```text
speed_limiter_enabled: bool   (default true)
red_light_assist_enabled: bool (default false)
```

They are session toggles, not edge-triggered actions. Godot must keep their
current values locally and include both values in every command. Do not model
them like the one-shot F/G presses.

The state already contains:

```text
state.taxi.total_score
state.should_stop
state.city_summary
```

When present, `city_summary` is:

```text
[city, score, completed_fares, next_city, career_total_score]
```

`next_city` is null when the career is complete. Missing fields must remain
safe for compatibility with older/incomplete state fixtures.

---

## 3. Implement the V/B toggles

In the Godot client:

* keep local speed-limiter state, initially `true`
* keep local red-light-assist state, initially `false`
* toggle them on non-echo V and B key presses
* send their current values in every command
* preserve their values across ordinary input commands
* keep refuel and interact one-shot behaviour unchanged
* clear held driving input on focus loss as before; do not reset the toggles

Update the normal driving hint or another small existing HUD element so both
controls and their ON/OFF states are visible while driving. Match the current
compact HUD rather than adding a settings system or analog speedometer.

The server remains authoritative over vehicle behaviour. The client only
chooses and reports the two command values.

---

## 4. Show the score

Display `state.taxi.total_score` in the normal HUD using the existing top row
or another existing compact HUD location.

Requirements:

* update directly from each presented state
* display negative and positive values correctly
* use a harmless placeholder/default when the field is absent
* do not cache or calculate score client-side
* do not redesign the HUD or add an analog speedometer

---

## 5. Show the career city summary

When a state has `should_stop == true` and a valid `city_summary`, replace or
cover normal gameplay UI with a simple full-screen summary matching the
information in Pygame's `draw_city_summary`:

* title: City summary
* completed city
* city score
* completed fares
* next city, when non-null
* career-complete message and total career score when `next_city` is null

Use existing Godot controls and styles. Do not create a new menu framework.

Treat this state as terminal for the current server session. Stop sending
driving commands once the summary is shown so stale held input cannot continue
to affect the simulation. Do not make the client choose or load the next city;
the server owns career progression and world selection.

If the current server lifecycle provides a real continuation mechanism,
follow it. Otherwise show the terminal summary without inventing a request or
reconnect protocol. Do not add a fake Enter action that cannot advance the
server.

Handle malformed or absent summary data safely: normal play must not crash,
and `should_stop` without a valid summary may show a small terminal message
rather than fabricated values.

---

## 6. Scope and protected systems

Do not change:

* vehicle movement or physics
* speed-limiter or red-light-assist rules in Python
* server authority or networking design
* camera following, interpolation, or jitter fixes
* map chunks or the 2D/3D rendering pipeline
* buildings, lighting, weather, or audio
* phone behaviour
* refuelling behaviour

Do not implement other parity items, including lane assist, navigation,
taximeter details, fuel-station price, road rage, particles, speech, pause or
settings, manual respawn, trip reset, or historical weather.

No new dependency is needed.

---

## 7. Tests

Add the smallest deterministic Godot checks that prove the feature works.
Cover at least:

1. command defaults are limiter ON and red-light assist OFF
2. V changes the limiter value sent by `command_for()`
3. B changes the red-light-assist value sent by `command_for()`
4. later commands retain both selected values
5. F/G one-shot command behaviour remains unchanged
6. HUD formatting shows positive, zero, and negative scores
7. a missing score is safe
8. the five city-summary values render correctly
9. null `next_city` shows career completion and total score
10. the summary hides normal gameplay UI and suppresses further driving
   commands
11. absent or malformed summary data does not crash

Prefer extending `godot/tests/run_tests.gd` and the existing input test over
adding a new test harness. Add a Python test only if a Python contract is found
to be untested and the production Python code remains unchanged.

Run at minimum:

```bash
make godot-test
make godot-selftest
```

Run any directly relevant Python protocol/server tests if those files are
touched. Distinguish pre-existing unrelated failures from regressions.

Manually verify:

1. V toggles limiter ON/OFF and the HUD reflects it
2. B toggles red-light assist ON/OFF and the HUD reflects it
3. both settings remain selected while driving and using F/G/E
4. score changes appear in the HUD
5. a representative next-city summary is readable
6. a career-complete summary is readable
7. no driving command is sent after the terminal summary appears
8. camera and driving remain unchanged before the summary

---

## 8. Documentation

Update only the relevant rows and phase history in
`docs/architecture/godot-pygame-rendering-parity.md`:

* speed limiter / red-light assist toggles and status
* score
* career city summary
* `godot-final-02` implementation and tests

Do not rewrite or re-audit the whole document.

---

## 9. Git workflow

Work on the current branch:

```text
release/v0.16.0g-alpha
```

Create clear commits and push them when implementation and validation are
complete. Do not create or push a Git tag.

---

## Final report

Report:

### Implementation

* V/B toggle behaviour and command flow
* score placement
* city-summary behaviour
* whether any existing contract differed from this prompt

### Tests

* exact commands and results
* manual scenarios checked
* any unrelated failures

### Regression and performance

* confirmation that driving, refuelling, camera, and rendering are unchanged
* confirmation that this client-only phase adds no meaningful per-frame cost

### Git

* commit hash(es)
* confirmation that the branch was pushed
* explicit confirmation that no Git tag was created

Do not start the next parity phase automatically.
