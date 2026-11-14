# Third-person driving camera (brief: docs/3rd-person.md, phase 1)

## Goal
Third-person chase camera as the default driving view (key 1), top-down on 2, driver-eye on 3;
the navigation route drawn on the road in the 3D world. Python stays authoritative.

## Audit (release/v0.22.0beta, after terrain/road smoothing and DEM fixes)
- `godot/main.gd:27` `Camera2D` follows `entities.player_position() + _camera_lead()` (`:762`); zoom 3..24 (`:620`). Confirmed.
- `godot/buildings_3d.gd:40-41,233-241` one `Camera3D` (FOV 30, `KEEP_HEIGHT`) in a `SubViewport`; `_process` (`:304-363`)
  places it straight down above the 2D camera centre (`top_camera_position`, `:295`, rotation -90) or, with `windshield_on`,
  at the eye (`windshield_camera_position`, `:291`), `_eye_blend` glide (`:366`). Confirmed.
- `main.gd:555-556` `KEY_I` toggles `_set_windshield()` (`:650-679`), which works driving and on foot (walk_eye);
  driving it forces `camera.zoom = 3.0` so forward chunks/traffic stay loaded (`:668-669`). Confirmed.
- `godot/entity_layer.gd:1764-1790` route = `_route_node.draw_polyline` of `navigation.points` (2D canvas). Confirmed.
- `godot/map_layer.gd:608` `deck_height(at, layer)` -> `Buildings3D.deck_height` (`buildings_3d.gd:2557`): ground grid
  (`map_chunk.gd:455`) plus layer*DECK_M with ramps to `bridge_ends`. Confirmed.
- 3D world completeness (with `MapChunk.outdoor_3d`, the default start, `map_layer.gd:80`): terrain, roads + markings
  (`map_chunk.gd:599`), buildings, forest/trees, street lights, cars/NPC vehicles (`buildings_3d.car/vehicle`), pedestrians
  and animals (`person`, `_flush_animals`), trains, precipitation (`buildings_3d.gd:90`), sky, sun shadows (opaque mode)
  are all in the one 3D world; the windshield scenarios already prove they align in perspective.
- **Gaps:** (1) the route exists only on the 2D canvas, so it is missing in any perspective view (driver-eye too);
  (2) `navigation.points` are `[x, y]`, no layer, so bridge/tunnel sections cannot be lifted correctly;
  (3) the camera pose code only knows "top" and "eye"; no chase pose, no ground clamp at the camera;
  (4) the non-opaque `_shadow_ground` path is sized from the 2D view - perspective needs `opaque` (as windshield does);
  (5) without `outdoor_3d` (2D view flag) there is no 3D world: modes 1/3 fall back to top-down there.
  No substantial rendering change needed: the chase camera reuses the windshield path (full-screen TextureRect of `_view`).

## Design
- New `godot/camera_modes.gd` (Node, owned by main): `enum Mode {THIRD, TOP, EYE}`, `var mode := THIRD`,
  `func select(m: Mode) -> void`, `func handle_key(event) -> bool`, `static func chase_pose(at: Vector2, heading: float,
  ground: float, cam_ground: float) -> Transform3D`, `func smooth_heading(target: float, delta: float) -> float`.
  main.gd only forwards keys and calls `select`; the existing `_set_windshield` is reused for EYE and generalised to a
  `_set_3d_view(kind)` that shows the same full-screen 3D texture (no car trims for THIRD).
- `buildings_3d.gd`: add `chase_on`, `chase_transform` (set per frame from main using the same interpolated
  `entities.player_body()` sample as the taxi mesh), applied in `_process` alongside the windshield branch; near 0.3, far 1200, sky background.
- Constants (code, top of camera_modes.gd): `CHASE_BACK_M = 7.5`, `CHASE_UP_M = 3.2`, `LOOK_AHEAD_M = 6.0`,
  `LOOK_UP_M = 1.0`, `FOV = 60`, `HEADING_SMOOTH_S = 0.25`, `CLEARANCE_M = 1.2`. Why: a 4.5 m taxi fills ~1/4 width at
  7.5 m with FOV 60 and sits in the lower-centre third; 3.2 m up gives ~17 deg down so ~40 m of road ahead stays visible
  over the roof; the look-ahead point keeps the horizon in the upper third. Only heading is smoothed (critical-damped,
  no position lag), so no rubberband: position is locked to the interpolated taxi, which already is smooth.
  No roll: `look_at(..., Vector3.UP)`. Pitch from taxi slope is not followed (upright on hills).
- Obstruction: no physics. Clamp camera y >= `deck_height(cam_xy, 0) + CLEARANCE_M` and, when the taxi is on layer <= 0
  under a deck, cap y below the deck (`deck_height(cam_xy, 1) - 0.5`, shorten CHASE_UP). Buildings: accept occlusion
  (rare at 7.5 m behind on a road); out of scope to fade walls.
