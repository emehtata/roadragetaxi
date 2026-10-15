# NPC traffic safety and liveness: next-phase plan

Date: 2026-10-15. Runtime baseline: `b885d0b` (`release/0.17.0alpha`).
The original work was an observation, gap analysis and implementation plan,
without gameplay changes. Subsequent implementation is recorded at the end;
diagnostic scripts are not imported by the game.

## Decision

Fix the trip lifecycle and recovery pipeline alongside collision prevention.
Simply reducing collisions is an insufficient success criterion: traffic can
stop crashing because nearly all vehicles have stopped making useful trips.
Keep authoritative decisions on the Python server, map levels separate, and
per-frame work bounded. Do not remove collision checks, pedestrians, sidewalk
protection or legitimate legal waits to improve the numbers.

## Observation method and limits

The requested ten-minute run uses `tools/observe_npc_traffic.py`, a real-time
30 Hz `SimulationServer` listening on localhost, without a graphical client.
The player remains stationary in the taxi. Oulu's local PBF supplies 8,851 ways
and 2,767 buildings; targets are 40 NPC vehicles, 20 moving,
and 60 ordinary pedestrians. Actual populations are measured, not assumed.
The seed is 20261015. Weather is held clear/dry at 18 °C to isolate traffic.
Historical weather, timetable downloads and map growth are disabled. Home and
outside-weather UI work are bypassed; NPC decisions and collision response are
unchanged. The ordinary no-fare calendar still runs at 60×; physical movement
uses fixed 1/30-second steps, paced against real time.

Collision instrumentation captures pre-response poses, dimensions, decisions,
nearby obstacles and five seconds of 4 Hz movement history. A separate read-only
socket client joins partway through the run, sends no controls, and samples
vehicle/pedestrian motion at approximately 1 Hz. A 30-second, two-metre
low-displacement flag is diagnostic only: parked visits and legal red-light
waits are not automatically stalls. Continuous client episodes and active-driver
poses are needed to distinguish them. Timed route budgets make seeded runs
not bit-for-bit deterministic; recording also adds some overhead.

The completed duration, tick count, final populations, crash count and waiting
measurements follow below. Raw reports and reproduction scripts are in
[the evidence folder](npc-traffic-safety-2026-10-15-data/README.md).
Headless observation does not establish rendered FPS. One stationary, dry-city
run cannot certify Finnish-law compliance or cover motorway, ice, snow, moving
player, dense queues, every junction, or cold streamed-map behavior. Pedestrian
state samples are not a pedestrian-injury detector. No claim of zero pedestrian
collisions is made.

### Completed ten-minute result

| Measurement | Result |
|---|---:|
| Actual elapsed wall time | 600.023 s |
| Simulation ticks / physical time advanced | 17,886 / 596.2 s |
| Calendar advancement with the normal 60× no-fare clock | approximately 9.94 game hours |
| Distinct NPC vehicle IDs seen | 47 |
| Vehicle collision events / distinct crashed NPCs | 2 / 4 |
| Final population | 40 total, 32 PARKED, 8 other states |
| Sampled STUCK → REVERSING / REVERSING → STUCK transitions | 258 / 258 |
| Server tick p50 / p95 / p99 / maximum | 5.53 / 8.76 / 15.84 / 168.00 ms |

The run started at 06:09:49 UTC and finished at 06:19:49 UTC on 2026-10-15.
The read-only client sampled 406 states from approximately 191.4–599.1 seconds.
All 32 parked cars remained within two metres of their first client position
throughout that 407.7-second window. The remaining eight never appeared as
healthy cruising traffic: their samples were WAITING, REVERSING or PARKING;
their maximum excursions from the first sampled pose were only 9.4–19.3 m.
Some samples still had speed above 0.5 m/s during these local maneuvers, so
“actually moving” alone also cannot establish useful trip progress.

The client collector found 139 low-displacement episodes: 44 vehicle and 95
pedestrian episodes. These include intentional parking/visits/activities and
must **not** be read as 139 deadlocks. The longest contiguous sampled pedestrian
`waiting_at_light` episode was about 12.15 seconds; an indefinite pedestrian
signal wait was not observed in this interval. Nor was a persistent mutual
vehicle wait-for cycle established. The confirmed late-run problem is traffic
lifecycle collapse and local recovery livelock, not proven junction gridlock.
The low overall tick p99 is not evidence of healthy traffic performance after
the workload has collapsed into mostly parked/stalled vehicles.

