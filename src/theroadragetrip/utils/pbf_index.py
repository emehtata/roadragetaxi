"""Pre-partition a large .osm.pbf into a grid of small regional .pbf files,
so per-bbox extraction (osm/pbf_source.py) only has to scan a tiny regional
file instead of rescanning the whole country extract on every query.

Each cell is cut with the same strategy (default "smart") pbf_source.py
uses for its real per-bbox extract, so a cell file is already a complete
superset for anything touching that cell - extracting a query bbox from it
later gives the same elements osmium would return extracting straight from
the full source file (verified in tests/test_pbf_index.py). A query bbox
that straddles more than one cell is handled by extracting from every cell
it overlaps and letting the caller merge/dedupe by (type, id) - see
tiles_for_bbox().

Cells are cut ONE AT A TIME (one `osmium extract` process per cell), not
batched into a single multi-region pass. That costs one file scan per cell
instead of one scan total, but it's not optional here: osmium's "smart"/
"complete_ways" strategies fully resolve any relation touching a cell (e.g.
a coastline or route relation strung along hundreds of km), and doing that
for more than one cell *concurrently* (via `osmium extract --config`, which
runs every region in one pass) was measured to blow past several GB of RAM
and get OOM-killed even with just two small cells in flight at once. One
cell at a time is the same memory profile as the single-bbox extract
osm/pbf_source.py already does safely today - just done once up front for
a whole grid instead of once per query. See DEFAULT_GRID_SIZE_DEG for the
resulting cell count/build-time trade-off.
"""
import json
import logging
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Degrees, not meters: an .osm.pbf's own header bbox (and osmium's --bbox)
# is lon/lat. Each cell costs its own `osmium extract` process (see module
# docstring), so the grid must stay coarse enough to build in a reasonable
# time: 1.0 deg is ~55-110km across Finland's latitude range, ~150 cells
# for the whole country, each a single-digit-to-tens-of-seconds extract -
# a one-time build measured in minutes, not hours. Still a large win per
# query: a query bbox (a few km, see tile_streaming.PBF_TILE_SIZE_M) reads
# a tens-of-MB cell instead of the full ~750MB source file.
DEFAULT_GRID_SIZE_DEG = 1.0
DEFAULT_STRATEGY = "smart"
MANIFEST_NAME = "manifest.json"

# Extra margin (degrees) cut into each cell file beyond its own nominal grid
# bounds, so a query that only slightly crosses a grid line can still be
# answered from one cell instead of two. Without this, any query bbox
# straddling a boundary needs an osmium extract from *every* cell it
# touches (see tiles_for_bbox) - normally rare, but Finland's default city
# (Oulu, (65.012, 25.468) - see config.py's city catalog) sits only 0.012deg
# above the lat=65.0 grid line, so essentially every autofetch tile
# (PBF_TILE_SIZE_M=3300m, ~0.03deg) near the default starting area straddles
# it, doubling extraction cost for the whole default play area. 0.05deg
# (~5.5km at Finland's latitudes) comfortably covers a query centered that
# far from the line without needing the neighbor; a query straddling by
# more than that (a large initial-load bbox, or a coincidence elsewhere)
# still correctly falls back to pulling both cells - this only removes the
# redundant work for the common case, never removes correctness.
DEFAULT_CELL_PADDING_DEG = 0.05


def default_index_dir(pbf_path: Path) -> Path:
    return Path(pbf_path).parent / f"{Path(pbf_path).name}.index"


def _source_bbox(pbf_path: Path) -> Tuple[float, float, float, float]:
    """(west, south, east, north) covering the whole source file.

    Extracts like Geofabrik's ship a header bbox, so this is normally just
    a header read. A file with no header bbox (e.g. hand-built with
    `osmium cat`) falls back to `fileinfo -e`, which scans the whole file
    to compute one - no slower than the indexing pass that follows anyway.
    """
    result = subprocess.run(
        ["osmium", "fileinfo", "--json", str(pbf_path)],
        capture_output=True, text=True, check=True,
    )
    boxes = json.loads(result.stdout)["header"]["boxes"]
    if boxes:
        west, south, east, north = boxes[0]
        return west, south, east, north

    result = subprocess.run(
        ["osmium", "fileinfo", "-e", "--json", str(pbf_path)],
        capture_output=True, text=True, check=True,
    )
    bbox = json.loads(result.stdout)["data"]["bbox"]
    west, south, east, north = bbox
    return west, south, east, north


def _cell(lon: float, lat: float, grid_size_deg: float) -> Tuple[int, int]:
    return math.floor(lon / grid_size_deg), math.floor(lat / grid_size_deg)


