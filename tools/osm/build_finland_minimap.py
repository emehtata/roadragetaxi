#!/usr/bin/env python3
"""Build the Godot Finland highway minimap from a local OSM PBF."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


WIDTH, HEIGHT = 420, 360
MIN_LON, MAX_LON = 19.0, 32.0
MIN_LAT, MAX_LAT = 59.5, 70.5
MID_LON = (MIN_LON + MAX_LON) / 2
LON_SCALE = math.cos(math.radians(65.0))
ROAD_COLORS = {"motorway": "#ffca28", "trunk": "#e8b923", "primary": "#9aa7b4"}


def project(lon: float, lat: float) -> tuple[float, float]:
    scale = HEIGHT / (MAX_LAT - MIN_LAT)
    return (
        WIDTH / 2 + (lon - MID_LON) * LON_SCALE * scale,
        (MAX_LAT - lat) * scale,
    )


def simplify(points: list[tuple[float, float]], minimum_distance: float = 0.45) -> list[tuple[float, float]]:
    kept = [points[0]]
    for point in points[1:-1]:
        if math.hypot(point[0] - kept[-1][0], point[1] - kept[-1][1]) >= minimum_distance:
            kept.append(point)
    if points[-1] != kept[-1]:
        kept.append(points[-1])
    return kept


def build(input_path: Path, output_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="rrt-minimap-") as temp_dir:
        temp = Path(temp_dir)
        extract = Path(temp_dir) / "highways.osm"
        subprocess.run(
            [
                "osmium", "tags-filter", str(input_path),
                "w/highway=motorway,trunk,primary",
                "-o", str(extract), "-f", "osm",
            ],
            check=True,
        )
        root = ET.parse(extract).getroot()
        border_pbf = temp / "border.pbf"
        border_geojson = temp / "border.geojson"
        subprocess.run(
            ["osmium", "tags-filter", str(input_path), "r/admin_level=2", "-o", str(border_pbf)],
            check=True,
        )
        subprocess.run(
            ["osmium", "export", str(border_pbf), "-f", "geojson", "-o", str(border_geojson)],
            check=True,
        )
        features = json.loads(border_geojson.read_text(encoding="utf-8"))["features"]
        coast_pbf = temp / "coast.pbf"
        coast_geojson = temp / "coast.geojsonseq"
        subprocess.run(
            ["osmium", "tags-filter", str(input_path), "w/natural=coastline", "-o", str(coast_pbf)],
            check=True,
        )
        subprocess.run(
            ["osmium", "export", str(coast_pbf), "-f", "geojsonseq", "-o", str(coast_geojson)],
            check=True,
        )
        coast_paths = []
        with coast_geojson.open(encoding="utf-8") as coast:
            for line in coast:
                feature = json.loads(line.lstrip("\x1e"))
                if feature.get("properties", {}).get("natural") != "coastline":
                    continue
                geometry = feature.get("geometry", {})
                if geometry.get("type") != "LineString":
                    continue
                points = simplify([project(float(lon), float(lat)) for lon, lat in geometry["coordinates"]])
                if len(points) < 2:
                    continue
                xs, ys = zip(*points)
                if max(max(xs) - min(xs), max(ys) - min(ys)) >= 0.35:
                    coast_paths.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points))

    finland = next(
        feature["geometry"] for feature in features
        if feature.get("properties", {}).get("ISO3166-1") == "FI"
        and feature.get("geometry", {}).get("type") == "MultiPolygon"
    )
    land_parts = []
    for polygon in finland["coordinates"]:
        for ring in polygon:
            points = [project(float(lon), float(lat)) for lon, lat in ring]
            land_parts.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points) + " Z")
    land_path = " ".join(land_parts)

    nodes = {
        node.attrib["id"]: project(float(node.attrib["lon"]), float(node.attrib["lat"]))
        for node in root.findall("node")
    }
    paths: dict[str, list[str]] = {road_type: [] for road_type in ROAD_COLORS}
    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        road_type = tags.get("highway")
        if road_type not in paths:
            continue
        points = [nodes[ref.attrib["ref"]] for ref in way.findall("nd") if ref.attrib["ref"] in nodes]
        if len(points) < 2:
            continue
        points = simplify(points)
        if len(points) < 2 or math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1]) < 0.15:
            continue
        paths[road_type].append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" rx="12" fill="#172b3a"/>',
        f'<path d="{land_path}" fill="#263a2b" fill-rule="evenodd" stroke="#78909c" stroke-width="1.4"/>',
        f'<clipPath id="finland"><path d="{land_path}" fill-rule="evenodd"/></clipPath>',
        '<g clip-path="url(#finland)">',
    ]
    for road_type in ("primary", "trunk", "motorway"):
        width = {"primary": 0.7, "trunk": 1.1, "motorway": 1.5}[road_type]
        lines.append(
            f'<path d="{" ".join(paths[road_type])}" fill="none" stroke="{ROAD_COLORS[road_type]}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>'
        )
    lines.append(
        f'<path d="{" ".join(coast_paths)}" fill="none" stroke="#d5e3e8" '
        'stroke-width="0.8" stroke-linecap="round" stroke-linejoin="round"/>'
    )
    lines.append('</g>')
    lines.append(f'<path d="{land_path}" fill="none" stroke="#a8b6bd" stroke-width="1.4"/>')
    lines.append('</svg>')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.input, args.output)


if __name__ == "__main__":
    main()
