You are working on the Road Rage Trip repository.

Current branch:

`release/0.15.0alpha`

## Objective

Perform a **data-driven performance analysis of the current game**, identify the actual performance bottlenecks, and fix the highest-impact problems without breaking existing gameplay systems.

This is an investigation and optimization task.

**Do not start by making speculative optimizations.**

First measure the current implementation, identify the expensive operations, determine their frequency and impact on frame time, and only then implement targeted fixes.

The game is already heavily optimized in several areas, so assume that an apparently expensive subsystem may already have an efficient implementation.

---

# 1. Establish the baseline first

Before changing production code, inspect the existing performance instrumentation and benchmark tools.

Look for existing:

* frame-time measurements;
* FPS measurements;
* p95/p99 frame timing;
* subsystem timers;
* debug HUD performance counters;
* OSM/tile streaming metrics;
* route graph metrics;
* NPC traffic metrics;
* pedestrian metrics;
* rendering metrics;
* collision metrics;
* garbage collection instrumentation;
* memory measurements.

Reuse existing instrumentation where possible.

Do not create a second incompatible profiling system if one already exists.

Run a representative baseline benchmark on the current implementation.

Record at least:

* average frame time;
* median frame time;
* p95 frame time;
* p99 frame time if available;
* worst frame;
* FPS;
* startup time;
* first-tile-load cost;
* runtime tile-streaming cost;
* memory/RSS if available;
* number of loaded tiles;
* number of active roads;
* number of active NPCs;
* number of pedestrians;
* number of trains;
* route graph sizes;
* collision/query counts.

---

# 2. Profile actual frame-time contributors

Break the frame into meaningful subsystems.

At minimum investigate:

```text
main loop
simulation/update
player physics
road lookup
NPC traffic
pedestrians
trains
taxi system
route finding
collision detection
building collision
environment queries
weather
rendering
road rendering
building rendering
lighting
street lights
vehicle lights
pedestrian rendering
train rendering
audio
HUD/debug rendering
garbage collection
tile streaming
map synchronization
incremental merge/integration
```

Do not assume every subsystem needs optimization.

Measure first.

For every significant subsystem, determine:

* time per frame;
* number of calls per frame;
* worst-case time;
* allocations if measurable;
* whether cost scales with world size;
* whether cost scales with actor count;
* whether cost occurs only during tile/map changes;
* whether cost occurs only at startup;
* whether cost occurs only when the player moves.

---

# 3. Pay particular attention to recent architecture

The repository now contains several performance-sensitive systems.

Audit these carefully rather than replacing them:

### OSM runtime streaming

Inspect:

* `AutoFetchManager`
* tile activation/deactivation
* `_merge_queue`
* incremental tile integration
* background fetch/build
* cache loading
* tile eviction
* map synchronization
* spatial-grid rebuilds
* route graph updates

The runtime game must remain playable while OSM data is fetched and integrated.

Do not reintroduce blocking loading screens.

Do not move network, PBF parsing, or large world-cache operations onto the main thread.

Do not replace the existing cache-first architecture without measured evidence.

---

# 4. Level-aware map architecture

The game now supports logical map levels for parking garages and underground roads.

Inspect the performance of:

* `Car.map_level`
* `LevelRoadNetworks`
* `SpatialWayGrid`
* `level_view_ways`
* level-aware road lookup
* level-aware collision
* `LevelTransitions`
* level connector resolution
* level route graphs if already implemented
* map-sync rebuilding

Important:

Do not revert level-aware filtering to broad world scans.

Do not reintroduce surface-road queries for underground levels.

Do not rebuild level networks every frame.

Level-specific structures should be constructed/rebuilt only when map data actually changes.

---

# 5. Railway systems

Profile the railway subsystem separately.

Measure:

* train simulation;
* train schedule lookup;
* station passenger logic;
* taxi bookings;
* station announcements;
* announcement audio queue;
* spatial audio calculations;
* train rendering;
* passenger rendering;
* route calculations.

Do not assume that a railway system with many objects is necessarily expensive.

Measure actual cost.

