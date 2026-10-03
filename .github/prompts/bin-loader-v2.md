You are working on the Road Rage Taxi / The Road Rage Trip repository:

https://github.com/emehtata/roadragetaxi

**Current branch:** `release/0.15.0alpha`

## Context

The city-specific road BIN integration is now working.

The road renderer has also been benchmarked independently using the real Oulu 20×20 km city road dataset containing approximately 22,193 ways.

The investigation showed that **road rendering is already well optimized and is NOT currently a meaningful frame-time bottleneck**.

Do NOT optimize `render/roads.py` further unless new profiling evidence demonstrates a regression.

The existing road renderer already has:

- `SpatialWayGrid` viewport culling;
- padded viewport selection;
- camera-relative rendering;
- quantized camera-cell static caching;
- zoom-bucketed cache keys;
- incremental cache rebuilding;
- a dedicated ~4 ms incremental rebuild budget;
- previous-cache rendering while a rebuild is in progress;
- endpoint joining and per-way drawing handled incrementally.

The measured Oulu road-rendering results were approximately:

```text
Scenario                    Average      Worst
------------------------------------------------
Stationary                  0.40 ms      0.52 ms
~40 km/h                    0.45 ms      8.08 ms
~110 km/h                   0.53 ms      7.75 ms
```

The occasional ~8 ms rebuild frame is understood and documented: the rebuild checks its deadline between discrete work items, so one unusually expensive item can overshoot the nominal 4 ms chunk budget.

This is still below the 16.67 ms budget for 60 FPS.

The benchmark therefore concluded:

> Road rendering is not worth optimizing further right now.

---

# Objective

Find the **actual remaining frame-time bottleneck in the complete game**.

Do not assume it is rendering.

Do not assume it is roads.

Do not optimize anything before measuring it.

The goal of this task is:

```text
Full frame
    │
    ├── simulation
    ├── NPCs
    ├── routing
    ├── residents
    ├── traffic
    ├── rendering
    │    ├── roads       ← already benchmarked, likely not the issue
    │    ├── buildings
    │    ├── scenery
    │    ├── vehicles
    │    ├── pedestrians
    │    └── other layers
    └── other work
             │
             ▼
       identify the actual
       dominant cost
```

---

# 1. First inspect the existing profiler

Before changing any code, inspect the existing performance instrumentation.

In particular inspect:

- `FrameProfiler`;
- F3 performance HUD;
- `FPS_OPTIMIZE.md`;
- existing `render:*` profiling sections;
- simulation profiling sections;
- NPC profiling;
- routing profiling;
- map/cache profiling;
- any existing benchmark utilities.

Determine exactly what the game already measures.

**Do not create a second profiling framework if the existing one is sufficient.**

---

# 2. Run the profiler during real gameplay

Use realistic gameplay rather than an isolated synthetic benchmark.

Test at least:

### Stationary

Player stopped in a dense city area.

### Normal driving

Approximately 40–60 km/h.

### Fast driving

Approximately 100–120 km/h.

### Dense urban area

Large number of buildings, roads, vehicles and pedestrians.

### Less dense area

Compare against a lower-density environment.

### Camera movement

Pay particular attention to periods where the player previously experienced stuttering.

---

# 3. Identify the largest contributors

Collect actual frame-time measurements.

Determine:

```text
Average frame time
Worst frame time
95th percentile if available
99th percentile if available
```

Then break the frame down into major categories.

For example:

```text
Simulation             X.XX ms
NPC                     X.XX ms
Routing                 X.XX ms
Residents               X.XX ms
Traffic                 X.XX ms
Road rendering          ~0.XX ms
Building rendering      X.XX ms
Scenery rendering       X.XX ms
Vehicle rendering       X.XX ms
Pedestrian rendering    X.XX ms
Other                   X.XX ms
```

Use the project's actual profiler names.

Do not invent measurements.

---

# 4. Distinguish average cost from spikes

This is especially important.

A subsystem can be cheap on average but responsible for visible stutters.

Find both:

### Sustained frame-time cost

and:

### Intermittent spikes

For example:

```text
Average:
    4 ms

Occasional:
    30 ms
```

is potentially more important to gameplay than:

```text
Average:
    8 ms

Worst:
    9 ms
```

Identify both.

---

# 5. Investigate camera-related spikes

The game has previously experienced stuttering during camera movement.

Determine whether those spikes still exist.

Specifically investigate whether camera movement causes:

- cache rebuilds;
- map tile loading;
- geometry conversion;
- OSM processing;
- binary loading;
- spatial-grid updates;
- NPC spawning;
- NPC despawning;
- routing;
- surface creation;
- garbage collection;
- Python object allocation;
- large lists/dictionaries being rebuilt.

Do not assume that a camera-related symptom means the renderer is responsible.

---

# 6. Investigate dynamic systems

The game now has a significant amount of simulation logic.

Profile:

- NPC vehicles;
- residents;
- pedestrians;
- traffic lights;
- routing;
- route generation;
- collision handling;
- spawn/despawn;
- spatial queries;
- nearest-road queries;
- traffic management;
- resident daily routines;
- passenger logic.

