#!/usr/bin/env python3
"""Benchmark: Oulu 20x20 km V2 road dataset carved from the Finland PBF.

Clips the Finland source PBF to a ~20x20 km box around Oulu with
`osmium extract` (default "complete_ways" strategy: a way is kept in full,
with every one of its nodes, if ANY of its nodes falls inside the box --
geometry is never truncated at the boundary), builds a V2 binary with the
existing generator, and runs the existing v2 runtime loader benchmark
against it. This script adds only the geographic clip and the Oulu-vs-
Finland report; build_finland_roads.py and benchmark_finland_roads.py are
reused unmodified. Not integrated into the game.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Mapping

try:
    from tools.osm.build_finland_roads import (
        V2_FORMAT_VERSION,
        _haversine_m,
        build_finland_roads,
        encode_coordinate,
        load_road_dataset,
    )
    from tools.osm.benchmark_finland_roads import (
        REFERENCE as FINLAND_REFERENCE,
        _elapsed_ms,
        _format_bytes,
        benchmark_dataset,
    )
except ModuleNotFoundError:  # Direct: python tools/osm/benchmark_oulu.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_finland_roads import (
        V2_FORMAT_VERSION,
        _haversine_m,
        build_finland_roads,
        encode_coordinate,
        load_road_dataset,
    )
    from benchmark_finland_roads import (
        REFERENCE as FINLAND_REFERENCE,
        _elapsed_ms,
        _format_bytes,
        benchmark_dataset,
    )


# Oulu city center.
CENTER_LAT = 65.0121
CENTER_LON = 25.4651
TARGET_KM = 20.0

# Already-measured Finland v2 baseline from tools/osm/README.md, not re-run
# here: loading it needs ~2.7 GiB RSS, more than this machine currently has
# free, and it was already validated in a prior benchmark run.
FINLAND_DOCUMENTED = {
    "file_size_mib": 129.54,
    "load_time_s": 32.266,
    "warm_load_time_s": 33.608,
    "additional_rss_gib": 2.56,
    "peak_rss_gib": 2.71,
    "memory_expansion_ratio": 20.24,
    "random_way_lookup_ms": "10.7-15.4",
    "random_node_lookup_ms": "8.8-16.4",
    "geometry_access_ms": "52.0-66.5",
}


def _meters_per_degree(lat_deg: float) -> tuple[float, float]:
    """WGS84 meters per degree of latitude/longitude at the given latitude."""
    phi = math.radians(lat_deg)
    m_lat = 111_132.92 - 559.82 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi) - 0.0023 * math.cos(6 * phi)
    m_lon = 111_412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi) + 0.118 * math.cos(5 * phi)
    return m_lat, m_lon


def bbox_for_center(center_lat: float, center_lon: float, target_km: float = TARGET_KM) -> dict[str, float]:
    m_lat, m_lon = _meters_per_degree(center_lat)
    half_m = target_km * 1000.0 / 2.0
    dlat, dlon = half_m / m_lat, half_m / m_lon
    return {
        "min_lat": center_lat - dlat,
        "max_lat": center_lat + dlat,
        "min_lon": center_lon - dlon,
        "max_lon": center_lon + dlon,
    }


def oulu_bbox() -> dict[str, float]:
    return bbox_for_center(CENTER_LAT, CENTER_LON)


def measured_dimensions_km(bbox: Mapping[str, float]) -> tuple[float, float]:
    """Actual width/height of the bbox via the existing haversine helper."""
    mid_lat, mid_lon = (bbox["min_lat"] + bbox["max_lat"]) / 2.0, (bbox["min_lon"] + bbox["max_lon"]) / 2.0
    west = (encode_coordinate(mid_lat), encode_coordinate(bbox["min_lon"]))
    east = (encode_coordinate(mid_lat), encode_coordinate(bbox["max_lon"]))
    south = (encode_coordinate(bbox["min_lat"]), encode_coordinate(mid_lon))
    north = (encode_coordinate(bbox["max_lat"]), encode_coordinate(mid_lon))
    return _haversine_m(west, east) / 1000.0, _haversine_m(south, north) / 1000.0


def extract_city_pbf(input_pbf: Path, output_pbf: Path, bbox: Mapping[str, float]) -> None:
    bbox_arg = f"{bbox['min_lon']},{bbox['min_lat']},{bbox['max_lon']},{bbox['max_lat']}"
    subprocess.run(
        [
            "osmium", "extract", "--bbox", bbox_arg, "-s", "complete_ways",
            "-O", "-o", str(output_pbf), str(input_pbf),
        ],
        check=True,
    )


WAY_INCLUSION_STRATEGY = (
    "osmium extract complete_ways (whole way + all nodes kept if any node is inside the box)"
)


def build_city_dataset(city_name: str, center: tuple[float, float], input_pbf: Path, work_dir: Path) -> dict:
    """Clip, build and runtime-benchmark one city's V2 binary. Shared by
    benchmark_oulu.py and benchmark_cities.py so the pipeline exists once."""
    work_dir.mkdir(parents=True, exist_ok=True)
    bbox = bbox_for_center(*center)
    width_km, height_km = measured_dimensions_km(bbox)

    clipped_pbf = work_dir / f"{city_name}_20x20.osm.pbf"
    extract_ms, _ = _elapsed_ms(lambda: extract_city_pbf(input_pbf, clipped_pbf, bbox))

    city_bin = work_dir / f"{city_name}_20x20.bin"
    generation = build_finland_roads(clipped_pbf, city_bin, format_version=V2_FORMAT_VERSION)

    first_load = benchmark_dataset(city_bin, expected=None, sample_sizes=(1000, 10_000))
    warm_ms, _ = _elapsed_ms(lambda: load_road_dataset(city_bin))

    return {
        "city": city_name,
        "center": {"lat": center[0], "lon": center[1]},
        "bbox": bbox,
        "dimensions": {"width_km": width_km, "height_km": height_km, "area_km2": width_km * height_km},
        "way_inclusion_strategy": WAY_INCLUSION_STRATEGY,
        "input_pbf_bytes": input_pbf.stat().st_size,
        "clipped_pbf_bytes": clipped_pbf.stat().st_size,
        "extraction_time_ms": extract_ms,
        "file_size_bytes": city_bin.stat().st_size,
        "dataset": {
            "ways": generation["drivable_ways"],
            "nodes": generation["stored_nodes"],
            "geometry_points": generation["geometry_points"],
            "road_length_km": generation["road_length_m"] / 1000.0,
            "highway_types": generation["highway_types"],
        },
        "generation": {
            "time_ms": generation["processing_seconds"] * 1000.0,
            "peak_rss_bytes": generation["peak_memory_bytes"],
            "validation": generation["validation"],
        },
        "runtime": {
            "load_time_ms": first_load["total_load_time_ms"],
            "warm_load_time_ms": warm_ms,
            "baseline_rss_bytes": first_load["baseline_rss_bytes"],
            "loaded_rss_bytes": first_load["loaded_rss_bytes"],
            "additional_rss_bytes": first_load["rss_increase_bytes"],
            "peak_rss_bytes": first_load["peak_rss_bytes"],
            "memory_expansion_ratio": first_load["memory_expansion_ratio"],
            "validation": first_load["validation"],
        },
        "random_access": {
            "way_lookup_ms": first_load["random_way_lookup_ms"],
            "node_lookup_ms": first_load["random_node_lookup_ms"],
            "geometry_access_ms": first_load["geometry_access_ms"],
        },
    }


def _flatten_oulu_result(data: dict) -> dict:
    """Reshape build_city_dataset()'s nested result into the original flat
    Oulu JSON schema, so `benchmark_oulu.py --json` stays backward compatible."""
    return {
        "area_name": "Oulu 20x20 km",
        **data["bbox"],
        **data["dimensions"],
        "way_inclusion_strategy": data["way_inclusion_strategy"],
        "input_pbf_bytes": data["input_pbf_bytes"],
        "clipped_pbf_bytes": data["clipped_pbf_bytes"],
        "extraction_time_ms": data["extraction_time_ms"],
        "file_size_bytes": data["file_size_bytes"],
        "ways": data["dataset"]["ways"],
        "nodes": data["dataset"]["nodes"],
        "geometry_points": data["dataset"]["geometry_points"],
        "road_length_km": data["dataset"]["road_length_km"],
        "highway_types": data["dataset"]["highway_types"],
        "generation_time_ms": data["generation"]["time_ms"],
        "generation_peak_rss_bytes": data["generation"]["peak_rss_bytes"],
        "generation_validation": data["generation"]["validation"],
        "load_time_ms": data["runtime"]["load_time_ms"],
        "warm_load_time_ms": data["runtime"]["warm_load_time_ms"],
        "baseline_rss_bytes": data["runtime"]["baseline_rss_bytes"],
        "loaded_rss_bytes": data["runtime"]["loaded_rss_bytes"],
        "additional_rss_bytes": data["runtime"]["additional_rss_bytes"],
        "peak_rss_bytes": data["runtime"]["peak_rss_bytes"],
        "memory_expansion_ratio": data["runtime"]["memory_expansion_ratio"],
        "random_way_lookup_ms": data["random_access"]["way_lookup_ms"],
        "random_node_lookup_ms": data["random_access"]["node_lookup_ms"],
        "geometry_access_ms": data["random_access"]["geometry_access_ms"],
        "load_validation": data["runtime"]["validation"],
        "finland_comparison_source": "tools/osm/README.md documented Finland v2 benchmark (not re-run)",
    }


def run(input_pbf: Path, work_dir: Path, json_out: Path | None) -> dict:
    data = build_city_dataset("oulu", (CENTER_LAT, CENTER_LON), input_pbf, work_dir)
    result = _flatten_oulu_result(data)

    print("Oulu benchmark area:")
    print(f"  min_lat: {result['min_lat']:.6f}")
    print(f"  max_lat: {result['max_lat']:.6f}")
    print(f"  min_lon: {result['min_lon']:.6f}")
    print(f"  max_lon: {result['max_lon']:.6f}")
    print(f"Width:  ~{result['width_km']:.1f} km")
    print(f"Height: ~{result['height_km']:.1f} km")
    print(f"Area:   ~{result['area_km2']:.0f} km2")
    print(
        "Way inclusion: osmium extract's default 'complete_ways' strategy -- "
        "a way is kept in FULL, with every one of its nodes (even nodes far "
        "outside the box), if ANY single node of that way falls inside the "
        "box. Geometry is never clipped or truncated at the boundary."
    )

    generation = {
        "processing_seconds": result["generation_time_ms"] / 1000.0,
        "peak_memory_bytes": result["generation_peak_rss_bytes"],
        "validation": result["generation_validation"],
    }

    print()
    print(f"=== Oulu 20x20 km Dataset ===")
    print(f"Input PBF (clipped): {_format_bytes(result['clipped_pbf_bytes'])}")
    print(f"Output: {_format_bytes(result['file_size_bytes'])}")
    print(f"Ways: {result['ways']:,}")
    print(f"Nodes: {result['nodes']:,}")
    print(f"Geometry points: {result['geometry_points']:,}")
    print(f"Road length: {result['road_length_km']:,.3f} km")
    print("Highway breakdown:")
    for highway, count in result["highway_types"].items():
        if count:
            print(f"  {highway}: {count:,}")
    print(f"Processing time: {generation['processing_seconds']:.3f} s")
    print(f"Peak Python memory: {_format_bytes(generation['peak_memory_bytes'])}")
    print(f"Validation: {generation['validation']}")

    print()
    print("Oulu contains (share of Finland v2):")
    print(f"  {result['ways'] / FINLAND_REFERENCE['ways'] * 100:.3f}% of Finland's ways")
    print(f"  {result['nodes'] / FINLAND_REFERENCE['nodes'] * 100:.3f}% of Finland's nodes")
    print(f"  {result['geometry_points'] / FINLAND_REFERENCE['geometry_points'] * 100:.3f}% of Finland's geometry points")
    print(f"  {result['road_length_km'] / FINLAND_REFERENCE['road_length_km'] * 100:.3f}% of Finland's road length")
    finland_size_bytes = FINLAND_DOCUMENTED["file_size_mib"] * 1024 * 1024
    print(f"  {result['file_size_bytes'] / finland_size_bytes * 100:.3f}% of Finland's v2 binary size")

    print()
    print("=" * 60)
    print("Finland vs Oulu 20x20 km")
    print("=" * 60)
    print(f"{'Metric':<22} {'Finland':<16} {'Oulu'}")
    print("-" * 60)
    print(f"{'Binary size':<22} {FINLAND_DOCUMENTED['file_size_mib']:.2f} MiB{'':<7} {_format_bytes(result['file_size_bytes'])}")
    print(f"{'Ways':<22} {FINLAND_REFERENCE['ways']:<16,} {result['ways']:,}")
    print(f"{'Nodes':<22} {FINLAND_REFERENCE['nodes']:<16,} {result['nodes']:,}")
    print(f"{'Geometry points':<22} {FINLAND_REFERENCE['geometry_points']:<16,} {result['geometry_points']:,}")
    print(f"{'Road length (km)':<22} {FINLAND_REFERENCE['road_length_km']:<16,.3f} {result['road_length_km']:,.3f}")
    print(f"{'Load time (s)':<22} {FINLAND_DOCUMENTED['load_time_s']:<16} {result['load_time_ms'] / 1000:.3f}")
    print(f"{'Warm load time (s)':<22} {FINLAND_DOCUMENTED['warm_load_time_s']:<16} {result['warm_load_time_ms'] / 1000:.3f}")
    print(f"{'Additional RSS':<22} {FINLAND_DOCUMENTED['additional_rss_gib']:.2f} GiB{'':<8} {_format_bytes(result['additional_rss_bytes'])}")
    print(f"{'Peak RSS':<22} {FINLAND_DOCUMENTED['peak_rss_gib']:.2f} GiB{'':<8} {_format_bytes(result['peak_rss_bytes'])}")
    print(f"{'Expansion ratio':<22} {FINLAND_DOCUMENTED['memory_expansion_ratio']:.2f}x{'':<12} {result['memory_expansion_ratio']:.2f}x")
    print("-" * 60)

    print()
    print("=== Analysis ===")
    print(f"A. Oulu 20x20 km binary size: {_format_bytes(result['file_size_bytes'])}.")
    print(f"B. Additional RAM with the current Python loader: {_format_bytes(result['additional_rss_bytes'])}.")
    print(f"C. Load time: {result['load_time_ms'] / 1000:.3f} s (Finland: {FINLAND_DOCUMENTED['load_time_s']} s).")
    expansion_note = "remains" if abs(result["memory_expansion_ratio"] - FINLAND_DOCUMENTED["memory_expansion_ratio"]) < 5 else "diverges from"
    print(f"D. additional RSS / binary size = {result['memory_expansion_ratio']:.2f}x; this {expansion_note} the Finland-wide ~20x figure.")
    print(
        f"E. Random access: way lookup {result['random_way_lookup_ms']:.3f} ms, "
        f"node lookup {result['random_node_lookup_ms']:.3f} ms, "
        f"geometry access {result['geometry_access_ms']:.3f} ms for 10,000 samples "
        f"(Finland: way {FINLAND_DOCUMENTED['random_way_lookup_ms']} ms, "
        f"node {FINLAND_DOCUMENTED['random_node_lookup_ms']} ms, "
        f"geometry {FINLAND_DOCUMENTED['geometry_access_ms']} ms)."
    )
    finland_load_reduction = (1.0 - (result["load_time_ms"] / 1000.0) / FINLAND_DOCUMENTED["load_time_s"]) * 100.0
    finland_rss_reduction = (1.0 - result["additional_rss_bytes"] / (FINLAND_DOCUMENTED["additional_rss_gib"] * 1024**3)) * 100.0
    print(
        f"F. A single 20x20 km city dataset requires approximately "
        f"{_format_bytes(result['file_size_bytes'])} on disk and "
        f"{_format_bytes(result['additional_rss_bytes'])} of additional RAM with the current loader. "
        f"Loading takes approximately {result['load_time_ms'] / 1000:.3f} s. "
        f"Based on these measurements, the city dataset approach would reduce the runtime "
        f"dataset from the Finland-wide measurements by approximately "
        f"{finland_rss_reduction:.1f}% in additional RSS and {finland_load_reduction:.1f}% in load time "
        f"for this one city."
    )

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print()
        print(f"JSON result written to: {json_out}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path,
        default=Path("src/theroadragetrip/assets/osm/finland-latest.osm.pbf"),
        help="Finland source .osm.pbf",
    )
    parser.add_argument("--work-dir", type=Path, required=True, help="Directory for the clipped PBF and Oulu .bin")
    parser.add_argument("--json", type=Path, help="Optional machine-readable result path")
    args = parser.parse_args()
    try:
        run(args.input, args.work_dir, args.json)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
