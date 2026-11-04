# Motorway traffic: status and next steps

Status as of 2026-11-04, branch `release/v0.21.0beta`. Written so the work can
be picked up later.

## Goal

Fast NPC traffic (over 70 km/h, law § 58) should run on motorways and their
ramps only, be spawned on the motorway ahead of the taxi before the taxi sees
it, never park on the motorway (§ 37), and despawn once it is passed and out
of view.

## What is in the repository

- `c0f37e2` **Motorway route graph.** `traffic_world.py` builds a third route
  graph over `motorway` and `motorway_link` (`MOTORWAY_HIGHWAYS`), in the same
  commit window as the car graph and under the same route revision.
  `plan_motorway_route_steps` plans on it. Nothing uses it yet.
- `4d8b98b` **Traffic readings on a drive.** Driving visual tests record the
  most NPCs in view, the fewest moving and the top speed (`result.json`,
  `traffic`). The scenario `motorway_through_traffic` drives Perämerentie
  (Oulu, 1.76 km straight, start pose `383200.8, 7302861.8`, heading
  `-0.056`) at about 56 m/s.
- `visual-testing.md`: the scenario list and how to add one.

## What was tried and is not in the repository

`docs/motorway-traffic/motorway_spawn.patch` (apply with `git apply`):
- motorway spawning in `npc.py`: when the taxi does over 60 km/h within
  150 m of a motorway node, transit spawns come from motorway nodes ahead of
  the taxi, route on the motorway graph to a point 300–600 m ahead, and never
  park;
- the transit cap rises to the full shortfall in that mode.

Measured on `motorway_through_traffic` (same drive, same seed):

| Build | Most NPCs in view | Moving | Top speed |
|---|---|---|---|
| Without the patch | 4 | 0 at some frames | 50 m/s |
| With the patch | 2 | 0 at some frames | 56 m/s |

So the patch did not help and was not committed.

## What the diagnostics show

- Spawns are plentiful: about 700 candidates placed in 20 s of driving at
  58 m/s, but only 3–4 activate.
- Route latency is not the cause once motorway routing is used: p50 5 frames,
  max 12–32 frames (it was up to 257 frames with ordinary routing).
- Rejections are spread across checks: route failures (a few per tick),
  `crowded` (a 106 m clearance at 22 m/s, from `_transit_clearance`),
  `destination_taken`, `in_view`, `full`. No single check explains the gap.
- Spawn rate is capped at about two cars per population tick
  (`NPC_TRANSIT_SPAWNS_PER_TICK`) unless the cap is raised.

## Corrections to earlier notes

- The § 58 filter already works. Vehicle types the guide excludes declare a
  top speed (tractor 60, bus 70, truck 80), and the spawn code rejects them
  for motorway starts. Cars with no declared speed may use motorways, as the
  guide permits. There is no legal bug here.

## Failing tests (not caused by the motorway work)

- `tests/test_license_inventory.py`: 49 problems. Licence entries are missing
  for the train assets added in `5de0ac7` and for `borders.json.gz`.
- `tests/test_soak.py`: fails on the branch without any motorway change.
  Its assertion is `states >= ticks // 100` (6 states for 4000 ticks).
- `tests/test_npc_population.py::test_household_vehicle_ownership_persists_through_a_full_trip_cycle`:
  the known flaky NPC trip-cycle test.

## Next steps

1. Trace the spawn pipeline during the `motorway_through_traffic` drive and
   log the reason each planned car is dropped. Fix the largest one first.
2. Only then re-apply `motorway_spawn.patch` (or a corrected version) and
   measure against the same drive.
3. Add the despawn check: a motorway car passed by the taxi and out of view
   should be removed, and the scenario should show it.
4. Fix the licence entries and the soak assertion, so the suite is green.

## How to measure

```bash
.venv/bin/python tools/visual_test.py run motorway_through_traffic
```

Read `visual-test-results/motorway_through_traffic/*/result.json`, field
`traffic`. The baseline numbers above are for the commit that introduced the
scenario.
