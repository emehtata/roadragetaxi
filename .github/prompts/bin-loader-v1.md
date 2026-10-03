You are working on the Road Rage Taxi / The Road Rage Trip repository:

https://github.com/emehtata/roadragetaxi

**Current branch:** `release/0.15.0alpha`

## Goal

The road network is now loaded from the prebuilt city-specific V2 `.bin` files for predefined cities.

This successfully improves road-data loading, but it does **not** automatically improve rendering performance.

The next task is to investigate and optimize the **road rendering pipeline** so that the game does not repeatedly perform unnecessary geometry processing and drawing work for roads.

The important distinction is:

```text
City BIN
   │
   ▼
Road network data
   │
   ├──► Routing / NPC / traffic
   │
   └──► Road rendering
```

The BIN optimization has already addressed the road-data loading side.

This task is specifically about the second branch:

```text
Road network
      │
      ▼
Rendering preparation
      │
      ▼
Visible road geometry
      │
      ▼
Pygame rendering
```

Do not assume that the BIN itself will improve FPS.

---

# 1. First inspect the current renderer

Before changing code, thoroughly inspect the existing road-rendering implementation.

Find:

- where road geometry is converted to screen coordinates;
- where roads are selected for rendering;
- where visibility/culling is performed;
- whether roads are rendered every frame;
- whether world-to-screen coordinate conversion happens every frame;
- whether Pygame surfaces are created every frame;
- whether polygons/lines are rebuilt every frame;
- whether road widths are recalculated every frame;
- whether road classifications are repeatedly looked up;
- whether the same road geometry is transformed multiple times;
- whether roads are rendered individually;
- whether nearby roads outside the viewport are processed unnecessarily;
- whether camera movement invalidates previously calculated geometry;
- whether the current tile/cache system can be reused.

Do not modify anything until the current rendering path is understood.

---

# 2. Establish a baseline

Before optimizing, measure the current behavior.

Use the existing performance/debugging infrastructure if available.

Measure at least:

- FPS;
- frame time;
- road-rendering time if it can be isolated;
- number of roads considered per frame;
- number of roads actually rendered;
- number of geometry points processed;
- number of Pygame draw calls if practical;
- camera movement vs stationary camera;
- CPU usage if practical.

Test both:

```text
Stationary camera
```

and:

```text
Moving camera
```

The moving-camera case is especially important because the game has previously exhibited periodic rendering stutters during camera movement.

Do not optimize based purely on intuition.

---

# 3. Determine what is actually expensive

Identify the dominant cost.

Possible examples include:

```text
A) OSM/BIN data lookup
B) world → screen coordinate conversion
C) visibility/culling
D) road polygon generation
E) Pygame draw calls
F) surface creation
G) cache invalidation
H) repeated geometry processing
I) Python object iteration
```

Do not assume the answer.

If road rendering is already cheap and another subsystem dominates frame time, document that instead of introducing unnecessary complexity.

---

# 4. Separate road data from render data

The road BIN should remain the authoritative source for the road network.

Do not modify the V2 binary format unless there is a demonstrated need.

Conceptually separate:

```text
Road network data
    ├── IDs
    ├── topology
    ├── metadata
    └── world geometry

Render cache
    ├── screen/world transformed geometry
    ├── visibility information
    └── optionally prebuilt render surfaces
```

The road graph must remain usable by:

- routing;
- NPCs;
- residents;
- traffic;
- traffic lights.

Rendering optimizations must not corrupt or alter the road graph.

---

# 5. Investigate render caching

Determine whether road geometry can be cached after it has been transformed into the representation needed by the renderer.

For example, instead of doing:

```python
for road in roads:
    points = transform_world_to_screen(road.geometry)
    pygame.draw.lines(...)
```

every frame, investigate a design closer to:

```text
Road BIN
   │
   ▼
Road geometry
   │
   ▼
Render preparation/cache
   │
   ▼
Cached representation
   │
   ▼
Fast per-frame visibility + drawing
```

