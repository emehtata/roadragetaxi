# Road Rage Trip — Replace OSM Loading Screens with Seamless Predictive Streaming

## Context

Repository: `emehtata/roadragetaxi`

Current branch:

`release/0.15.0alpha`

The game already has a fairly sophisticated background OSM streaming implementation in:

* `src/theroadragetrip/osm/autofetch.py`
* `src/theroadragetrip/osm/overpass.py`
* `src/theroadragetrip/main/__init__.py`

The game currently shows a loading screen when OSM data needs to be fetched. I want to remove this dependency on a loading screen during normal gameplay.

The main problem is that the player can drive toward the edge of the currently available OSM data faster than the background fetch can complete. The game therefore currently needs to stop gameplay and show a loading screen.

The goal is to turn this into a seamless open-world-style streaming system.

## Most important requirement: FPS stability

**Performance is the highest-priority requirement of this task.**

The game must remain fully playable while OSM data is being downloaded, parsed, built, integrated and unloaded.

### Non-negotiable performance requirements

* Never block the main/game thread waiting for network OSM data.
* Never perform an Overpass request synchronously from the game loop.
* Never parse a large PBF/OSM response synchronously from the game loop.
* Never perform a large world/tile merge synchronously in a single frame.
* Never introduce a large allocation spike during normal gameplay.
* Never rebuild the entire world when a new tile arrives.
* Never scan all existing world objects every frame to determine streaming state.
* Do not increase per-frame work merely because streaming is active.
* Streaming work must be incremental and budgeted.
* New OSM objects must be integrated over multiple frames when necessary.
* Existing rendering, collision, NPC traffic, pedestrian simulation and gameplay must continue while streaming happens.
* Streaming must be allowed to take longer rather than causing an FPS spike.
* Prefer deferred work over doing too much work in one frame.
* Do not trade a loading screen for frame-time spikes.

The target is **stable frame pacing**, not merely a high average FPS.

Existing performance optimizations must be preserved, including the current spatial grids, road caching/culling, tile object tracking, incremental integration and other relevant optimizations already present in the repository.

Before changing anything, inspect the current implementation and identify which existing performance mechanisms must remain intact.

---

# Desired architecture

Implement a seamless streaming system based on a **streaming horizon** rather than a hard loading boundary.

Conceptually:

```text
                    Direction of travel
                           ---->

                 [ predictive horizon ]
                    [ tile ][ tile ]
               [ tile ][ PLAYER ][ tile ]
                    [ tile ][ tile ]

                         |
                         v

              background streaming system
                         |
              +----------+----------+
              |                     |
         local cache             network
              |                     |
              +----------+----------+
                         |
                    background
                  parse/build work
                         |
                         v
                 incremental merge
                         |
                         v
                    live world
```

The player should not have to wait for the next tile to become available.

---

# 1. Inspect the existing implementation first

Before writing code:

1. Read `AutoFetchManager` completely.
2. Read the relevant startup/loading logic in `main/__init__.py`.
3. Inspect `WorldCacheManager`.
4. Inspect the OSM cache implementation.
5. Inspect the existing tile streaming tests.
6. Identify how `loaded_tiles`, `active_tiles`, `pending_tiles`, `_completed_tile_batches`, `_merge_queue`, `map_revision`, inactive tiles and tile eviction currently work.
7. Identify exactly where the loading screen is triggered.
8. Identify which operations currently happen on the main thread.
9. Measure or reason about the current frame-time cost of:

   * tile integration
   * object registration
   * grid updates
   * tile eviction
   * world cache operations
   * large OSM batches

Do not rewrite working systems simply to introduce a new abstraction.

Reuse the existing streaming infrastructure wherever possible.

---

# 2. Separate startup loading from runtime streaming

The initial game startup may still require a loading phase when absolutely necessary.

However, once the player is in the world:

**No loading screen should be required merely because the player is approaching an unloaded OSM area.**

