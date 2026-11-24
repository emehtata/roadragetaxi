# Prop model sources

`Swing Set` by [Grab3D](https://grab3d.com/models/toys/swing-set/), from the Cozy Playground & Gym kit, is offered as CC0 1.0 Universal (public domain). Downloaded on 2026-11-18 from https://grab3d.com/dl/swing-set/swing-set.glb. The full applicable [CC0 legal text](CC0-1.0.txt) is retained here; the [source manifest](manifest.json) records URL, hash, bounds and conversion details. Attribution is also shown in the in-game credits in English, Finnish and German.

The unchanged source GLB contains 19,740 triangles, three PBR materials and three mesh children (frame, left swing, right swing). Actual source dimensions X/Y/Z: 3.600000 × 2.430000 × 2.017987 m. Runtime import bakes the child transforms and keeps source normals, UVs, tangents and all PBR materials. The neutral pose is static; the two moving children are not animated.

The footprint centre is placed at the existing scenery row and feet at local Y=0, with X along the existing row heading. Uniform scale 0.891977990 fits the original 3.4 × 1.8 × 2.2 m length/width/height envelope. Rendered X/Y/Z dimensions are 3.211121 × 2.167507 × 1.800000 m. Chunk terrain height is applied per vertex through the same ground sampling used by other props, with normals/tangents adjusted for that ground slope. Textures and source colours are retained. There is no new collision or simulation data.

SHA-256: `6197b924aba6ea102b8ef9544cc594743ee14d0c05f8018bb2b4edf8bad9a614`.

## Playground Slide

`Playground Slide` by [Grab3D](https://grab3d.com/models/city/playground-slide/), from the Cozy Playground & Gym kit, is offered under CC0 1.0 Universal. Downloaded on 2026-11-18 from https://grab3d.com/dl/playground-slide/playground-slide.glb. The [full CC0 text](CC0-1.0.txt) and [slide source manifest](playground_slide.json) are shipped here; English, Finnish and German in-game credits also identify the source.

The unchanged GLB contains 15,988 triangles and one PBR material. Measured source X/Y/Z dimensions are 1.010913 × 2.058000 × 3.866525 m. Runtime batching bakes the original child transform, centres the ground footprint and rotates +90 degrees around Y to place the downhill chute along local +X. Uniform scale 0.827616594 fits the existing 3.2 × 0.9 × 1.8 m length/width/height envelope; rendered X/Y/Z dimensions are 3.200000 × 1.703235 × 0.836648 m. Source materials, UVs, normals and generated tangents are retained, and terrain height follows the existing prop placement path. No new collision or simulation data is introduced.

SHA-256: `ada2534de7aacd5253ce5fa4b3db1c9107cec3bd9f904243a8b192a90c64c1fe`.

## Spring Rider

[Spring Rider](https://grab3d.com/models/city/spring-rider/), Grab3D Cozy Playground & Gym Kit. Downloaded 2026-11-18 from https://grab3d.com/dl/spring-rider/spring-rider.glb, under CC0 1.0 public domain. Full legal text is retained in `CC0-1.0.txt`; hash, measured bounds and static runtime transforms are in `spring_rider.json`. The source GLB bytes are unchanged. Godot extracts the embedded JPG textures during import.

The model is uniformly scaled to 0.8 m height within the server's existing 0.8 m radial equipment clearance, ground centred and rotated +90 degrees around Y so the ladybug faces local +X. The separate ladybug/spring and base child transforms are retained in the static material batches.

## Climbing Frame

- Source: Grab3D, Cozy Playground & Gym Kit — https://grab3d.com/models/city/climbing-frame/
- Exact Light GLB download: https://grab3d.com/dl/climbing-frame/climbing-frame-light.glb (2026-11-18).
- License: CC0 1.0 public domain; retained full legal text in `CC0-1.0.txt`.
- Unchanged source hash, bounds, uniform fit and provenance: `climbing_frame.json`. Light has 13,734 triangles, one PBR material and 1K textures; normal map is absent in the offered Light source. Frame, net, wall, ladder and monkey bars are retained; no source edits.
- Runtime front wall faces local +Z; ground-centred source is uniformly scaled by 0.729927036516 to 1.666423 × 1.600000 × 1.333177 m.

## Seesaw

[Seesaw](https://grab3d.com/models/city/seesaw/), Grab3D Cozy Playground & Gym Kit. Downloaded 2026-11-18 from https://grab3d.com/dl/seesaw/seesaw.glb under CC0 1.0 public domain. Full text is retained in `CC0-1.0.txt`; unchanged source hash, measured bounds and runtime transforms are in `seesaw.json`. English, Finnish and German in-game credits name the source.

The actual GLB contains 10,940 triangles and two PBR materials. Baked child transforms preserve the beam's authored tilt, seats, handles, stand and partly buried tyre bumpers. Its horizontal centre and intended ground contacts use local zero. Uniform scale 0.47909068462320603 fits the existing 3.0 × 0.3 × 0.6 m envelope; long axis is local X before row yaw. Textures, UVs, normals and generated tangents are retained in static chunk batches; no simulation or collision changes.

## Fairground Carousel

[Fairground Carousel](https://grab3d.com/models/city/carousel/), Grab3D Cozy Amusement Park Kit. Unchanged Light GLB downloaded 2026-11-18 from https://grab3d.com/dl/carousel/carousel-light.glb, under CC0 1.0 public domain. Full legal text is retained in `CC0-1.0.txt`; exact hash, bounds and runtime fitting rule are in `carousel.json`. Finnish, English and German in-game credits identify the source.

The selected model has 21,956 triangles and three original materials: textured fixed plinth, textured spinning roof/seats/poles/deck, and emissive bulbs. Child transforms retain the authored 0.28 m deck offset. Source X/Y/Z bounds measure 7.167183 × 6.472999 × 7.168641 m. The static source is centred on the mapped loop mean and base zero. One uniform factor keeps authored size when its horizontal bounding circle fits, otherwise shrinks it into the circle from the mean to the nearest footprint edge; zero-area/unclosed footprints are skipped. The Vauhtipuisto 6.498 m radius footprint retains scale 1.0. Existing per-vertex DEM grounding and chunk material batching retain UVs, normals and tangents. Ride animation and collision/simulation data are unchanged.

## Swing Ride and Ferris Wheel

[Swing Ride](https://grab3d.com/models/city/swing-ride/) Light GLB and [Ferris Wheel](https://grab3d.com/models/city/ferris-wheel/) GLB, Grab3D Cozy Amusement Park Kit, downloaded 2026-11-18 under CC0 1.0 public domain. Exact download URLs, unchanged source hashes, child-transform measurements and runtime fitting are recorded in `swing_ride.json` and `ferris_wheel.json`; the full legal text remains in `CC0-1.0.txt`. Finnish, English and German in-game credits show both sources.

Swing Ride retains 18,532 triangles and three materials (mast/base, spinning roof/chains/chairs, bulbs). Ferris Wheel retains 39,652 triangles and three materials (lattice A-frames/base, rotor/spokes/gondolas, bulbs). Source child transforms, original textures, UVs, normals and tangents survive static chunk batching. The authored moving parts are shown in their neutral pose. A single uniform scale shrinks only when the mapped loop's contained circle is smaller than the source half-diagonal; authored size is never enlarged. Ferris wheel local X follows the existing mapped longest-axis direction. Base/DEM adjustment uses the established prop path; simulation, activity and collision data remain server-owned.

## Camping props

Travel Trailer and Station Wagon from Grab3D Cozy Cars, and A-Frame Tent from Cozy Camping & Outdoor, are CC0 1.0 public domain. Unchanged GLBs and exact source URLs, hashes, measured bounds and static transforms are recorded in `travel_trailer.json`, `station_wagon.json`, and `a_frame_tent.json`. Original Grab3D manifests (`*.source.json`) and notices (`*.LICENSE.txt`) accompany the full `CC0-1.0.txt`. Credits appear in Finnish, English and German.

The tent retains all guylines and open doors within 3.2 × 2.4 m. The trailer and car share one uniform fit within 9.4 × 2.5 × 2.5 m, with the authored coupler meeting the car rear bumper. Standalone trailer fits 6.2 × 2.5 × 2.5 m. Runtime +90° Y rotation faces local +X; rows retain existing yaw and per-vertex terrain grounding. Existing `vehicles/camper_van.glb` is reused for static campers only, uniformly fit to the positive row length, 2.5 m width and 2.9 m height. Untextured camper surfaces have zero UVs and generated orthogonal tangents.

## Picnic Table

[Picnic Table](https://grab3d.com/models/furniture/picnic-table/), Grab3D Cozy Playground & Gym; unchanged GLB downloaded 2026-11-18 from https://grab3d.com/dl/picnic-table/picnic-table.glb. CC0 1.0; full legal text in `CC0-1.0.txt`, original notice/manifest in `picnic_table.LICENSE.txt`/`picnic_table.source.json`. Hash, measured dimensions and runtime transforms in `picnic_table.json`. Source GLB unchanged; baked child transforms and ground-centred origin. Uniform envelope fit. Finnish, English and German in-game credits name the source.

## Urban Street: Street Light and Bollard

Grab3D Urban Street Kit, retrieved 2026-11-24. Exact source/download URLs, unchanged SHA-256, measured dimensions, source notices/manifests and runtime transforms accompany `street_light.glb` and `bollard.glb`; full CC0 1.0 text is `CC0-1.0.txt`. The sources are credited in Finnish, English and German.

Street Light retains 5,280 triangles in two authored parts/materials (body 5,088; LED 192), dimensions 0.400 × 2.214292 × 8.158134 m. Cached merged source uses uniform scale 7/8.15813446. The LED lower face (source Y 8.03471565, centre X/Z 0/0.77420503) anchors the streamed luminaire point. The measured pole base at source Z -0.90714586 therefore sits 1.4426 m behind that point, grounded on the DEM at its actual base; the light is placed at the same source panel height on slopes. The shared LED material follows existing artificial-light level; nearest-light pool, hysteresis, falloff and broken identities are retained. Chunk MultiMeshes instance the shared immutable geometry; workers build only transforms.

Bollard retains all 1,180 source triangles and its PBR texture/material. Uniform scale 0.9/1.001999974 gives 0.900 m height and 0.17964 m base width. Its square anchor plate stays centred on the mapped bollard and on the DEM. Existing knocked-post filtering removes it. It shares one mesh per chunk batch.

Additional inspected Urban Street candidates: Park Bench is one inseparable 8,656-triangle mesh, 1.80 × 0.70402 × 0.88429 m, seat 0.45 m. Fitting the existing 0.45 m depth requires scale0.639, reducing length to1.151 m and seat height to0.288 m; it also cannot represent backrest=no. Retained the existing bench. Wave Bicycle Rack (`bicycle-rack`, distinct from `bike-rack`) is one inseparable9,996-triangle mesh, 2.075 ×0.150×0.89970 m. At the current0.8 m height its span is1.845 m; reaching existing outer slots±1.2 m requires scale≥1.157 and height≥1.041 m. Retained the corrected four-slot rack rather than distort geometry. These rejected downloads are not shipped.

Other reviewed kit categories: modular roads/curbs/intersections do not fit arbitrary OSM polylines/terrain. Existing bus-stop shelter polygons could support a later shelter fit/access/seat review. The Traffic Light could follow existing authoritative phases after measured lens/front orientation review; fixed-value kit signs cannot replace arbitrary streamed speed limits/directions/country styles. Utility Pole could replace existing power poles only after crossarm/wire-anchor fitting. Utility cabinets, meters, hydrants, mailboxes, notices and decorative clutter need matching authoritative placement/attributes; no new equipment is inferred. A dumpster is not the existing small waste basket, and the parking meter is not the existing EV charging station. Previous railway-crossing/source mismatch remains. Fences/rails would require segment and endpoint fitting; they are later candidates rather than a direct pole replacement.
