You are working on the Road Rage Taxi / The Road Rage Trip repository:

https://github.com/emehtata/roadragetaxi

**Current branch:** `release/0.15.0alpha`

# Objective

Investigate the remaining large frame-time spikes after the incremental map synchronization work from `bin-loader-v3`.

**This is a profiling and investigation task, NOT an optimization task.**

Do not change production behavior unless a minimal instrumentation change is required.

The previous versions established the following:

### bin-loader-v1

Road rendering was independently benchmarked and found not to be a meaningful bottleneck:

```text
Stationary:       ~0.40 ms average
~40 km/h:         ~0.45 ms average
~110 km/h:        ~0.53 ms average
```

The existing road renderer already has:

- spatial culling;
- static render caching;
- camera-relative caching;
- incremental rebuilds;
- a ~4 ms render rebuild budget.

### bin-loader-v2

Full-frame profiling found the original major stall:

```text
map_sync:pedestrians       ~3218–3260 ms
map_sync:spatial_grid     ~1719 ms
map_sync:taxi              ~410 ms
map_sync:traffic           ~180 ms
```

The dominant cause was synchronous map synchronization after a large tile-streaming batch arrived.

### bin-loader-v3

Map synchronization was made incremental.

The results are now approximately:

```text
Metric                                      Before          After
-----------------------------------------------------------------------
map_sync:pedestrians worst frame           ~3220–3260 ms   ~85–300 ms
map_sync:spatial_grid worst frame          ~1719 ms        ~9–11 ms
Worst overall frame                        ~3048–3260 ms   ~440–560 ms
```

Average incremental synchronization work is now approximately:

```text
pedestrians:    ~5–6 ms
spatial_grid:   ~4.7 ms
```

The implementation also eliminated redundant pedestrian synchronization and reduced the **total amount of synchronization work**, not merely spread the same work over more frames.

The remaining reported synchronous stages are:

```text
map_sync:taxi
map_sync:traffic
```

and there is also a known first-cache-build cost after a fresh world/tile load.

---

# Critical requirement

**Do NOT optimize anything yet.**

The current ~440–560 ms worst frame must first be decomposed.

The task is to answer:

> What exactly is consuming the remaining 440–560 ms frame?

Do not assume it is:

- taxi;
- traffic;
- rendering;
- cache building;
- map synchronization;
- garbage collection;
- tile loading.

Measure it.

---

# 1. Inspect the existing profiler

First inspect the existing profiling infrastructure.

Find and understand:

- `FrameProfiler`;
- F3 performance HUD;
- all `map_sync:*` sections;
- all `render:*` sections;
- tile streaming profiling;
- world-cache profiling;
- NPC profiling;
- routing profiling;
- simulation profiling;
- any existing frame-time histogram/statistics;
- `FPS_OPTIMIZE.md`;
- the benchmark created in the previous tasks.

Do not create a parallel profiling framework if the existing one can be extended.

---

# 2. Reproduce the exact V3 scenario

Use the same dense Oulu scenario used for `bin-loader-v2` and `bin-loader-v3`.

Use:

- real Oulu data;
- real local PBF/BIN-backed road data as currently configured;
- warm world cache;
- dense urban area;
- real tile streaming;
- same camera/player setup if the existing benchmark specifies one.

Do not switch to a synthetic dataset.

The purpose is to explain the already observed 440–560 ms spike.

---

# 3. Capture complete frame breakdown

The existing profiler currently aggregates many operations.

For the frames containing the large spikes, capture the complete breakdown.

At minimum determine:

```text
Frame time
    ├── tile fetch/loading
    ├── map synchronization
    │    ├── pedestrians
    │    ├── spatial grid
    │    ├── taxi
    │    └── traffic
    ├── rendering
    │    ├── roads
    │    ├── buildings
    │    ├── scenery
    │    ├── vehicles
    │    ├── pedestrians
    │    └── other
    ├── simulation
    ├── NPCs
    ├── routing
    ├── cache construction
    ├── garbage collection
    └── other
```

