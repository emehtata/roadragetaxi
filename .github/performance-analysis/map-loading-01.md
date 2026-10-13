# Map loading 01 — long-distance Home relocations

Task: [.github/prompts/map-loading-01.md](../prompts/map-loading-01.md).
Branch `release/0.17.0alpha`; baseline is `9d0b216` (before this work).

## Current state (summary)

| Home jump (Oulu, local PBF) | before: chunk under the taxi | after | before: worst tick | after |
|---|---|---|---|---|
| A — 400 m, already loaded | 0.14 s (settled 13.1 s) | 0.13 s (settled 11.0 s) | 266 ms | 328 ms |
| B — 2 km, warm RWC | 13.6–15.1 s | **2.7–2.9 s** | 203–1253 ms | 77–380 ms |
| D — 12 km, warm RWC (revisit) | 9.5 s | **1.1–1.5 s** | 1796 ms | 238–354 ms |
| C — 14 km, cold (PBF extraction) | 25.9 s (38.4 s with the 12 km target) | **11.8–13.4 s** | 4622 ms | 204–362 ms |
| C after 30 s of Home preparation | – | **0.68 s** | – | 207 ms |
| Godot: warm 12 km jump, chunk drawn | 4.9 s | **2.1–2.5 s** | frame p95 56 ms | 57 ms |

- Root cause (measured): after a jump the destination waited behind a
  budget-throttled whole-world map sync (~1 s of work spread over 5–23 s
  of wall time at 4 ms/tick), then a whole-world chunk rebuild (2.4–3.8 s),
  then a client queue that freed the old area's 49 chunks one per frame
  before drawing any destination chunk. A cold jump also ran two separate
  ~11 s PBF extractions (a jump treated as a one-tile step), and the
  simulation stalled for 0.5–4.6 s per tick in NPC/pedestrian searches
  that scan the whole world when nothing is near the player.
- The local PBF is not the bottleneck once a destination is cached: an RWC
  hit loads in 0.3–1.5 s. A cold extraction is ~11 s (full-file scan).
- Remaining: Python's full (gen 2) garbage collection takes 250–300 ms on
  this world and decides the worst tick in normal driving, before and
  after; a cold jump without preparation still pays one ~11 s extraction.

Measurements were taken on a 4-core Azure VM (Godot with the software
renderer, so absolute FPS is low; compare before/after only). Each server
scenario was run 1–3 times; ranges are given where repeated.

## Phase 1 — tracing and measuring the relocation path

The path from H to a drawn destination, as the code runs it:

1. `SimulationServer._home_pressed` sets the car to the saved home
   (`respawn_car` resets, then `car.x/y/heading`) — authoritative position
   changes in the same tick (< 0.02 s).
2. Next tick `MapStreamer.tick` → `AutoFetchManager.start_tile_streaming`:
   the 3×3 tile window (1 km tiles) moves; missing tiles are requested as
   one region on the `WorldCacheManager` executor (`preload_region`), keyed
   by the region's exact lat/lon bbox.
3. `load_area`: an RWC file for that exact region (hit: 0.3–1.8 s to load),
   else fetch (Overpass, or `osmium extract` from the PBF: ~11 s full-file
   scan, 0.76 GB osmium RSS) + `build_ways` + RWC write.
4. The result is merged into the live world lists in 4 ms slices
   (`integrate_completed_tiles`).
5. `map_sync_steps`: trees under roads, road grid, generated house bays,
   building/scenery/small grids, railways, taxi roads, traffic graph,
   pedestrian graph, level structures — for the whole world.
6. `_map_grew`: street lights for the new roads, then a whole-world
   `ChunkIndex` in a background thread; changed chunks resent as
   `chunk_unload` + `chunk`.
7. Godot: chunks parsed in worker tasks, then one add *or* unload per frame
   (unloads first).

Instrumentation added:
- `map_sync_steps` yields name their stage; `MapStreamer` sums busy time
  per stage and logs `Map sync stages: wall, busy, ticks, per stage` once
  per sync (`last_sync`, `sync_stage_ms`).
- `tools/bench_home_relocation.py`: the real server in-process at its tick
  rate, H pressed towards a destination; reports position/central/settled
  times, tick max/p95/p99, RWC hits/misses, PBF extractions, peak RSS,
  per-generation GC pauses, and the stacks of every thread during a tick
  over `--stall-ms`.
- Godot `main.gd`: `relocation_visible` — ms from a > 500 m jump until the
  chunk under the player is drawn with roads (in `--bench` output and the
  log).
- `Map chunks rebuilt for W x H m (lights ms)` log line per growth.

