# bin-loader-v10: global Python GC pauses

> The prompt file `.github/prompts/bin-loader-v10.md` ends mid-sentence in §10 ("Python allocated m"). This work covers §1–§10 as written.

## 1. Executive summary

The game never configured Python's collector: thresholds were the defaults `(700, 10, 10)` on CPython 3.10.12, and GC was enabled throughout. With default thresholds, each 3000-frame Oulu run did **39 generation-2 collections**. In-game passes took 282–492 ms each (852 ms with object counting on), over 1.1–1.33 M tracked objects. **Every one of them collected 0 objects.**

The world is large, long-lived and acyclic, so reference counting already frees everything, including obsolete map revisions and the pedestrian or street-light structures that each sync replaces. Full collections were pure scanning cost.

Shipped change: `gc.set_threshold(10000, 10, 1000)` at game start (`main/__init__.py`, `GC_THRESHOLDS`). Across two final runs:

- **0 generation-2 collections**
- largest single GC pause **21.7 ms** (was 397.5 / 492.0 ms)
- total GC **0.73–0.76 s** (was 3.65–5.50 s)
- RSS unchanged (1160–1169 MB vs 1152–1177 MB)

`gc.freeze()` was measured, but it is **not** shipped: it adds nothing on top of the thresholds in this workload, and it would leak any future cyclic garbage.

## 2. Existing GC usage (verified)

The only `gc` usage in the repository was the benchmark's timing callback (`utils/benchmark_full_frame.py`). There were no `collect`, `disable`, `freeze` or `set_threshold` calls anywhere in `src/`.

V9's frame-attribution fix (GC time keyed to the frame it ran in) is preserved and verified: spike frames now show matching gc time, for example `render:hud` frame 1 with gc 146.8 ms.

## 3. Instrumentation added (benchmark only)

- **Per generation:** collection count, total and maximum pause, and objects collected and uncollectable, from `gc.callbacks` info.
- **Per generation-2 pass:** frame, pause, collected count, and RSS (read from `/proc/self/statm`, cheap).
- **Opt-in only (`V10_GC_OBJECTS=1`):** tracked-object count per generation-2 pass, a type census at the end, and a forced full collect at the end. This is diagnostic only and never used in reported timings.
- **`V10_GC` experiment switch:** `base`, `thresh:A,B,C`, `collect_sync`, `freeze_start`, `freeze_sync` and `freeze_nc`, combinable with `+`. Sync hooks fire after the pedestrian map-sync commit, which is the last heavy map-sync stage.

## 4. Baseline (default thresholds)

| Metric | base A | base B |
|---|---:|---:|
| avg / p95 / p99 / worst | 34.49 / 44 / 74 / 437 ms | 47.13 / 73 / 111 / 533 ms |
| frames ≥100 / ≥200 / ≥400 | 10 / 4 / 1 | 50 / 6 / 3 |
| GC total | 3653.8 ms | 5500.4 ms |
| gen0 count / max | 10143 / 2.6 ms | 10159 / 9.1 ms |
| gen1 count / max | 922 / 2.7 ms | 923 / 6.2 ms |
| gen2 count / max | 39 / **397.5 ms** | 39 / **492.0 ms** |
| objects collected, gen0 / gen1 / gen2 | 315 / 14 / **0** | 315 / 14 / **0** |
| RSS at end | 1152 MB | 1177 MB |

Base B ran noticeably slower overall (host noise). Its GC pauses scale up with it.

**Generation-2 timeline.** 34 passes happen during load, growing from about 10 ms to 290 ms as the heap grows from 108 to 576 MB. Two more happen in frame 1 (the initial tile merge, 816 → 991 MB). Then 3 happen during gameplay: frames 29/45 at the first merge, 517/741, and 864/1220. Each of those takes 282–492 ms at 1120–1191 MB.

## 5. What is in generation 2

