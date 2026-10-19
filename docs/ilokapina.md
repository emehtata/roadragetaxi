# Ilokapina road protests

Ilokapina is a fictional arcade event, not lawful pedestrian priority or a
simulation of an actual organisation. Python owns spawning, movement, collision
and rage decisions. Godot only draws the event and its phone notice.

## Gameplay

Normally up to two 24-person sit-ins appear during 10:00–20:00 game time,
with a slightly higher weekend probability. Each spawn attempt uses nearby
loaded roads and a session-local seeded generator. Clear mid-block urban road
locations are required, at least 120 m from the taxi and 300 m from another
event. Motorways, fast roads, bridges, tunnels, other levels, sharp bends,
junctions, roadworks, occupied approaches and blocked roadside slots are rejected.

An active sit-in blocks the full roadway. Swept movement checks stop the taxi
even at high speed; NPCs brake and wait without triggering stuck recovery.
Ordinary pedestrians wait rather than walk through the crowd. Vehicles and
ordinary horns cannot move the group.

An accepted existing rage shout, with its normal rage-meter cost, alarms groups
within 100 m on the same surface layer. They hesitate for 0.8 simulation seconds,
then move aside over 3 seconds. An occupied pedestrian shoulder delays clearing.
The road remains blocked until they finish moving. They stay aside for at least
30 simulation seconds, then return only when no nearby/incoming vehicle or
ordinary pedestrian makes it unsafe. Returning aborts when a hazard arrives.
Rage can be used again during return. Driving away alone does not remove a group.

Events expire after 20 simulation minutes or when their road unloads (checked
every five seconds). Expiry prevents permanent protest queues. Out-of-view
events retain their small group-level state, but members are only included in
snapshots within 800 m and only drawn in view. There is no per-member AI or
resident/population-budget change. New clients receive the current snapshot.
The phone shows a Finnish/English/German warning in both fare and navigation
apps while a group is active in the loaded city area, including while cleared.

## Implementation map

- `src/theroadragetrip/protests.py`: configuration, deterministic spawning,
  group transitions, swept obstruction and bounded render snapshots.
- `config.py` and `server/__init__.py`: user defaults and server-owned lifecycle.
- `simulation.py`: accepted-rage integration, taxi and ordinary pedestrian safety.
- `npc.py`: protest braking as an ordinary restrictive traffic decision, recovery
  suppression while waiting, and swept movement safety including reversing.
- `protocol.py`: current visible groups plus an active-city flag in every state.
- `godot/entity_layer.gd`: interpolated members using the existing pedestrian
  layer, seated poses and a moving Ilokapina banner.
- `godot/phone.gd`, `main.gd`, `i18n.gd`: one shared notice for both phone apps,
  translated into Finnish, English and German, cleared on disconnect.
- `tests/test_protests.py`, `tests/test_server_headless.py`,
  `godot/tests/run_tests.gd`: lifecycle, actual driving/rage, snapshot and UI checks.
- `docs/finnish-npc-traffic-law.md`: explicitly distinguishes this fictional
  arcade exception from ordinary pedestrian behavior and Finnish traffic law.

## Configuration

Existing user `roadragetrip.ini`, section `[protests]`:

```ini
enabled = true
max_groups = 2
group_size = 24
schedule = Mo-Su 10:00-20:00
intimidation_radius_m = 100.0
clearing_s = 3.0
return_delay_s = 30.0
lifetime_s = 1200.0
spawn_interval_s = 30.0
spawn_probability = 0.4
seed = 19
```

Schedules use the existing simple weekly opening-hours parser. Unsupported
schedule syntax disables spawning instead of silently choosing other hours.
Timers other than the daytime schedule use normal simulation seconds, not the
accelerated game calendar. Resource caps are eight groups of at most 80 people.

## Limits

Collision uses a conservative swept vehicle-radius envelope, not individual
body contacts. Shoulder safety is geometric, not a complete pedestrian route
planner; this does not certify all roadside placements as legally accessible.
No alternate-route search is added: vehicles wait until rage clearance or event
expiry. Finite event duration and low density bound protest-induced waits, but
do not guarantee a jam-free road network. Spawn attempts inspect at most 40
local candidate roads; no suitable location means no spawn.

Tests: `tests/test_protests.py`, the Ilokapina server-headless regression and
the phone checks in `godot/tests/run_tests.gd`. A group-level microbenchmark is
not a measured full-game FPS guarantee.

Validation on 2026-10-19: full Python suite 1,947 passed, 2 skipped; Godot
3,135 checks passed. A separate headless draw check exercised all five states
with 24 people and the banner. A read-only cached-Oulu spawn check found a
Torikatu site (ten scheduled updates: about 57 ms total, without live traffic).
Live visual review and a full-game FPS comparison have not been performed.
