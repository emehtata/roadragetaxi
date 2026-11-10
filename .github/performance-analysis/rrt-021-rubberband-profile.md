# Rubberbanding profile, 2026-11-03

This adds phase detail to the connected-client map-growth harness. The 90-second Oulu drive used the real server and a socket client, with 2,657 measured ticks; map work was active for 66.9% of ticks. The harness now records simulation sections, existing pedestrian subphases, selected NPC subphases, population counts, and garbage collections overlapping the drive. The raw capture is rrt-021-rubberband-profile.json.

This was a diagnostic run, not a controlled before/after comparison. Instrumentation and naturally changing traffic can affect timings.

## Findings

- The tile merge itself totaled 34 ms across slow ticks; map chunk swap/resend totaled 38 ms. Budgeted map sync totaled 683 ms across those ticks. These are not the large per-tick CPU costs.
- Busy-map tick p95/p99/maximum were 38.2/50.5/93.3 ms. There were 18 ticks over 50 ms and none over 100 ms. The client saw one 109 ms state gap, no frozen frames and no clock snaps.
- Slow ticks spent 4.25 s in simulation and 0.99 s constructing state. Inside simulation, pedestrian updates used 1.46 s and NPC updates 2.07 s across the slow ticks. Pedestrian movement was the largest measured subphase (883 ms); its spawn phase used 293 ms. NPC route jobs used 296 ms and population work 151 ms.
- State helpers were usually small. A 41 ms `_traffic_light_phases` measurement coincided with a 41 ms generation-1 collection on the main thread, so it does not identify that helper as the cause.
- There were no generation-2 collections during the measured interval. Generation 1 ran 44 times and took 725 ms total, with a 49 ms maximum. Collections also ran on `map-growth` and `world-cache` threads, and can pause the tick while they hold the GIL.
- While `_background_tile_fetch` was active, the tick's wall-minus-thread-CPU wait averaged 15.9 ms and had a 25.8 ms p95. Cache logs show individual binary world-cache loads taking 0.4–2.9 s on `world-cache` threads. This is the clearest map-specific source of GIL contention in this capture. Chunk rebuilds run in a worker process by default, though parent-side snapshot preparation remains Python work.

A 20.3 MB cached tile decoded into 19,510 map objects in 1.30 s in a local probe. Pickling the resulting world took 82 ms; unpickling took 221 ms. Returning the whole decoded world from a process would therefore risk replacing distributed GIL contention with a single long unpickle pause.

## Recommendation

Do not port the simulation, tile merge, or state builder wholesale to Rust/C. The merge is already cheap, and measured CPU work is spread across NPC movement, pedestrian movement/spawning, and route jobs. Those gameplay paths need separate fixed-scenario profiling before any rewrite.

For map-specific rubberbanding, the next candidate is the binary cache decoder and the parent-side chunk snapshot preparation. Measure their thread CPU and allocation costs separately. A native decoder is worth a small prototype only if it releases the GIL during parsing and preserves bounded batches when Python objects are restored. A single large result handed back to Python is not a safe shortcut, based on the unpickle measurement above.

No production optimization was made from this capture: it does not yet isolate cache decode from object restoration, nor quantify the parent snapshot's share of map-growth GIL time. The measurements do not establish a universal speedup or eliminate rubberbanding.
