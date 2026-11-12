# Animal model sources

Close-range (detail 1, within 40 m) animal meshes from [grab3d.com](https://grab3d.com),
downloaded 2026-11-08. Each `<name>.manifest.json` is the verbatim grab3d manifest
(the licence record). Far animals and every other species keep the procedural shape.

| Local file | grab3d slug | Licence | Triangles | Note |
| --- | --- | --- | --- | --- |
| `fox.glb` | `low-poly-fox` | CC0-1.0 | 2999 | |
| `small_bird.glb` | `low-poly-bird` | CC0-1.0 | 1990 | European robin, 0.139 m long (mesh bounds); drawn 0.3 m long to read on screen |
| `roe_deer.glb` | `low-poly-deer` | CC0-1.0 | 2996 | a deer, accepted for roe deer |
| `horse.glb` | `low-poly-horse` | CC0-1.0 | 2996 | |
| `hare.glb` | `low-poly-rabbit` | CC0-1.0 | 2999 | a rabbit, used for the hare; `ai_content: true` like the others |

CC0 needs no attribution; credit grab3d.com as a courtesy.

AI content: grab3d's manifests say every model is an AI-assisted derivative (base
mesh and textures from Meshy image-to-3D, reduced to low poly with a palette
texture in Blender), `ai_content: true`. The user approved this.