- Keys (in the existing `_unhandled_input` match, so text fields/menus that consume input never see them): `KEY_1` THIRD,
  `KEY_2` TOP, `KEY_3` EYE; deterministic select. `I` acts only `on_foot` (walk first person); driving it does nothing.
  The chosen driving mode persists across leaving/re-entering the taxi; first entry = THIRD. Mouse stays visible in 1/2/3
  driving. 2D zoom forced to 3.0 in THIRD/EYE (loading as today), restored on 2.
- Route in 3D (phase 3): `godot/route_3d.gd` (MeshInstance3D in the 3D world, unshaded, RS.ROUTE/ROUTE_EDGE, `route_tint`):
  `static func build(points: PackedVector2Array, layers: PackedInt32Array, height: Callable) -> ArrayMesh` - a ribbon 1.2 m
  wide (edge) / 0.5 m (centre), resampled every 2 m, y = `map_layer.deck_height(p, layer) + 0.08`. Rebuilt only when
  `entity_layer._route_source` changes or a chunk with ground_heights loads under the route (map_layer chunk signal);
  hidden when `route_for()` is empty (same N/visibility rules). Top-down 2D route untouched.
  **Protocol:** the smallest change is additive: the server emits `[x, y, layer]` per point (layer of the road edge the
  point lies on, already known in the path; Douglas-Peucker keeps the layer of kept points). Client accepts 2- or 3-element
  points (missing layer = 0, ground). No routing-algorithm change. Ramps come from `deck_height`'s existing bridge ramps.

## Files
`godot/camera_modes.gd` (new), `godot/route_3d.gd` (new), `godot/main.gd` (keys, delegate; net <= +20 lines),
`godot/buildings_3d.gd` (chase branch), `godot/entity_layer.gd` (expose route points + layers), `godot/visual_test.gd`
(scenario `camera` key: third|top|eye, `switch` list), server navigation serializer (`[x, y, layer]`) + its test,
`docs/architecture/godot-client.md` (protocol row, camera modes), `docs/specs/driver-eye-first-person.md` (key 3),
README.md key table (`:105`), `godot/i18n.gd`/help + HUD key hints, `tools/visual_scenarios.json`.

## Commits
1. Camera modes and keys: camera_modes.gd, 1/2/3 select, I on foot only, docs/README/hints (THIRD = top-down until commit 2).
2. Third-person camera: chase pose, smoothing, ground/deck clamp, default THIRD, scenarios 1-5, 7-10.
3. Route in 3D: server `[x, y, layer]`, route_3d.gd, scenario 6, driver-eye route check.

## Acceptance (brief criteria)
1 default THIRD at first entry (test); 2-4 keys select modes (`godot/tests/camera_modes.gd`: test_keys_select_deterministic);
5 I ignored driving, walk-eye on foot (test_i_on_foot_only); 6 scenario 9 repeated switching; 7 scenarios 1-3;
8 scenario 6 + test_route_heights_follow_deck (fails without layer); 9 scenarios 4-5 + test_chase_clamped_above_ground,
test_chase_below_deck; 10 per-frame camera delta log in visual_test (max step <= taxi step + 0.05 m, no heading jumps);
11 `make check` unchanged server tests, no Python change except navigation serializer; 12 scenarios inspected;
13 perf table below; 14 README/help/hints updated.

## Visual scenarios (real Oulu poses already in the registry)
1 `third_oulu_straight` = windshield_oulu_day pose; 2 `third_oulu_curve` = terrain_oulu_curve; 3 `third_oulu_dense` =
walk_bench_oulu_day pose (city centre); 4 `third_bridge` = terrain_hill_bridge_day (Helsinki; only layer-1 bridge pose in
registry - add an Oulu bridge via `visual_test.py find` if one exists); 5 `third_oulu_terrain` = terrain_oulu_dem80;
6 `third_oulu_route` = windshield_oulu_day + a fare target; 7 `top_after_third`, 8 `eye_after_third`, 9 `camera_cycle`
(1,2,3,1 while driving with `--screenshot-drive`), 10 `walk_eye_i` = walk_city_street_day with I. Same pose/time/weather per comparison.

## Performance (native Windows GPU, dense_city_performance pose, top-down vs third vs eye)
Frame avg/p50/p95/p99, CPU/GPU render ms, draw calls, primitives (perf.gd), route_3d build ms, per-frame allocations.
Reject if third p95 > eye p95 + 10 %.

## Test commands
`make check`; `XDG_DATA_HOME=$(mktemp -d) make godot-test`; visual scenarios via godot-shot per docs/visual-testing.md.

## Out of scope
Building fade/obstruction avoidance, mouse orbit, camera collision shapes, minimap, changing the 2D route or handling.

## Status (2026-11-14)
- Tester verdict: PASS after round 2 (phone keys 8/9/0 correct; both suites green).
- Implemented: camera modes and keys 1/2/3 (THIRD default, TOP, EYE), chase camera with smoothing and
  ground/deck clamp, route drawn in 3D from `navigation.points` `[x, y, layer]`, phone keys moved to 8/9/0.
- Unverified: switching while driving at speed; tunnels; the under-deck clamp on real map data (only unit
  tests and the Joutsensilta bridge render cover it).
- Performance (one native Windows run, dense_city_performance): third-person p95 is +4% over driver-eye.
  Within the 10% limit, but measured once only.
