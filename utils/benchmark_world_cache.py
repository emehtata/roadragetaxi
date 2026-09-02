"""Compare normalized JSON processing with RWC loading.

Run with: PYTHONPATH=src python utils/benchmark_world_cache.py
"""

import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from theroadragetrip.osm import build_ways
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def timed(function):
    tracemalloc.start()
    started = time.perf_counter()
    result = function()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, (time.perf_counter() - started) * 1000.0, peak / 1024.0


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "sample_osm_large.json").open(encoding="utf-8") as stream:
        elements, parse_ms, parse_memory = timed(lambda: json.load(stream)["elements"])
    world, process_ms, process_memory = timed(lambda: build_ways(elements))
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "benchmark.rwc"
        _, write_ms, write_memory = timed(lambda: BinaryWorldCacheWriter().write(path, world, "benchmark"))
        _, load_ms, load_memory = timed(lambda: BinaryWorldCacheLoader().load(path))
    print(f"JSON parsing: {parse_ms:.1f} ms")
    print(f"JSON processing: {process_ms:.1f} ms")
    print(f"RWC writing: {write_ms:.1f} ms")
    print(f"RWC loading: {load_ms:.1f} ms")
    print(f"Peak memory (KB): JSON={parse_memory:.0f}, processing={process_memory:.0f}, "
          f"writing={write_memory:.0f}, loading={load_memory:.0f}")
    print(f"Total JSON pipeline: {parse_ms + process_ms:.1f} ms")
    print(f"Total RWC pipeline: {load_ms:.1f} ms")


if __name__ == "__main__":
    main()
