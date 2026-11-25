# Terrain-following bodies, speed-bump hops, no air control, real cyclist

## Goal
Speed bumps are real road shapes that the car rolls over slowly and hops over fast. Every drawn
moving body sits on and tilts with DEM ground, decks, ramps and bumps. The car can't steer,
accelerate or brake in the air (decided on the server). Cyclists are posed people, not boxes.
Follows docs/specs/vehicle-airborne-physics.md. The server stays authoritative and NPC traffic
decisions don't change.

## Root causes (evidence)
- Bumps are visual only. The server sends `[x, y, angle, width, kind]` (`map_chunks.py:641-645`), and
  the client draws a flat 0.07 m box (`buildings_3d.gd:2708,2771-2772`, lengths `chunk_detail.gd:15`,
  where "hump" is 0.6 m but should be about 3.7 m). `road_surface_height` (`buildings_3d.gd:2810-2814`)
  ignores bumps, so `deck_height` and `VehicleVertical` never see them. `LAUNCH_GAP_M` 0.15
  (`vehicle_vertical.gd`) is also taller than any bump. On the server, `check_speed_bump`
  (`taxi.py:1156`) only cuts speed.
- Air control: `physics.py:1831-1858` applies steering every tick. The server has no vertical state.
- Rider: `_rider` (`buildings_3d.gd:1339-1343`) is two boxes (torso and head), used for the bicycle
  at `:1190-1191` (GLB) and `:1465-1466` (procedural). `person_arrays` (`:1572`) already has posed
  limbs and a seated "riding" pose with leg joints (`riding_leg_joints`, `:1567`). No new asset is needed.
- Screenshot: the newest PNG with bicycles in its JSON (`screenshots/screenshot_1795011901188000000`)
  is a top-down night view, too far out to show the rider. The boxes are confirmed from the code above.

## Audit (client bodies)
| Body | Height | Pitch/roll | Verdict |
|---|---|---|---|
| Player car, NPC cars/taxis/vans | `deck_height` `entity_layer.gd:1041` | `wheel_tilt` `:1043` | OK (no bumps) |
| Bus, truck, tractor/plough, camper, motorcycle, bicycle, e-scooter | `deck_height` `:918` via `vehicle()` | none (`buildings_3d.gd:1305-1325` drops tilt) | level on slopes and ramps |
| Trains, trams, ferries | `rail_height` `map_layer.gd:635-642` = `DECK_M` or 0.0 | none | no DEM: sink or float on hills |
| Pedestrians, walking player | `deck_height(at, ped.layer)` `entity_layer.gd:2167` | upright (correct) | NPC pedestrians OK (`layer` is sent). Measured: the walking player's row had no layer (`player_walker_dict`), so on a bridge deck the figure stood on layer 0, up to 6 m under it. Fixed in 2d |
| Elves | `person()` with no elevation `:2169` | - | sink or float on DEM |
| Dogs | `animal()` with no elevation `:2173` | - | sink or float on DEM |
| Wildlife | `animal()` elevation = flight offset only `:2190` | - | ignores ground |

## Part 1: speed bumps (commits 1a server data, 1b client surface)
Files: `chunk_detail.gd:15` (profiles), `buildings_3d.gd` (bump mesh and `road_surface_height`),
`map_layer.gd:623` (pass the chunk's bumps), `vehicle_vertical.gd` (launch gap).
Profiles (h, L): bump 0.07 m / 0.6 m; hump 0.10 m / 3.7 m (sinusoidal); cushion 0.08 m / 2.5 m,
1.8 m wide; table 0.10 m with 1.2 m ramps and a flat top (total 2.2 + 2.4 m).
`static func bump_height(at: Vector2, bumps: Array) -> float`: the profile offset, added in `road_surface_height`.
1. The drawn bump mesh top and `deck_height` agree within 0.005 m at 9 points along each profile.
2. A hump (10 cm) never hops at 20 or 40 km/h. At 50 km/h each axle's tyre is off the road 0.05-0.12 s and lifts under 4 cm;
   faster means longer and higher (60, 70, 100 km/h), the body's lift staying under 0.10 m at 70 km/h.
3. A 7 cm bump at 50 km/h: each axle off the road 0.05-0.12 s, lifting under 3.5 cm (under half the bump), and a landing
   jolt `land_bump` > 0.2. A half-height bump does not hop at 50 km/h, a double-height one hops more; the rear axle's hop
   comes a wheelbase after the front axle's. The hop is the same at every frame rate (airtime within 2 ms from 30 to 720 Hz
   and with jittered frames, both directions) and the same yes/no for every bump type at a given speed.
