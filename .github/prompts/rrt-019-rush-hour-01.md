# Task: Fix NPC Vehicle Spawning and Implement Reliable Rush-Hour Traffic

Repository: `emehtata/roadragetaxi`

Target branch: `release/v0.19.1alpha`

The project uses a Python simulation server and a Godot rendering client. The server remains authoritative for vehicle movement, NPC behavior, road routing, collisions, and population management.

## 1. Problem Statement

NPC vehicle spawning frequently fails. As a result, the actual number of moving vehicles remains too low, and realistic afternoon rush-hour traffic cannot develop.

The current implementation already has:
- A time-dependent traffic demand model.
- Measured Finnish traffic profiles derived from Fintraffic LAM data.
- Urban and rural traffic profiles, including weekday and weekend differences.
- Local population and road-class-based traffic demand.
- A separate target for moving traffic.
- Asynchronous route-planning jobs.
- SpawnMemory for remembering successful and repeatedly unsuccessful spawn locations.
- Vehicle placement, road, collision, and route validation.

Relevant implementation files include:
- `src/theroadragetrip/npc.py`
- `src/theroadragetrip/population.py`
- `src/theroadragetrip/traffic_world.py`
- `src/theroadragetrip/physics.py`
- `src/theroadragetrip/traffic_rules.py`
- `src/theroadragetrip/config.py`

Relevant existing tests include:
- `tests/test_traffic_demand.py`
- `tests/test_traffic_fill.py`
- `tests/test_npc_population.py`
- `tests/test_through_road_spawn.py`
- `tests/test_npc_motorway_spawn.py`
- `tests/test_nightlife_traffic.py`

Read the actual implementations and current tests before making changes.

The goal is not merely to increase the configured vehicle count. The goal is to make the existing traffic demand result in a sufficient, stable population of genuinely moving NPC vehicles on real Finnish roads.

## 2. Audit the Entire Spawning Pipeline

Trace the complete lifecycle of a moving traffic vehicle:

1. Calculate the local traffic demand.
2. Determine the moving-traffic target.
3. Count the moving vehicles that are actually relevant to the player.
4. Decide whether additional vehicles are needed.
5. Find candidate spawn locations.
6. Reject candidates that are visible, unsafe, outside the active simulation area, or too close to existing vehicles.
7. Create a vehicle at a valid position on the road network.
8. Find a destination and construct a route.
9. Validate the route against road geometry, curbs, buildings, map levels, and traffic direction.
10. Apply the asynchronous route job result.
11. Start the vehicle moving at a safe initial speed.
12. Continue its journey through the active simulation area.
13. Retire the vehicle only when its lifecycle permits removal.

Identify every point where an otherwise valid spawn can fail.

Investigate these existing constraints in particular:
- `NPC_TRANSIT_SPAWN_MIN_DISTANCE_M`
- `NPC_TRANSIT_SPAWN_MAX_DISTANCE_M`
- `NPC_TRANSIT_SPAWN_NODE_TRIES`
- `NPC_TRANSIT_SPAWN_CLEARANCE_M`
- `NPC_TRANSIT_TRIP_MIN_DISTANCE_M`
- `NPC_TRANSIT_TRIP_MAX_DISTANCE_M`
- `NPC_TRANSIT_SPAWNS_PER_TICK`
- `NPC_TRIP_START_TICK_BUDGET_S`
- `NPC_ROUTE_JOB_SLICE_S`
- `NPC_MAX_ROUTE_JOBS`
- `NPC_POPULATION_SPAWN_LIMIT_PER_TICK`
- The current SpawnMemory failure and retry policy.

Do not assume these values are wrong simply because they are restrictive. Determine which constraints actually cause failures on realistic, dense OSM road networks.

Inspect how route jobs compete with existing trip starts, recovery jobs, continuation jobs, and other population-management work.

Check whether route jobs are rejected, discarded, cancelled, starved, or left waiting long enough that the moving-traffic population cannot reach its target.

Distinguish between:
- No suitable road node.
- No valid initial vehicle position.
- Insufficient spawn clearance.
- No reachable destination.
- Route generation failure.
- Route validation failure.
- Vehicle footprint validation failure.
- Unsafe initial speed or insufficient braking distance.
- Viewport or active-area rejection.
- Destination conflicts.
- Full population or unavailable replacement vehicles.
- Route-job queue saturation or excessive job latency.
- A successfully spawned vehicle that stops too soon or otherwise fails to provide useful moving traffic.

Report the actual root causes using source-code references and measurements. Do not stop after adding diagnostic counters.

## 3. Add Reliable Spawn Diagnostics

Extend the existing diagnostics instead of introducing an unrelated logging subsystem.

Track, at minimum:
- Current moving-traffic target.
- Actual moving vehicles inside the relevant simulation area.
- Actual moving vehicles on road-network routes.
- Number of spawn jobs queued, running, completed, failed, and discarded.
- Number of candidate spawn positions examined.
- Number of valid vehicle placements.
- Number of valid routes produced.
- Number of vehicles successfully activated.
- Number of vehicles that remain moving after activation.
- Route-job queue depth and job latency.
- Time spent on spawn search, route planning, and route validation.
- Failure and discard counts grouped by reason.
- Number of retries and successes associated with previously unsuccessful spawn locations.

