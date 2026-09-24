# bin-loader-v10: diagnose and reduce global Python GC pauses

## Objective

Continue the Road Rage Taxi performance optimization on the current branch.

V9 successfully optimized pedestrian synchronization and discovered that the largest remaining frame-time spikes are **Python generation-2 garbage-collection pauses**, not pedestrian computation.

The current evidence:

```text
Generation-2 GC pauses:
~250–350 ms
~1.1–1.35 million tracked objects
~5–6 major collections per benchmark run
```

These pauses appear inside different subsystems depending on which code happens to allocate immediately before the collection:

```text
pedestrian sync
tile integration
rendering
other update stages
```

Therefore the next goal is:

> Measure the application's allocation/GC behavior and determine whether GC policy, object lifetime, allocation patterns, or a combination of these is responsible for the large pauses.

Do NOT blindly enable `gc.freeze()`.

Do NOT blindly disable GC.

Do NOT change object allocation architecture before profiling proves it is necessary.

The first phase must establish a safe baseline and compare GC strategies experimentally.

---

# 1. Read the V9 report first

Review:

```text
bin-loader-v9.md
```

Pay particular attention to:

* GC attribution
* generation-2 collection counts
* object counts
* pedestrian allocation behavior
* tile integration behavior
* rendering behavior
* memory observations
* the recommendation for V10

Verify the actual implementation before changing anything.

---

# 2. Inspect the current GC behavior

Find all existing uses of:

```python
import gc
gc.collect()
gc.disable()
gc.enable()
gc.freeze()
gc.set_threshold()
gc.get_threshold()
gc.get_stats()
gc.get_count()
```

Also inspect any benchmark instrumentation related to GC.

Determine:

1. Current GC thresholds.
2. Whether GC is enabled throughout gameplay.
3. Which generations are being collected.
4. How often generation-2 collections occur.
5. How many tracked objects exist immediately before/after a full collection.
6. Whether collection frequency changes after:

   * world load
   * tile loading
   * tile merge
   * pedestrian synchronization
   * traffic updates
   * rendering
7. Whether explicit `gc.collect()` calls already exist.

Do not modify behavior yet.

---

# 3. Establish a clean GC baseline

Run the exact benchmark used by V9:

```bash
TZ=UTC-15 PYTHONPATH=src:. .venv/bin/python -c 'import utils.benchmark_full_frame as b; b.run_scenario("Driving V10 GC baseline", "oulu", frames=3000, drive=True, spike_threshold_ms=100.0)'
```

Use:

```text
--preset oulu
--no-menu
--osm-source pbf
warm WorldCache
real tile streaming
real rendering
night-time start via TZ=UTC-15
```

Run at least twice.

Record:

```text
average
p95
p99
worst
frames >=100
frames >=200
frames >=400

GC total time
generation-0 collections
generation-1 collections
generation-2 collections
max individual GC pause
tracked-object count
RSS / process memory if available
```

Do not compare only total GC time.

The critical metric is the longest individual pause.

---

# 4. Improve GC attribution

The V9 report fixed an off-by-one bug in the benchmark's GC frame attribution.

Preserve that fix.

Verify that the benchmark now reports GC against the frame in which the collection actually ran.

If useful, add lightweight instrumentation around:

```text
generation
collection duration
tracked object count before
tracked object count after
```

For example:

```text
gc:gen0
gc:gen1
gc:gen2
```

Do not run expensive object enumeration every frame.

If object counts are sampled, sample only around actual GC events.

---

# 5. Identify what survives into generation 2

The important question is not simply:

> "Why does Python GC take 300 ms?"

It is:

> "Why does generation 2 contain ~1.1–1.35 million tracked objects?"

Investigate what major object populations exist.

Look for long-lived Python objects associated with:

* OSM ways
* nodes
* buildings
* scenery
* pedestrian objects
* route graphs
* junction grids
* tile caches
* rendering caches
* traffic objects
* spatial grids
* temporary map structures that accidentally remain referenced

Do not perform a full `gc.get_objects()` scan every frame.

Use targeted diagnostics around benchmark phases.

---

# 6. Determine whether the large object population is intentional

Separate objects into:

```text
long-lived world state
temporary objects
obsolete map revisions
obsolete cache structures
short-lived per-frame objects
```

The goal is not necessarily to reduce the total object count.

For example, a large static OSM world representation may legitimately contain many long-lived objects.

Instead determine whether objects that should be dead remain tracked because of Python reference cycles.

Pay particular attention to:

```text
reference cycles
self-referencing structures
mutually referencing grid objects
callbacks
closures
bound methods
objects containing parent references
cached temporary structures
```

Do not introduce speculative weak references.

Measure first.

---

# 7. Investigate whether reference counting already handles most cleanup

Python objects without reference cycles are normally reclaimed immediately when their reference count reaches zero.

Generation-2 GC is primarily important for cyclic garbage.

Determine whether the expensive collection is actually finding many cyclic objects.

Use appropriate diagnostics around controlled test cases.

The key questions are:

```text
How many objects are collected?
How many are unreachable?
How many are cyclic?
How many are merely tracked?
```

Do not equate:

```text
tracked objects
```

with:

```text
garbage
```

---

# 8. Test GC strategies independently

Create a controlled benchmark matrix.

At minimum compare:

### Strategy A — current behavior

```text
existing GC configuration
```

### Strategy B — tuned thresholds

Experiment with carefully chosen `gc.set_threshold()` values.

Do not guess a single "magic" value.

Test a small set of reasonable configurations.

Measure:

```text
collection frequency
individual pause duration
total GC time
frame-time spikes
RSS
tracked objects
```

### Strategy C — explicit collection at a safe point

Test whether generation-2 collections can be moved away from latency-sensitive frames.

For example, investigate controlled collection after a large map-sync operation or another safe point.

Do not assume this is beneficial.

Measure it.

### Strategy D — freeze experiment

Test `gc.freeze()` only in a controlled experiment.

Do not commit it as the default merely because it improves the benchmark.

Test:

```text
baseline
freeze after static world initialization
freeze after world/map caches stabilize
freeze after map-sync commit
```

Only test states that are technically safe according to Python's GC semantics and the game's object lifetime.

---

# 9. Critical requirement for gc.freeze()

If experimenting with:

```python
gc.freeze()
```

first establish exactly what is being frozen.

Do NOT freeze objects that will later be mutated or whose lifetime is expected to end.

In particular investigate:

* tile data that can be unloaded
* map caches
* dynamically replaced spatial grids
* pedestrian state
* traffic state
* temporary rendering objects
* objects participating in future map revisions

The experiment must verify that unloading still releases memory.

Measure:

```text
RSS before freeze
RSS after freeze
RSS after tile load
RSS after tile unload
RSS after repeated tile cycles
```

A lower GC pause with unbounded memory growth is not an acceptable optimization.

---

# 10. Test memory behavior

GC optimization must include memory measurements.

Run controlled sequences such as:

```text
world load
→ several tile merges
→ tile unload
→ more tile loads
→ repeated map revisions
```

Measure:

```text
RSS
Python allocated m
```
