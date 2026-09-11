# utils

Standalone helper utilities that aren't tied to a specific game system.

## pbf_index.py

Pre-partitions a large `.osm.pbf` (e.g. `assets/osm/finland-latest.osm.pbf`)
into a grid of small regional `.pbf` cells, so [osm/pbf_source.py](../osm/pbf_source.py)'s
per-bbox `osmium extract` calls can read a tens-of-MB cell instead of
rescanning the whole ~750MB source file on every query.

### Build the index

```bash
make index-pbf
```

or directly:

```bash
PYTHONPATH=src .venv/bin/python -m theroadragetrip.utils.pbf_index src/theroadragetrip/assets/osm/finland-latest.osm.pbf
```

(the `make index-pbf` target always points at the default Finland path
above; use the direct form for a different `--index-dir`/`--grid-deg` or
a different source file)

This is a one-time (per source file) preprocessing step - budget minutes,
not seconds, for the whole-country default grid (~150 cells, one `osmium
extract` process each). It's safe to re-run: an up-to-date index is a
no-op, and an interrupted build resumes (only missing cells are rebuilt).

Options:

| Flag | Default | Meaning |
|---|---|---|
| `--index-dir PATH` | `<pbf_path>.index/` next to the source | where to write the grid |
| `--grid-deg N` | `1.0` | cell size in degrees lon/lat - smaller cells shrink per-query reads further but multiply build time (one `osmium extract` per cell) |
| `--strategy S` | `smart` | osmium extract strategy - must match whatever `pbf_source.py` uses per query, or a cell can end up missing data a query needs |
| `--force` | off | rebuild every cell even if already present |
| `--selftest` | off | run the offline grid-math self-check and exit (no osmium/pbf needed) |

Rebuild whenever the source `.osm.pbf` is replaced (e.g. a fresh Geofabrik
download) - `build_index()` detects a changed/newer source automatically
and rebuilds, so re-running the same command above is enough.

### Use it from code

```python
from theroadragetrip.utils.pbf_index import build_index, tiles_for_bbox

index_dir = build_index(pbf_path)  # builds once, reuses after
tiles = tiles_for_bbox(index_dir, bbox)  # bbox = (south, west, north, east)
```

`tiles_for_bbox()` returns every cell `.pbf` the query bbox overlaps -
usually one, occasionally more for a bbox straddling a cell boundary; an
empty list means there's no usable index, so the caller should fall back
to extracting from the full source file.

[osm/pbf_source.py](../osm/pbf_source.py) already does exactly this: build an index once with
`make index-pbf` (or the CLI above) and every `--osm-source pbf` extract
after that reads the matching cell(s) instead of the full source file -
no code changes, no config flag, nothing else to opt into. Skip the build
and it transparently falls back to reading the full file, same as before
the index existed.
