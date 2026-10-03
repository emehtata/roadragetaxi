# Benchmark: Oulu 20×20 km V2 Road Dataset

## Objective

We currently have a validated Finland-wide V2 road binary:

- File size: 129.54 MiB
- Ways: 1,038,925
- Nodes: 10,325,748
- Geometry points: 11,548,814
- Road length: 334,848.757 km
- Validation: PASS

The current Python runtime representation requires approximately:

- 32.3 seconds to load
- +2.56 GiB RSS
- 2.71 GiB peak RSS
- 20.24× memory expansion relative to the binary

Before attempting to optimize the runtime representation further, we want to test a different architecture:

> Instead of shipping/loading the entire Finnish road network, generate a separate V2 binary for each supported city.

For this task, implement **only a benchmark for Oulu**.

Do NOT integrate this into the game yet.

Do NOT modify the existing V2 binary format.

Do NOT modify NPC routing, rendering, tile streaming, Overpass handling, or gameplay.

---

# 1. Inspect the existing implementation first

Before making changes, inspect the repository and identify:

1. The existing Finland PBF → V2 generator.
2. The existing V2 binary format.
3. The existing V2 reader/loader.
4. The existing runtime benchmark.
5. How geographic bounds are currently represented.
6. How OSM/PBF coordinates are represented.
7. Existing test utilities related to geographic filtering.

Use the actual repository implementation.

Do not invent paths, APIs, structures, or field names.

Reuse the existing V2 generator and loader wherever possible.

---

# 2. Define the Oulu benchmark area

Create a geographic test area covering **20 km × 20 km = 400 km²** around Oulu.

The benchmark must use a deterministic bounding box.

Prefer defining the area using geographic coordinates:

    min_lat
    max_lat
    min_lon
    max_lon

The bounding box should represent approximately 20 km × 20 km.

Because degrees of longitude have latitude-dependent physical size, do not simply assume that:

    0.2 degrees = 20 km

unless the existing project already uses such a convention.

Calculate/select the longitude and latitude bounds appropriately for Oulu's latitude.

The benchmark output must print the exact bounding box:

    Oulu benchmark area:
      min_lat: ...
      max_lat: ...
      min_lon: ...
      max_lon: ...

Also print the approximate physical dimensions:

    Width:  ~20.0 km
    Height: ~20.0 km
    Area:   ~400 km²

The exact area does not need to be mathematically perfect, but the benchmark must be deterministic and approximately 20×20 km.

---

# 3. Important: define how ways are included

The benchmark must explicitly document how the geographic clipping works.

We need to avoid accidentally producing an incomplete road graph.

Determine how the existing V2 generator handles ways that cross the bounding box.

For example, if a road:

    starts outside the 20×20 km area
    enters the area
    exits the area

the benchmark must document whether:

1. the entire way is included,
2. the geometry is clipped to the bounding box,
3. the way is included if any geometry point intersects the area.

Do not silently invent behavior.

For the first benchmark, prefer preserving the existing way/geometry semantics rather than modifying geometry.

However, the output must clearly state which behavior was used.

---

# 4. Generate an Oulu V2 binary

Using the existing Finland PBF:

    finland.osm.pbf

(or the actual PBF path used by the repository)

generate:

    oulu_20x20.bin

using the existing V2 format.

The generator must filter the source dataset geographically.

It must NOT change:

- V2 encoding
- coordinate precision
- road attributes
- highway types
- one-way information
- lanes
- maxspeed
- names
- refs
- junction information
- bridge/tunnel information
- surface
- OSM way identity
- geometry semantics

The only difference from the Finland-wide dataset should be:

> geographic selection of the Oulu benchmark area.

---

# 5. Report dataset statistics

After generating the Oulu dataset, report:

    File size
    PBF input size
    Ways
    Nodes
    Geometry points
    Road length
    Highway type distribution
    Processing time
    Peak Python memory
    Validation result

Example:

    === Oulu 20×20 km Dataset ===

    Input PBF:
      731.51 MiB

    Output:
      8.42 MiB

    Ways:
      ...

    Nodes:
      ...

    Geometry points:
      ...

    Road length:
      ... km

    Processing time:
      ... seconds

    Peak Python memory:
      ... MiB

    Validation:
      PASS

Do not fabricate expected values.

---

# 6. Compare against the full Finland dataset

Calculate:

    Oulu binary / Finland binary

for file size.

Also calculate:

    Oulu ways / Finland ways
    Oulu nodes / Finland nodes
    Oulu geometry / Finland geometry
    Oulu road length / Finland road length

Report the percentages.

Example:

    Oulu contains:

      4.2% of Finland's ways
      3.8% of Finland's nodes
      4.1% of Finland's geometry points
      2.7% of Finland's road length

These numbers are examples only. Use measured values.

---

# 7. Run the existing runtime loader benchmark

This is a critical part of the experiment.

Load:

    oulu_20x20.bin

using the same V2 runtime loader used in the previous benchmark.

Measure exactly the same metrics:

- file size
- load time
- baseline RSS
- loaded RSS
- additional RSS
- peak RSS
- memory expansion ratio
- way count
- node count
- geometry point count
- road length

