# Testing Road Rage Trip

How to run the tests, what each kind covers, how to write a new one, and
what must pass before a release. Task: `.github/prompts/rrt-018-testing.md`.

## Commands

All commands run from the repository root, after `make install`, which
installs `requirements.txt` into `.venv`.

| What | Command | Time | Needs |
| --- | --- | --- | --- |
| Python suite, in random order | `make test` (or `.venv/bin/python -m pytest -q`) | ~90 s | nothing else |
| One file or test | `.venv/bin/python -m pytest -q tests/test_taxi.py -k lifecycle` | | |
| Reproduce an order | `pytest -p randomly --randomly-seed=N` (each run ends with `random order: --randomly-seed=N`) | | |
| Fixed order | `pytest -p no:randomly` | | |
| Compile check | `make compile` | | |
| Audio catalogue | `make audio-check` | | |
| Godot client tests | `make godot-test` | ~10 s | Godot 4.7.2 (`make fetch-godot`) |
| Server + headless client, offline | `make godot-selftest-sample` | ~10 s | Godot |
| Server + headless client, real city | `make godot-selftest` | 1–3 min | Godot, network (Overpass) or a world cache |
| Longer soak runs | `RRT_SOAK_SCALE=10 pytest -q tests/test_soak.py` | ~3 min | |

`make godot-selftest-sample` fails unless the selftest report says
`"ok":true`. `make godot-selftest` prints the report; read `"ok"` yourself.

CI also measures `taxi_brawls` and `digitraffic_road` with `coverage` (a
CI-only test tool, not a game dependency). Each module must have at least
90% **line coverage and branch coverage independently**; a high line score
cannot hide untested branches. To reproduce the report locally, install
`coverage` in the virtual environment and run:

```sh
.venv/bin/python -m coverage run --branch --source=theroadragetrip.taxi_brawls,theroadragetrip.digitraffic_road -m pytest -q tests/test_taxi_brawls.py tests/test_digitraffic_road.py
.venv/bin/python -m coverage report
.venv/bin/python -m coverage json -o /tmp/rrt-feature-coverage.json
```

This is a gate for the new modules, not a claim that all Python or Godot
code meets 90% branch coverage. Wall-clock performance checks should also
be run without instrumentation before diagnosing a timing regression.

## Test levels

| Level | Where | Examples |
| --- | --- | --- |
| Unit | most of `tests/` | fares, fuel purchases, building people, traffic demand, protocol parsing |
| Subsystem | `tests/test_npc_population.py`, `test_pedestrians.py`, `test_ride_lifecycle.py` | NPC trips on a block grid, the taxi ride state machine |
| Server integration | `test_client_server_integration.py`, `test_server_headless.py`, `test_slow_clients.py` | a real server on the sample map, a real client over TCP |
| Long runs | `test_soak.py` | the server past midnight; minutes of traffic and walkers, checked every tick |
| Client unit | `godot/tests/run_tests.gd` (`make godot-test`) | HUD, phone, rendering helpers, attributions |
| End to end | `make godot-selftest-sample` | the Godot client starts, connects, drives the taxi and reports frame timing |

`make godot-test` and the selftest test different things. The tests check
client logic. The selftest checks that the real client starts, loads its
scenes, follows the server and drives. A clean `--import` alone shows neither.

## Guarantees of the test environment (`tests/conftest.py`)

- **Isolated user paths:** `HOME`, `XDG_*`, `APPDATA` and `LOCALAPPDATA`
  point at a throwaway directory before the game is imported. The tests never
  touch your config, saves, OSM cache or world cache, and server subprocesses
  inherit the same directory. `tests/test_isolation.py` checks this.
- **No live network:** a connection to anything but this machine fails the
  test with "test tried to reach the network". Fake the fetch instead, as
  `test_auto_fetch.py` does.
- **No downloads:** timetable and train-composition refreshes are disabled;
  the bundled data is used.
- **Servers closed:** every server a test starts with `run_server` is closed
  after the test, pass or fail.
- **Fake `pyproj` per test:** a module that needs one installs it with an
  autouse `monkeypatch` fixture, never at import, because an import-time
  install leaks into every later test.
- **Timing tests:** a test that asserts a wall-clock budget is marked
  `@pytest.mark.timing` and passes when one of three runs meets the budget.
  Load only adds time, so a real regression fails all three runs.

## Randomness and time

- **Random order:** `pytest-randomly` shuffles the test order and reseeds
  `random` before every test. A test must pass for any seed. When one fails,
  rerun it with `--randomly-seed=N`: the same seed reproduces it.
- **Several seeds in one test:** use `random.Random(seed)` and a parametrized
  seed, as `test_ride_lifecycle.py` and `test_traffic_demand.py` do.
- **NPC traffic demand:** the draw comes from `NPCVehicleManager.demand_rng`;
  seed it in tests.
- **Game time:** comes from the server's calendar (`--start-time` on the
  command line). Managers take the moment as an argument, such as
  `npc_manager.clock` or `taxi.update(..., game_time_seconds=)`, so tests pass
  a fixed `datetime`.
- **Wall time:** never `sleep` and hope. Wait for a state, as
  `_until_state` does, or for a port, as `tools/wait_for_port.py` does.

## Writing a regression test for a bug

1. Reproduce it with the smallest test that shows the symptom, at the lowest
   level that has it. The passenger-identity bug was one helper in
   `simulation.py`, not a whole game session.
2. Check that the test **fails without the fix**: stash the fix, run the test,
   restore. Say in the commit message that you did.
