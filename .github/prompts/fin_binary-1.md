Work on the current `release/0.15.0alpha` branch of the Road Rage Taxi repository.

We now have a working Finland-wide OSM road extraction pipeline.

The first generated dataset produced these measured results:

```text
Input PBF:                  731.51 MiB
Output binary:              281.43 MiB
Reduction:                  61.527%
BIN/PBF ratio:              38.473%

Ways inspected:             10,173,409
Drivable ways:               1,038,925
Stored nodes:                10,325,748
Geometry points:             11,548,814
Road length:                 334,848.8 km

Processing time:             107.9 seconds
Approx. Python peak memory:    2.42 GiB
Validation:                  PASS
```

The goal of this task is to create **binary format v2** and significantly reduce the size of the generated `finland_roads.bin` without removing ANY road network data.

---

# 1. Critical requirement: preserve the dataset

This is an optimization of the binary representation only.

The following must remain unchanged between v1 and v2:

- number of drivable ways
- road geometry
- road length
- all selected highway types
- all currently exported road attributes
- one-way information
- lane information
- maxspeed information
- road names
- road refs
- junction information
- bridge information
- tunnel information
- surface information
- OSM way identity where currently preserved
- all node references/geometry required by the current format

Do NOT remove roads.

Do NOT narrow the `DRIVABLE_HIGHWAY_TYPES` whitelist.

Do NOT remove attributes simply because they appear unnecessary.

If an attribute is later determined to be unnecessary for runtime, that should be a separate future change.

For this task:

> Same data, smaller representation.

---

# 2. First: inspect the existing implementation

Before changing anything, inspect the complete implementation created in the previous task.

Find:

- the Finland road extraction script
- the binary writer
- the binary reader
- the binary validation code
- the statistics generator
- the binary format documentation
- any tests

Do not assume filenames.

Search the repository and identify the actual implementation.

Understand exactly what is currently stored in the 281.43 MiB file.

---

# 3. Analyze the current binary format

Before implementing v2, add or create a diagnostic mode that can analyze the existing v1 file.

The analysis should determine how the 281.43 MiB is distributed.

At minimum calculate:

```text
Header size
Node table size
Way table size
Geometry/reference data size
String data size
Metadata size
Padding/alignment
Other sections
```

If the current format has variable-length records, estimate their contribution.

Also calculate:

```text
bytes per stored node
bytes per geometry point
bytes per way
bytes per attribute
```

where practical.

Do not guess.

Use the actual binary structure.

Produce a report similar to:

```text
========================================
Finland Roads Binary Format Analysis
========================================

File size:                 281.43 MiB

Header:                    XX MiB
Nodes:                     XX MiB
Ways:                      XX MiB
Geometry references:       XX MiB
Strings:                   XX MiB
Metadata:                  XX MiB
Other:                     XX MiB

Stored nodes:              10,325,748
Geometry points:           11,548,814
Ways:                       1,038,925

Average bytes/node:
Average bytes/geometry point:
Average bytes/way:
```

This analysis must happen before making optimization decisions.

---

# 4. Implement binary format v2 separately

Do NOT silently change v1.

The new format must have an explicit version:

```text
MAGIC
VERSION = 2
...
```

The existing v1 reader should continue to recognize v1.

Ideally the reader should support:

```text
v1
v2
```

so that we can compare both formats.

Do not make v2 backwards-compatible at the byte level.

It is fine for v2 to use a completely different internal layout.

---

# 5. Optimize coordinate storage

Investigate the current coordinate representation.

If v1 stores absolute coordinates for every node, evaluate integer coordinate encoding.

A good baseline is:

```text
latitude_microdegrees  = round(latitude * 1_000_000)
longitude_microdegrees = round(longitude * 1_000_000)
```

stored as signed 32-bit integers.

However, do not automatically implement this if v1 already uses an equivalent representation.

Then investigate delta encoding.

For ordered geometry:

```text
x1
y1

dx2 = x2 - x1
dy2 = y2 - y1

dx3 = x3 - x2
dy3 = y3 - y2
```

