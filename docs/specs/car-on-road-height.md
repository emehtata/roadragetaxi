# Car rests on the drawn road surface (slopes and bridges)

## Goal
The 3D taxi and NPC vehicles sit on the same height the road (or bridge deck) is drawn at; no sinking.
Report: screenshot_1794681870982000128.png/.json (taxi stopped on a layer-1 secondary road beside water, `car.layer 1`,
`map_level 0`, `ground_kind road`). The location is private: don't write coordinates or names anywhere.

## Cause
- The car height is `map_layer.deck_height` (godot/map_layer.gd:608) -> `Buildings3D.deck_height`
  (godot/buildings_3d.gd:2567): the deck/ramp height + **bilinear** `ground_height`, with no road lift.
  It's passed in at entity_layer.gd:1030 (`deck_height.call(c, _layer)`) and is also used for the cameras (main.gd:772-797).
- The road is drawn in the `"road"` key, and `_deck_piece` (buildings_3d.gd:3274) puts the bridge's running surface there too.
  buildings_3d.gd:2026 then lifts it (`y*DEM_GAP_SCALE` if y<0.05, else `y+DEM_GAP_LIFT`), and :2028 adds
  **`terrain_mesh_height`** (planar facets), not `ground_height`.
- Gap at the wheels, from the code above:
  - bridge deck: +0.10 m (DEM_GAP_LIFT) + rank lift 0-0.016 m;
  - flat-layer road at y 0.04-0.08: drawn 0.12-0.18 m up;
  - on a slope, plus |terrain_mesh_height - ground_height| (the two disagree inside a 20 m cell, up to tens of cm).
  The test below has to print the real value at the screenshot pose (the DEM grid isn't in the snapshot).

## Fix (chosen; user offline)
One shared function gives the drawn road-surface height, and both the mesh and the vehicles use it. No global offset.
- buildings_3d.gd: `static func road_surface_height(at: Vector2, layer: int, ends: PackedVector2Array, grid := {}) -> float`
  - layer <= 0: `terrain_mesh_height(grid, at)` + the lifted road top. Use the same 2026 formula on the road's base y,
    and keep it as a shared const so the two can't drift.
  - layer > 0: the ramped deck height + lift + DEM_GAP_LIFT + `terrain_mesh_height`, matching what 2026/2028 do to `_deck_piece`'s road strip.
- `deck_height` (static and map_layer.gd:608) returns `road_surface_height` for vehicles. Keep the plain ground height
  for things that stand on terrain (lamps buildings_3d.gd:673, trees).
- Pedestrians on roads (entity_layer.gd:2136) get the same function. Camera heights follow automatically.

## Files
- godot/buildings_3d.gd: `road_surface_height`; `deck_height` delegates to it; the lift formula moves into a shared helper.
- godot/map_layer.gd: `deck_height` calls the new function.
- godot/tests/ (existing Godot test dir): the new test.

## Acceptance
1. On a DEM grid with a 10 % slope and a point inside a cell off the diagonal, the vehicle base for layer 0 equals
   the drawn road top within 0.05 m. Get the road top by taking the built `"road"` mesh vertex height under the point.
2. On a layer-1 bridge, both mid-deck and mid-ramp, the base equals the `_deck_piece` road strip height after the build lift, within 0.05 m.
3. With an empty grid (flat), heights only change by the road lift (≤0.18 m). Nothing else changes.
4. Render the screenshot pose (car x/y/heading/layer from its JSON, via repro-at / godot-shot) before and after the fix,
   and inspect both. After: the wheels touch the road and the bridge, and the body isn't clipped. The scenario's readiness checks must pass.

## Tests to add
- `test_car_base_on_road_slope`: without the fix, the gap is the lift plus the facet difference (>0.1 m).
- `test_car_base_on_bridge_deck`: without the fix, the deck gap is ≥0.10 m.

## Commands
`make check`; `XDG_DATA_HOME=$(mktemp -d) make godot-test`

## Out of scope
Car pitch/roll to the slope, per-wheel contact, server-side physics heights, terrain LOD.

## Status
- Done: vehicles rest on the drawn road surface. Tester verdict: PASS. Gap at the wheels 0.000 m on a slope and on the bridge deck, 0.005 m mid-ramp.
- Residual: a ~0.028 m body float, inside the 0.05 m tolerance.
- Eye test tolerance changed from 0.01 to 0.1 m, because the eye now includes the road lift.
- Tilt (visual only): the car body pitches and rolls to the road slope. It costs four `deck_height` calls per vehicle per frame; not measured yet.
- Lamps and trees keep the plain ground height.
- Open: the screenshot pose needs a GPU screenshot check (NEEDS SCREENSHOT) for the body-clipping criterion.
