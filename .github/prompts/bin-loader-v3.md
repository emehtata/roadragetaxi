You are working on the Road Rage Taxi / The Road Rage Trip repository:

https://github.com/emehtata/roadragetaxi

**Current branch:** `release/0.15.0alpha`

# Objective

Eliminate the multi-second frame stalls caused by synchronous map-data synchronization after new map tiles arrive.

The latest profiling investigation has established that **road rendering is not the problem**.

The main problem is:

```text
tile streaming
    ↓
large batch of newly available tiles
    ↓
PedestrianManager.sync_map_data()
    ↓
large synchronous processing pass
    ↓
multi-second frame stall
```

The current Oulu dense-city measurements showed approximately:

```text
map_sync:pedestrians       3218–3260 ms
map_sync:spatial_grid     ~1719 ms
map_sync:taxi              ~410 ms
map_sync:traffic           ~180 ms

render:roads               ~2.35 ms average
render:buildings           ~2.17 ms average
```

The pedestrian optimization already implemented in `bin-loader-v2.md` reduced:

```text
map_sync:pedestrians
~3220–3260 ms
        ↓
~2485 ms worst case
```

by adding an exact building-grid bbox pre-check to `_building_free_ways()`.

That optimization is complete.

**Do not redo it.**

The remaining problem is architectural:

> Large map-sync batches are processed synchronously in one uninterrupted pass, while road rendering already uses incremental, time-budgeted processing.

The goal of this task is to give the expensive map synchronization stages the same general incremental-processing principle.

---

# 1. First inspect the current implementation

Before modifying anything, inspect:

- `PedestrianManager.sync_map_data()`;
- `_building_free_ways()`;
- `_build_route_graph()`;
- `network.set_ways()`;
- `_build_junction_grid()`;
- `spatial_grid` synchronization;
- parking generation;
- taxi synchronization;
- traffic synchronization;
- tile-streaming completion handling;
- `_wait_for_active_tile_fetch`;
- the code that determines when newly fetched tiles become active;
- the existing road renderer incremental rebuild mechanism.

Understand exactly where the synchronous boundary currently exists.

Do not start by rewriting individual algorithms.

---

# 2. Preserve the existing blocking-loading-screen semantics

This is important.

The current `_wait_for_active_tile_fetch` behavior intentionally displays a full-screen loading state while required map tiles are being fetched.

**Do not remove this loading screen.**

It is outside the scope of this task.

The problem to solve is what happens **during that loading/synchronization period**.

Current behavior is effectively:

```text
tiles arrive
    ↓
synchronous map sync
    ↓
several seconds of uninterrupted CPU work
    ↓
sync complete
    ↓
game continues
```

The target behavior should be closer to:

```text
tiles arrive
    ↓
map sync starts
    ↓
process bounded amount of work
    ↓
yield
    ↓
process next bounded amount
    ↓
yield
    ↓
...
    ↓
sync complete
```

The loading screen may remain visible during this process.

Do not attempt to make the player drive while the map synchronization is incomplete.

---

# 3. Main architectural requirement

Introduce an incremental/budgeted map synchronization mechanism.

The implementation should follow the existing road-rendering pattern where practical:

```text
start rebuild
    ↓
remember progress
    ↓
perform work until time budget expires
    ↓
save progress
    ↓
return control
    ↓
continue next update
```

The exact API is up to the existing architecture.

Do not blindly copy the road renderer.

The synchronization stages have different semantics and may need explicit state machines or iterators.

---

# 4. Important correctness requirement

Map synchronization must behave **exactly as it does today when complete**.

Incremental processing must not change the final result.

After synchronization completes:

- all relevant ways must be present;
- pedestrian route graph must be complete;
- junction grid must be complete;
- road spatial grid must be complete;
- parking data must be complete;
- taxi data must be complete;
- traffic data must be complete;
- no tile data may be lost;
- no duplicate entries may accumulate;
- no stale data from previous tiles may remain.

The optimization is about **when the work happens**, not about changing what work happens.

---

# 5. Identify independent stages

Based on the profiling results, the synchronization currently contains several expensive stages.

At minimum investigate:

```text
Pedestrians
    ├── _building_free_ways()
    ├── _build_route_graph()
    └── _build_junction_grid()

Spatial grid
    ├── road spatial grid
    └── parking generation

Taxi
Traffic
```

Determine which stages can safely be made incremental.

Do not assume all of them need exactly the same mechanism.

---

# 6. Pedestrian synchronization

The pedestrian stage is currently the largest single contributor.

Existing optimization:

```text
_building_free_ways()
    ↓
building-grid bbox pre-check
```

must remain intact.

Now make the overall pedestrian synchronization incremental.

Potential design:

```text
Pedestrian sync state
    │
    ├── building-free-way processing
    │
    ├── route graph construction
    │
    └── junction grid construction
```

