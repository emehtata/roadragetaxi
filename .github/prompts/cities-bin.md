# Benchmark: Finnish City 20×20 km V2 Road Datasets

## Objective

We have now benchmarked the Oulu 20×20 km road dataset.

Oulu baseline:

```text
Area:
  ~19.9 × 19.9 km
  ~397 km²

Binary:
  1.48 MiB

Ways:
  22,193

Nodes:
  87,084

Geometry points:
  114,123

Road length:
  2,123.265 km

Load time:
  0.333 s

Additional RSS:
  25.71 MiB

Peak RSS:
  47.51 MiB

Memory expansion:
  17.40×

Random access:
  Way:       5.465 ms / 10,000
  Node:      4.880 ms / 10,000
  Geometry: 21.509 ms / 10,000
```

The Finland-wide baseline is:

```text
Binary:
  129.54 MiB

Ways:
  1,038,925

Nodes:
  10,325,748

Geometry points:
  11,548,814

Road length:
  334,848.757 km

Load time:
  32.266 s

Additional RSS:
  2.56 GiB

Peak RSS:
  2.71 GiB

Memory expansion:
  20.24×
```

The next goal is to determine how strongly these numbers vary between Finnish cities.

Benchmark the same approximately 20×20 km area around:

1. Oulu
2. Helsinki
3. Tampere
4. Rovaniemi

The Oulu implementation already exists and must remain compatible.

---

# 1. Inspect the existing Oulu benchmark

Before making changes:

1. Read the existing `tools/osm/benchmark_oulu.py`.
2. Read its tests.
3. Read the existing V2 generator and loader.
4. Read the benchmark documentation.
5. Understand exactly how the Oulu bounding box is calculated.
6. Understand how `osmium extract` is invoked.
7. Understand how the runtime benchmark is performed.

Do not duplicate existing logic unnecessarily.

The new implementation should reuse the existing benchmark infrastructure.

Do not modify the V2 binary format.

---

# 2. Cities

Add support for these four benchmark areas:

```text
Oulu
Helsinki
Tampere
Rovaniemi
```

Use deterministic geographic centers.

Use the same methodology as Oulu:

- approximately 20 km × 20 km
- approximately 400 km²
- WGS84
- calculate the longitude extent using the latitude-dependent meters-per-degree conversion
- calculate the latitude extent using meters-per-degree at the relevant latitude

Do not simply use a fixed number of degrees for every city.

---

# 3. City centers

Use these centers unless the repository already defines authoritative coordinates for these cities:

```text
Oulu:
  latitude  = 65.0121
  longitude = 25.4651

Helsinki:
  latitude  = 60.1699
  longitude = 24.9384

Tampere:
  latitude  = 61.4978
  longitude = 23.7610

Rovaniemi:
  latitude  = 66.5039
  longitude = 25.7294
```

If the existing project already contains canonical coordinates for any of these cities, use those instead and document the source.

---

# 4. Exact bounding boxes

Generate the bounding box from the city center using the same physical-distance calculation as the existing Oulu benchmark.

Target:

```text
width  ≈ 20 km
height ≈ 20 km
area   ≈ 400 km²
```

Print the exact bounding box for every city:

```text
Helsinki:
  min_lat: ...
  max_lat: ...
  min_lon: ...
  max_lon: ...

  width:  ...
  height: ...
  area:   ...
```

The benchmark must be deterministic.

Do not manually type arbitrary bounding boxes if they can be calculated consistently.

---

# 5. Preserve Oulu behavior

Do not change the existing Oulu benchmark semantics unless necessary.

The new multi-city benchmark should produce the same Oulu result methodology as the existing implementation.

If the existing Oulu script remains as a standalone command, keep it working.

For example:

```text
python3 tools/osm/benchmark_oulu.py ...
```

must continue to work.

The new benchmark can be:

```text
python3 tools/osm/benchmark_cities.py ...
```

or another appropriate name based on the repository's existing conventions.

---

# 6. Input PBF

Use the same Finland PBF as the existing Oulu benchmark.

Default:

```text
src/theroadragetrip/assets/osm/finland-latest.osm.pbf
```

Allow an explicit input PBF argument if the existing tooling supports this pattern.

Do not download OSM data automatically.

Do not use Overpass.

The benchmark must operate entirely on the local PBF.

---

# 7. Generate one V2 binary per city

For each city generate:

```text
oulu_20x20.bin
helsinki_20x20.bin
tampere_20x20.bin
rovaniemi_20x20.bin
```

Use the existing V2 format and generator.

Do not create V3.

Do not alter:

- coordinate precision
- road attributes
- highway classification
- one-way information
- lanes
- maxspeed
- names
- refs
- junction information
- bridge/tunnel information
- surface
- OSM way identity
- geometry encoding

The only intended filtering operation is geographic selection.

---

# 8. Important: retain the existing `complete_ways` semantics

The previous Oulu benchmark documented this limitation:

`osmium extract` with the `complete_ways` strategy keeps the entire geometry of a way if any node of that way is inside the bounding box.

Therefore some ways can extend beyond the nominal 20×20 km area.

Do NOT silently change this behavior for the multi-city benchmark.

Report this limitation for all cities.

If the existing tool already reports the actual resulting geographic extent, preserve that information.

---

# 9. Run the complete benchmark for every city

For each city perform:

### Generation

Measure:

- clipped input PBF size
- output V2 size
- generation time
- peak generation RSS

### Dataset statistics

Measure:

- ways
- nodes
- geometry points
- road length
- highway type distribution

### Runtime loading

Measure:

- baseline RSS
- loaded RSS
- additional RSS
- peak RSS
- memory expansion ratio
- cold load time
- warm-cache load time

### Random access

Run exactly:

```text
10,000 way accesses
10,000 node accesses
10,000 geometry accesses
```

Use the same deterministic random seed and methodology as the existing Oulu benchmark.

Do not change the benchmark methodology between cities.

---

# 10. Do not rerun the full Finland benchmark

Do not regenerate or reload the full Finland dataset as part of this task.

Use the already documented Finland baseline:

```text
File size:
  129.54 MiB

Ways:
  1,038,925

Nodes:
  10,325,748

Geometry:
  11,548,814

Road length:
  334,848.757 km

Load time:
  32.266 s

Additional RSS:
  2.56 GiB

Peak RSS:
  2.71 GiB

Memory expansion:
  20.24×
```

The purpose of this benchmark is to compare city datasets with the existing baseline.

---

# 11. Generate a combined JSON result

Produce one machine-readable result containing all four cities.

For example:

```text
multi_city_benchmark.json
```

Structure it logically by city:

```json
{
  "benchmark": "Finnish 20x20 km city comparison",
  "cities": {
    "oulu": {
      "center": {},
      "bbox": {},
      "dimensions": {},
      "dataset": {},
      "generation": {},
      "runtime": {},
      "random_access": {}
    },
    "helsinki": {},
    "tampere": {},
    "rovaniemi": {}
  },
  "finland_baseline": {}
}
```

Use actual measured values.

Do not fabricate or interpolate results.

---

# 12. Calculate relative percentages

For each city calculate its share of the Finland-wide dataset:

```text
binary size / Finland binary size
ways / Finland ways
nodes / Finland nodes
geometry points / Finland geometry points
road length / Finland road length
```

Report percentages.

Also calculate the relationship between:

```text
binary size
RAM increase
load time
```

This is important for determining whether the city-pack approach scales predictably.

---

# 13. Calculate cross-city comparisons

Create a table like:

```text
================================================================================================================
20×20 km Finnish City Benchmark
================================================================================================================

Metric                  Oulu       Helsinki       Tampere       Rovaniemi
----------------------------------------------------------------------------------------------------------------
Area km²                ...        ...            ...            ...
Binary MiB              ...        ...            ...            ...
Ways                    ...        ...            ...            ...
Nodes                   ...        ...            ...            ...
Geometry points         ...        ...            ...            ...
Road length km          ...        ...            ...            ...
Load seconds            ...        ...            ...            ...
Warm load seconds       ...        ...            ...            ...
Additional RSS MiB      ...        ...            ...            ...
Peak RSS MiB            ...        ...            ...            ...
Memory expansion        ...        ...            ...            ...
Way lookup ms           ...        ...            ...            ...
Node lookup ms          ...        ...            ...            ...
Geometry lookup ms      ...        ...            ...            ...
----------------------------------------------------------------------------------------------------------------
```

