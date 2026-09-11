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
