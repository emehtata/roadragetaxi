# Road Rage Taxi 0.17.0alpha — Optimize Long-Distance Home Teleports
# and Background Map Preparation

You are working in the Road Rage Taxi repository:

https://github.com/emehtata/roadragetaxi/tree/release/0.17.0alpha

The current Godot client and Python simulation server work well during
normal gameplay. The major remaining problem is long-distance relocation
using the Home feature.

When the player teleports to a saved Home location, the destination may
require substantial new map data. The game can take a long time to make
the destination visible.

The source map is often an already-downloaded local OSM PBF file.
The repository already contains:
- A versioned RWC world-data cache.
- WorldCacheManager.
- PBF extraction and indexing.
- AutoFetchManager and dynamic tile streaming.
- Predictive tile loading.
- Budgeted incremental tile merging.
- Budgeted map synchronization.
- Server-generated map chunks.
- A Godot client that parses chunk messages in worker tasks and
  incrementally adds chunks to the rendered scene.

Your task is to investigate and optimize this existing architecture.
Do not replace it wholesale.

The primary goals are:
1. Make long-distance Home relocations fast and predictable.
2. Reuse already-processed map data whenever possible.
3. Prepare known Home destinations in the background.
4. Keep rendering smooth during all background work.
5. Avoid regressions in normal driving, map correctness, gameplay,
   memory usage, and FPS.

IMPORTANT PROJECT CONSTRAINTS
-----------------------------

- Keep Python responsible for simulation and authoritative game rules.
- Keep Godot responsible for rendering and presentation.
- Preserve the existing top-down Godot renderer and its visual quality.
- Preserve the current stabilized vehicle movement and camera behavior.
- Do not introduce client-side physics or collision decisions.
- Do not introduce BIN-based map caches or BIN-based map architecture.
  BIN cache has been removed and must remain out of this solution.
- Use the existing RWC cache architecture, improving it where necessary.
- Do not invent environment variables or configuration options without
  implementing, documenting, and testing them.
- Do not perform unrelated gameplay or rendering refactors.
- Maintain compatibility with existing world data and cache invalidation
  rules, or implement a safe cache-format/version migration where needed.
- Git pushes are permitted. Do not create or push Git tags.
- Copilot Agent instructions, code comments, and documentation must be
  written in English.

PHASE 1 — TRACE AND MEASURE THE COMPLETE RELOCATION PATH
---------------------------------------------------------

Before changing behavior, trace the complete code path from the Home
command to the first correctly rendered destination view.

Inspect at least:
- src/theroadragetrip/home.py
- src/theroadragetrip/tile_streaming.py
- src/theroadragetrip/osm/autofetch.py
- src/theroadragetrip/osm/pbf_source.py
- src/theroadragetrip/osm/cache.py
- src/theroadragetrip/world_cache.py
- src/theroadragetrip/world_loader.py
- src/theroadragetrip/server/map_sync.py
- src/theroadragetrip/map_chunks.py
- The Home command and teleport handling in the simulation server.
- godot/main.gd
- godot/sim_client.gd
- godot/map_layer.gd
- godot/map_chunk.gd
- Relevant existing tests and performance reports.

Follow the actual code rather than assuming how the Home feature works.

Determine and document:
1. How the destination is selected and how the player position changes.
2. Whether the current world already contains the destination.
3. How the active tile window changes after relocation.
4. Whether missing destination tiles are served from RWC, another cache,
   a local PBF extraction, or a network request.
5. Whether the same area is parsed or built repeatedly.
6. How tile results are merged into the live world.
7. Which derived spatial/gameplay structures are rebuilt.
8. How and when map chunks are regenerated and sent to Godot.
9. How many chunks are queued and how quickly Godot processes them.
10. Which exact stage accounts for the largest part of the delay.

Add targeted timing and counters where necessary. At minimum, measure:
- Home relocation command to position change.
- Cache lookup and cache hit/miss.
- PBF extraction, if invoked.
- OSM parsing and world-object construction.
- RWC read/write time.
- Tile merge duration and queue depth.
- Derived map synchronization duration.
- Chunk generation and transmission.
- Godot chunk JSON parsing.
- Godot chunk queue wait time.
- Godot geometry creation time.
- Time until the destination's central playable area is visible.