Baseline (before), warm 2 km jump: fetch 0.7 s, merge 0.5 s, sync 5.6–7.3 s
wall for 0.87–1.15 s of work, chunk rebuild 2.4 s → central chunk 12.4 s;
then a second round of the same for the rest of the window. Cold 12 km:
two extractions of 11.4 s and 11.7 s, sync 23.5 s wall, a 6.7 s tick.

## Phase 2 — RWC coverage for streamed tiles

- Streamed regions already use RWC (`preload_region` → `load_area` →
  atomic write: temp file, fsync, rename; magic, `FORMAT_VERSION` 23,
  per-section CRC; invalid files deleted and rebuilt). The per-tile API
  (`save_tile`/`load_tile`) exists but nothing uses it.
- Keys are the exact region bbox, so reuse needs the same request shape.
  That made jumps deterministic only after fixing the request (below); a
  revisit of the same destination is now an RWC hit (scenario D).
- Fixed: a jump along one axis was treated as a one-tile cardinal step and
  trimmed to two rows; the third row needed a second extraction
  (`start_tile_streaming`: the trim now applies only to a step of exactly
  one tile).
- Fixed: the OSM JSON cache (`save_osm_cache`) wrote in place; an
  interrupted save left a truncated file that looked like a cache. Now a
  unique temp file + `os.replace`.
- Concurrent requests for one region share one future (`preload`), across
  both executors.
- PBF tile size: `PBF_TILE_SIZE_M` (3300 m) is no longer applied — nothing
  calls `set_tile_size_m` since the Pygame client's removal — so PBF
  streaming uses 1 km tiles. Measured: a full-file extract of a 3×3 km
  region takes 10.6 s / 0.76 GB, about the same scan as the documented
  10×10 km (28 s / 530 MB at the time). Left unchanged, as asked.
- Grid index (`utils/pbf_index.py`, `make index-pbf`): one 1° cell takes
  13.6 s and 4.0 GB RSS to cut (0.18° cell: 11.7 s / 2.9 GB); a query from a
  cell takes 0.56 s instead of 10.6 s. Not built automatically: the memory
  peak is too high to start unasked on a player's machine. It remains the
  documented opt-in speed-up.

## Phase 3 — preparing the Home destination

- `AutoFetchManager.prepare_window(x, y)` asks for exactly the region a
  jump to (x, y) requests (tested equal), via
  `WorldCacheManager.prepare_region`: nothing if a fresh RWC file exists;
  otherwise a load on its own one-worker executor (a foreground streaming
  load never waits behind it), registered in the shared `_futures` so a
  jump during preparation joins it; the built world is dropped once
  cached (cache, not memory).
- The server prepares once per home, only while the map is idle
  (`_prepare_home_map`); a moved home cancels a preparation that hasn't
  started. A failure only means the jump loads the area then.
- In-process thread, not a worker process: the expensive part is the
  `osmium` subprocess (already a separate process) and RWC I/O; the
  in-process remainder is the XML parse and `build_ways` for one 3×3 km
  region, which the streaming path already runs in a thread. A worker
  process would need the world pickled across for nothing extra.
- Result: a cold 14 km jump after 30 s of preparation shows the
  destination in 0.68 s instead of 11.8–13.4 s.

## Phase 4 — prioritised loading after relocation

- `MAP_SYNC_URGENT_BUDGET_S` (20 ms of the 33 ms tick) for merge and sync
  while the chunk under the player has no roads
  (`SimulationServer.central_chunk_ready`).
- `AutoFetchManager.dirty_rect`: the extent of objects merged in or
  unloaded since the last sync; `ChunkIndex.updated(old, world, region)`
  rebuilds only those chunks from a bbox-filtered view of the world and
  keeps the rest (and their encoded bytes). Verified identical to a full
  rebuild on the real Oulu world and in a unit test.
- The player's 3×3 chunks are rebuilt and swapped in first, with the
  street lights known so far; the rest of the changed area and the new
  lamps follow in a second pass (at night the destination's new lamps
  appear about a second after the streets).
- The chunk rebuild starts as soon as its inputs are synced
  (`CHUNK_INPUTS_READY`: trees, house bays, lamp grid); the taxi, traffic
  and pedestrian graphs finish meanwhile. `hold` now pauses only merges
  and fetches.
