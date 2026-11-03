# Simulation optimization follow-through, 2026-11-03

This implements the measured work in the [simulation audit](rrt-021-simulation-performance-audit.md). The comparison baseline is `14803040`. Production changes are confined to Python NPC and pedestrian code.

## Changes and plan coverage

| Audit priority | Result |
|---|---|
| 0: finer capture | The audit harness now separates NPC grid rebuild, per-driver movement, pair collision, route-job scheduler and population work. Population captures retain every tick's wall/CPU time, inclusive phase times, call counts, exact vehicle counts and route-job counters. |
| 1: NPC hot path | Queue detection rejects obstacles outside the current route segment and reach before evaluating orientation and projected width. Collision checks, update cadence, road boundaries and priority decisions still run. The measured grid rebuild was only 0.21 ms/tick in the preliminary baseline, so removing/reducing rebuilds was unjustified. |
| 2: routing | Lane-correct path construction now yields between road lookups and vertices when called by asynchronous route validation and transit trips. The transit fallback also yields between segments and through validation, rather than doing an entire walk/validate/build in one scheduler step. Its search-time diagnostic sums execution slices, excluding time waiting between ticks. Synchronous callers drain the same generator. Existing graph-revision checks and commit validation still govern the jobs. |
| 3: pedestrian cost | Exact endpoint-to-node lookups use a bounded 2,048-entry cache, discarded atomically when a new pedestrian network commits. This removes repeated searches in dog-walking reachability tests without rounding coordinates or caching routes. Venue spawn candidates outside the distance limit are rejected before building geometry queries. |
| 4: state construction | Profiled and checked a smaller `compact_row` lookup variant; its representative microbenchmark was slower (0.227 s versus 0.224 s for 30,000 rows). No state-format, frequency or encoding change was justified. |
| 5: map growth | Exercised the connected-client map-growth benchmark separately, including state arrivals and tick phases. Results below. |

No population caps, demand reductions, skipped collision checks, new runtime dependencies or traffic-rule changes were introduced. Background route workers and general route-result caching were not justified by these measurements.

## Profiling evidence

Initial cProfile captures identified 39,968 calls to pedestrian endpoint lookup consuming 3.55 s and 13,175 calls to queue detection consuming 1.50 s in a simulated minute. After endpoint caching and early queue rejection, an exploratory capture recorded 49,492 endpoint lookups in 0.28 s and 13,605 queue checks in 0.72 s. Average profiled cost per call fell approximately 94% and 54% respectively. These captures differed in live demand and instrumentation and were used to select work, not claim an overall tick speedup.

Path construction previously did all road lookups, lane offsets and corners between scheduler yields (71 calls, 0.36 s cumulative in the initial profile). Its new resumable form exposes those units to the existing scheduler; this is a latency change, not a change to the generated geometry.

The route-step diagnostic then isolated the synchronous transit fallback: 16 individual steps exceeded 1 ms, with a maximum of 9.63 ms and an 8.69 ms maximum inside the fallback walk. After making the fallback resumable, a diagnostic repeat recorded three steps over 1 ms, maximum 3.60 ms. This probe adds overhead and reports wall time, so its tick totals are excluded from the unprofiled comparison. Individual geometry calls, garbage collection and scheduling can still exceed the nominal 1 ms scheduler budget; it remains a soft deadline, with regular yield points rather than hard preemption.

## Measured results

Two unprofiled Oulu rush-hour captures per version, pooled over 3,600 ticks each:

| Metric | Before (`14803040`) | Optimized |
|---|---:|---:|
| Mean / median tick | 9.49 / 8.49 ms | 7.85 / 7.25 ms |
| p95 / p99 | 16.53 / 21.10 ms | 12.52 / 17.00 ms |
| Maximum | 37.07 ms | 31.02 ms |
| >16.67 ms | 171 / 3,600 (4.75%) | 42 / 3,600 (1.17%) |
| >33.33 / >50 / >100 ms | 3 / 0 / 0 ticks | 0 / 0 / 0 ticks |
| Mean total / moving NPCs | 49.50 / 19.23 | 47.38 / 21.83 |
| Mean pedestrians | 74.38 | 73.54 |
| Mean NPC / pedestrian phase | 5.42 / 1.88 ms | 4.64 / 1.22 ms |
| Mean route-job scheduler | 1.19 ms | 1.05 ms |
| Maximum route-job scheduler frame | 11.72 ms | 5.54 ms |
| RSS start / end ranges | 416.4–417.1 / 427.6–428.5 MiB | 416.4–416.5 / 427.5–427.9 MiB |