Use bounded counters, rolling statistics, or another suitable existing diagnostic mechanism. Do not accumulate an unlimited history of every spawn attempt.

Expose useful aggregate values through the existing population diagnostics and F12 diagnostic JSON.

Diagnostics must make it possible to distinguish a shortage of spawn candidates from a shortage of route-planning capacity.

Avoid logging every failed candidate individually during normal gameplay.

## 4. Correct the Spawn and Retry Architecture

Implement a robust solution based on the audit findings.

Requirements:

- Traffic demand must not be silently lost when an individual spawn attempt fails.
- Failed candidates must not permanently block future attempts when conditions change.
- Repeatedly impossible candidates must not consume all available work.
- Known-good spawn locations should be reused when appropriate, but previously unsuccessful locations must remain eligible for recovery when the road graph, map coverage, or surrounding traffic changes.
- A failed candidate must not cause an entire population update to be abandoned unnecessarily.
- Route jobs must make forward progress without starving existing vehicles, passenger trips, or recovery work.
- The system must maintain a clear distinction between requested traffic, pending spawn jobs, successfully spawned vehicles, and vehicles currently moving.
- Spawn-job completion must recheck safety, vehicle clearance, target counts, and the current world state before committing the vehicle.
- A failed or discarded job must release all reservations and temporary state.
- No vehicle may be activated without a valid route and a safe starting position.
- Do not weaken building, curb, road-boundary, or collision checks simply to increase the success rate.

Use bounded retries and backoff where necessary, but ensure the retry strategy cannot leave the simulation permanently below its moving-traffic target.

Consider a persistent, demand-driven queue of spawn work that retries while the actual moving-traffic population remains below target.

Do not simply increase the number of attempts, route-job limits, or per-frame time budgets without measuring the effect.

## 5. Improve Spawn-Location Selection

Review whether the current candidate search provides enough valid road entry points in dense urban areas.

The spawn system should:
- Prefer real drivable roads with valid connectivity in the existing route graph.
- Prefer useful road corridors near the player's active simulation area.
- Use the player's current road and heading to improve traffic relevance where appropriate.
- Support both directions of traffic on two-way roads.
- Respect one-way roads and map levels.
- Avoid spawning vehicles in the visible viewport.
- Avoid placing vehicles too close to the player or other vehicles.
- Avoid creating vehicles on disconnected service roads or across bridges with incompatible map levels.
- Continue working with streamed map data and newly available roads.
- Avoid repeatedly sampling the same invalid positions.
- Avoid scanning the entire route graph unnecessarily on every spawn attempt.

Inspect the current `through_road_first`, `prioritize_transit_spawn_nodes`, and `transit_spawn_focus` implementations before changing them.

Do not replace the existing indexed road search with a global linear scan.

If useful, maintain a reusable collection of validated road entry candidates, invalidating or updating it when the relevant road graph changes.

## 6. Create Genuine Through Traffic

The current `_short_transit_trip_steps()` often chooses a roadside stopping destination only 80–200 metres from the vehicle's starting point.

Investigate whether this causes newly spawned traffic to stop too quickly and whether this contributes to the inability to sustain congestion.

Moving through-traffic vehicles should travel on valid road-network routes that pass through the player's active simulation area.

Requirements:
- The route must be long enough for the vehicle to approach, pass the player, and continue beyond the immediate encounter area.
- Where practical, use connected road-network destinations beyond the player's current position rather than short roadside parking destinations.
- Preserve valid road directions and the existing route-validation requirements.
- Do not spawn a vehicle already inside the visible viewport.
- Do not spawn a vehicle directly into a queue of other vehicles.
- Vehicles must obey traffic rules and react to traffic lights, signs, and other vehicles through the existing traffic systems.
- Vehicles must not be teleported forward merely to simulate traffic flow.
- Vehicles must not be removed while still needed for a legitimate active trip.
- Existing resident, driver, passenger, taxi, bus, and vehicle lifecycle rules must remain intact.

A vehicle that reaches its actual destination may stop or park normally. Through traffic should not routinely terminate after only a very short trip merely because that makes route generation easier.

The solution must remain compatible with the existing `TrafficWorld`, `SpatialWayGrid`, and authoritative Python simulation.

## 7. Make Afternoon Rush Hours Materialize in Gameplay

Preserve the existing demand model in `population.py`, including its measured LAM traffic profiles, weekday and weekend differences, monthly adjustments, and urban/rural behavior.

Do not replace the measured curves with an arbitrary fixed multiplier.

The existing weekday curve places the main afternoon peak around 15:00–17:00.

The target must translate into actual moving vehicles rather than merely increasing a displayed target value.

