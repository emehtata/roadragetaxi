# Map-expansion stutter: investigation and implementation spec (Phase A)

Revision: `release/v0.22.0beta` at 62b6a75a. Source of this document: reading the current code only. No run was made, so every cost below is **code-confirmed (the work exists on that thread)** or **hypothesis (magnitude unmeasured)**. Older reports in this folder (rrt-021-*, map-loading-02) are context, not proof. Brief: `docs/analysing-map-extension-freezes.md`. Tile size (1000 m tiles, 500 m chunks) is not changed here.

## 1. Pipeline and where each step runs

1. Detect: `AutoFetchManager.start_tile_streaming` (osm/autofetch.py:460), called each tick by `MapStreamer.tick` (server/map_sync.py:260) on the **simulation thread**. Lookahead = 90 s of travel, max 3 tiles (`tile_streaming.lookahead_tiles`). Note: `tile_streaming.py` is at package root, not under `osm/`.
2. Fetch/decode: `_background_tile_fetch` thread -> `world_cache_manager.preload_region` (`world-cache` executor thread; PBF/cache decode, object restore) -> pure Python, **holds the GIL in slices**. One fetch at a time (`is_fetching`), plus `cooldown_s`.
3. Merge: `integrate_completed_tiles(budget_s)` on the sim thread, items via `advance_chunked` (4 ms, `TILE_MERGE_BUDGET_S`; 20 ms when `urgent`). Runs under `manager.lock`.
4. Settle wait: sync starts only after `SYNC_SETTLE_S` 1 s (up to 3 s while a fetch is in flight).
5. Map sync: `map_sync_steps` generator, sim thread, 4 ms/stage slice, shares the tick deadline with the merge. A thread `taxi-roads` (`connected_drivable_ways`, whole-graph search) runs beside it.
6. Chunk rebuild: `_map_grew` (server/__init__.py:~1406) on a map-growth thread; with `--build-in-process` a worker process builds and JSON-encodes, but parent-side `chunk_worker.snapshot` is Python on the parent. `hold=True` while it runs (no merges).
7. Send: `_stream_map_chunks` (sim thread, encode budget `CHUNK_ENCODE_BUDGET_S`), one JSON line per chunk on the same socket as state.
8. Godot: `sim_client._parse_chunk` -> worker task `JSON.parse_string` + `MapChunk.prepare` -> `_chunk_parsed` (deferred, main) -> `_chunk_queue` -> `main._process_chunk_queues` (4 ms budget) -> `MapLayer.replace_chunk` -> `MapChunk.setup` -> `_build_2_5d` (**main**) -> worker task `B3.build` -> `_meshes_ready.call_deferred` (**main**) -> `B3.meshes` (**main**) -> render.

## 2. Confirmed findings (from code)

C1. **Intentional slowdown = `AutoFetchManager.streaming_speed_cap_mps`** (osm/autofetch.py:411; constants :182-185), applied in `simulation.py:505-513` as `speed_limit_mps = min(..., cap)` every tick while driving. Probes 6 x 100 m ahead along velocity for the first tile not in `loaded_tiles`; cap = `max(8 m/s, distance * 0.08)` (300 m ahead -> 24 m/s; current tile unloaded -> 8 m/s). Enabled by `world_loader.py:471` (`soft_boundary_enabled = args.auto_fetch`) and again by `MapStreamer.__init__` (`= True`, server/map_sync.py:218); the MapStreamer line was added in commit 23d1caf8. It is a **real simulation speed limit** (server side, through the physics limiter), not a presentation effect, and exists purely because streaming can lag. It is therefore part of the problem: it is the visible consequence of slow fetch/merge. It releases when the tile is **merged**, not when its chunks are synced and drawn, so the cap and the pop-in are decoupled. In normal 3x3+lookahead operation the unloaded tile is >=1000 m away and the cap should not fire; it fires when a fetch is late. How often it fires is unmeasured (M1).
C2. **Server production has no tick timing.** `server/__init__.py:1115` passes `_NullFrameProfiler`; per-section tick timing, GC callbacks and thread-CPU only exist in `tools/bench_map_jitter.py`. A field stutter cannot be attributed to server or client from a normal run.
C3. **Unbounded steps inside the "budgeted" sync.** A generator budget only applies between `yield`s. Single synchronous blocks with no internal budget: `close_garage_roads(all ways)`, `_add_roadworks_on_new_ways`, `street_lamps[:] = [... scenery_objects]`, `traffic_mgr.start_map_sync`, `arena_crowds.sync_buildings`, `tram_mgr.rebuild`, `ferry_mgr.rebuild`, `list(w.ways)`, `taxi_mgr.sync_map_data(...)` and `_level_structures(...)` (map_sync.py:~190-204; whole-world rebuild of level roads, connectors and route graphs, called on every sync, with no incremental form). Their durations are not recorded individually (stage names group them: "taxi", "level_structures", `CHUNK_INPUTS_READY`). Whether any exceeds 33 ms is a hypothesis (M3); the code does guarantee they scale with total loaded map size, not with the new tile.
C4. **`merge` holds `manager.lock`** while advancing; fetch-progress callbacks and `update_player_tile` take the same lock. Contention is bounded by the 4-20 ms slice but not measured.
C5. **GIL**: decode and restore run in `world-cache`/`map-growth` threads. `performance.tune_interpreter` sets switch interval 0.5 ms and GC thresholds; rrt-021 reports a generation-1 GC (up to 49 ms) overlapping slow ticks. Still historical for this revision (M4).
C6. **Godot main-thread work outside the 4 ms budget.** The `CHUNK_BUDGET_USEC` accounting (`main.gd:366`) covers `replace_chunk` (counted as `chunk_add`, with a 1 us/point draw estimate) only. These run outside it:
 - `_meshes_ready`, a `call_deferred` from the worker: runs when the deferred queue flushes, any number per frame, uncounted.
 - `B3.meshes` (buildings_3d.gd:1909): `ArrayMesh.add_surface_from_arrays` per surface (up to ~10 per chunk), `flat_normals` per vertex in GDScript (`_mesh`, :1985), and a per-vertex GDScript loop for window colours (`arrays["lit"]`, :1944-1948). `Perf` records only `B3.build` (worker, via `build_usec`) as `chunk_buildings_build`, so **the main-thread cost of `B3.meshes` is not measured anywhere**, and the name suggests a main-thread cost that it is not.
 - `_road_snow_3d` (Image + ImageTexture per chunk) inside `_meshes_ready`.
 - The ground-dictionary assembly of `_build_2_5d` (map_chunk.gd:733-830: road/area/prop `map`/`filter` lambdas in GDScript) runs on the **main** thread, before the worker is started; it is inside `chunk_add` but the ~10-20 ms comment there is old.
 - GPU upload of mesh data on first draw, and shadow re-render for new casters: not measurable from GDScript timers.