The exact implementation must be based on the current renderer.

Do not blindly cache everything.

---

# 6. Camera-aware caching

The game has a moving camera.

A screen-space cache cannot simply remain valid forever.

Determine whether the renderer would benefit from caching in:

### World coordinates

or:

### Camera-relative coordinates

or:

### Pre-rendered map tiles/chunks

or:

### Pygame surfaces

Choose based on measured behavior.

A potentially useful architecture is:

```text
                 Road BIN
                    │
                    ▼
             World-space road
               render cache
                    │
                    ▼
              Visible chunks
                    │
                    ▼
             Camera transform
                    │
                    ▼
                 Pygame
```

This can avoid rebuilding the underlying road geometry every frame.

---

# 7. Consider chunk/tile-based rendering

Investigate whether roads should be grouped into fixed world-space render chunks.

For example:

```text
+---------+---------+---------+
| chunk   | chunk   | chunk   |
|         |         |         |
+---------+---------+---------+
| chunk   | camera  | chunk   |
|         |         |         |
+---------+---------+---------+
| chunk   | chunk   | chunk   |
|         |         |         |
+---------+---------+---------+
```

Only chunks intersecting the camera viewport need to be rendered.

The existing game already has tile/map streaming concepts.

Investigate whether those mechanisms can be reused rather than introducing a second unrelated spatial system.

Do not assume the existing OSM tiles are the correct rendering chunks.

---

# 8. Avoid per-frame geometry reconstruction

Look specifically for code patterns like:

```python
list(...)
```

```python
tuple(...)
```

```python
[(transform(...)) for ...]
```

```python
pygame.Surface(...)
```

```python
pygame.draw.polygon(...)
```

```python
pygame.draw.lines(...)
```

inside the main rendering loop.

Determine which of these are genuinely expensive.

The goal is to move expensive work from:

```text
every frame
```

toward:

```text
once when data/chunk becomes dirty
```

where practical.

---

# 9. Camera movement must remain smooth

Do not optimize stationary rendering at the expense of camera movement.

Test:

```text
slow camera movement
normal driving
high-speed driving
rapid direction changes
```

The game should not exhibit visible stalls when entering previously unseen road areas.

If a new render cache/chunk must be generated while driving, consider:

- lazy generation;
- limited work per frame;
- background preparation where safe;
- pre-generation of neighboring chunks.

Do not introduce threads unless necessary and safe with the existing Pygame architecture.

Pygame rendering itself should remain on the main thread.

---

# 10. Visibility culling

Investigate the current road visibility logic.

A road should not be transformed or drawn if it cannot possibly contribute to the current frame.

Consider:

```text
road bounding box
        ↓
viewport intersection?
        ↓
YES → transform/render
NO  → skip
```

Do not perform expensive point-by-point transformation just to discover that an entire road is outside the viewport.

If the road network lacks cached bounding boxes, determine whether they can be derived once when the BIN is loaded.

Do not modify the BIN format just for this unless necessary.

---

# 11. Long roads crossing the viewport

Pay special attention to long roads.

A road may have:

```text
100+ geometry points
```

while only a small portion intersects the screen.

Investigate whether the renderer currently transforms the entire geometry every frame.

If so, consider:

- cached world-space bounding boxes;
- segment-level culling;
- chunk assignment;
- geometry simplification at render distance;
- clipping.

Do not implement complex segment-level clipping unless profiling shows it is useful.

---

# 12. Rendering levels of detail

Investigate whether distant roads need the same geometry precision as nearby roads.

Potential model:

```text
Near:
    full geometry

Medium:
    simplified geometry

Far:
    simplified line / lower detail
```

However:

**Do not implement LOD automatically.**

Only add it if profiling demonstrates that geometry complexity is a meaningful rendering cost.

The first priority is avoiding repeated work.

---

# 13. Preserve visual appearance

The optimization must not noticeably change:

- road positions;
- road widths;
- road classifications;
- intersections;
- road colors;
- road geometry;
- camera alignment.

Do not sacrifice visual correctness for a benchmark number.

If an optimization changes rendering behavior, compare before/after screenshots or equivalent visual validation.

---

# 14. Do not change unrelated systems

This task is NOT:

- a routing rewrite;
- an NPC rewrite;
- a traffic rewrite;
- a road BIN format rewrite;
- an OSM extraction rewrite;
- an Overpass rewrite;
- a Pygame replacement;
- a migration to C;
- a full renderer rewrite.

Do not modify these systems unless profiling proves that a small compatibility change is necessary.

---

# 15. Keep the existing custom-city fallback

The previous BIN integration introduced:

```text
Predefined city
    → city BIN

Custom city / missing BIN
    → existing OSM/PBF/Overpass path
```

Preserve this behavior.

The renderer must work identically regardless of whether road data originated from:

```text
city BIN
```

or:

```text
existing OSM/PBF/Overpass fallback
```

Do not make rendering depend on a BIN being available.

---

# 16. Suggested optimization architecture

After inspecting the existing code, prefer the smallest architecture that achieves measurable benefit.

A possible target architecture is:

```text
                    Road network
                         │
                         ▼
                 World-space geometry
                         │
                         ▼
                  Spatial/chunk index
                         │
             ┌───────────┴───────────┐
             │                       │
        visible chunks          non-visible
             │                       │
             ▼                       ▼
       render cache                  skip
             │
             ▼
       camera transform
             │
             ▼
          Pygame
```

But this is only a target concept.

**Do not implement this exact structure blindly.**

Adapt it to the actual repository after profiling.

---

# 17. Performance acceptance criteria

The optimization should demonstrate measurable improvement.

Record before/after results for at least:

```text
Stationary camera
Moving camera
Dense urban area
Less dense area
```

Report:

```text
Average FPS
Average frame time
Worst observed frame time
Road rendering time
Roads processed
Roads rendered
Geometry points processed
```

If the existing project has a suitable benchmark harness, extend it rather than creating a parallel framework.

The result should clearly answer:

> Did road rendering become cheaper?

If the answer is no, do not keep unnecessary caching infrastructure just because it looks architecturally interesting.

---

# 18. Tests

Add focused tests for any new caching/culling functionality.

At minimum test:

- road geometry remains unchanged;
- viewport culling does not hide visible roads;
- roads outside the viewport are skipped;
- cached geometry produces the same rendering input;
- camera movement invalidates/reuses caches correctly;
- cache invalidation works when changing cities;
- custom-city road data still renders;
- BIN-backed road data still renders.

Run:

```bash
pytest -q
```

Do not modify unrelated tests just to make them pass.

Clearly identify pre-existing failures.

---

# 19. Profiling and implementation order

Follow this order:

### Phase 1 — inspect

Understand the current renderer.

### Phase 2 — benchmark

Measure the current road-rendering cost.

### Phase 3 — identify bottleneck

Determine the largest avoidable cost.

### Phase 4 — implement one optimization

Do not introduce several speculative optimizations simultaneously.

### Phase 5 — benchmark again

Compare before/after.

### Phase 6 — only then consider another optimization

This is important because the game already contains substantial complexity.

Avoid creating a complicated rendering cache without evidence that it solves an actual bottleneck.

---

# 20. Final report

When finished, report:

1. How roads are currently rendered.
2. What the actual bottleneck was.
3. What was changed.
4. What was deliberately left unchanged.
5. Whether road geometry is now cached.
6. Whether spatial/chunk culling was introduced.
7. Before/after FPS.
8. Before/after frame time.
9. Before/after road rendering time.
10. Any remaining rendering bottlenecks.
11. Test results.
12. Any recommended next optimization.

The most important principle is:

> **The city BIN solves road-data loading. This task solves road-rendering cost. Keep those concerns separate.**

The existing road network, routing, NPC systems and custom-city fallback must continue to work exactly as before.