For a dense urban centre on a normal weekday afternoon:
- The target should reflect the existing demand model.
- The actual number of moving vehicles should converge toward that target when the loaded road network can support it.
- A transient shortage caused by failed spawns must trigger further bounded attempts.
- Parked vehicles must not count as moving traffic.
- Crashed vehicles must not count as moving traffic.
- Vehicles outside the relevant simulation area must not count toward the locally available moving-traffic population.
- Pending jobs must not be mistaken for successfully spawned vehicles.
- Replacing an idle parked vehicle with a moving vehicle must update the counts consistently.
- The system must not create unlimited vehicles when the target cannot be achieved.

Do not hardcode a universal target of 20 moving cars or any other arbitrary number. Preserve the existing city-density and road-demand scaling.

The desired outcome is a visibly busier afternoon in dense urban areas than at night or on quiet rural roads, while maintaining the existing Finnish traffic-demand model.

A weekday at 16:00 in a dense urban centre is the primary acceptance scenario.

Also verify:
- Weekday morning rush hour.
- Weekday late evening.
- A quiet rural road at night.
- A main road through a sparsely populated area.
- Weekend traffic and existing Friday/Saturday nightlife behavior.

## 8. Keep Performance Under Control

The project has previously suffered from expensive route planning and traffic-related frame spikes.

Preserve the incremental route-job architecture and bounded per-frame processing.

Requirements:
- No synchronous, unbounded route-planning loop in the normal frame update.
- No unbounded retry loop.
- No global all-to-all collision or spawn-clearance checks.
- Reuse existing spatial indexes.
- Avoid repeatedly rebuilding the route graph or rescanning all roads.
- Avoid unnecessary object allocations in hot loops.
- Keep spawn and route validation off unrelated rendering code.
- Ensure that the spawn queue continues to make progress under load.
- Measure route-job latency and population convergence under a dense traffic scenario.
- Do not optimize away safety validation to improve the numbers.

If the current per-frame job budget is the bottleneck, improve scheduling and work distribution before considering a larger budget.

## 9. Automated Tests

Extend the existing test suite.

### Spawn reliability

Test:
- Spawn success on a simple connected urban road network.
- Spawn success on a dense multi-intersection road network.
- Spawn behavior when some candidate nodes are invalid.
- Retry after an initial route-generation failure.
- Recovery when a previously unavailable road becomes available.
- Correct behavior when the route-job queue is busy.
- Correct handling of full population and safe parked-vehicle replacement.
- Correct release of reservations after failed jobs.
- No duplicate vehicle activation when a job completes more than once.
- No unsafe spawn positions or routes.

### Traffic population convergence

Test:
- Moving-traffic target below actual count.
- Moving-traffic target above actual count.
- Pending jobs do not count as active vehicles.
- Parked and crashed vehicles do not satisfy the moving-traffic target.
- Vehicles outside the active simulation area do not satisfy the local target.
- Spawn failures trigger retries without creating an unbounded queue.
- The target converges when sufficient valid road and route capacity exists.
- The target remains unmet, with an explicit diagnostic explanation, when the network genuinely cannot support it.

### Rush-hour acceptance tests

Use deterministic clocks, random seeds, and synthetic road networks.

Test at least:
- Wednesday 07:30.
- Wednesday 16:00.
- Wednesday 23:30.
- Thursday 01:00 in October.
- Friday evening and the existing nightlife period.

Verify both the calculated traffic target and the actual moving-vehicle count after a defined simulation period.

For the dense urban afternoon test, use the existing default city-scale population settings and enough valid roads and destinations to support the expected traffic.

Do not assert that every possible map must reach a fixed count regardless of its road capacity.

### Performance tests

Measure:
- Number of route jobs completed per simulated minute.
- Spawn attempts and successful activations per simulated minute.
- Time required to reach the moving-traffic target.
- Route-job latency and queue depth.
- CPU time per population update.
- Performance with 20, 40, and 60 moving vehicles where the test environment supports those counts.

Compare results against the existing baseline and identify any regressions.

## 10. Implementation Rules

- Python remains the authoritative simulation language.
- Godot remains responsible for rendering.
- Do not add CARLA, SUMO, Box2D, or another external simulation engine as a runtime dependency.
- Do not create a second, competing NPC movement system.
- Do not remove existing vehicle types or passenger lifecycle behavior.
- Do not introduce arbitrary global NPC limits.
- Do not alter unrelated gameplay systems.
- Do not weaken traffic laws or collision checks to force a higher spawn count.
- Preserve existing configuration compatibility.
- Follow the repository's existing coding and testing conventions.
- Reuse existing diagnostics and performance infrastructure where practical.

## 11. Deliverables

Implement the necessary fixes, not just an audit report.

Provide:
1. The identified root cause or causes, supported by the current implementation and measurements.
2. The changes to spawn selection, retries, route jobs, or traffic lifecycle that address those causes.
3. The diagnostic counters and failure reasons added.
4. Automated tests demonstrating successful population convergence.
5. Results from the weekday 16:00 dense urban acceptance scenario.
6. Before-and-after spawn success rates and route-job latency.
7. Before-and-after CPU measurements.
8. Any remaining cases in which the target cannot be achieved because the road network or available routes are insufficient.

The final implementation should produce sustained, genuinely moving traffic during Finnish afternoon rush hours without compromising safe spawning, authoritative simulation, or game performance.