# Simulation performance audit, 2026-11-03

Source-code review and measurements only. No production code or game behavior was changed.

## Executive summary

Two current-code Oulu rush-hour runs varied substantially: mean tick time 9.89–13.61 ms, p95 18.16–28.30 ms, p99 23.85–40.17 ms and maximum 32.28–79.21 ms. The first run had 2.17% over the 33.33 ms budget and 5/1,800 ticks (0.28%) over 50 ms, reconstructed from its sorted top-eight list; the instrumented repeat had 0% above 33.33 or 50 ms. Both saw 0% over 100 ms. Most sustained work is in `NPCManager.update`; the worst spikes combine that phase with state construction and pedestrian work. This is an in-process, back-to-back benchmark, not a connected-client real-time run.

Natural Oulu scenarios now cover approximately 10, 20, 40 and 60 vehicles without changing traffic demand or NPC counts. The 10 and 20 suburb scenarios share a map and clock; the 40–60 rush-hour scenario uses a larger city-center map. They provide useful workload bands, not a controlled scaling curve or cost-per-vehicle estimate. At the nominal 60 point the observed population was 55–56.

The largest confirmed code-level cost is per-NPC update and spatial-grid maintenance, with observed `sim.npc` mean 5.58–7.71 ms and max 19.77–50.61 ms across the runs. Pedestrian update averaged 1.74–2.54 ms (max 18.77–33.50 ms). State construction/broadcast averaged 1.78–2.33 ms (max 8.65–14.24 ms); separate JSON encoding averaged 0.68 ms (max 3.28 ms in the first run). The worst tick had no GC pause. Routing is already sliced across ticks, but route jobs remain Python generator work on the simulation thread and the route job scheduler reached 13.34–16.80 ms in one frame despite a nominal 1 ms budget.

## Method and measurement quality

The reusable harness is [bench_sim.py](rrt-019-sim-audit-data/bench_sim.py). It runs the real `SimulationServer` and simulation code at a real OSM location, advances `server.tick(1/30)` back-to-back, times the whole tick with `perf_counter` and the tick thread with `thread_time`, wraps major server/simulation sections, records GC callbacks, RSS, tracked GC objects and entity counts, then separately encodes one captured state message. Its optional `--population-bands` captures vehicle counts after each timed tick, so sampling does not inflate tick time; report bands use `[target-5,target+5)`. Timers are diagnostic monkeypatches; this is more representative than a microbenchmark, but the wrappers and Python-version/platform differences still add noise.

The primary run used Oulu (427960, 7210718), rush-hour clock 2026-10-23 17:00, seed 1, 30 s simulated warm-up and 60 s / 1,800 measured ticks. The harness used Python 3.10.12 on this host. Additional 10/20 scenarios used Oulu suburb coordinates at noon, one simulated tick warm-up and 60 s / 1,800 ticks; the 40/60 bands are from the primary rush-hour run. The prior checked-in runs were Python 3.12.3 and had materially different populations and timings, so they are context only, not a before/after comparison. The run script and raw JSON captures are in [the audit data directory](rrt-021-simulation-performance-audit-data/README.md). No production source or gameplay behavior was changed.

The harness reports reliable wall-time quantiles for the sampled run, and per-thread CPU time and phase totals. It does not persist every tick or report p50 of phase timings, per-tick route counts, process-wide CPU utilization, bytes allocated, lock wait, or client/network delivery latency. It records RSS only at measurement start/end and `gc.get_objects()` counts, which are live tracked-object counts, not total allocations. `maxrss` and `VmRSS` are different OS readings and should not be treated as allocation metrics. This report distinguishes these gaps from measured facts.

## Architecture and execution flow

