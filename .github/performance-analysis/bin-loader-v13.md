# bin-loader-v13: `map_sync:traffic`

## Executive summary

`map_sync:traffic` was one synchronous call, `TrafficWorld.sync_map_data`. It rebuilt the whole road route graph (node merging, directed edges, node grid, weakly-connected components) and the parking grid in a single frame: 175–185 ms in game and 177–212 ms offline on the captured Oulu input.

V13 turns it into a **budgeted, snapshot-based build with an atomic commit**, using the same pattern as the V9 pedestrian network:

- a generic `RouteGraphBuild` is filled way by way under the existing `MAP_SYNC_BUDGET_S` (4 ms)
- the node grid and the component union-find are maintained per node and edge, so there is no whole-graph pass
- the previous graph stays authoritative until the commit, which bumps `route_graph_revision` once

In game, the sync now takes 43–51 frames at **p95 6.7–7.1 ms and max 10.0–13.9 ms per frame**, instead of one 175–185 ms frame. The graph and all routes are exactly identical to before.

## Root cause (measured)

**Real Oulu input** (captured `sync_map_data` arguments): 30,589 ways, of which 13,096 are car roads with 64,595 points, and 5,026 parking spaces. It produces 48,130 nodes, 96,688 directed edges, 1,591 grid cells and 668 weak components.

Offline breakdown (5 repetitions each, game GC thresholds, noisy host):

| Stage | Median | Max | GC inside (median / max) |
|---|---:|---:|---:|
| road filter + node merging + edges (per way) | 160–225 ms | 428 ms | 61 / 148 ms |
| weak components (separate union-find pass) | 45–82 ms | 146 ms | 0 |
| node grid | 15–21 ms | 64 ms | 0 |
| parking grid | 4–7 ms | 15 ms | 0 |
| old graph release | 0.0 ms | 0.0 ms | 0 |

The dominant cost is per-way graph construction: the 3 m node-merge bucket lookups plus about 150k new tuples and lists. Weak components were a real but secondary share (about 20–25%). GC contributed young-generation passes caused by those allocations, about 26–28 ms of the in-game 175–185 ms frames. It was not a full collection, since V10's thresholds hold. Releasing the old graph is free, because it is acyclic and freed by reference counting.

## Existing architecture (before)

Main loop map-sync stage 12 called `traffic_mgr.sync_map_data(...)` once, after the tile-merge queue drained and the road spatial grid was rebuilt. It set `self.ways` to the live list, rebuilt `_parking_grid` in place, then ran `_build_route_graph()` → `_finish_route_graph()`, which built the grid, the full-pass components and bumped the revision. Everything happened in one frame. Syncs were already coalesced by the map-sync state machine: a change arriving during sync triggers exactly one more full sync after it.

## Implementation

`src/theroadragetrip/traffic_world.py`:

- **`RouteGraphBuild`:**
  - snapshots `ways` (and optionally `parking_spaces`) at start
  - `advance(budget_s)` adds parking spaces, then ways, through `performance.advance_chunked`
  - each way runs the unchanged node-merge and edge code, plus grid insertion for new nodes and a union per edge
  - `include=` selects which ways form the graph (car roads by default), so other networks can reuse it
- **`_component_root`:** union-find with path halving. Unions keep the smaller root, so a root equals the component's lowest node index, the same values as V12's full pass.
- **`TrafficWorld.start_map_sync` / `advance_map_sync` / `_commit_route_graph`:**
  - the commit swaps nodes, edges, grid, `_route_component_parent`, the parking grid (when rebuilt) and `ways` together, then bumps `route_graph_revision`
  - `sync_map_data` and `_build_route_graph` are now "start + advance to completion", with the same API
  - `_finish_route_graph` is kept for callers that assign graph arrays directly
- **`plan_route_steps`:** looks up component roots lazily (≤ 64 lookups per search stage) instead of reading a precomputed list.

`src/theroadragetrip/main/__init__.py`: stage 12 starts the build once, then advances it each frame with `MAP_SYNC_BUDGET_S`, and moves to stage 13 only after the commit.

`tests/test_traffic_world.py`: three V13 tests, with the pre-V13 algorithm embedded verbatim as the reference. `tests/test_npc_population.py`: the nearest-node test uses a real `TrafficWorld`.

## Incremental architecture

**Snapshots.** `ways` and `parking_spaces` are copied at start, so later merges or unloads of the live lists never reach the build (tested with additions and removals mid-build).

**Budget.** 4 ms per frame, at least one item per frame (`advance_chunked`). Atomic items can exceed it: one long way, or a young-generation GC pass (measured max 10–14 ms).

**Generations.** Until the commit, every query and every V12 route job sees the complete previous graph. The revision increments exactly once, at commit, so jobs planned on the old graph are detected as stale by the existing V12 check.

**Coalescing.** Unchanged and sufficient. The state machine never starts a second sync while one is in progress, and changes that arrive meanwhile produce one follow-up sync of the latest world.

**Tile unload.** A build always starts from scratch from the snapshot, so removed ways leave no nodes, edges, grid cells or components behind (tested).

## Weak components

They cost 45–82 ms as a separate full pass, which is significant. They are now merged per edge during the build, so the separate pass is gone. The graph is directed (one-way roads); weak connectivity is only used as the V12 exact early rejection (a necessary condition for a route), which remains valid. Component data is committed atomically with its graph, and route jobs keep using the previous graph's data until the commit.

## GC / memory