- Godot: chunks drawn first within a 4 ms per-frame budget (another one
  only if it fits by the last one's cost, always one), unloads only once
  nothing waits to be drawn; resent chunks replace the drawn copy in the
  same frame; the server resends changed chunks nearest first, without an
  unload before each. A hybrid (time budget, minimum one) was chosen over a
  fixed count: chunk adds range from ~0.1 ms (empty) to ~25 ms (dense);
  a fixed count either wastes frames on empty chunks or spikes on dense
  ones.
- Loading indication: the existing HUD sign (`map_loading`: fetching /
  merging / syncing / building) is shown meanwhile; before the destination
  arrives the taxi stands on the plain ground colour — no stale geometry,
  since the old area's chunks are out of the 7×7 window and unloaded.
- 500 m chunks and the 3/4 load/unload radii were not changed: the
  destination window is 49 chunks, drawn within ~1 s once sent.

## Phase 5 — background work and FPS

- Stalls removed (the main cause of multi-second ticks after a jump):
  NPC destination picks and the pedestrian spawn fallback scanned every
  building/way in the world per attempt next to an empty area; both now
  skip by bbox, and spawning remembers an area with no way within 1 km.
- Bridge guardrails: each bridge outline matched to its own centrelines
  (identical output, 0.36 → 0.06 s); the crossings' underground test skips
  far garage ways by bbox; full `ChunkIndex` on Oulu 1.52 → 1.11 s.
- Taxi road network (`connected_drivable_ways`, 0.1–0.5 s, one call) runs
  in a worker thread while the sync stage yields. Also a gameplay fix:
  every road network at least 10% of the largest is kept, so a far home
  (not yet connected to the start city) has rides and road names.
- Tick time while a jump loads (B, 3 runs): p95 10–11 → 27–31 ms (the
  urgent budget, by design, under the 33 ms tick), p99 30–70 → 59–243 ms,
  worst 203–1253 → 77–380 ms; the whole load takes 6 s instead of 14 s.
- Normal driving, one-tile step (3 runs): settled 11.4–12.3 → 10.0–10.3 s,
  p95 15–23 → 16–20 ms, worst 214 → 261–308 ms. The worst tick in both is a
  gen-2 GC pause (measured 248 ms before, 294 ms after; 2 vs 3 full
  collections in the window — the region rebuilds allocate more).
- Peak RSS: 374–460 MB before and after (no new resident copies; prepared
  worlds are not kept).
- Godot (warm 12 km jump, 45 s `--bench`, software renderer): frame p95
  56 → 57 ms, p99 70 → 65–67 ms, frames over 66 ms 13 → 9–11.

## Phase 6 — tests and benchmarks

New tests: jump requests the whole window (`test_tile_streaming`), region
update equals a full rebuild and keeps other chunks (`test_map_chunks`),
preparation builds once / shares with a jump / keeps nothing / skips a
cached area / never delays a foreground load / same region as a jump /
moved home cancels (`test_home_preparation`), interrupted OSM cache save
leaves no file, changed chunks resent nearest first without unloads, taxi
roads keep a far home network but not fragments (`test_connected_roads`),
pedestrian spawn search once per empty area (`test_walk_walls`), streamer
reports growth at `CHUNK_INPUTS_READY` (`test_server_map_sync`); Godot:
chunk queue latest-message-wins. Existing RWC tests cover corrupt,
truncated and stale-version files.

Reproduce (needs `osmium` and `src/theroadragetrip/assets/osm/finland-latest.osm.pbf`):

```bash
# server side; caches in ~/.cache/RoadRageTrip (delete the destination's files for a cold run)
PYTHONPATH=src python tools/bench_home_relocation.py --preset Oulu --osm-source pbf --dest 428491 7198561
PYTHONPATH=src python tools/bench_home_relocation.py --preset Oulu --osm-source pbf --dest 427800 7224500 --prepare-s 30
PYTHONPATH=src python tools/bench_home_relocation.py --preset Oulu --osm-source pbf --dest-offset 1100 0 --stall-ms 150
# client: a server with a saved home (homes.json beside roadragetrip.ini), then
#   godot --path godot -- --skip-menu --bench 45   (press F, then H; read "relocation:" and BENCH)
```

## Remaining limitations

- Gen-2 GC pauses of 250–300 ms decide the worst tick in normal driving
  (pre-existing). `gc.freeze()` after startup didn't help (most of the map
  arrives by streaming); freezing after every sync would leak unloaded
  tiles held in reference cycles. Options: freeze with an unfreeze at an
  idle moment, or Python 3.14's incremental GC.
- Cold jumps without preparation still pay one ~11 s full-file PBF scan;
  the grid index would make it ~0.6 s but needs 3–4 GB to build.
- The railway rebuild (25–160 ms) and level structures (~20 ms) are still
  single sync steps.
- On a near jump the changed area is most of the loaded map (large
  landuse polygons), so the region rebuild saves little there; the
  player-first pass is what helps.
- After a growth a resent chunk's buildings are rebuilt in a worker
  task, so they can be missing for a frame or two after the swap.
