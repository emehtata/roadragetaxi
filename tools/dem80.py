"""MML KM10 (10 m) GeoTIFFs -> 80 m RRD1 tiles + dem80.json (docs/dem-terrain-80m.md).

    MML_API_KEY=... .venv/bin/python tools/dem80.py download --out km10/
    .venv/bin/python tools/dem80.py convert km10/*.tif --out ~/.cache/.../dem80 --source-date MM/YYYY
Test source (no key; WGS84, reprojected to EPSG:3067 on the 10 m grid):
    .venv/bin/python tools/dem80.py download --source copernicus --out ~/.cache/copernicus-dem30
    .venv/bin/python tools/dem80.py convert --source copernicus ~/.cache/copernicus-dem30/*.tif --out ...

The API key comes only from the MML_API_KEY environment variable; it is never
printed or written. Heights stay absolute N2000; NoData stays NoData.
"""
import argparse
from functools import lru_cache
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from theroadragetrip.osm import elevation as el  # noqa: E402

MML_OGC_PROCESSES = "https://avoin-paikkatieto.maanmittauslaitos.fi/tiedostopalvelu/ogcproc/v1/processes"
OULU_BBOX = (400000.0, 7180000.0, 460000.0, 7240000.0)  # EPSG:3067 x0, y0, x1, y1
FINLAND_BBOX = (50000.0, 6600000.0, 740000.0, 7800000.0)
COP_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
COP_ATTRIBUTION = ("produced using Copernicus WorldDEM-30 \u00a9 DLR e.V. 2010-2014 and \u00a9 Airbus Defence and Space GmbH "
                   "2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved")
