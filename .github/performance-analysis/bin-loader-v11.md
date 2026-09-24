# bin-loader-v11: pedestrian route search

## Summary

The V10 621 ms `pedestrians:route_search` was an **unreachable target**. The Oulu pedestrian graph has **2,508 connected components**: one of 56,043 nodes, the next largest 225 nodes, and 54 singletons. `_footway_route_to` targets the network point nearest a door. That point often lies on a small disconnected footway piece, so Dijkstra expanded the start's entire component (up to all 56,043 nodes) and then returned the straight-line fallback.

V11 assigns connected components incrementally while the graph is built and rejects cross-component requests before Dijkstra runs. Route output is unchanged; in a controlled replay, 2,000 of 2,000 routes were identical. The worst route search fell from 119 ms to 5.7 ms in that replay, and from 69.8 ms to 0.32 ms in game runs.

## Architecture (verified in code)

- **Graph.** `PedestrianNetwork` (`pedestrian.py`) has nodes (metric UTM points, merged within 3 m) and undirected edges: every way segment is added in both directions with Euclidean length. Building-crossing pieces are split out beforehand (`_split_way_around_buildings`).
- **Rebuild.** The graph is rebuilt from scratch on every pedestrian map sync. `_PedestrianNetworkBuild` is filled across frames (`advance_rebuild`, budgeted) and swapped in by `_commit`. There are no incremental edits, and node ids are only meaningful within one build.
- **Routing callers.** `PedestrianNetwork.route()` has a single caller: `_plan_pedestrian_route` ← `_footway_route_to` ← `_walk_route_to` (trip-group members, activities) and the vehicle-approach path. A route is planned once per destination change. A failed route still returns the non-`None` straight fallback, so the same request is **not** repeated every frame and no cooldown or cache was needed.
- **Tile unload.** Unloading removes ways from the world lists. The next sync rebuilds the whole network, so no node or component state survives from removed tiles.

## Implementation

- **Union-find (`component_parent`)** on `_PedestrianNetworkBuild`. It is merged per edge in `add_way`, so the cost is spread across the already-budgeted rebuild with no whole-graph pass in any single frame. `_component_root` uses path halving.
- **Committed atomically with nodes and edges.** The component data is committed together with `nodes` and `edges` (`_commit`), so a query can never mix graph generations. The graph is undirected, so connectivity is exactly route reachability.
- **Early rejection in `route()`.** Different roots return the same `[start, target]` fallback as before, with no search.
- **Measurement counter.** `PedestrianNetwork.last_route_expanded` (an int) counts nodes expanded by the last search. There is no logging.
- **A\*: not added.** Edge costs are metric distances and nodes are metric, so a Euclidean heuristic would be admissible. But reachable searches were already at most 4–6 ms (see below), and A\* could change equal-cost tie-breaks. Dijkstra stays the single implementation.

Files: `src/theroadragetrip/pedestrian.py`, `tests/test_pedestrians.py`.

## Correctness

- **`test_v11_route_rejects_other_component_without_searching`:** A–B–C routes, a separate island is rejected with 0 nodes expanded, and the fallback output is unchanged.
- **`test_v11_components_match_brute_force_and_follow_graph_rebuilds`:**
  - union-find agrees with a brute-force flood fill for both the synchronous and the zero-budget incremental build
  - generation N stays live (nodes and components) until N+1 commits
  - N+1 joins former islands correctly
  - a later rebuild with fewer ways (the unloaded-tile case) leaves no stale entries
- **V9 tests pass unchanged,** including the exact-route comparison against brute-force Dijkstra.
- **Full suite:** 1151 passed; only the 5 established failures (NPC ×2, RWD ×2, headless boundary) plus, intermittently, the known flaky `test_npc_population` household test.
- `git diff --check`: clean.

## Performance

**Controlled replay.** Captured the real Oulu pedestrian network after a 900-frame drive: 66,992 nodes and 4,460 door entrances. Replayed 2,000 game-shaped requests (a pedestrian position to `nearest_point` of a door within 300 m) on the identical network, with component rejection disabled (before) and enabled (after):

| Metric | Before | After |
|---|---:|---:|
| route avg | 21.15 ms | 0.33 ms |
| route p95 | 60.34 ms | 1.18 ms |
| route p99 | 76.47 ms | 2.22 ms |
| route worst | 119.36 ms | 5.71 ms |
| worst nodes expanded | 56,043 | 3,430 |
| worst failed (unreachable) search | 119.36 ms | 1.02 ms |
| worst reachable search | 4.01 ms | 5.71 ms (host noise; same search) |
| no-route share | 1,111 / 2,000 | 1,111 / 2,000 (identical results) |

**Game benchmark.** Same command as V10 (`TZ=UTC-15`, Oulu, 3000 frames, driving). Only the rejection is toggled; before and after runs were interleaved.

| Metric | Before A | Before B | After A | After B |
|---|---:|---:|---:|---:|
| route searches (no route) | 9 (0) | 16 (4) | 8 (5) | 2 (1) |
| route worst | 1.50 ms | **69.84 ms** | 0.25 ms | 0.32 ms |
| worst nodes expanded | 635 | **56,043** | 66 | 101 |
| avg / p95 / p99 frame | 33.1 / 44 / 86 | 34.3 / 49 / 128 | 31.5 / 44 / 130 | 31.4 / 46 / 70 |
| worst frame | 504 | 527 | 277 | 288 |
| frames ≥100 / ≥200 / ≥400 | 24 / 14 / 2 | 33 / 25 / 2 | 41 / 4 / 0 | 11 / 1 / 0 |

Every ≥200 ms frame in all four runs is `npc` (up to 471.5 ms) or `map_sync:traffic`, never pedestrian routing. The frame-level differences between these runs are therefore NPC variance, not a V11 effect, and no frame-time improvement is claimed. The 621 ms V10 case was **not reproduced exactly**. The mechanism was: an unreachable target making Dijkstra expand the whole 56,043-node component. That was verified directly, at 69.8 ms in game and 119 ms in the replay; the 621 ms figure was the same search on a slower or more loaded frame.

## Remaining bottlenecks

**Confirmed (measured):**
1. `npc`, the NPC population tick: 170–470 ms frames. It is dominated by NPC route planning (`TrafficWorld.plan_route`, about 120 ms per call) and transit-spawn attempts.
2. `map_sync:traffic`: 137–228 ms.
3. taxi: up to 279 ms (V10, not re-measured here).

**Observation, not a performance issue:** 56% of door-bound pedestrian requests in the replay have no network route, and those pedestrians walk the straight-line fallback. The graph's 2,508 components (building-split footways, disconnected door stubs) are a data and topology question, outside V11.
