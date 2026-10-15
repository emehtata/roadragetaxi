# Weather, traffic and FPS: measured optimization plan

Status: **analysis only; no runtime optimizations implemented**.
Measured on 2026-10-14, branch `release/0.17.0alpha`, code
`ccb35766bf6dfca7f5f50cd6b6bd8b1eec437bba`.
This includes Finnish-priority yielding, sidewalk parking rejection, road snow,
ploughing, snowy tyre tracks and their subsequent snowfall fading.

## Findings and recommended order

1. **Road snow invalidation creates periodic client hitches.** Both snowfall
   repetitions produced ten frames above 66.7 ms in roughly ten measured seconds.
   Snow/ploughed-road p99 reaches 140 ms. Road drawing instrumentation confirms
   repeated rebuilds, including roads whose visible snow amount has not changed.
2. **Sidewalk-aware parking selection defeats server work budgets.** The driving
   run catches 212–253 ms CPU-bound ticks in candidate selection and walkway
   overlap checks. This is a new correctness feature with a costly eager scan,
   not a reason to allow parking on sidewalks again.
3. **Tyre-track fading repeatedly rebuilds the entire trail.** A synthetic
   4,000-point trail costs about 22 ms per rebuild, roughly four times per second
   while snow falls, plus significant render cost when all marks overlap on screen.
4. **The 3D building pass and night/wet rendering reduce steady FPS.** Disabling
   3D buildings for diagnosis saves about 5 ms/frame in a fixed-actor scene.
   Street-light pools save only about 1.6 ms/frame in that comparison.
5. **Streaming still delays state delivery.** The 60-second drive has 17
   interpolation-freeze episodes, ten gaps above 100 ms and young-GC spikes up to
   91.7 ms. Existing full-GC tuning works: zero full collections in the drive.

First fix work/invalidation granularity; then address steady rendering cost.
Do not remove street lights, snow, lawful yielding or sidewalk checks to improve
the benchmark. Do not increase interpolation delay as the primary fix.

## Environment and what the measurements mean

- AMD Ryzen 5 5600X, 6 physical cores / 12 logical CPUs, WSL2, Python 3.12.
- Godot 4.7.2, compatibility renderer, actual X11 rendering at 1280×720.
- Renderer: **Mesa llvmpipe, LLVM 20.1.2**, OpenGL 4.5 / Mesa 25.2.8.
  This is software rendering, **not a measurement of the user's hardware GPU**.
  Disabling VSync was requested; the driver reported it could not change VSync.
  Therefore absolute FPS is specific to this environment. Relative attribution
  and measured CPU stalls are useful; hardware-GPU savings must be revalidated.
- Real Oulu map from local Finland PBF/caches: 8,851 ways, 2,767 world buildings;
  client loaded 49 chunks, 2,713 rendered buildings, 135,930 windows and 15,859 lit
  windows according to existing counters. Default 3D buildings, no label overlay.
- No historical-weather requests or live train timetable in the weather matrix;
  Dummy audio driver. Audio device cost is not measured.
- Existing `Perf` reports include main-render and 3D-subviewport intervals.
  **Do not add overlapping render CPU/GPU/subviewport times as independent costs.**
  The software driver's GPU-labelled monitor is not hardware GPU utilization.

The stationary matrix ran ten conditions twice, 15 seconds each, discarding the
first five seconds of client frames and resetting section counters after warm-up.
The clock was held at each scenario's selected local date/time. Temperature and
precipitation were explicitly set; output records the **actual** weather and
temperature. Snow started at 3 cm; snowfall accumulated normally at game time
60×. The taxi remained stationary while NPCs and pedestrians continued updating.

Population evolved during the first pass (10→40 vehicles), so its FPS differences
must not be attributed entirely to weather/time. The second pass retained 40
vehicles, although active/crashed/parked distributions still evolved. Its results
are shown below; both passes and counts are retained in the raw evidence.
This is not a fresh, identical driving fleet for every condition.

Controlled layer comparisons use a separate warmed scene with **25 frozen NPC
actors (19 classified driving)** and frozen pedestrian updates, identical across
its variants. This isolates presentation cost; freezing actors is **diagnostic
only**, not a proposed production optimization. Their absolute FPS must not be
compared directly with the 40-vehicle live matrix.

The track stress case injects 4,000 full-strength, four-wheel snow-track points
in a repeated 25 m-radius circle. It deliberately stresses the existing buffer
limit and dense on-screen overdraw; it is not representative of a spread-out
ordinary drive. Long-running track burial at 120 seconds was not benchmarked.