BLOCK = int(el.DEM80_STEP // 10)  # 8x8 10 m cells per 80 m sample


def read_geotiff(path):
    """(float64 heights north-up with NaN NoData, west m, north m, cell m) from the GeoTIFF tags."""
    with Image.open(path) as image:
        tags = image.tag_v2
        heights = np.asarray(image.convert("F"), dtype=np.float64)
        sx, sy = tags[33550][:2]
        _, _, _, west, north, _ = tags[33922][:6]
        nodata = tags.get(42113)
    if sx != sy:
        raise ValueError(f"{path}: non-square cells {sx} x {sy}")
    if nodata is not None:
        heights[heights == np.float32(float(str(nodata).strip("\x00 ")))] = np.nan  # this file's own NoData
    return heights, float(west), float(north), float(sx)


def block_mean(a):
    """Mean of each 8x8 block, NoData (NaN) skipped; NaN if all 64 are NoData."""
    rows, cols = a.shape[0] // BLOCK, a.shape[1] // BLOCK
    blocks = a[:rows * BLOCK, :cols * BLOCK].reshape(rows, BLOCK, cols, BLOCK)
    valid = ~np.isnan(blocks)
    count = valid.sum(axis=(1, 3))
    total = np.where(valid, blocks, 0.0).sum(axis=(1, 3))
    return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def index_for(tiles, sources, source_date, vertical="N2000", attribution=None):
    return {
        "crs": el.DEM80_CRS, "vertical": vertical, "step_m": el.DEM80_STEP, "tile_size": el.DEM80_SIZE,
        "scale": el.DEM80_SCALE, "nodata": el.DEM80_NODATA, "format": "RRD1 v1, zlib int16, rows along +y",
        "tiles": [{"i": i, "j": j, "file": f"dem80_{i}_{j}.bin", "bounds": list(el.tile_bounds(i, j))} for i, j in sorted(tiles)],
        "sources": sorted(sources), "source_date": source_date,
        "attribution": attribution or f"Contains data from the National Land Survey of Finland (Maanmittauslaitos) Elevation model 10 m (KM10) "
                       f"{source_date}, CC BY 4.0",
    }


def convert(src_tifs, out_dir, bbox=None, source_date="unknown"):
    """Mosaic the sheets on the 10 m grid, then 8x8 block means aligned to the 80 m tile grid."""
    sheets = [read_geotiff(p) for p in src_tifs]
    for _, west, north, step in sheets:
        if step != 10.0 or west % 10 or north % 10:
            raise ValueError("expects 10 m sheets on the 10 m grid")
    s80 = el.DEM80_STEP
    x0 = min(w for _, w, _, _ in sheets) // s80 * s80
    y0 = min(n - h.shape[0] * 10 for h, _, n, _ in sheets) // s80 * s80
    x1 = -(-max(w + h.shape[1] * 10 for h, w, _, _ in sheets) // s80) * s80
    y1 = -(-max(n for _, _, n, _ in sheets) // s80) * s80
    mosaic = np.full((int((y1 - y0) // 10), int((x1 - x0) // 10)), np.nan)  # rows along +y
    for h, west, north, _ in sheets:
        r0, c0 = int((north - y0) // 10) - h.shape[0], int((west - x0) // 10)
        target = mosaic[r0:r0 + h.shape[0], c0:c0 + h.shape[1]]
        flipped = h[::-1]
        np.copyto(target, flipped, where=~np.isnan(flipped))
    return write_tiles(block_mean(mosaic), x0, y0, out_dir, bbox, index_for([], [Path(p).name for p in src_tifs], source_date))


def write_tiles(grid, x0, y0, out_dir, bbox, index):
    """80 m grid (rows along +y, grid[0, 0] at x0, y0) -> non-empty tiles + dem80.json."""
    s80 = el.DEM80_STEP
    x1, y1 = x0 + grid.shape[1] * s80, y0 + grid.shape[0] * s80
    gx0, gy0 = int(x0 // s80), int(y0 // s80)  # global 80 m sample index of grid[0, 0]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n, written = el.DEM80_SIZE, []
    i0, j0 = el.tile_of(x0, y0)
    i1, j1 = el.tile_of(x1 - 1, y1 - 1)
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            if bbox and not (el.tile_bounds(i, j)[0] < bbox[2] and el.tile_bounds(i, j)[2] > bbox[0]
                             and el.tile_bounds(i, j)[1] < bbox[3] and el.tile_bounds(i, j)[3] > bbox[1]):
                continue
            t = np.full((n, n), np.nan)
            r_lo, c_lo = max(j * n - gy0, 0), max(i * n - gx0, 0)
            r_hi, c_hi = min((j + 1) * n - gy0, grid.shape[0]), min((i + 1) * n - gx0, grid.shape[1])
            t[r_lo + gy0 - j * n:r_hi + gy0 - j * n, c_lo + gx0 - i * n:c_hi + gx0 - i * n] = grid[r_lo:r_hi, c_lo:c_hi]
            if np.isnan(t).all():
                continue
            (out_dir / f"dem80_{i}_{j}.bin").write_bytes(el.encode_tile(i, j, t))
            written.append((i, j))
    index["tiles"] = index_for(written, [], "")["tiles"]
    (out_dir / "dem80.json").write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
    return index


def cop_name(lat, lon):
    return f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM"


def cop_tiles(bbox):
    """(lat, lon) of the 1x1 degree Copernicus tiles under an EPSG:3067 bbox."""
    from pyproj import Transformer
    if tuple(bbox) == FINLAND_BBOX:  # the land tiles only, not the Swedish/Russian corners of the bbox
        return [(lat, lon) for lat in range(59, 71) for lon in range(19, 32)]
    w, s, e, n = Transformer.from_crs(3067, 4326, always_xy=True).transform_bounds(*bbox, densify_pts=21)
    return [(lat, lon) for lat in range(int(np.floor(s)), int(np.floor(n)) + 1) for lon in range(int(np.floor(w)), int(np.floor(e)) + 1)]


def fetch_copernicus(bbox, cache_dir):
    """Downloads the missing tiles over plain HTTPS (public bucket, no key); returns the paths."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for lat, lon in cop_tiles(bbox):
        name = cop_name(lat, lon)
        path = cache_dir / f"{name}.tif"
        if not path.is_file():
            try:
                with urllib.request.urlopen(COP_URL.format(name=name), timeout=300) as reply:
                    path.with_suffix(".part").write_bytes(reply.read())
            except urllib.error.HTTPError as error:
                if error.code in (403, 404):  # ocean: the bucket has no tile
                    print(name, "no tile (sea)")
                    continue
                raise
            path.with_suffix(".part").rename(path)
        print(name, path.stat().st_size, "bytes")
        paths.append(path)
    return paths


def read_copernicus(path):
    """(heights north-up, NaN NoData, lon0, lat_top, dlon, dlat); ValueError unless EPSG:4326 and the
    1x1 degree bounds named in the file name."""
    with Image.open(path) as image:
        tags = image.tag_v2
        heights = np.asarray(image.convert("F"), dtype=np.float64)
        dlon, dlat = tags[33550][:2]
        _, _, _, lon0, lat1, _ = tags[33922][:6]
        keys = tags.get(34735, ())
        nodata = tags.get(42113)
    geo = {keys[k]: keys[k + 3] for k in range(4, len(keys) - 3, 4)}
    if geo.get(2048) != 4326:
        raise ValueError(f"{path}: not EPSG:4326 ({geo.get(2048)})")
    name = Path(path).stem
    lat = int(name[23:25]) * (1 if name[22] == "N" else -1)
    lon = int(name[30:33]) * (1 if name[29] == "E" else -1)
    if (round(lon0, 6), round(lat1, 6)) != (lon, lat + 1) or abs(heights.shape[1] * dlon - 1) > 1e-6 or abs(heights.shape[0] * dlat - 1) > 1e-6:
        raise ValueError(f"{path}: bounds {lon0},{lat1} {heights.shape} do not match {name}")
    if nodata is not None:
        heights[heights == np.float32(float(str(nodata).strip("\x00 ")))] = np.nan
    return heights, float(lon0), float(lat1), float(dlon), float(dlat)


def convert_copernicus(src_tifs, out_dir, bbox, source_date="2021 release"):
    """Copernicus GLO-30 -> nearest sample on the EPSG:3067 10 m grid -> the same 8x8 mean and tiles as KM10."""
    from pyproj import Transformer
    to_ll = Transformer.from_crs(3067, 4326, always_xy=True)
    read = lru_cache(maxsize=40)(read_copernicus)  # strips run south to north: a latitude band of sheets in memory
    s80 = el.DEM80_STEP
    x0, y0 = bbox[0] // s80 * s80, bbox[1] // s80 * s80
    cols, rows = int(-(-(bbox[2] - x0) // s80)), int(-(-(bbox[3] - y0) // s80))
    grid = np.full((rows, cols), np.nan)
    xs = x0 + 5 + 10 * np.arange(cols * BLOCK)
    strip = 16  # 80 m rows per transform batch: bounded memory
    for r0 in range(0, rows, strip):
        ys = y0 + 5 + 10 * np.arange(r0 * BLOCK, min(r0 + strip, rows) * BLOCK)
        gx, gy = np.meshgrid(xs, ys)
        lon, lat = to_ll.transform(gx, gy)
        fine = np.full(gx.shape, np.nan)
        for path in src_tifs:
            name = Path(path).stem
            lat0 = int(name[23:25]) * (1 if name[22] == "N" else -1)
            if lat.min() >= lat0 + 1 or lat.max() < lat0:
                continue
            h, lon0, lat1, dlon, dlat = read(path)
            c = np.floor((lon - lon0) / dlon).astype(int)
            r = np.floor((lat1 - lat) / dlat).astype(int)
            inside = (c >= 0) & (c < h.shape[1]) & (r >= 0) & (r < h.shape[0])
            fine[inside] = h[r[inside], c[inside]]
        grid[r0:r0 + strip] = block_mean(fine)
    index = index_for([], [Path(p).name for p in src_tifs], source_date, "EGM2008", COP_ATTRIBUTION)
    return write_tiles(grid, x0, y0, out_dir, bbox, index)


def download(bbox, out_dir, api_key):
    """Lists the MML OGC API processes into out_dir/processes.json. The KM10 process
    id and its inputs are not verified yet (needs a key), so no job is sent."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    auth = base64.b64encode(f"{api_key}:".encode()).decode()  # Basic realm="API-key required"
    request = urllib.request.Request(MML_OGC_PROCESSES + "?f=json", headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        processes = json.loads(reply.read())
    (out_dir / "processes.json").write_text(json.dumps(processes, indent=1, sort_keys=True))
    for p in processes.get("processes", []):
        print(p.get("id"), "-", p.get("title"))
    raise SystemExit(f"bbox {bbox}: pick the KM10 process from {out_dir / 'processes.json'} and verify its inputs "
                     "(docs/dem-terrain-80m.md); executing it is not implemented until verified.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--source", choices=("mml", "copernicus"), default="mml")
    c = sub.add_parser("convert")
    c.add_argument("tifs", nargs="+", type=Path)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--source", choices=("mml", "copernicus"), default="mml")
    c.add_argument("--source-date", default=None, help="KM10 delivery MM/YYYY (attribution)")
    for p in (d, c):
        p.add_argument("--bbox", type=lambda s: FINLAND_BBOX if s == "finland" else tuple(float(v) for v in s.split(",")),
                       default=OULU_BBOX, help="EPSG:3067 x0,y0,x1,y1 or finland (default Oulu)")
    args = parser.parse_args(argv)
    if args.cmd == "download" and args.source == "copernicus":
        fetch_copernicus(args.bbox, args.out)
    elif args.cmd == "download":
        key = os.environ.get("MML_API_KEY", "")
        if not key:
            raise SystemExit("MML_API_KEY is not set: get a free API key from Maanmittauslaitos and export it; nothing downloaded.")
        download(args.bbox, args.out, key)
    else:
        if args.source == "copernicus":
            index = convert_copernicus(args.tifs, args.out, args.bbox, args.source_date or "2021 release")
        else:
            index = convert(args.tifs, args.out, args.bbox, args.source_date or "unknown")
        print(len(index["tiles"]), "tiles ->", args.out)


if __name__ == "__main__":
    main()