Use measured values only.

---

# 14. Important derived metrics

Calculate at least:

### Road density

```text
road_length_km / area_km2
```

### Ways per km²

```text
ways / area_km2
```

### Nodes per km²

```text
nodes / area_km2
```

### Binary MiB per 1,000 km of road

```text
binary_size_mib / (road_length_km / 1000)
```

### RAM MiB per 1,000 km of road

```text
additional_rss_mib / (road_length_km / 1000)
```

### Load seconds per 1,000 km of road

```text
load_seconds / (road_length_km / 1000)
```

These measurements will help determine whether road density is a better predictor than geographical area.

---

# 15. Memory scaling analysis

The most important question is whether the current Python memory expansion remains approximately linear.

For each city calculate:

```text
memory_expansion_ratio =
    additional_rss_bytes / binary_size_bytes
```

Compare:

```text
Oulu:
  17.40×

Finland:
  20.24×
```

Then report the observed ratios for Helsinki, Tampere and Rovaniemi.

Do not assume they will be identical.

---

# 16. Load-time scaling analysis

Similarly compare:

```text
Oulu:
  0.333 s

Finland:
  32.266 s
```

Calculate useful ratios such as:

```text
load time / number of ways
load time / number of nodes
load time / geometry points
load time / binary MiB
```

This should help identify whether loading time scales primarily with file size or decoded object count.

---

# 17. Runtime behavior

Do not modify the actual Road Rage Taxi runtime.

Do not integrate the city binaries into:

- Pygame
- NPC system
- Resident simulation
- traffic manager
- routing
- rendering
- game startup
- tile streaming

This remains a benchmark only.

---

# 18. Tests

Add focused tests for the new multi-city benchmark.

At minimum verify:

- all four city definitions exist
- all four bounding boxes are deterministic
- all bounding boxes are approximately 20×20 km
- JSON output contains all four cities
- the benchmark can process a small fixture PBF
- generated V2 output passes existing validation
- runtime benchmark fields are present

Do not require the real Finland PBF in unit tests if that would make tests excessively slow.

Use an appropriate small fixture where possible.

---

# 19. Existing test suite

After implementation run:

```text
git diff --check
```

Then run the focused benchmark tests.

Run the full test suite if practical.

Report pre-existing failures separately from failures introduced by this change.

Do not modify unrelated failing tests.

---

# 20. Final report

The final response must contain:

1. Exact command used.
2. Bounding box for every city.
3. Physical dimensions of every area.
4. Binary size for every city.
5. Ways/nodes/geometry/road length.
6. Generation time.
7. Runtime load time.
8. Warm-cache load time.
9. Additional RSS.
10. Peak RSS.
11. Memory expansion ratio.
12. Random access results.
13. Road density.
14. Cross-city comparison.
15. Finland comparison.
16. Test results.
17. Any limitations.

Most importantly, explicitly answer with measured data:

> How much does a 20×20 km map vary in size and RAM usage between Oulu, Helsinki, Tampere and Rovaniemi?

And:

> Does geographical area alone provide a useful estimate, or does road density dominate the actual resource requirements?

Do not provide a subjective architectural verdict.

Provide the measurements needed to make that decision later.

---

# Constraints

This task is a benchmark.

Do not:

- redesign V2
- introduce V3
- optimize Python memory
- introduce NumPy
- introduce mmap
- add a spatial index
- clip geometry differently
- change OSM extraction semantics
- modify gameplay
- modify rendering
- modify NPCs
- modify routing
- modify Overpass
- modify existing tile streaming

The objective is to obtain a clean, directly comparable four-city dataset and runtime benchmark.