## Observed collisions

Both initial collisions reported road layer 0. Neither involved the stationary
player. The evidence includes endpoint OBB overlaps, not just nearby cars.

| Time after start | Vehicles and place | What the recorded history establishes |
|---|---|---|
| 44.307 s | 31, an 11.0 × 2.5 m vehicle on Hallituskatu; 49, a 4.3 × 1.8 m car on Mäkelininkatu | 31 received right-hand-yield braking and was fully stopped for over two seconds before impact. 49 approached at 30 km/h and hit at 16.4 km/h, despite a zero target speed and a “waiting for vehicle ahead” label. |
| 50.462 s | 38, a 4.3 × 1.8 m car; 57, a 7.5 × 2.3 m vehicle; both reported Kirkkokatu | 57 was stopped with a right-hand-yield decision. 38 still had `PROCEED`, “no relevant light ahead”, and a 30 km/h target/actual speed at impact. The vehicles' headings differed by about 80°. |

The first case disproves “having a yield decision is sufficient”: the stopped
vehicle's body still conflicted with the approaching trajectory, and the other
driver did not stop in time. The second exposes a similar occupied-path hazard
while one vehicle is mid-turn. Relative to 38's actual heading at impact, 57's
centre was 4.63 m laterally away, outside the fixed 2.5 m centre-based following
cone, despite their bodies overlapping. Avoidance actually uses the steering
target bearing, which was not recorded: the exact missed query is an inference,
not a fully replayed controller trace. Full-body trajectory prediction and
earlier stop geometry are needed, not a blanket reversal of right-hand priority.

Road names/current-way metadata are not proof of legal approach ownership:
`update_npc` adopts the next path point's way during turns. Exact OSM approach,
sign applicability, stop-line and incoming/outgoing lane evidence were not all
captured, so this report does not assign legal blame to a specific driver.

## Population collapse and repeated recovery

By 60 seconds the run reported 20 driving vehicles. By 180 seconds it reported
only eight, with 32 parked. Trip-start attempts/successes had plateaued at 72/45
by 150 seconds and remained unchanged at subsequent checkpoints.
“Driving” here includes WAITING, PARKING and REVERSING; it is not an actual-speed
or successful-trip measure.

In the client trace from approximately 191–318 seconds, vehicles 18, 28, 53,
66, 72 and 74 ended only 0–1.8 m from their first sampled positions, repeatedly
cycling among waiting, reversing and footprint-blocked parking. Vehicles 46 and
64 also repeatedly recovered, but had larger net displacement. The stopped
population must not be counted as healthy throughput. These observations show
recovery livelock/failed approaches; they do **not** by themselves prove a
multi-vehicle right-of-way deadlock.

### Confirmed trip-lifecycle defect

`PedestrianManager._materialize_parked_drivers` materializes every trip member
absent from the pedestrian list. `_update_linked_driver` correctly marks a
returning person boarded, then despawns that pedestrian. On the next frame the
materializer sees the same person absent, spawns them outside again and clears
their boarded flag. This can defeat `all_aboard` before the five-second
population tick gets a chance to continue the trip. Parked vehicles retain
drivers/groups, so they are neither idle trip-start candidates nor replaceable
empty parked vehicles. A population full of these cars cannot replenish moving
traffic.

A diagnostic reproduction calls the real materialize → reboard → despawn →
materialize sequence and confirms the boarded flag is cleared again. This is a
confirmed mechanism consistent with the population plateau, not a claim that
all 32 parked cars have individually been proven to hit it. Existing lifecycle
tests call the linked-person updater but do not adequately cover the next full
manager frame with rematerialization before trip continuation.

The six isolated baseline probes are saved as
[probes.py](npc-traffic-safety-2026-10-15-data/probes.py) with
[recorded outcomes](npc-traffic-safety-2026-10-15-data/probes-results.json).
All reproduced their stated defects. The existing crossing/NPC-population/
pedestrian test subsets still passed **158 tests**, demonstrating why passing
the present suite does not cover these missing acceptance scenarios.

### Other inspected recovery hazards

- `_run_population_tick` still runs trip continuation and recovery route searches
  synchronously against a shared eight-millisecond deadline. Timeout and genuine
  no-route both become an empty/None result. Recovery can then reverse although
  no route impossibility was established; repeated restarts can starve searches.
