# bin-loader-v12: asynchronous traffic route planning

## Root cause

NPC trips could only start if a complete route plan and validation finished inside the population tick's 8 ms budget.

On the real Oulu road graph (48,130 nodes, 96,688 directed edges), `TrafficWorld.plan_route` alone measured **p50 3.0 ms, p95 856 ms, p99 961 ms, worst 1,063 ms** over 400 NPC- and navigation-shaped requests. The cost had three sources:

- It built a set of every node on every call.
- Its multi-target heuristic ran a `min` over up to 64 targets at every expansion.
- An unreachable target was searched four times in full (8/16/32/64 candidates).

Route validation (curb and building footprint samples) never checked a deadline, and transit spawns called the planner with no deadline at all. Result: 0 of 38 trip starts succeeded, only 1–2 NPCs moved, and the `npc` section still spiked to 176 ms.

## Architecture

**Route planning is a job.** It is built from resumable generator "steps" (`RouteSteps`), each of which yields after every unit of work and returns its result:

- `TrafficWorld.plan_route_steps`: A\*, yielding per node expansion.
- `_route_stays_on_road_steps`: yields per segment.
- `_route_crosses_obstacles_steps`: yields per footprint sample.
- `_plan_and_validate_npc_route_steps`: composes the three above.
- `_find_npc_trip_steps`: a trip start for an idle parked car.
- `_transit_spawn_steps` and `_short_transit_trip_steps`: a new moving car.

Every step function is **pure**: it reads the world and returns a plan, never mutating it. `run_route_steps(steps, deadline)` drives a job synchronously. All pre-existing synchronous APIs (`plan_route`, `_plan_and_validate_npc_route`, `start_npc_trip`, `find_and_start_npc_trip`, `_spawn_transit_vehicle`, continuation and recovery) are now "run steps, then apply", with unchanged signatures and results.

**`NPCVehicleManager` job queue.** The population tick no longer plans trip starts or transit spawns. It *queues* them (`_enqueue_route_job`, at most `NPC_MAX_ROUTE_JOBS = 8`, no duplicate job per vehicle).

`_advance_route_jobs` runs every frame from `update()` and works through the queue as follows:

- **Budget:** at most `NPC_ROUTE_JOB_BUDGET_S = 2 ms` per frame.
- **Fair scheduling:** round-robin with a persistent cursor. Each job gets up to `NPC_ROUTE_JOB_SLICE_S = 0.5 ms` before the next one's turn.
- **Guaranteed progress:** at least one step per frame.
- **Why a time slice rather than a step count:** a search step costs microseconds, but one footprint sample can cost milliseconds. A 64-step slice measured about 9 ms per frame. The clock read per step is negligible next to either.

**Generations.** `TrafficWorld.route_graph_revision` is incremented by `_finish_route_graph` on every graph rebuild. A job records it at enqueue; if the graph changes first, the job is closed and counted as `stale`, and never applied.

**Lifecycle (`_finish_route_job`).** A plan is applied only if all of these still hold:

- For a trip job:
  - the vehicle is still in `self.vehicles`
  - it is PARKED, has no driver, is AVAILABLE and has not been abandoned (`driver_departed` is false)
  - the chosen parking space is still free
  - no household member has meanwhile started riding in another car
- For a transit job:
  - the spawn point is still out of view
  - the spawn point is still clear of other vehicles
  - there is still room below the target (or a replaceable parked car)

Otherwise the job is `discarded`. A job whose vehicle is removed while it is running is dropped the next time it would be advanced.

**Failures.** A failed trip keeps the existing exponential retry backoff (`_trip_retry_after_tick`), so there is no tight retry loop.

**Exact planner speed-ups (output unchanged).**

- `allowed = None` when no layer is requested, instead of building a set of every node.
- The heuristic is memoised per search.
- `TrafficWorld._route_component` holds weakly-connected components, built with the graph. The graph is directed, so a shared component is necessary but not sufficient. A search stage whose start and target candidates share no component can only fail, and is skipped.
- The `drivable_ways` filter over all loaded ways is built only for the no-grid fallback that reads it.
- Nearest-node lookup reuses `TrafficWorld`'s own node grid, with an exact ring search.

No threads: the incremental planner already stays within its per-frame budget, and a worker would need the road graph shared across a map-sync rebuild.

The routing pieces (a step generator, `run_route_steps`, a revision number, weak components) are generic and not car-specific, so other vehicle planners can reuse the same pattern.

## Implementation

- `src/theroadragetrip/traffic_world.py`: `RouteSteps`, `run_route_steps`, `plan_route_steps`, `_finish_route_graph` (grid, `route_graph_revision`, `_route_component`), and the exact speed-ups above.
- `src/theroadragetrip/npc.py`: the step versions listed above, `_apply_npc_trip`, `_apply_transit_spawn`, the job queue (`_enqueue_route_job`, `_advance_route_jobs`, `_finish_route_job`, `route_job_stats`), and constants.
- `tests/test_npc_population.py`:
  - Four v12 tests:
    - an incremental and exact route search, with unreachable searches skipped
    - fairness with an endless job queued first, and a trip spread over frames going PARKED → driving
    - stale-revision and removed-vehicle results never applied
    - failure backoff
  - `_finish_route_jobs` helper: four existing tests that expected a synchronous trip start now run the queued jobs before asserting; their assertions are unchanged.
  - The claimed-destinations test now patches `_find_npc_trip_steps`.
  - The nearest-node test now exercises the real grid.

## Performance

**Route planning, controlled replay.** The captured Oulu graph, 400 identical requests. Every route is identical to the original.