Each stage should maintain progress between updates.

For example:

```python
class MapSyncState:
    ...
```

or an equivalent existing-project approach.

Do not expose unnecessary implementation details to unrelated systems.

---

# 7. `_build_route_graph()` / `network.set_ways()`

Profiling showed approximately:

```text
150–450 ms per call
```

for this area.

Investigate whether `network.set_ways()` currently rebuilds the entire graph whenever new tiles arrive.

If so, determine whether it can be incrementally extended.

Possible approaches include:

### Option A — incremental graph insertion

Add newly arrived ways to the existing graph.

### Option B — process `set_ways()` preparation incrementally

Prepare the required data over multiple frames and perform the minimum final commit.

### Option C — defer graph construction until the relevant pedestrian stage

Only if the current architecture permits this safely.

Do not redesign the routing engine unless necessary.

First determine what the current graph API allows.

---

# 8. `_build_junction_grid()`

Profiling showed:

```text
~85–420 ms
```

per rebuild.

Investigate whether the junction grid can be updated incrementally for newly affected ways/tiles.

Prefer:

```text
existing grid
    +
new tile data
```

over:

```text
discard everything
    ↓
rebuild entire grid
```

if the existing data structures make that safe.

However, do not force incremental updates if they would substantially complicate correctness.

If a full rebuild is required, make the rebuild itself time-budgeted.

---

# 9. Spatial grid and parking generation

Profiling showed:

```text
map_sync:spatial_grid
~1719 ms
```

This is a major remaining bottleneck.

Inspect whether this consists of several independent operations.

For example:

```text
road spatial grid
parking generation
other spatial indexing
```

Separate them if possible.

Then determine whether each operation can be:

- incrementally updated;
- processed tile-by-tile;
- processed way-by-way;
- time-budgeted.

The desired behavior is:

```text
Tile A
    ↓
update spatial structures

Tile B
    ↓
update spatial structures

Tile C
    ↓
update spatial structures
```

rather than:

```text
all new tiles
    ↓
rebuild everything
    ↓
multi-second stall
```

---

# 10. Taxi and traffic synchronization

The current measurements showed approximately:

```text
taxi       ~410 ms
traffic    ~180 ms
```

Investigate both.

Do not automatically redesign them.

Determine whether:

- they can consume newly synchronized tile data incrementally;
- they currently rebuild global structures;
- they can simply be scheduled after the more expensive stages;
- they can be time-budgeted.

If they are already cheap enough once the major stalls are removed, leave them mostly unchanged.

---

# 11. Time budget

Use a configurable synchronization budget.

A reasonable initial target is approximately:

```text
MAP_SYNC_BUDGET_MS = 4.0
```

or a value consistent with the existing rendering/cache budgets.

However, **do not blindly copy the road renderer's exact value**.

The goal is to prevent a single map-sync operation from monopolizing a frame.

The implementation should guarantee that ordinary work yields approximately within the budget.

As with the road renderer, acknowledge that a single indivisible operation may occasionally exceed the budget.

Do not split operations into absurdly small units purely to satisfy a numeric deadline.

---

# 12. Loading-screen behavior

Because the existing game deliberately blocks normal gameplay while waiting for active map tiles, the loading screen can remain active while synchronization progresses.

The synchronization loop should therefore become conceptually:

```text
while map_sync_incomplete:

    process_sync_for_budget()

    update loading/progress state

    yield back to the main loop
```

If the existing loading screen is not driven by the normal frame loop, adapt the implementation carefully.

Do not freeze the entire process for several seconds just because the loading screen is displayed.

The loading screen itself should remain responsive enough to redraw.

---

# 13. Avoid one giant generator if it creates hidden problems

Generators are one possible implementation:

```python
def sync_map_data_incremental(...):
    yield ...
```

But do not use generators merely because they are convenient.

The important requirement is persistent progress.

Suitable implementations include:

- iterators;
- explicit state machines;
- queues;
- per-stage cursors;
- resumable tasks.

Choose the approach that best fits the existing code.

---

# 14. Tile-level dependency handling

Be careful about dependencies.

Some operations may require all newly loaded tiles before they can safely execute.

For example:

```text
Tile A graph construction
may depend on
Tile B intersection
```

Do not introduce subtle boundary bugs by processing tiles independently when the existing algorithms assume a complete batch.

If an operation requires the complete set of newly loaded tiles:

1. prepare its input incrementally;
2. build any required intermediate structures incrementally;
3. perform the smallest possible final commit.

Correctness is more important than perfect incremental granularity.

---

# 15. Duplicate and stale data

Tile streaming may cause the same map area to be encountered more than once.

Ensure incremental synchronization does not cause:

```text
duplicate roads
duplicate pedestrians routes
duplicate junctions
duplicate parking entries
duplicate spatial-grid entries
```

Also ensure old tile data is correctly removed when the existing system evicts/unloads tiles.

Do not change eviction semantics in this task.

---

# 16. Failure recovery

If an incremental synchronization stage fails:

- do not leave the map half-marked as synchronized;
- preserve enough state to retry or fail cleanly;
- do not silently discard the newly loaded tile;
- log the actual failing stage.

The system must not enter a state where it believes synchronization completed when it did not.

---

# 17. Performance target

The primary target is **not** to make the total amount of CPU work disappear.

The primary target is:

> No single map synchronization frame should block for multiple seconds.

For example, changing:

```text
3.2 seconds in one frame
```

into:

```text
~4–8 ms per frame for several hundred frames
```

would solve the frame-freeze problem but might be unnecessarily slow overall.

Therefore, optimize both:

### Frame responsiveness

and:

### Total synchronization time.

A good result would be:

```text
old:
    ~3 seconds blocked frame

new:
    bounded work per frame
    no multi-second frame
    similar or better total sync time
```

Do not sacrifice total synchronization time by an order of magnitude merely to achieve a strict per-frame budget.

---

# 18. Measure before and after

Before changing the implementation, establish a baseline using the same Oulu scenario.

Record:

```text
map_sync:pedestrians
map_sync:spatial_grid
map_sync:taxi
map_sync:traffic

total synchronization time

worst frame during synchronization
number of frames used by synchronization
```

After implementation record exactly the same metrics.

The important result is:

```text
maximum single-frame sync cost
```

not just total time.

---

# 19. Test scenario

Use the real Oulu dense-city dataset.

Prefer the same scenario used for `bin-loader-v2.md`.

Test:

1. stationary initial map;
2. drive across a tile boundary;
3. drive through several consecutive tile boundaries;
4. high-speed driving;
5. dense urban area;
6. repeated tile streaming.

Pay particular attention to:

```text
player crosses tile boundary
        ↓
new tiles arrive
        ↓
map sync starts
        ↓
does any single frame become >100 ms?
```

The desired result is that the synchronization progresses without a multi-second frame stall.

---

# 20. Tests

Add focused tests for the incremental synchronization state.

At minimum verify:

- synchronization eventually completes;
- all expected data exists after completion;
- synchronization can pause and resume;
- multiple tiles are handled correctly;
- no duplicate data is created;
- tile boundaries remain correct;
- custom cities continue to work;
- BIN-backed cities continue to work;
- existing OSM/PBF fallback continues to work.

Run:

```bash
pytest -q
```

Do not "fix" unrelated pre-existing failures.

Report them separately.

---

# 21. Do not touch unrelated rendering

Do NOT modify:

```text
render/roads.py
```

unless a synchronization integration issue genuinely requires it.

The road-rendering investigation has already demonstrated that roads are not the current bottleneck.

Likewise, do not optimize buildings, scenery, vehicles, etc. in this task unless the incremental map-sync implementation directly requires a compatibility change.

Keep this task narrowly focused.

---

# 22. Important distinction

There are two different problems:

### Problem A — expensive computation

```text
_building_free_ways()
_build_route_graph()
_build_junction_grid()
spatial-grid construction
```

### Problem B — scheduling all of that synchronously

This task primarily addresses **Problem B**.

Do not prematurely rewrite every algorithm to make it faster.

First make expensive work incremental.

After that, future profiling can identify which individual algorithms are still expensive enough to justify their own optimization.

---

# 23. Final report

When complete, report:

### Before

```text
Worst map-sync frame:
...
Total sync time:
...
Pedestrian sync:
...
Spatial grid:
...
Taxi:
...
Traffic:
...
```

### After

```text
Worst map-sync frame:
...
Total sync time:
...
Pedestrian sync:
...
Spatial grid:
...
Taxi:
...
Traffic:
...
```

Also report:

- number of frames used for synchronization;
- effective average sync work per frame;
- whether the loading screen remained functional;
- whether camera/tile-boundary stuttering improved;
- whether total synchronization time increased or decreased;
- tests added;
- test results;
- any remaining synchronous stages.

---

# Critical rule

**Do not remove the loading screen.**

**Do not rewrite the road renderer.**

**Do not optimize random subsystems.**

The profiling has already identified the current problem:

```text
tile streaming
    ↓
large batch arrives
    ↓
synchronous map synchronization
    ↓
~3+ second frame stall
```

The objective is to transform that into:

```text
tile streaming
    ↓
large batch arrives
    ↓
incremental map synchronization
    ├── bounded work
    ├── yield
    ├── bounded work
    ├── yield
    └── complete
```

while preserving exactly the same final map state and game behavior.

**Measure first, implement second, benchmark again.**