You are working on **The Road Rage Trip / Road Rage Taxi**, a Python/Pygame top-down driving game using real-world OpenStreetMap data.

Repository:
https://github.com/emehtata/roadragetaxi

Target branch:
`release/0.15.0alpha`

## Objective

Optimize the game's rendering and world-loading architecture to reduce:

* occasional FPS drops
* frame-time spikes
* stuttering when moving the camera
* visible pauses when new map areas are loaded
* unnecessary repeated rendering of static world geometry

The goal is **not** to rewrite the rendering engine. The existing architecture already contains several performance optimizations, including static rendering caches, tile streaming, binary world caching, throttled cache rebuilds, and a frame profiler.

First understand and measure the existing implementation. Only change architecture where profiling demonstrates a real bottleneck.

---

# 1. Inspect the existing architecture first

Before modifying anything, inspect the current implementation of:

* `render/common.py`
* `render/roads.py`
* `render/buildings.py`
* `render/scenery.py`
* `render/waters.py`
* `render/vehicles.py`
* `render/pedestrians.py`
* `render/labels.py`
* `render/navigation.py`
* `world_cache.py`
* OSM/PBF loading and tile streaming code
* `performance.py`
* `weather.py`
* the main game/render loop
* camera and zoom handling
* static cache invalidation logic

Do not assume the architecture from filenames alone. Trace the actual execution flow.

Document briefly:

1. How world data is loaded.
2. How map tiles are loaded/unloaded.
3. How static geometry is rendered.
4. How the static render cache works.
5. What causes the cache to be invalidated.
6. What causes a cache rebuild.
7. How cache rebuild work is distributed across frames.
8. Which objects are rendered every frame.
9. Which objects are rendered only when visible.
10. How zoom changes affect cached surfaces.
11. How dynamic weather effects interact with rendering.
12. Where frame-time spikes can originate.

---

# 2. Use the existing profiler before making architectural changes

The project already has a frame profiler and runtime profiling support.

Use the existing:

* F3 diagnostic/frame profiler
* F9 `cProfile`
* F10 profile output
* F12 diagnostic output

Do not replace the profiler unless there is a clear deficiency.

Add additional low-overhead diagnostics if necessary.

Useful metrics include:

* total frame time
* FPS
* static cache rebuild time
* number of static cache rebuilds per frame
* static cache rebuild queue length
* cache hit/miss count
* number of loaded world tiles
* number of visible tiles
* number of visible roads
* number of visible buildings
* number of visible scenery objects
* number of visible vehicles
* number of visible pedestrians
* world/tile loading time
* world-cache lookup time
* OSM geometry processing time
* number of objects actually drawn
* number of surfaces created per frame

These metrics should be cheap enough to leave enabled in the debug/profiling HUD.

Do not add expensive per-frame diagnostic processing.

---

# 3. Identify the actual source of frame spikes

Classify frame-time spikes into categories:

### A. Rendering

Examples:

* excessive `pygame.draw.*` calls
* large numbers of individual polygons
* repeated transformations
* unnecessary surface creation
* repeated text rendering
* repeated sprite scaling
* excessive alpha blending

### B. Static cache rebuilding

Examples:

* rebuilding too much geometry after small camera movement
* rebuilding multiple cache regions in one frame
* rebuilding regions that are no longer visible
* unnecessary invalidation
* cache thrashing while moving the camera

### C. World streaming

Examples:

* loading too many tiles simultaneously
* parsing OSM geometry on the main thread
* binary cache decoding on the main thread
* building renderable geometry synchronously

### D. Simulation

Examples:

* pedestrians
* residents
* vehicles
* traffic
* pathfinding
* collision detection

### E. Other

Examples:

* garbage collection
* image conversion
* font rendering
* filesystem operations
* logging
* weather effects

Do not optimize the wrong subsystem.

---

# 4. Improve the static render cache only if profiling justifies it

The existing static-cache system must be preserved unless it is demonstrably responsible for the performance problem.

The preferred direction, if static cache rebuilding is a bottleneck, is a **world-space tile render cache** rather than repeatedly rebuilding a large screen-space cache.