## Time and weather results

Second pass; frame intervals in milliseconds. All weather types below were
verified in the server state. Winter noon is low sun, not summer daylight.

| Local date/time / condition | Sun altitude | Avg FPS | Median frame | p99 frame | Worst frame | Frames >66.7 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| July 1, 12:00, clear | 46.06° | 31.9 | 31.2 | 37.0 | 38.2 | 0 |
| September 1, 06:00, clear | −1.08° | 29.5 | 33.7 | 38.3 | 38.6 | 0 |
| September 1, 20:00, rain, fully wet | 2.66° | 25.6 | 38.7 | 45.6 | 48.7 | 0 |
| January 1, 23:00, clear | −45.98° | 26.5 | 37.3 | 45.4 | 50.9 | 0 |
| September 1, 23:00, thunderstorm | −12.86° | 23.3 | 42.3 | 49.7 | 50.4 | 0 |
| January 1, 12:00, slush, fully wet | 1.88° | 25.6 | 38.8 | 43.2 | 43.8 | 0 |
| January 1, 12:00, falling snow, initially 3 cm | 1.88° | 23.7 | 38.4 | 130.4 | 131.7 | 10 |
| January 1, 23:00, falling snow | −45.98° | 20.3 | 43.7 | 132.7 | 145.4 | 10 |
| January 1, 12:00, snow + partially ploughed cells | 1.88° | 21.9 | 40.9 | 140.1 | 147.6 | 10 |
| January 1, 12:00, snow stopped + same cleared-cell pattern | 1.88° | 25.2 | 39.3 | 46.0 | 48.6 | 0 |

The partially ploughed cases seed 560 nearby 10 m cells in a deterministic pattern,
representing fragmented clearing without waiting for tractors to visit every cell.
Natural tractor clearing remains enabled in the live matrix.

The clearest regression is **p99 under active snow**, rather than the small
differences between particle types. Stopping snow removes the periodic long
frames while retaining road-snow state and nearby cleared-cell records.

## Controlled attribution

One run per variant, about ten seconds measured after warm-up; same frozen actors.
Layer removal here is an experiment, not an implementation recommendation.

| Variant | Avg FPS | Avg frame | p99 frame | Observation |
| --- | ---: | ---: | ---: | --- |
| Summer clear, complete scene | 41.2 | 24.25 | 27.59 | Baseline |
| Same, 3D building pass disabled | 51.8 | 19.31 | 23.77 | About 4.94 ms saved |
| Winter night, complete scene | 35.6 | 28.13 | 31.55 | Night baseline |
| Same, street-light pools hidden | 37.6 | 26.57 | 32.44 | About 1.55 ms average saved; no p99 improvement in this short run |
| Same, 3D building pass disabled | 43.5 | 23.01 | 25.39 | About 5.12 ms saved |
| Dusk rain, precipitation/ripples hidden | 30.6 | 32.63 | 37.16 | Still expensive; no matched rain baseline in this frozen-scene set, so no isolated FPS gain claimed |
| Falling snow + partially ploughed cells | 24.8 | 40.36 | 133.41 | Road draw callbacks: 640 calls, 776.72 ms total, 11.57 ms largest individual callback |
| Falling snow + 4,000 track points | 15.5 | 64.61 | 158.55 | Tracks: 35 redraws, 22.04 ms average / 31.23 ms max; roads: 744.72 ms total |
| Snow stopped + 4,000 track points + cleared cells | 19.4 | 51.66 | 61.82 | Track geometry rebuilt once, 20.66 ms; persistent dense-trail rendering still expensive |

Road callback totals are across all road layers/chunks. About 777 ms over ten
seconds is about 78 ms of redraw CPU work per second, concentrated around snow
updates. The largest **whole frame** is larger than any single callback because
many chunk road layers redraw together. This work was absent from the original
section names; the temporary diagnostic client wraps their existing draw callbacks
to measure it without changing game source.

In the live second pass, particle draw CPU is only approximately 0.09 ms for rain,
0.10–0.11 ms for snow and 0.16 ms for slush. These numbers cover particle drawing,
not all native rendering. The 100+ ms periodic snow hitch cannot reasonably be
explained by that particle CPU cost alone.

## Server and driving jitter