Use the project's actual profiler categories where they differ.

Do not invent categories that are not measured.

---

# 4. Identify the exact 440–560 ms frame

This is the most important part.

Find several actual frames with:

```text
> 400 ms
```

and preferably:

```text
> 500 ms
```

For each one, record:

```text
frame number
frame time
player position
camera position
tile event
map-sync state
largest profiler section
```

Determine whether all large spikes have the same cause.

Do not rely on a single frame.

---

# 5. Determine whether the spike is caused by map synchronization

The V3 implementation reduced most map-sync work to approximately 4 ms chunks.

Verify whether that is actually true for the worst frames.

Specifically inspect:

```text
map_sync:pedestrians
map_sync:spatial_grid
map_sync:taxi
map_sync:traffic
```

For each stage report:

```text
average
P95 if available
P99 if available
maximum
```

Pay particular attention to whether the old `pedestrians` or `spatial_grid` stall still occasionally occurs as one indivisible operation.

If a single sub-operation takes hundreds of milliseconds, identify the exact function responsible.

---

# 6. Investigate taxi and traffic

Do not assume these are responsible simply because they remain synchronous.

Measure:

```text
map_sync:taxi
map_sync:traffic
```

during the actual >400 ms frames.

The previous measurements showed:

```text
taxi       ~40–410 ms depending on run
traffic    ~180–470 ms depending on run
```

Those ranges are large enough that they need to be measured in the actual spike.

Determine whether:

```text
taxi + traffic
```

can explain the whole spike.

If they cannot, explicitly state that.

Do not modify them yet.

---

# 7. Investigate the first-cache-build hypothesis

The V3 report mentions:

> the very first "no cache yet" frame after a fresh world/tile load still pays its one-time setup cost synchronously.

Determine whether this explains the remaining 440–560 ms frame.

Specifically compare:

```text
fresh map/tile load
```

against:

```text
already populated world cache
```

Measure:

- which cache is being created;
- how long it takes;
- whether it happens in the same frame as map synchronization;
- whether several cache builds happen in the same frame;
- whether it is possible for multiple static layers to perform first-build work together.

Do not change the cache implementation yet.

---

# 8. Investigate tile streaming boundaries

The historical symptom was:

```text
camera/player crosses tile boundary
        ↓
new tiles become available
        ↓
large frame-time spike
```

Determine the exact sequence now.

Instrument or inspect:

```text
tile fetch completes
    ↓
tile activation
    ↓
map sync scheduling
    ↓
cache invalidation
    ↓
cache rebuild
    ↓
normal gameplay
```

Determine which step causes the >400 ms frame.

This distinction is critical.

---

# 9. Check for multiple expensive operations in one frame

A likely possibility is not one 500 ms operation, but several medium-sized operations accidentally landing in the same frame.

For example:

```text
taxi              150 ms
traffic           100 ms
cache build       180 ms
other              70 ms
------------------------
total              500 ms
```

or:

```text
map sync           300 ms
render cache       150 ms
other               50 ms
------------------------
total              500 ms
```

Find out whether this is happening.

For every >400 ms frame, produce a contribution table.

---

# 10. Check the profiler itself

Verify that the profiler correctly accounts for nested sections.

For example, avoid accidentally reporting:

```text
parent = 300 ms
child  = 250 ms
```

and then treating both as independent costs totaling 550 ms.

Determine whether profiler timings are:

- inclusive;
- exclusive;
- nested;
- overlapping.

Document this in the report.

This is important before drawing conclusions from the numbers.

---

# 11. Check garbage collection and allocation spikes

Only investigate this if the frame breakdown does not already explain the spike.

Look for evidence of:

- Python GC;
- massive temporary allocations;
- object destruction;
- list/dictionary rebuilds;
- large cache replacement;
- Pygame Surface allocation.

Do not disable GC.

Do not change allocation behavior.

This task is only about finding evidence.

---

# 12. Check disk/network activity

Determine whether the >400 ms frame includes synchronous:

- PBF access;
- binary loading;
- filesystem operations;
- tile decompression;
- cache reads;
- network operations.

