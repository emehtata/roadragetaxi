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

## Phase 4 (full): one static-obstacle index
Goal: one level-aware static-obstacle index, built on SpatialWayGrid, replaces the taxi's 4 hand-made grids
(`_building_collision_grid`, `_fence_collision_grid`, `_barrier_grid`, `_post_grid`). Streamed tiles add and remove entries
without a full rebuild. Covers scenarios 9 (objects approaching from different chunks) and 12 (objects entering and leaving streamed chunks).

Current state (what this replaces): each grid keeps its own `_ref`/`_count`, indexes the appended tail, and clears itself
completely when the list is replaced or shrinks. That happens on every `autofetch._unload_tiles` (it filters every `_WORLD_SECTIONS` list),
so one unloaded tile rebuilds all four grids on the next tick. The cell sizes are 100/100/50/20 m. `stand_trees_in` (client chunk unload)
only resets felled trees and is not touched.

Files:
- `src/theroadragetrip/physics.py` `SpatialWayGrid`: add `def remove(self, item) -> None`. It removes the item from the cells its stored bbox
  covers, without a scan of the whole grid. `insert` records the insertion order for every insert, not only in `rebuild`, so the
  `ways_in_rect` order stays stable as items stream in. No other behaviour changes; the existing road grids stay byte-identical.
