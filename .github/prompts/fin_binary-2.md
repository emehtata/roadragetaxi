## Goal

Implement a standalone runtime benchmark for the existing `finland_roads.bin` V2 binary format.

The purpose of this task is to determine whether the current V2 binary format is suitable for runtime use in Road Rage Taxi before integrating it into the actual game, NPC routing, or simulation.

**Do not modify the game runtime or NPC systems in this task.**

The benchmark must use the **existing V2 binary format and existing V2 reader/loader implementation**. Do not redesign the binary format as part of this task.

---

# 1. Inspect the existing implementation first

Before writing code:

1. Locate the existing V1 and V2 binary format implementations.
2. Locate the V2 writer/generator.
3. Locate the V2 reader/loader, if one already exists.
4. Determine the exact V2 file structure.
5. Determine which fields are decoded into Python objects/structures.
6. Determine whether the current reader loads the entire dataset into memory.
7. Identify any existing utilities for binary validation or statistics.

Do not assume field names, offsets, structures, paths, or APIs.

Use the actual implementation in the repository.

If a V2 reader does not currently exist, implement the smallest possible reader required for this benchmark based on the actual V2 format definition.

---

# 2. Create a standalone benchmark

Add a standalone benchmark tool/script for loading:

    finland_roads.bin

The benchmark must:

1. Open the V2 binary.
2. Load/decode it using the same logic intended for runtime use.
3. Verify the expected dataset counts.
4. Measure loading performance.
5. Measure process memory usage.
6. Perform representative lookup tests.
7. Print a clear benchmark report.
8. Exit without starting Pygame or the actual game.

The benchmark must be runnable independently from the game.

For example, use an appropriate existing project structure such as:

    tools/
    scripts/
    benchmarks/

Do not invent a new architectural subsystem if an appropriate existing location already exists.

---

# 3. Measure file loading time

Measure at least:

- file open time
- binary parsing/decode time
- total load time

Use a monotonic high-resolution timer.

Report times in milliseconds and seconds.

Example output:

    === Finland Roads V2 Runtime Benchmark ===

    File:
      finland_roads.bin

    File size:
      129.54 MiB

    Load:
      Open:        12.4 ms
      Parse:      842.7 ms
      Total:      855.1 ms

Do not hard-code these example values.

---

# 4. Measure process memory

Measure memory usage before and after loading the dataset.

At minimum report:

- baseline RSS
- RSS after loading
- additional RSS caused by loading
- peak RSS if practical

Prefer the most appropriate cross-platform mechanism already used by the project.

The benchmark must work on the development environment used by Road Rage Taxi.

If Windows and Linux require different implementations, provide a small platform abstraction rather than disabling the measurement.

Example:

    Memory:
      Baseline RSS:      184 MiB
      Loaded RSS:      1,024 MiB
      Increase:          840 MiB
      Peak RSS:        1,031 MiB

The important metric is:

    memory increase caused by loading the road network

Do not confuse Python's allocator statistics with actual process RSS.

---

# 5. Validate the loaded dataset

After loading, report and verify:

- way count
- node count
- geometry point count
- total road length
- all major V2 metadata counts available from the format

The benchmark should verify that the loaded dataset still matches the known V2 source data:

    Ways:
      1,038,925

    Nodes:
      10,325,748

    Geometry points:
      11,548,814

    Road length:
      334,848.8 km

Do not hard-code validation logic into the loader itself.

The benchmark may use these expected values as regression-test expectations.

If the existing V2 validation mechanism already provides authoritative values, reuse it instead of duplicating calculations.

If the actual repository contains different authoritative values, use those instead.

---

# 6. Benchmark representative access patterns

The benchmark must not only test loading.

We need to understand whether the loaded representation is practical for runtime use.

Add representative read/lookup benchmarks based on the actual V2 data structures.

At minimum test:

## A. Random way access

Select a deterministic set of random way indices.

For example:

    1,000 ways
    10,000 ways

Measure:

- lookup time
- total time
- average lookup time

Use a fixed random seed so results are reproducible.

Do not generate a different random workload on every run.

---

## B. Random node access

Perform the same type of benchmark for nodes.

Measure:

- lookup time
- average lookup time

Again use deterministic indices.

---

## C. Geometry access

Benchmark accessing geometry for a representative set of ways.

For example:

- 1,000 random ways
- 10,000 random ways

Measure the total number of geometry points touched and elapsed time.

The purpose is to determine whether the V2 representation makes geometry access expensive.

---

# 7. Nearest-road benchmark

If the current V2 representation contains enough information to perform a meaningful nearest-road lookup, implement a benchmark for it.

However:

**Do not build a sophisticated spatial index as part of this task.**

We only want to establish a baseline.

Use deterministic test coordinates.

For example:

