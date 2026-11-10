# Visual testing

Rendering changes are verified with named, repeatable scenarios: the same
place, vehicle pose, clock, weather and camera every run, captured only when
the scene is provably ready.

```bash
.venv/bin/python tools/visual_test.py list
.venv/bin/python tools/visual_test.py run metallic_vehicle_paint_day
.venv/bin/python tools/visual_test.py compare visual-test-results/ID/RUN_A visual-test-results/ID/RUN_B
PYTHONPATH=src .venv/bin/python tools/visual_test.py find --city Helsinki --near 385913 6671841
```

Results go to `visual-test-results/SCENARIO/STARTTIME_RUNTIME_COMMIT/`
(git-ignored): `scenario.json` (what was asked), `result.json`,
`screenshot.png` (only when every check passed), `server.log`, `godot.log`.
`run` exits 1 when any run failed.

## How a run works

`tools/visual_test.py run` starts the simulation server on a free port with
developer-only flags, never used in normal play:

| flag | effect |
|---|---|
| `--test-pose X,Y,HEADING` | the taxi at EPSG:3067 metres, heading in radians (0 east, counter-clockwise); the player in it, engine on |
| `--test-weather clear\|rain\|slush\|snow` | that weather, unchanging; historical (FMI) weather off |
| `--test-cloud C` | cloud cover held at C (0..1) |
| `--test-seed N` | seeds the random generators: the same traffic and wind draws |
| `--test-time-scale 0` | the game clock held at `--start-time` |

plus `--preset CITY`, a `--bbox` of `box_km` around the pose and
`--start-time`. Road wetness follows the weather (rain and slush start
fully wet, clear and snow dry).

The Godot client gets `--visual-test scenario.json` (and `--zoom`,
`--outdoor-3d` unless `"view": "2d"`). `godot/visual_test.gd` then checks
every frame, and only when **all** of these hold for 60 consecutive frames
does it measure and capture:

1. a state from the server has arrived;
2. the vehicle is within 1 m and 0.02 rad of the scenario pose, the player in it;
3. the game date and clock match `start_time` (within 2 game minutes);
4. the sun's altitude is inside `sun_altitude_deg`;
5. the weather type, cloud cover (±0.02) and road wetness (`wetness` range) match;
6. no chunk is queued; a loaded chunk covers each view corner and the centre,
   and none of them is still building its 3D meshes;
7. at least `requires.lamps_in_view` working street lamps and
   `requires.buildings_in_view` buildings are in the view;
8. the 3D view's light pool exists;
9. the camera is on the vehicle.

Then it records `measure_s` seconds of frame times (or, with `drive_s`,
drives straight at full throttle that long and records the street-lamp
stability counters), re-checking the conditions every frame, saves the
screenshot and writes `result.json`: status, commit, timestamp, renderer and
GPU, resolution, game time, weather, vehicle pose, camera, the scene counts,
frame times (avg / p50 / p95 / p99 / worst, lows), render times and lamp
counters. Ride offers close the phone so it never covers the scene.

A run that is not ready after 240 s fails with the checks still missing,
for example:

```
- 2 street lamps in view, the scenario needs 6
- weather clear, not rain
- a chunk under the view is still building its meshes
```

No screenshot is written for a failed run: a capture under the wrong
conditions is not evidence.

## Reading a failure

- *vehicle at ..., not the scenario's ...*: the pose is off the road, in a
  building or the server snapped it; pick the pose again with `find`.
- *game time ... not ...*: `--start-time` is clamped to at most a year
  back and never the future; pick a date in that window.
- *sun at ... deg*: the date and time do not give the light the scenario
  needs (Finnish winter days are short); change the time, not the range.
- *N street lamps / buildings in view*: the place does not have what the
  feature needs at this zoom; choose another place or zoom.
- *chunks still queued / building meshes / no chunk loaded*: the map was
  still streaming at the timeout; a cold area can take minutes on first
  load (`server.log`), run again.
- *conditions lost while measuring*: something changed during the
  measurement (weather, a chunk unloaded); the numbers are not comparable.

## Adding a scenario

Scenarios live in `tools/visual_scenarios.json`. Fields:

| field | meaning |
|---|---|
| `id`, `description` | name and what it tests |
| `why` | why this place and these conditions suit it (the map evidence) |
| `city` | the preset (`--preset`) |
| `pose` | `[x, y, heading]`: EPSG:3067 metres, radians - from `find` |
| `box_km` | the map loaded around it (default 2) |
| `start_time` | `YYYY-MM-DDTHH:MM`, or a list for a time series (one run each) |
| `weather`, `cloud` | `clear`/`rain`/`slush`/`snow`, cover 0..1 |
| `wetness` | `[min, max]` road wetness required |
| `sun_altitude_deg` | `[min, max]` the light the scenario needs |
| `zoom` | camera zoom factor (the camera is top-down, following the vehicle) |
| `view` | `3d` (default) or `2d` |
| `requires` | `lamps_in_view`, `buildings_in_view` minimums; `notice_contains`: a HUD notice with that text, wholly on screen (the data-source notice's ~15 s clock is held while it is checked) |
| `measure_s` / `drive_s` | seconds measured standing / driving |
| `seed` | random seed (default 1) |
| `graphics` | graphics settings under test, over the saved ones, e.g. `{"brightness": 1.4}` |
| `godot_args`, `server_args` | extra flags |
| `windshield` | press `I` once the taxi is ready and require the forward view before capture |
| `lane_assist` | press `K` once the taxi is ready ("keep car on lane") |

### Choosing the place

Never pick coordinates because they are easy to reach. Name what the
feature needs to be seen (lit street, wet asphalt, varied facades, metal,
glass, buildings close enough to reflect) and find a real place with it:

```bash
PYTHONPATH=src .venv/bin/python tools/visual_test.py find --city Oulu --near 427804 7210711 --radius 700
```

loads the real map and ranks drivable street points by street lamps
(±40 x 25 m), buildings (±70 x 40 m), building colours and commercial
buildings around them, with the heading along the street. Copy a row's
`x y heading` into `pose` and write the counts into `why`. The OSM data has
no facade materials (`building:material` is not read): a "facade types"
scenario can only promise different building colours and categories.

### Conditions

Choose `start_time` so the sun is where the feature needs it (check it with
`sun_altitude_deg`): day above 20 degrees, sunset 0..6, night below -12.
Weather sets the wetness; use `rain` for wet-road tests.

## Comparing implementations

Run the same scenario on two commits (`git stash`, or a worktree) and
`compare` the two result directories: a sheet with A, B and their
difference (x4), the mean pixel difference, and both runs' frame and render
times. The same scenario gives the same start, but traffic and pedestrians
move, so expect small differences around them.

## Rules for agents

For any change that needs visual verification:

1. Name the physical conditions the feature needs to be seen.
2. Look for a scenario in `tools/visual_scenarios.json` that provides them.
3. If none fits, add one from real map data (`find`), with `why`.
4. Say why the place and conditions suit the feature.
5. Run it; a failed readiness check is a failed test, not a screenshot.
6. Inspect `screenshot.png` and `result.json`.
7. Report what was verified and what was not.

Never place a vehicle at unchecked coordinates, assume a chunk or the
weather is ready, use a screenshot of an unready scene, call compilation a
visual check, or change game behaviour to make a test pass.