Runtime streaming must be independent of the startup loading screen.

If cached OSM data is already available:

* use it immediately;
* do not wait for a network refresh;
* refresh/update it in the background.

If no cached data exists:

* fetch it in the background;
* keep the game running;
* use the existing loaded world until the new area becomes available.

---

# 3. Predictive streaming

Do not wait until the player actually enters a new tile.

Predict where the player is going based on:

* player position;
* current tile;
* velocity;
* driving direction;
* optionally recent movement direction;
* optionally route/navigation direction if this information is already available.

Create a streaming horizon ahead of the player.

The horizon should adapt to movement.

For example:

```text
stationary:
    small nearby streaming region

slow:
    nearby region + 1 tile ahead

fast:
    nearby region + 2–3 tiles ahead
```

Do not blindly expand the active region to something like 7×7.

That could dramatically increase:

* Overpass query size;
* parsing cost;
* memory usage;
* world integration cost;
* cache pressure.

The system should fetch only what is actually useful.

---

# 4. Prioritize tiles by importance

The streaming system should distinguish between:

### Priority 0 — immediate gameplay area

The tile containing the player and immediately adjacent tiles.

These must have the highest priority.

### Priority 1 — driving horizon

Tiles in the player's direction of travel.

These should be fetched before tiles behind the player.

### Priority 2 — lateral horizon

Tiles beside the likely path of travel.

### Priority 3 — scenery/background

Tiles that are useful for visual continuity but are not immediately needed for gameplay.

The player should never wait for Priority 3 data.

---

# 5. Consider separating gameplay data from scenery data

Investigate whether OSM data can be processed in stages.

Gameplay-critical data includes things such as:

* roads;
* intersections;
* traffic lights;
* stop signs;
* crossings;
* taxi stops;
* railway data;
* other data required for navigation/NPC behaviour.

Less urgent visual data includes:

* buildings;
* trees;
* benches;
* lamps;
* parking areas;
* decorative scenery;
* other non-critical objects.

If practical within the current architecture, allow the gameplay-critical portion of a tile to become usable before all visual objects have been integrated.

Do not implement this as a large architectural rewrite unless the existing code makes it straightforward.

---

# 6. Replace the hard boundary with a soft boundary

There must be no situation where the player simply reaches an invisible wall and the game freezes while waiting for OSM.

If the player approaches an area for which data is not yet ready, implement a graceful fallback.

A preferred approach is:

```text
data available:
    normal driving

data loading but still sufficiently far away:
    normal driving

player approaching unavailable area:
    gradually reduce maximum driving speed

data becomes available:
    restore normal speed

network temporarily unavailable:
    maintain a safe playable boundary rather than showing a loading screen
```

The speed limitation must be gradual and unobtrusive.

It must not feel like the game suddenly stopped responding.

Do not implement an arbitrary hard speed limit everywhere.

The system should only apply a streaming safety limit when necessary.

If the required data becomes available, immediately remove the limitation.

---

# 7. Improve request strategy

Inspect the current `_background_tile_fetch()` implementation.

It currently combines requested tiles into a larger bounding box.

Determine whether this is still the best strategy for predictive streaming.

Avoid unnecessarily requesting large rectangular areas when only a few leading tiles are needed.

For example, if the player is driving east:

```text
       low priority
           |
           v

      [ ][ ][ ]
      [ ][ ][ ]
      [ ][ ][ ]
          P
          |
          +----> high priority
               [X]
               [X]
               [X]
```

The streaming system should be able to prioritize the leading edge rather than always treating the entire rectangular area equally.

However, do not make dozens of tiny Overpass requests if a reasonably sized combined request is substantially more efficient.

Use measurements and existing cache behaviour to choose the strategy.

---

# 8. Local cache first

The streaming pipeline should effectively be:

```text
requested tile
      |
      +---- local cache exists?
      |          |
      |         yes
      |          |
      |     load/build locally
      |
      no
      |
      v
background network request
      |
      v
cache result
      |
      v
background build
      |
      v
incremental integration
```

