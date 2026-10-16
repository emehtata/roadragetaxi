# 0.18 living-city work: audit and implementation record

Date: 2026-10-17. Starting revision: `7a445cf`, branch `release/0.18.0alpha`.
Scope: `.github/prompts/rrt-0.18-target.md`. This is an incremental work
record, not a claim that the target is complete. PBF stuttering, parsing,
loading and rendering optimization are explicitly excluded. No release or tags.

## Phase 0: current repository audit

| Area | Existing foundation | Gap / next verification |
| --- | --- | --- |
| Identity and ownership | `ResidentManager`, `HouseholdManager`, resident vehicle/group links | No general persistent resident activity/trip lifecycle or daily schedule. Test cross-manager ownership, not just lists. |
| Vehicle travel | `NPCVehicle`, `Driver`, `TripGroup`, resumable revision-bound route jobs, reservation revalidation, recovery HOLD and cleanup | Route-job completion is not physical trip completion. Existing counters do not establish completed/failed journey rates or full legal compliance. |
| Pedestrians | Walk network, activities/plugins, reservations, linked vehicle boarding/alighting, prevention of repeated disembarkation | Disconnected pedestrian networks still return direct connectors; safe access and route failure need dedicated coverage. |
| Signals and conflicts | Shared signal decisions, approach direction, right-hand crossing checks, following, footprint/obstacle checks | Confirmed: yellow stopping feasibility uses posted/cruise speed rather than actual speed. Signal stop buffer is fixed rather than vehicle-length-aware. STOP-without-conflicting-traffic and connected turn conflicts need later verification. |
| Calendar and demand | `GameCalendar` advances local Finnish game time, seasons, DST; pedestrian amenity cadence changes after 17:00 | No shared smooth weekday/weekend demand profile. `ActivityContext` carries simulation time, not the local calendar/weather demand context. |
| Venues and events | Liiga fixtures, `ArenaEvent`, entrance lookup, arrival/departure windows, lights, departures seeking taxi stands | Arena-specific visible sampling, not a shared resident-trip/vehicle/parking demand model. Departures are newly spawned pedestrians rather than tracked returning attendees. |
| Observability | Population diagnostics, route-job statistics, bounded wait-frame samples, existing observation tools | Current collision, trip-throughput, rule-violation and long-stall rates need a fresh controlled scenario; old reports are historical evidence only. |
| Architecture | Python owns rules/simulation; Godot presents state. Existing network/spatial indexes and activity managers | Keep these owners. Do not add parallel resident, event, route or population systems. |

Inspected: `npc.py`, `traffic_rules.py`, linked-driver and network sections of
`pedestrian.py`, `residents.py`, `activities/base.py`, `activities/manager.py`,
`arena_crowds.py`, `sports_fixtures.py`, `calendar.py`, server/simulation call
sites, `docs/architecture/godot-client.md`, the Finnish NPC traffic-law guide,
and the historical 2026-10-15 traffic-safety report.

### Ownership to preserve

- Resident/household registries own identity and ownership, not drawn entities.
- Vehicle manager and driver own planned movement, reservations and recovery;
  graph revision and occupant snapshots invalidate stale asynchronous commits.
- Pedestrian manager owns visible walking/activity and linked boarding/alighting;
  `TripGroup` records who is aboard and who has already disembarked at a stop.
- Calendar owns game datetime; arena crowds currently own fixture timing.
- Server advances these managers; the client must not independently assign priority.

## Ordered implementation plan

1. **Traffic safety and lifecycle:** establish current regression baseline;
   reproduce yellow-speed/long-vehicle stop errors, fix shared server decisions,
   add real approach/wait/resume trajectories. Next: STOP latch, connected
   junction/turn conflicts, legal waits versus failed recovery, lifecycle cycles.
2. **Demand:** extend existing calendar/manager inputs with smooth distinct
   weekday/weekend profiles. Verify accelerated time and continuity before wiring
   population changes; do not mass-respawn or impose new population caps.
