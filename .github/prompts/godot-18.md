# godot-18: Performance Investigation and Rendering Optimization

## Goal

Investigate and eliminate the severe FPS drops introduced or exposed by the Godot 2.5D building renderer.

The reported headline benchmark from godot-17 is misleading: although the measured steady-state FPS was 145–151, real gameplay can visibly drop below **15 FPS**. This phase is therefore primarily a profiling and optimization task.

Do not add new gameplay features or new rendering features until the severe frame-time spikes are understood and addressed.

The target is not merely a better average FPS. The important goal is stable frame time during normal gameplay, camera movement, chunk streaming, day/night changes, and dense building areas.

---

## 1. Preserve the architecture

Do not change the fundamental architecture:

* Server-authoritative gameplay remains unchanged.
* Godot remains a rendering client.
* Do not add client-side physics or collision.
* Do not add navigation yet.
* Do not reintroduce the old Pygame oblique/isometric building renderer.
* Keep the current top-down map with 2.5D elevated buildings.
* Keep the current building projection model unless profiling proves a specific part of it is responsible for the problem.
* Do not remove visual features merely to hide the problem.

Any optimization must preserve the current godot-17 visual behaviour and protocol semantics.

---

## 2. First reproduce the real problem

Do not rely on the existing 145–151 FPS benchmark.

Create a repeatable performance test that deliberately exercises the situations most likely to cause frame-time spikes:

1. Start in central Oulu.
2. Drive continuously through dense building areas.
3. Cross chunk boundaries repeatedly.
4. Move through areas containing many tall buildings.
5. Move through areas containing many buildings with windows.
6. Test dusk/night when lit windows are active.
7. Test rapid chunk streaming.
8. Test entering/leaving areas with bridges and underground levels.
9. Test fuel stations and raised canopies.
10. Test winter/snow if it affects the same rendering paths.

Record:

* average FPS
* minimum FPS
* 1% low FPS
* 0.1% low FPS if practical
* frame-time average
* frame-time p95
* frame-time p99
* worst frame time
* chunk load time
* chunk draw/build time
* memory
* number of buildings rendered
* number of facade surfaces
* number of windows
* number of lit windows
* number of active chunks

A single average FPS number is insufficient.

---

## 3. Profile before changing code

Use Godot's profiler and, where useful, lightweight internal instrumentation.

Determine whether the spikes are primarily caused by:

* CPU scripting
* rendering submission
* CanvasItem redraw
* geometry generation
* building batch construction
* window generation
* lit-window updates
* chunk streaming
* scene-tree operations
* allocations / garbage collection
* shader work
* texture/material changes
* excessive draw calls
* cross-chunk ordering
* main-thread synchronization
* server/network processing
* some interaction between these systems

Do not assume that 2.5D buildings are the cause simply because they were introduced in godot-17.

Identify the actual hot path.

---

## 4. Pay particular attention to buildings_25d.gd

Audit `buildings_25d.gd` in detail.

Look for:

* per-frame loops over buildings
* per-frame loops over windows
* per-frame geometry reconstruction
* repeated Polygon2D/Line2D creation
* repeated material creation
* repeated allocation of arrays/Vectors
* repeated sorting
* repeated transformation calculations
* repeated string operations
* repeated node creation/removal
* unnecessary notifications/redraws
* unnecessary updates when day/night state has not changed
* unnecessary work for buildings outside the visible area

The building geometry is supposed to be built once when the chunk loads.

Verify empirically that it really is.

If any static building geometry is being regenerated every frame, eliminate that immediately.

---

## 5. Investigate lit-window implementation

The new lit-window implementation is a particularly important suspect.

Verify whether lit windows:

* create individual nodes
* create individual draw calls
* trigger per-window updates
* trigger per-building redraws
* trigger full chunk redraws
* allocate objects during fade-in
* update every frame even after reaching their target intensity

The requirement is:

> Lit windows should be static geometry/material state whose visual intensity can change efficiently.

Do not update hundreds or thousands of individual windows every frame if a batched or shared mechanism can achieve the same visual result.

If the current implementation uses individual window nodes, redesign it so that large numbers of windows can be rendered efficiently.

Keep the deterministic building-position seed.

Keep the current Pygame-inspired probability distribution.

Keep the current fade-in behaviour.

Do not simply remove lit windows.

---

## 6. Investigate chunk streaming

godot-17 changed building ownership and increased per-chunk load time from approximately:

* 7.5 ms → 12.0 ms

The current architecture still loads one new chunk per frame.

Determine whether chunk loading can cause the <15 FPS spikes.

Instrument separately:

* protocol/static data parsing
* chunk object creation
* building geometry generation
* window generation
* sorting
* node creation
* first draw
* renderer synchronization

If one chunk can consume a large fraction of a frame budget, optimize it.

Do not simply increase the number of chunks loaded per frame.

The existing one-chunk-per-frame rule is intentional and should remain unless profiling proves a different strategy is necessary.

If necessary, split chunk construction into incremental stages while preserving the visible result.

---

## 7. Investigate cross-chunk building ordering

godot-17 currently uses a shared group to order buildings far-to-near across chunks, while the report also says that overlapping building volumes are ordered by chunk rather than per building.

Determine whether this sorting is:

* happening every frame
* happening only when chunks load
* unnecessarily repeated
* causing allocations
* causing frame spikes

If sorting is static, perform it only when the relevant chunk/building set changes.

Do not introduce expensive per-frame global sorting.

---

## 8. Verify renderer ownership optimization

