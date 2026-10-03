# bin-loader-v4: explaining the remaining ~440-560ms frame

Investigation only, per the task's own rule (section 15). The only production
changes are the ones the task explicitly permits: profiling instrumentation
and one profiler-accuracy bug fix, both inert with respect to gameplay
behavior. `render/roads.py` was not touched.

## 1. Test environment

- City: Oulu (dense preset), the same one used for bin-loader-v2/v3.
- Road data: prebuilt V2 binary (`assets/roads/oulu.bin`, 22,193 ways,
  87,084 nodes), loaded via the existing BIN-first path.
- World cache: warm (`WorldCache` cache hit for both areas fetched during
  the run - `Cache hit ... (30949 roads, 20976 buildings)` and the smaller
  city-preset area).
- Config: `--preset oulu --no-menu --osm-source pbf`, real auto-fetch tile
  streaming enabled (not disabled/stubbed).
- Harness: `utils/benchmark_full_frame.py`, extended in place (not
  replaced) - runs the actual `main()` game loop in-process with a dummy
  SDL driver, `FrameProfiler` forced on, and synthetic input.
- **Scenario fix required before this task could produce valid data**: the
  existing "Driving" scenario (used by v2 and v3 too) held the K_UP key
  but never actually moved the car. The player spawns `on_foot=True`
  (main.py), and throttle is forced to zero while on foot
  (`simulation.py`). Entering the car needs the `F` key, processed as a
  discrete `KEYDOWN` event - not a held key - and the very first `KEYDOWN`
  after warmup is unconditionally consumed by the "awaiting start" overlay
  dismissal (`main.py` ~1416-1422), regardless of which key it is. Fixed
  by sending a throwaway dismiss key, then `K_f`, one frame apart, before
  holding K_UP. Verified directly: car position is now a distinct value on
  effectively every captured frame instead of one fixed value across the
  entire run. This means **v2 and v3's own "Driving" numbers were also
  measuring a stationary car**, not a driving one - worth knowing, though
  out of scope to re-validate here.
- Longest run captured: 15,111 real frames (~110 warmup + ~15,000 driving
  frames, ~7 simulated minutes) holding full throttle straight ahead (no
  steering AI).

## 2. Baseline

From the 15,111-frame driving run (Oulu, warm cache, real tile streaming):

```text
average frame time   28.10 ms
p95 frame time        33.00 ms
worst frame          755.00 ms
average FPS (from avg frame time)   35.6
```

