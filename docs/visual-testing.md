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
| `--test-hill X,Y,HEIGHT,RADIUS` | a synthetic cosine ridge at EPSG:3067 metres as the render ground (replaces any DEM; nothing read from or written to the cache); give it with the scenario's `server_args` |
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
| `requires` | `lamps_in_view`, `buildings_in_view` minimums; `ground_rise`: `[x, y, m]`, ready only when the ground at (x, y) is m metres above the pose's (a `--test-hill` is loaded); `airborne_frames`: the run fails if the taxi was in the air for fewer frames; `body_pitch`: `{kind: rad}`, ready only when the last drawn body of each kind (`bus`, `tram`...) is pitched at least that much with the ground; `bodies_on_ground`: `[lineup m, traffic m]`, ready only when every drawn model's wheel points are within that of the surface of its own layer (the rails for trains), the standing lineup and the moving traffic judged apart; `rider_parts`: ready only when a rider mesh with at least a walking person's vertex count was built; `riders_near`: `[max m, min px, kind]`, ready only when a riding `kind` (bicycle, motorcycle, e_scooter) is on screen within that distance of the camera and at least that tall; `notice_contains`: a HUD notice with that text, wholly on screen (the data-source notice's ~15 s clock is held while it is checked) |
| `requires.forest_target` | `{bounds: [west, south, east, north], min_crowns: N, min_height_px: px}`: `require_glb: true` compares expected normally streamed forest rows with complete cached Cozy Nature source instances and their original ground-centred transforms inside that real mapped target. Both LOD populations must match; active camera layers, applicable batch distance ranges and at least N on-screen GLB instances of useful projected height are required. Primitive crowns cannot satisfy the GLB requirement. Counts are recorded in `scene.forest_target`. |
| `requires.catalog_stars` | Require pinned SAO source/atlas hashes, authoritative observer/UTC basis, actual sky camera, and known catalogue directions projected into the view. `min_projected`, `min_visible`, `min_faint`, `pollution: [min,max]`, `moonless`, `hidden` select controls. Before timing, paired star-on/off renders measure each source pixel's actual star contribution, excluding window/cloud/gradient false positives; normal rendering is restored before readiness and capture. Results record IDs, magnitudes, directions, pixels and contrasts in `scene.catalog_stars`. `eye.pitch` tilts the existing driver-eye camera to view the sky. |
| `measure_s` / `drive_s` | seconds measured standing / driving |
| `seed` | random seed (default 1) |
| `graphics` | graphics settings under test, over the saved ones, e.g. `{"brightness": 1.4}` |
| `godot_args`, `server_args` | extra flags |
| `windshield` | press `I` once the taxi is ready and require the forward view before capture |
| `speed_limiter` | `false` turns the speed limiter (V) off for the whole run, so a `drive_s` drive can exceed the street's limit (the taxi reaches 30 m/s in about 8 s) |
| `capture_airborne_m`, `capture_apex` | with `drive_s`: take the screenshot as soon as the player's taxi is this many metres above the road (`entities.air_height`); with `capture_apex` at the first frame past the top of the arc (the run fails if the shot is under 90 % of the peak); the run fails if it never was |
| `lineup_shift`, `lineup_lane` | with `lineup_along_road`: where the lineup starts along the road (default 6 m ahead of the taxi's middle) and how far left of the taxi's line it stands (default 3.5 m) |
| `lineup_check` | `false`: the lineup's screen boxes are not required inside the view (a scenario that checks its bodies another way) |
| `lineup_turn_deg` | the lineup's bodies turned this many degrees from the road's direction (a side or three-quarter view from the chase camera) |
| `lineup_top_m` | the height (default 3.5 m) up to which each lineup body must be inside the screen |
| `with_tram`, `lineup_tram_s`, `lineup_no_coach` | with `lineup_kinds`: the lineup's tram section too, starting `lineup_tram_s` m along the road (default 27); `lineup_no_coach` leaves out the train coach under it |
| `lane_assist` | press `K` once the taxi is ready ("keep car on lane") |
| `extends` | the id of another scenario whose fields this one starts from; its own fields override them, `null` removes one |
| `engine_args` | extra Godot engine flags before `--`, e.g. `["--rendering-method", "forward_plus", "--rendering-driver", "vulkan"]` (the result records the active renderer and GPU) |
| `binoculars.clear_street` | `true`: the client draws no server walkers or NPC cars (`entities.drop_traffic`), so none can stand in a street target's sight line. A remaining blocker (walker 1.9 m, car 2 m, bus/truck/tram/tractor 4.2 m, within the target's width of the ray to the target's middle and taller than the ray there) is named in the readiness message and the run fails when it persists (60 s of no change) |
| `binoculars` | docs/specs/binoculars-fps-moon.md: with `walk` (on foot, first person, `forward: 0`, `yaw`/`pitch` = the manual aim) the scenario presses `O`, then `steps` wheel-up notches (3 = 8x) as input events; `lower: true` presses `O` again. The FOV is never set by the test. Readiness: on-foot first person, the expected raised/lowered state, camera FOV equal to `2*atan(tan(base/2)/magnification)` (exactly the base FOV when lowered), the aim and eye unchanged since the 2x view, and the `target` fully inside the view. `target`: `{"kind": "moon"}` (adaptive Moon disc bounds, lit-interior contrast and clipping from `requires.moon_phase`; `"hidden": true` for a full-overcast control that must show no Moon), or `{"kind": "points", "points": [[x, y, height_m], ...], "building_at": [x, y]}` (EPSG:3067 corners projected through the real camera; `building_at` must lie in a loaded building footprint). At 8x the 2x capture predicts the projected target width, the Moon's lit extent, and the whole image (the middle 1/4 of the 2x image enlarged 4x must correlate with the 8x image, and better than the unmagnified one). Evidence is in `scene.binoculars` of `result.json` |

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