C7. **Frees**: `_free_chunk` frees mesh nodes with `free()` synchronously; `replace_chunk` frees the old chunk's buildings via `drop_stale_buildings` inside `_meshes_ready`. Unload queue is budgeted by count of calls (one chunk may exceed budget; `spent == 0` always allows one).
C8. **Redundant rebuilds**: after each sync the server resends every chunk its dirty area touched (`take_dirty_areas`), and the client rebuilds a chunk fully even when only a neighbouring tile's items changed. How many resent chunks are byte-identical in content is unmeasured (M6). A queued message is replaced by a newer one (`_queue_chunk`), but one already building on a worker is not cancelled.
C9. **Client has no rubberband correction path to measure.** The player is rendered purely from interpolated server states (`state_buffer.gd`): delay 0.1 s, extrapolation <=0.2 s, clock slew +/-25%, snap on a >0.25 s clock error. There is no client prediction, so "rubberbanding" is either (a) the server tick stalling, then states arriving in a burst (`max_arrival_gap_s`, `underruns`, `render_backsteps` exist), (b) the C1 cap decelerating the car, or (c) a client frame stall (CLIENT_STALL logic exists). Existing diagnostics do not log which of these coincides with a tile event.

## 3. Hypotheses (not established)

H1. Main-thread `B3.meshes` + deferred `_meshes_ready` bursts are the largest client spikes (memory notes ~130 ms/chunk in `chunk_buildings_build`, which is worker time, so main-thread cost is unknown).
H2. `_level_structures` and `taxi_mgr.sync_map_data` are 30-300 ms single-tick stalls in large maps.
H3. Cache decode GIL contention is the main source of 33-50 ms ticks while `_background_tile_fetch` is active (rrt-021 numbers, one run).
H4. The cap (C1) fires mainly when the fetch is serialised behind a previous large fetch, not at ordinary driving speed.
H5. Burst state delivery after a stall is the dominant rubberband cause; the cap is a secondary one.

## 4. Missing or misleading measurements (to add in Phase B, behind a flag or cheap counters)

M1. Counter and log in `simulation.py`: ticks where the streaming cap was the binding limit, cap value, car speed, distance to the unloaded tile, time since the tile was requested.
M2. Server tick duration p50/p95/p99/max and count > 33.3 ms in a real (non-bench) server, with the stage active at that moment (merge, sync stage name, chunk encode, state build). Reuse the section timers from `bench_map_jitter.py`.
M3. Per-step wall time in `map_sync_steps` for every non-chunked block listed in C3 (new stage names), and the max single-slice overrun vs the budget.
M4. GC pauses (`gc.callbacks`) and thread-CPU vs wall of the tick during fetch/decode, separately for cache read, decode, parse and restore.
M5. Godot: rename/split Perf sections: `chunk_build_worker` (B3.build), `chunk_meshes_main` (B3.meshes), `chunk_ready_deferred` (whole `_meshes_ready`), `chunk_ground_dict` (`_build_2_5d` main part), `chunk_free`; per-frame total main-thread chunk time including deferred callbacks; per chunk buildings/vertices/surfaces. Frame times > 16.7/33.3 ms linked to the frame's chunk work.
M6. Resend accounting: chunks sent per sync, how many were content-identical to what the client holds.
M7. State timeline: server send time/position/speed vs client arrival and rendered position, with a marker on tile-merge, sync-complete and chunk-arrival events, so one run shows whether a hitch is server, socket burst or client. Log `max_arrival_gap_s` per tile event, not only per run.
M8. Memory: resident tiles and chunk counts over a 180 s drive.

## 5. Reproducible scenario

Real server (not headless-only tests) plus native Windows Godot 3D renderer (`godot-shot`/`make run`, see AGENTS.md) with `--screenshot-drive`/the `tools/bench_map_jitter.py` driver: fixed start, fixed route and constant speed (e.g. 20 and 33 m/s), same PBF, cold and warm world cache, one dense urban and one sparse area, ~180 s each, so several tile crossings occur. Run once with the cap enabled and once with `soft_boundary_enabled=False` for the A/B on C1 (diagnostic only). Report p50/p95/p99/max, never averages. Headless Linux Godot cannot show render hitches and must not be used to claim their absence.

## 6. Implementation spec (Phase B), by priority; stop after the measured top items

P0. Add M1-M8 instrumentation; no behaviour change. Update this document with the first baseline before P1.
P1. Slowdown: replace the cap's trigger from "tile not merged" to a readiness signal that matches what the player sees, and remove the speed cap for tiles whose fetch is in flight; keep a hard safety only at the real edge of the known world (no road data under the car). Requirement: no cap while a fetch or merge is merely pending. Test must show speed is not reduced by tile events in the fixed scenario. Do not weaken server authority.
P2. Make the C3 blocks resumable (`_level_structures` first if M3 confirms it); each yields between bounded units.
P3. Client: budget `_meshes_ready` (queue ready results, drain under `CHUNK_BUDGET_USEC`); move per-vertex normal/colour loops of `B3.meshes` into the worker-side `B3.build` (arrays only, no Godot objects); build surfaces one per frame if M5 still shows >4 ms.
P4. Skip resending/rebuilding chunks whose content did not change (needs M6).
P5. Only if M4 confirms: cache-decode batching so the GIL is released between items. No tile-size change unless M2/M5 show per-tile batch size, not total work, is the limiter.

## 7. Tests (Phase B/C)

- `tests/`: unit test that `streaming_speed_cap_mps` returns None when the missing tile has a fetch in flight (fails today: returns a cap).
- Server test: a map sync with a large synthetic world never has a single `tick` slice over N ms per stage (fails today for `_level_structures`).
- Godot test: queuing 6 ready chunks results in at most the budgeted `_meshes_ready` work per frame (fails today: all run in the deferred flush).
- Scenario run per section 5 with before/after table; screenshot with `visual_scenarios.json` readiness checks per `docs/visual-testing.md`.

## 8. Out of scope

Tile or chunk size changes (A/B only if M2/M5 point there), Pygame renderer, BIN map format, client physics/collision, tags and releases, rewrite of NPC/pedestrian simulation.

## 9. Implementation (Phase B)