Because adjacent road points are spatially close, these deltas should be much smaller than absolute coordinates.

Evaluate whether:

- int16
- int24
- int32
- variable-length integer

is appropriate.

Do not sacrifice coordinate precision.

The v2 decoder must reproduce coordinates within a clearly documented tolerance.

---

# 6. Investigate whether OSM node IDs are actually necessary at runtime

The v1 format may preserve:

```text
OSM node ID
```

for every stored node.

Analyze whether this is required by the runtime representation.

Do not simply remove it.

Instead determine:

- whether node IDs are required to reconstruct ways
- whether they are required by the existing game
- whether they are only needed during extraction
- whether a local sequential node index could replace them

If OSM IDs are not required after extraction, v2 should consider:

```text
OSM node ID
        ↓
local node index
```

For example:

```text
node 0
node 1
node 2
...
node 10,325,747
```

Ways can then reference compact local indices.

If OSM IDs are still needed, retain them.

Document the decision.

---

# 7. Optimize way node references

Analyze how v1 stores:

```text
way → node references
```

If full 64-bit OSM node IDs are stored repeatedly, this is a major optimization target.

Prefer local sequential indices where possible:

```text
way:
    node 100
    node 101
    node 102
    node 103
```

instead of:

```text
way:
    981273645123
    981273645127
    981273645132
    981273645138
```

Then investigate delta encoding:

```text
100
+1
+1
+1
```

combined with a compact integer encoding.

The representation must remain lossless.

---

# 8. Optimize strings

Inspect how these fields are currently stored:

```text
name
ref
highway
surface
junction
```

Do not store repeated strings independently for every way.

Create dictionaries/string tables where appropriate.

For example:

```text
HighwayType:
0 = motorway
1 = trunk
2 = primary
...

Surface:
0 = asphalt
1 = gravel
...
```

For arbitrary strings such as road names:

```text
String table:
0 → "Hämeenkatu"
1 → "Kirkkokatu"
2 → "E75"
...
```

Ways then store integer IDs.

Measure whether a string table actually saves space before finalizing the implementation.

---

# 9. Optimize boolean/enum metadata

Do not store individual Python booleans or strings if compact integer flags are sufficient.

For example:

```text
flags:
bit 0 = oneway
bit 1 = bridge
bit 2 = tunnel
bit 3 = junction
...
```

Use compact enums for:

```text
highway
surface
junction
```

Use appropriate integer representations for:

```text
lanes
maxspeed
```

However, preserve special values such as:

```text
unknown
none
conditional
signals
```

if the current extraction can produce them.

Do not change semantics just to save bytes.

---

# 10. Investigate variable-length integers

Evaluate whether variable-length integer encoding is useful for:

- node indices
- delta coordinates
- way IDs
- string IDs
- geometry counts
- metadata indexes

Use a deterministic implementation.

Do not add compression merely because it sounds useful.

Benchmark it.

The resulting format should remain fast enough to load and query during game startup/runtime.

---

# 11. Consider section-based binary layout

Prefer a layout that allows selective reading.

For example:

```text
Header
  ↓
Metadata
  ↓
String tables
  ↓
Node table
  ↓
Way table
  ↓
Geometry/reference data
```

Consider storing offsets/counts in the header:

```text
node_section_offset
node_count

way_section_offset
way_count

geometry_section_offset
geometry_size

string_section_offset
string_size
```

This will make future memory mapping possible.

Do not unnecessarily load the entire file into RAM.

The eventual goal is to make a Finland-wide road network usable without excessive memory consumption.

---

# 12. Consider memory mapping

The v1 extraction used approximately:

```text
2.42 GiB
```

of Python memory.

This is acceptable for the offline generator but we should investigate whether the resulting v2 format can later be memory-mapped efficiently.

The v2 layout should therefore be designed with:

- fixed-size structures where practical
- explicit offsets
- contiguous arrays
- no Python-specific serialization

in mind.

Do NOT implement runtime memory mapping into the game yet unless it is trivial.