In particular, check whether announcements cause:

* repeated filesystem access;
* repeated manifest parsing;
* repeated `pygame.mixer.Sound` construction;
* large audio buffer allocations;
* repeated spatial-volume calculations;
* queue scans;
* unnecessary object creation.

The railway announcement system must not introduce frame-time spikes.

---

# 6. NPC traffic

The current project has previously shown that visible NPC count alone was not the real traffic bottleneck.

Do not simply increase/decrease NPC limits.

Measure:

* parked NPC count;
* moving NPC count;
* trip-start attempts;
* successful trip starts;
* route calculation failures;
* road-network lookup failures;
* spawn failures;
* blocked paths;
* per-NPC update cost;
* per-NPC collision cost;
* pathfinding cost.

If traffic appears thin, determine whether the actual problem is:

```text
spawn
trip generation
route generation
road connectivity
destination selection
vehicle state
parking state
collision avoidance
```

before changing any population limit.

---

# 7. Pedestrians

Measure:

* active pedestrian count;
* pedestrian update time;
* pathfinding time;
* road/footway lookup;
* spawning/despawning;
* rendering;
* collision;
* tile synchronization.

Pay special attention to work triggered by tile loading.

Do not perform full-world pedestrian synchronization when only one tile changed.

Use incremental updates where the existing architecture supports them.

---

# 8. Rendering analysis

Measure rendering separately from simulation.

Determine whether the current frame budget is dominated by:

* road drawing;
* buildings;
* trees;
* scenery;
* lighting;
* vehicle lights;
* windows;
* rain;
* puddles;
* shadows;
* text;
* debug overlays.

Check whether off-screen objects are correctly culled.

Check whether surface-only rendering is skipped while the player is underground.

Check whether static geometry is unnecessarily rebuilt.

Do not optimize by simply lowering visual quality.

Prefer:

* culling;
* caching;
* spatial indexing;
* dirty-region updates;
* incremental updates;
* avoiding redundant draw calls;
* avoiding repeated transformations.

---

# 9. Garbage collection and allocations

The project has previously investigated Python GC behaviour.

Do not blindly change GC thresholds.

Measure first.

Determine:

* number of allocations in hot paths;
* generation-2 collections;
* collection duration;
* temporary list/dict creation;
* repeated tuple/object creation;
* per-frame object churn.

If GC is responsible for spikes, identify the allocation source before changing GC configuration.

Do not globally disable GC as an optimization.

---

# 10. Tile streaming and map synchronization

This is a high-priority area.

Measure what happens when the player crosses a tile boundary.

Capture:

```text
tile detection
tile fetch scheduling
cache lookup
background build
completed batch handling
merge
object insertion
spatial-grid updates
level-network updates
route-graph updates
NPC synchronization
pedestrian synchronization
train synchronization
render-cache invalidation
```

Determine whether any of these operations execute too much work in one frame.

If a tile merge causes a frame spike:

* measure the amount of work;
* identify the expensive phase;
* split the work into incremental chunks where appropriate;
* preserve correctness;
* preserve the existing background fetch/build model.

Do not merely increase the merge budget because that may make the frame spike worse.

Likewise, do not reduce the budget blindly if it causes the world to lag behind the player.

---

# 11. Route graph performance

If Phase 11/12 route graphs are already implemented, audit them.

Measure:

* graph construction time;
* graph rebuild frequency;
* nodes per level;
* edges per level;
* connector edges;
* route calculation time;
* failed route calculation time;
* memory use;
* map-sync rebuild cost.

Verify that route graphs are not being rebuilt because of unrelated per-frame state changes.

A route graph should only be rebuilt when its underlying map topology changes.

Do not rebuild graphs every frame.

Do not create cross-level graph edges implicitly.

Only resolved level connectors may create cross-level transitions.

---

# 12. Identify the top bottlenecks

After measurement, produce a ranked **technical bottleneck list**, but do not optimize based on intuition.

For every candidate bottleneck provide:

```text
Subsystem
Measured cost
Frequency
Frame-time impact
Scaling behaviour
Likely cause
Confidence
Proposed fix
Expected benefit
Risk
```

