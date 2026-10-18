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

### Building/road-bridge compositing (2026-10-17)

Screenshot `1792189216740344064` shows ground building roofs painted over
Joutsensilta. Collision separation was fixed earlier; the renderer still placed
road decks (z2–4) below both 2D and composited 3D buildings (z7).

Road layers 1–3 now occupy z8–10, above ground buildings, preserving their order
even across chunks. The underground mask is z11; road vehicles are z12;
canopies/rail bridges z13, trains z14 and price boards z15. Under-bridge vehicles
remain at absolute z1; reflectors remain z22. Deck wet shading/puddles stay with
their deck rather than disappearing beneath it or painting all ground effects
above roofs. Their extra static canvas items are limited to three per occupied
bridge layer (maximum three layers), hidden when dry. No per-frame geometry
rebuild, map-data changes, collision changes or PBF work.

Validation: cross-chunk order, all bridge layers, underground occlusion,
vehicle/canopy order and wet/dry passes are covered by the client suite.
The new `godot/tests/bridge_occlusion.gd` also renders actual pixels using Mesa
OpenGL compatibility: **both 2D and 3D building cases failed with the original
road ordering and pass with the fix**. The bridge covers the roof, with the
uncovered building still visible. Passing images were inspected and saved in
`/tmp/rrt-bridge-buildings-{2d,3d}.png`; rerun the script on a display to recreate.
The first sandboxed display attempt failed; the approved desktop run succeeded.
Python logical-level render tests: **5 passed**. Final client suite:
**850 checks, 0 failed**; diff check passes. Editor import generated the new
test script's UID, but sandbox restrictions prevented saving editor preferences
and opening its local listening sockets; the standalone tests above completed.

This remains ordered 2D compositing, not a shared physical-elevation depth
buffer: arbitrary tall-building/bridge clearances and layer-aware street-light
metadata are not solved. Full gameplay/FPS was not benchmarked. The existing
client-suite startup/cleanup diagnostics remain outside this fix.

### Active water-geometry task (2026-10-17)

Follow `.github/prompts/rrt-018-waters.md`. Detailed audit, confirmed real Oulu
geometry failures, implemented fixes, validation and remaining screenshot-wide
reproduction are recorded in [rrt-0.18-waters-progress.md](rrt-0.18-waters-progress.md).
This does not resume the excluded PBF-stuttering work or mark the broader living
city/safety target complete.

### Motorway transit spawning: no stopped cars inserted into flowing lanes

2026-10-17. User report: stopped NPCs appear on Pohjantie while the player is
driving above 100 km/h. The graphify query (`spawn transit speed parked`) located
the transit/parked creation chain; its older line locations were verified against
the live source rather than treated as current behavioral evidence.

Confirmed root cause: `_apply_transit_spawn` uses `_apply_npc_trip`, whose shared
`_begin_trip_on_vehicle` intentionally sets speed to zero for departures from
parking. That was also applied to newly inserted through traffic. Highway transit
now receives an initial speed *after* the parked-trip setup: 80% of its starting
road limit, capped by the vehicle plugin's maximum. This is a game policy, not a
statutory minimum speed. Ordinary parking departures remain unchanged.

The same policy is conservatively applied to motorway/trunk and their links.
New freeway traffic is rejected, not inserted stationary, if its route is too
short to brake comfortably, has a nearby turn, is near controls, or lacks a clear
braking-distance-plus-one-second gap from traffic/player. Conditions are checked
both during route preparation and at asynchronous commit, before replacing an
existing vehicle or creating residents. Nearby control presence conservatively
rejects the spawn even if the current phase is permissive. Live traffic decisions,
collision checks and lawful waits remain unchanged. No population cap or unsafe
forced acceleration was added.

The model's non-road vehicles and vehicles capped at 70 km/h or less cannot be
seeded on this freeway path (currently includes the 60 km/h tractor and 70 km/h
bus definition). This is about these model definitions, not a blanket ban on real
buses. It does not certify vehicle eligibility across every ordinary route.