Conceptually:

```
Finland OSM/PBF
       ↓
World/binary cache
       ↓
World-space render tiles
       ↓
     Camera
       ↓
     Screen
```

A world-space render tile should contain pre-rendered static geometry such as:

* roads
* road markings
* buildings
* parks
* water
* trees
* curbs
* parking areas
* railways
* other static scenery

The screen should then primarily perform:

```
draw cached tile surface → screen
```

instead of regenerating all static geometry when the camera moves.

However:

**Do not implement this architecture unless profiling shows that the current cache is a significant bottleneck.**

The existing cache may already be sufficiently efficient.

---

# 5. Account for zoom correctly

The game has configurable world-to-screen scaling (`px_per_m`).

A world-space render cache must not become incorrect when zoom changes.

Choose one of these approaches based on the existing architecture:

* invalidate and rebuild render tiles when zoom changes, or
* maintain render caches for discrete zoom levels/buckets.

Do not scale a low-resolution cached world tile indefinitely, because that can cause:

* blurry graphics
* incorrect line widths
* poor road markings
* visual artifacts

Zoom changes should be relatively rare compared with camera movement, so rebuilding on zoom change may be acceptable if implemented efficiently.

---

# 6. Keep static and dynamic rendering strictly separated

Never bake dynamic effects into permanent static render tiles.

Static cache may contain:

* roads
* buildings
* water
* parks
* static scenery
* static road markings
* parking spaces
* railway infrastructure

Dynamic rendering must remain separate:

* player vehicle
* NPC vehicles
* pedestrians
* traffic lights that change state
* headlights
* shadows that depend on dynamic state
* rain
* rain splashes
* puddles/wetness overlays
* skidmarks
* temporary roadworks or other changing effects
* UI/HUD

In particular, **do not bake wet roads or puddles into the static road cache**.

The weather system already separates game-time wetness progression from real-time particle animation. Preserve this behavior.

---

# 7. Optimize tile rendering granularity

If a world-space render cache is implemented, use reasonably sized render tiles.

Do not create one enormous Surface for the entire Finland map.

The cache should be spatially partitioned so that:

* only nearby/visible render tiles are needed
* distant tiles can be unloaded
* camera movement normally only changes which cached surfaces are blitted
* loading/rendering can happen incrementally
* memory consumption remains bounded

The render tile size should be chosen based on actual world scale and profiling, not arbitrarily.

Avoid thousands of tiny surfaces if they create excessive management overhead.

---

# 8. Prevent cache thrashing

Camera movement should not cause continuous destruction/recreation of the same cache data.

Implement or preserve:

* deterministic world-space cache coordinates
* cache reuse
* padding around the visible area
* bounded cache memory
* LRU-style eviction if needed
* rebuild queues
* rebuild budgets per frame
* cancellation/skipping of obsolete queued rebuild work

If the player moves quickly, prioritize tiles that will become visible next.

Do not spend several frames rebuilding tiles that are already behind the camera.

---

# 9. Avoid main-thread stalls during world streaming

Investigate whether OSM/PBF processing, binary cache loading, geometry preparation, or tile construction can block the Pygame main loop.

Where safe, separate:

### Background/preparation work

* reading world data
* decoding cached data
* preparing geometry
* determining which objects belong to a tile

from:

### Main-thread Pygame work

* creating/displaying Pygame Surfaces if required by Pygame
* final blitting
* actual screen rendering

Be careful with Pygame thread-safety.

Do not introduce unsafe rendering from worker threads.

If background processing is not currently necessary, do not add threading merely for the sake of it.

---

# 10. Reduce unnecessary per-frame work

Inspect all rendering loops for opportunities to avoid work.

Examples:

* do not iterate through the entire loaded world when only nearby objects are visible
* use spatial partitioning where appropriate
* perform cheap visibility checks before expensive rendering
* cache transformed/static geometry
* cache fonts and rendered text
* avoid creating temporary Surfaces every frame
* avoid repeated image conversion
* avoid repeated polygon transformations
* avoid recalculating values that only change when the camera/zoom/world changes

