# Surface colours and close-zoom detail

OSM `surface=*` controls both road/path colours and the paved areas used for
pedestrian plazas, parking and forecourts. Untagged and unknown surfaces keep
their existing road-class or area fallback. No simulation or grip rules change.

The palette uses lighter warm grey for concrete, neutral granite grey for sett,
darker natural grey for cobblestones, light greige for paving stones and muted
brown-grey for gravel. This reduces the former yellow cast and separates these
materials without turning the map into a categorical colour chart. Colours are
material approximations: OSM does not specify the actual colour of each stone.

At close zoom a shared procedural shader adds aggregate grain, paving joints,
cut sett blocks, rounded cobbles, concrete joints, wood planks, grass-paver cells
and a subtle metal pattern. The nine pattern families are defined in
`map_style.SURFACE_TEXTURES`; the shader reads the family from per-vertex UV data.
Roads remain in their existing batched triangle arrays; paved polygons retain
their original draw order. Forest canopy, markings and weather overlays keep
their separate rendering layers. Flat/untextured batches allocate no UV array.

Detail fades in between **12 and 24 pixels per metre**. At the normal 9 px/m
view only the base palette is visible. Patterns use the map's common metre
coordinates, so they remain fixed during camera movement and continue across
chunk boundaries. Road snow suppresses the pattern, including the existing
ploughed/snowy segment redraws; rain darkens it through the existing wet overlay.
Paved-area snow/wetness behaviour is unchanged. Pattern orientation is a generic
world-aligned approximation, not an OSM survey of how the paving was laid.

Validation on 2026-10-28:

- 199 relevant Python tests passed: palette, road and footway encoding, paved
  area clipping, kerbed redraws, static world and map-level separation.
- 3,558 Godot checks passed; the existing suite reports shutdown cleanup leaks.
- The rendered `godot/tests/surface_details.gd` checks UV batching, flat distant
  surfaces, close material variation on roads and pedestrian areas, camera-pan
  stability, chunk seams, wet concrete darkening and snow suppression.
- Existing road-stroke and wet-road pixel comparisons passed (maximum channel
  differences 1/255 and 0 respectively), as did the existing snow render test.
- Inspected normal/close, wet and snowy comparison screenshots. The session
  previews are `/tmp/rrt-surface-{9,27,wet,snow}.png`.

No bitmap asset pack or new dependency was added. Rendering was checked using
Linux Godot 4.7.2/OpenGL with Mesa; native GPU performance was not benchmarked.