A cached tile should never require an unnecessary network request before becoming usable.

Network refreshes should happen independently in the background.

---

# 9. Incremental integration budget

This is critical.

When a completed tile arrives, do not simply integrate an arbitrarily large object batch in one frame.

Introduce or improve a frame-time budget for streaming integration.

For example:

```text
normal frame:
    integrate only a small amount of pending streaming work

frame already expensive:
    integrate little or nothing

frame has spare time:
    integrate more
```

The exact implementation should be based on the existing frame-time architecture.

Do not blindly use a fixed "N objects per frame" limit if object complexity varies significantly.

A time-budget approach is preferable if it can be implemented cleanly.

The system should prioritize:

1. roads required for immediate gameplay;
2. navigation-critical objects;
3. nearby visual objects;
4. distant/scenery objects.

---

# 10. Avoid frame-time spikes during eviction

Tile unloading can also cause stutters.

Inspect the existing inactive tile retention and eviction system.

If unloading a tile involves many objects:

* do not remove everything in one frame if that causes a frame spike;
* use incremental eviction where necessary;
* preserve the existing tile/object bookkeeping;
* do not leave stale references in spatial grids.

Correctness is important, but so is frame pacing.

---

# 11. Do not increase per-frame streaming checks unnecessarily

The game loop must remain lightweight.

Avoid code like:

```python
for every world object:
    determine whether it belongs to a streaming tile
```

Instead use the existing tile bookkeeping and spatial structures.

The desired architecture is approximately:

```text
game loop
    |
    +-- cheap player tile update
    |
    +-- cheap movement prediction
    |
    +-- cheap streaming priority update
    |
    +-- consume a bounded amount of completed work
    |
    +-- render
```

All expensive operations belong outside the main thread or inside carefully budgeted incremental work.

---

# 12. Loading screen removal

Find the exact conditions that currently trigger the loading screen during runtime OSM streaming.

Change those conditions so that:

* startup loading may still use the loading screen;
* runtime tile fetching does not;
* the game remains interactive;
* the player can continue driving;
* streaming happens invisibly in the background.

Do not simply hide the loading screen while keeping the same blocking behaviour.

The underlying architecture must actually become asynchronous/non-blocking.

---

# 13. Handling very slow or failed network requests

The game must remain playable if:

* Overpass is slow;
* an endpoint is rate limited;
* an endpoint fails;
* the network connection temporarily disappears;
* a tile request takes significantly longer than expected.

Existing endpoint cooldowns and retry logic in `overpass.py` must be respected.

Do not hammer Overpass with repeated requests.

If a tile cannot be fetched:

* keep the existing world alive;
* retry using the existing cooldown mechanisms;
* continue streaming other useful tiles;
* do not freeze the game;
* do not show the loading screen.

The player should only encounter a soft streaming boundary if they somehow drive faster than data can be acquired.

---

# 14. Instrumentation

Add lightweight diagnostics so the system can be evaluated.

At minimum track:

* current player tile;
* predicted movement direction;
* streaming horizon;
* queued tiles;
* tiles being fetched;
* completed tiles waiting for integration;
* current integration backlog;
* tile integration time;
* tile eviction time;
* streaming/network state;
* frame time / FPS while streaming.

Diagnostics must be cheap.

Do not perform expensive measurements every frame unless already available.

A debug-only streaming overlay would be useful if there is an existing debug UI architecture.

---

# 15. Performance acceptance criteria

The implementation is NOT complete merely because the loading screen disappeared.

It must satisfy all of the following:

### Gameplay

* Player can continue driving while OSM data is being downloaded.
* Runtime streaming never displays the loading screen.
* Cached data is used immediately where possible.
* Player movement toward the map edge does not freeze the game.
* Slow network conditions do not freeze gameplay.
* Failed network requests do not freeze gameplay.

### Performance

