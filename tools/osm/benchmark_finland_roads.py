#!/usr/bin/env python3
"""Benchmark the existing Python loader for a Road Rage Taxi roads v2 binary."""

from __future__ import annotations

import argparse
import gc
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping

try:
    from tools.osm.build_finland_roads import (
        V2_FORMAT_VERSION,
        _haversine_m,
        analyze_road_binary,
        load_road_dataset,
    )
except ModuleNotFoundError:  # Direct: python tools/osm/benchmark_finland_roads.py
    from build_finland_roads import (
        V2_FORMAT_VERSION,
        _haversine_m,
        analyze_road_binary,
        load_road_dataset,
    )


REFERENCE = {
    "ways": 1_038_925,
    "nodes": 10_325_748,
    "geometry_points": 11_548_814,
    "road_length_km": 334_848.756687,
}
RANDOM_SEED = 0x525254


def _windows_memory_bytes() -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.windll.kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    ):
        raise OSError("GetProcessMemoryInfo failed")
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def current_rss_bytes() -> int:
    """Current resident set size, not Python allocator accounting."""
    if sys.platform.startswith("linux"):
        fields = Path("/proc/self/statm").read_text().split()
        return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
    if sys.platform == "win32":
        return _windows_memory_bytes()[0]
    output = subprocess.check_output(
        ["ps", "-o", "rss=", "-p", str(os.getpid())], text=True,
    )
    return int(output.strip()) * 1024


def peak_rss_bytes() -> int:
    if sys.platform == "win32":
        return _windows_memory_bytes()[1]
    import resource

    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _elapsed_ms(callback) -> tuple[float, object]:
    started = time.perf_counter_ns()
    result = callback()
    return (time.perf_counter_ns() - started) / 1_000_000.0, result


def _sample_indices(count: int, population: int, seed_offset: int) -> list[int]:
    if population <= 0:
        return []
    rng = random.Random(RANDOM_SEED + seed_offset)
    return [rng.randrange(population) for _ in range(count)]


def _lookup_benchmarks(dataset, sample_sizes: tuple[int, ...]) -> dict:
    results = {"way": {}, "node": {}, "geometry": {}}
    way_count, node_count = len(dataset.ways), len(dataset.nodes)
    for sample_size in sample_sizes:
        way_indices = _sample_indices(sample_size, way_count, sample_size)
        node_indices = _sample_indices(sample_size, node_count, sample_size + 1)

        def access_ways():
            checksum = 0
            for index in way_indices:
                way = dataset.ways[index]
                checksum ^= way.osm_id ^ way.maxspeed_kmh ^ len(way.node_ids)
            return checksum

        way_ms, way_checksum = _elapsed_ms(access_ways)

        def access_nodes():
            checksum = 0
            for index in node_indices:
                latitude, longitude = dataset.nodes[index]
                checksum ^= latitude ^ longitude
            return checksum

        node_ms, node_checksum = _elapsed_ms(access_nodes)

        def access_geometry():
            checksum = 0
            points = 0
            for index in way_indices:
                for node_index in dataset.ways[index].node_ids:
                    latitude, longitude = dataset.nodes[node_index]
                    checksum ^= latitude ^ longitude
                    points += 1
            return checksum, points

        geometry_ms, (geometry_checksum, points_touched) = _elapsed_ms(access_geometry)
        key = str(sample_size)
        results["way"][key] = {
            "total_ms": way_ms,
            "average_us": way_ms * 1000.0 / sample_size,
            "checksum": way_checksum,
        }
        results["node"][key] = {
            "total_ms": node_ms,
            "average_us": node_ms * 1000.0 / sample_size,
            "checksum": node_checksum,
        }
        results["geometry"][key] = {
            "total_ms": geometry_ms,
            "ways": sample_size,
            "points_touched": points_touched,
            "average_us_per_way": geometry_ms * 1000.0 / sample_size,
            "checksum": geometry_checksum,
        }
    return results