The focus is the binary format.

---

# 13. Preserve all data

Create a v1 → v2 verification tool.

It must load both datasets and compare them.

The comparison must verify:

```text
Way count
Node/geometry count
Highway type
Oneway
Lanes
Maxspeed
Name
Ref
Junction
Bridge
Tunnel
Surface
Geometry
```

for every corresponding road.

Because v2 may use local IDs instead of OSM IDs internally, compare the semantic data, not merely raw IDs.

The comparison should fail loudly if anything changes.

---

# 14. Generate v2 from the original PBF

Do not convert v1 → v2 unless there is a strong reason.

Prefer:

```text
Finland PBF
    ↓
shared extraction logic
    ↓
v2 writer
```

This avoids carrying unnecessary v1 representation into v2.

If useful, retain the v1 writer temporarily so we can generate both:

```text
finland_roads_v1.bin
finland_roads_v2.bin
```

from exactly the same extracted data.

This is ideal for benchmarking.

---

# 15. Benchmark v1 vs v2

Run both formats against the same Finland PBF.

Produce a comparison:

```text
Metric                    v1              v2
------------------------------------------------
File size                 281.43 MiB      XX MiB
Ways                      1,038,925       1,038,925
Stored nodes              10,325,748      same
Geometry points           11,548,814      same
Road length               334,848.8 km    same
Processing time           107.9 s         XX s
Peak memory               2.42 GiB        XX GiB
Validation                PASS            PASS
```

Also report:

```text
v2 size reduction vs v1
v2 bytes / way
v2 bytes / geometry point
v2 bytes / stored node
```

The most important metric is:

> v2 must contain exactly the same road network and semantic information as v1.

---

# 16. Add a size regression test

Add a test that prevents accidental format bloat.

Do not hard-code an unrealistically strict exact file size because binary layout may evolve.

Instead establish a reasonable upper bound based on the current measured result.

For example:

```text
v2 must be smaller than v1
```

for the reference Finland dataset.

If a future change makes v2 larger than v1, the test/report should make this obvious.

---

# 17. Keep the current game untouched

Do NOT:

- replace the current Overpass system
- replace tile streaming
- change tile size
- change NPC routing
- change road rendering
- change game startup
- load `finland_roads.bin` automatically
- remove existing OSM functionality

This task is only about creating and validating the optimized dataset format.

---

# 18. Documentation

Update the road dataset documentation with:

```text
Binary format v1
Binary format v2
Why v2 exists
Format structure
Coordinate representation
Node representation
Way representation
String tables
Flags/enums
Validation method
Generation command
```

Clearly state that v2 is intended to preserve exactly the same dataset as v1.

---

# 19. Run the full real-world test

After implementation, run the generator against the same Finland PBF used to create v1.

Generate:

```text
finland_roads_v2.bin
finland_roads_v2.stats.json
```

If possible, retain the v1 dataset for comparison.

Run full semantic validation.

Do not report success until:

```text
v1 → v2 semantic comparison = PASS
```

---

# 20. Final report

At the end, provide a concise but complete report:

```text
========================================
Road Rage Taxi Finland Roads v2
========================================

v1 size:
v2 size:

v2 reduction vs v1:
v2/PBF ratio:

Ways:
Nodes:
Geometry points:
Road length:

Processing time:
Peak memory:

Validation:
PASS/FAIL

Major optimizations:
- ...
- ...
- ...

Remaining opportunities:
- ...
- ...
```

Also report exactly which optimizations produced the biggest size reduction.

Do not claim an optimization was useful unless the measurements demonstrate it.

---

## Final principle

The success criterion is NOT:

> "Make the file as small as possible."

The success criterion is:

> "Represent exactly the same 1,038,925 drivable ways, 334,848.8 km of road network, geometry and currently exported attributes in a substantially smaller, deterministic and runtime-friendly binary format."

Do not sacrifice data correctness for compression.

Do not remove roads.

Do not remove attributes.

Do not change the highway whitelist.

Measure first, optimize second, validate third.