- Stuck detection exempts any crossing decision and broad final-approach states.
  Other blocked vehicles can loop through STUCK/REVERSING without a finite
  failure outcome or demonstrated forward-route progress.
- Reverse clearance is a circle behind the car, not a swept actual-size body
  checked against every relevant road user, curb/building and legal maneuver.
- Live footprint violation permits a crawl instead of preventing entry into the
  invalid pose. Route validation still uses generic NPC dimensions in important
  checks, while observed vehicles include 7.5 m and 11 m bodies.

These inspected hazards need targeted instrumentation/replays to apportion
their contribution to each observed recovery loop; do not treat every mechanism
as separately proven by the ten-minute run.

## Finnish-law gap map

Authority: [current Finnish Tieliikennelaki 729/2018](https://www.finlex.fi/fi/lainsaadanto/2018/729),
whose indexed consolidation identifies 2026-04-17; checked 2026-10-15. The full
page exceeded the browsing fetch limit; targeted indexed excerpts and the
repository's [Finnish NPC law guide](../../docs/finnish-npc-traffic-law.md) were
used. Implementers must recheck applicable current sections and exceptions.
The short legal requirements below are distinct from the proposed game algorithms.

| Legal duty | Current gap / evidence | Next implementation requirement |
|---|---|---|
| §§ 3–5, 20: anticipate danger, control speed and maintain safe clearance. | Both measured collisions struck an already stopped vehicle. Narrow centre cones do not represent an angled long body. | Predict actual-size swept conflicts along the intended movement and maintain a feasible braking envelope. |
| §§ 24–25: apply approach-specific priority and show yielding early. | Heading-ray intersections substitute for connected approaches; path metadata changes during turns. | Bind incoming/outgoing lanes, entry duties and signs to one real junction and conflict movement. |
| § 28: avoid obstructing crossing traffic if stopped in a junction. | Yielding did not ensure the whole stopped vehicle cleared the other's route; exit-space admission is absent. | Stop before conflict boundaries with front/rear overhang considered; require receiving-lane storage. |
| § 74, annexes 2 and 3.2: obey applicable signals and STOP controls. | A no-traffic STOP probe returns no stop decision. Yellow uses cruise rather than actual speed. A relevant light bypasses other crossing evaluation. | Independent B6 full-stop latch; actual-speed yellow commitment; retain turning and pedestrian duties on green. |
| §§ 24, 27, 29: protect pedestrians, including crossing intent and turning conflicts. | Ordinary NPC forward control has no equivalent of the needed crossing-intent/pedestrian constraint. | Add a shared pedestrian conflict input; do not rely on last-second player-only dodges. |
| §§ 30–35: safe meeting, passing, reversing and departure. | Passing/reversing checks are geometric shortcuts without full legal scope or swept pedestrian/obstacle clearance. | Validate legality, visibility, opposite traffic, full swept area and return space before committing. |
| §§ 13–16: use lawful walking space/crossings, exercise care and cross without delay. | Disconnected networks fall back to a straight connector; route-specific walkers bypass the generic light gate. | Lawful foot routing plus the same crossing gate for every walking purpose. |
| § 74, annex 2: use the pedestrian signal first, otherwise the signal in the walking direction. | “Any nearby approach green/yellow” blocks pedestrians, independent of their crossing or direction; it can stop an already-entered pedestrian. | Bind the actual crossing/signal and preserve crossing-clearance progress after entry. |
| Map separation is an implementation requirement for applying those duties correctly. | A separate probe confirms collision handling can crash two vehicles at identical x/y on different layers; following queries also lack equivalent filtering. | One consistent physical map-level test in prediction, following, collision, crossing, passing and recovery. |

No observed crash is presented as proof of every law gap. STOP, yellow,
different-layer collision and pedestrian-routing/signal defects were separately
probed; they were not necessarily exercised by the two recorded road crashes.
There is no legal “wait N seconds, then ignore priority” rule. Timers below are
diagnostic/game-policy thresholds, not statutory permissions.

## Ordered implementation plan

### 1. Restore a sound trip lifecycle and measure useful throughput (P0)

First atomic fix: one per-stop lifecycle for alighting, visiting, returning,
boarding and ready-to-depart. Materialize each person exactly once per stop;
reboarding must remain committed until departure/next stop. Keep person, driver,
vehicle and parking reservations consistent. Expired stragglers must not be
recreated as members of the same stop. Never despawn occupied cars merely to
satisfy the moving-traffic target.

Exercise full `PedestrianManager.update` plus `NPCVehicleManager.update`, including
the next frame after reboarding and the delayed population tick. Test multiple
members, unavailable pedestrian spawn points, partial return, expired members,
household return-home and crash cleanup. At least two complete park–visit–return–
depart cycles must succeed for the same car without cloned residents.

Add console/report counters for completed legs, actual moving vehicle-seconds,
ready-to-depart age, boarded/member counts, route-job age, timeout versus no-route,
recovery attempts and route arc-length progress. Do not call non-PARKED count
“moving” without also reporting actual speed. Retain bounded queries/work.

### 2. Make continuation/recovery resumable and resolve bad approaches (P0)

Reuse the existing round-robin route jobs for continuation and recovery, with
graph-revision, vehicle-state, reservation and occupant rechecks on commit.
Distinguish budget exhaustion, invalid geometry and unreachable destination.
Give existing blocked/ready vehicles fair service; new spawns must not consume
every work slice. Track progress along the route, not only centre displacement.

Carry the actual plugin length/width and turning capability through route,
parking and live swept validation. Avoid steering a large vehicle through a
car-sized accepted approach. Stop before a predicted invalid pose. Try a
different verified legal stop or abandon the trip safely when an approach is
unusable; do not repeat the identical invalid goal indefinitely.

Reverse only after explicit safe/legal clearance of the swept body, including
pedestrians, player, stationary cars, curbs, buildings and map level. Preserve
engine/gear behavior. Exhausted work budget must never itself authorize reverse.
Cap repeated maneuver attempts and escalate a persistent unresolved case to a
diagnosed safe hold/reroute, not forced driving or visible teleportation.

Acceptance: each eligible job advances under load and has an observable outcome;
valid deferred routes eventually complete without increasing frame budgets.
The recorded footprint/recovery cases must either finish or reach a stable,
explained safe fallback, not alternate forever between the same poses.

### 3. Prevent the two recorded occupied-path collisions (P0)

Add a short, spatially bounded trajectory/footprint safety horizon using actual
speed, dimensions, steering response and available braking grip. A geometric
collision threat must constrain motion regardless of who has legal priority.
Include stationary/yielding/parked/wreck bodies and angled vehicles, not just
centres within a narrow forward cone. Preserve the existing swept collision
detector as a final safety net and regression oracle; do not hide crashes by
changing overlap thresholds or disabling response.

Use the captured Hallituskatu/Mäkelininkatu and Kirkkokatu geometries as regression
fixtures. Capture more controller detail on rerun: lookahead target/bearing,
incoming lane, active constraint/blocker, predicted contact time and braking
margin. Tests must prove both non-collision **and later safe progress**, with
7.5/11 m vehicles, turning traffic, queues and permuted update order. Repeat the
different-layer probe with real manager updates: bridges must not block/crash
unrelated ground traffic, while same-level overlap remains detected.

### 4. Connected junction duties and lawful queue management (P1)

Reuse mapped logical intersections; resolve control applicability and movement
conflicts from connected approaches rather than infinite heading rays. Keep
entry-from-yard/parking duties separate from ordinary right-hand priority.
Handle B5 versus B6, signed priority endings/directions, left-turn/oncoming
conflicts, roundabout entry/exit and green-light residual duties explicitly.
Missing sign data must differ from confirmed absence. Keep an already-entered
movement's incoming identity stable until it clears the conflict.

Require downstream capacity before entering a box. Record wait reason, blocking
entity/conflict, stop position and next reevaluation; release promptly when the
constraint clears. Detect persistent wait-for cycles without city-wide all-pairs
scans. Scheduling may support explicit safe concessions (a game policy), but
must not give an arbitrary vehicle ID or elapsed timer legal priority. No
reversing around red lights, pedestrian waits or a legitimately queued leader.

Test rotated/mirrored unsigned junctions, T junctions, STOP with no traffic,
opposite-facing signs, green left turns, blocked exits, four-way contention,
queue spillback and bridge separation. A non-conflicting green/priority vehicle
must resume when its actual blocker clears; permanent legal obstructions must
remain safe and be diagnosed rather than “solved” by violating priority.

### 5. One pedestrian safety gate for every walking purpose (P1, alongside 4)

Route ordinary walkers, shopping/activities, taxi-stop customers, vehicle
approaches, group returns and crash evacuees through the same movement gate.
Currently `_walk_route_to`, linked-driver/activity handling and vehicle approach
can return before generic light handling. Fixing only ordinary wandering would
leave most purposeful walking unprotected.

Use typed walking/crossing connections with layer and access evidence. Prefer
nearby lawful crossing/underpass/overpass routes; absent those, assess the allowed
road-edge/perpendicular crossing fallback. Do not treat a direct connector
between disconnected graphs as automatically walkable. Use the appropriate
road edge when sidewalks/shoulders are unavailable, with documented exceptions.
Do not invent a statutory numeric meaning for “nearby”.

Represent approach/intent → wait → committed crossing → clear. Match the actual
pedestrian signal; use the correct directional vehicle signal only as the legal
fallback. Recheck before entry, but do not freeze a lawful pedestrian halfway
across because another traffic approach turns green. Preserve layer separation,
refuges and crossing length. Use approaching vehicle distance **and speed**,
stopping capability and relevant paths rather than a radial “within 10 m and
moving” veto. Vehicle yielding and pedestrian entry must coordinate so each does
not wait forever for the other. Clear crossings without unnecessary delay;
activities/boarding waits must stay out of the carriageway/crossing.

Tests: pedestrian red/green and phase change during crossing; waiting intent at
an unsignalized zebra; turning car; parallel traffic; different layers; refuge;
slow/vulnerable walker; disconnected network; missing sidewalk; each purposeful
walking branch; a stopped yielding car allowing entry and resuming only after
clearance. Keep mounted cyclists separate from pedestrians/walked bicycles and
apply their relevant controls, not an unconditional zebra priority.

### 6. Acceptance soak and performance guardrails

Turn both crash histories and the isolated probes into failing behavior tests
before their fixes, then assert safe passage, clearance and resumption rather
than merely checking helper outputs. Add real-map fixtures with stable OSM IDs.

After each atomic change run the traffic/pedestrian test subsets. Then repeat
the same ten-minute Oulu soak for at least three seeds and add a 30-minute soak.
Include 0/20/40/80 actors, moving player, parking turnover, bus/truck plugins,
day/night, rain/snow/ice, streamed topology changes and constrained intersections.
Use event-based logs so diagnostics do not become a new per-frame bottleneck.

Engineering acceptance targets (not legal rules): zero collisions in the
deterministic regression scenarios; no same-stop passenger rematerialization;
continued completed-leg throughput in every late-soak minute; no unexplained
ready-to-depart or recovery episode over 30 seconds; route jobs demonstrably
progress under the existing budget; no persistent unreported wait cycle.
Classify intentional visits, red/rail/pedestrian waits and external permanent
blockages separately—never shorten them just to satisfy a timeout statistic.
Report collisions per vehicle-km **and** moving vehicle-hours, completions,
safe-fallback rate and actual moving fraction. This run did not measure vehicle-
kilometres accurately enough to supply a reliable normalized baseline rate.

Maintain server tick p99 under 33.3 ms in a warmed 30 Hz run and keep routing/
population work within existing slices; report worst ticks and diagnostic
overhead rather than trading correctness for timing. Retest rendering separately.

## First implementation batch

Start with the next-frame reboarding regression and its lifecycle fix, then
resumable continuation/recovery with explicit outcomes, then the two full-body
collision regressions. Do not begin by changing global yielding delays, lowering
population targets, increasing blanket braking distances, or making red-light
queues trigger recovery. Those can hide symptoms without fixing the observed
failures. The subsequent intersection/pedestrian work should be paired so
neither side implements an incompatible right-of-way model.

## Implementation progress — passenger lifecycle

First atomic step implemented after the baseline observation:

- Track successful disembarkation once per member per stop, independently of
  current boarded membership. Returned members stay aboard after their
  pedestrian disappears; successful continuation resets the per-stop record.
- Remove explicitly despawning pedestrians before the next movement update, so
  a reboarded person cannot become an ordinary walker again while still counted
  aboard. Failed disembark spawns leave the person aboard and may retry.
- Pass the existing Resident ID to `spawn_pedestrian_at` instead of allocating
  an unrelated Resident and then overwriting the pedestrian's identity.
- Detach pedestrians removed from a group by its return deadline; they cannot
  subsequently board that old group. The actual driver is never discarded as a
  timed-out passenger, and trip continuation requires the driver to be aboard.
  A missing driver leaves the car safely parked; unreachable return routes and
  safe cancellation remain part of the following scheduling/recovery step.

Four initial regression cases failed on the old code and passed with the fix.
Coverage now includes full pedestrian update loops for one/three members,
post-reboarding cleanup and delayed population ticks, two actual visits and
departures through both NPC/pedestrian managers, failed-spawn retry, preserved
Resident identities, and return-deadline driver/passenger separation. The small
two-visit fixture isolates lifecycle/turnover; it does not certify dense-city
parking geometry or pedestrian traffic-law compliance.

Validation: **1,421 Python tests passed, 2 skipped**; focused NPC/pedestrian
coverage: **274 passed**. The diagnostic probe now expects no rematerialization;
its archived original `probes-results.json` remains unchanged. STOP, yellow,
pedestrian routing/signals, physical-layer collision filtering and trajectory
safety are still pending; no improvement to those behaviors is claimed.

Final-code real-time Oulu smoke check: **120.028 seconds, 3,593 ticks**, separate
from test-suite execution, using the same clear/dry fixture and seed. The
[recorded summary](npc-traffic-safety-2026-10-15-data/lifecycle-fix-smoke.json)
identifies `c0315fc` plus SHA-256 of the uncommitted runtime patch; that patch
was verified unchanged after the run. Groups in vehicles 3 and 7 remained fully
boarded after disembarkation/return, rather than being recreated outside.
Sampled arrivals numbered 21, but **no departures were sampled**: parked,
fully boarded cars still expose the continuation scheduling failure described
in step 2. Final counts were 40 total, 21 parked, 14 other non-crashed states and
5 remaining wrecks. There were **five collision events**; no collision-reduction
claim is made, and this shorter run is not a controlled collision-rate comparison
to the ten-minute baseline. Seeded trajectories also change when the unnecessary
Resident allocations/random draws are removed.

Next atomic step: resumable continuation/recovery jobs with explicit timeout
versus no-route outcomes and fair service for already waiting vehicles. The
small-fixture two-departure test establishes the lifecycle works when routing
can finish; it must not be mistaken for restored Oulu traffic throughput.

## Implementation progress — resumable continuation/recovery (step 2a)

Continuation, destination-conflict rerouting and recovery now use the existing
round-robin generator scheduler. Planning no longer restarts at the shared
population deadline. An unfinished generator stays pending; only a completed
search returning no validated plan counts as failure. The scheduler retains
its **2 ms frame budget and 0.5 ms slices**, with the existing caveat that a
single geometry operation is not preemptible.

Fresh idle/transit jobs may occupy only half of the eight job slots. Existing
ready/stuck trips are admitted oldest-last-served first, including competition
between continuation and recovery. A vehicle cannot acquire duplicate jobs on
successive population ticks. Pending recovery brakes to a stop and keeps its
route state rather than crawling while planning or reversing on budget expiry.

Before applying a delayed result, check the graph revision, vehicle presence,
driver/group identity, occupant/owner membership, vehicle state/origin,
destination, home intent and parking reservation identity/state. Recheck the
chosen destination against current vehicle claims and parking occupancy.
Discarding a result leaves the existing route/reservation/group intact; household
home intent changes only after commit. Successful continuation preserves the
same driver and group and resets only the next stop's visit bookkeeping.

A fully failed recovery now enters a diagnosed, stationary `HOLD` instead of
assuming a route failure proves reverse clearance. This is a conservative game
fallback, **not** a claim that stopping there resolves an obstruction legally.
Such holds can still block other traffic. Automatic alternative-stop selection,
actual-plugin-size/turning validation, route arc-length progress, safe/legal
swept reverse clearance and bounded maneuver escalation remain **step 2b**;
step 2 as a whole is not complete. Completed validation failures still report
“no validated route,” not an invented distinction between unreachable graph
and invalid geometry. STOP, pedestrian/junction duties, physical-layer safety
and the two measured occupied-path collisions remain later work.

Regression coverage includes zero-budget multi-frame progress alongside an
endless competing spawn job, no premature mutation/reverse, pending-job reuse,
reserved queue capacity, graph/driver/group/occupant/state/origin changes,
stolen reservations, newly occupied destinations and atomic household home
intent. The real two-visit manager-loop lifecycle test remains in the suite.
The observation harness now records completed continuation/recovery counts,
safe holds and pending route-job age alongside its original traffic evidence.

Real-time Oulu smoke: **180.014 seconds, 5,389 ticks**, same clear/dry seed and
map fixture, run separately from heavy tests. The
[saved summary](npc-traffic-safety-2026-10-15-data/resumable-routes-smoke.json)
identifies `9ce6e3e` plus runtime patch SHA-256; the runtime patch was unchanged
during observation. There were **2 sampled departures, 10 completed recovery
plans, 4 safe holds and 6 collision events**. The continuation counter also
includes destination-conflict reroutes; sampled park-to-driving transitions are
the independent departure check. Tick p50/p95/p99 were **7.49/10.16/14.72 ms**,
maximum **27.75 ms**. Worst routing work was **6.38 ms**, above its nominal 2 ms
budget because an individual operation remains non-preemptible.

Seven continuation jobs were still pending; the oldest was **2,208 frames
(73.6 simulated seconds)**. Successful resumption is now observable, but this
does **not** meet the plan's unexplained-wait/late-soak-throughput acceptance
targets or prove restored traffic flow. Final population was 35, with 25 parked
and 8 in other non-crashed states; those states are not proof of useful motion.
Six collisions in this short run do not establish a collision-rate improvement
or regression against either earlier fixture. Next: investigate expensive
rejected approach candidates, actual-size geometry and bounded safe alternatives
in step 2b, then the occupied-path safety regressions. The three-seed ten-minute
and thirty-minute acceptance soaks remain outstanding.

Final validation: **1,442 Python tests passed, 2 skipped**; observation harness
self-check and saved JSON validation passed. No Godot/rendering test was needed
for this server-only scheduling change. No junction/pedestrian legal rules were
changed, and no general Finnish-law compliance is claimed.

## Iteration — prevent unapproved off-road motion

User observation: NPCs visibly drove off-road. Ordinary travel must remain on
the carriageway; obstacles alone do not authorize an unchecked ground bypass.
This iteration adds a bounded, server-side live road-envelope guard for forward
and reverse physics. It samples nine actual-body points at up to one-metre swept
increments, capped at 32 poses. A rejected proposal is not published: retain the
previous pose, stop, label the boundary blockage and request the existing route
recovery. Both OSM layer and logical garage level constrain road coverage.
This is sampled protection, not an exact continuous polygon-containment proof.

Keep existing parking entry/departure within a short corridor around the planned
approach, including curved legs. Track the actual parked departure origin, not
the lane-offset route point. A transit endpoint merely flagged off-road does not
grant an exception when its endpoint is on the carriageway. A stationary safe
hold does not become STUCK merely because its existing pose is outside the road.
The parking corridors still rely on existing route/destination validation;
verified access, full bay footprint and generic-yard removal remain necessary
before claiming compliance with the new off-road policy.

Related causes fixed: preserve the off-road destination flag on continuation;
do not lane-offset an explicitly supplied parking destination; join the directed
road edge instead of routing a driveway exit through a junction behind it;
limit lookahead through sampled turns; apply yard pace over the entire bounded
approach/departure, not just the final waypoint. These are connected movement
fixes required to keep the household and two-visit turnover regressions working
under the guard, not permission to weaken the boundary when a route stalls.

Added regressions cover actual car/truck dimensions, indexed/unindexed roads,
bad headings, swept gaps, footways, bridge/garage levels, middle-of-trip and
transit-endpoint exemptions, actual parked origins, curved approach speed and
reverse road edges. The reverse-distance test now starts far enough inside its
road to reverse legally; a separate test verifies refusal at the road endpoint.
Arrival tests accept both coasting ARRIVING and already-stationary PARKED while
retaining destination-distance/parking-occupancy assertions.

Validation before the real-map run: **1,452 Python tests passed, 2 skipped**;
after the final level-filter changes, the focused NPC/pedestrian suite passed
**305 tests**. No claim of traffic maturity is made: route waits, collision
prediction, verified parking access and the ordered junction/pedestrian work
still need iteration and multi-seed acceptance soaks.

Real-time Oulu check: **120.024 seconds, 3,593 ticks**, run separately from the
test suite. The [saved summary](npc-traffic-safety-2026-10-15-data/road-boundary-smoke.json)
records the unchanged runtime patch fingerprint against `90f9dc0` and the first
blocked proposal for each affected vehicle. **13 boundary proposals were
blocked**, with **1 sampled departure, 1 collision and 16 recovery holds**.
There were **zero successful recovery plans**. Tick p50/p95/p99 were
**8.07/11.00/15.58 ms**, maximum **30.07 ms**; worst routing slice work was
**5.80 ms**, still above its nominal budget for a non-preemptible operation.
This short run is not a controlled collision-rate improvement claim.

The safety/liveness tradeoff is explicit: containment exposes bad routes instead
of letting cars leave the road. Several first blocks occurred at path index 1,
including a 7.5 m vehicle. Rejecting unsafe initial poses and carrying actual
vehicle dimensions through spawn/route/parking validation is the next iteration;
the current guard is not proof that every freshly spawned footprint was valid.
The 16 holds and low departure count fail the maturity/liveness targets. Do not
relax the road boundary or count the 20 non-PARKED labels as useful throughput
to hide these failures. No automatic off-road obstacle bypass is enabled.

## Iteration — actual vehicle sizes and safe initial poses

Carry plugin length/width through synchronous and resumable route validation,
curb/building checks, endpoint walkway exclusion, lane placement and parking-bay
selection. Direct `spawn_npc` now constructs the selected plugin's actual body
and capacity rather than a default car carrying another type's name. Parked
placement also refuses a mapped bay too small for the selected plugin.

Before publishing through traffic, validate the actual lane-offset starting
pose against the sampled road envelope and curb/building footprints. Update the
unpublished candidate to that exact pose before the existing commit-time player
distance, visibility and live vehicle-clearance checks; the seed graph-node
coordinate is not a substitute for where the car will actually appear.
Invalid candidates remain unpublished and still obey the spawn-attempt limit.
Ordinary direct spawns similarly require a road-contained starting footprint.

Preserve actual parked and recovering origins in lane construction instead of
offsetting them a second time. Recovery also removes a short, artificial
sideways graph-snap connector when the car is already on the carriageway; it
must not interpret that connector as an abrupt physical turn.

New tests cover five plugin bodies/capacities, a bus on a car-width road, curb
clearance that differs between car and bus, car bays rejected for buses,
unpublished off-road transit starts, actual parked origins and lane-positioned
truck recovery. Fixtures testing recovery/rage selection now spawn on genuine
roads before setting up their selection conditions, not inside grid blocks or
beyond the road's endpoint. The parking-orientation fixture now has a car-width
bay rather than a one-metre-wide strip. Assertions about the actual behavior
under test remain in place.

Full suite: **1,463 passed, 2 skipped**. This is not a maturity certificate.
The independently seeded [household replay](npc-traffic-safety-2026-10-15-data/household-seed-123.py)
still fails with a recovery hold; the same seeded household test was reproduced
as failing against baseline `dd7a87e` loaded in a separate diagnostic process.
The normal test's unseeded/global-RNG-dependent trajectory can pass while this
specific approach fails. Keep that evidence visible rather than treating an
arbitrary successful RNG trajectory as general household-turnover coverage.
This iteration does not yet validate full road containment along every planned
turn, turning feasibility, verified access for generic yard targets, predictive
vehicle conflicts or pedestrian/junction duties.

Real-time Oulu check: **120.011 seconds, 3,593 ticks**; the
[saved summary](npc-traffic-safety-2026-10-15-data/actual-dimensions-smoke.json)
records `dd7a87e` plus the unchanged runtime patch fingerprint. There were
**9 rejected boundary proposals, 1 sampled departure, 5 collisions and 13
recovery holds**, again with **zero completed recovery plans**. Tick p50/p95/p99
were **8.86/11.84/16.67 ms**, maximum **24.52 ms**; worst routing work was
**6.35 ms**. Dimensions/spawn validation alone have not restored useful traffic
flow or solved collision safety. The two short runs have different trajectories
and populations, so their collision totals are not normalized improvement or
regression estimates. Some first-motion blocks remain at path index 1: valid
initial containment does not prove the following maneuver is feasible.

The observation preceded four independently pushed map-picker/coastline commits.
The NPC change rebased cleanly over them; the combined branch then passed
**1,465 tests, 2 skipped**. No overwrite or force push was used.
