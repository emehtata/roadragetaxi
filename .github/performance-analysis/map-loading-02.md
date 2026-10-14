# Map loading 02 — stalls and UI jitter while the map grows

Follow-up to [map-loading-01](map-loading-01.md). Branch `release/0.17.0alpha`;
baseline code `df4bcbb`. Measured with `tools/bench_map_jitter.py` (added for
this report) unless noted.

## Summary

**Outcome** (details in [Fixes and results](#fixes-and-results)). On the same
warm route after the fixes: no full garbage collection, worst tick 65–80 ms
instead of 505–536 ms, no state gap over 100 ms, the picture frozen 0–1 times
(under 0.05 s) instead of 24–31 times (4.6–7.7 s), no clock snaps instead of
10–13, and 0.8–1.0 % of frames at the wrong speed instead of 5.5–7.1 %. Chunk
resends fell from 41–52 to 5–6 per drive, and a tile step runs one whole-world
sync instead of two. A first drive into uncached tiles still freezes 12–15
times (1.8–2.1 s, no snaps) because of the tile loader, and the Godot client's
own worst frames didn't improve; both are in [Remaining](#remaining).

**The problem, as measured before the fixes.** While the taxi drives into new
map, the Godot client's picture freezes for 0.1–0.6 s at a time, then jumps or
runs in slow motion for a moment. On the
warm-cache benchmark route (Oulu, 72 km/h, 3.6 km east, 180 s) that is 24–31
freezes (4.6–7.7 s frozen in total), 10–13 clock snaps and 5.5–7.1 % of frames
drawn at the wrong speed, with a client that never drops a frame of its own.

The tile merge itself is not the problem: it is budgeted and cheap. The
problem is what a merge sets off in the one Python server process, which stalls
the 30 Hz tick for longer than Godot's 100 ms interpolation buffer can hide:

1. **Full garbage collections, a regression.** 10–14 per run, 0.27–0.59 s
   each, all while the map syncs or rebuilds chunks. The Pygame client's
   `main()` set `gc.set_threshold(10000, 10, 1000)` (bin-loader-v10) and
   `sys.setswitchinterval(0.0005)` (osm-stream-00) for the process that ran the
   simulation. The standalone server never set them, and `db49742` deleted them
   with the Pygame client.
2. **Background threads share the GIL with the tick.** While the chunk
   rebuild, a tile load or the taxi-road search runs, ticks wait 6–13 ms longer
   on average. Cold tile loads blocked the tick for 130–390 ms at a time without
   any GC.
3. **Unbudgeted work in the tick:** the railway timetable rebuild (43–97 ms),
   level structures (30–44 ms), and JSON-encoding resent chunks (40–60 ms per
   growth).
4. **Whole-world gameplay scans** that get slower with every merge: taxi
   offers and train passengers, 60–420 ms (bin-loader-v4 found the same).
5. **Server time never catches up after a stall,** so every stall shifts
   Godot's clock; above 250 ms it snaps.

Merging is slow because each 1 km tile step runs **two whole-world syncs**
(the new tile column and the lookahead tile are separate fetches), each 1.2–2.4 s
of CPU spread over 7–12 s at 4 ms per tick. A step takes about 20 s to settle.
And the client gets **10–13 chunk resends per tile step**, about half of all
chunk messages while driving, mostly because Godot's chunk window reaches
further than the server's tile window. Each resend rebuilds the whole chunk on
Godot's main thread and makes its buildings blink.

## Method

`tools/bench_map_jitter.py` runs the real `SimulationServer` in-process at its
tick rate (as `run_forever` does), with a socket client in a child process that
reads the same line-JSON stream as Godot. After the start has settled, the taxi
is moved along a straight line through new tiles. Per tick it records:

- wall and thread-CPU time; the difference is time spent waiting for the GIL
  or a lock;
- time per phase (simulation, merge, map sync, chunk swap and resend, chunk
  streaming, state);
- every garbage collection on any thread (a collection holds the GIL, so one
  on a background thread stops the tick too);
- which background threads were alive.

The client logs when each message arrives. `godot/state_buffer.gd` is then
replayed at 60 fps on those arrival times, counting frames where the render
time is past the newest state (the picture holds still), clock snaps (a visible
jump), and frames where the render clock runs more than 5 % off real time.
`tools/bench_home_relocation.py` (map-loading-01) runs without a client, so it
never saw chunk encoding or state delivery.

Machine: 12-core WSL2, Python 3.12.3, the local Finland PBF with its grid
index. Warm-cache figures are two runs (ranges given). Cold-cache figures come
from the same measurement during the investigation, before the tool was
committed (same hooks and replay, measured from 12 s after start instead of
after the start settled), on routes whose tiles weren't cached yet.

Godot's own frame cost is not in these numbers, because the test client never
drops a frame. The client was measured separately, headless, attached to the
same drive (`--port`; see [Fixes and results](#fixes-and-results)); a headless
run measures the GDScript side of chunk handling and drawing, not the renderer.

## Baseline

| 180 s at 72 km/h, Oulu | warm, east (2 runs) | cold, east | cold, north |
|---|---|---|---|
| Tick p99 / max | 31–34 / 505–536 ms | 46 / 583 ms | 37 / 598 ms |
| Ticks over 100 ms | 12 | 18 | 14 |
| Tick p99, map idle / busy | 18 / 48–52 ms | 18 / 63 ms | – |
| Map busy, share of the drive | 38–44 % | 57 % | – |
| Full GCs: count (max, total) | 10–14 (490–521 ms, 4.1–5.3 s) | 13 (576 ms, 6.1 s) | 13 (590 ms, 5.6 s) |
| Chunk messages / of them resends | 90–101 / 41–52 | – | – |
| State gaps over 100 ms | 19–28 | 31 | 29 |
| Picture frozen | 24–31 times, 4.6–7.7 s | 49 times, 9.1 s | 36 times, 7.2 s |
| Clock snaps | 10–13 | 14 | 16 |
| Frames at the wrong speed | 5.5–7.1 % | 11 % | 6.9 % |

## Root causes

### 1. Full garbage collections, a regression from deleting the Pygame client

- In the cold east run, 10 of the 11 ticks over 380 ms were generation-2
  collections; in a warm run the 8 worst ticks all were. They fire inside sync
  stages (the pedestrian and traffic graph rebuilds allocate heavily), in
  `_broadcast_state`, or on the chunk-rebuild and tile-loader threads. A
  collection on a background thread stops the tick just the same.
- A full pass costs 0.27–0.59 s because the server tracks 1.2–1.44 M objects
  by the end of a drive (584 k right after start).
- They free almost nothing. Over a whole drive all generation-2 passes
  together collected 12–86 objects, and a final `gc.collect()` found none.
  Reference counting frees everything else.
- This was measured and fixed once already.
  [bin-loader-v10](bin-loader-v10.md) shipped
  `gc.set_threshold(10000, 10, 1000)` (largest GC pause 492 → 22 ms), and
  osm-stream-00 `sys.setswitchinterval(0.0005)` (an Oulu drive's frames over
  100 ms: 36 → 7), both in the Pygame client's `main()`. The Godot split moved
  the simulation into `python -m theroadragetrip.server`, whose `main()` never
  set them, and `db49742` deleted the old one.

### 2. Background threads share the GIL with the tick

- The chunk rebuild (thread `map-growth`: `ChunkIndex.updated` and street
  lights, 0.3–4.9 s per growth), tile loading (`world-cache` executor: osmium
  output parse, `build_ways`, RWC write) and the taxi-road search (`taxi-roads`)
  are Python threads. While one runs, each tick waits 6–13 ms longer on average
  (p95 16–36 ms).
- During cold loads the tick was blocked for 130–390 ms at a stretch with no
  GC involved, while the loader finished a 63–72 k element extract.
- Measured in isolation on a 3 × 3 km extract: an OSM-cache hit's `json.load`
  holds the GIL for 80–90 ms in one C call. The OSM cache's `json.dump` does
  not; it is pure Python and yields every few milliseconds.
- At the default 5 ms switch interval, every hand-back of the GIL to the tick
  is slow. The Pygame client's 0.5 ms setting was lost with it (see 1).

### 3. Unbudgeted work in the tick

- `trains.rebuild` (sync stage "railways": timetable matching and station
  calls) runs as one 43–97 ms step. It runs right after `CHUNK_INPUTS_READY`
  starts the chunk-rebuild thread, so it also competes with that thread for the
  GIL.
- Level structures: one 30–44 ms step.
- `_apply_map_growth` JSON-encodes every resent chunk in the tick: 40–60 ms
  for a growth that resends about 10 chunks.

### 4. Whole-world gameplay scans

`TaxiManager.generate_offers` calls `passenger_waiting_position` three times
per offer, each a scan over every road segment, and `pick_random_building_point`
scans every building; train passengers reach the same scan through
`rail_bookings`. These gave 60–420 ms ticks with no GC;
[bin-loader-v4](bin-loader-v4-frame-spike-analysis.md) found the same (up to
~650 ms). This isn't merging, but every merge makes them slower.

### 5. Server time never catches up

`run_forever` resets its schedule after an overrun, and each tick still
advances 33 ms of simulation. A stall therefore moves server time back against
Godot's local clock for good. `state_buffer.gd` snaps its render clock when the
shift exceeds 250 ms (`CLOCK_SNAP_S`); otherwise it slews at up to 25 % until it
catches up, which is the slow motion.

## Why a tile step takes about 20 s

One warm-cache step, as logged: tiles requested; loaded 0.5 s later; merged
over 0.9 s; a whole-world sync (1.45 s busy over 10.4 s). Meanwhile the
lookahead tile's separate fetch merged, so a second whole-world sync followed
(1.75 s busy over 9.5 s), with three chunk rebuilds alongside (0.2–0.8 s each).
That is about 22 s from crossing into the tile to settled, for about 5 s of CPU.

- **Two syncs per step.** The 3 × 3 core window's missing tiles and the
  lookahead tile are separate requests, merged separately. Each merge bumps the
  map revision and gets its own whole-world sync.
- **Whole-world syncs.** Each costs 1.2–2.4 s of CPU, spread over 7–12 s at
  the 4 ms budget. The largest parts are the pedestrian network (0.5–1.8 s),
  house parking (0.14–0.5 s, because it re-processes every loaded building on
  each sync), the traffic route graph (0.1–0.4 s) and railways (44–218 ms).
- **The world only grows.** Tiles unload only above 768 MB RSS
  (`DEFAULT_TILE_MEMORY_BUDGET_MB`). A 3.6 km drive took the road count from
  10.6 k to 13.8 k, and every later sync is that much slower.
- **Dirty areas.** One large merged object (landuse, a river) can stretch the
  rebuilt area over the whole map (27 × 25 km after the first sync), and 15–98
  chunks change per full rebuild pass.

## What the Godot client adds

- **Resends.** 10–13 chunks per tile step (41–52 of 90–101 chunk messages per
  run). In a diff of 278 changed chunks, all but 5 changes were pure additions,
  from two sources:
  - Godot's 7 × 7 window of 500 m chunks (`LOAD_RADIUS` 3) reaches 1.5–2 km
    from the player; the server's 3 × 3 window of 1 km tiles reaches 1–2 km.
    Chunks beyond the merged tiles are sent with whatever reached into them,
    then resent once their tile merges (one went from 294 to 445 roads, another
    from 59 to 654 parking spaces).
  - Large objects from a new tile reach into finished chunks. Landuse changed
    in 235 of the 278 and was the only change in 38; rivers or long roads alone
    in another 25.
- **Each resend is a full chunk rebuild on the main thread.** The 4 ms budget
  in `_process_chunk_queues` (main.gd) times only creating the chunk's nodes.
  Their first draw (10–20 ms per chunk, per the comment beside it) runs later in
  the same frame.
- **Buildings blink.** `_free_chunk` frees the old chunk's 3D building meshes
  at once. The new ones are built on a worker and added in `_meshes_ready`,
  which also loops over every lit-window vertex in GDScript on the main thread.
- **Frame hitches look like late states.** A state is stamped when a frame
  drains it, and the clock offset follows late samples at 50 % but early ones at
  5 %, so each hitch adds a short slow-motion wobble.

## Checked and ruled out

- The tile merge (`integrate_completed_tiles`) stays within its 4 ms budget.
  It appeared among the worst ticks only when a GC fired inside it.
- Transport: state latency from tick end to the client is p50 0.7–0.9 ms and
  p99 11–20 ms. Its spikes coincide with collections, when the sender threads
  can't run either. A burst of 7 chunks (0.1–0.4 MB) passes in under 10 ms on
  loopback.
- House parking's key set (`_existing_house_parking_keys`) takes 0.05 ms per
  call.
- Chunk size is 52–55 KiB on average, up to 188–380 KiB. Encoding takes
  1.8–2 ms on average, 10–19 ms at most.

## Fixes and results

Measured with the tool on the warm route, two runs per row; each row adds a
change to the ones above. Until the taxi road index, a row's worst tick depends
on when phone offers happened to be generated during the drive.

| Change | Full GCs | Worst tick | Ticks >100 ms | Chunk msgs / resends | State gaps >100 ms | Picture frozen | Snaps | Wrong speed |
|---|---|---|---|---|---|---|---|---|
| Baseline (`df4bcbb`) | 10–14 | 505–536 ms | 12 | 90–101 / 41–52 | 19–28 | 24–31×, 4.6–7.7 s | 10–13 | 5.5–7.1 % |
| + GC tuning restored (`7b41253`) | 0 | 119–303 ms | 1–2 | 86–97 / 37–41 | 3 | 3–4×, 0.1–0.4 s | 0–1 | 2.5–3.4 % |
| + chunks wait for their tile (`457de5d`) | 0 | 115–292 ms | 1–4 | 55–56 / 7–8 | 4–6 | 4–16×, 0.1–1.4 s | 0–1 | 3.2–5.4 % |
| + taxi range pre-filter (`38afda5`) | 0 | 141–150 ms | 1 | 44–55 / 6–7 | 2–3 | 4–6×, 0.2–0.3 s | 0 | 3.2 % |
| + encoding off the tick, railways in slices (`6890523`, `2664780`) | 0 | 69–77 ms | 0 | 46 / 6 | 0–1 | 0–2×, ≤0.1 s | 0 | 1.6–3.4 % |
| + taxi road index (`f93bac3`) | 0 | 52–57 ms | 0 | 44–55 / 6–7 | 0 | 0 | 0 | 0.6–0.9 % |
| + no fetch cooldown for the local extract (`93fd53b`) | 0 | 58–67 ms | 0 | 43–54 / 5–6 | 0 | 0 | 0 | 1.1–1.4 % |
| + sync settle (`dd996a1`), final | 0 | 65–80 ms | 0 | 45–54 / 5–6 | 0 | 0–1×, <0.05 s | 0 | 0.8–1.0 % |

What each change does:

1. **GC tuning restored** (`7b41253`). `performance.tune_interpreter()` sets the
   thresholds and switch interval; `server/__main__.py` calls it before the
   world loads, and both benchmarks do the same (`896dbc7`). Full collections
   per drive: 10–14 → 0. Young-generation passes are bigger instead: up to
   25–33 ms, 20–39 of them over 10 ms per drive. The cyclic garbage left at the
   end of a drive was 9–95 objects, so nothing piles up.
2. **A chunk waits for its tile** (`457de5d`). Beyond the player's own 3 × 3, a
   chunk is sent once the chunk index has been rebuilt with its tile (the tiles
   loaded when that sync started); the player's own 3 × 3 still goes at once,
   so a Home jump's destination is drawn as it arrives. Resends 37–41 → 7–8.
3. **Buildings don't blink on a resend** (`eda9c84`, Godot). The replaced
   chunk's building meshes stay until the new chunk's are built. Unit-tested; a
   headless client can't show the blink itself.
4. **Taxi offers** (`38afda5`, `f93bac3`). A building that can't meet the
   distance limits is skipped before any road scan, and the nearest-road searches
   use a `SpatialWayGrid` of the taxi roads, with the same results as the full
   scan (tested against it). `generate_offers` on Oulu: median 30 → 6 ms, worst
   136 → 16 ms.
5. **Work out of the tick** (`6890523`, `2664780`). The railway timetable is
   matched 20 trains per sync slice (on Oulu the same 69 passes, in 22 slices of
   at most 3.4 ms). The rebuild thread encodes the chunks the next ticks will
   send, and `ChunkIndex.updated` keeps the bytes of rebuilt chunks that didn't
   change: chunk encoding inside slow ticks went from 64–102 ms per drive to
   1–2 ms. The same commit closes a race in which the final rebuild pass read a
   byte cache the tick could be writing into; that would have killed the rebuild
   thread with merges on hold, so the map would have stopped growing.
6. **One whole-world sync per tile step** (`29c6c5d`, `93fd53b`, `dd996a1`). A
   settled merge waits 1 s, and longer while a fetch is in flight (at most 3 s;
   never while the map under the player is missing). On its own this changed
   nothing (`29c6c5d`): the 5 s fetch cooldown, there to spare public Overpass
   servers, kept the lookahead tile's fetch from starting until the core
   window's sync had begun. The local extract now has no cooldown (`93fd53b`).
   Syncs per drive 10–11 → 6, and the map is busy 28–32 % of the drive instead
   of 38–44 %. The 1 s settle (`dd996a1`) is for a lookahead tile that enters the
   window just after the merge, seen once; in the final runs the count stayed 6.
7. **NPC destination search** (`1f8292a`, after the measured rounds). A parking
   lot's polygon is tested only when its bounding box holds the point; the scan
   over every lot gave 30–90 ms ticks.

`58fd0e4` fixes a flaky test the work ran into: the client/server integration
test read the socket for a fixed 50 ms and sometimes got 18 of the 49 chunks.

**Cold cache.** Before (east and north, first visit): 36–49 freezes
(7.2–9.1 s), 14–16 snaps, worst tick 583–598 ms. After (south and southeast,
first visit, 7–8 tiles extracted): 12–15 freezes (1.8–2.1 s), no snaps, worst
tick 96–226 ms, worst state gap 249–259 ms. What is left is the tile loader
(see Remaining).

**Home jump** (`tools/bench_home_relocation.py`, at `dd996a1`). A 12 km jump to a
cached destination: the chunk under the player is ready after 0.96 s
(map-loading-01 measured 1.1–1.5 s) and the map has settled after 5.2 s.

**Godot client.** Headless at 60 fps, attached to the same drive, two runs each.
With it attached the server sent the test client more chunk messages, varying
between runs for a reason not found (160–162 at the baseline, 43–110 after);
resends were 41–43 and 5–6.

| Godot, 180 s drive | Baseline | After |
|---|---|---|
| Chunk adds on the main thread | 202–208, 934–953 ms in total | 78–112, 547–730 ms |
| Average / worst add | 4.6 / 21.5–28.6 ms | 6.5–7.0 / 23–26 ms |
| Building meshes built on workers | 165–171, 2.9–3.0 s | 78–112, 1.8–2.5 s |
| Frames over 33 ms | 9–11 | 12–18 |
| Worst frame | 68–69 ms | 50–90 ms |
| Picture frozen (state replay) | 21–25×, 5.7–6.6 s; 11–13 snaps | 0 |

The client does 22–43 % less chunk work on its main thread, but its worst
frames didn't improve: chunks now arrive once and complete, so the average add
is heavier, and a dense chunk is one long frame either way. On the five densest
Oulu chunks (255–378 KiB), `setup()` takes 15–21 ms on the main thread, of
which drivable-road boxes 3–5 ms, puddle spots ~2 ms and point conversion with
clipping 6–11 ms; the first draw adds 6–13 ms in the same frame (headless,
outside the 4 ms chunk budget).

Tests: pytest 1363 → 1371 passed (2 skipped throughout), Godot 649 → 653
checks; every change but the cooldown (`93fd53b`, a constructor argument) has a
test beside it.

## Remaining

- **Client chunk cost.** The 11–19 ms of data work in a dense chunk's `setup()`
  can run on the worker that already parses the chunk; the first draw stays.
- **Cold tile loads.** The loader thread still holds the GIL for up to ~0.2 s
  at a time. An RWC miss falls back to a covering OSM-cache file, which here was
  the 115 k-element start region, parsed and rebuilt whole for a one-tile
  request; young collections reach 70–83 ms while it builds. Building tiles in a
  worker process (and reading only the requested area from a covering cache)
  would take this off the tick.
- **Young collections** of up to 25–33 ms, the price of the thresholds.
- **GIL sharing.** Ticks still wait 5–10 ms longer while the chunk rebuild or a
  tile load runs.
- **Whole-world syncs.** One per tile step now, still 0.7–1.5 s of CPU each
  (the pedestrian network most), and growing with the map: tiles unload only
  above 768 MB RSS.
- **Clock coupling.** States are stamped when a Godot frame drains them, and
  server time never catches up after a stall. Both matter little while stalls
  stay short.
- **Other gameplay spikes** in the stack samples: pedestrian spawning and
  routing, and resident creation, 20–50 ms of CPU now and then.

## Reproduce

```bash
# Warm cache: the route east of the Oulu start (cached after a first run).
PYTHONPATH=src .venv/bin/python tools/bench_map_jitter.py --preset Oulu --osm-source pbf --drive-s 180 --json out.json
# Cold: a direction whose tiles aren't cached yet (--heading 1.5708 is north), or remove
# the route's files from ~/.cache/RoadRageTrip/world and osm_cache first.
# --sample-ms 45 records the stack of every tick that runs longer than 45 ms.

# Godot attached to the same drive: start it first, it retries until the server is up.
godot --headless --max-fps 60 --path godot -- --skip-menu --port 8799 --bench 180 &
PYTHONPATH=src .venv/bin/python tools/bench_map_jitter.py --preset Oulu --osm-source pbf --port 8799 --json out.json

# Home jump (map-loading-01's benchmark)
PYTHONPATH=src .venv/bin/python tools/bench_home_relocation.py --preset Oulu --osm-source pbf --dest 428491 7198561
```