def benchmark_dataset(
    path: Path,
    expected: Mapping[str, float | int] | None = REFERENCE,
    sample_sizes: tuple[int, ...] = (1000, 10_000),
) -> dict:
    path = Path(path)
    analysis = analyze_road_binary(path)
    if analysis["format_version"] != V2_FORMAT_VERSION:
        raise ValueError(f"benchmark requires v2, got format v{analysis['format_version']}")

    gc.collect()
    baseline_rss = current_rss_bytes()
    open_ms, _ = _elapsed_ms(lambda: path.open("rb").close())
    loader_ms, dataset = _elapsed_ms(lambda: load_road_dataset(path))
    parse_ms = max(0.0, loader_ms - open_ms)
    loaded_rss = current_rss_bytes()

    geometry_points = sum(len(way.node_ids) for way in dataset.ways)

    def calculate_road_length():
        total = 0.0
        for way in dataset.ways:
            for first, second in zip(way.node_ids, way.node_ids[1:]):
                total += _haversine_m(dataset.nodes[first], dataset.nodes[second])
        return total / 1000.0

    road_length_ms, road_length_km = _elapsed_ms(calculate_road_length)
    if expected is not None:
        actual = {
            "ways": len(dataset.ways),
            "nodes": len(dataset.nodes),
            "geometry_points": geometry_points,
        }
        for key, value in actual.items():
            if value != expected[key]:
                raise ValueError(f"{key} mismatch: expected {expected[key]}, got {value}")
        if abs(road_length_km - float(expected["road_length_km"])) > 0.001:
            raise ValueError(
                f"road length mismatch: expected {expected['road_length_km']}, got {road_length_km}"
            )

    lookups = _lookup_benchmarks(dataset, sample_sizes)
    peak_rss = peak_rss_bytes()
    return {
        "format_version": V2_FORMAT_VERSION,
        "file": str(path.resolve()),
        "file_size_bytes": path.stat().st_size,
        "ways": len(dataset.ways),
        "nodes": len(dataset.nodes),
        "geometry_points": geometry_points,
        "unique_strings": analysis["string_count"],
        "road_length_km": road_length_km,
        "road_length_validation_ms": road_length_ms,
        "open_time_ms": open_ms,
        "parse_time_ms": parse_ms,
        "total_load_time_ms": loader_ms,
        "baseline_rss_bytes": baseline_rss,
        "loaded_rss_bytes": loaded_rss,
        "rss_increase_bytes": loaded_rss - baseline_rss,
        "peak_rss_bytes": peak_rss,
        "memory_expansion_ratio": (loaded_rss - baseline_rss) / path.stat().st_size,
        "lookups": lookups,
        "random_way_lookup_ms": lookups["way"][str(sample_sizes[-1])]["total_ms"],
        "random_node_lookup_ms": lookups["node"][str(sample_sizes[-1])]["total_ms"],
        "geometry_access_ms": lookups["geometry"][str(sample_sizes[-1])]["total_ms"],
        "nearest_road": "NOT IMPLEMENTED IN CURRENT V2 REPRESENTATION",
        "mmap": "NOT RUN: current Python loader fully materializes decoded objects",
        "filesystem_cache": "OS cache state not controlled; no privileged cache flushing performed",
        "validation": "PASS",
    }


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024.0 or unit == "GiB":
            return f"{amount:.2f} {unit}"
        amount /= 1024.0
    raise AssertionError


def print_report(result: Mapping) -> None:
    print("=== Finland Roads V2 Runtime Benchmark ===")
    print(f"File: {result['file']}")
    print(f"File size: {_format_bytes(result['file_size_bytes'])}")
    print("Load:")
    print(f"  Open:  {result['open_time_ms']:.3f} ms")
    print(f"  Parse: {result['parse_time_ms']:.3f} ms ({result['parse_time_ms'] / 1000:.3f} s)")
    print(f"  Total: {result['total_load_time_ms']:.3f} ms ({result['total_load_time_ms'] / 1000:.3f} s)")
    print("Memory:")
    print(f"  Baseline RSS: {_format_bytes(result['baseline_rss_bytes'])}")
    print(f"  Loaded RSS:   {_format_bytes(result['loaded_rss_bytes'])}")
    print(f"  Increase:     {_format_bytes(result['rss_increase_bytes'])}")
    print(f"  Peak RSS:     {_format_bytes(result['peak_rss_bytes'])}")
    print("Dataset:")
    print(f"  Ways: {result['ways']:,}")
    print(f"  Nodes: {result['nodes']:,}")
    print(f"  Geometry points: {result['geometry_points']:,}")
    print(f"  Unique strings: {result['unique_strings']:,}")
    print(f"  Road length: {result['road_length_km']:,.3f} km")
    print(f"  Road-length validation: {result['road_length_validation_ms']:.3f} ms")
    print("Lookups:")
    for kind in ("way", "node", "geometry"):
        for sample_size, values in result["lookups"][kind].items():
            suffix = f", {values['points_touched']:,} points" if kind == "geometry" else ""
            average_key = "average_us_per_way" if kind == "geometry" else "average_us"
            print(
                f"  {kind.title()} {int(sample_size):,}: {values['total_ms']:.3f} ms, "
                f"{values[average_key]:.3f} us each{suffix}"
            )
    print(f"Nearest-road lookup: {result['nearest_road']}")
    print(f"mmap: {result['mmap']}")
    print(f"Cache note: {result['filesystem_cache']}")
    print("=== Interpretation ===")
    print(f"Runtime memory expansion: {_format_bytes(result['rss_increase_bytes'])}")
    print(f"Expansion ratio: {result['memory_expansion_ratio']:.2f}x file size")
    print(f"Total load time: {result['total_load_time_ms'] / 1000:.3f} s")
    print("Assessment: measurements recorded; no integration threshold is assumed.")
    print(f"Validation: {result['validation']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, help="Existing v2 roads binary")
    parser.add_argument("--json", type=Path, help="Optional machine-readable result path")
    args = parser.parse_args()
    try:
        result = benchmark_dataset(args.binary)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print_report(result)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        temp = args.json.with_name(f".{args.json.name}.tmp")
        try:
            temp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            temp.replace(args.json)
        finally:
            temp.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