Example:

```text
NPC route lookup
1.8 ms/frame
1,200 calls
~7% of frame budget
scales with NPC count
repeated spatial query
high confidence
cache nearest road segment
medium expected benefit
low risk
```

Use actual measurements, not invented numbers.

---

# 13. Fix only measured problems

After identifying the bottlenecks, implement targeted fixes.

Prioritize:

1. recurring per-frame costs;
2. frame-time spikes;
3. tile/map synchronization spikes;
4. expensive repeated queries;
5. unnecessary allocations;
6. only then minor rendering improvements.

Do not spend time optimizing code that is already insignificant.

---

# 14. Preserve behaviour

Optimization must not change:

* road connectivity;
* map levels;
* level transitions;
* train schedules;
* taxi behaviour;
* pedestrian behaviour;
* NPC traffic rules;
* announcement contents;
* OSM import semantics;
* OSM level semantics;
* tile streaming semantics.

Correctness comes first.

Do not use approximate spatial logic where it can change gameplay.

---

# 15. Benchmark every significant change

For each optimization:

1. run the relevant targeted benchmark;
2. compare against the baseline;
3. run the existing regression tests;
4. verify that the optimization actually improves the measured metric.

If an optimization does not measurably improve performance, revert it unless it has another clear architectural benefit.

Do not accumulate speculative "optimizations".

---

# 16. Test multiple gameplay situations

Performance must be checked in more than one situation.

At minimum test:

### Surface driving

Normal driving in a populated city.

### Dense city

Many roads, buildings, NPCs and pedestrians.

### Underground

Switch between:

```text
0
-1
-2
```

where supported.

Verify that underground rendering and level-aware road queries remain efficient.

### Tile boundary crossing

Drive continuously across several tile boundaries.

Measure frame-time spikes.

### Railway activity

Run with trains, station passengers and announcements active.

### NPC activity

Run with normal traffic simulation active.

### Long session

Run long enough to expose:

* memory growth;
* object accumulation;
* cache growth;
* GC spikes;
* stale tile objects;
* performance degradation.

---

# 17. Performance acceptance criteria

Do not invent a new target unless the repository already defines one.

Use the project's existing performance targets.

At minimum report:

```text
Average frame time
P95 frame time
P99 frame time
Worst frame
FPS
Startup time
Tile-crossing spike
Memory/RSS
```

Compare before and after.

The important metric is not only average FPS.

A game with a high average FPS but occasional 200–500 ms stalls still has a frame-pacing problem.

---

# 18. No blind architectural rewrites

Do not:

* replace Pygame;
* rewrite the renderer;
* replace spatial grids;
* replace the OSM importer;
* replace the cache format;
* remove level-aware architecture;
* remove incremental streaming;
* replace Python with another language;
* introduce multiprocessing solely because it sounds faster;
* introduce an external database;
* introduce a new dependency without evidence that it solves the measured bottleneck.

Work with the current architecture.

---

# 19. Final report

At the end provide a concrete performance report containing:

## Baseline

Actual measured:

* average frame time;
* p95;
* p99 if available;
* worst frame;
* FPS;
* memory;
* tile-load timing.

## Bottlenecks

List the actual measured bottlenecks and their impact.

## Changes

For every implemented optimization:

* file;
* function;
* old behaviour;
* new behaviour;
* measured improvement.

## Regression tests

Report the exact test commands and results.

## Before/after

Provide a compact table:

| Metric              |   Before |    After |   Change |
| ------------------- | -------: | -------: | -------: |
| Average frame       | measured | measured | measured |
| P95                 | measured | measured | measured |
| P99                 | measured | measured | measured |
| Worst frame         | measured | measured | measured |
| Tile-crossing spike | measured | measured | measured |
| Memory              | measured | measured | measured |

Never fabricate measurements.

## Remaining problems

Clearly separate:

* fixed bottlenecks;
* known bottlenecks not yet fixed;
* areas that were measured and found not to be bottlenecks.

The final report must make it clear **what was actually measured and what was merely suspected**.