The city BIN should already avoid unnecessary road-network loading.

Do not assume that all tile streaming work is asynchronous simply because fetching is asynchronous.

If there is synchronous disk/network work on the main thread, identify it.

Do not fix it yet.

---

# 13. Check rendering one more time, but only as a verification

Road rendering has already been independently measured and should remain out of scope.

Verify the full-frame numbers:

```text
render:roads
render:buildings
render:scenery
render:vehicles
render:pedestrians
```

If roads remain around the previously measured order of magnitude, explicitly mark them as ruled out.

Do not modify `render/roads.py`.

---

# 14. Compare normal frames against spike frames

Create a table like:

```text
Subsystem                 Normal frame     Spike frame
------------------------------------------------------
Simulation                X ms             X ms
Map sync                  X ms             X ms
Taxi                      X ms             X ms
Traffic                   X ms             X ms
Road rendering            X ms             X ms
Building rendering        X ms             X ms
Scenery rendering         X ms             X ms
Vehicle rendering         X ms             X ms
Pedestrian rendering      X ms             X ms
Cache work                X ms             X ms
Tile handling             X ms             X ms
GC                        X ms             X ms
Other                     X ms             X ms
```

Use actual measurements.

This should make the cause of the spike immediately visible.

---

# 15. No optimization in this task

Do NOT:

- make taxi incremental;
- make traffic incremental;
- modify rendering;
- change cache architecture;
- change tile streaming;
- change the loading screen;
- rewrite routing;
- modify the road BIN;
- change OSM/PBF fallback;
- change custom-city behavior;
- disable garbage collection;
- add threads;
- add multiprocessing.

The only permitted code changes are:

- profiling instrumentation;
- diagnostic output;
- benchmark/test harness changes required to reproduce and measure the spike.

If instrumentation changes production behavior, keep it minimal and remove it after measurement if appropriate.

---

# 16. Reproduce multiple times

Run enough repetitions to distinguish:

### deterministic behavior

from:

### occasional spikes.

At minimum capture several tile-boundary transitions.

Ideally measure:

```text
10+ tile transitions
```

if practical.

Report:

```text
number of transitions
number of >100 ms frames
number of >400 ms frames
number of >500 ms frames
maximum frame
```

---

# 17. Final report

Produce a new report:

```text
bin-loader-v4.md
```

with these sections.

## 1. Test environment

Document:

- Oulu dataset;
- BIN/PBF source;
- cache state;
- relevant game configuration;
- test scenario.

## 2. Baseline

Report:

```text
average FPS
average frame time
worst frame
```

## 3. Normal frame breakdown

Show the normal frame contributions.

## 4. Spike frame breakdown

Show the >400 ms frame contributions.

## 5. Root cause

Identify exactly what produces the remaining 440–560 ms spike.

Do not use vague conclusions such as:

> "map synchronization is slow."

Name the actual function/stage(s).

## 6. Contribution

Explain how much each contributor adds.

For example:

```text
A: 220 ms
B: 150 ms
C: 80 ms
D: 30 ms
```

## 7. Road rendering

Explicitly state whether it remains ruled out.

## 8. Tile-boundary sequence

Document what happens when the player crosses into new territory.

## 9. Remaining synchronous work

List all remaining synchronous stages.

## 10. Recommended next task

Based strictly on the evidence, identify the **single most useful next optimization target**.

Do not implement it in V4.

---

# Critical rule

The previous three profiling/optimization passes have already demonstrated the value of measuring before changing code.

The current known state is:

```text
v1:
    roads ruled out

v2:
    found ~3+ second synchronous map-sync stall

v3:
    map-sync made incremental
    redundant work removed
    worst frame reduced to ~440–560 ms

v4:
    explain the remaining ~440–560 ms
```

The purpose of this task is therefore:

> **Find exactly where the remaining half-second frame goes.**

Do not guess.

Do not optimize.

Measure the complete frame, correlate the spike with the tile-streaming event, identify the exact expensive operation(s), and only then recommend the next change.