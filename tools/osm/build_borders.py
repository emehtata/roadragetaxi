"""Build src/theroadragetrip/assets/borders.json.gz (borders.py): Finland's
outline, territorial waters included, from OSM relation 54224 (ODbL), and
its neighbours' outlines from Natural Earth (public domain), in EPSG:3067.

    P=finland-latest.osm.pbf
    osmium getid -r $P r54224 -o fi.osm.pbf
    osmium export fi.osm.pbf -f geojson --geometry-types=polygon -o fi.geojson
    curl -LO https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson
    python tools/osm/build_borders.py fi.geojson ne_50m_admin_0_countries.geojson
"""
import gzip
import json
import sys
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

NEIGHBOURS = ("SWE", "NOR", "RUS", "EST")
REGION = box(4.0, 53.0, 45.0, 72.0)  # lon/lat: as far as a drive from Finland goes
FINLAND_TOLERANCE_M = 20.0  # the border runs down rivers: keep it close
NEIGHBOUR_TOLERANCE_M = 200.0  # only names the country once outside Finland
OUT = Path(__file__).resolve().parents[2] / "src" / "theroadragetrip" / "assets" / "borders.json.gz"


def _rings(geometry):
    polygons = mapping(geometry)["coordinates"] if geometry.geom_type == "MultiPolygon" else [mapping(geometry)["coordinates"]]
    return [[[[round(x), round(y)] for x, y in ring] for ring in polygon] for polygon in polygons]


def main(finland_geojson: str, natural_earth_geojson: str) -> None:
    project = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True).transform
    finland = next(shape(f["geometry"]) for f in json.load(open(finland_geojson, encoding="utf-8"))["features"]
                   if f["properties"].get("admin_level") == "2")
    data = {"finland": _rings(transform(project, finland).simplify(FINLAND_TOLERANCE_M)), "neighbours": {}}
    for feature in json.load(open(natural_earth_geojson, encoding="utf-8"))["features"]:
        code = feature["properties"]["ADM0_A3"]
        if code in NEIGHBOURS:
            area = transform(project, shape(feature["geometry"]).intersection(REGION)).simplify(NEIGHBOUR_TOLERANCE_M)
            data["neighbours"][code] = _rings(area)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main(*sys.argv[1:3])
