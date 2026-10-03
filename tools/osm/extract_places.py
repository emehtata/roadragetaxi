#!/usr/bin/env python3
"""Extract fixed world places (airports, railway stations, ...) from an OSM
PBF into a small committed JSON file the game loads at runtime.

    python tools/osm/extract_places.py INPUT.osm.pbf OUTPUT.json

Build-time only: the game reads the JSON (theroadragetrip.world_places),
never the PBF. Independent of the (disabled) BIN road pipeline. Categories
live in places_config.py; see docs/places.md.

Pipeline: one `osmium tags-filter` pass over the PBF (streaming, keeps the
referenced way nodes and relation members) -> the game's own OSM XML
parser (theroadragetrip.osm.pbf_source._parse_osm_xml) -> category match
-> one representative coordinate per element -> deterministic dedupe ->
sorted JSON.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shapely.geometry import LineString, MultiPoint, Point  # noqa: E402
from shapely.ops import polygonize, unary_union  # noqa: E402

from places_config import CATEGORIES, PlaceCategory  # noqa: E402
from theroadragetrip.osm.pbf_source import _parse_osm_xml  # noqa: E402

FORMAT_VERSION = 1
COORDINATE_DECIMALS = 6  # ~0.1 m
OSMIUM_TIMEOUT_S = 1800.0
SUPPORTED_SUFFIXES = (".pbf", ".osm")
NAME_TAGS = ("name", "name:fi", "name:sv", "name:en")
M_PER_DEG_LAT = 111_320.0


class ExtractError(RuntimeError):
    """A user-facing failure (bad input, osmium error, ...)."""


# -- geometry ---------------------------------------------------------------

class _Projection:
    """Local equirectangular metres around one latitude: good to well
    under a metre across any single airport, so centroids and
    point-in-polygon tests are not skewed by degrees of longitude
    shrinking northwards."""

    def __init__(self, lat0: float) -> None:
        self.kx = M_PER_DEG_LAT * math.cos(math.radians(lat0))

    def to_xy(self, lat: float, lon: float) -> Tuple[float, float]:
        return lon * self.kx, lat * M_PER_DEG_LAT

    def to_latlon(self, x: float, y: float) -> Tuple[float, float]:
        return y / M_PER_DEG_LAT, x / self.kx


def _representative(points: List[Tuple[float, float]], areas, lines) -> Optional[Tuple[float, float]]:
    """(lat, lon) for the collected geometry: an area's centroid, or a point
    guaranteed inside it when the centroid falls outside (an L-shaped
    airport); a line's midpoint along its length; else the points' mean."""
    all_latlon = points + [p for ring in areas for p in ring] + [p for line in lines for p in line]
    if not all_latlon:
        return None
    projection = _Projection(sum(lat for lat, _ in all_latlon) / len(all_latlon))
    if areas:
        polygons = list(polygonize([LineString([projection.to_xy(*p) for p in ring]) for ring in areas]))
        if polygons:
            shape = unary_union(polygons)
            point = shape.centroid
            if not shape.contains(point):
                point = shape.representative_point()
            return projection.to_latlon(point.x, point.y)
    if lines:
        merged = unary_union([LineString([projection.to_xy(*p) for p in line]) for line in lines])
        point = merged.interpolate(0.5, normalized=True) if merged.geom_type == "LineString" else merged.centroid
        return projection.to_latlon(point.x, point.y)
    point = MultiPoint([projection.to_xy(*p) for p in points]).centroid if len(points) > 1 else Point(projection.to_xy(*points[0]))
    return projection.to_latlon(point.x, point.y)


class _Geometry:
    def __init__(self, elements: Iterable[dict]) -> None:
        self.nodes: Dict[int, Tuple[float, float]] = {}
        self.ways: Dict[int, List[int]] = {}
        self.relations: Dict[int, List[dict]] = {}
        for element in elements:
            if element["type"] == "node":
                self.nodes[element["id"]] = (element["lat"], element["lon"])
            elif element["type"] == "way":
                self.ways[element["id"]] = element["nodes"]
            else:
                self.relations[element["id"]] = element["members"]

    def _way_coords(self, way_id: int) -> List[Tuple[float, float]]:
        return [self.nodes[n] for n in self.ways.get(way_id, ()) if n in self.nodes]

    def point_for(self, element: dict) -> Optional[Tuple[float, float]]:
        kind = element["type"]
        if kind == "node":
            return element["lat"], element["lon"]
        if kind == "way":
            coords = self._way_coords(element["id"])
            if len(coords) >= 4 and coords[0] == coords[-1]:
                return _representative([], [coords], [])
            return _representative([], [], [coords]) if len(coords) >= 2 else _representative(coords, [], [])
        members = self.relations.get(element["id"], [])
        # A mapper-designated point wins over any computed one.
        for member in members:
            if member["type"] == "node" and member["role"] in ("label", "admin_centre") and member["ref"] in self.nodes:
                return self.nodes[member["ref"]]
        rings = [
            self._way_coords(m["ref"]) for m in members
            if m["type"] == "way" and m["role"] in ("outer", "")
        ]
        rings = [ring for ring in rings if len(ring) >= 2]
        points = [self.nodes[m["ref"]] for m in members if m["type"] == "node" and m["ref"] in self.nodes]
        if element["tags"].get("type") in ("multipolygon", "boundary"):
            return _representative(points, rings, [])
        closed = [ring for ring in rings if len(ring) >= 4 and ring[0] == ring[-1]]
        return _representative(points, closed, [ring for ring in rings if ring not in closed])


# -- matching & dedupe ------------------------------------------------------

def _distance_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    kx = M_PER_DEG_LAT * math.cos(math.radians((a[0] + b[0]) / 2.0))
    return math.hypot((a[0] - b[0]) * M_PER_DEG_LAT, (a[1] - b[1]) * kx)


def _names(tags) -> set:
    return {tags[key].strip().casefold() for key in NAME_TAGS if tags.get(key, "").strip()}


def _find(parent: List[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _dedupe(category: PlaceCategory, candidates: List[dict]) -> List[List[dict]]:
    """Groups of candidates that are one physical place: they share an
    identity tag value (ICAO, station code, ...), or share any name
    (name / name:fi / name:sv / name:en, case-insensitive) within
    dedupe_radius_m. Similar-but-different names never merge. Grid-bucketed
    by the radius, so no all-pairs scan."""
    candidates = sorted(candidates, key=lambda c: (c["osm"]["type"], c["osm"]["id"]))
    parent = list(range(len(candidates)))

    def union(a: int, b: int) -> None:
        ra, rb = _find(parent, a), _find(parent, b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_identity: Dict[Tuple[str, str], int] = {}
    for index, candidate in enumerate(candidates):
        for tag in category.identity_tags:
            value = candidate["tags"].get(tag, "").strip().casefold()
            if value:
                union(index, by_identity.setdefault((tag, value), index))

    cell_deg = category.dedupe_radius_m / M_PER_DEG_LAT
    grid: Dict[Tuple[int, int], List[int]] = {}
    for index, candidate in enumerate(candidates):
        lat, lon = candidate["point"]
        # Longitude cells widened by 1/cos(lat) keep a cell >= radius wide.
        cell = (math.floor(lat / cell_deg), math.floor(lon * math.cos(math.radians(lat)) / cell_deg))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in grid.get((cell[0] + dx, cell[1] + dy), ()):
                    if (
                        candidate["names"] & candidates[other]["names"]
                        and _distance_m(candidate["point"], candidates[other]["point"]) <= category.dedupe_radius_m
                    ):
                        union(index, other)
        grid.setdefault(cell, []).append(index)

    groups: Dict[int, List[dict]] = {}
    for index, candidate in enumerate(candidates):
        groups.setdefault(_find(parent, index), []).append(candidate)
    return list(groups.values())


def _keeper(category: PlaceCategory, group: List[dict]) -> dict:
    preference = {kind: rank for rank, kind in enumerate(category.element_preference)}
    return min(group, key=lambda c: (
        preference.get(c["osm"]["type"], len(preference)),
        -sum(1 for tag in category.metadata.values() if c["tags"].get(tag)),
        c["osm"]["id"],
    ))


def _place_record(category: PlaceCategory, group: List[dict]) -> dict:
    keeper = _keeper(category, group)
    others = sorted((c for c in group if c is not keeper), key=lambda c: (c["osm"]["type"], c["osm"]["id"]))
    tags = keeper["tags"]
    identity = next((tags[t] for t in category.identity_tags if tags.get(t)), None)
    record = {
        "id": f"{category.type}_{identity}".casefold().replace(" ", "_") if identity else
        f"{category.type}_{keeper['osm']['type'][0]}{keeper['osm']['id']}",
        "type": category.type,
        "name": tags.get("name") or next(tags[k] for k in NAME_TAGS if tags.get(k)),
        "lat": round(keeper["point"][0], COORDINATE_DECIMALS),
        "lon": round(keeper["point"][1], COORDINATE_DECIMALS),
        "osm": dict(keeper["osm"]),
    }
    names = {key.split(":")[1]: tags[key] for key in NAME_TAGS[1:] if tags.get(key) and tags[key] != record["name"]}
    if names:
        record["names"] = names
    for json_key, tag in category.metadata.items():
        # A duplicate may carry a code the keeper lacks.
        value = next((c["tags"][tag] for c in [keeper] + others if c["tags"].get(tag)), None)
        if value is not None:
            record[json_key] = value
    if others:
        record["osm_duplicates"] = [dict(c["osm"]) for c in others]
    return record


def extract_places(elements: Sequence[dict], categories: Sequence[PlaceCategory] = CATEGORIES) -> Tuple[List[dict], dict]:
    """Pure core: OSM element dicts (Overpass/_parse_osm_xml shape) ->
    (sorted place records, stats). Unnamed or geometry-less matches are
    counted, never silently lost."""
    geometry = _Geometry(elements)
    records: List[dict] = []
    stats = {"categories": {}, "unnamed_skipped": [], "no_geometry_skipped": [], "duplicates_merged": 0}
    for category in categories:
        candidates = []
        for element in elements:
            tags = element.get("tags") or {}
            if not tags or not category.matches(tags):
                continue
            osm = {"type": element["type"], "id": element["id"]}
            names = _names(tags)
            if not names:
                stats["unnamed_skipped"].append({"category": category.type, **osm})
                continue
            point = geometry.point_for(element)
            if point is None:
                stats["no_geometry_skipped"].append({"category": category.type, **osm})
                continue
            candidates.append({"osm": osm, "tags": tags, "names": names, "point": point})
        groups = _dedupe(category, candidates)
        category_records = [_place_record(category, group) for group in groups]
        # Ids must stay unique even if two places share a code.
        seen: Dict[str, int] = {}
        for record in sorted(category_records, key=lambda r: (r["osm"]["type"], r["osm"]["id"])):
            seen[record["id"]] = seen.get(record["id"], 0) + 1
            if seen[record["id"]] > 1:
                record["id"] = f"{record['id']}_{record['osm']['type'][0]}{record['osm']['id']}"
        stats["categories"][category.type] = {"candidates": len(candidates), "places": len(category_records)}
        stats["duplicates_merged"] += len(candidates) - len(category_records)
        records.extend(category_records)
    records.sort(key=lambda r: (r["type"], r["name"].casefold(), r["id"]))
    return records, stats


# -- I/O --------------------------------------------------------------------

def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=OSMIUM_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise ExtractError(f"osmium timed out: {' '.join(cmd)}") from exc
    if result.returncode != 0:
        raise ExtractError(f"osmium failed (exit {result.returncode}): {result.stderr.strip() or 'no output'}")
    return result


def read_elements(input_path: Path, categories: Sequence[PlaceCategory] = CATEGORIES) -> List[dict]:
    """One streaming osmium pass: only the candidates plus what their
    geometry references - the PBF itself is never loaded into Python."""
    if shutil.which("osmium") is None:
        raise ExtractError("the `osmium` command (osmium-tool) is required but not on PATH")
    filters = sorted({f for category in categories for f in category.osmium_filters})
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "candidates.osm")
        _run(["osmium", "tags-filter", "--overwrite", "-f", "osm", "-o", out, str(input_path), *filters])
        try:
            return _parse_osm_xml(out)
        except Exception as exc:  # osmium wrote something unparsable
            raise ExtractError(f"could not parse osmium output: {exc}") from exc


def source_timestamp(input_path: Path) -> Optional[str]:
    """The extract's replication timestamp (Geofabrik sets it) - part of
    the output so a regenerated file shows which data it came from."""
    try:
        value = _run(["osmium", "fileinfo", "-g", "header.option.osmosis_replication_timestamp", str(input_path)])
    except ExtractError:
        return None
    return value.stdout.strip() or None


def build_document(input_path: Path, places: List[dict]) -> dict:
    document = {"version": FORMAT_VERSION, "source": input_path.name}
    timestamp = source_timestamp(input_path)
    if timestamp:
        document["source_timestamp"] = timestamp
    document["places"] = places
    return document


def write_json(document: dict, output_path: Path) -> None:
    """Atomic (temp + rename); one place per line keeps diffs readable."""
    lines = [json.dumps({k: v for k, v in document.items() if k != "places"}, ensure_ascii=False)[:-1] + ', "places": [']
    places = document["places"]
    for index, place in enumerate(places):
        lines.append("  " + json.dumps(place, ensure_ascii=False) + ("," if index < len(places) - 1 else ""))
    lines.append("]}")
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(output_path)


def validate_input(input_path: Path, output_path: Path) -> None:
    if not input_path.is_file():
        raise ExtractError(f"input not found: {input_path}")
    if not input_path.name.endswith(SUPPORTED_SUFFIXES):
        raise ExtractError(f"unsupported input {input_path.name!r}: expected an .osm.pbf (or .osm) file")
    if not output_path.parent.is_dir():
        raise ExtractError(f"output directory does not exist: {output_path.parent}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("input", type=Path, help="OSM extract, e.g. finland-latest.osm.pbf")
    parser.add_argument("output", type=Path, help="JSON to write, e.g. src/theroadragetrip/assets/places.json")
    args = parser.parse_args(argv)
    try:
        validate_input(args.input, args.output)
        print(f"Reading: {args.input}")
        places, stats = extract_places(read_elements(args.input))
        write_json(build_document(args.input, places), args.output)
    except ExtractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\nExtracted places:")
    for place_type, counts in stats["categories"].items():
        print(f"  {place_type + ':':<20}{counts['places']:>5}   ({counts['candidates']} matching elements)")
    print(f"  {'total:':<20}{len(places):>5}")
    print(f"  duplicates merged:  {stats['duplicates_merged']}")
    for key in ("unnamed_skipped", "no_geometry_skipped"):
        if stats[key]:
            print(f"  {key.replace('_', ' ')}: {len(stats[key])} {stats[key]}")
    print(f"\nOutput:\n  {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