Do not introduce complicated spatial indexes if the existing tile system already provides sufficient locality.

---

# 11. Preserve visual quality

Optimization must not noticeably degrade:

* road geometry
* road markings
* buildings
* water
* scenery
* labels
* vehicles
* pedestrians
* weather
* lighting

Do not solve performance problems by simply reducing:

* draw distance
* object density
* resolution
* update frequency
* visual effects

unless the existing game design explicitly permits it.

The preferred solution is to avoid doing unnecessary work.

---

# 12. Pay special attention to Surface creation

Search for code that creates Pygame Surfaces during normal gameplay.

Identify:

* `pygame.Surface(...)`
* `pygame.transform.*`
* `pygame.font.*`
* repeated image conversions
* alpha surface creation
* temporary masks

Determine whether each operation really needs to happen every frame.

Where appropriate:

* create reusable surfaces
* cache converted images
* reuse particle surfaces
* cache static text
* cache scaled sprites
* avoid repeated allocations

Be careful not to create an enormous cache that simply trades CPU usage for excessive RAM.

---

# 13. Weather-specific constraints

The existing weather system contains:

* rain particles
* splash effects
* wetness progression
* drying
* future snow support

Do not accidentally move weather effects into static world caches.

Rain particles should remain dynamic.

Puddles/wetness should use a dynamic overlay or another mechanism that does not force the entire static world cache to rebuild every frame.

A change in wetness should **not** invalidate every static render tile.

If puddles need to be associated with roads, keep that association spatially local to active/visible tiles.

---

# 14. Do not over-engineer

This is a performance optimization task, not a complete rendering-engine rewrite.

Follow these rules:

1. Measure first.
2. Change one subsystem at a time.
3. Keep changes small and reversible.
4. Preserve existing APIs where practical.
5. Do not duplicate existing caching systems unnecessarily.
6. Do not add a second cache for the same data without a clear reason.
7. Do not add threading unless profiling shows a main-thread blocking problem.
8. Do not optimize code that is not measurable in the profiler.
9. Do not change gameplay behavior.
10. Do not remove visual features to hide performance problems.

---

# 15. Establish measurable targets

Before and after optimization, compare representative scenarios:

### Scenario 1 – stationary

Camera stationary in a populated area.

Measure:

* average frame time
* FPS
* worst frame
* 95th percentile frame time

### Scenario 2 – slow driving

Drive continuously through a populated urban area.

Measure:

* average frame time
* frame spikes
* cache rebuilds
* loaded/visible tiles

### Scenario 3 – fast driving

Drive quickly across several map tiles.

Measure:

* streaming stalls
* cache rebuilds
* frame spikes
* tile loading latency

### Scenario 4 – weather

Run the same driving test during rain.

Measure whether weather adds significant frame-time overhead.

### Scenario 5 – zoom changes

Change zoom while moving.

Measure cache invalidation/rebuild behavior.

The optimization should improve frame-time consistency, not merely increase average FPS.

---

# 16. Success criteria

A successful implementation should result in:

* smoother camera movement
* fewer long frame-time spikes
* no noticeable pauses when entering new map areas
* static world geometry being reused instead of unnecessarily rerendered
* bounded memory usage
* dynamic entities remaining independent of static caching
* weather remaining dynamic
* correct rendering at all supported zoom levels
* no gameplay regressions

Most importantly:

**Do not implement a large architectural rewrite just because a tile-based render cache sounds faster. Prove the current bottleneck first.**

---

# 17. Final report

After implementation, provide a concise report containing:

### Findings

What was actually causing the largest frame-time spikes?

### Changes

What code was changed and why?

### Performance

Provide before/after measurements for:

* average FPS
* average frame time
* worst frame time
* 95th percentile frame time
* static cache rebuild time
* world/tile loading time

### Architecture

Explain whether the existing static cache was retained or whether a world-space render-tile cache was introduced.

### Remaining bottlenecks

List the next 2–3 performance bottlenecks if any remain.

Do not claim a performance improvement unless it was actually measured.
