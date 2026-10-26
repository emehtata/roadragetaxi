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

All of them come from existing events. None of them scans every pair of NPCs.

| Trigger | Source | Notes |
| --- | --- | --- |
| `passenger` | `competitor_taxis.Dispatcher`: a fare goes to one idle taxi while another idle taxi waits within `ENGAGE_RADIUS_M` | `DISPUTE_CHANCE` (0.15) |
| `rank` | every `RANK_CHECK_INTERVAL_S` (30 s): pairs of idle, parked rival taxis within `ENGAGE_RADIUS_M` | `RANK_CHANCE` 0.002 per pair, or `NIGHT_RANK_CHANCE` 0.02 at the Friday/Saturday 22–06 nightlife peak (`nightlife_peak`). Away from a taxi stand (`TAXI_STAND_RADIUS_M`), times `RANK_FALLBACK_FACTOR` |
| `traffic` | the player's minor bump of a rival taxi (`npc_manager.taxi_bumps`) | player against NPC (see "Player brawls") |
| `provoke` | on foot, a SPACE shout (it needs the rage a shout costs) within `PROVOKE_REACH_M` (6 m) of a rival taxi with its driver aboard (`simulation._provoke_rival`) | player against NPC; the driver also gets `PROVOKE_TAUNT` rage |

These values are game estimates, not incident statistics, and are kept rare
on purpose. All tunables are module constants at the top of `taxi_brawls.py`,
like the other simulation tunables.

**Eligibility** (`_eligible_npc`) requires all of these:

- the vehicle exists and is a competitor taxi;
- it is `PARKED` and has its driver (against the player: any state but
  `CRASHED`, as long as it has stopped, below 0.5 m/s);
- it is not in another brawl, not held by rage clearance, and has no
  queued route job (against the player, a queued job may wait);
- it is not cooling down from an earlier brawl;
- it has no fare aboard, and is not stopped to board or drop one off.

The two taxis must be within `ENGAGE_RADIUS_M` of each other and on the same
layer and map level. Against the player, the rival must be within
`PLAYER_ENGAGE_M` (15 m) of the player or the player's taxi, on the player's
map level. The player must have no fare in or for the taxi, and must not be
in `PLAYER_COOLDOWN_S` (60 s) after an earlier brawl. A participant cannot fight themselves. Each trigger
event has a key; a key that was already processed is ignored
(`PROCESSED_TRIGGER_MEMORY`), and so are duplicates queued in the same tick.

## Combat

Each driver has three traits fixed per vehicle id (`driver_traits`):
aggression, skill and retreat. These are personality and never change. On
top of them comes the participant's current **road rage** (next section),
which is temporary. All rolls use the manager's `rng`; tests seed it, and
the same seed plays out the same fight.

With `m(r)` the rage modifiers below, `a` the attacker and `d` the defender:

| Decision | Formula |
| --- | --- |
| Who strikes | weight `aggression + 0.1 + m(r).initiative` each, unless one is staggered: then the other strikes |
| Hit | `0.45 + 0.5 × (a.skill − d.skill) + m(r_a).attack − m(r_d).defense`, clamped to 0.1–0.9 |
| Staggered by a hit | with chance `1 − m(r_d).stagger_resist`: loses the next initiative |
| Surrender after a hit | `d.retreat × hits × 0.2 × (1 − m(r_d).stagger_resist)` |
| Back down (confrontation; escalation × 0.5) | `retreat × (1 − opponent.aggression) × (1 + m(r_opponent).intimidation)`, at most 0.95 |

The clamp means rage never guarantees a hit or a win. Skill, the opponent's
traits, staggering and the dice still decide.

## Road rage

Rage is 0..1 for everyone. **One function**, `rage_modifiers(rage)`, turns
it into modifiers for players and NPCs alike. Out-of-range, NaN or
non-numeric values are clamped to 0..1, with NaN and garbage counting as 0.

| Modifier | At rage r | Default at full rage |
| --- | --- | --- |
| `attack` (+ hit chance) | `RAGE_ATTACK_BONUS × r` | +0.12 |
| `initiative` (+ strike-first weight) | `RAGE_INITIATIVE × r` | +0.6 |
| `intimidation` (opponent backs down × (1 + this)) | `RAGE_INTIMIDATION × r` | ×1.8 |
| `stagger_resist` | `RAGE_STAGGER_RESIST × r` | 0.6 |
| `defense` (≤ 0: easier to hit) | `−RAGE_DEFENSE_PENALTY × smoothstep((r − 0.7) / 0.3)` | −0.15 |

Offence grows linearly with rage. Defence is untouched up to
`RAGE_EXTREME` (0.7) and then drops smoothly, so a raging fighter hits
harder but is easier to hit, with no jump at any threshold.

**The player**: the rage is the existing meter, `rage_power` (0..1, the HUD's
"Rattiraivo"). Speeding, waiting at red lights and sliding raise it; legal
driving lowers it; a shout spends 0.25. The simulation passes it to
`BrawlManager.update(player_rage=…)` every tick. It never comes from a client
message, and fighting never changes it.

