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

## Phase 2 (full): shared shape helpers
Goal: there is one OBB-vs-polygon, OBB-vs-polyline and post-vs-box test, in collision.py. The taxi and trams
call it instead of their own copies. Python stays the authority, and Godot gets no collision code.

Functions that move (into `src/theroadragetrip/collision.py`, pure functions with no state, built on `geo`):
- `def box_hits_polygon(corners: Sequence[Point], points: Sequence[Point], centre: Optional[Point] = None) -> bool`:
  True if `centre` or a box corner lies inside the closed `points`, or a polygon vertex lies inside the box,
  or any box edge crosses any polygon edge. The edge loop skips polygon edges outside the box's AABB (an exact
  prefilter, taken from taxi.py building). It replaces:
  taxi.py `check_building_collision` (lines ~723-733), `check_fence_collision` (~896-903),
  `_backing_off` `touching` (~806), and trams.py `_overlaps` (it becomes a loop of `box_hits_polygon` over the box pairs; delete `_overlaps`).
- `def box_hits_polyline(corners: Sequence[Point], points: Sequence[Point]) -> bool`: an open line, so the
  last-to-first edge is not checked. True if a line vertex is inside the box or a line segment crosses a box edge.
  It replaces taxi.py `check_barrier_collision` `hit` (~1008-1012).
- `def post_box_depth(px, py, radius, x, y, heading, length, width) -> float`: the penetration depth
  `min(L/2+r-|along|, W/2+r-|across|)`. A value above 0 means contact. It is the same expanded box as now, not a true
  rounded rectangle. It replaces both the inline test and the "previous pose" depth in `check_post_collision` (~1094-1108).
  Phase 3 uses it for trees.
Not moved: npc.py `_check_vehicle_collision` already uses `geo.boxes_intersect`, which is shared (phase 1),
and `is_vehicle_pose_valid` uses clearance-distance semantics (curb margin). Both stay as they are. NPC-vs-static moves in phase 6.
Broad phase, grids, cooldowns, penalties, exemptions and responses stay where they are. Only the narrow-phase predicate moves.

Behaviour that must stay identical (the current tests must pass without being edited):
tests/test_post_collisions.py (all 5, including the existing-overlap reverse and push-in cases), tests/test_barrier_collision.py
(all 10), tests/test_level_collision.py, tests/test_crash_physics.py, tests/test_scenery_and_buildings.py,
tests/test_map_chunks.py, the tram tests that call `TramManager.hits` / footprint overlap, and tests/test_collision_scenarios.py (phase 1).
Deliberate change (the only one): building and fence checks now also hit when a small polygon lies wholly under the
car with no corner inside it and no edge crossing (before, it was caught only if it held the centre). Trams already did this.

Acceptance:
1. collision.py exports the three helpers. `grep -n "point_in_polygon\|segments_intersect" taxi.py trams.py` shows no
   narrow-phase box test left. The only remaining uses are `_road_overlaps_building`, `_backing_off` `clearance`, and sweep segments.
2. Unit tests: `box_hits_polygon` is True for corner-in, vertex-in (small polygon inside the box), X-crossing (no
   vertex inside either), and centre-in. It is False for disjoint shapes and for a polygon outside the box AABB. `box_hits_polyline` does not
   close the line (a U-shaped line around the box with its open end at the box does not hit).
3. `post_box_depth` matches the old inline formula on 20 seeded random poses (abs diff < 1e-9).
4. Scenario 4: taxi at 8 m/s (below POST_KNOCK_DOWN_KMH) drives at a pole. `check_post_collision` returns True, speed is 0,
   and `post_box_depth` at the final pose is <= the depth at first contact. At 15 m/s the post is knocked (`knocked_angle` set) and the taxi keeps going.
5. Scenario 14: a taxi placed overlapping a building (one corner 0.3 m inside) and a pole (depth 0.1). Driving away is
   allowed (pose not reset, no new penalty after the first). Driving deeper is reset to the previous pose.
6. Scenario 3 is unchanged (test_taxi_hits_building_stops), and the full `pytest` suite is green with nothing deselected.
7. PBF bench at 69 m/s: taxi collision tick time is within 5% of the phase 1 time.

Tests to add in tests/test_collision_scenarios.py (no map load, explicit poses):
- test_box_hits_polygon_cases, test_box_hits_polyline_is_open. Without phase 2: ImportError. The vertex-in case fails on the old building code.
- test_post_box_depth_matches_old_formula (it fails on import).
- test_taxi_hits_pole_stops_or_knocks (scenario 4). It guards existing behaviour.
- test_initial_overlap_building_drive_out, test_initial_overlap_pole_drive_out (scenario 14). They guard the
  `_backing_off` / post "already touching" rule through the new helpers.

Out of scope: trees on the server (phase 3), merging the taxi grids (phase 4), NPC static collision (phase 6), and Godot changes.

## Phase 3 (full): trees on the server
Goal: the server decides which trees the taxi fells and sends them to Godot. Godot only draws fallen trees and plays the sound.
Godot has no tree hit test left. Covers scenarios 4 (vehicle hits a tree) and 10 (fast vehicle, small obstacle).

Tree data: the surveyed `natural=tree` points that `osm/trees.py plant_trees` attaches to each scenery
(`scenery.trees`, `scenery.tree_kinds`, after `remove_trees_under_roads` in world_loader.py). These are the same points that
map_chunks.py sends as chunk `trees`, so server and client keys match (`round(x, 1), round(y, 1)`). No new data source, so no licence change.

