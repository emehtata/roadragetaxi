"""Build <cache_root>/<city>.dem.json (osm/elevation.py) offline.

Source: NLS Finland 10 m elevation model (Maanmittauslaitos, CC BY 4.0,
EPSG:3067) or Copernicus GLO-30, converted to ESRI ASCII grid first, e.g.
    gdal_translate -of AAIGrid -tr 10 10 -t_srs EPSG:3067 in.tif hill.asc
    .venv/bin/python tools/make_dem.py Helsinki --asc hill.asc
A synthetic test raster (no real heights; for render checks only):
    .venv/bin/python tools/make_dem.py Helsinki --test-hill X,Y,HEIGHT,RADIUS
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def from_asc(path: Path) -> dict:
    """ESRI ASCII grid (rows north to south) to the DEM JSON (rows along +y)."""
    lines = path.read_text().split("\n")
    head = {}
    while lines and lines[0].split() and lines[0].split()[0].lower() in (
            "ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter", "cellsize", "nodata_value"):
        key, value = lines.pop(0).split()[:2]
        head[key.lower()] = float(value)
    cols, rows, step = int(head["ncols"]), int(head["nrows"]), head["cellsize"]
    x0 = head.get("xllcorner", head.get("xllcenter", 0.0) - step / 2)
    y0 = head.get("yllcorner", head.get("yllcenter", 0.0) - step / 2)
    values = [float(v) for line in lines for v in line.split()]
    nodata = head.get("nodata_value")
    values = [0.0 if v == nodata else v for v in values]
    grid = [values[r * cols:(r + 1) * cols] for r in range(rows)][::-1]
    return {"origin": [x0, y0], "step": step, "cols": cols, "heights": [v for row in grid for v in row]}


def test_hill(x: float, y: float, height: float, radius: float, step: float = 10.0) -> dict:
    """A smooth hill of `height` m at (x, y), flat 0 m from 2 * radius out."""
    n = int(4 * radius / step) + 1
    x0, y0 = x - 2 * radius - step / 2, y - 2 * radius - step / 2
    heights = []
    for r in range(n):
        for c in range(n):
            d = math.hypot(x0 + (c + 0.5) * step - x, y0 + (r + 0.5) * step - y) / (2 * radius)
            heights.append(round(height * 0.5 * (1 + math.cos(math.pi * min(d, 1.0))), 2))
    return {"origin": [x0, y0], "step": step, "cols": n, "heights": heights}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("city")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--asc", type=Path)
    group.add_argument("--test-hill", help="X,Y,HEIGHT,RADIUS (EPSG:3067 m)")
    args = parser.parse_args()
    from theroadragetrip.osm.cache import default_cache_root
    data = from_asc(args.asc) if args.asc else test_hill(*(float(v) for v in args.test_hill.split(",")))
    out = Path(default_cache_root()) / f"{args.city}.dem.json"
    out.write_text(json.dumps(data))
    print(out, data["cols"], "x", len(data["heights"]) // data["cols"])


if __name__ == "__main__":
    main()
