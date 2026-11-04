# Spawn rejection distribution on motorway_through_traffic

## Goal
Show, per drive, how many planned transit cars were dropped for each reason, so
the largest bottleneck is fixed first (docs/motorway-traffic.md, next step 1).
Diagnostics only: no change to which cars spawn. Not a traffic-law change.

## What exists
`NPCPopulation._count_discard` already fills `route_job_stats["discard_reasons"]`
(shown in `_spawn_summary`, F12 JSON, `population_diagnostics["spawn"]`) for
no_speed, near_taxi, full, far, in_view, crowded, controls, destination_taken,
left_area. Gaps: a failed transit route (`result is None`, npc.py ~5815) only
bumps `route_generation_failures`, never `discard_reasons`; there is no output
per drive; no total to turn counts into shares.

## Files to change
- `src/theroadragetrip/npc.py`: in the `job["kind"] == "transit"` failure
  branch call `self._count_discard("route_failed")`. Add
  `spawn_rejection_summary(self) -> dict` returning `{reason: count}` plus
  `total` and `share` (reason -> fraction, 0 when total is 0), sorted largest
  first; reuse it in `_spawn_summary` as `discard_reasons`. Any discard path
  without a named reason uses `"other"`.
- `godot/visual_test.gd`: add `spawn_rejections` (from the server debug
  snapshot `population_diagnostics.spawn.discard_reasons`) to the `traffic`
  dict in `result.json`; print one line `spawn_rejections: reason=n (pp%) ...`.
- `docs/motorway-traffic.md`: append a section with the measured distribution
  for `motorway_through_traffic` (append only, per the phased-docs rule).

## Acceptance criteria
1. A transit job whose route fails increments `discard_reasons["route_failed"]`
   by 1 and `route_generation_failures` by 1, and counts in `jobs.failed`.
2. Each discarded transit job increments exactly one reason; the sum of reasons
   equals `jobs.discarded` + transit route failures.
3. `spawn_rejection_summary()` is sorted descending, shares sum to 1.0 (+-1e-6)
   when total > 0, and is `{"total": 0}` with empty shares otherwise.
4. Reasons seen: route_failed, crowded, destination_taken, in_view, full; any
   other reason (no_speed, near_taxi, far, controls, left_area, other) is kept
   under its own name, not dropped.
5. After `motorway_through_traffic`, `result.json` `traffic.spawn_rejections`
   is present and non-empty, and the log line is printed once at drive end.
6. Spawn decisions are unchanged: same seed gives the same activated count
   with and without the logging; per-frame work stays O(1) per job (a dict
   increment, no per-attempt log lines or lists).

## Tests to add
- `tests/test_npc_population.py::test_transit_route_failure_counts_route_failed`:
  fails today because the failed transit job never reaches `discard_reasons`.
- `tests/test_npc_population.py::test_every_transit_discard_counts_exactly_one_reason`:
  drive crowded / in_view / full / destination_taken jobs through the
  result handler; fails today for route failures (sum mismatch).
- `tests/test_npc_population.py::test_spawn_rejection_summary_sorted_with_shares`:
  pure summary check of ordering, share sum and empty case (fails: function absent).
- `tests/test_visual_scenarios.py` (or the existing visual-result schema test):
  `traffic` result contains `spawn_rejections`; skip if no graphics (VM has
  none, run on the GPU machine).

## Out of scope
- Fixing any bottleneck, re-applying `motorway_spawn.patch`, raising
  `NPC_TRANSIT_SPAWNS_PER_TICK` or changing `_transit_clearance`.
- Despawn check, licence entries, soak assertion (next steps 3 and 4).
- Per-attempt log lines, log files, or non-transit (household, bus, taxi) jobs.