3. Fix the cause, then run the subsystem's tests and the whole suite.
4. Name the test after the behaviour, such as
   `test_a_dropped_off_passenger_walks_on_as_the_same_person`, and start its
   docstring with `Bug:` and the symptom as reported.
5. Add a row to the matrix below if it covers something new.

If a bug can't be reproduced automatically, write the manual steps under
"Manual verification" and say why.

## Release gates

`.github/workflows/tests.yml` runs on every push to `master` and
`release/**`, and on every pull request:

1. The Python suite in random order, the compile check, and the audio check.
2. The Godot client tests, then the server and headless client selftest on
   the sample map, offline. The server and selftest logs are kept as an
   artifact.

`windows-release.yml` builds and smoke-tests the Windows package, on a manual
run or a `v*` tag.

**A release candidate is validated when all of these are true:**

- `tests.yml` is green on the release commit.
- `windows-release.yml` is green.
- `make godot-selftest` passes on a real city (it needs the network, so it
  isn't in CI).
- `RRT_SOAK_SCALE=10 pytest tests/test_soak.py` passes.
- The manual checks below are done.

Passing unit tests alone does not validate a release.

## Coverage matrix

The matrix covers the behaviour that matters most. P1 is something that can
corrupt game or money state or block a release; P2 is a visible gameplay
error; P3 is cosmetic.

| Subsystem | Behaviour and invariants | Tests | Missing | Level | P |
| --- | --- | --- | --- | --- | --- |
| Taxi rides | States go PICKUP → WALKING → DROPOFF and never back. One payment per fare. A cancelled ride pays nothing, and cancelling twice penalises once. No offer can be accepted during a ride. | `test_ride_lifecycle.py`, `test_taxi.py` | Long fares end to end on a real map | unit, subsystem | P1 |
| Passenger identity | The same resident (id, name, gender) from offer to drop-off and after it. The next ride is someone else. | `test_ride_lifecycle.py` (including the drop-off bug) | | unit | P1 |
| Fares, money | Fare tables, tips, speed bonus, refuelling charges (exactly once per press; refused presses charge nothing) | `test_fare.py`, `test_speed_bonus.py`, `test_fuel.py`, `test_client_server_integration.py` | Speed camera fines against the balance | unit, integration | P1 |
| Fuel | Consumption, an empty tank, refuelling rules | `test_fuel.py`, `test_client_server_integration.py` | | unit, integration | P2 |
| Saves | Career, gig odometer and homes round trip; the config path is never relative | `test_career.py`, `test_home.py`, `test_isolation.py` | A corrupt save file | unit | P1 |
| Protocol | Encode and decode, version mismatches, malformed lines; a malformed command is no input and never crashes the tick; phone requests | `test_protocol.py` | Reconnecting a client | unit | P1 |
| Server and client | The world header, chunks, states and commands over TCP; a slow client; closing; one player id | `test_client_server_integration.py`, `test_slow_clients.py`, `test_server_headless.py` | | integration | P1 |
| NPC traffic | Spawning and despawning, trips, recovery and give-up, households, parking, demand by place, road and clock; no duplicate or orphan vehicles or drivers | `test_npc*.py`, `test_traffic_demand.py`, `test_soak.py` | NPCs at real junctions on a real map | subsystem, long run | P2 |
| Pedestrians | Spawning by population, despawning, one walker per resident | `test_pedestrians.py`, `test_population.py`, `test_soak.py` | | subsystem | P2 |
| Traffic law | Signals, crossings, priority, roadworks (`docs/finnish-npc-traffic-law.md`) | `test_traffic_lights.py`, `test_crossing*.py`, `test_finnish_traffic_acceptance.py`, `test_roadworks.py` | | subsystem | P2 |
| Rail | Timetable, passengers, bookings, meet and greet | `test_train*.py`, `test_rail_*.py`, `test_station_*.py` | | subsystem | P2 |
| Clock, weather | Seasons, the clock crossing midnight, holidays, FMI parsing (fixtures in `tests/data`) | `test_calendar_seasons.py`, `test_soak.py`, `test_weather*.py` | Year boundaries | unit | P2 |
| Map data | OSM building, PBF, chunks, streaming, caches | `test_build_*.py`, `test_pbf_*.py`, `test_map_chunks.py`, `test_tile_streaming.py`, `test_world_cache.py` | `osm/overpass.py` and `server/map_sync.py` have no direct tests | unit | P2 |
| Activities | Sports and games at venues | `test_activities.py`, `test_soccer.py`, `test_ice_sports.py` | `activities/team_game.py` has no direct test | unit | P3 |
| Godot client | HUD, phone, rendering helpers, attributions; startup and driving (selftest) | `godot/tests/run_tests.gd`, the selftest | Input handling, menus | client unit, end to end | P2 |
| Packaging | The licence inventory; the Windows build | `test_license_inventory.py`, `test_packaging.py`, `windows-release.yml` | | unit, CI | P1 |

## Manual verification

These are not automated, and they need a person before a release:

- Visual correctness: rendering, lighting at night, the headlight beams, snow,
  and bridges. The selftest checks frame timing, not how things look.
- Audio: mixing, chatter timing and announcements, beyond what
  `make audio-check` covers (files and references).
- A real city drive of about 15 minutes: fares, refuelling, NPC behaviour at
  real junctions, trains at a station, and FPS.
- Loading and stuttering on a large local `.osm.pbf` map. This is a known
  issue and isn't measured by these tests.
- The Windows installer on a clean machine: installing, the first start, and
  uninstalling.