4. Terrain does not launch on grade kinks: a raster with 2-6 % kinks, grades to 12 % and 3-6 m embankments driven at
   50-58 m/s at 30-144 Hz never takes off; the real Oulu DEM gives 0 take-offs per km; a 10 m hill does launch a 30 m/s car,
   the same hop within 0.06 s at 30-720 Hz. (The client's own `VehicleVertical`, whose seam and ramp tests this replaces, is
   removed: the client draws the server's hop.)
5. Lookup cost: only the bumps of the chunk containing `at`.

## Part 2: bodies follow the ground (2a helper, 2b vehicles, 2c rail, 2d people/animals)
`EntityLayer.body_pose(c: Vector2, heading: float, length: float, width: float, layer: int, id) -> Vector3`
returns (height, pitch, roll). It reuses `wheel_tilt` and the `_tilts` easing (moved out of `:1036-1044`).
`vehicle()` gains `tilt := Vector2.ZERO` and passes it to `place_model_car`/`place_body`.
`rail_height` returns `ground_height + DECK_M on rail decks`. Elves, dogs and wildlife get
`deck_height(at, 0, false)` (flying animals add their offset to it).
6. On a 6 % DEM grade, a bus's pitch matches `atan(0.06)` within 0.01 rad. It is 0 on flat ground.
7. Along the scenario route, every drawn body's lowest wheel or foot is within 0.025 m (standing) or 0.03 m (moving traffic)
   of the surface of its own layer (trains: rail deck or ground).
8. Trains on a slope have nonzero pitch. Ferries sit at the drawn water surface within 0.1 m.
9. Tilt is computed only within 120 m of the camera, else 0. `perf` counter `pose_lookups` <= 4 x bodies per frame.

## Part 3: no air control (3a server vertical, 3b wire flag)
New `src/theroadragetrip/vertical.py`. `TerrainFlight` takes the car over the DEM (leaves where v^2 times the crest curvature at
the DEM's spacing reaches g and the arc clears the ground); `BumpFlight` over a mapped bump, closed form from the profile, the speed
and the car's wheelbase: a quarter-car per axle (the front axle meets the profile first, the rear one a wheelbase later; the
body keeps the road's vertical speed over the last 2 m and falls ballistically; the wheel stays on the road while it drops away
less than the spring's 6 cm droop). The server computes airborne itself and doesn't trust the client, so it is cheat-safe for
multiplayer. Layer != 0: never airborne. The server has no deck data, and ramps never launch.
In `physics.py:~1831`: while `car.airborne`, steer, throttle and brake are 0, the heading rate is 0
and only drag acts. Velocity keeps its take-off direction, so after landing the motion follows the arc.
`protocol` sends `airborne`, `air_height` and `land_bump` in the player state (protocol version 3) and the client draws them.
10. Client and server agree because the client draws the server's hop: it blends `air_height` and `land_bump` of the two
    snapshots (tested), and the real server tick over a mapped hump sends `airborne` exactly while `air_height` is up and a
    landing jolt (tested). The client computes no arc.
11. Full steer held during a hump hop: the heading change while airborne is 0. Throttle does not
    raise speed. Brake does not lower it beyond drag.
12. On landing, the position is within 0.2 m of the straight-line extrapolation of the take-off velocity.

## Part 4: cyclist body (4a pose, 4b wire)
Replace `_rider` for the bicycle with `person_arrays(..., "cycling")`: hips on the saddle and hands
on the bars. The legs alternate on a crank circle (radius 0.17 m), and the phase comes from distance
travelled. Clothing, skin and variant come from the vehicle id.
13. The rider mesh has the same limb part count as a walking pedestrian (no 2-box torso).
14. The feet stay within 0.03 m of the pedal circle at 8 crank phases. The hips are within 0.05 m of the saddle top.
15. No new asset, so no licence changes.

## Tests
- `godot/tests/speed_bump_surface.gd::test_mesh_matches_deck_height` (criterion 1), `::test_hump_hop_fast` (the client draws the
  server's hop, criterion 10), `::test_hump_rolls_slow`, `::test_short_bump_jolts`.
- `godot/tests/body_pose.gd::test_bus_pitch_on_grade`, `::test_train_on_dem`, `::test_animals_on_dem`,
  `::test_stance_is_immediate_and_frame_rate_independent`.
- `tests/test_vertical.py`: `::test_a_bump_is_a_short_hop_with_a_small_lift` (3), `::test_a_hump_hops_more_the_faster_it_is_taken_and_not_at_20_kmh` (2),
  `::test_the_hop_scales_with_the_height_and_the_wheelbase`, `::test_the_decision_is_the_same_for_every_bump_type_at_every_frame_rate`,
  `::test_dem_kinks_and_embankments_never_launch_at_motorway_speed` (4), `::test_no_air_steer` (11), `::test_landing_follows_arc` (12);
  `tests/test_server_headless.py::test_the_server_hops_a_mapped_hump_and_sends_the_hop` (10).
- `godot/tests/cyclist_rider.gd::test_rider_is_posed_person`, `::test_feet_on_pedals`.
- Visual scenarios in `tools/visual_scenarios.json`, from real data via `tools/visual_test.py find`
  with public Helsinki-centre coordinates. Each one's readiness check fails when the feature is missing:
  `speed_bump_hop_helsinki` (drive 4 s over a hump, requires `airborne_frames` > 0),
  `slope_bodies_helsinki` (bus and tram on a grade, requires a body pitch of 0.08 rad),
  `cyclist_closeup_helsinki` (chase cam near riding bicycles, requires the rider part count >= person's and the riders large on screen).
- Full Python and Godot suites, with `XDG_DATA_HOME=$(mktemp -d)`.

## Questions (recommended default)
- Should the motorcycle and e-scooter riders use the person pose too? Default: yes, in commit 4a, with the same test.
- Should NPC cars hop over bumps? Default: no. NPCs slow down for bumps (traffic-law guide § cyclists/calming).

## Out of scope
Server-side bridge and deck heights. Changes to NPC speed choice beyond the 25 km/h cap over a surface bump (docs/finnish-npc-traffic-law.md).

## Implementation and measured results
- Bump hop model (`vertical.py`): a quarter-car per axle, the rear axle a wheelbase (0.6 x car length) after the front, closed
  form per (profile, speed, wheelbase), so airtime is the same at any frame rate (0.000 s spread, 30-720 Hz, jittered frames).
  A wheel leaves the road only when it drops away more than 6 cm of spring droop over the last 2 m; hops under 1 cm of lift are
  dropped. Per axle: bump 7 cm at 50 km/h 0.101 s / 2.2 cm; hump at 50 km/h 0.079 s / 2.3 cm, 60 0.124 s / 5.2 cm,
  70 0.158 s / 7.1 cm, 100 0.249 s / 11.6 cm, none at 20 or 40; cushion 50 0.073 s; table 70 0.111 s / 6.0 cm, none up to 60.
- Terrain: unchanged launch rule; 0 take-offs per km on 174.8 km of the real Oulu DEM at 14, 22, 28, 33, 50 and 58 m/s.
- The client keeps no vertical model: `EntityLayer.player_air` blends the server's `air_height`, and `land_bump` gives the squat.
- Slope scenario: bus pitch 0.163 rad and tram 0.186 rad on the grade; wheel-to-ground error 0.016 m (lineup, bound 0.025 m) and
  0.006 m (moving traffic, bound 0.03 m). The earlier 0.038-0.057 m traffic error came from bodies first seen easing up from
  level, and from the easing being per frame; it is now a time constant (0.058 s) and a new body stands at its slope at once.
  With 8 cm added to every non-lineup body the scenario fails (lineup 0.080 m, traffic 0.086 m).
- Rider close-ups (three-quarter views, nearest rider within 9 m and 170 px high): bicycle 185 px at 6.5 m, motorcycle 178 px at
  7.3 m, e-scooter 185 px at 6.5 m; 9360 rider vertices.
- Bump hop scenario: passes with the shot at the apex of a 3 cm hop (`capture_airborne_m` 0.02); the hop is a short, small lift, as specified.
- NPC cars cap at 25 km/h over a surface bump (`docs/finnish-npc-traffic-law.md`); they never hop.
- Tests: `make check` 3006 passed, 4 skipped (plus the 62 serial ones); `make godot-test` 47 passed, 0 failed; nothing deselected.
