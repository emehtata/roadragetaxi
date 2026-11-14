# Spec: centralised collision detection (phased)

Source: docs/collision-detection.md. Progress log at the end; update it per phase.

## Goal
Make every solid-object collision on the Python server go through one category and filter
definition and shared narrow-phase helpers. Build on the checks that already work, without a second system.

## Audit findings (sections 1, 3)
| Pair | Where | Geometry / broad phase | Response | Notes |
|---|---|---|---|---|
| NPC vs NPC, NPC vs taxi, trailers | npc.py `_check_vehicle_collision` | OBB `geo.boxes_intersect`, swept (up to 12 samples); candidates from `nearby_vehicles_at` (SpatialWayGrid of vehicles) | impulse `collision_impulse`, scrape, stun, crash | filters `layer` and `map_level` inline |
| NPC pushed into building | npc.py ~5284 `is_vehicle_pose_valid` | building grid passed in per update | rejects the invalid pose | only on a knock, not while driving normally |
| Taxi vs building | taxi.py `check_building_collision` | OBB corners vs footprint; own 100 m `_building_collision_grid` | stop, penalty, cooldown | level-aware; roads crossing a footprint are exempt |
| Taxi vs fence / railing | taxi.py `check_fence_collision`, `check_barrier_collision` | own 100 m and 50 m grids | stop, penalty | surface level only |
| Taxi vs bollard / lamp post | taxi.py `check_post_collision` | circle `POST_RADIUS_M` vs box; `_post_grid` | stop, or knock the post down | `knocked_posts` sent to the client |
| Taxi vs tram | taxi.py `check_tram_collision`; trams.py `_overlaps` | boxes | stop | separate box code |
| Taxi vs bridge edge | physics.py `is_car_colliding_with_bridge_edge` | way geometry | pull back, bounce | |
| **Taxi vs tree** | **godot map_chunk.gd `knock_trees`** | client 10 m tree grid | tree falls, taxi goes on | **breaks the rule: collision on the client** |
| Taxi vs pedestrian / cyclist | pedestrian.py `check_player_avoidance` | loops over all pedestrians | pedestrian dodges | no solid contact; O(n) scan |
| Player on foot vs walls / cars | simulation.py `walk_blocked_by_walls`, `point_in_vehicle` | `_point_inside_building`, vehicles within 8 m | slides along | |
| NPC pedestrians vs buildings | pedestrian.py `_point_inside_building` and segment test | route-time check | | none between pedestrians (only ice_skating `collide`) |
| Animals | godot wildlife.gd | none | none | client decoration only |

Repeated code: there are 4 hand-made taxi grids (building, fence, barrier, post) next to SpatialWayGrid.
OBB-vs-polygon code is written separately in taxi, npc and trams. The layer and level check is
written inline in each place. Godot gets results only (`knocked_posts`, `crashed_timer`, `fallen`,
sound events), plus the tree knock-down that Godot computes itself.

## Category matrix (section 5)
Categories: VEHICLE (taxi, NPC, trailer, tram), PEDESTRIAN, ANIMAL (none yet), BUILDING, POST
(bollard, lamp, tree, traffic light), BARRIER (fence, railing, bridge edge), ROADWORKS, NONSOLID.
VEHICLE collides with all solid categories. PEDESTRIAN collides with VEHICLE, BUILDING and BARRIER.
Static categories never collide with each other. NONSOLID collides with nothing.
Both bodies must also share `layer` and `map_level`. A body with no level is a surface body.

## Reuse plan and architecture
- Keep `geo.boxes_intersect`, `box_contact_normal`, `point_in_polygon`, SpatialWayGrid and the NPC swept test and impulse code.
- New `src/theroadragetrip/collision.py`: the categories, `can_collide`, `same_plane`, and later shared narrow-phase helpers. Existing checks call into it; no new tick loop.
- Python is the authority. Godot draws state only. Grid queries stay bounded per tick.

## Migration risks
- Changing the taxi checks can alter crash penalties and the stuck-escape behaviour (taxi.py exemptions).
- Moving trees to the server needs the tree list on the server and a protocol field.
- The flaky NPC trip-cycle test (see memory) can hide regressions. Run it on fixed seeds.
- Swapping the hand-made grids can cost per-tick time. Benchmark with the PBF bench.

## Phase 1 (full): categories, filter, and test harness for scenarios 1 and 3
Files:
- `src/theroadragetrip/collision.py` (new): `class Category(IntFlag)`, `COLLIDES: dict[Category, Category]`,
  `def can_collide(a: Category, b: Category) -> bool`, `def same_plane(a, b) -> bool` (reads `layer` and `map_level`; a missing value counts as 0 / SURFACE_LEVEL).
- `src/theroadragetrip/npc.py` `_check_vehicle_collision`: swap the inline layer/level check for `same_plane(vehicle.car, other_car)`. Behaviour stays the same.
- `tests/test_collision_scenarios.py` (new): deterministic, explicit poses, no map load.
Acceptance:
1. `can_collide` is symmetric for every category pair, and the matrix above holds.
2. `same_plane` is False when `layer` or `map_level` differ, and True when both attributes are missing.
3. Scenario 1: two NPC vehicles drive head-on at 10 m/s, 20 m apart. After stepping `_check_vehicle_collision` at 30 Hz, their boxes never overlap more than one frame's travel, and both get stopped or flagged with a collision response.
4. Scenario 1b: the same setup, one map level apart, gets no collision response.
5. Scenario 3: taxi at 15 m/s drives at a square building footprint. `check_building_collision` returns True, and the taxi's final pose has no corner inside the footprint.
6. The whole suite passes (`pytest`), including test_level_collision.py and test_crash_physics.py.
Tests: test_matrix_symmetric, test_same_plane_levels, test_vehicles_head_on_resolve,
test_vehicles_other_level_pass, test_taxi_hits_building_stops. Without phase 1, the first two fail on import.
The scenario tests guard against regressions in the existing behaviour.

## Later phases (outline)
2. Shared OBB-vs-polygon and circle-vs-box helpers in collision.py. Taxi, npc and trams use them. Scenarios 3, 4, 14.
3. Move trees to the server: add trees to the taxi's post grid with the POST category, send `knocked_trees` in the protocol, and remove the collision from Godot `knock_trees` so Godot only draws it. Scenarios 4, 10.
4. One static-obstacle index over SpatialWayGrid (level-aware) to replace the 4 taxi grids. Benchmark it. Scenarios 9, 12.
5. Vehicle vs pedestrian contact through the vehicle grid, replacing the O(n) avoidance scan. Scenarios 5, 7, 8.
6. NPC vehicles collide with static obstacles while driving. Add swept substeps for the taxi. Scenarios 2, 10, 13, 15.
7. Collision counters in `performance.py`, and a dense-city benchmark. Scenarios 11, 15.

## Out of scope
Animals on the server (wildlife.gd is decoration), and roadworks geometry before phase 4. Collision shapes in Godot.

## Progress
- [x] Audit, matrix, spec (2026-11-14)
- [x] Phase 1 (2026-11-14): collision.py, npc.py uses `same_plane`, tests/test_collision_scenarios.py (5 tests); full suite green
