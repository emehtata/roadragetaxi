# Vehicles look like their real-world kinds

Goal: each vehicle kind matches its real-world example in size and silhouette in both
the 2D layer and the 3D view, checked against one dimension table.

## Inventory (as of 379691d)
| kind | sim L x W m (base.py) | 2D (entity_layer.gd) | 3D near (< MODEL_CAR_RANGE) | 3D far (vehicle_arrays) | GLB W x L m |
|---|---|---|---|---|---|
| car (saloon/hatchback/estate/suv/pickup/sports/city_car) | 4.3 x 1.8 | CAR_SHAPES top-down | GLB per body style | car() boxes | 1.83-2.08 x 3.59-5.39 |
| van | 5.2 x 2.0 | VAN_SHAPE | panel_van.glb | car() boxes | 2.154 x 5.392 |
| taxi | car | CAR_SHAPES[0] + sign | GLB + sign | car() boxes | as car |
| truck | 7.5 x 2.3 | cab + box rects | box_truck.glb | 2 boxes | 2.652 x 7.542 |
| bus | 11.0 x 2.5 | hexagon + hatches | city_bus.glb | 3 slabs, no doors | 3.084 x 12.198 |
| tractor | 4.0 x 2.2 | wheels, bonnet, cab | tractor.glb (box when ploughing) | boxes | 2.33 x 3.665 |
| camper_van | 6.2 x 2.3 (camp pitch 7.0 x 2.3 x 2.9) | cab + living box | camper_van.glb | boxes | 2.154 x 5.042 |
| caravan trailer | 4.8 x 2.3 | box | caravan.glb | box + drawbar | 2.647 x 5.365 |
| motorcycle | 2.2 x 0.8 | TWO_WHEELERS drawing | motorcycle.glb | boxes shared with moped | 0.58 x 2.106 |
| moped | no definition | as motorcycle | none | motorcycle boxes | - |
| bicycle | 1.8 x 0.6 | tyres, frame, bars | none | procedural frame | - |
| e_scooter | 1.2 x 0.5 | wheels, deck, stem | e_scooter.glb | deck + stem | 0.482 x 0.844 |
| tram / train | trams.py / train_compositions.py | profile rects | train GLBs (< 35 m, train only) | 3 slabs, tram doors | 3.03 x 16.25, 2.89 x 26.4 |

## Real-world targets (acceptance tolerance: L and W within 10 %, H within 15 %)
Reference values: base.py where it exists, otherwise typical Finnish fleet values.
- bus: 12.0 x 2.55 x 3.1, 2 axles, flat roof with roof units, 2-3 doors on the right side, front entrance door.
- truck (rigid box): 7.5 x 2.5 x 3.4, 2 axles, cab-over, box taller than cab.
- tractor: 4.0 x 2.2 x 2.8, rear wheels about 2x front diameter, cab over the rear axle.
- camper_van: 6.2-7.0 x 2.3 x 2.9, van cab plus a wider living box, 2 axles.
- motorcycle: 2.2 x 0.8 x 1.2; moped: 1.8 x 0.7 x 1.1 with open step-through frame (no tank between knees).
- bicycle: 1.8 x 0.6 x 1.05, 2 x 0.7 m wheels; e_scooter: 1.1-1.2 x 0.5 x 1.2, deck about 0.15 m up.
- tram: about 2.4-2.65 wide, 3.4-3.8 high, pantograph on the roof, doors both sides; train: no pantograph only if diesel.
- taxi: car dimensions; at night head lamps, tail lamps and lit roof sign visible from above.

## Mismatches found
1. e_scooter GLB 0.844 m long is stretched to 1.2 m (x1.42 on length only): wheels become ovals.
2. camper_van GLB 5.04 m stretched to 6.2 m (x1.23 length, x1.07 width); camp pitch uses 7.0 m, a third size.
3. bus GLB 3.084 m wide (mirrors included) squeezed to 2.5 m while length scales x0.90: non-uniform; sim 11.0 m is short for a 12 m city bus.
4. motorcycle GLB width 0.58 vs sim 0.8: model scaled x1.38 sideways.
5. moped has no definition or model; drawn as a motorcycle in 2D and 3D (no open frame).
6. tram 3D has no pantograph (grep finds none) and only left-side doors.
7. Far bus boxes have no door or window bands; far tractor has equal-size wheels? (verify in render).
8. Night render metallic_vehicle_paint_night (20261103-073028): the taxi shows its roof sign but no headlight pool or tail lamps, while the other cars do.
   Not reproduced on 379691d: a passing night run shows the taxi's beam pair and lit tail lamps; the other taxi in that view is parked, lamps off. No lamp-path change.

## Fixes, smallest first (each its own commit)
1. buildings_3d.model_scale (place_model_car and vehicle_showcase): length and width always to the sim's; models stretched over 15 % in length (UNIFORM_SCALE_MODELS: e_scooter, camper_van) also scale their height by the length factor, so the wheels stay round (fixes 1, 3, 4).
2. base.py: bus 12.0 x 2.55; camper_van length shared with the camp-pitch entry at line ~2408 (one value).
3. Taxi night lamps: none needed (mismatch 8 not reproduced); the windshield_on early return only hides the body the camera is inside.
4. vehicle_arrays "train","tram": a pantograph on the tram only (the locomotive model is a diesel); doors on both sides of a tram (the real-world line), on the right side of a train coach.
5. moped: a VehicleDefinition("moped", ...) only when a traffic source spawns mopeds; else drop "moped" from VEHICLES_3D/TWO_WHEELERS (YAGNI).

## Tests to add
- tests/test_vehicle_definitions.py::test_dimensions_match_real_world_table: a REAL_WORLD dict of L/W per kind; fails today on bus (11.0 vs 12.0).
- tests/test_vehicle_definitions.py::test_glb_aspect_close_to_sim: parses MODEL_SIZE and UNIFORM_SCALE_MODELS from buildings_3d.gd; a model is in UNIFORM_SCALE_MODELS exactly when its length stretch exceeds 15 %.
- godot/tests/run_tests.gd::test_model_sizes_match_sim: rendered model bounds within 10 % of sim length and width; UNIFORM_SCALE_MODELS keep their height-to-length ratio.
- Render acceptance: vehicle_showcase.gd lineup day and night, top-down 2D and 3D, one inspected screenshot per kind; taxi night via metallic_vehicle_paint_night scenario with readiness checks passed (docs/visual-testing.md).

## Out of scope
New GLB models, LOD distances, paint/material work, NPC traffic behaviour, ferries.
Mismatch 7 (far bus door/window bands, far tractor wheel sizes): far boxes are drawn beyond MODEL_CAR_RANGE (66 m) at a few pixels; not addressed here.

## Open at commit (accepted as is, 2026-11-05)

The final tester run failed the render criteria, so these are recorded as open rather than done:
- **3D lineup, day and night:** no named 3D scenario with readiness exists; the lineup scenarios are 2D only. To be added.
- **Train right-side doors:** coach doors are in the code, but too small to see in the render.
- **2D camp pitch:** the frame is a scratch render, not a named scenario; the camper draws about 3 % short of 6.2 m.
- **E-scooter height:** 1.379 m, which is 14.9 % above 1.2 m; inside the 15 % limit, but at the edge.