- locations near Oulu
- locations elsewhere in Finland
- locations near major roads
- locations in rural areas

The exact coordinates should be selected from the existing data or existing project test data rather than invented blindly.

If an efficient nearest-road query is not currently possible with V2, report:

    Nearest-road lookup:
      NOT IMPLEMENTED IN CURRENT V2 REPRESENTATION

Do not redesign the format just to make this test possible.

---

# 8. Optional mmap experiment

If the V2 binary format is naturally suitable for memory mapping, add an OPTIONAL benchmark mode for mmap.

Do not redesign the file format for this.

The experiment should answer:

    Can V2 be accessed using mmap with little or no full-file copying?

Compare:

    Normal load
    mmap load

Measure:

- startup/load time
- RSS
- representative access time

Do not claim that mmap reduces RSS unless the measurements actually demonstrate it.

If mmap is not practical because the current format requires substantial decoding, document why and skip the experiment.

---

# 9. Cold-cache vs warm-cache

If practical, document whether the benchmark is being run against:

- OS filesystem cache
- cold filesystem cache

Do not attempt dangerous or privileged cache flushing.

At minimum make clear in the output that filesystem caching can affect the timing.

If useful, run the load twice:

    Run 1: cold-ish filesystem state
    Run 2: warm filesystem cache

Label the results correctly.

---

# 10. Do not integrate with the game yet

This task must NOT:

- change Pygame initialization
- change the game startup path
- change NPC routing
- change traffic simulation
- change Resident simulation
- remove Overpass
- remove the existing tile streaming
- replace existing map rendering
- change OSM tile behavior
- change gameplay

The benchmark is an isolated investigation.

---

# 11. Produce a machine-readable result

In addition to human-readable console output, produce an optional JSON result file.

For example:

    v2_runtime_benchmark.json

Include:

    {
      "file_size_bytes": ...,
      "ways": ...,
      "nodes": ...,
      "geometry_points": ...,
      "road_length_km": ...,
      "load_time_ms": ...,
      "parse_time_ms": ...,
      "baseline_rss_bytes": ...,
      "loaded_rss_bytes": ...,
      "rss_increase_bytes": ...,
      "peak_rss_bytes": ...,
      "random_way_lookup_ms": ...,
      "random_node_lookup_ms": ...,
      "geometry_access_ms": ...
    }

Use the actual measured values.

Do not fabricate metrics.

---

# 12. Add regression tests

Add automated tests for the benchmark/loader where appropriate.

At minimum verify:

- V2 file can be opened.
- Header/version is correct.
- Expected way count is correct.
- Expected node count is correct.
- Expected geometry count is correct.
- Road length matches the authoritative V2 value within the existing validation tolerance.
- Representative way records can be decoded.
- Representative node records can be decoded.
- Representative geometry can be decoded.

Tests must use the existing V2 format rather than introducing a fake replacement format.

If the real 129 MiB `finland_roads.bin` cannot reasonably be committed to the repository, create a small deterministic V2 fixture using the existing V2 writer.

The fixture must exercise the actual V2 encoding/decoding path.

---

# 13. Performance interpretation

At the end of the benchmark output, provide a short interpretation.

For example:

    === Interpretation ===

    Binary size:
      129.54 MiB

    Runtime memory expansion:
      X MiB

    Expansion ratio:
      X.X×

    Total load time:
      X.XXX s

    Assessment:
      [data-driven result]

Do not hard-code an arbitrary "good" or "bad" threshold unless the repository already defines one.

The benchmark should primarily provide measurements that we can use to make the architectural decision later.

---

# 14. Important: preserve the V2 format

Do NOT optimize V2 further in this task.

Do NOT:

- remove fields
- remove roads
- remove geometry
- reduce node precision
- remove metadata
- merge ways
- simplify geometry
- drop road types
- alter OSM identity
- change coordinate representation
- redesign the binary layout

The previous V2 optimization has already been validated:

    File size:        129.54 MiB
    Ways:           1,038,925
    Nodes:         10,325,748
    Geometry:      11,548,814
    Road length:     334,848.8 km
    Validation: PASS

Treat this dataset as the reference implementation.

---

# 15. Final report

When implementation is complete, report:

1. Files added/modified.
2. Exact command used to run the benchmark.
3. Exact benchmark results.
4. Load time.
5. Memory increase.
6. Peak RSS.
7. Random access performance.
8. Geometry access performance.
9. Nearest-road result.
10. mmap result, if implemented.
11. Test results.
12. Any limitations discovered.

Most importantly, explicitly answer:

    How much RAM does the current Python representation of the
    129.54 MiB V2 road network require?

and:

    How long does it take to load?

These two numbers will determine whether we should proceed with integrating the V2 road network into the game runtime or redesign the runtime representation first.

Do not make further architectural changes until these measurements are available.
