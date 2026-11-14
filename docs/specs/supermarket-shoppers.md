# Supermarket shoppers with carts

Goal: a few pedestrians walk between big grocery stores and their car parks, some pushing a shopping cart.

## Current behaviour
- Place-based crowds exist only for arenas: `ArenaCrowds` (src/theroadragetrip/arena_crowds.py:84), built in world_loader.py:487, ticked from simulation.py:938; spawns via `spawn_pedestrian_at_door` / `spawn_pedestrian_at` (pedestrian.py:2610, :2553) and `add_pedestrian` (pedestrian.py:810).
- Shops carry `shop_type` on buildings/places (building_style.py:98-170); car parks are `Scenery(kind="parking")` polygons (physics.py:357-373).
- Godot person mesh: `person_arrays(clothing, pose, ..., beard)` (godot/buildings_3d.gd:1380), pose from `person_pose` (godot/entity_layer.gd:2160); per-id variant pattern: `beard_style` (entity_layer.gd:2104). No cart prop exists.

## Design
1. New `src/theroadragetrip/shopper_crowds.py`, `ShopperCrowds(pedestrians, buildings, sceneries)`, modelled on ArenaCrowds. At map sync it lists stores with `shop_type` in {supermarket, hypermarket} whose footprint/point is inside a parking polygon or within `PARKING_RANGE_M = 60` of one. Entrance = existing `_arena_entrances` helper (reuse, rename public `venue_entrances`).
2. `update(now, taxi_position)`, throttled like ArenaCrowds (one pass per few seconds), only during store hours 07-22 local (choice: no opening_hours parsing). Keeps up to `MAX_PER_STORE = 3` live shoppers per store and `MAX_SHOPPERS = 60` total in the loaded map; only stores within the pedestrian spawn radius of the taxi are filled. Shopper walks parking point <-> entrance using the normal pedestrian walk target, despawns at the far end and is replaced.
3. `Pedestrian.cart: bool`, decided by `cart_for(ped_id) -> bool` = stable hash of id (`zlib.crc32`, ~50 % true), never `random`; serialised in the pedestrian frame dict as `"cart": true` only when true.
4. No new labels; names only from OSM `name` (none is added). No brand text on carts.
5. Godot: `person_arrays(..., cart := false)` appends a cart mesh (wire-box basket ~0.9x0.55x0.5 m on four 0.1 m wheels, grey) 0.45 m ahead of the hands, wheels' bottom at y = 0 (the walker's ground plane, plus `elevation`). With cart, arms reach forward (wrists at the handle) in walk poses. Cache key in `person()` (buildings_3d.gd:1351) includes the cart flag. entity_layer passes `ped.get("cart", false)`.
6. Python decides everything; Godot draws only, no physics, cart cost = one cached mesh per key.

## Files
- src/theroadragetrip/shopper_crowds.py (new), arena_crowds.py (expose entrance helper), pedestrian.py (`cart` field + frame dict), world_loader.py (build + attach `shopper_crowds`), simulation.py (~938: call `update`; sync with buildings like `sync_buildings`).
- godot/buildings_3d.gd (`person_arrays` cart + arm pose, cache key), godot/entity_layer.gd (pass cart).
- tools/visual_scenarios.json: scenario `supermarket_carts` at a real Oulu supermarket car park, location taken from the store's own OSM node via the loaded map (pick a large K-Citymarket/Prisma; store coordinates only, public data).

## Acceptance criteria
1. Shoppers spawn only at supermarket/hypermarket stores with parking within 60 m; a store with no parking in 60 m gets none.
2. Never more than 3 live shoppers per store nor 60 total, across repeated updates.
3. `cart_for(id)` returns the same value across runs and processes; the frame dict carries `cart` for those ids.
4. No shopper outside 07-22.
5. Godot cart mesh minimum y == 0 (+elevation) and is in front of the hands.
6. Scenario `supermarket_carts` renders with readiness checks passed showing at least one cart walker.

## Tests to add
- tests/test_shopper_crowds.py::test_shoppers_only_near_store_with_parking (fails: no module/spawning).
- ::test_shopper_caps_per_store_and_map (fails without caps).
- ::test_cart_deterministic_per_id (fails if random-based).
- ::test_no_shoppers_at_night.
- godot test (tests dir used by `make godot-test`) `test_cart_sits_on_ground`: `person_arrays(..., cart=true)` vertex min y == 0 and cart vertices exist beyond hand x.

## Commands
`make check`; `XDG_DATA_HOME=$(mktemp -d) make godot-test`; render via godot-shot with `supermarket_carts` and inspect.

## Out of scope
Cart physics/collisions with cars, carts left in lots, opening_hours parsing, 2D top-down cart drawing, store interiors.

## Status
VERDICT: PASS (tester).
- Shoppers and carts are implemented (a70a7fc9, de1888c6, 0c640d64).
- The cart render is small and far from the camera: acceptable, not a close-up.
- The render predates the final commits.
- Follow-up: held-peds leak on map sync is possible but rare and untested.
- Follow-up: shoppers do not yet do a scripted lot-to-door walk.
