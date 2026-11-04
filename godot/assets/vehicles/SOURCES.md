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

3DAssets.dev and Innerscene mark these models CC0. The 3DAssets.dev files were
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

The rail models were welded, simplified (`--ratio 0.12 --error 0.1`), flattened,
joined and resized to 256-pixel textures. Their close-range meshes are pooled;
the procedural train mesh remains the distant LOD.
