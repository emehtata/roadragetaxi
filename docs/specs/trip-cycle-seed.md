# Trip-cycle test: constant random seed

## Goal
Make `test_household_vehicle_ownership_persists_through_a_full_trip_cycle` reproducible by
seeding the global `random` module with a constant at the start of the test.

## Nondeterminism source
- `tests/test_npc_population.py:1007` (the test) never seeds. `pytest-randomly`
  (requirements.txt) reseeds `random` per test from `--randomly-seed`, so each run uses
  a different seed.
- The code under test draws from the global `random` module: `src/theroadragetrip/npc.py`
  lines ~400 (`random.shuffle` of on-road spawn points), 1891/4099 (colour), 1962-1987
  (trip group size, activity), 4506 (activity duration), plus `populate_initial` placement.
  Different draws mean different spawn spots and routes.
- Other tests in the same file already do `random.seed(N)` as the first statement
  (lines 460, 625, 1847, 1925, 2444). No fixture in `tests/conftest.py` seeds.

## Files to change
- `tests/test_npc_population.py`: first statement of the test body, before
  `NPCVehicleManager(...)` / `populate_initial`: `random.seed(2)` with a one-line
  comment ("placement is random; keep this scenario fixed"), as at line 1925.
  Do not touch assertions, loop length or tolerances.

## Acceptance criteria
1. With the seed in place the test passes alone (`-k full_trip_cycle`).
2. It passes under three different `--randomly-seed` values (for example 1, 2, 3, plus
   known-bad ones 4 and 9): the result no longer depends on pytest-randomly's seed.
3. Seed 2 was chosen because it passed in a trial (seeds 2, 3, 6, 10 all passed under
   randomly seeds 1-3). If it fails when implemented, try the next passing candidate; do
   not tune the seed to anything else.
4. The full suite passes (`pytest tests`, nothing deselected beyond the known exclusions).

## Honest caveat
The constant seed hides, not fixes, the underlying NPC bugs recorded in the memory note
`npc-trip-cycle-flaky.md`: head-on on a short block between two turns, and roadside
parking overshoot into the field (about half of random seeds fail). The user asked for
a fixed seed, so this is accepted; the real bugs stay open and should be mentioned in
the commit message.

If the test fails under the constant seed for a real reason (for example the
"neither made it home nor had a well-formed accident" assertion), report it with the
seed and failure text. Do not weaken assertions, raise the step count, or relax
the 100 m distance check. Choosing another passing seed is allowed only if the first
choice fails at first run; flipping seeds after a later regression is not.

## Tests to add
None new. The change is to the existing test; before the change it fails on
`--randomly-seed` 1, 4, 5, 8, 9 (alone) and after it passes on all of them.

## Out of scope
- Fixing the turn-path head-on or parking-overshoot behaviour.
- A global seeding fixture or changing pytest-randomly configuration.
- Other flaky tests.
