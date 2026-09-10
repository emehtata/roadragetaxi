"""Tests for the local-.osm.pbf alternative to live Overpass fetches
(src/theroadragetrip/osm/pbf_source.py).
"""
import shutil
import subprocess

import pytest

import theroadragetrip.osm as osm
from theroadragetrip.osm.pbf_source import (
    _parse_osm_xml,
    fetch_osm_ways_from_pbf,
    local_pbf_available,
)


def test_parse_osm_xml_produces_overpass_shaped_elements(tmp_path):
    """build_ways() expects the exact same dict shapes Overpass's JSON
    uses - this is the one place that translation happens, so it must be
    exactly right: node lat/lon/tags, way nodes/tags, relation
    members/tags with each member's type/ref/role."""
    xml_path = tmp_path / "fixture.osm"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6">
          <node id="1" lat="65.0" lon="25.0">
            <tag k="highway" v="traffic_signals"/>
          </node>
          <node id="2" lat="65.001" lon="25.001"/>
          <way id="10">
            <nd ref="1"/>
            <nd ref="2"/>
            <tag k="highway" v="primary"/>
            <tag k="name" v="Testikatu"/>
          </way>
          <relation id="100">
            <member type="way" ref="10" role="outer"/>
            <tag k="type" v="multipolygon"/>
            <tag k="natural" v="water"/>
          </relation>
        </osm>
        """,
        encoding="utf-8",
    )

    elements = _parse_osm_xml(str(xml_path))

    assert elements == [
        {"type": "node", "id": 1, "lat": 65.0, "lon": 25.0, "tags": {"highway": "traffic_signals"}},
        {"type": "node", "id": 2, "lat": 65.001, "lon": 25.001, "tags": {}},
        {
            "type": "way", "id": 10, "nodes": [1, 2],
            "tags": {"highway": "primary", "name": "Testikatu"},
        },
        {
            "type": "relation", "id": 100,
            "members": [{"type": "way", "ref": 10, "role": "outer"}],
            "tags": {"type": "multipolygon", "natural": "water"},
        },
    ]


def test_local_pbf_available_requires_both_file_and_binary(tmp_path, monkeypatch):
    pbf_path = tmp_path / "finland-latest.osm.pbf"

    assert local_pbf_available(pbf_path) is False  # file missing

    pbf_path.write_bytes(b"not a real pbf, just needs to exist")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert local_pbf_available(pbf_path) is False  # osmium missing

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/osmium")
    assert local_pbf_available(pbf_path) is True


def test_fetch_from_pbf_uses_cache_and_never_shells_out(tmp_path, monkeypatch):
    """A cache hit must short-circuit before touching osmium at all - the
    whole point of sharing fetch_osm_ways()'s bbox cache is to only pay
    the extraction cost once per area."""
    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path))
    bbox = (64.0, 25.0, 64.1, 25.1)
    cached_elements = [{"type": "node", "id": 1, "lat": 64.05, "lon": 25.05, "tags": {}}]
    osm.save_osm_cache(bbox, cached_elements)

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called on a cache hit")

    monkeypatch.setattr(subprocess, "run", _boom)

    result = fetch_osm_ways_from_pbf(bbox, pbf_path=tmp_path / "unused.osm.pbf")

    assert result == cached_elements


def test_fetch_from_pbf_raises_when_pbf_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    with pytest.raises(FileNotFoundError):
        fetch_osm_ways_from_pbf((64.0, 25.0, 64.1, 25.1), pbf_path=tmp_path / "does-not-exist.osm.pbf")


def test_fetch_from_pbf_gives_an_actionable_error_when_osmium_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    pbf_path = tmp_path / "finland-latest.osm.pbf"
    pbf_path.write_bytes(b"not a real pbf, just needs to exist")
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="osmium-tool"):
        fetch_osm_ways_from_pbf((64.0, 25.0, 64.1, 25.1), pbf_path=pbf_path)


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires the osmium CLI (osmium-tool)")
def test_fetch_from_pbf_end_to_end_with_a_real_extract(tmp_path, monkeypatch):
    """Full pipeline against a real (tiny) .osm.pbf file, produced by
    osmium itself from a hand-written fixture - exercises the actual
    subprocess call and XML parsing together, not just each in isolation."""
    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    fixture_xml = tmp_path / "fixture.osm"
    fixture_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6">
          <node id="1" lat="65.0" lon="25.0">
            <tag k="highway" v="traffic_signals"/>
          </node>
          <node id="2" lat="65.001" lon="25.001"/>
          <way id="10">
            <nd ref="1"/>
            <nd ref="2"/>
            <tag k="highway" v="primary"/>
          </way>
        </osm>
        """,
        encoding="utf-8",
    )
    fixture_pbf = tmp_path / "fixture.osm.pbf"
    subprocess.run(
        ["osmium", "cat", str(fixture_xml), "-o", str(fixture_pbf)],
        check=True, capture_output=True,
    )

    elements = fetch_osm_ways_from_pbf((64.9, 24.9, 65.1, 25.1), pbf_path=fixture_pbf)

    by_id = {(el["type"], el["id"]): el for el in elements}
    assert by_id[("node", 1)]["tags"] == {"highway": "traffic_signals"}
    assert by_id[("way", 10)]["nodes"] == [1, 2]


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires the osmium CLI (osmium-tool)")
def test_fetch_from_pbf_uses_the_grid_index_when_present(tmp_path, monkeypatch):
    """With a grid index built next to the source file (utils/pbf_index.py),
    extraction must read the small regional cell(s) instead of the full
    source file - and still return the same elements a full-file extract
    would."""
    from theroadragetrip.utils.pbf_index import build_index, default_index_dir

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    fixture_xml = tmp_path / "fixture.osm"
    fixture_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6">
          <node id="1" lat="65.0" lon="25.0">
            <tag k="highway" v="traffic_signals"/>
          </node>
          <node id="2" lat="65.001" lon="25.001"/>
          <way id="10">
            <nd ref="1"/>
            <nd ref="2"/>
            <tag k="highway" v="primary"/>
          </way>
        </osm>
        """,
        encoding="utf-8",
    )
    fixture_pbf = tmp_path / "fixture.osm.pbf"
    subprocess.run(["osmium", "cat", str(fixture_xml), "-o", str(fixture_pbf)], check=True, capture_output=True)
    build_index(fixture_pbf, grid_size_deg=0.25)
    assert default_index_dir(fixture_pbf).is_dir()

    real_run = subprocess.run
    extract_sources = []

    def spy_run(cmd, *args, **kwargs):
        if cmd[:2] == ["osmium", "extract"]:
            extract_sources.append(cmd[-1])
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy_run)

    elements = fetch_osm_ways_from_pbf((64.9, 24.9, 65.1, 25.1), pbf_path=fixture_pbf)

    by_id = {(el["type"], el["id"]): el for el in elements}
    assert by_id[("node", 1)]["tags"] == {"highway": "traffic_signals"}
    assert by_id[("way", 10)]["nodes"] == [1, 2]

    assert extract_sources, "expected at least one 'osmium extract' call"
    assert all(src != str(fixture_pbf) for src in extract_sources), (
        "with an index present, extraction must read an index cell, not the full source file"
    )