* No blocking network operations on the game thread.
* No large synchronous OSM parsing on the game thread.
* No full-world rebuild when a tile arrives.
* No large single-frame tile integration spikes.
* No large single-frame tile eviction spikes.
* No unnecessary full-world scans.
* No significant increase in normal per-frame CPU work when streaming is idle.
* Frame pacing remains stable while streaming is active.
* Streaming must yield when the frame is already expensive.
* Existing FPS performance must not regress in areas where no streaming is occurring.

### Correctness

* No duplicate objects when a tile is loaded/refreshed.
* No stale objects after tile eviction.
* No broken spatial-grid bookkeeping.
* No missing roads at tile boundaries.
* No visible gaps caused by premature unloading.
* NPC traffic continues to function.
* Pedestrians continue to function.
* Trains continue to function.
* Taxi stops and other gameplay objects remain correct.

---

# 16. Testing

Inspect and extend the existing streaming tests.

Add tests for at least:

1. Predictive tile selection.
2. Direction-aware tile prioritization.
3. Speed-aware streaming horizon.
4. Cached tile availability.
5. Network tile availability.
6. Failed network requests.
7. Streaming while the player continues moving.
8. Incremental integration.
9. Incremental eviction.
10. No duplicate tile/object registration.
11. Runtime streaming without invoking the loading screen.
12. Streaming backlog behaviour.
13. Priority ordering.
14. Soft boundary behaviour if implemented.

Where practical, add performance-oriented tests or instrumentation that can detect unexpectedly large integration batches.

---

# 17. Benchmark before and after

Before modifying the implementation, establish a baseline using the existing benchmark/performance tooling.

Then compare:

* normal gameplay with no streaming;
* active background download;
* large tile integration;
* tile eviction;
* rapid driving toward unloaded terrain;
* slow network;
* cached tile loading.

The critical metric is **frame-time stability**, not just average FPS.

Pay particular attention to:

* average frame time;
* p95 frame time;
* worst frame time;
* number and duration of integration spikes;
* number and duration of eviction spikes.

Do not accept an implementation that improves streaming but introduces noticeable stutter.

---

# 18. Keep the implementation focused

Do not rewrite unrelated systems.

Do not change:

* NPC behaviour;
* rendering architecture;
* road generation;
* game physics;
* train simulation;
* pedestrian simulation;

unless a change is directly required by the streaming implementation.

Prefer small, well-contained changes to:

* `AutoFetchManager`;
* OSM cache/streaming code;
* runtime loading-screen logic;
* existing tests;
* diagnostics.

Preserve the existing architecture wherever it already works well.

---

# Expected result

The final result should feel like a continuous open-world map:

```text
             background streaming
                     |
                     v
       +-----------------------------+
       |     future world data       |
       |  loaded before player gets  |
       |            there            |
       +-----------------------------+
                     |
                     v
              +-------------+
              |   PLAYER    |
              +-------------+
                     |
                     v
             already-loaded world
```

The player should normally never know that OSM data is being downloaded.

Most importantly:

**Do not solve the loading-screen problem by sacrificing FPS.**

A slower background stream is acceptable.

A temporarily incomplete distant world is acceptable.

A slightly reduced speed near an unavailable streaming boundary is acceptable.

A frame-time spike that causes visible stutter is **not** acceptable.

---

## Deliverables

1. Implement the streaming changes.
2. Add/update automated tests.
3. Add lightweight diagnostics where useful.
4. Run the relevant test suite.
5. Run performance benchmarks comparing the old and new behaviour.
6. Report:

   * files changed;
   * architecture changes;
   * how predictive streaming works;
   * how the soft boundary works;
   * how main-thread work is bounded;
   * how frame-time stability is protected;
   * test results;
   * benchmark results;
   * any remaining limitations.

Do not declare success based only on "the loading screen no longer appears".

The implementation is successful only if runtime OSM streaming is seamless **and** the game's frame pacing remains stable.
