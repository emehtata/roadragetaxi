# Soak test: state count assertion

## Goal
Make `tests/test_soak.py::test_the_server_runs_through_midnight_and_every_state_parses`
pass deterministically. The server is correct; the test's expectation is wrong.

## Diagnosis (evidence)
- `server/__init__.py:1576` `_broadcast_state` runs every tick (also at :995 while paused
  and :1169 after a normal tick), so the server does produce one state per tick.
- `transport.py:141-155` `send_state` keeps ONE pending state per client and replaces an
  unsent one (`coalesced_states += 1`); "a behind client gets the newest state". This is
  intended back-pressure, not a bug.
- The test (`tests/test_soak.py:34-46`) runs 4000 ticks back-to-back (~2.5 s, no sleep)
  and counts states the client received (`states >= ticks // 100`, i.e. 40). Delivered
  count depends on how often the writer thread gets scheduled against the tight loop.
  Observed on clean HEAD: 3, 14, 20, 31, 2 versus 40 needed. The assertion at :46
  encodes "no coalescing", which contradicts `send_state`.
- Clock and parse assertions (:37, :43-44, :45) are fine and stay.

## Decision
Test fix only. No server or transport change: coalescing is by design, and the server
sends every tick.

## Files to change
- `tests/test_soak.py` (that test only): replace the `states >= ticks // 100` rate
  assertion with checks that do not depend on thread scheduling.

## Behaviour / acceptance criteria
1. Every state the client receives decodes and has `game_time_seconds >= 0` (kept).
2. The client receives at least one state during the run, and the last received
   `message["tick"]` is strictly greater than the first (the stream keeps advancing).
3. Server-side accounting: for the server's client connection(s) in `server._clients`,
   `coalesced_states` plus the states received by the test never exceeds `ticks`, and
   the server produced a state every tick: assert `server._tick >= ticks` (or the last
   received tick is close to it after a short drain). No sleeps tuned to timing.
4. Clock only moves forward, 6 h elapsed, date turns (kept).
5. Passes in 3 consecutive runs, under two seeds
   (`pytest -p randomly --randomly-seed=N`, e.g. 1 and 12345), and the full suite
   (`python -m pytest tests`, nothing deselected) passes. Use
   `XDG_DATA_HOME=$(mktemp -d)` if any startup/settings test is in the run.

## Tests to add
- Same file, same test name, revised assertions as above. Without the fix it fails
  with `assert N >= 40` for N well below 40 depending on scheduling.
- Optional small transport test in `tests/` (existing transport test file): two
  `send_state` calls before the writer runs deliver only the second and bump
  `coalesced_states` to 1, documenting the behaviour the soak test relies on. Add only
  if one does not already exist (grep `coalesced_states` in `tests/` first).

## Out of scope
- Changing coalescing, tick rate, or state frequency.
- The flaky NPC trip-cycle test and the parked `server/cli.py` and
  `tools/visual_scenarios.json` edits (leave uncommitted and untouched).