Also run the same representative access benchmarks:

## Random way access

10,000 deterministic random way lookups.

## Random node access

10,000 deterministic random node lookups.

## Geometry access

10,000 deterministic way geometry accesses.

Use the same benchmark implementation and methodology as the Finland-wide benchmark whenever possible.

Do not create a second incompatible benchmark implementation.

---

# 8. Warm-cache benchmark

Perform a second load of:

    oulu_20x20.bin

after the first run.

Report:

    First load:
      ... seconds

    Warm-cache load:
      ... seconds

This allows us to determine whether loading the much smaller city dataset is still dominated by Python decoding/object creation.

---

# 9. Validate against the source data

The Oulu dataset must pass the same structural validation used by V2.

At minimum verify:

- all stored ways decode successfully
- all stored nodes decode successfully
- all geometry decodes successfully
- road length calculation succeeds
- no corrupted records
- no invalid offsets
- no invalid references
- V2 header/version is valid

If clipping/filtering changes the expected counts, do NOT compare them against the Finland-wide counts.

Instead validate the Oulu dataset internally.

---

# 10. Do not optimize anything yet

This is strictly an experiment.

Do NOT:

- introduce NumPy
- redesign Python runtime objects
- introduce mmap
- create a spatial index
- change V2
- add a new binary format
- optimize rendering
- optimize routing
- modify game startup
- modify NPC behavior
- remove Overpass
- remove tile streaming

We want a clean baseline first.

---

# 11. Produce a machine-readable benchmark result

Create a JSON result containing at least:

    {
      "area_name": "Oulu 20x20 km",
      "min_lat": ...,
      "max_lat": ...,
      "min_lon": ...,
      "max_lon": ...,

      "width_km": ...,
      "height_km": ...,
      "area_km2": ...,

      "file_size_bytes": ...,

      "ways": ...,
      "nodes": ...,
      "geometry_points": ...,
      "road_length_km": ...,

      "generation_time_ms": ...,
      "generation_peak_rss_bytes": ...,

      "load_time_ms": ...,
      "warm_load_time_ms": ...,

      "baseline_rss_bytes": ...,
      "loaded_rss_bytes": ...,
      "additional_rss_bytes": ...,
      "peak_rss_bytes": ...,

      "memory_expansion_ratio": ...,

      "random_way_lookup_ms": ...,
      "random_node_lookup_ms": ...,
      "geometry_access_ms": ...
    }

Use the actual measured values.

---

# 12. Final comparison

At the end print a comparison table like:

    ============================================================
    Finland vs Oulu 20×20 km
    ============================================================

    Metric                 Finland        Oulu
    ------------------------------------------------------------
    Binary size            129.54 MiB     ...
    Ways                   1,038,925      ...
    Nodes                  10,325,748     ...
    Geometry points        11,548,814     ...
    Road length            334,848.757 km ...
    Load time              32.266 s       ...
    Additional RSS         2.56 GiB       ...
    Peak RSS               2.71 GiB       ...
    ------------------------------------------------------------

Do not round away useful information.

---

# 13. Most important final analysis

The benchmark must explicitly answer these questions:

### A. How large is the Oulu 20×20 km binary?

This tells us the likely disk footprint of a city-based distribution model.

### B. How much RAM does it consume with the current Python loader?

This is the most important measurement.

### C. How long does it take to load?

Compare it directly with:

    Finland: 32.266 seconds

### D. Does Python object expansion remain approximately 20×?

Calculate:

    additional RSS / binary size

This is important because it tells us whether the memory problem scales roughly linearly with dataset size.

### E. Are random-access performance characteristics still good?

Compare:

    way lookup
    node lookup
    geometry access

with the Finland benchmark.

### F. Does this architecture appear viable for city-based maps?

Do not give a subjective "yes/no" verdict.

Instead provide the measured evidence and a short data-driven assessment such as:

    A single 20×20 km city dataset requires approximately X MiB
    on disk and Y MiB of additional RAM with the current loader.

    Loading takes approximately Z seconds.

    Based on these measurements, the city dataset approach would
    reduce the runtime dataset from the Finland-wide measurements
    by approximately X%.

Do not make further architectural changes.

---

# 14. Preserve the current game

After implementation:

    git diff --check

must pass.

Run the focused benchmark/format tests.

If practical, run the full test suite.

Report:

    Focused tests:
      X passed

    Full suite:
      X passed
      X failed

If failures are pre-existing or unrelated, identify them explicitly.

The benchmark must not alter current gameplay behavior.

---

# Final deliverable

The final response must contain:

1. Exact command used to generate the Oulu dataset.
2. Exact command used to run the benchmark.
3. Exact Oulu bounding box.
4. Oulu dataset size.
5. Oulu ways/nodes/geometry/road length.
6. Oulu load time.
7. Oulu warm-cache load time.
8. Additional RSS.
9. Peak RSS.
10. Memory expansion ratio.
11. Random-access results.
12. Comparison with the Finland-wide benchmark.
13. Test results.
14. Any limitations, especially regarding ways crossing the geographic boundary.

The benchmark is the goal of this task.

Do not integrate Oulu maps into the actual game yet.