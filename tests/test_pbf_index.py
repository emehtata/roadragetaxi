"""Tests for the .osm.pbf grid index (src/theroadragetrip/utils/pbf_index.py)."""
import shutil
import subprocess

import pytest

from theroadragetrip.utils.pbf_index import (
    _cell,
    _cell_bounds,
    build_index,
    index_is_stale,
    tiles_for_bbox,
)


def test_cell_math():
    assert _cell(25.3, 64.1, 0.25) == (101, 256)
    assert _cell_bounds(101, 256, 0.25) == (25.25, 64.0, 25.5, 64.25)


def test_tiles_for_bbox_overlap_and_missing_index(tmp_path):
    """Straddling a cell boundary must return every overlapping cell (the
    caller merges/dedupes); a missing index must return [] rather than
    raising, so callers can fall back to the full source file."""
    import json

    index_dir = tmp_path / "index"
    index_dir.mkdir()
    manifest = {
        "source": {"path": "x", "size": 1, "mtime": 1.0},
        "grid_size_deg": 0.25,
        "strategy": "smart",
        "cells": [
            {"gx": 0, "gy": 0, "bbox": [25.0, 64.0, 25.25, 64.25], "file": "a.pbf"},
            {"gx": 1, "gy": 0, "bbox": [25.25, 64.0, 25.5, 64.25], "file": "b.pbf"},
        ],
    }
    (index_dir / "manifest.json").write_text(json.dumps(manifest))
    (index_dir / "a.pbf").write_bytes(b"")
    (index_dir / "b.pbf").write_bytes(b"")

    assert [p.name for p in tiles_for_bbox(index_dir, (64.05, 25.05, 64.1, 25.1))] == ["a.pbf"]
    straddling = sorted(p.name for p in tiles_for_bbox(index_dir, (64.05, 25.2, 64.1, 25.3)))
    assert straddling == ["a.pbf", "b.pbf"]
    assert tiles_for_bbox(tmp_path / "no-such-index", (0, 0, 1, 1)) == []


