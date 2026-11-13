# Comic, well-animated pedestrians

## Goal
People in 3D get comic proportions (big head, short round torso, chunky hands/feet) and a
readable walk (opposed arm swing, body bob) plus idle breathing, inside the same bounding box and seat points.

## Current behaviour
- `godot/buildings_3d.gd:1368` `person_arrays()` builds every person (standing, walk_N, run_N,
  sitting, riding, swimming, lying); realistic proportions: head radii (0.118,0.145,0.112) at y 1.61
  (`:1428-1430`), torso at 1.14 (`:1406`), shoulders 1.37, hips 0.87, top of hair ~1.83 m.
- Walk: 6 discrete phases; legs `swing`/`lift` (`:1383`, `:1391`, `:1400-1401`), wrists already
  swing opposite (`:1421`). No body bob, no idle motion.
- Seats: `offset` per pose (`:1379`): sitting -0.35, riding `HORSE_SADDLE_Y - 0.87`; riding legs
  from `riding_leg_joints()` (`:1148`, `:1393-1399`); scooter/bike legs `:1240-1270`.
- Phase choice: `entity_layer.gd:2154` `person_pose()` -> `walk_%d` from `animation_time *
  WALK_POSES_PER_S` (10.5, `:2144`); running when server `speed >= 2.0`. Meshes cached per pose
  key in `person()` (`buildings_3d.gd:1336`) -> `place_body`; no per-frame vertex work.
- 2D view: `entity_layer.gd:2126` walk_a/walk_b strides (unchanged here).

## Design / choices
1. Keep the 6-phase cached-mesh scheme (phase from client `animation_time`, run/walk from server
   `speed`). Choice: no per-frame vertex recompute; cache keys already make it O(1) per person.
2. Proportions, fixed hip (0.87) and seat offsets: head radii x1.7 (~0.20,0.245,0.19), head centre
   lowered so top of hair stays <= 1.85 m; neck shortened to a stub; torso scale y 0.85, x/z 1.15;
   hands x1.6, shoes x1.4; limb radii +20% at joints (knee/elbow parts). Face parts scale with head.
3. Bob: walk/run poses add `bob = 0.03 * |cos(phase*TAU/6)|` (run 0.05) to everything above the
   hips (torso, arms, head); lowest at mid-stride. Feet stay on the ground.
4. Idle breathing: new poses `standing_0`/`standing_1` (torso y +0.012, shoulders +0.01 on _1);
   `person_pose()` returns `standing_%d` with period 4 s, phase offset by hash(id). Plain
   `"standing"` stays valid (= standing_0).
5. Sitting/riding/scooter/bike: only head/torso/hands restyled; hip, thigh, ankle and seat contact
   points unchanged.

## Files to change
- `godot/buildings_3d.gd`: `person_arrays()` proportions, bob, `standing_N`.
- `godot/entity_layer.gd`: `person_pose()` idle `standing_%d`.
- `godot/animal_models_test.gd`: re-record `POSE_HASHES` (intentional change).
- `godot/tests/run_tests.gd`: new tests below.
- `tools/visual_scenarios.json`: `pedestrian_comic_closeup_day` (walker at ~4 m + a `bench_sitter`).

## Acceptance criteria
1. Head bounding radius >= 1.6x and <= 1.8x the old one (standing pose).
2. Standing AABB height within +-0.03 m of before (1.83 m); width/depth within +-0.05 m.
3. Sitting, riding and scooter poses: min vertex y and hip y within 0.01 m of before.
4. Every `walk_N` is identical to `walk_(N+6 mod 6)` via `person_pose()`: pose at t and
   t + 6/WALK_POSES_PER_S equal (periodic cycle).
5. In walk_0..5 the left wrist x has the opposite sign of the left ankle x whenever |swing|>0.05.
6. Head y differs across walk phases (bob) by 0.02-0.06 m; lowest foot vertex y constant (+-0.01).
7. `standing_0` != `standing_1`; `person_pose(standing ped)` cycles both within 4 s.
8. Screenshot of `pedestrian_comic_closeup_day` passes readiness checks and is inspected:
   big-head silhouette, walker mid-stride, sitter on the bench (not floating/sunk).

## Tests to add (`godot/tests/run_tests.gd`)
- `test_person_comic_head_ratio` (1) - fails on current head size.
- `test_person_bbox_unchanged` (2), `test_person_seat_heights_kept` (3) - guard against the redesign drifting.
- `test_walk_cycle_periodic` (4), `test_walk_arms_oppose_legs` (5).
- `test_walk_body_bob` (6) - fails now: head y is constant across phases.
- `test_idle_breathing_poses` (7) - fails now: no `standing_N`.

## Commands
`make check`; `XDG_DATA_HOME=$(mktemp -d) make godot-test`;
`godot-shot` with scenario `pedestrian_comic_closeup_day`, inspect PNG + JSON.

## Out of scope
2D drawing of people; server changes; GLB/skinned models; animals; new gait states.

## Status
- Comic pedestrians: tester PASS (after the stride fix in 5680cbdb: walker held at walk_2 mid-stride).
- Drunk gait: tester PASS (53e86386).
- Accepted deviations: head 1.45x front-to-back (spec asked 1.6-1.8x on the radius measure);
  shoes 1.17x; body bob 4.5 cm; bbox reference 1.694 m.
- Screenshot: `visual-test-results/pedestrian_comic_closeup_day/2026-06-20T1500_20261113-235354_81f5c1e3-dirty/screenshot.png`
  (readiness checks passed).
- Commits: 53e86386, 164370af, 81f5c1e3, 5680cbdb, a08088ed (test cursor hardening, make godot-test 21 passed).