Do not merely add generic logging. Instrument the real stages with
consistent, low-overhead measurements and useful aggregate summaries.

Establish a reproducible baseline for:
A. A relocation to an already-loaded location.
B. A relocation to a location with a valid persistent cache.
C. A relocation to a location without a valid persistent cache.
D. Returning to a previously visited destination.

If automated tests cannot run a complete Godot session, separate the
server-side benchmark from the Godot rendering benchmark and document
the limitation.

PHASE 2 — RWC CACHE COVERAGE FOR DYNAMIC MAP TILES
-------------------------------------------------

Investigate how WorldCacheManager and RWC caching currently interact
with dynamically fetched tiles.

If dynamic tile loading does not already reuse RWC cache entries
effectively, extend the existing architecture so that completed map
tiles can be loaded from and persisted to the existing RWC format.

Requirements:

- Reuse existing RWC serialization, validation, and invalidation
  mechanisms wherever possible.
- Do not implement a second unrelated cache format.
- Cache keys must identify the exact tile/area and relevant source
  and transformation versions.
- Ensure cached data is compatible with the current coordinate system,
  tile size, OSM source, and map-generation logic.
- Avoid collisions between different tile sizes or source datasets.
- Invalidate data safely when map-generation logic changes.
- Write cache files atomically so interrupted writes cannot leave
  apparently valid partial files.
- Handle corrupted, truncated, stale, and incompatible cache entries
  safely.
- Concurrent requests for the same missing tile must not trigger
  duplicate expensive extraction/build operations.
- Preserve the current behavior when no valid cache entry exists.
- Never block the simulation tick while reading, building, or writing
  a large map tile.
- Avoid loading an unnecessarily large map area for a small request.

Pay particular attention to the existing PBF tile-size rationale.
The current source documents approximately 28 seconds and 530 MB for
processing an approximately 10 x 10 km area against the Finland PBF.
Verify whether this remains representative and measure the current path.

Do not simply increase the tile size. Larger tiles can make long-distance
relocations worse by increasing extraction time and memory use.

PHASE 3 — BACKGROUND PREPARATION OF THE HOME DESTINATION
--------------------------------------------------------

Use the saved Home location, when available, as an optional predictive
map-preparation target.

After the Home coordinates are known, the server may prepare missing
map data for the destination in the background, before the player
actually relocates there.

Requirements:

- Reuse the same tile/cache pipeline as normal map streaming.
- Prepare only a bounded destination area sufficient for the initial
  playable view and the existing active tile window.
- Prioritize the destination's central tiles over distant surrounding
  tiles.
- Respect memory limits and background CPU budgets.
- Do not starve active gameplay or foreground map loading.
- Do not run multiple competing PBF extraction jobs for the same area.
- If the player changes Home, cancel or deprioritize obsolete preparation
  work safely.
- If the player relocates before preparation finishes, prioritize the
  tiles needed immediately.
- If the destination is already cached, preparation should be cheap and
  must not rebuild the same data.
- Do not eagerly preprocess the entire country or entire PBF.
- Do not require a network connection when the local PBF and valid cache
  are available.
- Keep preparation optional and robust: failure must not prevent Home
  relocation.

Determine whether the best implementation is a background task in the
existing server process or a bounded worker process. Choose based on
measured CPU, memory, and thread-safety characteristics rather than
adding concurrency without evidence.

PHASE 4 — PRIORITIZED LOADING AFTER RELOCATION
----------------------------------------------

Optimize the path that makes the destination playable.

When the player relocates:
1. Update the authoritative player position correctly.
2. Immediately prioritize the map data required around the destination.
3. Load valid cached tiles before performing expensive source processing.
4. Merge and synchronize destination data incrementally.
5. Generate the nearest required map chunks first.
6. Send chunks in a priority order that makes the central playable area
   visible as soon as possible.
7. Add surrounding chunks progressively without blocking gameplay.