`frames >= 100ms: 42`, `frames >= 400ms: 1`, `frames >= 500ms: 1` - the
"400-560ms" regime described in bin-loader-v3 is a **single, rare, early
event per world load**, not a recurring per-frame or per-tile-crossing
tax. It is exactly reproduced here (755ms, in the same range as v3's
440-560ms and v2's original figures).

## 3. Normal frame breakdown

Representative per-frame costs (average, ms, from the 15,111-frame run;
`map_sync:*` one-shot startup entries excluded - those appear once, see
section 9):

```text
collisions              11.70
rendering               11.43   (parent; render:* children sum to ~9.4)
render:lighting          4.79
physics                  0.99
npc                      0.97
render:actors            1.00
render:roads              1.32
render:markings           0.78
render:hud                0.60
render:scenery            0.56
render:water              0.50
pedestrians               0.44
render:trees              0.44
render:buildings          0.42
render:grass              0.39
taxi (sim)                0.08
map_sync:tile_integration 0.04
traffic (sim)           ~0.00
```

Road rendering (`render:roads`, 1.32ms avg) is now measured with a car
that actually drives, still nowhere near a bottleneck - consistent with
bin-loader-v1's isolated measurement.

## 4. Spike frame breakdown

The single `>= 400ms` frame in this run (frame #3, the very first real
frame after the initial tile load lands):

```text
frame_ms                          755.0 ms
map_sync:tile_integration         532.0 ms   (70.5%)
render:lighting                   110.2 ms   (14.6%)
map_sync:spatial_grid_immediate    47.6 ms   ( 6.3%)
map_sync:building_grid_immediate   27.0 ms   ( 3.6%)
render:scenery                      6.4 ms
pedestrians                         4.8 ms
render:buildings                    4.4 ms
collisions                          4.3 ms
map_sync:spatial_grid               4.1 ms
render:scenery_cache_rebuild        4.1 ms
render:water                        3.4 ms
render:roads                        2.2 ms
render:markings                     1.3 ms
render:hud                          1.2 ms
---------------------------------------------
accounted (sum, exclusive)        756.3 ms   (100%, within rounding)
```

Player/camera position was unchanged from the tile-trigger log line for
this frame (car had not moved from spawn yet - it is the startup load, not
a mid-drive crossing; see section 8). `tiles_pending=3`, GC time this
frame was 3.9ms (negligible).

## 5. Root cause

Not "map synchronization is slow" - the frame is explained, almost to the
millisecond, by **four specific, named costs landing in the same frame**,
none of which is `map_sync:taxi` or `map_sync:traffic` (the two stages v2/v3
flagged as "remaining synchronous work" - see section 9, they turn out not
to be the problem):

1. **`AutoFetchManager.integrate_completed_tiles()` →
   `_merge_tile_world_for_tiles()`** (`src/theroadragetrip/osm/autofetch.py`,
   called from `main.py` line ~2124). Merges every newly-fetched tile's
   ways/buildings/waters/etc into the live world lists, fully synchronously,
   for however many tiles just finished streaming (up to 9 per call, ~18k+
   new items here). **This was completely invisible to the profiler before
   this task** - `integrate_completed_tiles()` self-times into
   `last_tile_integration_ms`, but that metric is read *before* the call
   runs each frame (main.py reads `tile_metrics` near line 2006, the call
   itself happens at line ~2124), so it always reported the *previous*
   frame's cost, never this one. Wrapping the call directly
   (`map_sync:tile_integration`) was required to see its real cost: 532ms,
   70% of the spike by itself.

2. **`draw_illuminated_windows()`'s `_illuminated_window_cache`**
   (`src/theroadragetrip/render/buildings.py:1291-1396`). A full,
   non-incremental rebuild over every visible building's window geometry,
   invalidated whenever the `buildings` list's length/identity changes -
   i.e. every time tiles integrate. Unlike every other static render layer
   (roads/buildings/scenery/water/grass all have their own budgeted,
   incremental `*_cache_rebuild` sub-stage), this cache has no budget and
   no dedicated timer - its cost is silently folded into `render:lighting`.
   Confirmed by the timing coincidence (lighting spikes to 110-190ms across
   every captured spike frame, always on the tile-integration frame, never
   otherwise) and by reading the function: it iterates every visible
   building's window slots with no incremental path.

3. **`map_sync:spatial_grid_immediate` + `map_sync:building_grid_immediate`**
   (`main.py` ~2126-2133). A *separate* code path from the incremental
   `map_sync_stage` state machine bin-loader-v3 built - these run a full,
   synchronous `SpatialWayGrid.rebuild()`/`building_grid.rebuild()`
   unconditionally whenever `integrate_completed_tiles()` returns a
   non-empty result, bypassing the exact incremental machinery built for
   the *same two grids* elsewhere (stage 2's `advance_rebuild()`). This is
   the "old indivisible stall" the task asked to check for (section 5) -
   confirmed still present, just much smaller now (~40-48ms and ~21-27ms,
   not 1.7s) because the grids themselves are smaller mid-tile-burst than a
   fresh world load.

4. **Profiler-accounting bug (found and fixed as instrumentation)**:
   `render:labels`'s stage timer (`render_profile_stage_start`) was last
   reset after the "actors" stage and never reset again before the labels
   block measured its own elapsed time - so `render:labels` silently
   included the entire lighting+weather block's duration on top of its own
   (near-zero, since `label_mode` defaults off). Before the fix,
   `render:labels` reported up to 181-190ms on spike frames, nearly
   identical to `render:lighting`'s own figure - a pure double-count, not a
   second real cost. Fixed by resetting the timer at the correct point;
   `render:labels` now reads ~0.00ms as expected. **Every prior
   bin-loader report's "render:labels" number was measuring this bug, not
   label rendering.**

## 6. Contribution

For the measured 755ms spike frame:

```text
tile_integration (merge)         532.0 ms   (70.5%)
illuminated-window cache rebuild ~106.1 ms   (14.0%, render:lighting minus its
                                              own ~4ms steady-state baseline)
spatial_grid_immediate            47.6 ms   ( 6.3%)
building_grid_immediate           27.0 ms   ( 3.6%)
everything else (rendering,
  collisions, pedestrians, etc.)  ~42.3 ms   ( 5.6%)
```

## 7. Road rendering

**Remains ruled out.** `render:roads` averaged 1.32ms and peaked at
10.96ms across the entire 15,111-frame real-driving run - same order of
magnitude as bin-loader-v1's isolated measurement (~0.4-0.53ms), a bit
higher under full real-world load but nowhere close to contributing to a
>400ms frame. `render/roads.py` was not modified.

## 8. Tile-boundary sequence

Directly observed sequence for the one tile-integration burst captured:

```text
tile fetch completes (background thread, WorldCache load ~3.6-4.0s)
    -> _wait_for_active_tile_fetch's blocking loading screen returns
       (clock is reset here - this multi-second wait does NOT inflate
       any frame_ms; confirmed, no ~4000ms frame was ever recorded)
    -> next real loop iteration: integrate_completed_tiles() merges the
       fetched tiles into ways/buildings/etc - 532ms, fully synchronous,
       previously unmeasured (root cause #1)
    -> same iteration: spatial_grid_immediate + building_grid_immediate
       rebuild synchronously (root cause #3)
    -> same iteration: map_sync_stage state machine kicks off (stage 1+),
       correctly incremental per bin-loader-v3
    -> same iteration: rendering runs, draw_illuminated_windows' cache
       rebuilds because the buildings list just changed (root cause #2)
    -> normal gameplay resumes; subsequent frames return to ~11-28ms
```

**Important caveat, stated plainly**: the 15,111-frame run never produced a
*second* tile-boundary crossing - `tile-boundary transitions: 0` even
after ~7 simulated minutes of full-throttle straight-line driving. The car
did move (confirmed via the on_foot/K_f fix, distinct position on nearly
every frame), but a naive "hold forward, no steering" AI collides with the
street network (buildings, curbs) almost immediately in a dense city grid,
and per-frame `collisions` cost rose sharply once the car was actually
driving (avg 11.7ms, up from ~0.06-0.16ms when the car was stationary in
earlier, buggy runs) - consistent with repeated low-speed contact rather
than free travel. Reaching even one genuine mid-drive tile crossing (the
active region is ~3300m per tile; crossing one needs on the order of
1500-1700m of net travel from the tile center) would require real
road-following steering in the benchmark, which is out of scope for a
measurement-only task. The evidence above is nonetheless a direct,
unconditional measurement of the same functions a mid-drive crossing would
trigger: `integrate_completed_tiles()`'s "if integrated_tiles:" branch and
the `spatial_grid_immediate`/`building_grid_immediate` block run identically
regardless of *why* tiles finished streaming - the startup burst and a
mid-drive crossing are the same code path, just a different trigger.

## 9. Remaining synchronous work

```text
map_sync:tile_integration          - NOT budgeted (new finding, #1 above)
draw_illuminated_windows cache     - NOT budgeted (new finding, #2 above)
map_sync:spatial_grid_immediate    - NOT budgeted (separate from the
map_sync:building_grid_immediate     incremental path built in v3 for the
                                      same two grids)
map_sync:taxi                      - synchronous, but confirmed CHEAP and
                                      one-shot: 42.4ms, present in exactly
                                      1/15,111 frames (the initial map
                                      sync only - never recurs)
map_sync:traffic                   - synchronous, same shape: 134.4ms,
                                      1/15,111 frames, one-shot only
```

`map_sync:taxi`/`map_sync:traffic` were the two stages bin-loader-v3 named
as "remaining synchronous work" - measured directly here, they are real
but small and **do not recur** (each map sync only fully completes once
per tile burst, and both stages finish in well under a frame budget each
time). They do not explain the spike.

**New, separate finding - not tied to tile boundaries at all**: the
simulation-level `taxi` section (`TaxiManager.update()` -> periodic
`generate_offers()`, distinct from `map_sync:taxi`) spiked to 175-650ms
across several runs, present on *every* frame (15,111/15,111) but with a
tiny average (0.08ms) hiding the outliers. Root cause, named precisely:
`pick_random_building_point()` / `pick_random_road_point()`
(`src/theroadragetrip/taxi.py:1001-1149`), called from
`generate_offers()` whenever a new phone offer is generated (observed
roughly every 15-90 simulated seconds in these runs). Both do a **brute-force
nested scan with no spatial index**: for each shuffled candidate building,
for each anchor point, for every way in `self.ways` (30,949 in this
world), for every segment in that way - computing point-to-segment
distance to find the nearest road, before even checking whether the
candidate satisfies the requested distance range. This is a genuinely
different, independently-recurring stall from anything in bin-loader-v2/v3
- it does not need a tile crossing to trigger, and its variance (175ms to
647ms observed across runs) tracks how many buildings get scanned before
one satisfies the constraints, which is random-shuffle-order dependent.

## 10. Recommended next task

Based strictly on the evidence above, in priority order:

1. **Make `_merge_tile_world_for_tiles()`'s per-tile merge budgeted/
   incremental**, the same way bin-loader-v3 did for the map-sync grids -
   it is the single largest contributor (70% of the measured spike) and
   was completely unmeasured before this task.
2. **Give `pick_random_building_point()`/`pick_random_road_point()` a
   spatial index** (reuse the existing `SpatialWayGrid`/building grid
   instead of a linear scan over `self.ways`/`self.buildings`) - this is
   unrelated to tile-boundary work and would fix a real, independently-
   recurring stall (up to 650ms observed) that has nothing to do with map
   synchronization.
3. Fold `spatial_grid_immediate`/`building_grid_immediate` into the
   existing incremental rebuild path (or justify in a comment why they
   must stay synchronous, since they currently duplicate machinery stage 2
   already has).
4. Give `draw_illuminated_windows()`'s cache the same incremental/budgeted
   treatment already applied to buildings/roads/scenery/water/grass.

**Single most useful next optimization target, if only one is picked**:
#1, `_merge_tile_world_for_tiles()` - it dominates the measured spike by a
wide margin and, unlike #2, is specifically what causes the tile-boundary
symptom the last three tasks have been chasing.

Not implemented in this task, per its own rule.
