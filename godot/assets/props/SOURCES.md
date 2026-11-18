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
