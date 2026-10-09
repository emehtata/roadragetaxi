# Godot Parity Phase 9 — Faster Night Rendering

## Objective

Redesign Godot's night presentation for substantially better frame rate while
keeping the important visual cues:

1. one cheap darkness pass
2. batched street-light pools
3. batched vehicle headlight illumination
4. lit windows without a second 3D viewport
5. measured removal of the current night-only bottlenecks

This is a Godot rendering/performance phase. Python already supplies darkness,
light placement, broken lamps, vehicles, and building data; do not change the
simulation or protocol.

Do not combine this with settings, controls, historical weather, gameplay, or
unrelated parity polish.

---

## 1. Measure before changing it

Trace and profile:

* darkness and sun-altitude presentation in `main.gd`
* `night_layer.gd` beam clipping, `tint_pieces`, building retint polygons, and
  redraw conditions
* `entity_layer.gd` headlight generation and vehicle limits
* `map_chunk.gd` street-light fans, overlap subtraction, worker tasks, lamp
  heads, and broken lamps
* `map_layer.gd` pool grouping, visible-road count, lamp queries, and building
  silhouette lookup
* both building viewports in `buildings_3d.gd`
* the godot-18 and godot-21 through godot-23 benchmark history
* existing `--bench-hide` categories, performance counters, and tests

Run a reproducible baseline before editing. Use the same Oulu location,
weather, date/time, loaded chunks, resolution, camera path, renderer, warm-up,
and duration for all comparisons. Record:

```text
average frame ms / FPS
p50, p95, p99, worst frame ms
1% low FPS
main-view render CPU/GPU time
main building viewport CPU/GPU time
lit-window viewport CPU/GPU time
night/headlight CPU time
draw calls and memory
visible vehicles, lamps, lit windows, buildings, and chunks
```

Add narrow counters or hide switches only where needed to attribute darkness,
street pools, headlights, lamp heads, main 3D buildings, and lit windows.
Measure the actual bottleneck rather than assuming one.

---

## 2. Target architecture

Use the smallest rendering path that works:

```text
normal world + one building viewport
                 ↓
one translucent darkness quad
                 ↓
one batched additive light mesh (street pools + headlights)
                 ↓
lamp/vehicle details, lightning, HUD
```

The steady-state night path must have:

* one darkness draw
* one or a small fixed number of light-batch draws
* the primary building viewport only
* no polygon boolean work per frame
* no per-light node, texture, viewport, shadow caster, or `PointLight2D`

This is a deliberate redesign, not pixel-identical Pygame compositing. Keep
night readable and preserve what each light communicates; prefer stable batches
over exact subtractive masks.

Do not add a deferred renderer, normal maps, SDF shadows, screen-copy shader,
full-resolution lightmap viewport, or lighting plugin. Those recreate the
fill/composite cost this phase must remove.

---

## 3. Replace polygon-subtracted darkness

The current `NightLayer` subtracts moving beams from the view with
`Geometry2D`, splits polygons to remove holes, clips beams against building
silhouettes, and redraws the pieces. Remove that runtime path.

Draw darkness as one rectangle/quad:

* keep the dark-blue tint and authoritative `calendar.darkness` fade
* retain the sparse-road extra-darkness rule only if its measured cost is
  negligible; otherwise cache its existing 0.1-second result
* hide the item at zero alpha
* resize without rebuilding a node tree
* preserve underground behaviour
* keep lightning above the world tint and below UI

Delete `tint_pieces`, `_subtract`, hole detection, beam retint polygons, and
building silhouette clipping when unused. Remove the per-frame `buildings_in`
query from the night path.

Do not use `CanvasGroup` or a screen-sized intermediate: godot-18 already
measured that approach at roughly 20 ms per night frame on llvmpipe.

---

## 4. Batch headlights as additive geometry

Reuse current interpolated positions, headings, engine state, bridge/covered
checks, short/long-beam rules, and vehicle cap. Change only presentation.

Put all visible headlight cones in one packed triangle submission on one
reusable canvas item:

* two lamps may share a combined trapezoid/fan when visually sufficient
* preserve short and long reach
* use a warm pale additive colour tuned against the new tint
* add at most a few vertex-alpha bands if a gradient materially helps; no
  texture is required
* cull and cap before emitting vertices
* reuse bounded arrays; create no nodes and perform no polygon clipping
* keep beams absent under covered/higher roads under the current rules

It is acceptable for headlights to brighten a facade rather than cut perfectly
around its projected silhouette. A softly illuminated building is preferable
to per-frame boolean clipping. Do not brighten the whole screen or HUD.

Keep the existing small headlamp, tail, brake, and indicator shapes. This
changes illumination cones, not vehicle lamps.

---

## 5. Batch street-light pools directly

Replace chunk fan-overlap subtraction and its worker jobs with direct packed
fan geometry:

* use one array for loaded surface lights, or bounded visible-chunk batches
  only if measurement proves faster
* rebuild only on chunk load/unload, map-level change, relevant zoom change,
  or broken-lamp change
* exclude broken lamps before emitting vertices
* reuse the existing direction and range
* remove `pool_union`, cached boolean pieces, worker tasks, and lifecycle code
  once unused
* show no surface pools underground
* retain lamp heads as one batch, excluding broken heads

Do not subtract overlaps. Tune each fan's low additive alpha so ordinary
overlaps look natural and dense junctions do not turn white. If clamping is
needed, use one batch material/shader—not CPU unions or per-lamp nodes.

The result must remain localized pools along streets, not uniform road glow.

---

## 6. Remove the lit-window viewport

