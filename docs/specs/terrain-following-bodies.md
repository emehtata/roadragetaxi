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
| Pedestrians, walking player | `deck_height(at, ped.layer)` `entity_layer.gd:2167` | upright (correct) | OK if `layer` is sent; check walker row |
| Elves | `person()` with no elevation `:2169` | - | sink or float on DEM |
| Dogs | `animal()` with no elevation `:2173` | - | sink or float on DEM |
| Wildlife | `animal()` elevation = flight offset only `:2190` | - | ignores ground |

## Part 1: speed bumps (commits 1a server data, 1b client surface, 1c hop tune)
Files: `chunk_detail.gd:15` (profiles), `buildings_3d.gd` (bump mesh and `road_surface_height`),
`map_layer.gd:623` (pass the chunk's bumps), `vehicle_vertical.gd` (launch gap).
Profiles (h, L): bump 0.07 m / 0.6 m; hump 0.10 m / 3.7 m (sinusoidal); cushion 0.08 m / 2.5 m,
1.8 m wide; table 0.10 m with 1.2 m ramps and a flat top (total 2.2 + 2.4 m).
`static func bump_height(at: Vector2, bumps: Array) -> float`: the profile offset, added in `road_surface_height`.
1. The drawn bump mesh top and `deck_height` agree within 0.005 m at 9 points along each profile.
2. A hump at 50 km/h gives 0.05-0.3 s airtime with peak air height <= 0.25 m. At 20 km/h, airtime is 0.
3. A short "bump" at 50 km/h gives a pitch jolt (`land_bump` > 0.2) and at most 0.1 s airtime.
4. The existing VehicleVertical tests still pass: the 0.04 m seam and the bridge ramp at 40 m/s never launch.
5. Lookup cost: only the bumps of the chunk containing `at`.

## Part 2: bodies follow the ground (2a helper, 2b vehicles, 2c rail, 2d people/animals)
`EntityLayer.body_pose(c: Vector2, heading: float, length: float, width: float, layer: int, id) -> Vector3`
returns (height, pitch, roll). It reuses `wheel_tilt` and the `_tilts` easing (moved out of `:1036-1044`).
`vehicle()` gains `tilt := Vector2.ZERO` and passes it to `place_model_car`/`place_body`.
`rail_height` returns `ground_height + DECK_M on rail decks`. Elves, dogs and wildlife get
`deck_height(at, 0, false)` (flying animals add their offset to it).
6. On a 6 % DEM grade, a bus's pitch matches `atan(0.06)` within 0.01 rad. It is 0 on flat ground.
7. Along the scenario route, every drawn body's lowest wheel or foot is within 0.05 m of
   `deck_height` (trains: rail deck or ground).
8. Trains on a slope have nonzero pitch. Ferries sit at the drawn water surface within 0.1 m.
9. Tilt is computed only within 120 m of the camera, else 0. `perf` counter `pose_lookups` <= 4 x bodies per frame.

## Part 3: no air control (3a server vertical, 3b wire flag)
New `src/theroadragetrip/vertical.py`: a line-for-line port of `VehicleVertical` (same constants).
Ground = DEM bilinear (`dem.height_m`) + the same bump profiles. The server computes airborne itself
and doesn't trust the client, so it is cheat-safe for multiplayer. Layer != 0: never airborne. The
server has no deck data, and by the existing criteria ramps never launch.
In `physics.py:~1831`: while `car.airborne`, steer, throttle and brake are 0, the heading rate is 0
and only drag acts. Velocity keeps its take-off direction, so after landing the motion follows the arc.
`protocol` sends `airborne` in the player state for HUD and debug.
10. A shared fixture `tests/fixtures/vertical_profiles.json` (crest, hump, seam, ramp) gives the same
    airborne ticks in Python and GDScript (+-1 tick).
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
- `godot/tests/speed_bump_surface.gd::test_mesh_matches_deck_height`, `::test_hump_hop_fast`,
  `::test_hump_rolls_slow`. These fail now because `deck_height` is flat.
- `godot/tests/body_pose.gd::test_bus_pitch_on_grade`, `::test_train_on_dem`, `::test_animals_on_dem`.
- `tests/test_vertical.py::test_fixture_parity`, `::test_no_air_steer`, `::test_landing_follows_arc`.
- `godot/tests/cyclist_rider.gd::test_rider_is_posed_person`, `::test_feet_on_pedals`.
- Visual scenarios in `tools/visual_scenarios.json`, from real data via `tools/visual_test.py find`
  with public Helsinki-centre coordinates. Each one's readiness check fails when the feature is missing:
  `speed_bump_hop_helsinki` (drive 4 s over a hump, requires `airborne_frames` > 0),
  `slope_bodies_helsinki` (bus and tram on a grade, requires a nonzero body pitch),
  `cyclist_closeup_helsinki` (chase cam near an NPC bicycle, requires the rider part count >= person's).
- Full Python and Godot suites, with `XDG_DATA_HOME=$(mktemp -d)`.

## Questions (recommended default)
- Should the motorcycle and e-scooter riders use the person pose too? Default: yes, in commit 4a, with the same test.
- Should NPC cars hop over bumps? Default: no. NPCs slow down for bumps (traffic-law guide § cyclists/calming).

## Out of scope
Server-side bridge and deck heights. Changes to NPC speed choice.
