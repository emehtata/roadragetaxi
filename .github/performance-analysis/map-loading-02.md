# Map loading 02 — stalls and UI jitter while the map grows

Follow-up to [map-loading-01](map-loading-01.md). Branch `release/0.17.0alpha`;
baseline code `df4bcbb`. Measured with `tools/bench_map_jitter.py` (added for
this report) unless noted.

## Summary

While the taxi drives into new map, the Godot client's picture freezes for
0.1–0.6 s at a time, then jumps or runs in slow motion for a moment. On the
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
drops a frame. The client section below is from the code and the costs recorded
in earlier reports.

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

## Fix plan

In this order, each measured with the tool before the next:

1. Restore the GC thresholds and switch interval in the server process.
2. Send a chunk only once its tile is in the chunk index, so it isn't sent
   half-built and then resent.
3. Godot: keep the old chunk's building meshes until the replacement's are
   ready.
4. `passenger_waiting_position` once per offer.
5. Encode resent chunks on the rebuild thread instead of in the tick.
6. `trains.rebuild` in budgeted steps.
7. One whole-world sync per tile step.

Left for later, because they are larger: tile loading and chunk rebuilds out of
the server's GIL (a worker process), an incremental pedestrian sync, indexed
taxi scans, and a server/client clock that survives a stall.

## Results

Added as the fixes land.

## Reproduce

```bash
# Warm cache: the route east of the Oulu start (cached after a first run).
PYTHONPATH=src .venv/bin/python tools/bench_map_jitter.py --preset Oulu --osm-source pbf --drive-s 180 --json out.json
# Cold: a direction whose tiles aren't cached yet (--heading 1.5708 is north), or remove
# the route's files from ~/.cache/RoadRageTrip/world and osm_cache first.
# --sample-ms 45 records the stack of every tick that runs longer than 45 ms.
```