`buildings_3d.gd` currently renders a second full-view pass for lit windows
and black building occluders, then composites it above the tint. Remove that
viewport, camera, sprite, occluder instances, measurement, and composite.

Render selected lit-window geometry in the primary building viewport:

* preserve deterministic selection and current proportions
* keep correct depth/occlusion in the primary camera
* use per-chunk batched meshes, never a node per window
* show/brighten the selected mesh only above the current darkness threshold
* preserve the 0.25-to-0.5 intensity fade
* choose an unshaded/emissive-looking colour that remains visible through the
  single tint
* show ordinary, non-glowing windows by day

Prefer one shared material/uniform and tracked per-chunk lit instances. Do not
rebuild building geometry when darkness changes. If another draw surface is
required, keep it in the same mesh/viewport; do not retain a second camera.

---

## 7. Preserve cheap night details

Keep:

* vehicle lamps and indicators
* broken street lamps staying dark
* pedestrian reflectors and their eligibility rules
* lightning flash and thunder timing
* traffic signals, fuel boards, labels, navigation, and HUD legibility
* seasonal/weather presentation

Profile reflector and `lamp_near` queries. They already inspect nearby chunks;
add a cache/grid only if measurement shows that bounded scan matters. Cull
lights against a modestly grown view before building vertices.

---

## 8. Visual acceptance

The redesign may differ from Pygame, but must satisfy:

1. unlit streets are clearly darker than day
2. the taxi's forward path is readable with headlights
3. moving/turning beams have no trail or lag
4. street lamps form warm local pools and broken lamps leave dark gaps
5. lit windows are visible, deterministic, and correctly depth-occluded
6. dense lamp overlaps do not turn roads white
7. buildings remain readable inside headlights
8. underground/covered areas receive no inappropriate surface light
9. lightning still flashes the full world cleanly
10. dusk causes no pop, hitch, or background geometry-job burst

Capture matched before/after screenshots at dusk, full darkness, a dense city
street, a sparse road, a lamp-heavy junction, beside tall buildings, under a
bridge/cover, and underground. Do not chase pixel parity after these rules hold.

---

## 9. Tests

Add deterministic checks for logic rather than screenshot-testing every colour:

1. zero darkness hides tint and light batches
2. darkness is one quad with no subtraction helpers
3. headlight vertices follow position, heading, range, eligibility, culling,
   covered state, and vehicle cap
4. repeated updates reuse one node and bounded arrays
5. street batches include working loaded lamps, exclude broken/unloaded lamps,
   and rebuild only on relevant changes
6. overlap remains direct fans rather than boolean-unioned pieces
7. pools and heads hide underground
8. lit-window instances use the primary viewport, preserve selection, follow
   darkness intensity, and hide by day
9. no lit-window viewport/camera/composite remains
10. lightning, reflectors, vehicle lamps, resizing, chunk churn, reconnect, and
    daytime rendering still work without orphan nodes/tasks

Run at minimum:

```bash
make godot-test
make godot-selftest
make audio-check
pytest -q tests/test_solar_position.py tests/test_crossings.py tests/test_protocol.py tests/test_server_headless.py
```

Also run the building scene and existing night/headlight visual path. Separate
unrelated pre-existing failures from regressions.

---

## 10. Performance acceptance

Use paired runs matching the baseline. Report raw results and percentages.

Architectural requirements:

* zero polygon booleans in a steady night frame
* zero full-screen intermediate light texture
* one building viewport
* no per-light or per-window nodes
* one darkness primitive
* one or a small fixed number of packed light submissions
* no dusk worker task for pool unions
* bounded headlight vertices and stable node count over a long drive

Measured requirements on the same machine/renderer:

* at least 20% lower median full-night frame time in dense Oulu
* p95 and p99 improve, not merely average FPS
* no dusk hitch from pool generation
* daytime stays within run-to-run noise
* memory does not materially increase

If 20% is not reached, use attribution counters to remove the largest remaining
night-only cost within this architecture. Do not reduce resolution, hide
buildings, reduce world/vehicle counts, shorten view distance, or weaken the
benchmark. Report a sparse-road case too.

---

## 11. Protected systems

Do not change server/protocol state, calendar math, light placement,
broken-lamp gameplay, vehicle beam eligibility, interpolation, building
geometry/projection/FOV, camera alignment, map streaming, physics, traffic,
weather, resolution, or the default 3D renderer.

No dependency or media asset is needed. Delete the superseded renderer code
instead of retaining two night paths behind a permanent switch. Temporary
benchmark switches may remain only when useful alongside `--bench-hide`.

---

## 12. Documentation

Update only the relevant history and rows in
`docs/architecture/godot-pygame-rendering-parity.md`:

* new tint/light batching architecture
* intentional headlight/building visual difference
* removal of pool boolean work and lit-window viewport
* exact paired benchmark method/results
* visual checks and test counts

Tint, street lights, windows, headlights, reflectors, and lightning remain
complete if acceptance holds. Do not re-audit unrelated rows.

---

## 13. Git workflow

Work on `release/v0.16.0g-alpha`. Preserve unrelated changes. Commit and push
after validation and benchmarks. Do not create or push a tag.

---

## Final report

Report the measured old bottlenecks; final tint, light, and window paths; code
and passes removed; intentional visual differences; exact test commands and
results; matched screenshots; paired dense/sparse performance tables including
per-pass timing, draw calls, memory, node/vertex bounds, and dusk hitches; commit
hashes; pushed branch; and confirmation that no tag was created.

Do not start the next parity phase automatically.