godot-17 deliberately drops the client's copy of building geometry after the first draw because keeping it cost approximately 15 MiB.

Verify that this optimization is actually safe and beneficial.

Measure:

* memory before dropping the CPU-side geometry
* memory after dropping it
* frame time before/after
* chunk reload behaviour
* redraw behaviour
* day/night behaviour

Do not restore the extra 15 MiB merely for convenience unless profiling demonstrates a significant performance benefit.

If the renderer requires CPU-side data for redraws, find the minimal data representation required rather than retaining full geometry.

---

## 9. Check all other newly affected rendering paths

Because the reported problem is severe, also profile interactions with:

* `map_chunk.gd`
* `map_layer.gd`
* `chunk_detail.gd`
* `entity_layer.gd`
* `main.gd`
* night layer
* street lights
* headlights
* labels
* tire marks
* snow
* traffic lights
* trains
* canopies
* bridge rendering

Determine whether the FPS collapse happens:

* only with buildings
* only at night
* only while moving
* only during chunk streaming
* only near dense geometry
* only when many entities are present
* only when several systems update simultaneously

---

## 10. Use frame-time budgets

Treat 60 FPS as approximately:

* 16.7 ms/frame

Treat 30 FPS as:

* 33.3 ms/frame

The reported <15 FPS corresponds to:

* > 66.7 ms/frame

Find exactly where those >66 ms frames come from.

Do not accept:

> "Average FPS is still above 140."

as evidence that the problem is solved.

The acceptance test must include worst-case frame-time behaviour.

---

## 11. Add a reusable performance diagnostic

Add a lightweight development/debug performance report that can be enabled without affecting normal release rendering.

It should be able to report at least:

* FPS
* frame time
* worst frame time
* active chunk count
* building count
* window count
* lit-window count
* draw-call count if available
* chunk currently loading
* chunk-load duration

Do not leave verbose logging enabled in normal gameplay.

Prefer a small in-game/debug overlay or structured diagnostic output.

---

## 12. Optimize only after identifying causes

For every optimization:

1. Measure baseline.
2. Change one logical bottleneck.
3. Re-run the same benchmark.
4. Compare frame-time distribution.
5. Verify visual correctness.
6. Verify memory.
7. Keep the optimization only if it produces a meaningful improvement.

Do not perform speculative micro-optimizations throughout unrelated code.

---

## 13. Preserve visual parity

The following must remain unchanged unless a change is demonstrably required for performance:

* building footprint
* building height
* projection direction
* 0.35 × height projection scale
* 11.1 m projection cap
* visible south/east walls
* L-shaped building handling
* pitched roofs
* entrances/doors
* windows
* deterministic lit-window distribution
* raised canopies
* canopy posts
* pumps visible through canopies
* bridge ordering
* underground rendering
* snow
* night tint
* street lighting

Do not solve performance by reverting the 2.5D architecture.

---

## 14. Regression tests

All existing tests must continue to pass.

Add focused tests where useful for any optimization that changes:

* geometry caching
* window batching
* chunk streaming
* rendering invalidation
* building rebuild behaviour

Especially ensure that static building geometry is not rebuilt unnecessarily.

The existing godot-17 checks must remain intact.

---

## 15. Real Oulu verification

Run the optimized client against the real Oulu server.

Verify at minimum:

### Day

* central Oulu
* dense building areas
* chunk boundaries
* tall buildings

### Dusk/night

* lit windows
* street lights
* headlights
* night tint

### Special geometry

* St1 Limingantie
* Neste station
* bridges
* underground roads
* dense commercial buildings

Verify that no visual regression was introduced.

---

## 16. Performance acceptance criteria

The phase is successful only if the severe frame drops are explained and fixed.

At minimum:

* No unexplained sustained or repeated drops below 30 FPS during normal Oulu driving.
* No unexplained single-frame spikes above 66 ms caused by avoidable client rendering work.
* 1% low FPS should be substantially above the current failure case.
* Chunk streaming must not produce visible multi-frame stalls.
* Building rendering must remain visually equivalent to godot-17.
* Static geometry must not be rebuilt every frame.
* Lit windows must not require expensive per-window/per-node updates every frame.
* No client-side physics or navigation is introduced.
* Memory must remain in the same general range unless a measured trade-off clearly justifies an increase.
* Existing Python and Godot tests pass.

The existing ~145 FPS steady-state result is useful only as a secondary metric. The primary metric is frame-time stability.

---

## 17. Documentation

Update:

* `godot-pygame-rendering-parity.md`
* `godot-client.md`

Document:

* root cause of the FPS drops
* profiler evidence
* optimization(s) made
* before/after frame-time measurements
* effect on memory
* effect on chunk loading
* any known remaining spikes

Do not claim "performance matches godot-16" unless the worst-case/frame-time measurements actually support that statement.

---

## 18. Git

When implementation and verification are complete:

* Commit the changes with a clear `godot-18` commit message.
* Push the branch.
* Do NOT create or push a Git tag.

---

## Final report

Report:

1. The actual root cause(s) of the <15 FPS drops.
2. The exact code path(s) responsible.
3. What was changed.
4. Before/after average FPS.
5. Before/after 1% low FPS.
6. Before/after worst frame time.
7. Before/after chunk load time.
8. Before/after memory.
9. Building/window/lit-window counts in the worst test area.
10. Real Oulu verification results.
11. Python test count.
12. Godot test count.
13. Remaining performance bottlenecks, if any.
14. Commit hash.

Do not move on to a new visual feature if the severe frame-time spikes remain unexplained.
