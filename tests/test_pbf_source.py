"""Tests for the local-.osm.pbf alternative to live Overpass fetches
(src/theroadragetrip/osm/pbf_source.py).
"""
import shutil
import subprocess

import pytest

import theroadragetrip.osm as osm
from theroadragetrip.osm.pbf_source import (
    PbfUnavailable,
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
    with pytest.raises(PbfUnavailable, match="not found") as error:
        fetch_osm_ways_from_pbf((64.0, 25.0, 64.1, 25.1), pbf_path=tmp_path / "does-not-exist.osm.pbf")
    assert error.value.reason == "pbf_missing"


def test_fetch_from_pbf_raises_cleanly_when_osmium_extract_hangs(tmp_path, monkeypatch):
    """Regression: _extract_elements's subprocess.run() used to have no
    timeout at all, so a stuck/hung osmium process blocked forever -
    _wait_for_active_tile_fetch (main.py) only waits as long as the fetch
    itself takes and relies on it to eventually give up, which was true for
    Overpass's requests.post(timeout=60) but not for this subprocess call."""
    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    pbf_path = tmp_path / "finland-latest.osm.pbf"
    pbf_path.write_bytes(b"not a real pbf, just needs to exist")

    def _hangs(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", _hangs)
    # osmium is found (it hangs, not missing) whether or not this machine has it
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    with pytest.raises(RuntimeError, match="timed out"):
        fetch_osm_ways_from_pbf((64.0, 25.0, 64.1, 25.1), pbf_path=pbf_path)


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


def _pbf_fetch_with_fake_overpass(monkeypatch, pbf_path):
    from types import SimpleNamespace

    from theroadragetrip import world_loader
    from theroadragetrip.osm import pbf_source

    pbf_source.pbf_fallback_notices.clear()  # session state: start each test clean
    overpass_calls = []
    monkeypatch.setattr(world_loader, "fetch_osm_ways",
                        lambda bbox, **kwargs: overpass_calls.append(bbox) or [{"type": "node", "id": 1}])
    args = SimpleNamespace(osm_source="pbf", osm_pbf_path=str(pbf_path))
    return world_loader.resolve_osm_fetch_func(args, ["https://overpass.example/api"]), overpass_calls


def test_pbf_osmium_missing_falls_back_with_notice(tmp_path, monkeypatch):
    from theroadragetrip.osm import pbf_source
    from theroadragetrip.protocol import data_source_notice

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    pbf_path = tmp_path / "finland-latest.osm.pbf"
    pbf_path.write_bytes(b"not a real pbf, just needs to exist")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    fetch, overpass_calls = _pbf_fetch_with_fake_overpass(monkeypatch, pbf_path)

    elements = fetch((64.0, 25.0, 64.1, 25.1))

    assert overpass_calls == [(64.0, 25.0, 64.1, 25.1)]
    assert elements[0] == {"type": "node", "id": 1}
    assert list(pbf_source.pbf_fallback_notices) == ["osmium_missing"]
    assert "osmium-tool" in data_source_notice("en")


def test_pbf_file_missing_falls_back_with_path_in_notice(tmp_path, monkeypatch):
    from theroadragetrip.osm import pbf_source
    from theroadragetrip.protocol import data_source_notice

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    pbf_path = tmp_path / "does-not-exist.osm.pbf"
    fetch, overpass_calls = _pbf_fetch_with_fake_overpass(monkeypatch, pbf_path)

    fetch((64.0, 25.0, 64.1, 25.1))

    assert len(overpass_calls) == 1
    assert list(pbf_source.pbf_fallback_notices) == ["pbf_missing"]
    for language in ("fi", "en", "de"):
        assert str(pbf_path) in data_source_notice(language)
        assert f"{pbf_path.name} " in data_source_notice(language)
        assert f" {tmp_path}," in data_source_notice(language), "names the folder to put the file in"


def test_pbf_osmium_failure_falls_back(tmp_path, monkeypatch):
    from theroadragetrip.osm import pbf_source
    from theroadragetrip.protocol import data_source_notice

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    pbf_path = tmp_path / "finland-latest.osm.pbf"
    pbf_path.write_bytes(b"not a real pbf, just needs to exist")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(pbf_source, "_cut_index_cells_later", lambda *a: None)

    def _fails(source, bbox):
        raise RuntimeError("osmium extract failed (exit 1): PBF error: invalid BlobHeader")

    monkeypatch.setattr(pbf_source, "_extract_elements", _fails)
    fetch, overpass_calls = _pbf_fetch_with_fake_overpass(monkeypatch, pbf_path)

    fetch((64.0, 25.0, 64.1, 25.1))

    assert len(overpass_calls) == 1
    assert list(pbf_source.pbf_fallback_notices) == ["osmium_failed"]
    assert "invalid BlobHeader" in data_source_notice("en")


def test_pbf_fallback_notice_emitted_once(tmp_path, monkeypatch):
    from theroadragetrip.osm import pbf_source

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    fetch, overpass_calls = _pbf_fetch_with_fake_overpass(monkeypatch, tmp_path / "missing.osm.pbf")
    fetch((64.0, 25.0, 64.1, 25.1))
    notices = dict(pbf_source.pbf_fallback_notices)
    fetch((64.1, 25.1, 64.2, 25.2))

    assert len(overpass_calls) == 2
    assert pbf_source.pbf_fallback_notices == notices and len(notices) == 1


def test_osm_source_overpass_records_no_notice(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from theroadragetrip import world_loader
    from theroadragetrip.osm import pbf_source

    pbf_source.pbf_fallback_notices.clear()  # session state: start each test clean
    monkeypatch.setattr(world_loader, "fetch_osm_ways", lambda bbox, **kwargs: [])
    fetch = world_loader.resolve_osm_fetch_func(SimpleNamespace(osm_source="overpass"), ["x"])
    fetch((64.0, 25.0, 64.1, 25.1))
    assert pbf_source.pbf_fallback_notices == {}


def test_pbf_osmium_timeout_falls_back(tmp_path, monkeypatch):
    from theroadragetrip.osm import pbf_source
    from theroadragetrip.protocol import data_source_notice

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    pbf_path = tmp_path / "finland-latest.osm.pbf"
    pbf_path.write_bytes(b"not a real pbf, just needs to exist")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(pbf_source, "_cut_index_cells_later", lambda *a: None)

    def _hangs(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", _hangs)
    fetch, overpass_calls = _pbf_fetch_with_fake_overpass(monkeypatch, pbf_path)

    fetch((64.0, 25.0, 64.1, 25.1))

    assert len(overpass_calls) == 1
    assert list(pbf_source.pbf_fallback_notices) == ["osmium_failed"]
    assert "timed out" in data_source_notice("en")


def _pbf_with_fake_osmium(tmp_path, monkeypatch):
    from theroadragetrip.osm import pbf_source

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    pbf_path = tmp_path / "finland-latest.osm.pbf"
    pbf_path.write_bytes(b"not a real pbf, just needs to exist")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(pbf_source, "_cut_index_cells_later", lambda *a: None)
    return pbf_path


def test_oserror_from_osmium_falls_back(tmp_path, monkeypatch):
    from theroadragetrip.osm import pbf_source
    from theroadragetrip.protocol import data_source_notice

    pbf_path = _pbf_with_fake_osmium(tmp_path, monkeypatch)

    def _vanished(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "osmium")

    monkeypatch.setattr(subprocess, "run", _vanished)
    with pytest.raises(PbfUnavailable) as exc_info:
        fetch_osm_ways_from_pbf((64.0, 25.0, 64.1, 25.1), pbf_path=pbf_path)
    assert exc_info.value.reason == "osmium_failed"

    fetch, overpass_calls = _pbf_fetch_with_fake_overpass(monkeypatch, pbf_path)
    fetch((64.0, 25.0, 64.1, 25.1))
    assert len(overpass_calls) == 1
    assert list(pbf_source.pbf_fallback_notices) == ["osmium_failed"]
    assert data_source_notice("en")


def test_truncated_osm_xml_falls_back(tmp_path, monkeypatch):
    from pathlib import Path

    pbf_path = _pbf_with_fake_osmium(tmp_path, monkeypatch)
    out_dirs = []

    def _killed_mid_write(cmd, **kwargs):
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_text("<osm><node", encoding="utf-8")
        out_dirs.append(out.parent)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _killed_mid_write)
    with pytest.raises(PbfUnavailable) as exc_info:
        fetch_osm_ways_from_pbf((64.0, 25.0, 64.1, 25.1), pbf_path=pbf_path)
    assert exc_info.value.reason == "osmium_failed"
    assert out_dirs and not out_dirs[0].exists(), "the extract tmpdir is removed"


def test_sigkilled_osmium_reports_exit_code(tmp_path, monkeypatch):
    from pathlib import Path

    pbf_path = _pbf_with_fake_osmium(tmp_path, monkeypatch)

    def _oom_killed(cmd, **kwargs):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"")
        return subprocess.CompletedProcess(cmd, -9, "", "")

    monkeypatch.setattr(subprocess, "run", _oom_killed)
    with pytest.raises(PbfUnavailable) as exc_info:
        fetch_osm_ways_from_pbf((64.0, 25.0, 64.1, 25.1), pbf_path=pbf_path)
    assert exc_info.value.reason == "osmium_failed"
    assert "exit -9" in exc_info.value.detail


def test_cell_cut_deferred_during_foreground_extract(tmp_path, monkeypatch):
    import threading
    import time

    from theroadragetrip.osm import pbf_source

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path / "cache"))
    pbf_path = tmp_path / "finland-latest.osm.pbf"
    pbf_path.write_bytes(b"not a real pbf, just needs to exist")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    events = []
    cut_done = threading.Event()

    def _cut(path, bbox):
        events.append("cut")
        cut_done.set()
        return 1

    def _extract(source, bbox):
        events.append("extract_start")
        pbf_source._cut_index_cells_later(pbf_path, bbox)  # a concurrent fetch asks too
        time.sleep(0.2)  # give a wrongly started cut thread time to run
        events.append("extract_end")
        return [{"type": "node", "id": 1, "lat": 64.05, "lon": 25.05, "tags": {}}]

    monkeypatch.setattr(pbf_source, "build_cells_for", _cut)
    monkeypatch.setattr(pbf_source, "_extract_elements", _extract)

    fetch_osm_ways_from_pbf((64.0, 25.0, 64.1, 25.1), pbf_path=pbf_path)

    assert cut_done.wait(5), "the cut is retried once the foreground extract is done"
    for _ in range(100):
        if not pbf_source._cell_builder_busy:
            break
        time.sleep(0.01)
    assert events == ["extract_start", "extract_end", "cut"]
