# Server footprint checks and wet-road drawing, 2026-10-27

Two small optimizations, preserving server authority, map layers and existing
collision clearance. No change to tick rates, population, visual detail or dependencies.

## Server

A 900-tick, 30 Hz simulated drive through Oulu (427400, 7210500; east at 8 m/s;
10 simulated seconds warm-up, 30 measured; seed 1; start 2026-10-23 17:00)
identified NPC routing/footprint validation as a substantial cost. Under cProfile,
mean tick wall time was 7.42 ms; p95 14.63 ms; p99 22.89 ms. This is a headless
back-to-back simulation workload, not a real-time rendered driving benchmark.

Spatial grids return entire obstacle polylines. `is_vehicle_pose_valid` formerly
computed exact segment distances even for individual edges far from the car.
It now rejects edges outside the footprint's clearance-expanded bounding box,
then runs the same exact distance test on every remaining edge. Crossing edges,
rotated/long vehicles, building closing edges and clearance are retained.

A same-call replay ran the previous and new validator on **2,040 identical calls**
during real-map warm-up and driving, asserting equality on every result:

| Validator | Total time |
| --- | ---: |
| Previous | 747.64 ms |
| With edge bounds rejection | 87.63 ms |

That is 8.53x faster for this validator (88.3% less measured time), not an
8.53x whole-server speedup. Separate profiled before/after drives averaged
7.42/7.80 ms per tick and had different entity/route workloads and host contention;
no overall tick-speed claim is made. cProfile timings include profiler overhead.

Raw summaries are in [2026-10-27-load-and-render/](2026-10-27-load-and-render/).
The replay compared the previous Git version of the function with the working
version, using identical positional/keyword arguments, timed with perf_counter.
The initial audit driver is an existing local diagnostic under
`rrt-019-sim-audit-data/bench_sim.py`; it is not added by these changes.

## Client

Godot 4.7.2 Compatibility, 1280x720, zoom factor 0.5, Oulu at night, road wetness
forced to 1. The host uses Mesa llvmpipe software rendering, not a hardware GPU.
The first live baseline averaged 70.64 ms/frame with 3,069 draw calls. A live rerun
had different precipitation and lighting state and is not an A/B comparison.
Layer-isolation probes identified wet-road drawing as a useful target. Disabling
other layers was diagnostic only; the production game retains them.

Straight two-point wet-road strokes of the same width now use draw_multiline
instead of separate draw_polyline commands. Curved paths, clipping, bridge layers,
darkening and sheen remain on their existing paths. This changes submission
batching only; it does not remove the wet-road effects.

The controlled rendering comparison freezes processing on one loaded live-game
snapshot, switches the wet-overlay draw callbacks between the old and new
implementations, waits one second, then measures four seconds per variant in
alternating order. Raw paired results are in `wet-render-pairs.json`.

The final isolated pairs measured:

| Variant | Mean frame, pair 1 | Mean frame, pair 2 | Draw calls |
| --- | ---: | ---: | ---: |
| Previous | 45.09 ms | 44.66 ms | 5,229 |
| Batched | 44.99 ms | 44.94 ms | 5,105 |

Draw calls decrease by 124 (2.37%) per frame. Mean frame time is effectively
unchanged (44.87 vs 44.96 ms). No FPS improvement is established on this
software-rendering host, and no hardware FPS gain is claimed.

## Validation

- 338 Python checks across NPC movement/population, server ticks, footprint,
  sidewalk parking, manoeuvres and crossing priority: passed.
- A seeded geometry regression compares the optimized validator with exhaustive
  edge distances for 200 randomized poses, both open and closed obstacles.
- 3,486 Godot client checks: zero failures (the existing runner emits resource
  cleanup warnings at exit).
- `godot/tests/wet_road_batching.gd` renders old/new strokes to textures and
  compares pixels: zero changed channels across 172,800 channels on this host.
  Includes mixed widths, crossings, a bent road, clipped chunk edges, a bridge
  road excluded from surface drawing, and a non-drivable road.
- Changed GDScript parse check, Python compile check and git diff check passed.
- Real game night/wet screenshot rendered and visually inspected.

## Limits and next measurement

This pass does not establish an end-to-end FPS improvement or complete the
proposed dense-city/map-boundary/weather matrix. The next useful measurement is
a fixed-route run on the target hardware, reporting client CPU/GPU times and
server p95/p99 separately. Avoid adding worker processes, lowering safety update
rates or removing visual detail without evidence from that run.
