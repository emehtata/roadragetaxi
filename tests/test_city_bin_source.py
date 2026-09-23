import shutil
import subprocess
from pathlib import Path

import pytest

from theroadragetrip.osm.bin_source import (
    CityBinUnavailableError,
    city_bin_available,
    city_bin_path,
    load_city_ways,
)


def _write_fixture_bin(tmp_path) -> Path:
    source_xml = tmp_path / "source.osm"
    source_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6">
          <node id="1" lat="65.00" lon="25.00"/>
          <node id="2" lat="65.01" lon="25.01"/>
          <node id="3" lat="65.02" lon="25.02"/>
          <way id="10">
            <nd ref="1"/><nd ref="2"/>
            <tag k="highway" v="residential"/>
            <tag k="name" v="Testitie"/>
          </way>
          <way id="11">
            <nd ref="2"/><nd ref="3"/>
            <tag k="highway" v="service"/>
          </way>
        </osm>
        """,
        encoding="utf-8",
    )
    source_pbf = tmp_path / "source.osm.pbf"
    subprocess.run(["osmium", "cat", str(source_xml), "-o", str(source_pbf)], check=True)

    from tools.osm.build_finland_roads import build_finland_roads

    fixture_bin = tmp_path / "fixture.bin"
    build_finland_roads(source_pbf, fixture_bin, format_version=2)
    return fixture_bin


def test_predefined_city_with_bin_is_available_and_loads_real_binary():
    # One check against the real bundled Oulu binary, to prove genuine
    # end-to-end V2 decoding + projection against real data. Every other
    # behavioral test below uses a small synthetic fixture instead - the
    # real binary is ~87k nodes and builds an 86k-node route graph, far
    # heavier than any other fixture in this suite.
    assert city_bin_available("oulu")
    ways, nodes, geometry_points, seconds = load_city_ways("oulu")
    assert len(ways) > 0
    assert nodes > 0
    assert geometry_points >= len(ways) * 2
    assert seconds >= 0.0
    way = ways[0]
    assert way.osm_id is not None
    assert way.is_drivable is True
    assert len(way.points_m) >= 2
    assert way.bbox != (0.0, 0.0, 0.0, 0.0)


def test_city_name_matching_is_case_and_whitespace_insensitive():
    assert city_bin_path("Oulu") == city_bin_path("  OULU  ") == city_bin_path("oulu")
    assert city_bin_available("Oulu")
    assert city_bin_available("  oUlU  ")


def test_predefined_city_without_bin_is_unavailable():
    # No "espoo.bin" exists in assets/roads/ - a predefined catalog city
    # with no prebuilt binary must be reported unavailable, not crash.
    assert not city_bin_available("espoo")
    with pytest.raises(CityBinUnavailableError):
        load_city_ways("espoo")


def test_custom_city_gets_no_bin_lookup_or_substitution():
    # An arbitrary/custom city name never has a bundled binary and must
    # never be silently mapped onto an existing city's file.
    assert not city_bin_available("MyCustomCity")
    assert city_bin_path("MyCustomCity") != city_bin_path("oulu")


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires osmium-tool")
def test_broken_bin_falls_back_instead_of_crashing(tmp_path):
    broken = tmp_path / "broken.bin"
    broken.write_bytes(b"not a real V2 road binary")
    with pytest.raises(CityBinUnavailableError):
        load_city_ways("oulu", bin_path=broken)


def test_missing_bin_path_falls_back(tmp_path):
    with pytest.raises(CityBinUnavailableError):
        load_city_ways("oulu", bin_path=tmp_path / "does_not_exist.bin")


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires osmium-tool")
def test_city_switching_gives_independent_uncached_results(tmp_path):
    # bin_source.py keeps no module-level cache, so loading a city, then
    # a different one, then the first one again must each return that
    # binary's own data - no stale ways left over from a previous load.
    fixture_bin = _write_fixture_bin(tmp_path)
    ways_first, nodes_first, _, _ = load_city_ways("fixture", bin_path=fixture_bin)
    other_ways, other_nodes, _, _ = load_city_ways("oulu")
    ways_again, nodes_again, _, _ = load_city_ways("fixture", bin_path=fixture_bin)

    assert len(ways_first) == len(ways_again) == 2
    assert nodes_first == nodes_again
    assert len(ways_first) != len(other_ways)
    assert {way.osm_id for way in ways_first} == {way.osm_id for way in ways_again}