Legal references checked against the consolidated
[Tieliikennelaki 729/2018](https://www.finlex.fi/fi/lainsaadanto/2018/729),
2026-04-17 consolidation: section 37 prohibits discretionary motorway stops but
allows compulsory traffic/yield/emergency stops; section 58 regulates eligible
motor vehicles. Trunk-road classification alone is not proof of motorway signing;
the shared spawn policy there is deliberately conservative.

Validation: eight rotated car/truck scenarios check the first committed frame and
five seconds of actual manager/physics updates alongside a 110 km/h player.
The zero-initial-speed reproduction failed all eight pre-fix initialization
cases (the initial reproduction used car/bus; the final eligible positive cases
use car/truck). Rejection tests cover fresh traffic, nearby player, short route,
turn, control, slow/non-road vehicles and forbidden roadside destinations.
Acceptance suite: **61 passed** (seed 1111877103); broader NPC/parking/priority
suite: **300 passed** before the final eligibility cases. Compile/diff checks
pass. Full randomized suite: **1,766 passed, 2 skipped** (87.83 s),
`--randomly-seed=3594144049`.

Limitations/resume: these are deterministic synthetic motorway trajectories, not
a replay of actual Pohjantie map data. They establish spawn initialization and
bounded safety rejection, not freedom from later routing stalls, collisions or
weather-dependent braking errors. No PBF/map optimization or Godot change.

### Invisible NPC collision on Hailuodon pengertie (2026-10-17)

Evidence: `screenshot_1792238617608587008` shows the player stopped on a layer-1
bridge. Its JSON records crashed competitor taxi 254 about 4.17 m ahead, but the
car is absent from the image. The old snapshot omitted NPC layer/LOD/on-foot
fields, so its exact client visibility inputs cannot be reconstructed.

Confirmed code defect: NPC physics calls have no road data and consequently do
not update `Car.layer`. Trip initialization also left the default layer zero.
Godot correctly routes a layer-zero car covered by a bridge below the deck,
making an on-bridge NPC invisible. Initialize the layer from the occupied start
road and refresh it after accepted motion, using only the current route road.
The existing geometric lookup keeps the old layer until that road is actually
beneath the car and cannot select an unrelated crossing bridge. Rejected motion
does not change the layer. This also covers reverse motion through the shared
motion-enforcement path. No city-wide lookup or client driving decision added.

The shared collision narrow phase previously ignored road/floor levels entirely;
it now excludes vehicles on different road layers or interior map levels,
including player/NPC and NPC/NPC pairs. Same-level wrecks remain solid.
Snapshots now record the NPC layer, map level, LOD and on-foot flag.

Validation: four road-layer spawn/update/protocol/snapshot cases, four transition
and unrelated-crossing cases, six collision separation/positive cases. Rendered
Godot regression verifies visible deck cars and hidden under-bridge cars with
both building rendering modes (six pixel checks including the existing building
checks, all passing). The original layer-one spawn assertion reproduced zero
instead of one before initialization was fixed. Focused NPC/traffic/protocol/
collision suite: **334 passed** (seed 2364576114). Full Python suite:
**1,780 passed, 2 skipped** in 99.75 s (seed 743673077). Godot suite:
**889 checks, 0 failed**; existing anchor/input/duplicate-signal and exit-resource
diagnostics remain. Compile and diff checks pass.

Limits: this reproduces the server-layer/bridge-occlusion defect with synthetic
geometry, not the original live session. Collision separation uses discrete OSM
layers, not physical deck heights; contact across a layer-transition boundary
is not modeled. Existing live-session cars need a simulation update/restart;
already crashed cars keep their frozen pose/layer until normal wreck cleanup.
Broader layer-aware following/traffic priority remains a separate task.

### Longer high beams across both lanes (2026-10-17)

Screenshot `1792250192564635904` showed the short, kerb-biased headlight cone.
Godot high beams now reach 150 m instead of 45 m and spread symmetrically across
both lanes (22.5 m half-width at the far end). Dipped beams retain their 15 m
reach/right bias, and train beams are unchanged. The oncoming detection range
and off-screen beam culling margin now match the 150 m reach. Existing automatic
dipping near street lights and oncoming traffic, bridge hiding, the 80-car cap
and batched rendering remain in place; no new lights or polygon clipping.

Tests cover four headings, both lanes 30 m ahead, reach, automatic dipping and
off-screen beam retention. Rendered low/high comparisons pass for the opposing
lane at 30 m and straight ahead at 90 m; images `/tmp/rrt-headlights-*.png`.
Godot suite: **908 checks, 0 failed**; existing UI/exit diagnostics remain. This is a visual tuning
change, not calibrated real-world photometry; no live driving/FPS benchmark or
Python suite rerun (Python unchanged). Existing beam/building masking behavior
is unchanged.

### Inari cold-start water geometry (2026-10-17)

Screenshot `1792250709006802176` stalled at 120 s on multipolygon 1/21.
The actual cached Inari extract (bbox 68.88648,27.12946,68.91352,27.20454)
contains 213,093 elements. Smart PBF extraction includes all of Inarijärvi
relation 402543: 158 outer and 5,066 inner member ways. A bounded 30-second
pre-fix profile of that relation did not finish: 21.57 s in `_water_rings`,
including repeated validity checks and splitting; containment also cost 6.52 s.

Fix: retain complete-reference/closed-ring/validity/containing-outer validation;
prepare each outer geometry once for island containment. Subtract all validated
islands, then intersect the result with the four-corner projected fetch region
before converting holes to hole-free renderer polygons. This preserves islands
crossing tile boundaries and avoids splitting thousands of distant islands.
Without fetch bounds, preserve existing whole-relation behavior. Water relations
no longer stitch outers twice, and their completion message follows the actual
water processing. The heartbeat remains only a liveness indication.

The actual Inari extract's complete `build_ways` stage now finishes in **2.36 s**,
with multipolygon 1/21 complete at 2.32 s (started at 0.66 s), returning 121
water records. This is map geometry build time, not an end-to-end startup claim.
Processed-cache format is 34 so old unbounded geometry is rebuilt; raw PBF/JSON
data is retained. Focused water/cache/PBF/startup tests: **61 passed** (seed
3053193970), including an island spanning adjacent clipped regions. Existing
Oulu flooding and incomplete-island regressions pass. Compile/diff checks pass.
First full run: 1,780 passed, 2 skipped, one pedestrian red-light failure (seed
1820452096). The same isolated test fails with both changed modules replaced in
memory by their HEAD versions, establishing a pre-existing seed-dependent issue;
it passes at seed 743673077. No unrelated pedestrian behavior/test edits made.
Full rerun: **1,781 passed, 2 skipped** in 100.33 s (seed 743673077).
Second actual Inari build with clipped-area conservation and validity assertions:
**2.47 s**, all outputs valid. No Godot or traffic changes.

### Group taxi fares and parent accompaniment (2026-10-17)

Screenshot `1792251484263926016` identifies Maria Eronen, born 2017-03-04.
The old fare generator allowed solo children from age seven. Fare organizers
are now generated as adults; ordinary generated requests can include 2–4 people,
including family fares with newly generated children linked to their actual
adult parent in the resident registry. Children under 18 require an adult from
their `parent_ids`, not just another adult. This is an explicit game policy,
documented in the traffic guide, not a statutory unaccompanied-taxi age claim.

Keep the existing lead passenger API and attach bounded companion records.
Street/stand pickups require a parent physically within 5 m and not driving;
when the parent hails, nearby children join too. Companion pedestrians transfer
to the fare representation without duplication. Rail greetings receive the
local pedestrians too, and newly visualized solo rail-taxi identities are adults.
Offer acceptance and live fare updates reject invalid/duplicate/over-capacity
groups. The five-seat taxi holds four passengers plus its driver. Everyone walks
to the door before the group boards, and all boarded weights contribute to mass.
Long-distance destination resolution updates every member. Dropoff, cancellation
and vomiting release the same resident identities; cancellation has a one-shot
release queue to avoid lost or duplicate passengers. One meter/one payment per
group. Godot draws all waiting companions and shows the phone-offer group count.

Checks include child alone/stranger/distant parent/driving parent rejection,
parent-first and child-first pickup, group boarding wait, identity-preserving
dropoff, duplicate/capacity rejection, generated families, cancellation/vomiting,
protocol data, and real server mass/cancellation updates. Focused lifecycle,
rail and protocol suites: 118 passed before the last positioning-only changes;
server/group tests: 11 passed. First full run: 1,790 passed, 2 skipped (seed
743673077), before two final tests were added. Final run recorded below.

Second full run: **1,792 passed, 2 skipped**, 100.05 s (seed 743673077).
After the final parent-actually-aboard/occupied-parent safeguards and their test,
focused fare/lifecycle/rail/protocol/headless-server tests: **138 passed**,
13.54 s (same seed). Godot: **910 checks, 0 failed**; compile/diff checks pass.
Rendered the real phone card, spotted/fixed fourth-line overflow by combining
count with the trip line, and inspected `/tmp/rrt-group-phone.png` after repair.

Limits: representative lead still supplies fare dialogue, happiness and nausea;
no per-person surcharge, child-seat equipment, child voice assets or general
on-foot family-following AI was added. Ages follow the existing resident age
calculation. No manual live-game visual/FPS session was performed. Existing
Godot UI and shutdown diagnostics remain unrelated.

### Clear stale destination arrow after a fare ends (2026-10-17)

Screenshot `1792252652673803008` shows the destination arrow despite no fare;
JSON confirms `current_passenger=null`, state PICKUP and zero passenger mass.
The server and navigation target already clear on vomiting exits. Godot's
`NavOverlay.update_view` queued drawing only for a nonempty target or enabled
compass, so clearing the last target with compass off left old canvas commands
visible indefinitely. Remember whether a target existed and request the one
redraw needed to erase it; idle no-target frames remain redraw-free. This covers
vomiting, cancellation and completed fares without changing their server logic.

Rendered `godot/tests/nav_clear.gd` checks a visible destination arrow then empty
target, with compass off/on. Old condition reproduces failure with compass off;
fixed condition passes both pixel checks. Navigation/group Python tests:
**30 passed** (seed 1339655107). No whole Python suite rerun for this client-only
two-line fix. Godot suite: **911 checks, 0 failed**; existing UI/shutdown
diagnostics remain unrelated.

### FMI fetch-failure console diagnostics (2026-10-17)

Observation and forecast network/XML exceptions already logged WARNING, but now
include exception type/reason, location, observation UTC-hour range where
applicable, existing 60-second retry backoff, and explicit cached/generated
fallback wording. Empty parsed observation/forecast responses also warn instead
of reporting only a successful zero-hour fetch. No fetch scheduling, cache,
weather generation or forecast-source attribution behavior changed.

Six parameterized tests cover offline, malformed XML and empty responses for
both queries, including unchanged exception retry backoff. Weather/history
suites: **47 passed** (seed 2340526910); compile/diff checks pass. A fake offline
fetch with normal `configure_logging('INFO')` visibly emits the warning to the
console without file logging. No real FMI request or full suite rerun needed
for these diagnostics. The previously diagnosed generated-thunder/source-label
problem remains a separate, unchanged issue.

### Reserve player clearance during NPC population placement (2026-10-17)

Screenshot `1792253226651350016`: taxi trip distance is only 0.537 m; NPC 13
is crashed 3.022 m away. Their oriented footprints intersect at the recorded
poses (also when shifting the taxi back by its entire recorded travel distance).
Initial population placement checked other NPC positions/reservations but never
the already-placed player taxi. A screenshot-coordinate startup regression
reproduces the unsafe parked-car placement before the fix.

The shared `_place_one` helper now accepts the current player position. Startup,
runtime parked top-up and transit staging all supply it. Reject before assigning
a vehicle ID or claiming a parking space. Clearance is at least the existing
7 m spacing, increased for long vehicle definitions using both vehicles'
bounding-circle radii plus 1 m. The taxi envelope uses the conservative default
NPC car dimensions, larger than the current player taxi. This is a spawn policy,
not an arbitrary traffic stop/despawn or a legal parking-rule change. Other
collision and reservation validation stays in place; no per-frame city scan.

Tests: captured spawn coordinates, four directions × car/bus × too-close/safe,
actual player-body nonintersection at four headings for accepted positions, and
no parking claim on rejection. Focused NPC/population/acceptance suites:
**321 passed** (seed 2319294418); compile/diff checks pass. Full results below.

Full run (seed 743673077): **1,816 passed, 2 skipped**, one client/server
fixed-sleep timing failure in 88.20 s: after 50 ms, `try_recv_latest` returned
an initial map `chunk` rather than the expected `state`. It failed before any
movement assertion. Isolated retry passes, and all **14 integration tests pass**
together on retry (7.18 s, same seed). That unrelated timing-sensitive test was
not changed in this spawn fix.

Limits: no complete original Oulu session/render replay. This prevents new NPCs
being placed into the player envelope; it does not relocate existing wrecks,
change ordinary moving-car avoidance or make manual taxi respawn search existing
vehicles. No Godot/rendering or map-source change.

### Keep the last good FMI forecast across failed refreshes (2026-10-17)

Successful forecast fetches already persisted to the OS-specific SQLite weather
cache. However, startup ignored entries older than one hour, and an empty FMI
response replaced both memory and disk forecasts with nothing. This could leave
generated weather after a restart despite a previously downloaded forecast.

Load saved forecast hours regardless of fetch age, retaining the original fetch
timestamp. The one-hour refresh policy still queues an update, but existing
hours are immediately available while it runs. Network/parse failures and empty
responses retain the last successful forecast, without marking it fresh, and
apply the existing 60-second retry backoff. Successful refreshes still replace
and persist the forecast. Cache location/schema and generated weather are
unchanged; the proposed deterministic-generator changes were withdrawn in favor
of the requested cache fallback.

Tests: six cases (offline/malformed/empty × in-session/restart) verify immediate
stale-cache availability during a blocked fetch, retention in memory and disk,
original fetch age and retry backoff. A successful-refresh test verifies the
new values survive restart. Weather/history suites: **54 passed**, seed
743673077. Server suite: **40 passed** with local-socket permission (the
restricted run could not create its test socket). Compile and diff checks pass.

Limits: stale forecasts can be inaccurate, and only explicitly cached hours are
used—there is no extrapolation beyond their time range. No live FMI outage or
rendered game replay was performed. Missing cache/hour still uses generated
weather; this does not make cold startup wait indefinitely for FMI.

### Preserve FMI observations independently of refresh age (2026-10-17)

Completed observation chunks remain permanently cached as before. Previously,
expired recent-chunk markers prevented loading their retained observation rows
on restart. Now those rows are loaded regardless of age and remain available
even if a subsequent fetch fails. If every requested hour is already observed,
no observation request is queued, even for an old incomplete chunk. Missing
hours still allow a fetch; an incomplete chunk must not be marked complete just
because real time has advanced. Forecast refresh rules are unchanged.

Regression: simulate an old incomplete chunk, restart without requests for known
hours, request missing hours with an offline fetch, then restart again and verify
the original observation survives without another request. Weather/history
suites: **55 passed** (seed 743673077); compile/diff checks pass. No schema
change, cache deletion, generator or rendering change. No live FMI requests or
full-game replay; genuinely missing hours may still require downloading their
containing chunk, rather than a separate per-hour query.

### Use previous cached FMI weather for a missing current hour (2026-10-17)

Current-hour precipitation now falls back to the latest strictly earlier usable
FMI observation or forecast for this location. Search both loaded data and the
existing SQLite history, so an observation outside the loaded three-day chunk
can be reused. Temperature-only records and future hours are not fallback
candidates. Exact-hour FMI precipitation always wins, including when it arrives
after startup. Missing-hour fallback is selected once per game hour, not queried
from SQLite each frame; the console warns with the original UTC hour and age.
No save, map, audio, cache-schema or weather-generator changes.

Tests cover disk history, location isolation, future exclusion, temperature-only
entries, newer usable forecast selection, repeated fallback without repeated
lookup/logging, and replacement by exact-hour dry weather. Weather/history and
socket-free server checks: **96 passed, 1 deselected** (the unrelated local-socket
test), seed 743673077. Compile and diff checks pass.

Limits: the requested fallback intentionally has no age cutoff, so old cached
weather can be inaccurate. With no usable earlier FMI record, generated weather
remains the last resort. Missing-hour fallback applies to current conditions;
the start-screen future forecast still uses exact-hour FMI where available.

### Bypass vehicle-body polygon triangulation (2026-10-17)

Reported `_paint:630` is the vehicle-body polygon submission, not lamps or
pedestrians. Its convex/finite/degeneracy check remains, but body fills now
submit explicit triangle fans, like the existing lamp meshes, instead of asking
Godot to triangulate map-relative coordinates. Outlines remain unchanged. Shared
`_paint` covers both ordinary and under-bridge vehicle bodies. No simulation,
traffic, weather or audio changes.

Tests: six convex coordinate/winding combinations plus collapsed and crossed
geometry; client suite **919 checks, 0 failed**. OpenGL rendered regression
`godot/tests/vehicle_body.gd`: **3 positions, 0 failed**, including coordinates
100 km from the origin; filled pixels verified, no triangulation error. Existing
client-suite startup signal/anchor/input and shutdown-leak diagnostics remain.
Diff checks pass. The exact original session geometry was not captured/replayed;
the precision mechanism is suspected, while bypassing that triangulator in the
reported fill path is verified. Keep body parts convex as required by the
existing drawable guard.

### Start 0.18.0alpha release preparation (2026-10-17)

Aligned Python package version `0.18.0a0` (PEP 440), Godot displayed version
`0.18.0alpha`, Windows EXE file/product version `0.18.0.0`, Inno Setup version
`0.18.0alpha`, and the README tag example. Added a consistency regression so the
installer and exported client cannot silently retain a different version.
Historical version references and untracked user prompt files are untouched.

Godot: **920 checks, 0 failed**, with existing signal/anchor/input and cleanup
diagnostics. Compile and diff checks pass. Full Python suite (seed 743673077):
**1,827 passed, 2 skipped, 1 failed** in 91.02 s. The known fixed-50-ms-wait
integration test received an initial map `chunk` rather than a `state`, matching
the earlier documented timing failure. Integration/version retry: **14 passed,
1 failed** in 6.84 s; the original state test passed, but the fixed-wait map-chunk
test collected 46 of 49 expected chunks before its assertion. The new version
consistency test passes. Networking timing checks therefore remain an explicit
release gate, not a claimed clean suite.

Not published: no tag, GitHub release or master merge. Next gates: review full
test results, Windows build/installer and in-game smoke testing (especially the
reported intermittent audio crackle), review release notes and the unresolved
asset-rights items already recorded in `LICENSE_AUDIT.md`. A `v*` tag triggers
the Windows workflow's public release publishing step; do not tag prematurely.

### Suppress match-day notices after the match ends (2026-10-17)

Client-connect schedule notices now omit games whose modeled end time is at or
before the current game time. Reuses `arena_crowds.GAME_DURATION` (2 h 30 min),
the same end boundary as arena game activity, rather than a separate duration.
Upcoming and ongoing games still appear; an entirely finished schedule produces
no notification. Existing once-per-session notification behavior is unchanged.
No spectator, routing, audio, or fixture-data changes.

Regression cases cover before kickoff, kickoff, one second before modeled end,
exact end, late evening, and reconnect deduplication. Real final-whistle times
are not provided by the current model; unusually long/short games retain the
existing estimated duration. No rendered game replay or Windows build here.
Server/arena/version suites: **57 passed, 1 deselected** (local-socket test),
seed 743673077. Compile and diff checks pass.

### Store remaining external JSON datasets as gzip (2026-10-17)

Converted the OSM-derived places database and Oulu water regression extract to
`.json.gz`; also converted both offline OSM samples because their provenance
is unresolved. Existing municipality, name, sports-fixture and railway datasets
were already gzip. The four converted files shrink from **698,558 to 181,234
bytes**, with decompressed bytes verified identical to the prior git versions.
Plain originals are replaced, not retained alongside compressed copies; they
remain recoverable from git history. No rewrite of history, user saves or caches.

Updated places/sample readers, GTFS-to-OSM station matching, the places exporter,
coastline fixture tests, benchmark, PyInstaller Windows sample bundle, licence
inventory/notices and documentation paths. The exporter retains atomic rename
and produces deterministic gzip (`mtime=0`). Custom plain JSON inputs remain
supported by the places and sample loaders. A truncated-gzip regression checks
graceful places fallback; a dataset check rejects plain duplicates and validates
all bundled gzip JSON. Added the external-dataset policy to Copilot instructions.
Project-owned manifests/configuration, dialogue and performance reports remain
plain JSON; no provenance or licence status is changed by compression.

Focused suites before the final policy test: **151 passed, 1 deselected**
(local-socket test). Godot: **920 checks, 0 failed**, with existing diagnostics.
Full Python suite: **1,835 passed, 2 skipped** in 90.36 s, seed 743673077.
The previously timing-sensitive networking checks passed in this run (no claim
that their fixed-wait sensitivity was repaired). Compile/diff checks pass. Windows packaging was
updated but an actual Windows executable/installer has not been built here.

### Refresh bilingual website for release preparation

Marketing downloads now point to the published `v0.17.1alpha` installer, while
the release-notes section explicitly previews the not-yet-published 0.18.0alpha.
Finnish and English cover group fares/parent accompaniment (game policy), map
layer and lake fixes, sun-driven shadows/high beams, FMI cache fallback and
traffic/spawn work without promising flawless traffic. Corrected phone N/P
controls, generated street-light placement and weather availability claims;
added F/E/G/J controls and seasonal-event copy. Historical screenshot assets are
retained and explicitly labeled earlier alpha builds, rather than relabeled as
0.18 captures. The isolated Oulu comparison capture had an empty phone and was
not suitable to replace the existing populated-phone marketing image.

Fixed the two localization crashes: 19 feature cards had 18 translations, and
five release-note rows had four. Now both languages cover 20 features (including
calendar events), all five preview notes and 13 control rows. Hero metadata and
the gallery disclaimer also translate. Chromium inspection with remote fonts
blocked exposed clipped hero headings/download actions; responsive font sizing,
content width and height now keep the actions visible with fallback fonts.

Verification: **3 Node checks passed**, covering both startup languages,
repeated toggles, HTML/data row parity, current installer links and local image
paths. **6 focused pytest checks passed**, including the Node wrapper, version
and licence inventory checks (seed 743673077). JavaScript syntax/diff checks
pass. Real headless Chromium-shell renders verified Finnish desktop (1440×1000)
and English mobile (390×844), including translated release text. Full Chromium
CLI stalled; it was stopped and the working headless-shell check substituted.
The existing font hosts were blocked for bounded offline rendering, so final
downloaded-font appearance remains unverified. No site deployment or release
tag; no game/simulation, user-save or audio changes. Download labels should be
updated again only after 0.18 is actually published.

### Client graphics options (2026-10-18, master)

Added Settings → Graphics with saved, default-on switches for building sun
shadows, 3D buildings, water/puddle ripples, precipitation particles, tyre
splashes, vehicle smoke/exhaust and lightning flashes. Labels and help cover
Finnish, English and German. Startup reads boolean values from `[graphics]` in
Godot `user://settings.cfg` for normal and skip-menu launches. Changes to effects
apply live; 3D/2D choice applies on the next session, explicitly labelled, to
avoid rebuilding every loaded chunk or mixing renderer modes during streaming.
The existing 2D renderer retains visible buildings and all server collisions.
CLI `--buildings` remains an explicit presentation override.

Disabling shadows turns off the sun's shadow generation and shadow viewport;
re-enabling invalidates the solar cache so the same sun position works again.
Map layers created later inherit the shadow setting. Disabled precipitation
does not advance particles; disabled ripples hide and stop scheduling the
water/puddle scan. Disabled splashes skip puddle probing/spawning and clear
old rings. Smoke returns before puff drawing. Lightning hides the flash only,
leaving thunder and weather alone. No simulation commands/rules, physics,
weather accumulation, collision/map layers or saves were altered.

Other candidates considered: seasonal decorations/fireworks and vegetation
animation are cosmetic but not included in this first set. Headlights, street
lighting, traffic controls, road snow/wetness, tyre tracks and obstacles remain
visible because they communicate driving conditions or hazards. No FPS gain is
claimed without rendered hardware measurements. README describes the options.

Verification: **1,863 Python tests passed, 2 skipped** (92.31 s, seed 743673077).
Godot: **1,579 checks passed, zero failed**, including saved/default/malformed
values, all-language labels/help, disabled weather work and unchanged input
state, re-enabling, 2D/3D session selection, shadow-viewport shutdown/restoration
at identical sun coordinates, and submenu persistence. Existing test-harness
anchor/input warnings and exit resource-leak diagnostics remain. Thirteen
focused packaging/render-style/localization/version tests also passed; diff
checks pass. Tests use isolated user/config/cache paths; no player bank/save
data used. No Windows build or interactive GPU benchmark performed.

### German game language (2026-10-18)

Added Deutsch to first-run and settings language selection, persisted through
the existing Godot settings path and passed as `--language de` to the server.
All 222 Python message keys and all Godot UI keys have German translations,
including navigation, settings help, loading details, passenger labels, phone
booking/group fares and inspector values. Added German subtitles to all 30
driver and 50 passenger lines without changing their Finnish hashes or audio
assets. Driver/passenger playback uses the separately tested Finnish fallback;
German recordings would be preferred if installed later. The recording scanner
and client file allowlist recognize the supported German language code.

Live language changes also send validated `command.language` to the server,
updating both server and taxi-manager language for subsequent notifications and
speech. Malformed/unknown codes are ignored. Existing messages already on screen
are not retroactively rewritten. Euro receipts use a decimal comma for German.
Updated README and client architecture notes; website language remains unchanged.
Legal credits, Finnish place/street names and station audio are retained.

Verification: **1,863 Python tests passed, 2 skipped** (92.94 s, seed 743673077)
and **1,502 Godot checks passed, zero failed**. The Godot harness still reports
its existing anchor/input warnings and shutdown resource leaks. Also passed 43
focused localization/speech/fare/client-server checks, website regression checks,
Python compile and diff checks. Coverage includes all-language key/argument
parity, German menu selection, inspector/phone/navigation/subtitles, real German
speech events backed by Finnish OGG files, and live language switching through
a socket with malformed codes ignored. Tests use isolated saves/config/cache
paths; no player bank data or real career was used. No new voice generation,
interactive layout replay or Windows build performed.

### Missing voice recordings fall back to Finnish (2026-10-18)

Both driver and passenger speech now select the Finnish recording when a clip
for the requested language is absent. This covers situation responses, periodic
chatter and explicitly requested lines while retaining gender and the existing
busy/cooldown rules. Subtitles retain the requested language when translated;
missing text falls back to Finnish instead of silencing an available recording.
No available recording remains silent. Thirteen speech tests passed, including
German subtitles with Finnish voices, both genders, all passenger entry points,
native-voice preference and no-recording behavior. No audio generation required.

### Game localization audit and passenger labels (2026-10-18)

Fixed hard-coded `[TO TAXI]` in the Godot passenger overlay: Finnish now shows
`[TAKSILLE]`, English keeps `[TO TAXI]`, and waiting passengers use the translated
pickup label. Both lead passengers and companions use the same formatter.
Reviewed menus, HUD, phone, inspection panels, loading/progress and server text
tables. Booking status values in phone titles/cards/details now use translations
instead of raw English enums. Inspector gender, pedestrian/vehicle states,
activity names and vehicle types are translated through the existing FI/EN
tables. Unknown future enum values retain a readable fallback; names, addresses,
real-world signs, legal attributions and developer diagnostics are not rewritten.

Changing language rebuilds the open settings menu, not just the running HUD.
Deferred menu focus checks the control still exists/is attached after a menu
rebuild. Removed the test's duplicate shell construction, which previously
registered the same viewport signal twice. Also translated the Python table's
Finnish settings-arrow hints and respawn label.

Verification: **1,221 Godot checks, zero failed** in isolated XDG data/config/cache
directories. Existing anchor/input warnings and shutdown resource-leak reports
remain; no rendered interactive replay or Windows build. **51 focused Python
tests passed**. Full Python suite: **1,851 passed, 2 skipped, 1 failed** (94.28 s,
seed 743673077): the unrelated reconnect test received world/chunks before its
state message. That test plus the three new localization tests passed on rerun
(4 passed). No transport behavior was changed to mask the timing failure.
New checks cover language-key and format-argument parity, all current vehicle
types/pedestrian/NPC states/activity names, passenger tags, phone booking statuses
and actual inspector text. A static audit found no missing literal server `tr`
keys. Diff checks pass. User saves/bank data were not used.

### Market the taxi antihero and rage superpower (2026-10-18)

Bilingual content review: compared every feature, release note, roadmap card,
control and heading. Gameplay promises, limits, future-feature status and
downloads match. Aligned the English adventure badge and playground wording;
removed the miles-only phrasing. Fixed Finnish no-JavaScript feature introduction
to include the full description. Gallery captions now switch languages rather
than mixing both; all six image descriptions, navigation/home/hero accessibility
labels and language-switch labels are localized too. Added checks for matching
translation keys, numeric claims per feature/note/control, translated gallery and
accessibility labels through repeated toggles, and Finnish gallery fallback.
Three Node checks and six focused pytest checks passed (seed 743673077), plus
JavaScript syntax/diff checks. No deployment or browser layout render.

Player-facing copy pass: rewrote technical feature/release descriptions in both
languages and the Finnish fallback. Removed engine/server badges, map-data
jargon, rendering/layer details, background tile loading, spawn/recovery terms,
HUD shorthand and cache explanations. Focus now stays on familiar streets,
night shifts, discoveries, fares and smoother driving. Kept controls, future
ideas clearly marked, installer links, source-repository link and the general
unfinished-game warning. Website checks now reject selected developer jargon
in translations and visible HTML text. Three Node checks and six focused pytest
checks passed; no game changes, deployment or browser render.

Weather marketing follow-up: replaced availability/cache/fallback detail in
the weather feature with player-facing atmosphere and driving stakes in Finnish,
English and the HTML fallback. Three Node website checks, JavaScript syntax
and diff checks passed. Copy only; no browser render or deployment.

Release-ready copy correction: per user request, both languages now describe
the latest version, not an upcoming update or unpublished development branch.
Hero, rage feature, screenshot note, release-note headings/lead and download
callout were updated consistently, including Finnish HTML fallback and search
description. Existing published installer links/version remain unchanged;
update the download target as part of publishing the release. Three Node checks,
JavaScript syntax and diff checks passed. No deployment or browser render.

Version-neutral copy follow-up: removed explicit 0.18.0 references from both
website languages, the Finnish fallback and search description. Upcoming
features remain labelled as the next update; published installer version and
links are unchanged. Website tests now reject reintroducing the removed version
in either translation or HTML. Three Node checks, JavaScript syntax and diff
checks passed; no deployment or new browser render.

Marketing follow-up: replaced FMI, VR, Digitraffic and weather-provider names
with general weather and train-timetable wording in both languages and the
Finnish HTML fallback, including upcoming-release notes. Kept map-data source
references intact; no data-source configuration or gameplay behavior changed.
JavaScript syntax, three Node website checks and diff checks passed. No browser
render or deployment performed for this copy-only follow-up.

Updated Finnish and English website hero, introduction and highlighted rage
feature around the taxi antihero: build enough rage, shout other drivers aside,
and floor it. Finnish copy leads with “Lyhyt pinna. Yliluonnollinen raivo.” and
“Huuda ruuhka helvettiin”; English uses “Short fuse. Supernatural rage.” and
“Shout traffic to hell”. The user-approved short-fuse slogan replaces the
less clear cape/patience wordplay.
Added the ten-second clearance and 210 km/h example to both upcoming-release
note lists. Updated Finnish no-JavaScript fallback and search description too.
The new power is explicitly coming in 0.18.0alpha; downloadable installer links
remain 0.17.1alpha. No invulnerability or scenery-clearing promise.

Verification: **3 Node checks and 6 focused pytest checks passed** (seed
743673077), covering both languages, repeated toggles, row parity, installer
links, local assets, release versions and licence inventory. JavaScript syntax
and diff checks pass. Copy-only change; no new browser render, full game test
run or website deployment performed.

### Implement arcade rage road clearance (2026-10-18)

Replaced the old one-driver, 40 m, eight-second slow crawl and edge steering.
An accepted shout (existing 0.25 rage cost, horn and five-second visible line)
now activates ten seconds of direct NPC roadside displacement. Lookahead is
ten seconds at the taxi's current speed plus body/movement margin: about 583 m
plus margin at 210 km/h, with a 60 m minimum at low speed. Follow loaded road
bends and the straightest connected continuation, retaining each segment's
bridge layer and the taxi's logical map level. Recompute as the taxi moves;
newly arriving/spawned cars are affected during the active window.

`road_rage.py` owns this temporary state under `NPCVehicleManager`, on the Python
server only. Clearance runs before taxi physics/collisions and before NPC
movement. All eligible vehicles are moved immediately, including oncoming,
waiting, parked and crashed vehicles; no normal steering/light/right-of-way
decision can veto it. Circle envelopes account for full vehicle dimensions;
crowded slots are spaced outward without overlapping other NPC bodies, and
late job-completion spawns are reindexed before slot selection. No identities,
occupants, trip groups, parking claims or original crash states are discarded.
Held cars skip normal driving, parked departure and population recovery/trip
candidates. After the active window, return to the original road position only
outside the taxi's forward corridor/proximity envelope and with the slot clear
of other vehicles; restart from rest rather than pop back at cruising speed.
Prune references when ordinary population/wreck cleanup removes a held car.

Updated the traffic-law guide with the explicit user-requested arcade exception;
ordinary NPC routing/parking still has no permission to use it. Removed obsolete
nearest-driver/crawl tests and replaced them with corridor and lifecycle tests.
Four headings at 210 km/h, all five moving/waiting/parked/wreck/oncoming cases,
large vehicle dimensions, curves/continuations, separate bridge/map levels,
new arrivals, 25-car overlapping jam, occupied rejoin slots, dense road vertices,
real NPC update loops, repeat-shout timing, population recovery exclusion and
minimal-manager diagnostics are covered. A full server-tick control reproduces
a collision with an NPC five metres ahead at 210 km/h without rage, while rage
clears that body before the collision pass.

Verification: final full run **1,849 passed, 2 skipped** (93.63 s, seed
743673077), including the held-population, late-spawn and actual server-tick
collision regressions. Earlier focused NPC/population/server run: **312 passed**
(one local-socket test deselected). Compile/diff checks pass.
Synthetic 100-car initial clearance: **23.07 ms**;
rolling updates: median **0.33 ms**, p95 **0.38 ms**, max **0.73 ms**, before the
additional O(population) entry reindex. This is a synthetic Python measurement,
not an overall FPS claim. No audio/rendering/protocol or save format change.

Limits: artificial roadside slots deliberately bypass terrain/building/water
and lawful parking checks. This is arcade clearance, not emergency priority or
general traffic-law compliance. Pedestrians, trains and scenery are not moved.
Unknown turns are not predicted, only loaded connected geometry is followed,
and the corridor walk is capped at 4,096 vertices per pass. Normal scenery,
pedestrian/rail and bridge-edge hazards still exist for the taxi. No full Oulu
rendered driving replay or Windows build was performed for this change.