Spec corrections:
- C1: the flag is also set in `world_loader.py:471` (fixed above).
- C3/H2: the first measured run (below) shows `_level_structures` is **not** the worst unbudgeted slice on this map (11.4 ms). The longest single slices are inside the *budgeted* stages: `traffic` 72.9 ms and `pedestrians` 46.0 ms (`advance_map_sync` / `advance_incremental_sync` overrun their 4 ms budget by one indivisible unit), then `railways` 22.0 ms. P2 must target those first, not `_level_structures`.
- C5/H3: the worst tick (551 ms wall) had 34 ms thread CPU, with a world-cache GC on another thread: the tick waited (GIL or lock), it did not compute. Strong hint for H3, not yet split GIL vs `manager.lock`.

Commits (release/v0.22.0beta):
- 60a04e03 P1: `streaming_speed_cap_mps` no longer probes ahead. It returns `SOFT_BOUNDARY_MIN_SPEED_MPS` (8 m/s) only when the tile under the car has no data, otherwise None, so a tile ahead that is fetching or merging never slows the car. Tests: `test_soft_boundary_never_caps_for_a_pending_tile_ahead`, `test_soft_boundary_hard_limit_only_without_data_under_the_car` (both failed before).
- 181c74df P0 (M1-M3 server part): `run_forever` logs `Tick ms: p50 p95 p99 max, N/M over 33.3` every 10 s (`tick_distribution`); `MapStreamer.sync_stage_max_ms` + log line `Map sync longest slice per stage`; `AutoFetchManager.hard_limit_ticks` in the stats dict.
- abc42ef7 P3 + M5 (part): worker-built 3D meshes go to `MapChunk.ready_meshes` and `main._process_chunk_queues` drains them first under `CHUNK_BUDGET_USEC` (at least one per frame), instead of all in one deferred flush. Perf: `chunk_meshes_main` (whole main-thread `_meshes_ready`, incl. `B3.meshes`), `chunk_build_worker` (was `chunk_buildings_build` for 3D). Godot test: six queued results, one over-budget drain applies one.

Measured baseline (`tools/bench_map_jitter.py --preset Oulu --osm-source pbf --drive-s 120 --speed 33`, Linux/WSL, headless socket client, after P1/P0; P1 does not affect this bench because it moves the taxi itself):
- PBF extract missing on this machine: tiles fell back to Overpass (one fetch ~35 s); not the field PBF path.
- Ticks (3482): p50 13.9, p95 31.3, p99 47.0, max 551.2 ms; 30 over 50 ms, 8 over 100 ms. Map busy 99% of ticks.
- Client: state gap p99 64.6 ms, max 637 ms, 15 gaps > 100 ms, 4 freezes, 5 clock snaps.
- GC: 263 young collections, max 70 ms, 26 over 10 ms; no full GC.
- Chunks: 60 sent, 30 resends (M6: whether identical is still unmeasured).
- Godot: full headless suite 8133 checks, 0 failed. `visual_test.py run building_materials_day` passed its readiness checks (avg 158 fps, p99 37.3 ms frame); screenshot inspected, buildings and chunks drawn normally.

Not measured / not done:
- No before/after for P1 in a driven run: the bench teleports the taxi. Logic is covered by the unit tests only.
- No before/after for P3 frame times: no native Windows 3D run with a drive across tiles was made; headless and one static scenario do not prove absence of render hitches.
- P2 not done: evidence points at traffic/pedestrian incremental-sync units, which need their own resumable split.
- P4 not done: needs M6 content comparison first (50% of sent chunks were resends).
- P5 not done: wall >> CPU on the worst tick suggests GIL/lock waiting, but GIL vs `manager.lock` is not separated.
- M4, M6, M7, M8 and the rest of M5 (ground dict, free, per-chunk counts) not added; the bench already reports GC, resends and client gaps.

### 9.1 Tester loop 1 fixes