Review the existing 500 m map chunks and the current load/unload radii.
Do not blindly change their sizes or radii; benchmark the impact first.

Review Godot's chunk queue and its current one-chunk-per-frame behavior.
Determine whether a fixed count, a measured time budget, or a hybrid
budget is the best way to prevent frame spikes.

The player must not appear in a completely unusable state while the
destination map is missing.

Provide a clear, lightweight loading indication if necessary, but do
not add an elaborate new UI system.

Avoid rendering a large, incorrect, or stale map as if it were the
destination. A temporary neutral loading presentation is preferable to
incorrect geometry.

Once the central playable area is available, allow the player to resume
driving while remaining map preparation continues in the background.

PHASE 5 — KEEP BACKGROUND WORK FROM HURTING FPS
------------------------------------------------

The core requirement is that map preparation must not cause noticeable
rendering or simulation stalls.

- Bound foreground tile merge and map-sync work per simulation tick.
- Bound Godot geometry creation work per frame.
- Keep expensive PBF processing outside the main simulation tick.
- Use worker threads/processes only where operations are safe.
- Do not mutate live world collections concurrently without a clear,
  tested synchronization strategy.
- Avoid holding large duplicate representations of the same map data.
- Keep background memory usage bounded.
- Preserve active tiles and recently visited locations sensibly without
  defeating memory management.
- Avoid unnecessary full-world rebuilds after a local destination load.
- Investigate whether existing derived structures can be updated only
  for affected areas instead of rebuilding everything.
- Preserve correct traffic, collision, pedestrian, building, railway,
  parking, lighting, and other map-dependent behavior.

Do not assume that moving a task to a thread makes it harmless.
Measure frame time, simulation tick time, CPU use, memory use, and
queue growth during background work.

PHASE 6 — TESTS AND BENCHMARKS
------------------------------

Add or extend automated tests for:

1. Valid RWC cache hit: no PBF extraction or redundant world rebuild.
2. Cache miss: correct background preparation and safe fallback.
3. Corrupted/stale cache: safe invalidation and rebuild.
4. Cache format or generation-version change: correct invalidation.
5. Repeated requests for the same destination: no duplicate expensive
   processing.
6. Home changes while preparation is pending.
7. Relocation while destination preparation is incomplete.
8. Priority ordering for destination tiles and map chunks.
9. Bounded merge/sync work and correct eventual completion.
10. No duplicate or missing geometry at tile boundaries.
11. Revisit to a previously loaded/cached destination.
12. Existing normal-driving predictive-streaming behavior.
13. Existing world-cache, map-sync, Home, and Godot rendering tests.

Add a reproducible benchmark that reports:
- Cold destination load time.
- Warm destination load time.
- Time until the central playable area is visible.
- Time until surrounding chunks finish loading.
- Number of PBF extractions.
- RWC cache hits and misses.
- Peak or measured resident memory where available.
- Maximum and percentile frame times during background work.
- Maximum simulation tick duration.
- Chunk queue depth and time to drain it.

Compare the results against the baseline collected in Phase 1.
Do not claim an improvement without measurements.

PHASE 7 — DOCUMENTATION AND DELIVERY
------------------------------------

Add an English performance report under:
.github/performance-analysis/

Document:
- The measured root cause.
- The before/after timings.
- The cache and scheduling changes.
- Memory and FPS trade-offs.
- Remaining limitations.
- How to reproduce the benchmark.

Update relevant tests and documentation.

Run the targeted tests first, then the broader relevant test suite.
Run available Godot headless checks and rendering benchmarks.
Investigate and fix regressions introduced by this work.

Keep the changes focused on long-distance relocation and map loading.
Do not add bus simulation or unrelated features in this task.

At the end, report:
1. The verified root cause and supporting measurements.
2. Files changed and the purpose of each change.
3. Before/after results for cold and warm relocations.
4. FPS and simulation tick impact during background work.
5. Test commands and results.
6. Any remaining bottlenecks.
7. The commit SHA and branch updated.

Push the working branch when the implementation and tests are ready.
Do not create or push Git tags.
