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
