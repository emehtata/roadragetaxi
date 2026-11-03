# Cache decoding and chunk snapshot measurements, 2026-11-03

Follow-through from the [rubberbanding profile](rrt-021-rubberband-profile.md).
Baseline is `6ca8a0b9`. This change reduces binary-cache decoding overhead and
adds phase timings to cache and chunk snapshot logs. Tile dimensions, cache
format, traffic behavior and per-tick budgets are unchanged.

## Finding and change

A cProfile load of a current-format 33,385,203-byte Helsinki cache recorded
3,009,044 `_decode` calls, 5.32 seconds inclusive out of 6.01 seconds for the
loader. Profiling adds substantial overhead; these are attribution figures.
Most work is recursive parsing, rather than dataclass restoration.

The loader already stores section payloads as bytes. It now decodes those bytes
directly instead of creating memoryviews and converting each string slice back
to bytes. Literal wire tags also avoid repeated type-table dictionary lookups in
the recursive hot path. All existing bounds, checksums and type checks remain.
No cache rebuild or new dependency is needed.

Cache logs now separate reading/validation, value decoding and object restoration.
Chunk snapshot logs separate object selection and pickling, and include thread
CPU time, object count, number of pieces and byte count.

## Isolated comparison

[Raw results](rrt-021-cache-decode-data/isolated.json). Both loaders read the same
warm file with the same interpreter tuning. All collection sections and bounds
compare equal across the two restored worlds (50,263 top-level map objects).
After warming both loaders, four alternating baseline/current pairs run
sequentially, with `gc.collect()` before each timed load. Load timings include
cleanup of decoder intermediates; internal phase logs end before that cleanup.
The connected drive and correctness checks had finished before this comparison.

| Whole load | Baseline | Current |
| --- | ---: | ---: |
| Median wall time | 2,191 ms | 1,843 ms |
| Minimum / maximum | 2,120 / 2,339 ms | 1,805 / 2,049 ms |

Median load time fell 15.9% for this file. This is a cache-loader result, not a
whole-game latency improvement. Current measured phase logs put decoding around
1.45–1.62 seconds in the four timed loads; restoration around 0.26–0.34 seconds.
The decoder remains Python code and still competes for the GIL.

A snapshot of a 1 km square at this cached map's bounds centre took 47.6–52.5 ms:
17.9–23.5 ms selecting objects and 28.8–29.8 ms pickling 14,460 selected objects
into 44 pieces totaling 3.89 MB. This probe uses cached lists and mapped lamps;
it omits generated lamps, roadworks and speed cameras, and is not a live growth
measurement. It makes the decoder the larger target in this sampled workload;
it does not rule out snapshot spikes on larger worlds.

To repeat the isolated comparison, extract the baseline module with
`git show 6ca8a0b9:src/theroadragetrip/world_cache.py` and import it under another
`theroadragetrip` module name using `importlib.util.spec_from_file_location`.
Call `tune_interpreter()`, warm both `BinaryWorldCacheLoader` implementations,
and alternate their `load(path)` calls four times after `gc.collect()`, timing
with `perf_counter()` and `thread_time()`. Use the exact cache named in the raw
results and compare every `_SECTIONS[:-1]` collection plus `bounds` before timing.
The cache is local map data, not a checked-in fixture; another cache is a new
workload. Snapshot coordinates and its omitted inputs are recorded in the JSON.

## Connected drive and limits

`.venv/bin/python tools/bench_map_jitter.py --preset Oulu --drive-s 90 --json /tmp/rrt-cache-connected-after.json`

The configured source was Overpass, with warm cache loads. Map work was active
65.3% of 2,652 ticks. Tick p95/p99/max was 36.2/49.4/87.9 ms; 23 ticks exceeded
50 ms and none exceeded 100 ms. State gaps had p99/max 55.6/103 ms, with one over
100 ms. Replay recorded zero freezes and clock snaps, but 12.8% wrong-speed
frames. There were no generation-2 collections; generation 1 still reached
33 ms. [Raw capture](rrt-021-cache-decode-data/connected.json) and
[cache phase logs](rrt-021-cache-decode-data/cache-phases.txt) are retained.

This is a functional drive, not a paired before/after comparison. Short
correctness checks overlapped its startup/early drive. No overall reduction in
rubberbanding is established. The snapshot logger was added after this drive
started, so its measurements above come from the isolated probe.

27 cache/chunk-worker tests passed, including cache corruption/version handling,
process-build round trips, signal-group and place sharing, chunk equivalence,
nested value types/offsets and rejection of every truncation of a nested value.
Compile and whitespace checks passed.

## Next work

Decoding remains the largest measured map-loader CPU cost. A native prototype
should preserve this format, release the GIL while parsing, and restore Python
objects in bounded batches. Passing one whole world back from another process
still risks the previously measured long unpickle pause. Keep the 1 km streaming
tiles until an identical-cache, identical-route tile-size comparison supports a
change. GC pauses and gameplay CPU work still need independent treatment.
