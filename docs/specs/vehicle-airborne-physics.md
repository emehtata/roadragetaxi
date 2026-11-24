# Vehicle airborne arc and grip limit (player-driven vehicle)

## Goal
The car the player drives leaves the ground over sharp crests at speed, flies a ballistic arc
and lands with a visible bump. Hard turns at speed slide or understeer instead of tracking the line.

## Root cause
- The sim is 2D: `Car` has x, y, heading, speed and no z or vz (`src/theroadragetrip/physics.py:228-275`).
- The client sets body height to the road surface every frame: `deck_height.call(c, _layer)`
  (`godot/entity_layer.gd:1039`, `godot/map_layer.gd:623-632`). Pitch and roll come from the four
  wheel heights, eased 0.25 per frame (`entity_layer.gd:1030-1037`, `godot/buildings_3d.gd:909-916`).
  So the body can never leave the surface.
- Default `physics_realism` is "arcade" (`config.py:94`), which multiplies grip by 1.57
  (`physics.py:89`): dry asphalt 1.15 g x 1.57 = 1.8 g, more than road tyres give, so curves feel glued.
  The slide model is already there (understeer clamp, drift angle, `is_sliding`, `physics.py:1509-1640`).
- The server has DEM heights (`map_chunks.py:683-697`) but no bridge deck or ramp heights. Those exist
  only on the client (`Buildings3D.road_surface_height`), so a server z would fall through bridges.

## Decision: client-side visual vertical state, server keeps 2D authority
The vertical motion is cosmetic and covers only the vehicle the player drives (taxi or any vehicle
the player drives). NPC vehicles stay as they are. Nothing in traffic decisions changes.

## Files to change
- `godot/vehicle_vertical.gd` (new, about 40 lines): `class_name VehicleVertical`,
  `func step(ground: float, ground_ahead_slope: float, speed: float, dt: float) -> float` returns body
  height. Fields: `z`, `vz`, `airborne`, `land_bump`. Constants: `GRAVITY = 9.81`, `LAUNCH_MIN_MPS = 12.0`,
  `SNAP_EPS_M = 0.05`, `BUMP_DECAY_S = 0.25`.
- `godot/entity_layer.gd` (~1030-1039): for the driven vehicle, pass `VehicleVertical.step(...)` as the
  elevation instead of the raw `deck_height`. While airborne, keep the last ground tilt; on landing add
  `land_bump` to pitch (nose down) and lower the body by up to 0.08 m.
- `src/theroadragetrip/physics.py:89`: lower arcade multiplier from 1.57 to 1.15 (about 1.3 g on dry asphalt).

## Behaviour / acceptance criteria
1. On ground, `vz` takes the vertical speed of the surface (`speed * slope`). If the surface drops away
   faster than gravity can follow (`ground < z - SNAP_EPS_M` after integrating `vz -= g*dt`), the car is
   airborne and falls with g until `z <= ground`. Then `z = ground`, `vz = 0`, and the bump starts.
2. Over a synthetic crest (slope +0.15 then -0.15 over 20 m) at 25 m/s, airtime is >= 0.15 s.
   At 8 m/s, airtime is 0 s.
3. `z >= ground - 0.001` on every step (no penetration) for any input, bridge decks and tunnels included,
   because `ground` is `deck_height` for the current layer.
4. Flat ground or a 2 % grade at <= 14 m/s gives a body height equal to `deck_height` (within 0.001 m)
   every frame. A 0.04 m mesh seam step never sets `airborne`.
5. Below `LAUNCH_MIN_MPS` the car never goes airborne.
6. Layer change (bridge or tunnel switch) or a teleport/respawn (jump > 5 m) resets `z = ground`, `vz = 0`.
7. Server, arcade mode, dry asphalt: with steer held at 25 m/s, peak `raw_lateral_g` is <= 1.35 and
   `is_sliding` becomes true within 2 s. At 8 m/s full lock, `is_sliding` stays false.
8. Per-frame cost: O(1) per driven vehicle, no new height lookups beyond one extra `deck_height`.

## Tests to add
- `godot/tests/vehicle_vertical.gd::test_crest_airtime_at_speed`: crest profile, airtime >= 0.15 s at 25 m/s
  (fails now: there is no airborne state).
- `::test_no_airtime_low_speed`, `::test_flat_unchanged`, `::test_seam_no_bounce`,
  `::test_never_below_ground`, `::test_layer_change_resets`.
- `tests/test_cornering_grip.py::test_arcade_peak_lateral_g_bounded`: criterion 7. It fails at the
  current 1.57 multiplier (peak about 1.8 g). Also `::test_arcade_low_speed_no_slide`.
- Existing `tests/test_grip.py`, `test_cornering_grip.py`, `test_physics.py`: update constants that
  assumed 1.57, but only where they assert the multiplier itself. The full suite must pass.
- Visual: add `vehicle_crest_jump_helsinki` to `tools/visual_scenarios.json`. Use a real sloped street
  near Helsinki centre found with `tools/visual_test.py find --city Helsinki` (public city-centre
  coordinates only). Use chase camera and `drive_s` of 4. Verify with `godot-shot --screenshot-drive 4`;
  the debug snapshot must show `airborne` true for at least one frame.

## Out of scope
NPC vertical motion, server-side z, steering or traction loss while airborne, suspension sim,
crash tumbling, new body-roll physics beyond the existing wheel tilt.