Existing `tools/bench_map_jitter.py`, northbound, requested 120 km/h for 60 seconds,
local PBF, caches left intact. Actual simulated displacement: 1.95 km. Some tiles
missed caches and required indexed local PBF extraction; this is a mixed-cache
drive, not a pure warm or fully cold benchmark. It moves the taxi along a line to
stress streaming, not a lawful path-following drive. Default timetable behavior
was retained here, unlike the controlled weather matrix.

| Measure | Result |
| --- | ---: |
| Tick median / p95 / p99 / max | 7.4 / 20.7 / 51.0 / 252.8 ms |
| Map idle p99 / max | 38.0 / 116.5 ms |
| Map busy p99 / max | 57.7 / 252.8 ms |
| Ticks >100 ms | 5 |
| State-arrival p99 / maximum gap | 79.2 / 279 ms |
| Gaps >100 ms | 10 |
| Interpolation replay freeze episodes / total frozen | 17 / 2.6 seconds |
| Replay frames >5% off nominal movement rate | 15.3% |
| Clock snaps | 0 |
| Full GC | 0 |
| Young GC count / max / total | 254 / 91.7 / 791 ms |
| Young collections >10 ms | 18 |
| Chunks sent / resends | 32 / 6 |

The replay models the existing state buffer at 60 FPS and never misses its own
render frame. These are **simulation/network interpolation stalls, not rendered
Godot FPS**. A client can display regular frame intervals while its cars freeze.

Of 2,482 ms in ticks above the 33.3 ms tick budget, phase accounting attributes
2,274 ms to simulation, 70 ms to map sync, 28 ms to chunk swap/resend and 18 ms to
tile merge. Those are nested phase totals, not independent costs to sum again.

The 253 ms CPU-bound tick at 18.7 s and the 212 ms tick at 16.5 s sample stacks in:

```text
NPCVehicleManager.update → _run_population_tick
  → _pick_npc_destination_candidates → _parking_overlaps_walkway
  → _way_at_point / SpatialWayGrid.ways_in_rect
```

Another 253 ms tick at 5.2 s used only 21 ms thread CPU: much of its wall time was
waiting, so its sampled tree-collision stack is **not proof** of a 253 ms tree
algorithm. Background work/GIL contention and collections need separate tracing.

An independent early-population cProfile sample of 180 ticks reports 2.86 s total,
1.25 s cumulative parking candidate selection, 1.18 s cumulative walkway overlap,
3,914 overlap calls and 65,866 `ways_in_rect` calls. This confirms the allocation/
query-heavy early-population path. cProfile adds overhead; these are attribution
figures, not unprofiled per-tick latency estimates.

Later 180-tick steady profiles are less dominated by population filling. For
example, ploughed snow: 1.81 s total, 0.81 s in NPC update, 0.40 s broadcast/state
construction, and 0.36 s cumulative `ways_in_rect`. Costs are nested. Sending
cleared cells adds measurable serialization work, but is not the leading server
stall in these runs.

## Root causes in current code

| Culprit | Evidence and code path | Confidence |
| --- | --- | --- |
| Global snow changes invalidate static roads | `godot/main.gd` calls `MapLayer.set_road_snow`; depth changes propagate to every loaded chunk, queuing every road layer. `_draw_roads` rebuilds road surfaces and markings even after global cover saturates. In chunks with cleared cells, it resamples every road segment at 2 m intervals and reconstructs arrays. | High: repeated hitches plus direct callback timing |
| Eager walkway checks before candidate limit | `npc.py:_pick_npc_destination_candidates` validates all sorted candidates in a list comprehension and only then slices to `limit`. Each candidate repeats nearby-way queries, heading lookup and footprint intersection work. Population top-up calls this synchronously; a generator yield cannot preempt a long call inside it. | High: unprofiled driving stacks and independent cProfile |
| Full-buffer track geometry rebuild/fading | `godot/entity_layer.gd:_lay_track`, `_draw_tracks`: snowfall requests redraw every 0.25 seconds; all retained points recreate four tyre-line segments and colors. Dense geometry also remains expensive to render when cached. `_bury_tracks` repeatedly pops the front of arrays. | High for redraw cost; front-pop retirement cost is inspection-only |
| Buildings rendered through a 3D subviewport | `godot/buildings_3d.gd`, main viewport/composite. Static camera does not inherently eliminate the building pass. | High on this software renderer: matched layer comparisons |
| Night/wet steady draw workload | `godot/entity_layer.gd`, light pools, wet overlays, main renderer. Live entity drawing reaches ~7 ms average; night/wet native render cost grows. Pools are a smaller contributor than removing buildings. | Measured aggregate; individual contributions require further controlled pairs |
| Allocation/GIL/young-GC pressure during driving | Repeated candidate queries, temporary lists/geometry and growing world bookkeeping. Streamer reports background waits and young collection spikes. | High for observed stalls; precise allocation ownership still needs tracing |
| Repeated plough-state distribution | `protocol.py` serializes nearby cleared cells; `MapLayer.set_road_snow` distributes cell arrays across chunks, which scan/filter them. | Measured smaller server cost; scaling risk supported by code |