3. **Resident journeys:** use existing identities, trip groups and destinations;
   record lifecycle outcomes and validate boarding/arrival/return across managers.
4. **Events:** extend the arena/fixture foundation into shared venue demand,
   preserving attendance identity and distributing travel/parking/taxi departures.
5. **Validation:** deterministic multi-junction/long-vehicle/event scenario,
   before/after collision and completed-trip counts, legal-wait classification,
   extended run and tick-time measurements. Do not infer FPS from headless ticks.

## Baseline and first slice

Before production edits, the current branch's full regression baseline was
**1,595 passed, 2 skipped** (48.26 s). The new acceptance scenario then failed
in **all 8 trajectories**: car and bus, each rotated in four directions, crossed
the signal with their front footprint despite approaching at 2 m/s with room
to stop. This is a measured scenario-specific violation baseline, not a fresh
city-wide collision or completed-trip rate. Broad observation remains pending.

Legal reference for the first slice: [Tieliikennelaki 729/2018, annex 2](https://www.finlex.fi/fi/lainsaadanto/2018/729),
checked 2026-10-17. Yellow prohibits passing the primary signal/stop line unless,
at the green-to-yellow change, stopping safely without danger or hindrance is
no longer possible. The existing comfortable-deceleration value is a game-model
parameter, not a statutory stopping-distance formula.

### Slice 1: yellow-light stopping and long-vehicle clearance

Implemented in the shared server decision and `update_npc`:

- Actual speed, rather than the road limit, determines whether stopping is feasible.
- Neither the stopping nor already-committed yellow branch requests acceleration
  above the current speed. Existing no-speed callers retain their compatibility fallback.
- A decision to stop is retained for the same yellow signal, preventing physics
  perturbations near the stopping-distance boundary from cancelling braking.
  Green and a different physical signal do not inherit that latch.
- NPC stop buffers cover at least half the vehicle length plus 2 m; the existing
  4 m minimum remains. No population caps or collision checks were removed.

`tests/test_finnish_traffic_acceptance.py` adds the dedicated acceptance-suite
entry point. Eight real `update_npc` trajectories test 3 seconds of yellow,
10 seconds of red, then 4 seconds of green at 30 Hz: footprint remains behind
the signal, a legal wait does not trigger recovery, and each vehicle resumes.
Four focused cases test actual speeds above/below the limit, stopped vehicles,
and signal-specific latch reset. Existing NPC, event/calendar, resident and
broader regression tests remain part of validation.
The acceptance cases use seed `20261017` and restore the caller's random state.

Validation: **12/12 new cases pass**; **165 focused NPC, priority, event,
calendar, resident and fixture tests pass**; full regression **1,607 passed,
2 skipped** (48.95 s). Compile-check and diff-check pass. Baseline versus fixed
stop-line violations in the eight approach trajectories: **8/8 → 0/8**, with
green-light resumption verified for all eight. Suite duration is not a gameplay
FPS measurement. The seed-isolation fixture was also rerun separately: 12 pass.

Commands:

```sh
.venv/bin/python -m pytest -q tests/test_finnish_traffic_acceptance.py
.venv/bin/python -m pytest -q
make compile
git diff --check
```

Limitations: this does not implement a full green-to-yellow phase-entry snapshot,
weather-specific braking, STOP-sign latching, movement-specific green conflicts,
or general traffic compliance. No fresh rendered FPS, long-running city metrics,
or event-linked journey completion rates are claimed. The remaining slices
above, including the controlled long-running baseline, are still required.

## Slice 2 complete: sign delivery and mandatory STOP

Confirmed that
`TrafficWorld` ignored `stop_signs` passed by map synchronization, startup did
not pass either sign list, and streamed synchronization omitted give-way signs.
Sign positions are roadside posts, not separately mapped stop lines: the first
implementation must label its projected-post stopping position as a conservative
game fallback, not claim exact stop-line/junction visibility compliance.

Implemented both sign delivery paths and a local nine-cell sign query, replacing
per-vehicle whole-map sign scans. The driver latches a full stop once per approach;
the latch survives equivalent streamed sign objects, clears after leaving, and
does not remove the independent crossing-yield check. Irrelevant opposite/upper
road signs and give-way signs do not force an unconditional stop. Operational
signals take precedence. Roadside applicability now accounts for road width.

Validation: 8 rotated car/bus stop/resume trajectories, 4 negative/green cases,
crossing-yield-after-stop and stream-replacement tests. Full suite: **1,621
passed, 2 skipped** (49.82 s). One earlier non-escalated socket test was blocked
by the sandbox; the complete socket-enabled run above passed.

Legal reference: B6, annex 3.2, and signal precedence under section 8;
[2026 amendment 281](https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2026/281)
(effective 2026-05-01) checked alongside the consolidated act on 2026-10-17.
The game uses <0.05 m/s as stopped and a projected-post position with a 1 m
nose margin. Exact mapped stop lines, junction visibility and advance plates
are not implemented by this slice. No PBF parser/loader/render optimization.

## Continuation checkpoint

### Slice 3 complete: retirement and resident trip reuse

Normal retirement now clears only the retiring group's resident trip and
active-vehicle links, restoring household/walking mode while preserving registry
identity and household/vehicle ownership. A stale group cannot unlink a resident
already assigned to a different trip. Beginning a reused trip assigns the real
driver/riding modes and active-vehicle links to all members, not only the driver.
The live-trip-group admission check remains: a visit outside the vehicle does
not make somebody available for a simultaneous second trip.

Validation: a real vehicle-manager + pedestrian-manager drive-home/retire/next-trip
cycle, stale-group protection and existing two-visit/reboarding tests pass.
Full suite: **1,623 passed, 2 skipped** (51.35 s). Physical disembarkation still
uses existing trip-group boarded membership; this slice does not redesign that
ownership or clear identities while a visit remains in progress.

Next checkpoint: a fresh offline ten-minute fixed-step observation has completed
using the existing observation tool (sample map, no PBF). Inspect its collisions
and low-progress reports before starting demand work. Tool changes and the
observation report are the next independent slice; do not include them in the
retirement commit. Broader city/event validation remains pending.

### Slice 4 complete: fresh observation and stopping-distance lookahead

The existing `tools/observe_npc_traffic.py` now accepts `--use-sample` and
`--unpaced` (fixed-step physics duration, not an FPS benchmark). A 600-second,
18,000-tick offline sample run found 2 collision events, 15 successful trip
starts, no sampled arrival/departure transitions, and repeated STUCK/recovery
cycles. Nine ways/two buildings do not represent city-wide demand or events.
One collision was a roughly 61 km/h NPC rear-ending the stationary player;
the fixed 30 m detection cone was shorter than comfortable stopping distance.

Implemented: derive
following detection and the manager's spatial-query radius from current speed,
braking distance, one second of margin and vehicle lengths. Existing cone/lane
tests and braking caps remain; no global vehicle scan or population cap.
All 16 new rotated car/bus-versus-player/NPC trajectories failed before the fix
and pass after it. Full suite: **1,639 passed, 2 skipped** (51.58 s).

Evidence is committed in `.github/performance-analysis/rrt-0.18-offline-baseline.json`
and `rrt-0.18-offline-following.json`, including source revision, runtime patch
hash, seed, compact incident poses and low-progress records. Original full
temporary logs remain under `/tmp/rrt-018-{lifecycle,following}-observation/`.

Repeat result: the player rear-end did not recur, but **5 collision events**
occurred versus 2 before; **23 successful trip starts** versus 15, no sampled
arrival transitions in either run. Timed route-job scheduling and subsequent
random choices diverge, so these are not a controlled collision-rate improvement.
The deterministic following trajectories establish the specific fix; the
observation still fails general safety/liveness goals. Tick p50/p95/p99:
baseline 0.77/1.37/2.55 ms, following 0.84/1.41/2.50 ms. Both ran alongside tests;
these timings are diagnostic, not isolated performance or rendered FPS claims.
The one-second detection margin is game policy; the stopping/following duties
come from sections 5 and 20 of the consolidated Finnish act checked 2026-10-17.

Resume here: **recovery claims success without physical progress**. The baseline
had 290 `recovered` route commits and thousands of stationary-driver samples;
valid-looking paths repeatedly reverse direction near the same blocked pose.
Bound repeated recovery plans by actual displacement, distinguish legal waits,
retain safe HOLD/new-destination recovery and documented cleanup. Add regressions
before claiming this issue fixed. No demand/event maturity claim yet.

### Slice 5: bound physically unsuccessful recovery (2026-10-17)

Implemented three recovery route commits per five metres of real displacement,
then safe HOLD and the existing bounded new-destination/failed-car cleanup path.
Successful-looking unhold plans retain the failure history until the car moves.
Ordinary queue waits are excluded from stuck recovery; wrecks/parked obstacles
still qualify. Regression coverage checks the limit, resident-link cleanup,
physical-progress reset and queue resumption. Initial full suite exposed an old
generic stopped-obstacle fixture; it now explicitly represents a wreck, and the
queue exemption excludes wrecks. Focused suite: **154 passed**. Full validation
result: **1,642 passed, 2 skipped** (51.77 s); compile-check and diff-check pass.

The first 600-second offline repeat completed: 9 collision events, 46 trip starts,
19.06 seconds wall time. This is **not** a safety pass or a collision-rate
improvement. Recoveries may terminate instead of repeat forever, but executable
initial-heading routes and junction safety still need work. Original logs:
`/tmp/rrt-018-recovery-observation/`. No PBF/rendering work performed.

Final-code repeat evidence is committed as
`.github/performance-analysis/rrt-0.18-offline-recovery.json` (raw logs in
`/tmp/rrt-018-recovery-final-observation/`). Same fixture/seed and 18,000 ticks:
**12 collision events**, **41 successful starts**, no sampled trip completions,
77 recovery route commits and 70 safe holds. Tick p50/p95/p99:
0.97/1.60/2.97 ms; 19.13 s wall time. As before, tests ran concurrently and
route-job timing changes subsequent random paths. More starts/replacement traffic
are not proof of completed journeys or improved collision rates. `recovered`
continues to count committed plans, not successfully driven recovery. The
deterministic regression establishes bounded retries and cleanup, not city safety.

The three-plan/five-metre threshold is game policy. It measures displacement,
not monotonic route progress; a large wiggle could reset it. Upgrade to a
route-progress measure if observations demonstrate that failure. No reversing,
off-road permission, collision suppression or population cap was added.

### Exact resume point after slice 5

1. **Reproduce a remaining collision deterministically before editing.** In the
   final report at 66.433 s, stopped vehicle 10 at (423668.42, 7207194.47),
   heading -1.623, is hit by vehicle 14 at (423669.36, 7207198.54), heading
   -1.806, speed 2.83 m/s. Both are labelled WAITING. Inspect route-target
   versus physical-heading lead detection and full-footprint stopping at low
   speed; the first impact alone does not establish which branch is wrong.
   Later collisions include impacts into already crashed cars. Preserve
   collision detection and lawful yielding; do not just shorten despawn timers.
2. **Initial-heading route executability:** repeated plans point behind a held
   vehicle, then road-footprint guards stop motion. Validate the departure
   connector/body sweep from its real pose; cleanup is only a fallback.
3. **Pedestrian signal lifecycle:** inspect the generic red-light check in
   `PedestrianManager.update` and `_is_pedestrian_red_light`; currently an
   already-crossing person can be reclassified as waiting. First verify legal
   crossing/clearance requirements and actual entry/exit geometry; the current
   CROSSING flag alone is proximity-based and is not proof of legal entry.
4. Add completed/cancelled trip accounting and deterministic full drive/visit/
   home cycles before moving into demand rhythms and shared events. The sample
   observation records no arrival transitions and cannot certify those phases.

Keep the ordered plan above. PBF work remains excluded, no tags/releases, and
the unrelated untracked `roadragetaxi.code-workspace` must remain untouched.

### Screenshot fix: building beneath Joutsensilta (2026-10-17)

Screenshot `1792188346686098944` places the taxi at
(428036.2884, 7209070.0431), on Joutsensilta, OSM layer 1 but logical
map level 0. These are intentionally different coordinates. Building collision
only checked the logical floor; the road-footprint overlap fallback does not
cover a roadside building touched by the car's collision radius.

The simulation now passes its current road to building collision. Surface
buildings are ignored only while that road is a car-drivable, positive-layer
bridge matching the taxi's layer/floor and the taxi centre remains on its deck
corridor. A stale bridge reference after leaving the corridor, a different
layer/floor, ordinary roads and garage-floor buildings retain collision checks.
The building itself is not deleted or changed; rendering is unchanged.

Added eight regression cases for bridge clearance and negative cases. Focused
collision/level suites: **68 passed**. Full suite: **1,650 passed, 2 skipped**
(56.02 s). Compile and diff checks pass. Visual gameplay was not rerun.
Limitation: OSM building heights and bridge deck elevations do not currently
provide a shared physical clearance model. Deck support is the explicit game
fallback, not a general three-dimensional collision solution. No PBF work.

### Screenshot fix: ground railways beneath road bridges (2026-10-17)

Screenshot `1792188564863280896` shows Poikkimaantie at OSM layer 2.
The Godot chunk renderer drew all ground tracks at z6, above road decks
(z2–4), irrespective of the server's correct road layer. Ground ballast,
sleepers and rails now draw at z1 after ground roads, below elevated decks.
The separate elevated railway/deck rendering remains at z11. No map parsing,
physics, routing or per-frame work changed.

Godot regression covers road layers 1/2/3 and both cross-chunk arrival orders,
plus preservation of elevated railway rendering. Headless client suite:
**822 checks, 0 failed**. Diff check passes. Visual gameplay was not rerun;
the suite also emits startup
signal-connection and resource-cleanup diagnostics outside this change.

### Runtime speed-camera placement (2026-10-17)

Removed the startup batch (up to 20 cameras in the opening map). All existing
camera placement was procedural, not imported mapped cameras. New games now
start with none. The authoritative server attempts one camera after a random
120–300 seconds of physical simulation time, then schedules another interval.
There is no catch-up batch after a long tick. These are game-design timings,
not a change to legal speed limits or enforcement rules.

Candidates come from the existing nearby road grid (up to 128 roads within
2 km), retain the existing main-road/direction/roadside placement rules and
exclude garage roads. Placement must be 300–2,000 m from the taxi and at least
1,500 m from any existing camera. If nothing qualifies, skip that interval.
Existing cameras remain fixed for the session; append-only IDs preserve flash
and enforcement identity. Runtime insertion invalidates just the affected chunk's
wire cache and resends it only to clients already holding it. New clients/chunks
get it normally. Placement pauses while map growth copies/swaps chunk indexes,
preventing lost camera updates. No whole-map rebuild or protocol change.

Validation: timer/startup/spacing/road-and-floor exclusions,
affected-chunk cache invalidation, client delivery/stable IDs, and map-growth
hold regression. Full suite: **1,657 passed, 2 skipped** (50.47 s); compile
and diff checks pass. Existing overspeed detection tests remain unchanged.
Rendering is unchanged; visual gameplay has not been rerun.