| Metric | Before | After |
|---|---:|---:|
| route p50 | 3.0 ms | 0.8 ms |
| route p95 | 855.9 ms | 18.7 ms |
| route p99 | 960.8 ms | 32.8 ms |
| route worst | 1,063.3 ms | 56.6 ms |
| total (400 requests) | 44.6 s | 1.0 s |

After the change, a single route's cost no longer lands in one frame; it is spread across frames by the job scheduler.

**Game.** Oulu, the V10 command (`TZ=UTC-15`, 3000 frames, driving), default target 78.

- **Before:** the last measurement of the 8 ms synchronous code.
- **After:** the final code.
- **Mid-way:** the step-count scheduler that exceeded its budget, shown to document the throughput/smoothness trade-off.

Each run spawns at a random place, and parking near the player varies a lot (total vehicles ranged from 2 to 55 across runs), so NPC counts differ between runs for reasons outside the planner.

| Metric | Before (sync 8 ms) | Mid (64-step slices) | After (2 ms time-sliced) |
|---|---:|---:|---:|
| NPC vehicles (avg) | 4–5 | 52.8 | 41.9 |
| moving NPCs (avg / max) | ~1.3 / 2 | 15.8 / 23 | 8.1 / 13 |
| parked NPCs (avg) | ~3 | 37.0 | 33.7 |
| trip requests / started / failed | 38 / 0 / 38 | 87 / 40 / 15 | 46 / 16 / 4 (+8 stale, 10 discarded) |
| route wait (frames) p50 / p95 / max | – | 193 / 772 / 883 | 509 / 1,544 / 1,891 |
| planner ms per frame (avg / p95 / p99 / max)* | sync, `npc` max 175.7 | 11.8 / 28.1 / 35.6 / 51.9 | 2.39 / 3.25 / 5.49 / 17.65 |
| `npc` section avg / max | 2.2 / 175.7 | 13.7 / 90.9 | 4.8 / 60.9 |
| avg / p95 / p99 frame | 34.6 / 46 / 140 | 46.6 / 66 / 88 | 33.2 / 46 / 65 |
| worst frame | 217 | 821 | 208 (taxi) |
| frames ≥100 / ≥200 / ≥400 | 44 / 1 / 0 | 15 / 2 / 1 | 11 / 1 / 0 |

\*Planner per-frame figures come from a dedicated 1500-frame run with a timing wrapper; the in-run maximum was 20.9 ms.

**Stress, final code.** Targets forced to 15–100, one run each.

| Target | vehicles (avg) | moving avg / max | started / failed | wait p50 / p95 (frames) | planner max ms/frame | worst frame | ≥100 / ≥200 / ≥400 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 15 | 15.0 | 4.9 / 7 | 8 / 3 | 867 / 1,898 | 24.0 | 204 (taxi) | 3 / 1 / 0 |
| 30 | 30.0 | 3.0 / 5 | 16 / 4 | 219 / 1,516 | 12.6 | 304 (taxi) | 5 / 2 / 0 |
| 50 | 8.4 | 1.7 / 4 | 7 / 2 | 266 / 1,308 | 13.2 | 1,334 | 21 / 3 / 1 |
| 75 | 10.6 | 3.0 / 4 | 10 / 2 | 628 / 2,430 | 16.2 | 536 (taxi) | 12 / 2 / 1 |
| 100 | 9.5 | 2.3 / 4 | 5 / 10 | 837 / 2,346 | 22.6 | 325 (taxi) | 7 / 4 / 0 |

The 50/75/100 runs spawned where only 8–11 vehicles could be placed at all, so they do **not** measure scaling with population. Across all runs, no ≥200 ms frame was attributed to `npc`. They were taxi (up to 496 ms) or `map_sync:traffic` (166–218 ms, including up to 29 ms of GC). The 1,334 ms worst frame in the target-50 run was not among the printed spike frames, so it is unattributed.

## Tests

- Full suite: **1156 passed, 5 failed.** These are the established NPC ×2, RWD ×2 and headless boundary failures.
- The household-ownership test remains intermittently flaky with the same message as before V12: 1 of 8 isolated runs failed with V12 and 2 of 8 without; it passed in the full-suite run.
- Kerb-gap and right-turn clearance tests pass.
- `git diff --check`: clean.

## Remaining bottlenecks

**Confirmed:**
- **Taxi:** up to 496 ms, not GC; the largest spike source now.
- **`map_sync:traffic`:** 166–218 ms, the synchronous traffic graph rebuild, which now also builds the weak components.
- **Atomic planner steps (≤ 7.5–9 ms each)**, which cap the planner's worst frame (~18–24 ms):
  - `build_driving_path` for a whole route
  - `_pick_npc_destination_candidates`
  - `_place_one`
  - single footprint checks (`is_vehicle_pose_valid`, up to about 4 ms)
- **Per-vehicle simulation cost of moving NPCs** (decisions, footprint checks, collisions): the `npc` section averages 4.8 ms at about 8 moving, and 13.7 ms at about 16 moving.

**Suspected:** route throughput is limited by validation rejections. Stale drops cluster at startup, when initial tile merges rebuild the graph.

**Future work:**
- Make `build_driving_path` and candidate picking stepwise.
- Restart jobs across a graph revision instead of dropping them, if the endpoints are still valid.
- Revisit `NPC_ROUTE_JOB_BUDGET_S`, a direct throughput/smoothness knob: 2 ms gives about 8 moving NPCs at this spawn, about 9–12 ms gave about 16.