**NPC drivers**: there was no NPC rage before, so `NPCVehicle` gains `rage`
and `rage_at`, the level at the last provocation and its sim time.
`npc_rage()` subtracts the calming since then (full rage to calm in
`NPC_RAGE_CALM_S`, 180 s) when it is read, so a calm or idle NPC costs
nothing per tick. `provoke()` raises it, bounded to 1:

| Provocation | Where | Amount |
| --- | --- | --- |
| the player's taxi bumped it | `npc.py` minor bump | 0.5 |
| shoved aside by the player's rage clearance | `road_rage.py` | 0.3 |
| a rival took the fare it was waiting for | `competitor_taxis.Dispatcher` | 0.3 |
| each blow taken in a fight | `taxi_brawls._act` | 0.15 |

Rage is read at every decision (`BrawlManager.rage`), so a change during a
fight counts from the next action. Rage does not change how often brawls
start; it only affects the fighting.

## Player brawls

The player fights with the keys they already have. These are the existing,
validated command fields: a client cannot send an action result, a winner
or a rage value, because `protocol.command_from_message` keeps only known,
typed fields.

| Key | Out of the taxi in a brawl | Otherwise (unchanged) |
| --- | --- | --- |
| SPACE | strike: in CONFRONTATION or ESCALATION it starts the fight at once with the player's blow | road rage shout |
| Shift (held) | dodge: the rival's next blow loses `PLAYER_DODGE_BONUS` (0.3) hit chance, never below 0.1 | sprint |
| F | run: outcome `fled`, and the rival wins | get in or out of the taxi |

How a player brawl goes:

- **Bumped rival.** The rival's driver gets out and walks to the player's
  driver door. The player is told "a rival driver is coming to have it out".
  - Getting out (F) starts the fight.
  - Driving more than `PLAYER_LEAVE_M` (8 m) away gives `player_left`.
  - Staying at the wheel for `PLAYER_WAIT_S` (8 s) gives `ignored`.

  The rival's car stops where it is, with hazard lights, and the NPC update
  skips it while `brawl_id` is set.
- **Provoked rival.** The driver gets out and comes to the player.
- **On foot in a brawl.** `BrawlManager.player_locked` holds the player in
  place, facing the rival, from confrontation to the end of the fight, and
  for `KNOCKDOWN_GET_UP_S` after a knockout. The walking input is ignored
  then.
- **Who strikes.** The player strikes only when they press SPACE. Otherwise
  the rival swings, one blow per `ACTION_INTERVAL_S`. The staggered rule
  still applies to both.
- **Odds.** Every roll uses the same `hit_chance` and `rage_modifiers` as NPC
  fights. The player's skill is `PLAYER_SKILL` (0.55), and their rage is the
  meter.
- **Backing down.** The dice never make the player back down or surrender;
  only the rival rolls to back down, with the player's rage intimidating it.
  The player gives up only by running.
- **Outcome notices**, through the existing notification line (fi/en/de):
  `brawl_won`, `brawl_lost`, `brawl_backed_down`, `brawl_fled`, `brawl_left`,
  `brawl_ignored`, `brawl_separated`. The on-foot hint line shows the fight
  keys during the brawl.

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
`curse_timer`, `curse_text`, `rage` rounded to 0.05 for display only, and
`in_car`, true for a player still at the wheel, who is not drawn). It holds
the current state only, never a
history, so a client that connects late cannot replay a fight. The F12
debug snapshot has `brawls.active`, `brawls.recent` (the last 20 outcomes)
and `brawls.rejected_triggers`.

## Presentation

Each fighter is drawn with the pedestrian figure: standing or walking, fists
up, `fallen` when down, with a curse bubble. The player's fighter wears the
player's yellow and replaces their walking figure. The face flushes red with the
fighter's rage, and anger marks appear above 0.7. A punch plays once per new
action `seq`, so a duplicated or late update never swings twice. Sounds:
`vehicle.door_open` and `vehicle.door_close`, `pedestrian.curse`, and
`collision.fence` as a stand-in for a hit, because the audio catalog has no
punch sound yet.

## Performance

Measured on 2026-10-26 with 300 NPC vehicles (10 idle rival taxis), 30 Hz
ticks, calling `BrawlManager.update` alone:

- no conflict: 0.38 µs per tick (the player's rage clamped, plus an id
  lookup every 30 s);
- one active fight: 12.1 µs per tick, with rage read at each decision.

Only active conflicts do per-tick work: two figure poses plus deadline
checks. Combat decisions run on deadlines, not every frame. The trigger
queue, processed keys, history and cooldowns are all bounded.

## Limitations and future work

- NPC-against-NPC fights happen only between idle, parked rival taxis. Only
  the player can stop a rival on the road.
- A brawl has no effect on score, money or the rage meter. The notices are
  its only consequence for the player.
- There is no punch sound or fight animation asset; figures use the
  pedestrian drawing.
- There are no police, injuries, reputation or damage consequences. These
  are outside this feature's scope.
