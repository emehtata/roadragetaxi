#!/usr/bin/env python3
"""Benchmark: 20x20 km V2 road datasets for Oulu, Helsinki, Tampere, Rovaniemi.

Reuses benchmark_oulu.py's build_city_dataset() (bbox calculation, osmium
extract, V2 generation, and runtime load benchmark) for each city and adds
only the four-city loop, cross-city comparison table, and combined JSON.
benchmark_oulu.py is unchanged and keeps working standalone. Not integrated
into the game.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Mapping

try:
    from tools.osm.benchmark_oulu import (
        CENTER_LAT as OULU_LAT,
        CENTER_LON as OULU_LON,
        FINLAND_DOCUMENTED,
        FINLAND_REFERENCE,
        WAY_INCLUSION_STRATEGY,
        build_city_dataset,
    )
    from tools.osm.benchmark_finland_roads import _format_bytes
except ModuleNotFoundError:  # Direct: python tools/osm/benchmark_cities.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from benchmark_oulu import (
        CENTER_LAT as OULU_LAT,
        CENTER_LON as OULU_LON,
        FINLAND_DOCUMENTED,
        FINLAND_REFERENCE,
        WAY_INCLUSION_STRATEGY,
        build_city_dataset,
    )
    from benchmark_finland_roads import _format_bytes


# Oulu keeps the center already used by the standalone Oulu benchmark, for
# exact continuity with its documented baseline (tools/osm/README.md).
# Helsinki and Tampere use the repository's canonical city centers
# (src/theroadragetrip/osm/constants.py: _CITY_CENTERS). Rovaniemi has no
# entry there, so it uses the coordinates from .github/prompts/cities-bin.md.
CITIES: dict[str, tuple[float, float]] = {
    "oulu": (OULU_LAT, OULU_LON),
    "helsinki": (60.169525, 24.935446),
    "tampere": (61.499113, 23.787117),
    "rovaniemi": (66.5039, 25.7294),
}


def _mib(byte_count: int) -> float:
    return byte_count / 1024.0 / 1024.0


def run_cities(
    input_pbf: Path,
    work_dir: Path,
    json_out: Path | None,
    cities: Mapping[str, tuple[float, float]] = CITIES,
) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    print(f"Way inclusion (applies identically to every city below): {WAY_INCLUSION_STRATEGY}")
    print()

    results: dict[str, dict] = {}
    for name, center in cities.items():
        print(f"--- {name.title()} ---")
        # Each city runs in its own fresh process: RSS/peak-RSS are process
        # high-water marks that never shrink, so measuring several cities in
        # one process would let a later, smaller city inherit an earlier,
        # larger city's memory footprint instead of its own.
        city_work_dir = work_dir / name
        city_work_dir.mkdir(parents=True, exist_ok=True)
        worker_json = city_work_dir / "_worker_result.json"
        subprocess.run(
            [
                sys.executable, str(Path(__file__).resolve()), "--worker",
                "--city", name, "--lat", str(center[0]), "--lon", str(center[1]),
                "--input", str(input_pbf), "--work-dir", str(city_work_dir),
                "--out-json", str(worker_json),
            ],
            check=True,
        )
        data = json.loads(worker_json.read_text(encoding="utf-8"))
        results[name] = data
        bbox, dims = data["bbox"], data["dimensions"]
        print(
            f"  bbox: min_lat={bbox['min_lat']:.6f} max_lat={bbox['max_lat']:.6f} "
            f"min_lon={bbox['min_lon']:.6f} max_lon={bbox['max_lon']:.6f}"
        )
        print(f"  size: {dims['width_km']:.1f} x {dims['height_km']:.1f} km (~{dims['area_km2']:.0f} km2)")
        print(
            f"  binary: {_format_bytes(data['file_size_bytes'])}, "
            f"ways={data['dataset']['ways']:,} nodes={data['dataset']['nodes']:,} "
            f"geometry={data['dataset']['geometry_points']:,} "
            f"road_length={data['dataset']['road_length_km']:,.3f} km"
        )
        print(
            f"  load: {data['runtime']['load_time_ms'] / 1000:.3f} s "
            f"(warm {data['runtime']['warm_load_time_ms'] / 1000:.3f} s), "
            f"+RSS {_format_bytes(data['runtime']['additional_rss_bytes'])}, "
            f"expansion {data['runtime']['memory_expansion_ratio']:.2f}x"
        )
        print()

    _print_cross_city_table(results)
    _print_scaling_analysis(results)
    _answer_questions(results)

    combined = {
        "benchmark": "Finnish 20x20 km city comparison",
        "way_inclusion_strategy": WAY_INCLUSION_STRATEGY,
        "cities": results,
        "finland_baseline": {
            "reference": FINLAND_REFERENCE,
            "documented": FINLAND_DOCUMENTED,
        },
    }
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"JSON result written to: {json_out}")
    return combined


def _print_cross_city_table(results: Mapping[str, dict]) -> None:
    names = list(results)
    col = 15
    width = 24 + col * len(names)

    def row(label: str, values: list[str]) -> str:
        return f"{label:<24}" + "".join(f"{v:<{col}}" for v in values)

    def fmt(values: list[float], spec: str) -> list[str]:
        return [format(v, spec) for v in values]

    area = [results[n]["dimensions"]["area_km2"] for n in names]
    binary_mib = [_mib(results[n]["file_size_bytes"]) for n in names]
    ways = [results[n]["dataset"]["ways"] for n in names]
    nodes = [results[n]["dataset"]["nodes"] for n in names]
    geometry = [results[n]["dataset"]["geometry_points"] for n in names]
    road_km = [results[n]["dataset"]["road_length_km"] for n in names]
    load_s = [results[n]["runtime"]["load_time_ms"] / 1000.0 for n in names]
    warm_s = [results[n]["runtime"]["warm_load_time_ms"] / 1000.0 for n in names]
    add_rss_mib = [_mib(results[n]["runtime"]["additional_rss_bytes"]) for n in names]
    peak_rss_mib = [_mib(results[n]["runtime"]["peak_rss_bytes"]) for n in names]
    expansion = [results[n]["runtime"]["memory_expansion_ratio"] for n in names]
    way_ms = [results[n]["random_access"]["way_lookup_ms"] for n in names]
    node_ms = [results[n]["random_access"]["node_lookup_ms"] for n in names]
    geom_ms = [results[n]["random_access"]["geometry_access_ms"] for n in names]
    road_density = [road_km[i] / area[i] for i in range(len(names))]
    ways_per_km2 = [ways[i] / area[i] for i in range(len(names))]
    nodes_per_km2 = [nodes[i] / area[i] for i in range(len(names))]
    mib_per_1000km = [binary_mib[i] / (road_km[i] / 1000.0) for i in range(len(names))]
    ram_mib_per_1000km = [add_rss_mib[i] / (road_km[i] / 1000.0) for i in range(len(names))]
    load_s_per_1000km = [load_s[i] / (road_km[i] / 1000.0) for i in range(len(names))]

    print("=" * width)
    print("20x20 km Finnish City Benchmark")
    print("=" * width)
    print(row("Metric", [n.title() for n in names]))
    print("-" * width)
    print(row("Area km2", fmt(area, ".0f")))
    print(row("Binary MiB", fmt(binary_mib, ".2f")))
    print(row("Ways", [f"{v:,}" for v in ways]))
    print(row("Nodes", [f"{v:,}" for v in nodes]))
    print(row("Geometry points", [f"{v:,}" for v in geometry]))
    print(row("Road length km", fmt(road_km, ",.3f")))
    print(row("Load seconds", fmt(load_s, ".3f")))
    print(row("Warm load seconds", fmt(warm_s, ".3f")))
    print(row("Additional RSS MiB", fmt(add_rss_mib, ".2f")))
    print(row("Peak RSS MiB", fmt(peak_rss_mib, ".2f")))
    print(row("Memory expansion", [f"{v:.2f}x" for v in expansion]))
    print(row("Way lookup ms", fmt(way_ms, ".3f")))
    print(row("Node lookup ms", fmt(node_ms, ".3f")))
    print(row("Geometry lookup ms", fmt(geom_ms, ".3f")))
    print("-" * width)
    print(row("Road density km/km2", fmt(road_density, ".2f")))
    print(row("Ways per km2", fmt(ways_per_km2, ".1f")))
    print(row("Nodes per km2", fmt(nodes_per_km2, ".1f")))
    print(row("Binary MiB/1000km", fmt(mib_per_1000km, ".2f")))
    print(row("RAM MiB/1000km", fmt(ram_mib_per_1000km, ".2f")))
    print(row("Load s/1000km", fmt(load_s_per_1000km, ".4f")))
    print("-" * width)
    print()


def _print_scaling_analysis(results: Mapping[str, dict]) -> None:
    print("=== Memory scaling (additional RSS / binary size) ===")
    for name, data in results.items():
        print(f"  {name.title()}: {data['runtime']['memory_expansion_ratio']:.2f}x")
    print(f"  Finland (documented): {FINLAND_DOCUMENTED['memory_expansion_ratio']:.2f}x")
    print()

    print("=== Load-time scaling ===")
    finland_load_s = FINLAND_DOCUMENTED["load_time_s"]
    print(
        f"  Finland: {finland_load_s:.3f} s total, "
        f"{finland_load_s / FINLAND_REFERENCE['ways'] * 1e6:.4f} us/way, "
        f"{finland_load_s / FINLAND_REFERENCE['nodes'] * 1e6:.4f} us/node, "
        f"{finland_load_s / FINLAND_REFERENCE['geometry_points'] * 1e6:.4f} us/geometry point, "
        f"{finland_load_s / FINLAND_DOCUMENTED['file_size_mib']:.4f} s/MiB"
    )
    for name, data in results.items():
        load_s = data["runtime"]["load_time_ms"] / 1000.0
        ways, nodes = data["dataset"]["ways"], data["dataset"]["nodes"]
        geometry = data["dataset"]["geometry_points"]
        mib = _mib(data["file_size_bytes"])
        print(
            f"  {name.title()}: {load_s:.3f} s total, "
            f"{load_s / ways * 1e6:.4f} us/way, "
            f"{load_s / nodes * 1e6:.4f} us/node, "
            f"{load_s / geometry * 1e6:.4f} us/geometry point, "
            f"{load_s / mib:.4f} s/MiB"
        )
    print()


def _spread(values) -> str:
    """'Nx spread' between max and min, or a note when min is too small (or
    zero) to divide by -- possible for a tiny dataset whose RSS delta falls
    below OS page-measurement granularity."""
    lo, hi = min(values), max(values)
    return f"{hi / lo:.2f}x spread" if lo > 0 else "spread unavailable (min is ~0)"


def _answer_questions(results: Mapping[str, dict]) -> None:
    binary_mib = {n: _mib(d["file_size_bytes"]) for n, d in results.items()}
    add_rss_mib = {n: _mib(d["runtime"]["additional_rss_bytes"]) for n, d in results.items()}

    print("=== Q: How much does a 20x20 km map vary between cities? ===")
    print(
        f"  Binary size range: {min(binary_mib.values()):.2f}-{max(binary_mib.values()):.2f} MiB "
        f"({_spread(binary_mib.values())})"
    )
    print(
        f"  Additional RSS range: {min(add_rss_mib.values()):.2f}-{max(add_rss_mib.values()):.2f} MiB "
        f"({_spread(add_rss_mib.values())})"
    )
    print()

    print("=== Q: Does area alone predict resource use, or does road density dominate? ===")
    for name, data in results.items():
        area = data["dimensions"]["area_km2"]
        road_km = data["dataset"]["road_length_km"]
        print(
            f"  {name.title()}: area {area:.0f} km2, road density {road_km / area:.2f} km/km2, "
            f"binary {binary_mib[name]:.2f} MiB, +RSS {add_rss_mib[name]:.2f} MiB"
        )
    print(
        "  All four areas are ~400 km2 by construction, so the spread reported above in binary "
        "size and RSS is measured against a constant area and tracks the road-density figures "
        "printed per city, not the (fixed) area."
    )
    print()


def _worker_main(argv: list[str]) -> int:
    """Internal: run one city's build_city_dataset() in its own process and
    dump the nested result as JSON. Invoked by run_cities() via subprocess,
    not meant to be called directly."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args(argv)
    data = build_city_dataset(args.city, (args.lat, args.lon), args.input, args.work_dir)
    args.out_json.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return 0


def main() -> int:
    if "--worker" in sys.argv[1:]:
        return _worker_main([a for a in sys.argv[1:] if a != "--worker"])

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path,
        default=Path("src/theroadragetrip/assets/osm/finland-latest.osm.pbf"),
        help="Finland source .osm.pbf",
    )
    parser.add_argument("--work-dir", type=Path, required=True, help="Directory for clipped PBFs and city .bin files")
    parser.add_argument("--json", type=Path, help="Optional combined machine-readable result path")
    args = parser.parse_args()
    try:
        run_cities(args.input, args.work_dir, args.json)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