`SimulationServer.run_forever` sets a fixed interval from `tick_rate` (default 30 Hz), calls `tick(interval)`, sleeps to the next deadline, and resets `next_tick` to the current time after an overrun rather than running catch-up bursts ([server/__init__.py:1529](../../src/theroadragetrip/server/__init__.py#L1529)). Each tick applies queued inputs, advances game time/weather and server services, then calls `advance_simulation`, builds/sends one state snapshot, and increments server time ([server/__init__.py:932](../../src/theroadragetrip/server/__init__.py#L932)). Python remains authoritative. Godot rendering is outside this audit and the benchmark.

Inside `advance_simulation`, the main measured phases include player physics/collisions, train/tram/taxi work, NPC update, traffic clock, and pedestrian update ([simulation.py:249](../../src/theroadragetrip/simulation.py#L249), [simulation.py:562](../../src/theroadragetrip/simulation.py#L562), [simulation.py:693](../../src/theroadragetrip/simulation.py#L693), [simulation.py:850](../../src/theroadragetrip/simulation.py#L850)). Server state is rebuilt every tick ([server/__init__.py:1502](../../src/theroadragetrip/server/__init__.py#L1502)). Transport queues the newest state asynchronously and replaces stale queued snapshots ([transport.py:46](../../src/theroadragetrip/transport.py#L46), [transport.py:130](../../src/theroadragetrip/transport.py#L130)); the benchmark had no connected game client.

## Measured baseline

| Metric | Current Oulu rush-hour run |
|---|---:|
| Ticks | 1,800 |
| Mean / median | 9.89–13.61 / 8.43–10.67 ms |
| P95 / P99 / max | 18.16–28.30 / 23.85–40.17 / 32.28–79.21 ms |
| >16.67 ms | 7.33–24.78% |
| >33.33 ms | 0–2.17% |
| >50 ms | 0–0.28% (5 ticks in first run; 0 in repeat) |
| >100 ms | 0% in both runs (maximum was 79.21 ms) |
| Mean thread CPU per tick | 9.89–13.62 ms |
| Vehicles total (mean; sampled range) | 47.7–50.2; 35–61 |
| Moving vehicles (mean) | 23.2–24.7 |
| Pedestrians (mean) | 72.0–72.4 |
| Residents (mean) | 370–387 |
| Map | 8,687 ways; 2,586 buildings; 1,699 parking spaces |
| RSS | 416.2 to 426.7 MiB |
| GC-tracked objects | 972,941 to 982,243 |
| GC pauses | 2 generation-0 collections; 4.14 ms total; no gen-1/gen-2 |
| State JSON encoding (outside tick) | mean 0.68 ms; max 3.28 ms; 25.5 KiB mean |

At 30 ticks/s, the observed 9.89–13.62 ms CPU per tick corresponds to about 30–41% of one core if each run's workload remains stable. The benchmark itself was CPU-bound at roughly one core because it did not sleep between ticks. This is not machine-wide CPU utilization and excludes other processes/clients. In the threshold run, RSS grew 10.6 MiB and tracked live objects grew about 11.4k during the minute; neither number reveals temporary allocation volume or proves a leak.

The temporary threshold rerun also measured 0% over 16.67/33.33/50/100 ms, mean 9.89 ms, median 8.43 ms, p95 18.16 ms, p99 23.85 ms, max 32.28 ms. It averaged 47.7 vehicles (35 first sampled, 61 last sampled), 24.7 moving vehicles and 72.4 pedestrians. The first run's top-eight list contains five ticks over 50 ms and its sixth-worst tick is 49.37 ms, so the exact first-run >50 ms fraction is 5/1,800. The first run measured higher times while a slightly larger average vehicle population was present; these two observations are not enough to infer linear scaling.

The stored older rush-hour runs (Python 3.12.3, typically 1–2 NPC vehicles) reported mean wall 3.3–4.4 ms, p95 5.0–11.4 ms, p99 28.3–36.1 ms, max 68.6–217.6 ms, and 0.72–1.08% over 33.33 ms. They also showed occasional 50–200 ms pedestrian spawn spikes. These runs confirm tail variability but are not directly comparable to the current Python 3.10 / 50 vehicle run.

## Subsystem findings

### NPC movement, routing, and collision

`NPCManager.update` rebuilds its vehicle spatial grid before and after movement, creates active/pose structures, updates every relevant vehicle and trailer, performs swept collision checks, advances route jobs, and periodically runs population work ([npc.py:6809](../../src/theroadragetrip/npc.py#L6809)). The measured parent phase `sim.npc` averaged 5.58–7.71 ms and peaked at 19.77–50.61 ms across runs. That is the strongest measured candidate for disproportionate CPU use at the observed population. The benchmark does not split NPC movement, grid rebuild, collision, routing, and population work, so assigning the 50.61 ms to any one of those sub-operations would be speculation.

Vehicle-to-vehicle and vehicle-to-player collision is not a global all-pairs loop. The manager spatial grid bounds candidates, then `_check_vehicle_collision` applies oriented-box and, when needed, swept interpolation checks ([npc.py:4713](../../src/theroadragetrip/npc.py#L4713), [npc.py:5023](../../src/theroadragetrip/npc.py#L5023)). Rebuilding the grid is O(N) twice per update; narrow-phase work is O(N·K), where K is local candidate count, and can approach O(N²) in a dense pile-up. Current measured player collision phase `sim.collisions` was only 0.088 ms mean / 0.88 ms max. NPC-internal pair collision cost is inside `sim.npc` and is not separately measured.

Building collision queries use a persistent 100 m spatial grid, incrementally adding newly appended buildings; exact polygon/edge checks are applied only to nearby candidates ([taxi.py:546](../../src/theroadragetrip/taxi.py#L546), [taxi.py:668](../../src/theroadragetrip/taxi.py#L668)). Its sub-cost is included in `sim.collisions`; no isolated building-collision measurement is present. Existing spatial indexes mean global building/road scans are not the default per-tick collision path.

Routing uses a spatial node grid, weak-component precheck, multi-source A* with heap/dictionaries, and resumable generators ([traffic_world.py:280](../../src/theroadragetrip/traffic_world.py#L280), [traffic_world.py:584](../../src/theroadragetrip/traffic_world.py#L584)). There is no evident general route-result cache in this path. NPC route jobs are round-robin slices with 0.5 ms per-job slice and a nominal 1 ms total budget ([npc.py:297](../../src/theroadragetrip/npc.py#L297), [npc.py:5595](../../src/theroadragetrip/npc.py#L5595)). The run queued 93 jobs, completed 50, failed 32, discarded 6, and recorded a 16.80 ms maximum route-job scheduler frame. This maximum is a recorded diagnostic, not isolated route CPU: it can include timer overhead and other work in the scheduler, and the actual tick maximum was 79.21 ms. The existing budget is soft because each generator step is non-preemptible Python work and the scheduler ensures progress.

`plan_route` candidates can perform repeated graph traversal for distinct start/destination requests. Some trip selection explicitly breadth-first enumerates candidate destinations, then validates a route; caller comments document that one synchronous route step may exceed an outer budget ([npc.py:2260](../../src/theroadragetrip/npc.py#L2260), [npc.py:2300](../../src/theroadragetrip/npc.py#L2300)). No call count per tick is currently collected, so duplicate route requests and cache hit rate cannot be quantified. In this run, `route_job_stats` indicate queued/completed work over the full minute, while `ped_stage.route_nearest` and `ped_stage.route_search` relate only to pedestrian staging. Route correctness must remain tied to graph revisions and current validation/occupancy.

### Pedestrian and animal simulation

Pedestrian update averages 1.74–2.54 ms, max 18.77–33.50 ms. Within it, walking movement averages 1.10–1.47 ms and peaks at 12.23–18.92 ms; spawning averages 0.17–0.43 ms and peaks at 11.64–16.08 ms; LOD averages 0.25–0.30 ms. Spawn and population processing run every two seconds, and a 4 ms budget applies only when viewport bounds exist ([pedestrian.py:434](../../src/theroadragetrip/pedestrian.py#L434), [pedestrian.py:2722](../../src/theroadragetrip/pedestrian.py#L2722), [pedestrian.py:2855](../../src/theroadragetrip/pedestrian.py#L2855)). The budget cannot interrupt one placement/path validation call; retries may also carry across population checks. The prior 3.12 runs had a much worse spawn tail (up to 191 ms), showing that the tail is workload/environment-sensitive and merits reproduction.

Pedestrian movement traverses the live pedestrian list each tick, with LOD deciding which agents run expensive behavior; local vehicle interaction uses a per-tick lookup grid in NPC code ([pedestrian.py:2890](../../src/theroadragetrip/pedestrian.py#L2890), [npc.py:6714](../../src/theroadragetrip/npc.py#L6714)). This is O(P) baseline work plus local-neighbor interaction. Animal simulation is not a separately timed server phase in the harness; it should not be attributed as a current tick bottleneck without finer instrumentation.

### Spawn system

In the measured minute, vehicle diagnostics recorded 43 trip-start attempts, 35 successful starts, 4 route-generation failures, and 13 vehicles waiting for trips at the end. This is cumulative diagnostics and does not expose per-attempt time or the exact spawn search count. Population work runs on a slower population tick and is included in `sim.npc`; pedestrian spawn timing is separately available. The 35/43 figure is a start success ratio, not an overall spawn success rate (some attempts are pending/retried and the diagnostic categories do not form a complete accounting identity).

### World/spatial processing and map growth

The measured run held a fixed 8,687-way / 2,586-building Oulu map and did not exercise a drive into newly streamed map tiles. Its `srv.map_streamer` mean was 0.045 ms / max 0.58 ms, so map streaming was not a measured hotspot in this setup. This does not cover map-sync rebuilds, world growth, cold tile loading, or chunk resend stalls. The separate [map-loading-02.md](map-loading-02.md) audit documents those as a different workload: whole-world sync, GIL contention, and unbudgeted chunk encoding produced hundreds-of-milliseconds stalls there. Those results are relevant risks during driving into new map, but should not be blended into this stationary rush-hour baseline.

### Communication and state generation

`srv.broadcast_state` averaged 1.78–2.33 ms and peaked at 8.65–14.24 ms. `protocol.encode` ran after the measured tick in this harness and averaged 0.68 ms (max 3.28 ms); the state averaged 25.5 KiB in the first run. Therefore state construction is a meaningful secondary CPU cost and can contribute to a long tick, while JSON encoding was separate in this particular measurement. The benchmark serializes one message and does not exercise per-client queue pressure, socket writes, JSON encoding under concurrent client count, or Godot decode cost. The queue is asynchronous and replaces obsolete states, but client delivery latency was not measured.

### Runtime, memory, and concurrency

Only two generation-0 collections ran, totaling 4.14 ms; there were no generation-1 or generation-2 collections. No evidence points to GC as the cause of the measured long ticks. The rising live object count is not a measure of allocation rate. The harness does not run `tracemalloc` or an allocation profiler, so temporary object churn and allocation hotspots remain unmeasured.

CPU-heavy simulation and route search are Python and therefore constrained by the GIL for Python threads. The repo already uses threads for I/O/background services and a process pool for selected map/chunk builds ([world_cache.py:465](../../src/theroadragetrip/world_cache.py#L465), [server/__init__.py:726](../../src/theroadragetrip/server/__init__.py#L726)); no route worker pool exists. Moving route search to threads is unlikely to give CPU parallelism. A process worker would need a stable immutable graph snapshot, request/result transfer, cancellation on route-graph revision changes, and main-thread validation/commit; serialization and stale-work costs are unmeasured. Precomputed route pools are similarly unproven because vehicle starts, goals, occupancy and graph revision vary.

The main tick is synchronous; expensive single calls block all simulation phases. Locks are used for command/client state, but the harness does not record lock wait and has no client connection. In map-growth / cold-loading workloads, background Python activity can also contend for the GIL; see the independent map-loading report.

## Scaling analysis

Natural population-band measurements (total vehicles include parked; “moving” is `abs(speed) > 0.5`) are:

| Nominal band | Observed total | Ticks | Mean moving | Tick mean / p95 / p99 / max (ms) | >16.67 ms | Mean NPC / pedestrian / collision / broadcast phase (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 9–14 (mean 10.87) | 1,079 | 4.95 | 2.15 / 3.16 / 8.77 / 11.31 | 0% | 0.98 / 0.08 / 0.09 / 0.59 |
| 20 | 21–24 (mean 23.12) | 1,559 | 7.88 | 5.70 / 10.23 / 15.34 / 21.21 | 0.64% | 3.44 / 0.39 / 0.06 / 1.16 |
| 40 | 40–44 (mean 42.06) | 633 | 23.06 | 9.83 / 19.78 / 24.50 / 59.92 | 9.95% | 4.81 / 2.48 / 0.07 / 1.75 |
| 60 | 55–56 (mean 55.16) | 404 | 18.88 | 8.80 / 15.69 / 18.17 / 22.15 | 2.97% | 4.76 / 1.65 / 0.06 / 1.69 |

No band had a tick over 100 ms. The 40 band had one tick over 50 ms (0.158%); it reached 59.92 ms, of which pedestrian spawning accounted for 40.28 ms. These natural scenarios differ in location, time and map size: the 10/20 runs share a 4,503-way suburban map, while 40/60 come from an 8,687-way center map. Population varies naturally within each band, so the table is workload evidence, not a controlled regression slope. The 10/20 suburb runs each used one warm-up tick; rush-hour used 30 seconds.

Code complexity predicts: vehicle-grid rebuild O(N) twice/tick; per-driver movement approximately O(A) where A is vehicles inside active bounds, plus local O(A·K) collision/avoidance candidates; pedestrian loops O(P), plus route/placement and local interactions; state assembly approximately O(E) for entities included in the transmitted view, followed by JSON encoding O(message bytes). These are structural estimates, not measured regression curves. A dense collision pile-up can inflate K toward N. Current use of spatial grids avoids an unconditional all-pairs collision pass.

The table completes a natural-scenario matrix while preserving live population logic. It cannot establish a universal slope: fixed-location replay at pinned populations, or authentic deterministic state snapshots, would be needed to separate entity-count effects from map, clock and activity differences. Per-tick counts are now stratifiable, but exact route calls/expansions and NPC update subphases still need instrumentation.

## Long-tick root causes (evidence ranking)

1. **NPC update work — measured, highest average contribution.** `NPCManager.update`, [npc.py:6809](../../src/theroadragetrip/npc.py#L6809): 7.71 ms mean, 50.61 ms max. Runs every tick for relevant active vehicles, with O(N) grid maintenance and local movement/collision/route work. Its tail alone can exceed 33 ms. Exact culprit among its subphases is not yet split. Optimize only after profiling a 40–60 vehicle long tick and correlating it with vehicle count, active candidates, route jobs, and collision candidates. Correctness risks: movement cadence, swept collision outcomes, traffic priority, fairness, and map-layer handling.

2. **State construction — measured secondary/tail contributor.** `SimulationServer._broadcast_state`, [server/__init__.py:1502](../../src/theroadragetrip/server/__init__.py#L1502): 2.33 ms mean, 14.24 ms max. It runs every tick and scales with transmitted dynamic state plus ancillary lookups. It co-occurred at 14.24 ms in the worst tick. JSON encoding is additional 0.68 ms mean outside the tick. A message-shape or frequency change risks client interpolation/events and should be measured end-to-end.

3. **Pedestrian update — measured.** `PedestrianManager.update`, [pedestrian.py:2722](../../src/theroadragetrip/pedestrian.py#L2722): 2.54 ms mean, 33.50 ms max in the initial rush-hour run. In the new 40–60 band run, a 59.92 ms tick contained 44.09 ms in pedestrian update, including 40.28 ms in `ped_stage.spawn`; the corresponding band p95 is 19.78 ms. Population/spawn runs every two seconds, with a soft deadline, so an individual placement can overrun the budget. Risks include pedestrian movement consistency, road-crossing and traffic-light decisions, and population quality.

4. **Route jobs — measured scheduler maximum, not proven root of whole-tick maximum.** `_advance_route_jobs`, [npc.py:5595](../../src/theroadragetrip/npc.py#L5595): 93 queued and 50 ready jobs in one minute, diagnostic max 16.80 ms/frame versus 1 ms nominal budget. It is a likely contributor to occasional NPC spikes, but per-job CPU and per-tick calls are missing. Risks of caching/parallelism include stale graph results, route correctness, curb/building validation and delayed trip starts.

5. **Map growth / cold loads — known separate workload.** Historical measurements in [map-loading-02.md](map-loading-02.md) establish GC, GIL and unbudgeted work during tile growth; they are not seen in this stationary run. Risks include state gaps and route/map revision consistency.

## Prioritized roadmap

| Priority | Work | Expected impact | Complexity / correctness risk | Independent? | Verification |
|---|---|---|---|---|---|
| 0 | Split NPC update into grid, movement, collision, route and population sections with sampled candidate counts; capture per-tick route-job counters. Natural population bands are now captured by the audit harness. | No runtime gain; makes causes measurable. | Low / none to gameplay. | Yes. | Same fixed scenario, overhead measured against uninstrumented harness; verify counters reconcile to total NPC phase. |
| 1 | Profile and optimize the measured NPC hot path, starting with grid rebuild and per-vehicle work at 40–60 natural vehicles. | Potentially high; this is 7.71 ms mean and 50.61 ms max. | Medium / high if changing movement, collision, update cadence or ordering. | Mostly. | Identical deterministic inputs; compare p95/p99/max and replay positions, routes, signal decisions, collisions and traffic demand. |
| 2 | Reproduce route-job over-budget frames; determine cost per expanded node, per candidate and repeated request before considering route-result reuse. | Medium if route search explains some of NPC tail; presently unproven. | Medium–high / stale route and path-validity risk. | Yes, after diagnostic step. | Count expansions/requests/hits, compare route geometry and graph revision, spawn success and job latency. |
| 3 | Reduce pedestrian movement/spawn cost only where profiling identifies repeated work; retain full population and traffic rules. | Medium; 2.54 ms mean, but long tail merits attention. | Medium / high to pedestrian behavior and crossings. | Yes. | Compare movement traces, crossings/light compliance, pedestrian/animal counts, spawn success and p99. |
| 4 | Measure state-build versus encode, then consider avoiding repeated derived conversions only if measured. | Low-to-medium mean, possible tail reduction. | Low–medium / client protocol and event delivery risk. | Yes. | Same state semantics; message byte size, encode/build p95, client decode and state gap. |
| 5 | Keep map-growth audit separate; profile cold/warm tile-load paths with current code and connected client. | Potentially high during map growth, no impact on stationary baseline. | Medium / world revision and delivery risks. | Yes. | Existing map-jitter replay, GC/GIL, tick distribution and state-gap checks. |

No benefit is established for background route workers or precomputed route pools. Threads would share the GIL; processes add snapshot and IPC cost and need stale-result safeguards. Do not pursue either until route profiling shows enough independent CPU work to amortize those costs.

## Regression and verification plan

Before each optimization, preserve a fixed seeded replay and report at least 1,800 measured ticks after warm-up. Record mean, median, p95, p99, max, >16.67/>33.33/>50/>100 ms rates, tick-thread CPU, process CPU, RSS, allocation sampling, GC pause distribution, map/entity counts, and separate simulation/state-build/encode/network timings. Keep the environment/Python version and host load stable, and include both a stationary dense-city run and a representative drive with map growth.

Repeat the natural 10/20/40/60 scenarios on a stable host for confidence intervals. Treat them as location-specific until same-map authentic replays can hold population bands fixed. Do not manufacture a win by reducing population, demand, update cadence or collision clearance.

For behavior comparisons, replay the same inputs and seed on the same map/time/weather and compare per-entity movement trajectories within a declared tolerance, routes and destinations, signal/stop/yield decisions, collision event pairs and outcomes, spawn attempts/success/failure reasons, moving/parked population and long-run stability. Keep Finnish traffic-law acceptance scenarios in scope for any routing, traffic, pedestrian or collision optimization. Run long enough to expose queue growth, memory growth, route-job starvation and periodic maintenance spikes. Validate both simulation results and client state freshness so lower tick CPU is not purchased with stale presentation.

## What was not established

- The first run's >50 ms count is inferred from the sorted worst-eight sample rather than raw tick storage; five exceed 50 ms and the sixth-worst is below it. Both runs had 0% >100 ms by their observed maxima.
- A controlled same-map 10/20/40/60 scaling curve, exact route calls per tick, duplicate route rate/cache effectiveness, per-subsystem collision cost, total allocation bytes/rate, lock wait, all-client network cost, and connected-client decode/latency were not measured. The measured population bands are natural scenarios and should not be generalized as a per-vehicle cost curve.
- The current run is stationary after warm-up and excludes map growth, cold cache, real client rendering and network load.
- No optimizations were implemented or performance claims made for proposed work.