Commits: 9afcee9c (queued meshes of freed chunks are dropped in `MapLayer._free_chunk`; each async build gets an id and only the newest build's arrays apply), c1d9a44c (`_process_chunk_queues(started_usec, budget)`; the "light ones still share a frame" check no longer depends on wall time and clears the static queue; it also failed at HEAD 62b6a75a in a fresh worktree, so it was already flaky before P3), d2ccffae (visual-test result records `over_16ms` and the chunk Perf sections), d4461b65 (P3: `flat_normals` for every surface and the lit-window colours are computed in the worker `B3.build`; `B3.meshes` reuses them). The Python flake `test_truncated_osm_xml_falls_back` was already there and has nothing to do with this work: a real `pbf-index-cells` daemon thread started by `test_fetch_from_pbf_end_to_end` was still running and called the next test's patched `subprocess.run` (failure listed `.../fixture.osm.pbf.index` as the first out dir). The test file now joins that thread after each test (9c4b0427; 30/30 clean runs of the 12 PBF-related test files under -n auto, against 1 failure in ~25 before).

Native measurement: `visual_test.py run motorway_through_traffic` (Oulu, 40 s drive at full throttle across tiles, windows Godot 4.7.2 forward_plus on an NVIDIA GeForce RTX 5060, 1280x720). Single runs, so expect ±noise:

| build | frames | p50 | p95 | p99 | max ms | >16.7 | >33.3 | >66.7 | chunk_add avg/max | B3 main (`chunk_meshes_main`) avg/max | worker build avg/max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before (181c74df, deferred flush) | 20378 | 1.85 | 2.08 | 2.78 | 88.4 | 17 | 14 | 3 | 31.2 / 76.6 | not timed | 14.0 / 104.8 |
| queue only (abc42ef7+fixes) | 21181 | 1.85 | 2.08 | 2.78 | 76.0 | 18 | 13 | 1 | 32.6 / 77.4 | 1.80 / 10.4 | 15.1 / 108.2 |
| queue + worker loops (d4461b65) | 21572 | 1.85 | 2.08 | 2.78 | 70.6 | 17 | 14 | 1 | 32.1 / 78.5 | 1.07 / 6.2 | 15.4 / 118.9 |

Server during the last run: `Tick ms` p99 6.1-13.8 ms, max 22.0, 0 over 33.3 per 10 s window. Screenshot inspected: motorway, traffic and lamps drawn normally, with the "drawing the new area" note shown during a tile crossing.

New diagnosis (corrects H1): the main-thread spike when chunks arrive is **`chunk_add`** (`MapLayer.replace_chunk` -> `MapChunk.setup` -> the GDScript ground-dictionary assembly in `_build_2_5d`, C6 bullet 4): about 31 ms on average and up to 78 ms per chunk. That matches the 14 frames over 33 ms in every build. `B3.meshes` is small next to it. Its single-call max is 6.2 ms, which is still over the 4 ms budget, so it is **not** within budget. Splitting it per surface would save at most ~2 ms per frame, while `chunk_add` costs ~30 ms. The next step is to move `_build_2_5d`'s ground-dict assembly into the worker `MapChunk.prepare` (pure data). It was not done in this loop.

Not done in loop 1: P2 (evidence points at the traffic/pedestrian sync units, a separate change), P4 (needs M6), P5 (GIL vs lock not separated), per-surface splitting of `B3.meshes` (see above).

### 9.2 Loop 2: the `chunk_add` stall (measured, corrects 9.1)

Splitting `chunk_add` into timers (commit c6a0241c, sections in result.json) showed that the ground-dictionary assembly 9.1 blamed is cheap (`chunk_ground_dict` 0.35 ms avg, 0.9 ms max), and so are the layer setup (`chunk_layers` 0.7 ms) and wildlife (0.5 ms). Almost all of it was **`_lamps_3d`**: 30.5 ms avg, 74.5 ms max, from `B3.lamp_posts_node` building 5 boxes per street lamp in GDScript on the main thread (a motorway chunk has hundreds of lamps). Measured in `visual-test-results/motorway_through_traffic/2026-06-20T1300_20261113-082846_9c4b0427-dirty/result.json`. The ground dict was therefore not moved. Fix in c6a0241c: `B3.lamp_posts_arrays` (boxes + normals, pure data) runs on a worker task; main only creates the mesh (`chunk_lamps_main`). The chunk waits for the task before it is freed, and a newer lamp build's id drops older arrays. The visual-test readiness check also waits for it.

Native Windows Godot 4.7.2, forward_plus, NVIDIA GeForce RTX 5060, 1280x720, `visual_test.py run motorway_through_traffic` (Oulu, 40 s full-throttle drive across tiles), 3 runs per build, all passed readiness. Values: median (worst) of the 3 runs.

| build | p50 | p95 | p99 | max ms | >16.7 | >33.3 | >66.7 | chunk_add avg / max ms | chunk_meshes_main max | chunk_lamps_main max |
|---|---|---|---|---|---|---|---|---|---|---|
| before 181c74df | 1.85 | 2.08 (2.78) | 3.05 (4.17) | 90.0 (114.0) | 18 (20) | 12 (14) | 4 (6) | 31.2 (41.2) / 80.7 (105.8) | not timed | not timed |
| after c6a0241c | 1.85 | 2.38 (2.38) | 3.03 (3.03) | 46.9 (140.0) | 3 (6) | 1 (2) | 0 (1) | 1.29 (1.30) / 3.6 (4.0) | 6.6 (7.5) | 2.8 (3.4) |

Result files:
- before: `visual-test-results/motorway_through_traffic_before_181c74df/2026-06-20T1300_20261113-083512_181c74df-dirty/result.json`, `.../2026-06-20T1300_20261113-083612_181c74df-dirty/result.json`, `.../2026-06-20T1300_20261113-083710_181c74df-dirty/result.json` (built from a worktree of 181c74df plus d2ccffae, the result-recording change only; copied here from that worktree).
- after: `visual-test-results/motorway_through_traffic/2026-06-20T1300_20261113-083148_c6a0241c-dirty/result.json`, `.../2026-06-20T1300_20261113-083252_c6a0241c-dirty/result.json`, `.../2026-06-20T1300_20261113-083355_c6a0241c-dirty/result.json`.
- The "-dirty" suffix comes from unrelated untracked files in the working tree, not from code changes. The single-run 9.1 "before" row had no kept result.json and is replaced by this table.

Screenshot (after, run 2) inspected: the motorway, lamp posts with arms, and the HUD are drawn as before.

Criterion 5 status: `chunk_add` is now bounded (max 4.0 ms, at the 4 ms budget, against 78-106 ms before), and frames over 33.3 ms fell from 12 to 1 (median). Still over budget: one `_meshes_ready` call (`chunk_meshes_main`, max 6.3-7.5 ms). The remaining fix is to build its surfaces one per frame, or to move `ArrayMesh` creation out of the frame with `RenderingServer` mesh calls. One after-run had a single 140 ms frame that none of the chunk timers covers (all chunk sections stayed at 7.5 ms or less in that run), so it is not chunk work. Possible causes are a shader/pipeline compile or GPU upload, which GDScript timers cannot see; it has not been attributed.

### 9.3 Loop 3

Commits: 575ccbd1 (test poll, item 5), 9a945d6f (thread CPU beside wall for the longest sync slice), efd5e8c8 + revert 097c35f1 (identical-resend skip, item 4), 262e4ba0 (mesh creation one surface piece per step, item 1), cbe2610e (queued chunks added before the mesh drain), c938e6db (visual tests: long-frame attribution; wait until chunks stop arriving), 5dd892bf (bench memory samples).

**Item 1: main-thread chunk steps.** `B3.mesh_steps` yields one callable per surface, and surfaces over `MESH_STEP_VERTS` (24000) vertices are cut into whole-triangle pieces. `drain_ready_meshes` runs one step at a time under the budget, and a final step attaches the result (`chunk_meshes_main`). Cost: a dense chunk gets one MeshInstance per 24k-vertex piece (more draw calls). Native Windows Godot 4.7.2 forward_plus, RTX 5060, 1280x720, `motorway_through_traffic`, 3 runs per build, median (worst):

| build | p50 | p95 | p99 | max ms | >16.7 | >33.3 | >66.7 | chunk_add max | largest surface step | attach (`chunk_meshes_main`) max | lamps main max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before 181c74df (from 9.2) | 1.85 | 2.08 (2.78) | 3.05 (4.17) | 90.0 (114.0) | 18 (20) | 12 (14) | 4 (6) | 80.7 (105.8) | not timed (whole `B3.meshes`) | not timed | in chunk_add |
| after 5dd892bf | 1.85 | 2.08 (2.08) | 2.79 (3.03) | 37.1 (39.6) | 2 (5) | 1 (2) | 0 (0) | 2.3 (2.5) | 2.2 (2.2) | 1.3 (1.8) | 2.9 (3.1) |

After files: `visual-test-results/motorway_through_traffic/2026-06-20T1300_20261113-094935_5dd892bf-dirty/result.json`, `.../2026-06-20T1300_20261113-095039_5dd892bf-dirty/result.json`, `.../2026-06-20T1300_20261113-095143_5dd892bf-dirty/result.json`. Before files: as listed in 9.2. Every main-thread chunk step now stays under the 4 ms `CHUNK_BUDGET_USEC`. Intermediate (surface split before cbe2610e): `.../20261113-090246_097c35f1-dirty`, `-090348_`, `-090450_` (largest surface 2.0-2.5 ms).

Regression found and fixed on the way: `dense_city_performance` passed at 62b6a75a and d4461b65, but failed from c6a0241c on ("conditions lost while measuring: N chunks still queued"). Bisected in a worktree: 9c4b0427 passes, c6a0241c fails. The cause was not broken client behaviour. With the lamp stall gone, the scene reached the readiness checks ~7 s earlier (16 s instead of 22-24 s), while the server was still streaming the outer chunks, and those then arrived during the measurement. Fix c938e6db: before measuring, no chunk may have arrived for 1.5 s. Requiring the server's `map_loading` status to be empty was tried first and was not enough: chunks kept arriving after that status cleared. After the fix: 2/2 passed (`visual-test-results/dense_city_performance/2026-10-20T2230_20261113-094540_097c35f1-dirty`, `-094718_`). Screenshot inspected: buildings, lit windows and lamps intact.

**Item 2: long frames.** result.json now has `render.long_frames`: for every frame over 33 ms, its main-process ms, chunk ms and render pipelines compiled. In 9 native motorway runs since this was added, there were 10 long frames. All 10 had chunk work 0.0 ms and main-thread work 1.1-1.8 ms, so neither the main thread nor chunk building caused them. Six (34-43 ms) compiled 5 render pipelines in that frame: shader/pipeline compiles of first-seen material variants. Four (37-64 ms) compiled none and did no chunk or main work. They are outside what GDScript timers and Godot monitors can see (GPU, driver, Windows/WSL scheduling) and are not attributed. The loop-2 140 ms frame predates this recording. It cannot be re-examined, and nothing over 64 ms has recurred in these 9 runs (max 63.8 ms). Next step if needed: pipeline precompilation (Godot's ubershader/pipeline cache warm-up) for the 5-pipeline frames.

**Item 3: server sync overruns, diagnosis corrected.** With thread CPU logged (9a945d6f), the long `traffic`/`pedestrians` slices are CPU on the simulation thread (e.g. traffic 43.4/42.8 ms wall/CPU). A probe run wrapped each unit and recorded garbage collections inside it (90 s Oulu drive, diagnostic script, not committed). Per-unit max:

| unit | max ms | GC inside |
|---|---|---|
| `RouteGraphBuild._add_way` | 30.2 | 30.2 |
| `PedestrianNetwork.advance_rebuild` | 41.7 | 38.9 |
| `_split_way_around_buildings` | 14.4 | 14.3 |
| `_insert_way_into_junction_grid` | 10.9 | 10.9 |
| `_commit_incremental_sync` | 33.5 | 0 (refcount freeing of the old graph) |
| `_commit_route_graph` | 8.4 | 0 |

The longest main-thread GC in that run was 611 ms, likely at load. So the overruns are mostly cyclic-GC passes that happen to start inside a unit, not oversized units: splitting the stages finer would leave the same pauses. Not implemented in this loop, because it changes memory behaviour and needs its own measurement. The fix to try: schedule young collections outside the sync (e.g. `gc.disable()` during map sync slices with a bounded `gc.collect(0)` between ticks, or raise the young threshold) and free the old pedestrian graph in pieces. P2 as written (split stages) is not supported by this evidence.

Bench (`bench_map_jitter.py --preset Oulu --osm-source pbf --drive-s 120 --speed 33`, Overpass fallback because the PBF is missing), before 9a945d6f vs after efd5e8c8 (only P4 differs): ticks p50 11.7/12.1, p95 23.3/25.1, p99 43.3/41.0, max 279/574 ms, over 50 ms 23/14, over 100 ms 6/2; the bench reports counts over 50 and 100 ms, not over 33.3. The difference is run-to-run noise (network fetch timing), not a code effect.

**Item 4: P4 measured, not supported.** Over the same run, 0 of 129 resent chunks were byte-identical to what the client already had (the counter added in efd5e8c8). Every resend carried changed content, so the skip was reverted (097c35f1). Why a merge changes ~70% of the chunks it touches is a separate question: the dirty area per merge is large, and lamps/labels/grids are rebuilt over it.

**Item 5:** `test_the_phone_shows_offers_and_answers_by_id` polls (bounded, 5 s) for the server to hold the command and for the next state, instead of fixed 50 ms sleeps. `make check`: 5 consecutive runs, each 2825 passed, 2 skipped (not timing) + 61 passed (timing), exit 0. `make godot-test` on the final tree: 8137 checks, 0 failed; 20 scripts passed.

**Item 6: memory** (`bench_map_jitter.py ... --drive-s 180 --speed 33`, 5.9 km, server process RSS once a second): 525 MB at the start, 787 at 30 s, 908 at 60 s, then 930 / 922 / 932 MB at 90 / 120 / 150 s, end 934 MB. Loaded tiles stayed at 13-14 (10 at the end). RSS plateaus around 930 MB after the first minute, above the 768 MB `tile_memory_budget_mb` default. The server's chunk index grows (94 → 136 chunks; 132 chunks for 10 tiles, about 4 per tile would be ~40), so it retains chunks of unloaded tiles. That is a candidate for unbounded growth on much longer drives and was not tested beyond 180 s. The Godot client's memory was not measured: the visual-test harness has no memory monitor yet.

### 9.4 Loop 4

Commits: 428c3029 (chunk-index prune), dd77ff67 (no cyclic GC inside a map sync; freeze its result), c34b48f9 (bench counts ticks over 33.3 ms), d6b8a581 (M7 state timeline).

**Item 1: chunk index and memory (criterion 7).** Cause: `ChunkIndex.updated()`/`replaced()` build each new index from *all* of the old index's chunks, and nothing ever removed chunks when tiles were unloaded. Fix: `ChunkIndex.prune()` runs on every final map growth (`_apply_map_growth`). It keeps chunks whose tile is in `loaded_tiles`, or within `UNLOAD_RADIUS + 1` chunks of the player (a client may still hold them), and builds new dicts so a map-growth thread reading the old ones is unaffected. Bench `bench_map_jitter.py --preset Oulu --osm-source pbf --drive-s 180 --speed 33` (5.9 km), samples every 30 s:

| | chunks in index | server RSS MB | tiles |
|---|---|---|---|
| before (5dd892bf) | 94, 109, 116, 120, 131, 144; end 156 | 526, 787, 901, 919, 910, 910 | 9 → 14 |
| after (dd77ff67) | 94, 85, 85, 84, 83, 88; end 82 | 524, 798, 899, 919, 911, 911 | 9 → 14 |

The chunk count now plateaus. RSS plateaus at ~910-920 MB with 14 tiles loaded, so the chunk index was a small share and the loaded world itself is the cost.

**Criterion 7 target, revised by the user:** server RSS must stay under **2 GB** during a long drive, with chunk count and RSS flat after the first minute. The earlier 768 MB figure is `DEFAULT_TILE_MEMORY_BUDGET_MB` (`src/theroadragetrip/osm/autofetch.py:172`), an eviction trigger for inactive tiles, not a process limit. Against the 2 GB ceiling the current ~920 MB plateau meets criterion 7. Still unmeasured: the chunk worker process's own memory and the Godot client's memory.

**Item 2: GC inside the sync (criterion 4).** Choice: `gc.disable()` from the start of a map sync to its end, then `gc.freeze()` and `gc.enable()` (`MapStreamer.tick`, re-enabled on any exception too).
- Why not `gc.collect()` between ticks: the sync's own allocations (route graphs, pedestrian indexes) would be scanned in that collection, which is still a pause on the tick thread.
- Why freeze: it moves them to the permanent generation without a scan, and they are long-lived and acyclic (references are freed by refcounting when tiles unload).
- Known ceiling: cyclic garbage created during a sync is never collected (~200 objects at the end of a bench run).

Same bench, same route, 180 s:

| | ticks | p50 | p95 | p99 | max ms | over 33.3 | over 50 | over 100 | GC collections | longest GC ms |
|---|---|---|---|---|---|---|---|---|---|---|
| before (5dd892bf, run 1) | 5371 | 10.4 | 22.5 | 35.2 | 117.2 | n/a (older bench) | 16 | 1 | 1005 | 66 |
| before (5dd892bf, run 2) | 5374 | 10.4 | 22.6 | 36.0 | 89.8 | 80 | 14 | 0 | 1005 | 55 |
| after (dd77ff67) | 5380 | 10.2 | 20.5 | 36.1 | 93.0 | 62 | 8 | 0 | 141 | 47 |

Max tick is under 100 ms after the change, but the before runs straddle it (117 / 90), so the max alone does not prove the improvement. What the change did is clear: 86% fewer collections, about half as many ticks over 50 ms, and 23% fewer over 33.3 ms. The remaining worst ticks: one 93 ms tick that used 13 ms of CPU while a 47 ms generation-1 collection ran on the map-growth thread (outside the sync, so the collector was on; it holds the GIL), `chunk_swap_and_resend` 32-36 ms (sim thread), and one `map_streamer` 52 ms slice. **Criterion 4 (33.3 ms ticks) stays unmet**: p99 is ~36 ms and 62 of 5380 ticks run over 33.3 ms. Next steps: also suspend the collector during the map-growth chunk rebuild, and budget `chunk_swap_and_resend`.

**Item 3: M7 state timeline (criteria 1, 2).** `state_buffer.gd` records each state's local arrival time, server time, tick, `map_loading` (tile events are its changes) and speed while a visual test measures. `visual_test.gd` writes `render.state_timeline` to result.json. Native Windows Godot, real server, driven `motorway_through_traffic` (40 s full throttle across tile merges), 2 runs:

| run | states | arrival p50 / p95 / p99 / max ms | gaps > 66.7 ms | of which within 1 s of a tile event | server-time gap max | tile events | underruns | render backsteps | clock snaps |
|---|---|---|---|---|---|---|---|---|---|
| `visual-test-results/motorway_through_traffic/2026-06-20T1300_20261113-103417_c34b48f9-dirty/result.json` | 1202 | 33.4 / 36.9 / 42.6 / 74.1 | 1 | 1 | 33.3 | 9 | 0 | 0 | 0 |
| `visual-test-results/motorway_through_traffic/2026-06-20T1300_20261113-103520_c34b48f9-dirty/result.json` | 1200 | 33.3 / 36.8 / 43.5 / 78.2 | 1 | 1 | 33.3 | 9 | 0 | 0 | 0 |

Reading:
- The server produced every state on time: the server-time gap max is 33.3 ms, exactly one tick.
- The single long arrival gap per run (74-78 ms, at 7.4 s in both runs) coincides with a tile event, so it happened in transport or on the client. A likely cause is chunk messages (up to ~2 MB each) on the same socket ahead of the state; not proven.
- The interpolation buffer absorbed it: 0 underruns, 0 render backsteps, 0 clock snaps. No pause or rubberband reached the rendered car in these runs (criteria 1 and 2 on this route).

Not recorded:
- the server's socket send time (not in the protocol; adding a send timestamp to the state message would separate send queue from socket);
- the rendered position against the authoritative one per frame (interpolation error).

The headless bench's client replay reports the same pattern (state gap max 116 ms, 2 gaps > 100 ms, 0 freezes, 0 clock snaps in the 180 s run).

**Item 4: the long frames remain unattributed.** Of the 10 frames over 33 ms in 9 native runs (9.3), **4 (37-64 ms) are unattributed**: in each, chunk work was 0.0 ms, main-process work 1.1-1.8 ms and 0 render pipelines were compiled. What would settle them:
- Godot's GPU frame times per frame (`RenderingServer.viewport_get_measured_render_time_gpu`, enabled in `--bench` but not recorded per long frame);
- a GPU/driver timeline from the Windows side (PIX or Nsight, or the NVIDIA overlay frame log) during a visual test, to see whether the GPU or the present/compositor stalled;
- the same scenario on native Windows without the WSL server, to rule out a host scheduling hiccup affecting the Windows process.

None of these was available in this environment's automation. The other 6 are pipeline compiles; precompiling the 5 pipelines is the fix if they matter.

### 9.5 Ship loop 1 (memory target now 2 GB: criterion 7 met at ~945 MB)

Commits: ad7b05e1 (GC between ticks; replaces the sync-time `gc.disable()`/`gc.freeze()` of dd77ff67), dccc09f3 (no chunk encoding inside the map-growth swap), 109cdd7e (replaced chunk index freed a chunk at a time).

**GC policy (item 1).** `performance.CollectorSchedule`: automatic collection is off in the tick loop (`run_forever`, and `bench_map_jitter`, which mirrors it). After each tick `collect_between_ticks(room)` runs:
- a young pass (`gc.collect(0)`, every 10th `gc.collect(1)`) once 10000 allocations are pending and at least 8 ms remain before the next tick, or regardless at 40000 pending;
- a full pass (`gc.collect()`) only while no client is playing (none connected or all paused), at most once a minute.

Nothing is frozen any more. Cycles are collected by the young/middle passes, or by the next idle full pass if they reach the oldest generation. In a non-stop 180 s drive no idle moment occurs, so 164-230 objects in cycles remained at the end (before: 178-274), which is the same order as with automatic GC. "No cyclic garbage left uncollected for the whole run" is therefore met only if the run includes a pause or menu, not for a continuous drive. Collections never start inside a tick or on a background thread: in every after-run no tick started more than 15 ms late, which shows the collections fit in the gap. The bench's GC timer reports single collections up to 114-126 ms; that contradicts the late-start data and is probably wall time including GIL waits, but it is not resolved.

**chunk_swap_and_resend (item 3).** Profiled: 30 of 33 ms was `_apply_map_growth`'s own time, freeing the replaced index's chunk content at once; up to 18.5 ms was JSON-encoding the player's neighbouring chunks. Fixes:
- only already-encoded chunks are resent in the swap; the others are streamed under `CHUNK_ENCODE_BUDGET_S`, which now covers near chunks too (at least one a tick);
- the old index is freed in 2 ms steps per tick, only while no map-growth thread runs.

Probe: `_apply_map_growth` max 32.9 → 3.8 ms.

**Bench** (`bench_map_jitter.py --preset Oulu --osm-source pbf --drive-s 180 --speed 33`, 5.9 km, 3 runs each, ms):

| build | p50 | p95 | p99 median (worst) | max median (worst) | over 33.3 median (worst) | over 50 | over 100 | tick start late max |
|---|---|---|---|---|---|---|---|---|
| before d6b8a581 (sync-time disable+freeze) | 10.2-10.5 | 20.5-21.5 | 35.4 (35.8) | 148.5 (177.3) | 66 (70) | 7-14 | 1, 1, 1 | 19-29 |
| GC schedule only (ad7b05e1 code, before 109cdd7e) | 9.8-10.3 | 20.8-21.5 | 34.3 (35.7) | 73.3 (78.7) | 60 (63) | 7-9 | 0 | 5-15 |
| after 109cdd7e (GC schedule + resend budget + incremental free) | 10.0-10.2 | 20.7-20.9 | **32.8 (34.3)** | **62.7 (63.1)** | 49 (60) | 2-5 | 0 | 11-15 |

Criterion 4:
- Max tick is under 100 ms in every run.
- p99 is under 33.3 ms in 2 of 3 runs (median 32.8). One run had 34.3, so the target is met on the median but not on the worst run.
- 43-60 ticks a run still exceed 33.3 ms. The remaining worst ticks (50-63 ms) are `simulation` with low thread CPU (11-22 ms, i.e. waiting on the GIL against the world-cache/map-growth threads) and `map_streamer` slices of 34-36 ms CPU. Those are the next targets.

Bench output: `/tmp/.../scratchpad/s_before{1,2,3}.json` and `f_after{1,2,3}.json`. These are scratch files, not kept in the repo; the numbers above are their contents.

**The 4 unattributed long frames (item 4) remain open; they are not fixed.** For each candidate, the evidence that rules it out:
- Chunk building or adding on the main thread: ruled out. `chunk_ms` was 0.0 for each of the 4 frames, and it sums every top-level chunk section (`chunk_add`, `chunk_unload`, `chunk_mesh_surface`, `chunk_meshes_main`, `chunk_lamps_main`).
- Other GDScript main-thread work: ruled out. `main_ms` (the whole `main._process`) was 1.1-1.8 ms in those frames.
- Shader/pipeline compilation: ruled out. All five `Performance.PIPELINE_COMPILATIONS_*` monitors increased by 0 in those frames, while the other 6 long frames each show 5.
- A server stall or state burst: ruled out as a frame-time cause. The client renders from the interpolation buffer, and the M7 runs show 0 underruns, 0 clock snaps and server-time gaps of 33.3 ms max. A late state cannot lengthen a client frame in any case: arrival is handled asynchronously by the network thread.

Not ruled out:
- GPU time of that frame. Godot's measured render time is not recorded per long frame.
- Driver/present/compositor stalls on Windows.
- Host scheduling of the Windows Godot process while the WSL server runs beside it.

What would settle them: record `viewport_get_measured_render_time_gpu/cpu` for each long frame, and capture a Windows GPU timeline (PIX, Nsight or the NVIDIA frame log) during a visual test, ideally also with the server on another machine.

### 9.6 Ship loop 2 (corrects 9.5)

Commits: 5df0d4af (bench places long collections on the tick timeline), 65360414 (collector off during map sync and chunk rebuild; idle unfreeze; replaces ad7b05e1's between-tick schedule), 04ea8e7f (pedestrian network ways chosen in budgeted steps), 3a0d1850 (replaced route/pedestrian graphs freed a piece a tick).

**Correction to 9.5 (GC contradiction, item 1).** 9.5's "probably wall time including GIL waits" was wrong. The new bench field `long_collections` placed every collection over 20 ms in one run on ad7b05e1/109cdd7e code: all were on MainThread **between** ticks, 20-116 ms long (gen 1: 116, 101, 93, 79, 75 ms; gen 0 up to 55 ms), and they pushed the next tick start out by up to 133 ms. `tick_start_late` missed them because the loop resets its schedule when it falls behind. So the "after" rows of 9.5 understated the stall: the tick max excluded those pauses, which stopped state production just the same. Moving collections out of the tick does not make them smaller.

**Client gap regression (item 3).** Bisected over the bench runs already taken, same bench and route (client gaps over 100 ms per run / late frames):

| build | gaps over 100 ms | late frames |
|---|---|---|
| dd77ff67 | 2 | 13 |
| d6b8a581 | 2, 4, 5 | 29, 10, 30 |
| ad7b05e1 (between-tick schedule) | 10, 11, 9 | 59, 47, 49 |
| 109cdd7e | 9, 10, 8 | 37, 37, 31 |

The regression came in with ad7b05e1. Cause: the between-tick collections above. Fix (65360414): the collector is off while a map sync runs and while the chunk rebuild it starts runs (`MapStreamer.hold`, counted, so the overlap of both is handled). At the end their result is frozen and automatic collection resumes. While no client plays, `gc.unfreeze()` and a full pass run at most once a minute, so frozen cycles are still collected, at the next pause. During a non-stop drive, 188-286 objects in cycles remain at the end of a 180 s run (before: 164-274).

**Tick tail (item 2).** Located and bounded:
- `_PedestrianNetworkBuild.__init__` filtered every street (each read lazily decodes the cached way) in one call: ~37 ms. Now `prepare()` runs under the `advance_rebuild` budget. Pedestrian sync slice max 34-37 → 12-15 ms.
- Swapping in the new route graph freed the old route, cycle and motorway graphs at once: 16 ms in `advance_map_sync` and 9 ms in `_commit_route_graph`, profiled as their own time. `performance.GRAVEYARD` now frees replaced graphs (traffic, pedestrian network and indexes) 2 ms a tick. An object still held elsewhere, such as an old graph a route job is using, is only let go, never dismantled. Traffic sync slice max 36 → 10-12 ms.
- A 48-54 ms collection on the map-growth thread inside a tick was behind the 93-110 ms worst ticks. Fixed by the collector-off window covering the chunk rebuild.

Bench (`bench_map_jitter.py --preset Oulu --osm-source pbf --drive-s 180 --speed 33`, 3 runs each; median (worst); tick max includes nothing between ticks, but `tick_start_gap_max` does):

| build | p99 ms | max tick ms | max gap between tick starts ms | over 33.3 | over 50 | over 100 | client gaps > 100 ms | late frames | GC passes, longest |
|---|---|---|---|---|---|---|---|---|---|
| 109cdd7e (9.5 "after") | 32.8 (34.3) | 62.7 (63.1) | 133 (one run measured) | 49 (60) | 2-5 | 0 | 9 (10) | 37 (37) | 561-569, 114-126 ms |
| + pedestrian prepare + graveyard, collector off in sync only | 31.4 (32.8) | 96.7 (110.3) | 97 (110) | 45 (46) | 4-9 | 0, 0, 1 | 1 (1) | 8 (8) | 127-131, 48-54 ms (map-growth, inside a tick) |
| 3a0d1850 (also off during the chunk rebuild) | 33.9 (34.4) | 70.3 (72.5) | 70 (73) | 58 (60) | 4-7 | 0 | 0 (0) | 1 (4) | 89-90, 17-25 ms (none inside a tick) |

Criterion 4 on 3a0d1850:
- **Met:** max tick and max gap between tick starts are under 100 ms in every run (66-73 ms); client gaps over 100 ms are 0 in every run.
- **Unmet:** p99 is 33.9 ms (worst 34.4), just over 33.3; 45-60 ticks a run exceed 33.3 ms. The middle row reached p99 31.4 but had a 110 ms tick. Keeping the collector off through the rebuild traded ~2.5 ms of p99 for removing the >100 ms ticks; the cause of that trade is not measured.
- **Remaining worst ticks:** `simulation` at 12-14 ms of CPU in 67-73 ms of wall time, i.e. waiting for the GIL. The holder was not captured: the slow-tick sampler only lists threads named map-growth / taxi-roads / tile fetch, while the remaining long collections ran on `world-cache_0`. Next step: include `world-cache` threads in that sampler and bound their GIL-holding work (cache decode).

**Native M7 on the current build (item 4).** 2 runs, `motorway_through_traffic`, Windows Godot with the real server, driving across tile merges:
- `visual-test-results/motorway_through_traffic/2026-06-20T1300_20261113-151130_3a0d1850-dirty/result.json`: 1202 states; arrival p50 / p95 / p99 / max 33.4 / 36.7 / 41.3 / 74.5 ms; 1 gap over 66.7 ms, within 1 s of a tile event; 0 underruns, 0 backsteps, 0 clock snaps.
- `visual-test-results/motorway_through_traffic/2026-06-20T1300_20261113-151234_3a0d1850-dirty/result.json`: 1202 states; 33.3 / 36.3 / 42.1 / 74.6 ms; the same single tile-event gap; 0 / 0 / 0.

The server-time gap max is 33.3 ms in both runs (no server stall reached the client). Criteria 1/2 hold on this route for the current code.

### 9.7 Ship loop 3: criterion 4

Commits: 56528659 (bench samples every background thread on a slow tick), 45d606dc (chunk worker hands the GIL to the tick between pickle calls).

**Who the tick waited for.** With `--sample-ms 30` and every thread sampled, 4 of the 6 low-CPU worst ticks (13-14 ms CPU in 54-78 ms wall) caught the map-growth thread in `chunk_worker.snapshot`'s `pickle.dumps` of a piece. Two more caught it in `built_in_worker`, at the `pickle.loads` of every built chunk in one comprehension. `world-cache_0` decoding appeared in two ticks with 24-25 ms CPU, so it is not the dominant waiter. Each pickle call is a C call that keeps the GIL until done. Back to back (50+ per snapshot) they left the tick a fraction of the GIL.

**Fix.**
- `PIECE_SIZE` 500 → 100.
- `chunk_worker.yield_gil()` (`time.sleep(0.001)`) after each pickled piece and after each unpickled chunk. A sleep really releases the GIL, so the background snapshot slows instead of the tick: its pickling now takes 357-453 ms wall (was ~50-75 ms). Full map-growth builds take about 7.3 s (64 chunks, 7307 and 7386 ms); only the nearby 9-chunk rebuild is about 1.8 s.
- No budget was changed.

Bench (`bench_map_jitter.py --preset Oulu --osm-source pbf --drive-s 180 --speed 33`, 3 runs each; median (worst)):

| build | p99 ms | max tick ms | max gap between tick starts | over 33.3 | over 50 | client gaps > 100 ms | late frames |
|---|---|---|---|---|---|---|---|
| before (3a0d1850) | 33.9 (34.4) | 70.3 (72.5) | 70 (73) | 58 (60) | 4-7 | 0 | 1 (4) |
| after (chunk-worker GIL yield) | **29.9 (31.2)** | **49.3 (52.0)** | 51 (52) | **29 (38)** | 0-1 | 0 | 0 (0) |

Criterion 4 (30 Hz ticks):
- **Met:** p99 under 33.3 ms in all 3 runs, max tick under 100 ms in every run.
- **Remaining:** 21-38 ticks a run over 33.3 ms (of ~5380, 0.4-0.7 %). They are now `simulation` ticks with 21-42 ms CPU, i.e. the simulation's own work (NPC population tick, pedestrians), not waiting on the map pipeline.