- `src/theroadragetrip/collision.py`: `class StaticObstacleIndex` (the only static index; no second spatial structure):
  - `__init__(self, cell_size: float = 50.0)` wraps one `SpatialWayGrid(cell_size, map_level=None)`.
  - An entry is a `StaticEntry(obj, category: Category, layer: int, level, bbox)` with `__slots__`. `level` comes from the object's map level
    (trees and posts: SURFACE_LEVEL), `layer` from `getattr(obj, "layer", 0)`, and `bbox` is set once at insert. The grid holds entries, not raw objects.
  - `def sync(self, source: str, items: list, category: Category, accept=None, expand=None) -> None` handles the source lists
    "buildings", "sceneries" (fences), "railings", "scenery_objects" (posts) and "sceneries.trees" (FelledTree via `expand`).
    The same list with more items indexes only the new tail. `forget(section, removed)` (amended 2026-11-15): autofetch's
    `_unload_tiles` hands the unloaded objects to its `unload_listeners` (world_loader registers the taxi's index), so the entries
    leave queries at once at a cost proportional to what was removed, and the next sync of the in-place filtered list takes the tail path.
    Otherwise a replaced or shrunk list does an id-set diff: it removes the entries that are gone
    and adds the new ones. Survivors keep their entry and their FelledTree identity, so `felled_trees` stays valid.
  - `def query(self, x, y, radius, categories: Category, level=None, layer=None) -> list[obj]` returns unique objects in a stable order
    (source insertion order, the same as the old grids' cell scan for single-cell hits), filtered by category, and by `on_map_level` and `layer` when given.
- `src/theroadragetrip/taxi.py`: delete the 4 grids, their `_ref`/`_count` fields and `_collision_cells`. Add `self.static_index`.
  `_nearby_collision_buildings`, `_nearby_collision_fences`, `_nearby_barriers` and `_nearby_posts` keep their signatures
  (protocol.py:438 calls `_nearby_barriers`) and become `sync(...)` + `query(...)`. Their accept rules stay the same
  (OPEN_ROOF_BUILDING_TYPES skipped, SOLID_AREA_KINDS, POST_KINDS). `check_*` bodies do not change.
- `tools/bench_map_jitter.py`: add `--compare-index` output fields `static_index_ms` (`build`, `update`, `query`), timed around `sync` and `query`.

Must stay identical: every `check_*_collision` return value, its penalty, cooldown, stop, the knocked post and felled tree, and the road-overlap
exemption, for the same inputs. Existing tests pass **unedited** (test_level_collision.py, test_crash_physics.py, test_collision_scenarios.py, protocol tests).
Server authoritative and nothing new is sent to Godot. Map-layer separation: buildings stay level-filtered, and posts and trees stay surface only.

Acceptance:
1. `grep -n "_collision_grid\|_barrier_grid\|_post_grid" src/` finds nothing except read-only accessors kept for existing tests
   (amended 2026-11-15: `TaxiManager._post_grid`, a property over the index that the unedited test_tree_felling_deterministic reads;
   it holds no grid of its own). `StaticObstacleIndex` is the only static obstacle grid in taxi.py.
2. Scenario 9: a building, a fence, a railing and a bollard each straddle a chunk boundary (`CHUNK_SIZE_M`), and the taxi approaches from the other chunk
   at 15 m/s. Each check reports the hit on the same tick as with the phase 3 grids (recorded in the test as the expected tick).
3. Scenario 12: after `sync` with a shrunk list (one tile's objects removed), a query at the removed spot returns nothing and the taxi passes through
   with no collision. After they are added back, it collides again. The other entries are never re-inserted (`SpatialWayGrid.insert` call count == new items only).
4. A level -1 building and a layer 1 railing are not returned for a surface, layer 0 query.
5. Felled trees survive an unrelated tile unload (same object, `knocked_angle` kept).
6. Bench budget (PBF bench at 69 m/s, the phase 3 drive): the static index work (`sync` + `query`, all four checks) is <= 0.30 ms per tick at p50
   and <= 1.0 ms at p99, and a tile-unload tick's `sync` is <= 2.0 ms. Ratio: the `collisions_section` mean is <= 1.05x phase 3, judged on the median of
   **7 interleaved runs** (A/B/A/B on the same machine, phase 3 from a temporary worktree, the first pair discarded as warm-up). If the 95% interval of the
   ratio over the 7 pairs is wider than +-5%, the absolute budget decides; record both numbers in Progress.
7. Full `pytest` and the Godot tests are green, nothing deselected.

Tests:
- tests/test_collision_scenarios.py: test_static_index_cross_chunk_approach (scenario 9; fails without a cross-chunk entry if bboxes are not spread over cells),
  test_static_index_unload_and_reload (scenario 12; fails today because a shrink clears and rebuilds the whole grid, the insert count),
  test_static_index_level_and_layer_filter, test_felled_tree_survives_tile_unload (fails today: a new scenery list drops and re-creates the trees).
- tests/test_spatial_way_grid*.py (or the existing physics test): test_remove_drops_item_from_all_cells, test_insert_order_stable_without_rebuild.
- Bench: `tools/bench_map_jitter.py --compare-index`, run as in acceptance 6.

Out of scope: NPC vehicles and pedestrians querying the index (phases 5, 6), the vehicle grid (dynamic, it stays as it is), roadworks and
bridge edges in the index, and the client-side chunk streaming.

## Phase 5 (full): vehicle and pedestrian contact through the vehicle grid
Goal: the taxi finds pedestrians and cyclists through a per-tick dynamic SpatialWayGrid (the same pattern as the NPC
vehicle grid) instead of `check_player_avoidance` looping over every pedestrian. Add pedestrian-vs-pedestrian and
pedestrian-vs-building contact. Covers scenarios 5, 7 and 8 of section 10. Today's dodge, curse and cyclist-hit results stay identical.

Current state: pedestrian.py:2715 `check_player_avoidance` loops over all `self.pedestrians`. In that loop it also ticks
`curse_timer`/`dodge_timer` and applies the dodge velocity. Pedestrians have no grid. NPC vehicles use `NPCManager.spatial_grid`
(`rebuild_spatial_grid` refreshes the point bbox, then `nearby_vehicles_at`). The pedestrian `_building_grid` is a venue-built dict grid.

Files:
- `src/theroadragetrip/pedestrian.py` `PedestrianManager`:
  - `self.spatial_grid = SpatialWayGrid(10.0, map_level=None)` and `def rebuild_spatial_grid(self) -> None`. It works like
    `NPCManager.rebuild_spatial_grid`: refresh `ped.bbox`, then one `rebuild`. It runs once per `update`, after the despawn filter and
    before avoidance. That is O(n) inserts and no per-pair work. It is the only pedestrian grid. Do not add a new class.
  - `def nearby_pedestrians_at(self, x, y, radius_m) -> list` returns `spatial_grid.ways_in_rect(...)` (stable order).
  - Split `check_player_avoidance`. Timer and dodge-motion ticking stays a plain loop. The taxi trigger test runs only on
    `nearby_pedestrians_at(car.x, car.y, AVOID_QUERY_M)`. `AVOID_QUERY_M = 3.5 + car half-length + 1.0` covers the 3.5 m ahead and 1.25 m touch rules.
    The thresholds, dodge vector, speed 3.5, timer 0.4, curse rule and the `cyclist_collision` return do not change.
  - `def _separate_pedestrians(self, dt) -> None` (scenario 7): each walking pedestrian queries `nearby_pedestrians_at(x, y, 2 * radius_m)`.
    Pairs whose circles overlap (`radius_m`, default 0.45) are pushed apart by half the overlap each, along the centre line.
    Only pairs with `can_collide(PEDESTRIAN, PEDESTRIAN)` are handled. The matrix gets PEDESTRIAN|PEDESTRIAN, and the phase 1 matrix test is
    updated (amendment: crowds stop walking through each other). Pairs must also pass `same_plane`. Skip pedestrians that are held, seated or in
    an activity (ice_skating keeps its own `collide`). Each pair is handled once (lower id first).
  - Scenario 8: the push and dodge steps are rejected when the new point is inside a building. Use `static_index.query(x, y, radius_m, BUILDING, level=ped level)`
    plus `point_in_polygon` from the phase 2 helpers. In that case the pedestrian stays put, and dodges slide along the other axis if that axis is free.
    `static_index` is the taxi's `StaticObstacleIndex`, handed in by world_loader (a reference, not a second index). With no index, fall back to `_point_inside_building`.
- `src/theroadragetrip/collision.py`: add `def circle_hits_circle(ax, ay, ar, bx, by, br) -> float` (overlap depth, 0 when apart). Taxi contact stays
  the existing trigger, so `post_box_depth` is not needed here.
- `tools/bench_map_jitter.py`: report `ped_internal` `pedestrians:grid`, `pedestrians:avoidance` and `pedestrians:separation` (they already go through `_record`).

Must stay identical: for the same pedestrians and car, every pedestrian's dodge_vx/vy, dodge_timer, curse_timer and `curses` entries, and the return value,
for pedestrians more than 2 * radius from any other pedestrian (separation only touches overlapping pairs). Existing tests in
tests/test_pedestrians.py (dodge, curse, cyclist) and test_cyclists.py pass unedited. Nothing new is sent to Godot. Python stays authoritative.

Acceptance:
1. `check_player_avoidance` reads `self.pedestrians` only for timer ticking. The trigger test runs on grid candidates (asserted by a spy: with 500 far pedestrians, 0 trigger evaluations).
2. Scenario 5: a taxi at 10 m/s heads at a pedestrian 20 m ahead. The dodge starts on the same tick as before (the expected tick is recorded), the pedestrian ends outside the taxi's box,
   and the curse is logged once. A pedestrian one map level below gets no dodge.
3. Scenario 7: two pedestrians walk head-on along one line at 1.4 m/s. Their centres never come closer than `2 * radius_m - 0.05` m, and both reach their targets.
4. Scenario 8: a pedestrian dodging or being pushed toward a square footprint never has its centre inside it, with or without the index.
5. Budget (PBF bench at 69 m/s, the phase 4 drive, about 300 pedestrians): grid + avoidance + separation <= 0.40 ms per tick at p50 and <= 1.2 ms at p99.
   Interleaved A/B against phase 4 (7 runs, first pair discarded) is reported as a check only. The absolute budget decides. Record both in Progress.
6. Full `pytest` and the Godot tests are green, nothing deselected.

Tests (tests/test_collision_scenarios.py, placed poses, fixed seed, no map load):
- test_taxi_avoidance_uses_pedestrian_grid (fails today: the spy counts every pedestrian)
- test_scenario5_taxi_approaches_pedestrian, test_scenario5_other_level_no_dodge
- test_scenario7_pedestrians_cross_without_overlap (fails today: their centres pass through each other)
- test_scenario8_pedestrian_dodge_stops_at_wall (fails today: the dodge velocity moves the pedestrian into the footprint)
- test_avoidance_identical_to_scan: 50 random pedestrians, fixed seed; the grid path's results equal a reference copy of the old loop.

Amendments (2026-11-15, after implementation):
- Dodge direction, a deliberate bug fix. HEAD built the taxi's forward vector as `(cos h, -sin h)`, but the car moves along `(cos h, sin h)`
  (physics.py). At diagonal headings HEAD therefore dodged the wrong pedestrians, for example one 21 m away at 0.79 rad. The fix uses `(cos h, sin h)`.
  The only equivalence with HEAD is at headings 0 and pi, where both vectors agree. The reference copy of the old loop in
  test_avoidance_identical_to_scan uses the fixed vector, so "identical" there means identical to the old loop with the fix.
- Sideways step, the chosen behaviour. Every overlapping pair, not only head-on pairs, gets a sideways step as large as its push along the centre line,
  so each walker moves about 0.7 x the overlap: half the overlap along the line plus the same amount sideways. Without it, walkers meeting head-on on one line stall.
  The code keeps the `ponytail:` comment on this step.
- Separation sorts the separable walkers by x (one C sort of current positions) and sweeps: each walker meets only those within 2 x radius in x and y. No grid query per walker and no second spatial structure; the grid serves the taxi trigger. `rebuild_spatial_grid` fills the SpatialWayGrid's cells directly (point items, no padding, one cell each) with the same cells and insertion order as `rebuild`.
- Map layers (section 8). A walker's layer is its way's `layer` (`ped.way.layer`, missing = 0), and its level is `map_level`. The taxi trigger runs only when the
  car's `layer` and `map_level` both match the walker's. Separation pairs only walkers on the same layer and level. A walker under a bridge deck is not dodged or pushed
  by a taxi on the deck, and the reverse. Tests: test_taxi_dodge_respects_way_layer, test_separation_only_on_one_layer.
- Acceptance 5, measured after the layer filter and the allocation cuts. The PBF bench (finland-latest, 69 m/s, 120 s, 5 runs) carries 129-151 pedestrians, not 300.
  Budget 0.40 ms p50 and 1.2 ms p99. Per-tick p50 0.040-0.043 ms; p99 0.272, 0.288, 0.213, 0.231, 0.246 ms (median 0.246, worst 0.288): pass with margin.
  Earlier p99 spikes (1.0-1.25 ms in tester runs; grid p99 0.84, separation p99 0.81) came from the generic SpatialWayGrid insert per walker and the
  per-walker cell-neighbour scan with list slices, which allocated O(n) objects per tick and stretched under GC and GIL waits from the background map threads;
  Python GC alone added about 0.07 ms p99 in a microbench. Isolated per-tick maxima (0.8-3.6 ms) are single ticks below the p99 and are GIL waits.
  Dense-crowd ceiling, a separate accepted limit: 300 dense walkers (synthetic, 150 x 120 m) take about 0.29 ms p50, 0.37 ms p99 per tick, and that is accepted.
  The interleaved A/B against phase 4 was not run (a report-only check).

Out of scope: NPC vehicles vs pedestrians (phase 6), merging the venue `_building_grid` (density and route uses) into the index, solid hit penalties for pedestrians, animals.

## Phase 6 (full): NPC static collisions and swept taxi steps
Goal: driving NPC vehicles never enter buildings, posts, trees or barriers, and the taxi cannot tunnel through a thin obstacle
when one tick moves it far. Covers scenarios 2, 10, 13 and 15 of section 10. One index (the phase 4 `StaticObstacleIndex`), no new tick loop.

Current state: a driving NPC checks curbs and buildings only through `is_vehicle_pose_valid` every `NPC_FOOTPRINT_CHECK_INTERVAL_S` (0.2 s), with
clearance semantics, and only to gate arrival (`footprint_clear`). Posts, trees, fences and railings are ignored. A knocked NPC (`update_knocked`)
stops at buildings only. Far NPCs step `FAR_TRAFFIC_STEP` x dt (4 x 33 ms). Taxi: one `update_car_physics` move per tick, then `check_*_collision` at the end
pose against `previous_position`. At 30 Hz and 69 m/s the step is 2.3 m, shorter than the taxi (4.0 m), so a steady drive does not tunnel. It does tunnel when
a tick's dt stretches (a 130 ms chunk-build stall at 69 m/s is a 9 m step) or when the car slides sideways (step > width + 2 x `POST_RADIUS_M`).

Files:
- `src/theroadragetrip/collision.py`:
  - `def sweep_samples(travel_m: float, turn_rad: float, length_m: float, width_m: float) -> int`: `ceil((travel + |turn| x length/2) / (width/2))`,
    min 1, max `SWEEP_MAX_SAMPLES = 16`. The width/2 spacing (0.9 m for the taxi) cannot skip a post (0.3 m) or a polyline in any direction. 2.3 m gives 3; a 9 m stall step gives 10.
  - `def first_static_hit(index, prev_pose, pose, length_m, width_m, categories, level, layer) -> tuple[int, obj] | None`: one `query` around the
    swept segment's midpoint (radius travel/2 + half diagonal + post radius), then tests the interpolated poses 1..n in order with `box_hits_polygon`,
    `box_hits_polyline` and `post_box_depth`. It returns the first sample that hits and the object. Candidates already touched at `prev_pose` count only when depth grows (phase 2 rule).
- `src/theroadragetrip/taxi.py` / `simulation.py` collisions section: before the `check_*` calls, run `first_static_hit` for BUILDING|BARRIER|POST on surface
  (BUILDING only off surface). On a hit at sample k, move the car to sample k (the time-of-impact pose) and run the existing `check_*` calls there, so their stop,
  penalty, cooldown, knock-down, felling and road-overlap exemption are unchanged. n == 1 is today's code path exactly. Trees still never stop the taxi.
- `src/theroadragetrip/npc.py`:
  - `NPCManager.static_index` (a reference, set in world_loader next to `pedestrian_mgr.static_index`; None keeps today's behaviour).
  - In the post-physics collision phase (`update` ~7266), for each active vehicle that moved and is not knocked: `first_static_hit(...)` with BUILDING|BARRIER|POST,
    the vehicle's `layer` and `map_level`. Posts and trees are surface only. Uses the same `previous_poses`, so far vehicles' 4 x steps are swept too.
  - Response (`def _resolve_static_hit(vehicle, driver, sample_pose)`): place the vehicle at the last free sample (k-1, else previous pose), speed 0. No impulse:
    static objects stay put, and an NPC never knocks a post or fells a tree (game policy: NPC travel stays on the carriageway, so a hit is a fault, not gameplay).
    The driver gets `target_speed_mps = 0`, `debug_waiting_for = "static obstacle"`, `recovery_stage = "STUCK"`, the same path as `_enforce_npc_road_motion`
    (manoeuvre, reroute, then the 2026-10-15 jam cleanup). That cleanup is what rules out a permanent stuck state.
  - Anti-oscillation: motion that reduces depth is always allowed (an NPC spawned or knocked into overlap drives out). A hit counter per vehicle: 3 hits within
    2 s without `NPC_RECOVERY_PROGRESS_M` of progress skip straight to reroute, no stop-start loop. No push-out for driving NPCs (it would move them off the road).
  - `update_knocked`: replace the building-only `is_vehicle_pose_valid` with `first_static_hit` on the slide step when the index exists (a slide stops at posts and fences too).
- `tools/bench_map_jitter.py`: fields `npc_static_ms`, `taxi_sweep_ms` and `taxi_sweep_samples` (p50 / p99 / max).

Traffic law (docs/finnish-npc-traffic-law.md): § 3-5 "priority never authorizes a collision"; the off-road game policy (recovery may not bypass barriers or leave the
carriageway); "a legal wait must not trigger stuck recovery": the static check never runs for a stationary vehicle, so a red-light or queue wait gets no hit.
All decisions stay in npc.py on the server; nothing new is sent to Godot.

Acceptance:
1. Scenario 2: two NPCs meet at a 4-way junction at 12 m/s, perpendicular. The phase 1 vehicle response fires; the knocked slide then stops before a building
   corner and a bollard placed in its slide path (no corner inside, post depth < 0 at rest). Neither gets stuck: within 20 s both have a route or are cleaned up.
2. Scenario 10: taxi at 69 m/s, with dt 1/30 and with one dt of 0.13 s, at a bollard (r 0.15), a fence polyline and a tree. Each is hit (stop, or knock / fell as today);
   with phase 5 code the 0.13 s case passes through. Sideways slide at 20 m/s past a bollard: hit. An NPC at the far-LOD step at 25 m/s is stopped before a bollard.
3. Scenario 13: in one tick the taxi touches a post and an NPC, and that NPC is shoved toward a building. Each response fires once (one post penalty, one vehicle
   impulse); the NPC ends outside the building; results are identical across two runs.
4. Scenario 15: 150 NPCs on a placed 300 x 300 m grid of streets with buildings, 200 posts and fences along the kerbs, 60 s at 30 Hz, fixed seed. No NPC corner is ever
   inside a building, no post depth > 0 after a resolution, no vehicle oscillates (no more than 3 static hits per vehicle per 10 s).
5. Unchanged: with nothing within reach, NPC poses equal phase 5 bit for bit; taxi results for n == 1 equal phase 5. Existing tests pass unedited.
   The flaky trip-cycle test: run 25 seeds alone, before and after; the pass count must not drop (report both counts in Progress).
6. Budget (PBF bench, 69 m/s, 120 s, the phase 4/5 drive, recorded traffic population): `npc_static_ms` <= 0.50 ms p50 and <= 1.5 ms p99 per tick; `taxi_sweep_ms` <= 0.10 ms p50 and
   <= 0.40 ms p99; total collision section stays under 3.0 ms p99. Cost model: taxi 3 samples x a handful of candidates per tick; NPC one query + about
   1-2 samples per moved vehicle. Bench rules from phases 4/5: 5 runs, report each p50/p99 and the median; interleaved A/B vs phase 5 (7 runs, first pair discarded) is report-only; the absolute budget decides.
7. Full `pytest` and the Godot tests are green, nothing deselected.

Tests (tests/test_collision_scenarios.py, placed poses, fixed seed, no map load):
- test_sweep_samples_counts (1 at 0.5 m, 3 at 2.3 m, 10 at 9 m, capped at 16): fails on import today.
- test_scenario2_junction_crash_slide_stops_at_static (fails today: the slide passes the bollard).
- test_scenario10_taxi_stall_step_hits_bollard, test_scenario10_taxi_sideways_hits_bollard, test_scenario10_far_npc_stops_at_bollard (fail today: tunnelling / NPCs ignore posts).
- test_scenario13_simultaneous_post_vehicle_building (determinism and one response each).
- test_scenario15_dense_traffic_no_static_overlap (fails today: NPCs drift into kerbside posts and fences).
- test_npc_drives_out_of_initial_overlap, test_npc_static_hit_no_oscillation (repeated hits go to reroute, not stop-start).

Out of scope: NPCs knocking posts or felling trees, pedestrians vs NPC vehicles (unchanged), roadworks and bridge edges in the index,
taxi vs NPC sweeping (already swept in `_check_vehicle_collision`), collision counters (phase 7), Godot changes.

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
- [x] Phase 4 (2026-11-15): `StaticObstacleIndex` in collision.py over `SpatialWayGrid` (`remove`, insert order); taxi.py's 4 grids gone; autofetch hands unloaded objects to `StaticObstacleIndex.forget` (`unload_listeners`, registered in world_loader); 8 new tests; full suite green (3003 passed, 3 skipped). Bench (Oulu, Overpass cache, no local PBF here, 69 m/s, 120 s, 3 runs, `--compare-index`): static index p50 0.033 ms, p99 0.83-0.92 ms per tick (pass); unload 1.35-1.47 ms per unload tick, 0.93-1.00 ms per call, no id-set diffs (pass, budget 2.0). collisions_section vs phase 3 after `forget`: median ratio 1.016, 95% interval +-6.3% (wider than the +-5% target, so the absolute budgets decide; they pass: static index p50 0.033 ms, p99 ~0.9 ms; unload tick <= 1.51 ms; forget <= 0.95 ms per call).
- [x] Phase 5 (2026-11-15): `PedestrianManager.spatial_grid` (10 m SpatialWayGrid, rebuilt once per update), `nearby_pedestrians_at`, avoidance trigger on grid candidates only, `_separate_pedestrians` (x-sorted sweep: each walker meets only those within 2 x radius in x and y, no grid query; the grid serves the taxi trigger only; half the overlap each plus an equal sidestep so head-on walkers pass), dodges and pushes rejected inside buildings (the taxi's `StaticObstacleIndex`, else `_point_inside_building`), `circle_hits_circle`, matrix PEDESTRIAN|PEDESTRIAN; 7 new tests, phase 1 matrix test amended; full suite green (3009 passed, 3 skipped), Godot tests 26/26. Fixed on the way: the avoidance forward vector was `(cos, -sin)` (skewed off the car's real `(cos, sin)` forward, triggering up to ~20 m away at diagonal headings; identical at 0 and pi); the taxi trigger also requires the same `map_level`. Bench (PBF finland-latest, 69 m/s, 120 s, ~129 pedestrians): grid + avoidance + separation p50 0.051 ms, p99 0.455 ms (pass, budget 0.40 / 1.2); Oulu Overpass cache runs before the separation rewrite: p50 0.07-0.10, p99 0.90-0.99. Synthetic 300 dense pedestrians: ~0.76 ms p50 (grid rebuild 0.28 + separation 0.42). Interleaved A/B vs phase 4 not run. After the layer filter (amendments): 3011 passed, 3 skipped; Godot 26/26; PBF rerun p50 0.064 ms, p99 0.879 ms, ~143 pedestrians. After the allocation cuts: 5 PBF runs, grid + avoidance + separation p50 0.040-0.043 ms, p99 0.213-0.288 ms (median 0.246 ms); tester's Oulu run p99 0.265 ms (pass, budget 0.40 / 1.2 ms).
- [x] Phase 6 (2026-11-15): `sweep_samples`, `sweep_pose`, `first_static_hit` in collision.py (walls and lines outside at the previous pose are tested by their edges inside the swept square only: a big outline is scanned once, not per sample); `box_hits_polygon` tests edges first and then one point (same result, fewer point-in-polygon scans); `TaxiManager.sweep_static` before the taxi checks (simulation.py, `taxi_sweep` section); `NPCVehicleManager.static_index` (world_loader), `_static_collisions` / `_resolve_static_hit` (third hit within 2 s skips the manoeuvre: reroute), `_npc_blocked` shared with `_enforce_npc_road_motion`, `update_knocked(static_index=)`; a mapped road through a building is exempt for NPCs as for the taxi. 9 new tests; full suite green (3020 passed, 3 skipped; one gc-count flake in test_soak under -n auto on 1 of 4 runs, passes alone and in the other runs; it does not use the index). Flaky trip-cycle test, 25 seeds alone: 25/25 before, 25/25 after. PBF bench (finland-latest, 69 m/s, 120 s, 5 runs), p50 / p99 ms: npc_static 0.031/1.214, 0.027/0.789, 0.040/0.861, 0.027/0.847, 0.038/1.508 (median p99 0.861; budget 0.50/1.5); taxi_sweep 0.023/0.509, 0.024/0.303, 0.023/0.288, 0.024/0.295, 0.025/0.278 (median p99 0.295; budget 0.10/0.40; run 1's 0.509 wall is GIL wait, its CPU p99 0.217); collisions section p99 1.18-1.28 (budget 3.0); taxi samples 3 per tick. Scenario 15 is a placed-pose drift harness, not a routed 150-NPC run. Interleaved A/B vs phase 5 not run.