## Optimization plan — not implemented

Each step should be an atomic change, measured against the same scene and followed
by its correctness tests. Targets below are acceptance goals, not promised FPS.

| Order | Proposed work | Acceptance and safeguards |
| --- | --- | --- |
| 1: server spikes | Stop scanning parking candidates once the requested number of **valid** nearest candidates is found. Budget candidate validation itself in the route/population job; cache static heading/walkway evidence with map-revision and vehicle-dimension keys. | No ordinary parking query exceeds a 2–4 ms work slice; steady server p99 <33.3 ms and no CPU-bound population tick >100 ms. Preserve full-footprint sidewalk prohibition, candidate order, fallback behavior, large vehicles, layers and async rechecks. |
| 2: snow hitches | Precompute road-segment/cell geometry once per chunk revision. Invalidate only chunks/cells with changed **visible** coverage; cap/bucket rendered snow rather than dirtying every road after snow is already fully white. Separate snow changes from unrelated road-marking rebuilds. Use bounded redraw work. | Active snow and fragmented ploughing no longer generate ~1 Hz frames >66.7 ms; total snow-update CPU <5 ms/frame target. Preserve snowy/ploughed appearance, bridges, new clean areas after snowfall stops, subsequent accumulation and melt. |
| 3: tracks | Reuse/cache tyre geometry in bounded trail sections. Update fade without reconstructing every point's geometry (evaluate a shared fade shader or section alpha before choosing). Batch retirement rather than repeated `pop_front`; cull offscreen sections, while retaining visible continuation and wheel spacing. | Near-capacity track draw CPU <5 ms target; no fade-driven 20–30 ms rebuilds; stationary unchanged trails do not rebuild. Benchmark both dense stress and normal spread-out driving. Preserve fade/burial, front/rear marks and buffer limits. |
| 4: serialization/allocation | Send cleared-cell revisions/deltas or compact changed chunks instead of repeatedly rebuilding the same nearby-cell data. Reuse static query results/temporary buffers where profiling confirms ownership. Instrument young-GC intervals and allocations before tuning thresholds further. | Lower allocation/parse cost with correct reconnect, late-joining chunks and streaming. No missing plough updates; young-GC pauses <10 ms target. Do not disable GC or freeze the whole evolving world without a measured memory/lifecycle audit. |
| 5: steady render cost | Make static building-subviewport updates depend on camera, visible geometry, lighting/window changes; evaluate quality-preserving resolution/LOD only after testing. Profile wet overlays and lighting in matched scenes. Keep existing street lamps and roof/bridge lighting constraints. | Aim for rendered p95 <33.3 ms here and <16.7 ms on the user's GPU if feasible. Revalidate moving cameras, night transitions, window lights, roof occlusion, map growth and visual quality. No promise of 60 FPS from this software-renderer study. |
| 6: streaming remainder | Re-run mixed/warm/cold routes after 1–4. Trace wall-vs-thread-CPU stalls and oversized work units; maintain existing out-of-process tile building and budgeted sync/chunk preparation. | No state gap >100 ms or interpolation freeze in a warmed repeat of the route; explicit cold-load bounds. Keep cache protections, no incomplete tiles, and no duplicated sync/resend storms. |

Avoid starting with particle-count cuts: measured particle draw CPU is small.
Avoid multicore refactors until work boundaries and allocations are fixed; threads
sharing the Python GIL do not make a long synchronous candidate scan interruptible.
Avoid declaring victory from average FPS while p99 or state gaps still regress.

## Validation after implementation

Repeat the matrix with controlled actor counts and movement traces, at least
60 seconds measured after warm-up and three repetitions. Run on the actual
hardware GPU, with renderer/device and VSync settings recorded. Include:

- stationary and driving camera, zoomed-out view, day/dawn/dusk/night;
- clear/rain/thunder/slush/falling snow/stopped snow/fragmented ploughing;
- no tracks, realistic long driving trails, maximum buffer, and >120 seconds of
  snowfall to measure burial rather than just fading;
- warm/mixed/cold streaming without deleting the player's caches;
- server tick p95/p99/max, arrival gaps, replay freezes, client frame p95/p99/max,
  draw counts, memory, GC pauses and actor/chunk counts;
- Finnish priority, STOP/turning/pedestrian duties and full-body sidewalk parking
  rejection, plus visual regression screenshots for roads/lights/bridges/tracks.

Memory counters in current output are end-of-run Godot static memory, not a complete
server/client peak-RSS or leak study. Snapshot phases and retirement need a longer
memory run. Initial warm-up frames are excluded from client FPS; existing server
tick summaries include startup delivery within each scenario. No hardware GPU,
fully cold graphical drive, audio output or 120-second track-retirement result
is claimed here.

## Evidence and reproduction

Raw reports and diagnostic-only harnesses:
[weather-traffic-2026-10-14-data](weather-traffic-2026-10-14-data/README.md).
The earlier temperature-injection probe that mislabeled rain/slush as snow was
discarded. Only the corrected, condition-verified matrix is included. The separate
early-population profile was a clear-weather probe; its parking CPU attribution
does not depend on precipitation temperature.

The runtime source remained unchanged throughout this analysis. Diagnostic layer
hiding, callback timers, actor freezing and trail injection exist only in the
supplied standalone benchmark driver, not the game.

## Implementation progress — 2026-10-15

First atomic step: parking selection now stops after the requested number of
**valid** nearest candidates, rather than checking the entire chosen tier before
slicing. Candidate collection and footprint validation yield to the existing
route-job scheduler. Synchronous trip continuation and population top-up use
their existing deadline during selection too; top-up requests only the single
candidate it actually consumes. Timeout returns no incomplete result and does
not reserve a space. Tier precedence, distance order, full-footprint sidewalk
checks and layer separation are unchanged. Existing job completion checks still
reject stale graph revisions and newly occupied/reserved destinations.

Controlled selection comparison against `454221d`, using the same loaded Oulu
world (8,851 ways, 2,767 buildings, 1,643 parking spaces), 100 query points from
`random.Random(20261014)` with independent x/y offsets uniformly sampled within
±400 m of the initial taxi position, default radius and limit:

| Selection time | Before | After |
|---|---:|---:|
| Median | 6.088 ms | 1.240 ms |
| p95 | 23.909 ms | 2.077 ms |
| Maximum | 26.601 ms | 2.567 ms |
| Total, 100 searches | 938.632 ms | 123.761 ms |

All 100 returned candidate lists were identical. Both functions ran in the same
process and world; the old function body was loaded from Git into the current
module's namespace for the comparison. A separate 1,064-space synthetic case
fell from 6.038 ms to 1.915 ms median over 30 searches (identical results).
These are selection measurements, not rendered FPS or an end-to-end tick bound.

Regression coverage includes skipping invalid nearest spaces, stopping once
enough valid spaces are found, yielding during collection/validation, timeout
without reservation, indexed/unindexed sidewalk rejection and layer separation.
Full Python suite: **1,414 passed, 2 skipped**, with localhost sockets enabled.

A 60-second northbound Oulu PBF drive at 120 km/h (1,999 m, 1,799 ticks) recorded
tick median/p95/p99/max of 7.9/18.9/27.6/45.7 ms, no ticks over 50 ms, no client
interpolation freezes, and maximum state gap 64 ms. Raw output:
[parking-optimization-driving.json](weather-traffic-2026-10-14-data/parking-optimization-driving.json).
Command: `PYTHONPATH=src .venv/bin/python tools/bench_map_jitter.py --preset Oulu
--osm-source pbf --drive-s 60 --speed 33.333333 --heading 1.5708 --sample-ms 45`.
This is a regression smoke check, **not a controlled before/after**: existing
map caches were reused and test-suite runs overlapped the benchmark. It uses a
socket client rather than a rendered Godot client; it cannot establish FPS gains
or prove all early-population stalls are eliminated.

Deferred: static geometry caching (not yet justified by these measurements),
snow redraw, tyre-track rendering and the remaining plan phases. A single
geometry query, index rebuild or sort remains non-preemptible; yielding between
candidates is not a hard real-time guarantee. Hardware-GPU FPS improvement is
not established by this first step.