Mean tick cost fell 17%, p95 24%, p99 19% and maximum 16% in these captures. The optimized version advanced 13% more moving vehicles, with 4% fewer total vehicles and 1% fewer pedestrians from natural population drift. This is evidence of improvement in the sampled workloads, not an isolated CPU-per-entity speedup. No dense capture had a generation-2 collection.

Stratifying the same captures by total population shows the limits of pooled results:

| Natural band | Before: ticks / mean total / moving | After: ticks / mean total / moving | Before mean / p95 / p99 (ms) | After mean / p95 / p99 (ms) |
|---|---:|---:|---:|---:|
| 40 | 1,110 / 42.62 / 21.13 | 1,227 / 40.99 / 21.76 | 8.61 / 15.11 / 18.03 | 7.85 / 13.69 / 18.87 |
| 60 | 953 / 58.95 / 19.36 | 468 / 56.59 / 23.40 | 11.10 / 19.08 / 24.08 | 8.42 / 14.38 / 18.05 |

The 40 band p99 is slightly worse despite a lower mean and p95. Natural timer-driven runs do not establish that every tail percentile improves at every population.

The final natural low-density scenarios measured mean/p95/p99/max of 2.19/3.23/8.04/12.42 ms around 13 vehicles and 2.66/3.66/7.13/10.61 ms around 22 vehicles. Both measured 1,800 ticks and none exceeded 16.67 ms. They confirm the small scenarios still run; differences from the original audit include natural demand drift, so they are not controlled speedup measurements.

The final 180-second connected drive covered 3.57 km at 20 m/s and delivered 5,346 state messages. Map growth was active during 57.3% of measured ticks. Overall tick p95/p99/max was 25.6/43.8/113.5 ms, with one tick over 100 ms. Client gap p99/max was 52.7/114 ms with one gap over 100 ms; replay recorded no frozen frames or clock snaps, but 6.1% of frames had the wrong speed. There were no full GCs. These map-growth delays remain a separate workload limitation; this stationary-hot-path change does not establish that they are fixed.

## Verification

The traffic and server suite passed 521 checks at pytest random seed `1342951790`, and the added transit timing/cancellation regression passed separately (522 checks total). It includes rotated/mirrored suburban traffic, wreck avoidance and resumption, crossings/signals, parking, map levels, route jobs, pedestrian routing/spawning, protocol and headless-server behavior. New regressions check cache bounds, exact coordinates, graph-rebuild invalidation, distance rejection before geometry, yielding between path lookups, and accurate transit timing/cleanup across pauses and cancellation.

The household full-trip test initially failed on both the baseline and modified source: its vehicle was allowed to wait behind unrelated traffic, and the fixture omitted the clock and pedestrian lifecycle needed to complete a visit. It now isolates one household and advances both the clock and pedestrian manager. No production trip cleanup or traffic waiting was weakened.

The corrected household fixture also passed against the unchanged `14803040` production source, confirming the fix is to the test lifecycle. Production changes are committed as `29350948` (pedestrians) and `3f0ece13` (NPC work); the independent fixture correction is `db6146c6`.

## Reproduction and limits

Create a baseline checkout with `git worktree add --detach /tmp/rrt021-baseline 14803040`, then run `./.github/performance-analysis/rrt-021-optimization-data/run_comparison.sh /tmp/rrt021-baseline` from the repository root. Both versions use the same current audit harness, interpreter, OSM map, seed, clock, viewport and warm-up. Dense comparisons run sequentially twice per version; low-density captures and a connected drive follow.

The simulation advances back-to-back in stationary captures; timers influence route-job progress and spawn budgets, so fixed seeds do not make entity histories identical. Population and phase totals must accompany timing comparisons. Each dense capture measures 1,800 ticks after 30 simulated seconds of warm-up. The suburb captures use one warm-up tick and retain natural drift through nominal population bands. These are host- and workload-specific measurements, not a promise of a universal speedup.