Tracked objects at each generation-2 pass (diagnostic run) rise with load: 42 k → 574 k → 961 k → 1.10 M → 1.17 M → **1.33 M**, at a 852 ms pause. Tracked objects at the end are **773 k**, so about 560 k of the peak population is transient. That fits the map-sync build structures (pedestrian junction, segment and spawn grids, street-light and tile-merge work lists), which hold new and old copies alive side by side until commit.

End-of-run census: `list` 463,615 (mostly grid cells), `tuple` 100,899, `dict` 90,533, `Way` 44,849, `Building` 20,119, `Scenery` 10,347, `function` 9,637, `ParkingSpace` 5,026, `SceneryObject` 2,471, `Crossing` 2,016.

## 6–7. Cycles and garbage

- Across the entire run, generation 2 collected **0** objects over 39 passes. Generation 0 and 1 collected 315 and 14.
- A forced `gc.collect()` at the end of the run found **151** unreachable objects among 773 k tracked.
- The one parent-style link checked, `associate_places_with_buildings`, points one way only (Building → Place).
- Tile unload (`AutoFetchManager._unload_tiles`) filters world lists and drops per-tile key sets. Nothing it removes is part of a cycle.

So nearly all of the tracked population is live state or acyclic temporaries, freed immediately by reference counting. Generation-2 cost is scanning, not reclaiming.

## 8. Strategy matrix (3000 frames each, same command)

| Strategy | avg / p95 / worst | ≥100 / ≥200 / ≥400 | gen2 (in-game max) | max gen0/1 pause | GC total | RSS end |
|---|---:|---:|---:|---:|---:|---:|
| A base | 34.5 / 44 / 437 | 10 / 4 / 1 | 39 (397.5) | 2.7 | 3654 | 1152 |
| A base (run 2) | 47.1 / 73 / 533 | 50 / 6 / 3 | 39 (492.0) | 9.1 | 5500 | 1177 |
| B `thresh 10000,10,10` | 35.5 / 50 / 385 | 9 / 2 / 0 | 6 (352.7) | 26.4 | 1758 | 1152 |
| B `thresh 50000,20,20` ×2 | 38.1 / 56 / 254 · 32.3 / 41 / 164 | 18/2/0 · 5/0/0 | 0 | **151.8** / 114.6 | 875 / 845 | 1166 / 1159 |
| **B `thresh 10000,10,1000` ×2** | 32.7 / 44 / 302 · 22.3 / 39 / 159 | 6/2/0 · 3/0/0 | **0** | **30.3** / 26.1 | 785 / 924 | 1153 / 1161 |
| C `collect_sync` | 28.8 / 47 / 445 | 11 / 6 / 1 | 40 (340.4) | 4.0 | 4095 | 1154 |
| D `freeze_start` (collect + freeze at frame 0) | 26.7 / 46 / 354 | 11 / 4 / 0 | 44 (258.1) | 2.9 | 3411 | 1158 |
| D `freeze_sync` (collect + freeze after sync) | 36.1 / 57 / 573 | 21 / 6 / 3 | 40 (521.5) | 4.2 | 4711 | 1185 |
| D `freeze_nc` ×2 (freeze without collect, frame 0 + each sync) | 24.1 / 41 / 321 · 31.7 / 41 / 306 | 18/5/0 · 8/4/0 | 47 (236.4 / 214.5) | 3.8 | 4023 / 3165 | 1162 / 1151 |
| B+D `10000,10,1000 + freeze_nc` ×2 | 24.9 / 44 / 303 · 27.6 / 46 / 210 | 8/1/0 · 5/1/0 | 0 | 25.3 / 26.7 | 814 / 817 | 1159 / 1162 |

Observations:

- **Explicit collection (C, `freeze_sync`)** only moves a 330–520 ms full pass into the map-sync frame. It is worse than nothing during gameplay.
- **Freezing** shrinks later passes, down to 93–236 ms with `freeze_nc`. It doesn't remove them, because each streamed tile keeps adding unfrozen objects.
- **`50000,20,20`** removes generation 2, but it lets generation 1 grow to about 1 M young objects, with pauses up to 152 ms.
- **`10000,10,1000`** keeps generation-1 passes bounded (≤30 ms, 63–64 per run) and needs about 100 M allocations before a full pass. At the measured rate of about 7 M allocations per 3000 frames, that is roughly a quarter-hour of gameplay before the 3.10 "25% long-lived growth" rule even gets consulted.
- Adding `freeze_nc` on top changed nothing measurable, because generation 2 never ran.

