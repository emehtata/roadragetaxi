# Spec: release-readiness fixes from docs/pr-findings-0.21.0b-0.md

## Goal
Fix the verified motorway through-traffic stuck defect, unify Godot test execution between `make godot-test` and CI, and add deterministic motorway regression and integration coverage. No new features, no NPC population caps.

## Observations covered
- F1 (P1) mid-route STUCK/HOLD through-traffic never retired while visible: REAL DEFECT.
- F2 (P2) Makefile and CI run different Godot tests: REAL DEFECT (CI hygiene).
- F3 Oulu motorway integration scenario: IN SCOPE, new test.
- F4 Performance verification and F5 release verification: PROCESS, no code change (see Out of scope).
- F6 Git workflow, F7 final report: PROCESS, out of scope for the spec.

## F1 Through-traffic stuck mid-route
Evidence: `src/theroadragetrip/npc.py:4686` `_retire_finished_through_traffic`. A mid-route vehicle in STUCK/HOLD passes the `continue` guard (line 4691). `dead_end` (line 4693) requires `path_index >= len(path)-1`, so it is False. Retirement then needs the vehicle to be outside the viewport. A visible mid-route stuck vehicle therefore stays forever. HOLD is set at line 5823 and retried by the population tick, but with no bound for through traffic. The existing tests in `tests/test_motorway_through_no_park.py` only cover end-of-route.
Expected: a `fast_through` vehicle that is STUCK/HOLD gets a bounded number of recovery attempts, then is retired by `retire_vehicle` (line 7064) even when visible. Recovery that succeeds returns it to NORMAL and resets the counters. Non-through NPCs and the player are untouched.
Acceptance:
1. Add per-driver bookkeeping (for example `through_stuck_since_tick`, `through_recovery_attempts`) and a constant `NPC_THROUGH_MAX_RECOVERY_ATTEMPTS`. Do not raise the existing stuck timeouts.
2. Mid-route STUCK for a `fast_through` vehicle: once the attempts are used up, the vehicle is removed from `vehicles`, `drivers`, `_route_jobs`, the spatial index and `nearby_vehicles_at`, whether or not it is in view.
3. Same for HOLD, including a failed "recovery" route job (line 5819).
4. A recovery route that succeeds before the bound sets stage NORMAL, keeps the vehicle, and clears the counters.
5. Dead end (path_index at end, STUCK/HOLD) is still retired at once, counted as `through_dead_end`.
6. A new counter `spawn_flow["through_stuck_retired"]` is incremented for bound-exceeded retirements.
7. Check the map-expansion path. A queued "transit" job is replanned on a revision change (lines 5747-5754) using the closure's frozen player position, viewport and `motorway` flag (line 6612). Decide from a test whether this discards or misplaces motorway spawns. If it does, the replan must use the current player and viewport. The job must never be dropped silently while demand remains: `job_stale` must not be counted for jobs that have a `replan`.
8. Retirement adds no per-tick global scan. It iterates only `fast_through` vehicles, as now.

## F2 Godot test list drift
Evidence: `Makefile:164-176` runs 11 scripts. `.github/workflows/tests.yml` "Client tests" runs 4, so CI misses home_interior, electronic_signs, surface_details, forest_trees, precipitation_3d, home_walk and home_interior_3d. `godot/tests/` holds about 43 `.gd` files, and many of those are render or screenshot tools, not assertions.
Expected: one authoritative runner, used by both Makefile and CI.
Acceptance:
1. Add `tools/run_godot_tests.py`, which reads one manifest (`godot/tests/manifest.txt`) of headless assertion scripts. It runs each with `--headless --script`, streams the output, and exits non-zero if any script fails. It prints a pass/fail summary.
2. The manifest lists every assertion test. Render or screenshot scripts are listed in a separate "excluded" section, each with a reason.
3. `make godot-test` calls the runner after the import. The CI "Client tests" step calls the same runner. No script is listed in either file by hand.
4. A Python test checks that every `godot/tests/*.gd` file is in the manifest as included or excluded, so a new test cannot be forgotten.
5. A script that calls `quit(1)`, or is killed by the timeout, fails the job.

## F3 Oulu motorway integration scenario
Expected: a deterministic test on real Oulu OSM data (the bundled sample or cached extract; skip with an explicit reason if the data is absent, never silently pass).
Acceptance:
1. A selector function picks a motorway way from the data by fixed criteria (highway=motorway, connected in `traffic_world.motorway_graph`, route extendable at least `MOTORWAY_TRIP_MAX_M` beyond the loaded bounds). It asserts these criteria and fails with a clear message if no segment qualifies.
2. The player car is placed on that segment at a fixed seed and driven along it above `MOTORWAY_SPAWN_MIN_SPEED_MPS`, with at least two simulated map expansions.
3. It records spawned, routed, entered and left, failed spawns, stuck retired, mean and max spawn delay, and tick duration, and writes them as JSON.
4. Asserts: spawning continues after each expansion, no vehicle is stationary beyond the F1 bound, and no vehicle disappears inside the view without a retire reason.
5. If the segment has no valid demand (no motorway nodes ahead), the test reports "no demand" and is distinct from a spawn failure. The selector then picks again, or the test fails as a setup error.

## Tests to add (pytest, deterministic, fixed seed)
`tests/test_motorway_through_lifecycle.py`
- `test_stuck_midroute_visible_is_retired_after_bound`: fails today, because a visible vehicle is never retired.
- `test_hold_midroute_visible_is_retired_after_bound`: fails today.
- `test_failed_recovery_retires_through_vehicle`.
- `test_successful_recovery_resets_counters_and_keeps_vehicle`.
- `test_dead_end_retired_immediately`.
- `test_retire_clears_all_registries`: checks `vehicles`, `drivers`, `_route_jobs` and the spatial index.
- `test_non_through_stuck_vehicle_unchanged`.
- `test_map_expansion_keeps_pending_motorway_spawn`: bumps `route_graph_revision` with a queued transit job, then asserts the job is replanned, not dropped, and that `motorway` is preserved.
- `test_repeated_map_expansion_preserves_demand`: several revision bumps, the job count is unchanged and spawns still complete.
`tests/test_godot_manifest.py::test_every_godot_test_is_listed` (F2.4). It fails today.
`tests/test_oulu_motorway_scenario.py::test_oulu_motorway_drive` (F3).

## Out of scope
- F4 and F5: run `tests/test_performance.py` and the full Python and Godot suites, and report before/after tick times. Add no code unless a regression appears, and fix its actual cause. Do not claim GPU or Windows rendering was verified from headless Linux. Visual checks use a named scenario from `tools/visual_scenarios.json` (docs/visual-testing.md), only if Godot code changes.
- F6 and F7: commits (one per concern), push and report are the implementer's workflow.
- No population limits, no timeout increases, no disabling of stuck detection, no tags.
