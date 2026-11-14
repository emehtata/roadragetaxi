# Road on terrain: no gap under the road with DEM ground on

## Status
- Done in 576b4baa (x3 / +0.10 spread, test `test_road_lies_on_sloped_ground`).
- Tester verdict: PASS. Side view shows the road meeting the ground flush; reverting the fix fails the test; no flicker in the stills.
- Not checked: shimmer/z-fighting in motion (still images cannot show it).
- Not checked: flat-ground before/after, checked by code reading only (spread runs only with a grid).

## Goal
With DEM terrain on, the 3D road ribbon sits on the ground under it, not about 0.5 m above the grass
(user screenshot 2026-11-14, forest road: a visible gap under the road edge).

## Cause (measured from the code's constants)
`godot/buildings_3d.gd:2001-2005` (the "spread" in the DEM drape of `ground` and `road` vertices):
`y = y * 20 if y < 0.05 else y + 0.95`, then `+ ground_height(grid, xz)`.
- Ground quad y 0 -> 0 m; landuse areas 0.002..0.010 -> 0.04..0.20 m.
- Roads `ROAD_M + 0.002*rank` = 0.012..0.028 (`:2436`, `:2455`) -> **0.24..0.56 m** above the ground.
- Markings 0.036 -> 0.72 m; kerbs 0.12 -> **1.07 m**; bumps 0.082 -> 1.03 m.
The ground grid (`map_chunks.py:680`, 20 m step) and `ground_height` (`:2587`, bilinear) are the same for
ground and road, and both layers are subdivided to 20 m (`:1998-1999`), so the gap is all spread:
road minus grass = 0.24..0.56 m, kerbs about 1 m. The cars ride at `map_layer.deck_height` (`map_layer.gd:608`)
= ground + 0, so they also sink into the floating ribbon's sides visually.

## Fix (smallest change)
In `buildings_3d.gd` only: replace the x20 / +0.95 spread with a small one, named constants:
`const DEM_GAP_SCALE := 3.0` and `const DEM_GAP_LIFT := 0.10`:
`y = y * DEM_GAP_SCALE if y < 0.05 else y + DEM_GAP_LIFT` (continuous at 0.05: 0.15 both sides).
Result: grass 0..0.03 m, roads 0.036..0.084 m, markings 0.108 m, kerbs 0.22 m above the ground.
The 20 m subdivision already keeps the facet error to cm, so x3 keeps the layer order without z-fighting.
Decision (user offline): keep the spread rather than remove it; x3 is the smallest factor that keeps
the 2 mm rank steps 6 mm apart. If z-fighting shows at distance, raise to 4 (roads still <= 0.11 m).

## Files to change
- `godot/buildings_3d.gd`: the two constants, the spread line (~2004) and its ponytail comment.
- `godot/tests/dem_terrain.gd`: the new test.

## Acceptance criteria
1. On a sloped grid (e.g. 26x26, 20 m step, heights rising 0.1 m/m along x), every `road` vertex from
   `Buildings3D` arrays for a 200 m road crossing the slope is within 0.1 m of `ground_height` at its xz.
2. Every `ground` vertex (grass quad) is within 0.05 m of `ground_height`, and below the road surface at the same xz.
3. Kerb vertices top out at <= 0.25 m above `ground_height`.
4. Flat ground (empty grid): geometry unchanged (spread only runs with a grid).
5. Rendered `terrain_oulu_dem80` scenario (readiness checks passed, docs/visual-testing.md) inspected:
   no visible gap or dark band under the road edges; no road/grass z-fighting.

## Tests to add
- `godot/tests/dem_terrain.gd::test_road_lies_on_sloped_ground`: builds arrays with one road over the
  sloped grid; asserts criteria 1-3. Fails today: roads 0.24..0.56 m and kerbs 1.07 m above ground.

## Commands
- `make check`
- `XDG_DATA_HOME=$(mktemp -d) make godot-test`
- `godot-shot` of scenario `terrain_oulu_dem80`, screenshot inspected.

## Out of scope
- Grid-aligned subdivision / exact bilinear ground mesh.
- Bridge decks, tunnels, `deck_height` and vehicle ride height.
- Trees, lamps, buildings on terrain.
