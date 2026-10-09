Work on the current `release/0.15.0alpha` branch of the Road Rage Taxi repository.

## Goal

Create a standalone tool that extracts the **drivable road network of Finland** from a local OpenStreetMap `.osm.pbf` file and converts it into a compact binary file:

```text
finland_roads.bin
```

This is a first proof-of-concept for a future global/local road-network dataset used by NPC routing.

**Do not modify the existing Overpass tile streaming implementation yet.**

**Do not integrate the new binary dataset into the game yet.**

The goal of this task is only:

```text
Finland OSM PBF
        ↓
road extraction
        ↓
finland_roads.bin
        ↓
statistics/report
```

We need a reliable and reproducible conversion tool first.

---

# 1. Inspect the existing implementation first

Before writing code, inspect the repository and understand the existing OSM architecture.

Pay particular attention to:

```text
src/theroadragetrip/osm/
src/theroadragetrip/osm/overpass.py
src/theroadragetrip/osm/build.py
src/theroadragetrip/osm/models.py
src/theroadragetrip/osm/constants.py
src/theroadragetrip/osm/tile_streaming.py
src/theroadragetrip/osm/autofetch.py
```

Also inspect the existing NPC routing/road graph implementation.

Find:

- how OSM ways are represented
- how nodes are represented
- how road geometry is represented
- how `highway` values are interpreted
- how `oneway` is handled
- how `lanes` is handled
- how `maxspeed` is handled
- how road IDs are represented
- whether road names/ref values are currently required
- whether junction information is used
- whether bridge/tunnel information matters
- how roads are converted into the current NPC navigation graph

Do not duplicate existing logic unnecessarily.

Reuse existing constants or parsing logic where appropriate.

---

# 2. Define the initial drivable highway whitelist

Create one clearly defined whitelist for the first dataset.

Start with:

```python
DRIVABLE_HIGHWAY_TYPES = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
    "road",
}
```

Do NOT include:

```text
footway
path
cycleway
pedestrian
steps
bridleway
corridor
construction
proposed
track
raceway
elevator
platform
```

Do not silently invent additional highway types.

Make the whitelist configurable so it can later be changed without rewriting the extraction algorithm.

---

# 3. Decide the tool location

Create a standalone utility under an appropriate existing project directory.

Prefer something like:

```text
tools/osm/
```

or another location consistent with the repository structure.

The tool should be executable independently from the game.

For example:

```bash
python tools/osm/build_finland_roads.py \
    --input /path/to/finland-latest.osm.pbf \
    --output data/finland_roads.bin
```

Do not hard-code the user's filesystem paths.

---

# 4. Choose a suitable PBF parser

Inspect the current Python dependencies first.

If an existing OSM/PBF library is already used by the project and is suitable for reading `.osm.pbf`, reuse it.

Otherwise choose a well-maintained Python-compatible PBF parser appropriate for large OSM PBF files.

The tool must be able to process the entire Finland PBF without loading the complete PBF into RAM.

**Streaming processing is required.**

Do not implement:

```python
all_data = list(...)
```

for the entire Finland dataset.

The tool must work with a PBF of several hundred MB.

---

# 5. Extract only required OSM data

The first implementation should preserve enough information to later construct an NPC road graph.

For each selected road way, investigate and preserve at least:

```text
OSM way ID
highway
oneway
lanes
maxspeed
name
ref
junction
bridge
tunnel
surface
```

However:

**Do not blindly store every OSM tag.**

Only retain tags that are actually useful for the Road Rage Taxi road network.

If inspection of the existing game code shows that some of the above fields are not currently needed, document that rather than inventing usage.

Also preserve the ordered list of referenced OSM node IDs for every road way.

We need the geometry to be reconstructable.

---

# 6. Handle OSM nodes correctly

A major requirement is that way geometry can be reconstructed.

A road way contains references such as:

```text
way:
  123
  456
  789
  1000
```

The PBF contains the corresponding nodes.

Design the extraction pipeline so that the resulting binary contains enough information to reconstruct the road geometry without requiring the original PBF at runtime.

Avoid storing unnecessary duplicate node data.

Consider using a separate node table:

```text
Node ID → coordinate
```

and road ways reference those node IDs.

However, do not make this assumption blindly. Compare the alternatives:

1. global node table + way node references
2. directly storing geometry per way

Choose the representation that is simpler and produces a reasonably compact result for the expected dataset.

Document the decision.

---

# 7. Coordinate representation

Do not store latitude/longitude as Python floats in the binary format without thinking about precision.

Use a deterministic compact representation.

For example, integer microdegrees:

```text
latitude  * 1_000_000
longitude * 1_000_000
```

stored as signed 32-bit integers.

But first check the actual coordinate ranges and precision requirements.

The format must preserve enough precision for the game's road geometry.

Document the chosen representation.

---

# 8. Binary file format

Create a small explicit binary format with a header.

The file should contain something conceptually like:

```text
MAGIC
VERSION
SOURCE/FORMAT FLAGS
NODE COUNT
WAY COUNT
...
NODE DATA
WAY DATA
```