GC inside the old single-frame sync was 26–28 ms, from young-generation passes. Spread across about 45 frames, those passes now land in individual build frames (part of the ≤10–14 ms maxima). The allocation total is unchanged: the same graph is built. Only one graph plus one in-progress build exist at a time, and the old graph is freed by reference counting at commit. No GC policy was changed.

## Correctness

- **Real Oulu input, three repetitions:** the zero-budget and 4 ms incremental builds are exactly equal (`==`) to the pre-V13 algorithm on nodes, edges, node grid and component roots.
- **`test_v13_incremental_route_graph_matches_the_old_full_rebuild_exactly`:** 8 random worlds with one-way roads (±1), layers and near-duplicate points. The old empty graph stays live during a zero-budget build, and 20 `plan_route` results per world match the synchronous graph.
- **`test_v13_components_match_a_brute_force_flood_fill`.**
- **`test_v13_budgeted_sync_snapshots_input_bumps_revision_once_and_unloads_cleanly`:** additions and removals during the build are ignored, the revision bumps only at commit, and a sync after unload leaves no stale nodes, edges, grid or components.
- **V12 route replay:** 400 real Oulu requests, `identical routes: True`.
- **V12 job tests:** stale-revision discard, removed vehicle, fairness, backoff and trip start all pass unchanged.

## Benchmark (real Oulu)

Same command as V10–V12 (`TZ=UTC-15`, 3000 frames, driving). "Before" forces the build to finish in the frame it starts, which is the pre-V13 synchronous behaviour with the same work. Runs were interleaved.

| Metric | Before A | Before B | After A | After B |
|---|---:|---:|---:|---:|
| `map_sync:traffic` frames | 1 | 1 | 43 | 51 |
| `map_sync:traffic` avg / p95 / max | 175.1 | 185.3 | 4.4 / 7.1 / 10.0 | 4.5 / 6.7 / 13.9 |
| GC in the sync frame | 25.7 | 27.5 | spread | spread |
| graph commits (revision bumps) in play | 1 | 1 | 1 | 1 |
| avg / p95 / p99 frame | 35.6 / 45 / 55 | 39.4 / 54 / 75 | 37.4 / 50 / 60 | 40.5 / 58 / 81 |
| worst frame | 871 (taxi) | 653 (taxi) | 266 (taxi) | 302 (taxi) |
| frames ≥100 / ≥200 / ≥400 | 6 / 3 / 1 | 6 / 4 / 1 | 5 / 2 / 0 | 8 / 2 / 0 |
| route jobs queued / ready / failed / stale / discarded | 24 / 12 / 2 / 5 / 1 | 32 / 7 / 8 / 7 / 2 | 20 / 12 / 1 / 3 / 1 | 32 / 7 / 8 / 8 / 2 |
| route wait p50 / p95 (frames) | 239 / 2,013 | 821 / 2,520 | 266 / 1,607 | 849 / 2,336 |
| NPC vehicles / moving (avg) | 9.9 / 3.8 | 14.7 / 2.2 | 10.1 / 4.6 | 11.0 / 3.5 |

In the "before" runs, `map_sync:traffic` was the largest section of a 208 ms and a 221 ms frame. In the "after" runs no frame ≥150 ms involves traffic sync; they are all taxi, plus frame 1, the post-load GC. Whole-frame averages and worst frames are dominated by taxi variance (139–842 ms) and NPC or spawn variance, so no frame-average improvement is claimed; the claim is the removed ~180 ms spike.

## Regression

- Full suite:
  - run 1: 1157 passed, 7 failed. These were the 5 established failures, plus the known flaky household test and `test_crossings::test_draw_pedestrian_reflector_marks_visible_pedestrian`. The latter passes 3/3 alone and 16/16 within its file, so it is order-dependent.
  - run 2: **1159 passed, 5 failed** (established only).
- Focused traffic and NPC tests: 194 passed, with only the 2 established NPC failures.
- `git diff --check`: clean.

## Remaining bottlenecks

**Confirmed (measured this version):**
- taxi: 139–842 ms, non-GC; now the only ≥200 ms source in the "after" runs
- the frame-1 load GC pass: 166–216 ms

**Traffic sync residue:** single build frames up to 10–14 ms, from one long way or a young-generation GC pass inside a chunk.

**Unchanged from V12:** atomic route-job steps (`build_driving_path`, candidate picking) and per-vehicle NPC simulation cost.

## Rejected approaches

- **Background thread:** the build mutates only its own snapshot structures, but the GIL means no frame-time win over budgeted main-thread chunks. It would add shared-state risk.
- **Incremental graph patching per tile (add/remove only changed ways):** the node merge depends on insertion order, and it would break the exact equality with a full rebuild. This was not needed once the rebuild was budgeted.
- **Separate budget constant:** the existing `MAP_SYNC_BUDGET_S` already governs every other map-sync stage; a second knob isn't justified.

## Future work (evidence-based)

1. Taxi frame spikes: the largest remaining source, and a V14 candidate.
2. If 10–14 ms traffic build frames matter, split the node-merge work of very long ways across chunks.
3. Route-job atomic steps, as listed in V12.

## Future vehicle types

`RouteGraphBuild` has no taxi or NPC knowledge. The way filter (`include=`) is a parameter, and the revision, snapshot and commit model is generic. A bus graph (car roads with bus lanes), a tram or rail graph (`railway=*` ways with their own filter) or a snowplough network could build their own graph with the same class and commit it through the same kind of revisioned swap.
