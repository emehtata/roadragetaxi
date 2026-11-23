# Vehicle model sources

The close-range GLB models are CC0 and contain no simulation or collision data.
All meshes remain visual children of the Python-authoritative vehicle position.

| Local file | Original model |
| --- | --- |
| `saloon.glb` | [Four-door saloon](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-saloon-ad831b1f) |
| `hatchback.glb` | [Five-door hatchback](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-five-door-hatchback-18f81884) |
| `estate.glb` | [Estate](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-estate-9c6ed02f) |
| `suv.glb` | [Mid-size SUV](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-mid-size-suv-949ce491) |
| `pickup.glb` | [Double-cab pickup](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-double-cab-pickup-5198b9ad) |
| `sports.glb` | [Sports saloon](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-sports-saloon-2d5d5fdd) |
| `city_car.glb` | [City car](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-city-car-033e3215) |
| `panel_van.glb` | [Medium panel van](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-medium-panel-van-9ef397a4) |
| `box_truck.glb` | [Box truck](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-box-truck-4574c765) |
| `motorcycle.glb` | [Motorbike](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-motorbike-8abc1635) |
| `camper_van.glb` | [Camper van](https://3dassets.dev/assets/car-park-and-road-vehicle-fleet-camper-van-40d26940) |
| `city_bus.glb` | [12 m low-floor city bus](https://www.innerscene.com/tools/library/3d-parts/12-m-low-floor-city-bus-8e3c7229) |
| `tractor.glb` | [Farm tractor](https://3dassets.dev/assets/air-land-sea-vehicles-farm-tractor-0254fd80) |
| `caravan.glb` | [Touring caravan](https://3dassets.dev/assets/caravan-park-and-campsite-touring-caravan-f889a9ff) |
| `e_scooter.glb` | [Folding kick scooter](https://3dassets.dev/assets/skate-park-and-street-sports-kick-scooter-e917e852) |
| `train_locomotive.glb` | [Rail locomotive](https://www.innerscene.com/tools/library/3d-parts/rail-locomotive-3b815032) |
| `train_coach.glb` | [Regional train coach](https://www.innerscene.com/tools/library/3d-parts/regional-train-coach-4ceef1bc) |
| `tram.glb` | [Tram](https://grab3d.com/models/vehicles/tram/) |
| `bicycle.glb` | [Bicycle](https://grab3d.com/models/vehicles/bicycle/) |
| `bmx_bike.glb` | [BMX bike](https://grab3d.com/models/vehicles/bmx-bike/) |
| `mountain_bike.glb` | [Mountain bike](https://grab3d.com/models/vehicles/mountain-bike/) |
| `moped.glb` | [Moped](https://grab3d.com/models/vehicles/moped/) |
| `subway_train.glb` | [Subway train (a metro train, a stand-in for a tram where no tram model exists)](https://grab3d.com/models/vehicles/subway-train/) |
| `e_scooter_grab3d.glb` | [E-scooter (Grab3D, a second model beside `e_scooter.glb`)](https://grab3d.com/models/vehicles/e-scooter/) |

3DAssets.dev and Innerscene mark these models CC0. The Grab3D models (tram, bicycle, BMX bike, mountain bike, moped, e-scooter, subway train) are CC0 1.0 with no attribution; their pages say so. The 3DAssets.dev files were
processed with `gltf-transform dequantize` because this Godot build cannot import
`KHR_mesh_quantization`. The bus was welded, simplified with glTF Transform
(`simplify --ratio 0.08 --error 0.1`), flattened and joined. This reduced it
from 829 mesh nodes to 10. The GLBs here are Godot-compatible results; the
URLs above are the originals.

The passenger-car GLBs (saloon, hatchback, estate, suv, pickup, sports, city_car)
also had their painted windscreen triangles removed from the body mesh, so the
glass under them shows. The windscreen was painted body geometry that hid it.
The removed triangles are forward-facing body faces inside the glass windscreen's
bounds; the change was made with a script over the glTF index buffers.

The VQA-001–005 follow-up repairs residual painted faces that still intersected
front glass in `hatchback`, `estate`, `suv`, `pickup` and `panel_van`.
`tools/repair_vehicle_windscreens.py` subtracts the existing front-glass projected
footprint from nearby paint faces, retaining a 15 mm painted surround. It clips
boundary triangles and interpolates only their added positions/normals; it does
not move or replace glass, change materials, or alter other primitives. Existing
vertices, node transforms and material data are preserved. The script uses the
project's Shapely dependency (2.1+), is deterministic for these source files and
leaves already repaired files unchanged. See
[correction evidence](../../../docs/visual-quality-corrections/vehicle-windscreens/README.md)
for source/pooled comparisons, preserved-data checks and gameplay screenshots.

The rail models were welded, simplified (`--ratio 0.12 --error 0.1`), flattened,
joined and resized to 256-pixel textures. Their close-range meshes are pooled;
the procedural train mesh remains the distant LOD.

The VQA-012 correction lowers only the existing regional coach HVAC assembly
(its box, feet, grilles and fans) by 0.32 m, placing its feet on the 3.57 m roof.
Run `tools/repair_train_coach_vent.py` with the project Python environment to
reproduce it; an already repaired file is unchanged. All non-HVAC vertex data,
normals, UVs, indices, textures, materials and node transforms are preserved.
This is local processing of the same CC0 source above, with no new data source.
See [correction evidence](../../../docs/visual-quality-corrections/train-coach-roof-vent/README.md).

Static camping props also reuse `camper_van.glb` (45,436 triangles, nine materials; source X/Y/Z 2.154150 × 2.214401 × 5.042000 m). Its complete mesh is ground-centred, turned +90° about Y to local +X, and uniformly fit to the positive streamed length, 2.5 m width and 2.9 m height. Driven vehicle resources/transforms remain unchanged. Finnish, English and German credits identify the original 3DAssets.dev CC0 source.

## Cozy Cars primary fleet

The shaded passenger-car body styles now select Grab3D [Cozy Cars](https://grab3d.com/kits/cozy-cars/) GLBs: saloon → Electric Car, city car → Compact Car, hatchback → Rally Car, estate → the already shipped `../props/station_wagon.glb`, sports → Coupe, SUV → Off-Road 4x4, pickup → Vintage Truck. `cozy_cars/*.json` records exact source/download URLs, unchanged hashes, measured bounds/parts/materials and transforms; original notices/manifests and full CC0 1.0 text accompany them. Attribution is displayed in Finnish, English and German.

Runtime keeps every authored source triangle and child transform. Equivalent wheel materials share cached batches. A single uniform scale fits the simulated length/width without oval wheels; height follows that factor. Body atlas hue tint retains trim/upholstery/lamp detail; source glass and tires remain separate. Head/tail/brake emission classifies authored yellow/red lens texels in source sRGB inside measured source height/depth bands. Small reverse/indicator overlays use cached source-triangle contact rays; the taxi roof sign is source-fitted and inherit road pitch/roll/elevation. Door/wheel animation is not added. The kit Minivan is rejected for the cargo-van role (passenger windows/seats and sliding door); the existing panel-van GLB remains. Static camping sources are unchanged.

## Cozy Retro Cars variety

Eight unchanged CC0 GLBs from [Grab3D Cozy Retro Cars](https://grab3d.com/kits/cozy-retro-cars/) supplement the primary Cozy Cars: 1980s Sedan/Hatchback/Station Wagon; 1990s Compact Car/Sports Car/SUV/Pickup Truck/Delivery Van. Exact downloads, hashes, measurements, materials and transformations are in `cozy_retro_cars/*.json`; original manifests/notices and full CC0 text accompany them. Source +Z is forward and wheels sit at Y=0; whole models uniformly fit existing simulation length/width. Salted stable ordinary NPC identities select primary/retro, preserving the same body parked or moving. No-ID calls/player and competitor taxis keep primary models. Complete source geometry and texture detail are retained, with intended body paint hue recolored and measured native lens emission. Reverse/indicators use existing source-contact overlays. Per-kind merged-mesh/material caches and node pools are reused. Displayed fi/en/de credits identify the kit/source/license. No traffic or physics decisions change.

## Cozy Vehicles tractor

[Tractor](https://grab3d.com/models/vehicles/tractor/) from [Grab3D Cozy Vehicles](https://grab3d.com/kits/cozy-vehicles/), CC0 1.0. Original download, source manifest, notice and legal text are in `cozy_vehicles/`; `tractor.json` records unchanged hash, dimensions and transforms. Complete 32,784-triangle source retains body, four wheels and cab glass. Uniform fit to 4.0×2.2 m produces 4.0×2.017 m, round wheels and grounded source contacts. Equivalent authored wheel materials share cached surfaces. Only sage paint is tinted; cream roof, wheels, engine and glass retain source detail. Native white front/red rear atlas lenses follow existing lamp bits; reverse/indicator overlays sit on measured lamp clusters. Ordinary and plough tractors share the body pool; the existing six-piece blade and server-state amber beacon are attachments, with beacon base fit to source roof y=2.86 m.

The kit has no tram or open-deck road ferry match: Steam Train and Fishing Boat have different roles. Their procedural rendering remains. No unused kit models are shipped.