def test_tiles_for_bbox_uses_cell_padding_to_avoid_the_neighbor(tmp_path):
    """Regression: a query that only slightly crosses a grid line (Oulu's
    map center sits 0.012deg above the lat=65.0 line - see
    DEFAULT_CELL_PADDING_DEG's docstring) used to always need *both*
    neighboring cells' files, doubling extraction cost for every such
    query. With cell_padding_deg recorded (a cell's file was cut with that
    much extra margin - see build_index), a query that pokes over the line
    by less than the padding must resolve to the single cell whose padded
    data already covers it; poking over by more than the padding must still
    correctly fall back to both (padding narrows the common case, never
    drops real coverage)."""
    import json

    index_dir = tmp_path / "index"
    index_dir.mkdir()
    manifest = {
        "source": {"path": "x", "size": 1, "mtime": 1.0},
        "grid_size_deg": 1.0,
        "strategy": "smart",
        "cell_padding_deg": 0.05,
        "cells": [
            {"gx": 25, "gy": 64, "bbox": [25.0, 64.0, 26.0, 65.0], "file": "tile_25_64.osm.pbf"},
            {"gx": 25, "gy": 65, "bbox": [25.0, 65.0, 26.0, 66.0], "file": "tile_25_65.osm.pbf"},
        ],
    }
    (index_dir / "manifest.json").write_text(json.dumps(manifest))
    (index_dir / "tile_25_64.osm.pbf").write_bytes(b"")
    (index_dir / "tile_25_65.osm.pbf").write_bytes(b"")

    # Pokes 0.012deg over the 65.0 line - well inside the 0.05deg padding.
    just_over = tiles_for_bbox(index_dir, (64.99, 25.4, 65.012, 25.5))
    assert [p.name for p in just_over] == ["tile_25_64.osm.pbf"]

    # Spans 0.10deg on *each* side of the line - past what either cell's
    # own 0.05deg padding alone can cover, genuinely needs both.
    far_over = sorted(p.name for p in tiles_for_bbox(index_dir, (64.90, 25.4, 65.10, 25.5)))
    assert far_over == ["tile_25_64.osm.pbf", "tile_25_65.osm.pbf"]

    # An index built before cell_padding_deg existed (key absent) must fall
    # back to the old, unpadded (0.0) overlap test exactly.
    del manifest["cell_padding_deg"]
    (index_dir / "manifest.json").write_text(json.dumps(manifest))
    unpadded = sorted(p.name for p in tiles_for_bbox(index_dir, (64.99, 25.4, 65.012, 25.5)))
    assert unpadded == ["tile_25_64.osm.pbf", "tile_25_65.osm.pbf"]


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires the osmium CLI (osmium-tool)")
def test_build_index_end_to_end(tmp_path):
    """Full pipeline against a real (tiny) .osm.pbf: build a grid index,
    then confirm extracting a bbox from the one regional cell it lands in
    gives exactly the same elements as extracting straight from the
    original source - the whole point of the index existing."""
    fixture_xml = tmp_path / "fixture.osm"
    fixture_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6">
          <node id="1" lat="64.05" lon="25.05"><tag k="highway" v="traffic_signals"/></node>
          <node id="2" lat="64.06" lon="25.06"/>
          <node id="3" lat="64.4" lon="25.4"/>
          <node id="4" lat="64.41" lon="25.41"/>
          <way id="10">
            <nd ref="1"/><nd ref="2"/>
            <tag k="highway" v="primary"/>
          </way>
          <way id="20">
            <nd ref="3"/><nd ref="4"/>
            <tag k="highway" v="residential"/>
          </way>
        </osm>
        """,
        encoding="utf-8",
    )
    source_pbf = tmp_path / "fixture.osm.pbf"
    subprocess.run(["osmium", "cat", str(fixture_xml), "-o", str(source_pbf)], check=True, capture_output=True)

    index_dir = tmp_path / "index"
    build_index(source_pbf, index_dir=index_dir, grid_size_deg=0.25)
    assert not index_is_stale(source_pbf, index_dir)

    query_bbox_osmium = "25.0,64.0,25.2,64.2"  # west,south,east,north
    tiles = tiles_for_bbox(index_dir, (64.0, 25.0, 64.2, 25.2))  # south,west,north,east
    assert len(tiles) == 1

    from_full = tmp_path / "from_full.osm"
    from_tile = tmp_path / "from_tile.osm"
    subprocess.run(
        ["osmium", "extract", "--bbox", query_bbox_osmium, "-s", "smart", "-f", "osm", "-O", "-o", str(from_full), str(source_pbf)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["osmium", "extract", "--bbox", query_bbox_osmium, "-s", "smart", "-f", "osm", "-O", "-o", str(from_tile), str(tiles[0])],
        check=True, capture_output=True,
    )
    assert from_full.read_text() == from_tile.read_text()


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires the osmium CLI (osmium-tool)")
def test_build_index_cuts_each_cell_with_extra_padding_margin(tmp_path):
    """Regression: a cell file must contain data up to cell_padding_deg
    past its own nominal grid bounds, not just exactly its nominal bounds -
    that's what lets tiles_for_bbox answer a slightly-over-the-line query
    from one cell instead of two (see that test). A node placed just past
    cell (100,256)'s nominal east edge (25.25), but within a 0.05deg
    padding, must still show up in that cell's own file."""
    fixture_xml = tmp_path / "fixture.osm"
    fixture_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6">
          <node id="1" lat="64.1" lon="25.05"/>
          <node id="2" lat="64.1" lon="25.27"/>
        </osm>
        """,
        encoding="utf-8",
    )
    source_pbf = tmp_path / "fixture.osm.pbf"
    subprocess.run(["osmium", "cat", str(fixture_xml), "-o", str(source_pbf)], check=True, capture_output=True)

    index_dir = tmp_path / "index"
    build_index(source_pbf, index_dir=index_dir, grid_size_deg=0.25, cell_padding_deg=0.05)

    # Node 2 (lon 25.27) sits just past cell (100,256)'s nominal east edge
    # (25.25) - its *nominal* owner is cell (101,256) - but 0.05deg padding
    # should still have pulled it into (100,256)'s own file.
    cell_a = index_dir / "tile_100_256.osm.pbf"
    assert cell_a.is_file()
    dump = subprocess.run(
        ["osmium", "cat", str(cell_a), "-f", "opl", "-o", "-"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "n2 " in dump, f"padded cell should contain node 2 (lon 25.27, within padding): {dump!r}"


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires the osmium CLI (osmium-tool)")
def test_build_index_rebuilds_from_scratch_when_padding_changes(tmp_path):
    """Regression: an index built with one cell_padding_deg must not be
    silently reused (nor merely resumed cell-by-cell) when called again
    with a different one - those on-disk cell files were cut with the old
    margin and don't match what the new parameter promises. Checked via
    mtime: every cell must be regenerated, not left untouched the way a
    same-parameters resume leaves survivors alone (see
    test_build_index_is_resumable)."""
    fixture_xml = tmp_path / "fixture.osm"
    fixture_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6">
          <node id="1" lat="64.1" lon="25.05"/>
        </osm>
        """,
        encoding="utf-8",
    )
    source_pbf = tmp_path / "fixture.osm.pbf"
    subprocess.run(["osmium", "cat", str(fixture_xml), "-o", str(source_pbf)], check=True, capture_output=True)

    index_dir = tmp_path / "index"
    build_index(source_pbf, index_dir=index_dir, grid_size_deg=0.25, cell_padding_deg=0.0)
    cell_files = sorted(index_dir.glob("tile_*.osm.pbf"))
    assert cell_files
    mtimes_before = {p: p.stat().st_mtime_ns for p in cell_files}

    build_index(source_pbf, index_dir=index_dir, grid_size_deg=0.25, cell_padding_deg=0.05)

    for p, mtime in mtimes_before.items():
        assert p.stat().st_mtime_ns != mtime, f"{p.name} was reused despite cell_padding_deg changing"


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires the osmium CLI (osmium-tool)")
def test_build_index_is_resumable(tmp_path):
    """An index with some cells already on disk only (re-)builds the
    missing ones - so an interrupted build can be safely re-run."""
    fixture_xml = tmp_path / "fixture.osm"
    fixture_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6">
          <node id="1" lat="64.05" lon="25.05"/>
        </osm>
        """,
        encoding="utf-8",
    )
    source_pbf = tmp_path / "fixture.osm.pbf"
    subprocess.run(["osmium", "cat", str(fixture_xml), "-o", str(source_pbf)], check=True, capture_output=True)

    index_dir = tmp_path / "index"
    build_index(source_pbf, index_dir=index_dir, grid_size_deg=0.25)
    cell_files = sorted(index_dir.glob("tile_*.osm.pbf"))
    assert cell_files

    victim = cell_files[0]
    survivor_mtimes = {p: p.stat().st_mtime for p in cell_files[1:]}
    victim.unlink()

    build_index(source_pbf, index_dir=index_dir, grid_size_deg=0.25)

    assert victim.is_file()
    for p, mtime in survivor_mtimes.items():
        assert p.stat().st_mtime == mtime, f"{p.name} was rebuilt but shouldn't have been"