Files:
- `src/theroadragetrip/taxi.py`: new `TREE_RADIUS_M = 0.4` (Godot `TRUNK_RADIUS_M`). Add a `class FelledTree` record (`x, y, kind="tree",
  knocked_angle=None`). The post grid also indexes trees: `_nearby_posts(objects, x, y, sceneries=())` adds each scenery's
  new trees to the same 20 m `_post_grid`. Index them on append, the same way as posts. They are surface only (level SURFACE, layer 0) and
  category `Category.POST`. A new `def check_tree_collision(self, player_car, sceneries, sim_time) -> int` returns the number felled
  this tick. It uses `post_box_depth(..., TREE_RADIUS_M, ...) >= 0` and sets `knocked_angle` to the taxi heading (reversed when reversing).
  It never stops the taxi, takes no score, no happiness and no penalty, the same as today. It adds the tree to `self.felled_trees` (a list, only ever grows).
- `src/theroadragetrip/simulation.py` collisions section: if `on_surface`, call `check_tree_collision`. If it returns >0, play
  `audio.play_group("collision.tree")` and `("collision.tree_fall")` at the car. Replace the "Trees: the client's alone" comment.
- `src/theroadragetrip/protocol.py`: `_knocked_trees(world_or_taxi, x, y) -> list` returns `[x, y, angle]` within the same radius as
  `_knocked`. The state field is `"knocked_trees"`. Bump `PROTOCOL_VERSION` to 2, because an old client would still fell trees on its own.
- `godot/main.gd`: delete the `knock_trees(body)` call and its two sound events (the server sends the sound now, like `post_knock`).
  Call `map_layer.set_knocked_trees(state.get("knocked_trees", []))`.
- `godot/map_layer.gd`: `func set_knocked_trees(trees: Array) -> void` skips the call if the array has not changed. Otherwise it pushes the
  `obstacle_key -> angle` dict to each chunk. Delete `knock_trees`.
- `godot/map_chunk.gd`: delete `knock_trees`, `_tree_grid` and `TREE_CELL_M`. `func set_fallen(fallen: Dictionary) -> void` replaces
  `_fallen` and redraws `_trees` when it changes. The drawing at ~1689 stays the same. Do the same in any 3D tree view that reads `_fallen`.
- Godot protocol version constant (where it checks `version`): set it to 2.

Must stay identical: a tree falls the way the taxi was heading and its tip is drawn 3.2 m away. The taxi keeps its speed. The sounds are
`collision.tree` then `collision.tree_fall`, once per felling tick. No score, no penalty. Behaviour kept as today: a fallen tree stands up again when its chunk
reloads. The server keeps felled trees only while their chunk is loaded (decided while the user was offline, to preserve existing gameplay).

Acceptance:
1. `grep -n "knock_trees\|_tree_grid" godot/` finds nothing. Godot has no tree distance test.
2. Scenario 4 (tree): a taxi at 8 m/s and at 20 m/s drives at a tree 10 m ahead. Within 2 s the tree has `knocked_angle` equal to the
   heading, the speed is unchanged (abs diff < 1e-6 from the physics without the tree), and `total_score` is unchanged.
3. A taxi passing 0.5 m beyond the reach (`width/2 + 0.4 + 0.5` from the centreline) fells nothing.
4. Scenario 10: at 69 m/s at 30 Hz (2.3 m per tick) a tree on the path is felled (no tunnelling at this speed, because the 4.5 m box > step).
5. Deterministic: the same seed and the same world give the same felled list in the same order across two runs. The tree grid holds each tree once.
6. A map level other than the surface, or `on_surface` False, fells nothing.
7. State has `knocked_trees` only near the player. A message with version 1 is rejected.
8. Visual: the named scenario `tree-knocked-topdown` (real map data, a park street with mapped `natural=tree` near
   the city centre; it uses `--screenshot-drive` to drive the taxi through a tree) passes its readiness checks. The screenshot shows the fallen
   trunk drawn from the server state. Inspect it.
9. Full `pytest` and the Godot tests are green, nothing deselected. PBF bench at 69 m/s: collision tick within 5% of phase 2.

Tests (tests/test_collision_scenarios.py, no map load, explicit poses and a stub scenery with `trees`):
- test_taxi_fells_tree_keeps_speed (scenario 4). It fails because `check_tree_collision` does not exist.
- test_tree_miss_beyond_reach, test_tree_fast_no_tunnel (scenario 10), test_tree_off_surface_ignored.
- test_tree_felling_deterministic: two identical runs give equal `felled_trees` lists. Each tree is indexed once after the sceneries grow.
- tests/test_protocol*.py: test_state_has_knocked_trees_near_player, test_protocol_v1_rejected.
- tools/visual_scenarios.json: add `tree-knocked-topdown`.

Out of scope: NPC vehicles felling trees (phase 6), trees in the shared static index (phase 4), and tree collision for the player on foot.

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
- [x] Phase 2 (2026-11-14): `box_hits_polygon`, `box_hits_polyline`, `post_box_depth` in collision.py; taxi.py and trams.py use them (`_overlaps` deleted); 6 new tests; full suite green; bench_map_jitter.py times the taxi checks