All remaining ≥200 ms frames in the threshold runs are non-GC: taxi at 171–279 ms, and `map_sync:traffic`.

## 9–10. Memory behavior

**RSS.** RSS at the end of the run was 1151–1185 MB for every strategy. No strategy grew memory within a run.

The benchmark never unloaded a tile (tile_unload = 0 ms throughout), so a controlled experiment measured load/unload cycles directly. It used real `Way`/`Building` objects held in lists and dict/list grids, loaded 2 tiles per cycle, unloaded the older ones, and rebuilt the grids, for 6 cycles:

| Mode | RSS cycle 0 → 5 | Frozen | End `gc.collect()` found |
|---|---|---:|---:|
| no freeze, acyclic | 132 → 159 MB | 0 | 0 |
| no freeze, deliberate way↔list cycle | 132 → 222 MB (flat after cycle 1) | 0 | 200,002 |
| freeze each cycle, acyclic | 132 → 153 MB | 323,038 (constant) | 0 |
| freeze each cycle, deliberate cycle | **132 → 531 MB, +~80 MB per cycle** | 1,323,048 | 1,000,010 (after unfreeze) |

Conclusions:

- Frozen **acyclic** data is still freed on unload, because reference counting does the work.
- Frozen **cyclic** garbage leaks until `gc.unfreeze()`.

The game currently has almost no cycles, but a future change that introduces one would turn freeze into an unbounded leak. That is the reason freeze is not shipped. The shipped threshold change keeps generation 2 able to run, so cycles are still eventually reclaimed.

## 11. Final verification (shipped default)

| Metric | final A | final B |
|---|---:|---:|
| avg / p95 / p99 / worst | 29.24 / 45 / 64 / 679 ms | 27.96 / 42 / 60 / 196 ms |
| frames ≥100 / ≥200 / ≥400 | 11 / 1 / 1 | 5 / **0** / 0 |
| gen0 count / max | 700 / 3.0 ms | 700 / 3.5 ms |
| gen1 count / max | 63 / 20.8 ms | 63 / 21.7 ms |
| gen2 count | **0** | **0** |
| GC total | 728.9 ms | 759.7 ms |
| RSS end / tracked end | 1169 MB / 779,628 | 1160 MB / 778,015 |

Run A's single frame ≥400 ms (679 ms) has gc = 0. It is one `pedestrians:route_search` of **621 ms**: a Dijkstra search over the whole pedestrian graph, most likely toward an unreachable target. Run B's maximum for the same stage was 0.48 ms. Its other spikes are taxi (≤173 ms), npc (≤102 ms) and `map_sync:traffic` (133–154 ms, of which 19–24 ms is gc).

Tests: full suite **1143 passed, 5 failed**, the same established failures as V7–V9 (NPC ×2, RWD ×2, headless boundary). `git diff --check` is clean.

## 12. Remaining bottlenecks and recommendation

1. **Pedestrian route search.** Dijkstra with no early bound: 621 ms once in run A, and up to 68 ms in V9. Reject unreachable targets using connected-component ids, which the graph build can assign during the budgeted rebuild, and/or use A* with an exact Euclidean heuristic. Both can be kept output-identical.
2. **Taxi.** Up to 279 ms with no GC, recurring across V8–V10.
3. **`map_sync:traffic`**, 133–186 ms.
4. **Long-session GC.** Verify in a 30+ minute soak that the first natural generation-2 pass arrives as rarely as estimated, and measure its pause. If it proves disruptive, `freeze_nc` after map-sync commits is the measured fallback, gated on keeping world data acyclic.
