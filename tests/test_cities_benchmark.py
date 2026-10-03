import json
import shutil
import subprocess

import pytest

from tools.osm.benchmark_cities import CITIES, run_cities
from tools.osm.benchmark_oulu import bbox_for_center, measured_dimensions_km
from tools.osm.build_finland_roads import analyze_road_binary


def test_all_four_cities_are_defined():
    assert set(CITIES) == {"oulu", "helsinki", "tampere", "rovaniemi"}
    for lat, lon in CITIES.values():
        assert -90 <= lat <= 90
        assert -180 <= lon <= 180


def test_bounding_boxes_are_deterministic_and_about_20x20_km():
    for name, (lat, lon) in CITIES.items():
        first = bbox_for_center(lat, lon)
        second = bbox_for_center(lat, lon)
        assert first == second, f"{name} bbox is not deterministic"
        width_km, height_km = measured_dimensions_km(first)
        assert 18.0 <= width_km <= 22.0, f"{name} width {width_km} km out of range"
        assert 18.0 <= height_km <= 22.0, f"{name} height {height_km} km out of range"


@pytest.mark.skipif(shutil.which("osmium") is None, reason="requires osmium-tool")
def test_run_cities_processes_a_small_fixture_and_produces_all_cities(tmp_path):
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

    fixture_cities = {"fixture_a": (65.01, 25.01), "fixture_b": (65.01, 25.01)}
    work_dir = tmp_path / "work"
    json_out = tmp_path / "result.json"

    combined = run_cities(source_pbf, work_dir, json_out, cities=fixture_cities)

    assert set(combined["cities"]) == set(fixture_cities)
    for name in fixture_cities:
        city = combined["cities"][name]
        assert city["dataset"]["ways"] == 2
        assert city["dataset"]["geometry_points"] == 4
        assert city["generation"]["validation"] == "PASS"
        assert city["runtime"]["validation"] == "PASS"
        assert city["runtime"]["load_time_ms"] >= 0.0
        assert city["runtime"]["memory_expansion_ratio"] >= 0.0
        assert city["random_access"]["way_lookup_ms"] >= 0.0
        assert city["random_access"]["node_lookup_ms"] >= 0.0
        assert city["random_access"]["geometry_access_ms"] >= 0.0

    on_disk = json.loads(json_out.read_text(encoding="utf-8"))
    assert set(on_disk["cities"]) == set(fixture_cities)
    assert on_disk["finland_baseline"]["reference"]["ways"] > 0

    city_bin = work_dir / "fixture_a" / "fixture_a_20x20.bin"
    analysis = analyze_road_binary(city_bin)
    assert analysis["format_version"] == 2
    assert analysis["way_count"] == 2