def _cell_bounds(gx: int, gy: int, grid_size_deg: float) -> Tuple[float, float, float, float]:
    west, south = gx * grid_size_deg, gy * grid_size_deg
    return west, south, west + grid_size_deg, south + grid_size_deg


def build_index(
    pbf_path: Path,
    index_dir: Optional[Path] = None,
    grid_size_deg: float = DEFAULT_GRID_SIZE_DEG,
    strategy: str = DEFAULT_STRATEGY,
    cell_padding_deg: float = DEFAULT_CELL_PADDING_DEG,
    force: bool = False,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Path:
    """Build (or reuse) a grid index for `pbf_path`. Returns the index dir.

    Cheap to call every run: with a complete, up-to-date index already on
    disk this is just a stat() and a manifest read, no osmium call at all.
    An index left half-built by an earlier interrupted run resumes - only
    cells not already on disk are (re-)extracted. An index built with
    different parameters (grid_size_deg/strategy/cell_padding_deg) than
    requested is treated the same as `force=True` - the cells on disk are
    for a different grid and can't be resumed into this one.
    """
    pbf_path = Path(pbf_path)
    index_dir = Path(index_dir) if index_dir else default_index_dir(pbf_path)

    existing_manifest = load_manifest(index_dir) if not force else None
    if not force and not index_is_stale(pbf_path, index_dir) and existing_manifest is not None:
        params_match = (
            existing_manifest.get("grid_size_deg") == grid_size_deg
            and existing_manifest.get("strategy") == strategy
            and existing_manifest.get("cell_padding_deg", 0.0) == cell_padding_deg
        )
        if params_match and all((index_dir / cell["file"]).is_file() for cell in existing_manifest["cells"]):
            logger.info("PBF index already up to date: %s", index_dir)
            return index_dir
        if not params_match:
            # Cells on disk (if any) were cut for a different grid/padding -
            # not a partial build of *this* one, so nothing is resumable.
            force = True
            logger.info("PBF index parameters changed - rebuilding %s from scratch", index_dir)

    if shutil.which("osmium") is None:
        raise RuntimeError("Building a PBF index requires the 'osmium' command-line tool (osmium-tool).")

    if progress_callback:
        progress_callback(0.0, "Reading source bbox...")
    west, south, east, north = _source_bbox(pbf_path)
    gx0, gy0 = math.floor(west / grid_size_deg), math.floor(south / grid_size_deg)
    gx1, gy1 = math.floor(east / grid_size_deg), math.floor(north / grid_size_deg)

    cells = [
        {"gx": gx, "gy": gy, "bbox": list(_cell_bounds(gx, gy, grid_size_deg)), "file": f"tile_{gx}_{gy}.osm.pbf"}
        for gy in range(gy0, gy1 + 1)
        for gx in range(gx0, gx1 + 1)
    ]

    index_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Building PBF index at %s: %d cells, one extract at a time", index_dir, len(cells))
    for i, cell in enumerate(cells):
        out_path = index_dir / cell["file"]
        if progress_callback:
            progress_callback(0.1 + 0.85 * i / len(cells), f"Cell {i + 1}/{len(cells)} ({cell['file']})...")
        if not force and out_path.is_file():
            continue  # resuming a previous (interrupted) build - this cell is already done
        cw, cs, ce, cn = cell["bbox"]
        cmd = [
            "osmium", "extract",
            "--bbox", f"{cw - cell_padding_deg},{cs - cell_padding_deg},{ce + cell_padding_deg},{cn + cell_padding_deg}",
            "-s", strategy, "-f", "pbf", "-O",
            "-o", str(out_path),
            str(pbf_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"osmium extract failed for cell {cell['file']} (exit {result.returncode}): {result.stderr.strip()}")

    st = pbf_path.stat()
    manifest = {
        "source": {"path": str(pbf_path.resolve()), "size": st.st_size, "mtime": st.st_mtime},
        "grid_size_deg": grid_size_deg,
        "strategy": strategy,
        "cell_padding_deg": cell_padding_deg,
        "cells": cells,
    }
    (index_dir / MANIFEST_NAME).write_text(json.dumps(manifest))

    if progress_callback:
        progress_callback(1.0, f"Index built: {len(cells)} cells")
    logger.info("Built PBF index at %s (%d cells)", index_dir, len(cells))
    return index_dir


def load_manifest(index_dir: Path) -> Optional[dict]:
    path = Path(index_dir) / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def index_is_stale(pbf_path: Path, index_dir: Path) -> bool:
    """True if the index is missing, unreadable, or was built from a
    different (or since-modified) source file."""
    manifest = load_manifest(Path(index_dir))
    if manifest is None:
        return True
    src = manifest.get("source", {})
    try:
        st = Path(pbf_path).stat()
    except OSError:
        return True
    return src.get("size") != st.st_size or src.get("mtime") != st.st_mtime


def tiles_for_bbox(index_dir: Path, bbox: Tuple[float, float, float, float]) -> List[Path]:
    """Regional .pbf file(s) that answer `bbox`
    (south, west, north, east - same convention as osm/pbf_source.py).

    Tries a single cell first: any cell whose *padded* bounds (its file
    actually contains data cell_padding_deg past its nominal grid bounds -
    see build_index) fully contain the whole query bbox needs no help from
    a neighbor, so that one cell alone is returned. This is what lets a
    query that only slightly crosses a grid line resolve to one file
    instead of two - naively widening *every* cell's overlap test by the
    padding would instead make MORE cells match a given query, the opposite
    of the goal, since expanding a boundary can only add false-positive
    overlaps, never remove real ones.

    Only when no single cell's padding covers the whole query (a query
    straddling by more than cell_padding_deg on both sides, or an index
    with no padding recorded - 0.0 for one built before this field existed)
    does this fall back to the old behavior: every cell whose *nominal*
    bounds intersect the query, unioned by the caller. Always correct
    regardless of padding, since it never depends on it.

    Empty list means "no usable index" - the index dir doesn't exist (or
    has no manifest); callers should fall back to extracting from the full
    source file in that case.
    """
    manifest = load_manifest(Path(index_dir))
    if manifest is None:
        return []
    pad = manifest.get("cell_padding_deg", 0.0)
    south, west, north, east = bbox
    if pad > 0.0:
        for cell in manifest["cells"]:
            cw, cs, ce, cn = cell["bbox"]
            if cw - pad <= west and ce + pad >= east and cs - pad <= south and cn + pad >= north:
                path = Path(index_dir) / cell["file"]
                if path.is_file():
                    return [path]
    tiles = []
    for cell in manifest["cells"]:
        cw, cs, ce, cn = cell["bbox"]
        if cw < east and ce > west and cs < north and cn > south:
            path = Path(index_dir) / cell["file"]
            if path.is_file():
                tiles.append(path)
    return tiles


def _selftest() -> None:
    """Pure-python check of the grid math and lookup, no osmium/network
    needed. Run with `python -m theroadragetrip.utils.pbf_index --selftest`."""
    assert _cell(25.3, 64.1, 0.25) == (101, 256)
    assert _cell_bounds(101, 256, 0.25) == (25.25, 64.0, 25.5, 64.25)

    with tempfile.TemporaryDirectory() as d:
        index_dir = Path(d)
        manifest = {
            "source": {"path": "x", "size": 1, "mtime": 1.0},
            "grid_size_deg": 0.25,
            "strategy": "smart",
            "cells": [
                {"gx": 0, "gy": 0, "bbox": [25.0, 64.0, 25.25, 64.25], "file": "a.pbf"},
                {"gx": 1, "gy": 0, "bbox": [25.25, 64.0, 25.5, 64.25], "file": "b.pbf"},
            ],
        }
        (index_dir / MANIFEST_NAME).write_text(json.dumps(manifest))
        (index_dir / "a.pbf").write_bytes(b"")
        (index_dir / "b.pbf").write_bytes(b"")

        assert [p.name for p in tiles_for_bbox(index_dir, (64.05, 25.05, 64.1, 25.1))] == ["a.pbf"]
        got = sorted(p.name for p in tiles_for_bbox(index_dir, (64.05, 25.2, 64.1, 25.3)))
        assert got == ["a.pbf", "b.pbf"]
        assert tiles_for_bbox(index_dir / "nope", (0, 0, 1, 1)) == []

    print("pbf_index selftest OK")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build a grid index for a local .osm.pbf file")
    parser.add_argument("pbf_path", nargs="?", type=Path, help="Source .osm.pbf to index")
    parser.add_argument("--index-dir", type=Path, default=None, help="Default: <pbf_path>.index next to the source")
    parser.add_argument("--grid-deg", type=float, default=DEFAULT_GRID_SIZE_DEG)
    parser.add_argument("--strategy", default=DEFAULT_STRATEGY)
    parser.add_argument("--force", action="store_true", help="Rebuild even if an up-to-date index exists")
    parser.add_argument("--selftest", action="store_true", help="Run the offline self-check and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.selftest:
        _selftest()
    elif args.pbf_path:
        out = build_index(
            args.pbf_path, index_dir=args.index_dir, grid_size_deg=args.grid_deg,
            strategy=args.strategy, force=args.force,
            progress_callback=lambda frac, msg: print(f"[{frac:.0%}] {msg}"),
        )
        print(f"Index ready: {out}")
    else:
        parser.error("pbf_path is required unless --selftest is given")
