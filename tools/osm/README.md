# Finland road binary builder

`build_finland_roads.py` is a standalone converter for the future Road Rage
Taxi NPC routing dataset. It extracts the selected drivable road ways from a
local Finland OpenStreetMap PBF and writes a deterministic, portable binary
plus a JSON statistics report. It does not alter or integrate with the game's
current Overpass/PBF tile streaming.

## Requirements and usage

- Python 3.10 or newer
- `osmium-tool` available as `osmium`
- A local `.osm.pbf`; the tool never downloads one

```bash
python tools/osm/build_finland_roads.py \
  --input /data/finland-latest.osm.pbf \
  --output data/finland_roads_v2.bin \
  --format-version 2
```

The optional `--highway-types` argument accepts a comma-separated subset of
the fixed whitelist. Unknown values are rejected.

The original v1 format remains available by omitting `--format-version 2` or
passing `--format-version 1`. Both readers and validators remain supported.

Analyze either format or compare every v1/v2 way and geometry point with:

```bash
python tools/osm/build_finland_roads.py --analyze data/finland_roads_v2.bin
python tools/osm/build_finland_roads.py --compare \
  data/finland_roads_v1.bin data/finland_roads_v2.bin
```

## Outputs

The command writes the requested `.bin` and a sibling `.stats.json`. Output
replacement is atomic, so interruption cannot publish a partial binary. The
generated files are not added to the repository automatically.

## Binary format v1

The little-endian binary starts with `RRTROAD`, format version 1, coordinate
precision, flags, node count, and way count. It then contains:

- one global node table: signed 64-bit OSM ID and signed 32-bit latitude and
  longitude at 10^-7 degree precision;
- ordered road records: OSM way ID, highway code, normalized one-way direction,
  layer, lane count, speed limit, bridge/tunnel/roundabout flags, ordered node IDs,
  and length-prefixed UTF-8 name, ref, junction, and surface strings.

A shared node table keeps intersection coordinates from being duplicated.
Version 1 retains every OSM node ID and repeats signed 64-bit IDs in every way's
geometry.

## Binary format v2

V2 starts with `RRTROAD`, version 2, counts, and explicit offsets for six
contiguous sections:

1. fixed-size coordinate table;
2. fixed-size way-record offset table;
3. variable-size way records;
4. delta-varint geometry references;
5. fixed-size string offsets;
6. deduplicated UTF-8 string data.

Coordinates remain signed 32-bit integers at 10^-7 degree precision, so v2 is
coordinate-lossless relative to v1. V2 replaces persisted OSM node IDs with
sequential local indices: the current game route graph consumes geometry and
never uses OSM node identity, while OSM way IDs remain preserved. Each way
stores its OSM ID, highway enum, one-way direction, layer, lanes, speed,
bridge/tunnel/roundabout flags, exact ordered geometry, and indexes for its
name, ref, junction, and surface strings.

The section layout and way-offset table allow future selective reads or memory
mapping without changing the format. Runtime memory mapping is intentionally
not integrated yet.

### Measured Finland result

| Section | v1 | v2 |
|---|---:|---:|
| Nodes | 157.56 MiB | 78.78 MiB |
| Way metadata/records and offsets | 19.82 MiB | 26.36 MiB |
| Geometry references | 88.11 MiB | 22.73 MiB |
| Strings and string indexes | 15.95 MiB | 1.67 MiB |
| Total | 281.43 MiB | 129.54 MiB |

V2 is 53.97% smaller than v1 and contains the same 1,038,925 ways,
10,325,748 nodes, 11,548,814 geometry points, attributes, and coordinates. The
full semantic comparison passes.

One-way, lane and speed values in both formats follow the current game's
parsing behavior. Neither version applies access-tag policy or stores turn
restrictions; those are separate future dataset decisions, not v2 reductions.

## Runtime loader benchmark

Benchmark the existing v2 Python loader without starting the game:

```bash
python tools/osm/benchmark_finland_roads.py \
  /tmp/finland_roads_v2.bin \
  --json /tmp/v2_runtime_benchmark.json
```

On the development Linux environment, the 129.54 MiB reference file took
32.266 seconds to materialize and increased process RSS by 2.56 GiB (20.24x
the file size). A second warm-cache run took 33.608 seconds, indicating that
Python object decoding rather than filesystem I/O dominates startup. Once
loaded, measured 10,000-way random lookup runs took 10.7-15.4 ms, node
lookups 8.8-16.4 ms, and geometry access for 10,000 ways took 52.0-66.5 ms.

The current format has no spatial index, so the benchmark reports nearest-road
lookup as unavailable. mmap is not benchmarked because the existing runtime
reader intentionally being measured fully materializes Python objects; adding
a second mmap reader would be a separate runtime architecture task.

## Highway whitelist

`motorway`, `motorway_link`, `trunk`, `trunk_link`, `primary`, `primary_link`,
`secondary`, `secondary_link`, `tertiary`, `tertiary_link`, `unclassified`,
`residential`, `living_street`, `service`, and `road`.

## OpenStreetMap attribution

The generated file is derived from OpenStreetMap data. Distribution and use
must comply with the OpenStreetMap Open Database License (ODbL), including its
attribution and share-alike requirements where applicable. The generated data
is not added to this repository automatically.