Determine whether any of these dominate frame time.

Especially look for:

```text
O(N)
O(N²)
```

operations performed every frame.

Also look for repeated pathfinding or route calculation.

---

# 7. Inspect allocation-heavy code

Python allocation can cause periodic frame spikes.

Look for per-frame creation of:

- lists;
- dictionaries;
- tuples;
- temporary geometry arrays;
- Pygame surfaces;
- vectors;
- route objects;
- transformed coordinates.

Do not optimize allocations blindly.

First identify them in a profiled hot path.

---

# 8. Check garbage collection

If the profiler suggests periodic spikes that do not correlate directly with one subsystem, investigate Python garbage collection.

Determine whether:

```text
GC collection
    ↓
temporary allocation burst
    ↓
frame spike
```

is occurring.

Do not disable garbage collection as a blind optimization.

Only change GC behavior if profiling demonstrates that it is relevant.

---

# 9. Rendering investigation

Road rendering has already been independently measured.

Therefore, treat this as the current baseline:

```text
Road rendering:
    ~0.4–0.5 ms steady state
```

Do not spend time optimizing it further unless the full-frame profiler reveals a regression.

Instead inspect other render layers:

- buildings;
- water;
- scenery;
- vegetation;
- vehicles;
- pedestrians;
- passengers;
- weather;
- lighting;
- shadows;
- effects;
- UI.

Again, measure first.

---

# 10. Do not optimize the wrong problem

This is a profiling task, not an optimization task yet.

If the profiler shows:

```text
NPC simulation = 6 ms
```

and:

```text
roads = 0.5 ms
```

then do not modify road rendering.

If:

```text
building cache rebuild = 15 ms
```

then investigate that.

If:

```text
routing = 10 ms
```

then investigate routing.

If:

```text
everything is below ~2 ms
```

then investigate intermittent spikes instead of arbitrarily rewriting systems.

---

# 11. Establish a concrete bottleneck report

Produce a table similar to:

```text
Subsystem                 Avg       P95       Worst
-----------------------------------------------------
Simulation                X.XX ms   X.XX ms   X.XX ms
NPC                       X.XX ms   X.XX ms   X.XX ms
Routing                   X.XX ms   X.XX ms   X.XX ms
Road rendering            X.XX ms   X.XX ms   X.XX ms
Building rendering        X.XX ms   X.XX ms   X.XX ms
Scenery rendering         X.XX ms   X.XX ms   X.XX ms
Vehicle rendering         X.XX ms   X.XX ms   X.XX ms
Pedestrian rendering      X.XX ms   X.XX ms   X.XX ms
Other                     X.XX ms   X.XX ms   X.XX ms
```

Use real values from the profiler.

If percentile information is unavailable, report whatever reliable measurements are available and state that limitation.

---

# 12. Only implement an optimization if justified

Once the dominant bottleneck is identified:

1. explain why it is the bottleneck;
2. identify the specific hot path;
3. propose the smallest practical optimization;
4. implement it;
5. benchmark again;
6. compare before/after.

Do not bundle several unrelated optimizations into one change.

The desired workflow is:

```text
measure
   ↓
identify bottleneck
   ↓
change one thing
   ↓
measure again
   ↓
keep or revert
```

---

# 13. Preserve existing architecture

Do not:

- rewrite the renderer;
- rewrite routing;
- rewrite NPC simulation;
- rewrite the road BIN;
- remove OSM/PBF fallback;
- remove custom-city support;
- migrate to C;
- replace Pygame;
- introduce a new ECS;
- introduce multiprocessing;
- introduce threads merely for the sake of optimization.

Any architectural change must be justified by measured evidence.

---

# 14. Preserve city BIN and fallback behavior

The current road-data architecture must remain:

```text
Predefined city
    │
    ├── valid city BIN
    │       ↓
    │   binary road network
    │
    └── no usable BIN
            ↓
       existing OSM/PBF/Overpass fallback
```

Custom cities must continue to work.

Do not make the performance investigation dependent on BIN availability.

---

# 15. Deliverable

At the end of this task, provide a concise report containing:

### Current full-frame performance

- average FPS;
- average frame time;
- worst frame time;
- profiler breakdown.

### Main bottleneck

Identify the actual subsystem responsible.

### Secondary bottlenecks

List any other meaningful contributors.

### Road rendering

Explicitly state that road rendering was measured separately and is currently not the dominant bottleneck.

### Camera movement

State whether camera movement still produces significant frame-time spikes and what subsystem causes them.

### Changes

If an optimization was implemented, describe exactly what changed.

If no optimization was justified, **do not make one just to produce code changes**.

### Before/after

If code was changed, provide measured before/after numbers.

### Tests

Run the relevant tests and report the results.

---

## Critical rule

**Do not start by changing code. Start by profiling the complete frame.**

The previous road-rendering investigation already demonstrated why this matters: the roads looked like a plausible optimization target, but measurement showed that they were already only about 0.4–0.5 ms per frame in steady state.

The purpose of this task is to avoid making the same assumption about another subsystem.

Find the real bottleneck first.