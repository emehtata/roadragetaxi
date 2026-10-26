# Taxi driver brawls

Rival (competitor) taxi drivers sometimes get out of their cars, argue and
come to blows (rrt-019-brawl-01). Code: `src/theroadragetrip/taxi_brawls.py`;
drawing: `godot/entity_layer.gd` (`_brawls`); tests: `tests/test_taxi_brawls.py`
and the "Taxi brawls" checks in `godot/tests/run_tests.gd`.

## Responsibilities

The **server** decides everything: who quarrels, every state change, every
action and whether it lands, the outcome and the cleanup. The **client**
only draws the state it receives, plus a short punch animation per action.
It never decides a hit or a winner. No client message touches brawls.

## State machine

```
(IDLE: no conflict)
  -> TRIGGERED      1 s    doors open, the drivers step out on the curb side
  -> CONFRONTATION  3 s    they walk over and shout (curse bubbles)
       -> RESOLUTION         the softer one backs down ("backed_down")
  -> ESCALATION     2 s    a threat; the threatened one may back down
       -> RESOLUTION         ("backed_down")
  -> FIGHTING      <=12 s  one action per 0.9 s at most
       -> RESOLUTION         "knockout" (3 hits), "surrender", or "separated" at 12 s
  -> RESOLUTION     4 s    a knocked-down driver gets up (2 s); both walk back
  -> COOLDOWN       1 s    back in the cars; then the locks go and the conflict is removed
```

`TRANSITIONS` lists the legal moves; `_enter` refuses any other. A conflict
resolves once (`_resolve` ignores a second call). Every conflict is removed
after `MAX_LIFETIME_S` (40 s) at the latest. If a participant despawns,
crashes or loses its driver, the conflict is removed at once as "aborted".

A conflict holds its id, trigger, two participants, state and deadlines,
the latest action (`seq`, kind, actor, target, hit) and the outcome and
winner. Participants are existing NPC taxis, referenced by `vehicle_id`
(no new identity), or, later, the player.

## Triggers

All three come from existing events. None of them scans every pair of NPCs.

| Trigger | Source | Notes |
| --- | --- | --- |
| `passenger` | `competitor_taxis.Dispatcher`: a fare goes to one idle taxi while another idle taxi waits within `ENGAGE_RADIUS_M` | `DISPUTE_CHANCE` (0.15) |
| `rank` | every `RANK_CHECK_INTERVAL_S` (30 s): pairs of idle, parked rival taxis within `ENGAGE_RADIUS_M` | `RANK_CHANCE` 0.002 per pair, or `NIGHT_RANK_CHANCE` 0.02 at the Friday/Saturday 22–06 nightlife peak (`nightlife_peak`). Away from a taxi stand (`TAXI_STAND_RADIUS_M`), times `RANK_FALLBACK_FACTOR` |
| `traffic` | the player's minor bump of a rival taxi (`npc_manager.taxi_bumps`) | the participant is the player; rejected while `PLAYER_BRAWLS_ENABLED` is False |

These values are game estimates, not incident statistics, and are kept rare
on purpose. All tunables are module constants at the top of `taxi_brawls.py`,
like the other simulation tunables.

**Eligibility** (`_eligible_npc`) requires all of these:

- the vehicle exists and is a competitor taxi;
- it is `PARKED` and has its driver;
- it is not in another brawl, not held by rage clearance, and has no
  queued route job;
- it is not cooling down from an earlier brawl;
- it has no fare aboard, and is not stopped to board or drop one off.

The two taxis must be within `ENGAGE_RADIUS_M` of each other and on the same
layer and map level. A participant cannot fight themselves. Each trigger
event has a key; a key that was already processed is ignored
(`PROCESSED_TRIGGER_MEMORY`), and so are duplicates queued in the same tick.

## Combat

Each driver has three traits fixed per vehicle id (`driver_traits`):
aggression, skill and retreat. Who acts is weighted by aggression. A hit
lands with probability `BASE_HIT_CHANCE + 0.5 × (skill − opponent's skill)`,
clamped to 0.1–0.9. Each hit may make the defender give up, with probability
retreat × hits × 0.2. All rolls use the manager's `rng`; tests seed it, and
the same seed plays out the same fight.

## Vehicles and drivers

`NPCVehicle.brawl_id` locks a taxi. A locked taxi is skipped by the
dispatcher and by trip continuation (the `ready` list in `npc.py`), so it
does not move. Drivers stay in `npc_manager.drivers`: the figures belong to
the conflict and are not pedestrians. The crash path that turns drivers into
pedestrians is permanent, so it is not reused here. Fighters step out at
`PedestrianManager._vehicle_entry_position`, the passenger (curb) side,
following § 41 (safe doors) in the traffic-law guide. When the conflict is
released, each driver gets `DRIVER_COOLDOWN_S` (10 min) before they can
quarrel again.

## Protocol

The state message has `"brawls"`: one row per conflict that is not in
COOLDOWN, holding `id`, `state`, `action`, `outcome`, `winner` and two
`fighters` (`kind`, `id`, `x`, `y`, `heading`, `down`, `moving`,
`curse_timer`, `curse_text`). It holds the current state only, never a
history, so a client that connects late cannot replay a fight. The F12
debug snapshot has `brawls.active`, `brawls.recent` (the last 20 outcomes)
and `brawls.rejected_triggers`.

## Presentation

Each fighter is drawn with the pedestrian figure: standing or walking, fists
up, `fallen` when down, with a curse bubble. A punch plays once per new
action `seq`, so a duplicated or late update never swings twice. Sounds:
`vehicle.door_open` and `vehicle.door_close`, `pedestrian.curse`, and
`collision.fence` as a stand-in for a hit, because the audio catalog has no
punch sound yet.

## Performance

Measured on 2026-10-26 with 300 NPC vehicles (10 idle rival taxis), 30 Hz
ticks, calling `BrawlManager.update` alone:

- no conflict: 0.17 µs per tick (an id lookup every 30 s);
- one active fight: 11.4 µs per tick.

Only active conflicts do per-tick work: two figure poses plus deadline
checks. Combat decisions run on deadlines, not every frame. The trigger
queue, processed keys, history and cooldowns are all bounded.

## Limitations and future work

- **Player brawls** are modelled (`Participant.kind == PLAYER`, the
  `traffic` trigger) but disabled. Enabling them needs:
  1. the player's pose and on-foot state as the participant's position;
  2. a validated client intent (strike, dodge or retreat) that the server
     turns into an action through the same `_act` rolls, at the same action
     interval, never a client-sent result;
  3. HUD prompts;
  4. road rage feeding the attack, intimidation and defence formulas
     (rrt-019-brawl-02).
- Fights happen only between idle, parked rival taxis. A taxi on its way to
  a fare is never stopped for one.
- There is no punch sound or fight animation asset; figures use the
  pedestrian drawing.
- There are no police, injuries, reputation or damage consequences. These
  are outside this feature's scope.