Use a fixed version number.

For example:

```text
MAGIC = b"RRTROAD"
VERSION = 1
```

Do not use Python `pickle`.

Do not serialize arbitrary Python objects.

The binary format must be deterministic and portable.

Create a Python reader as well:

```text
load_finland_roads()
```

or equivalent.

The reader does not need to be integrated into the game yet, but it should be capable of validating that the generated file can be read back correctly.

---

# 9. Measure everything

The extraction script must print useful statistics.

At minimum:

```text
Input PBF:
Output BIN:

PBF file size:
BIN file size:

Total OSM ways inspected:
Drivable ways:
Ignored ways:

Total OSM nodes encountered:
Nodes stored:

Total road geometry points:
Total road length if practical:

Highway type breakdown:
  motorway:
  trunk:
  primary:
  ...
```

Also report:

```text
Extraction time
Binary writing time
Total processing time
Peak/approximate memory usage if practical
```

Most importantly, report the compression/reduction ratio:

```text
PBF → BIN size reduction:
XX.X %
```

and:

```text
BIN / PBF:
X.XX %
```

---

# 10. Produce a JSON statistics file

In addition to:

```text
finland_roads.bin
```

generate:

```text
finland_roads.stats.json
```

Example:

```json
{
  "format_version": 1,
  "input_file_size": 0,
  "output_file_size": 0,
  "total_ways": 0,
  "drivable_ways": 0,
  "total_nodes": 0,
  "stored_nodes": 0,
  "geometry_points": 0,
  "highway_types": {},
  "processing_seconds": 0
}
```

Use actual measured values.

This will allow us to compare future versions of the binary format.

---

# 11. Add validation

The generated dataset must be validated before the script reports success.

Check at least:

- binary header is valid
- version is supported
- node count matches the written node records
- way count matches the written way records
- all referenced nodes exist
- coordinates are within valid ranges
- highway types are from the configured whitelist
- no malformed records exist
- the file can be completely read back

If validation fails, return a non-zero exit code.

---

# 12. Do not alter current game behavior

This task must NOT:

- change Overpass queries
- change tile size
- change active tile count
- change NPC behavior
- change road rendering
- change camera behavior
- change OSM tile caching
- replace the current road graph
- modify runtime game startup
- automatically load the new `.bin` into the game

This is an isolated data-generation tool.

---

# 13. Add documentation

Create a concise README for the tool explaining:

```text
Purpose
Input requirements
Installation/dependencies
Usage
Output files
Binary format version
Highway whitelist
License/OSM attribution
```

Include an example:

```bash
python tools/osm/build_finland_roads.py \
    --input /data/finland-latest.osm.pbf \
    --output data/finland_roads.bin
```

Also explain that the resulting dataset is derived from OpenStreetMap data and is subject to the applicable OSM Open Database License requirements.

Do not copy OSM data into the repository automatically.

---

# 14. Run the tool against the real Finland PBF

After implementing the tool, locate the existing Finland `.osm.pbf` if it is available in the development environment.

If the file is not available, do NOT download hundreds of MB automatically without asking.

Instead:

1. complete the implementation
2. run a small test against a small PBF/test fixture if available
3. verify the reader and validator
4. tell me the exact command needed to run it against my Finland PBF

If the Finland PBF is already available locally, run the full extraction.

The expected command should be equivalent to:

```bash
python tools/osm/build_finland_roads.py \
    --input <FINLAND_PBF> \
    --output data/finland_roads.bin
```

---

# 15. After the full extraction, report the actual numbers

Do not estimate the final size.

Report the measured results:

```text
========================================
Road Rage Taxi Finland Road Dataset
========================================

Input PBF:
Input size:

Output:
Output size:

Reduction:
Ratio:

Ways inspected:
Drivable ways:

Nodes encountered:
Nodes stored:

Geometry points:

Highway breakdown:
...

Processing time:
Peak memory:

Validation:
PASS/FAIL
```

This data is important because the next task will be designing the runtime road-network architecture around the actual size.

---

# 16. Tests

Add focused tests for:

- highway whitelist
- binary header
- binary writer/reader round trip
- coordinate encoding/decoding
- malformed binary detection
- missing referenced node detection
- statistics generation

Use small synthetic OSM-like fixtures rather than requiring the full Finland PBF for unit tests.

Run the existing test suite after the implementation.

Fix any regressions caused by your changes.

---

# 17. Important implementation principle

Do not over-engineer this first version.

The objective is to answer one concrete question:

> How large is a compact, self-contained binary representation of the entire Finnish drivable OSM road network for Road Rage Taxi?

Build a correct measurable proof-of-concept first.

After we have the real:

```text
way count
node count
geometry point count
BIN size
memory usage
processing time
```

we will optimize the format and decide how it should integrate with NPC routing and the existing tile-streaming system.

At the end, summarize:

1. files created/modified
2. implementation decisions
3. actual Finland dataset statistics
4. binary size
5. processing time
6. validation result
7. any concerns or limitations
8. exact command used to reproduce the dataset
