#!/usr/bin/env python3
"""Pin/filter the NASA SAO catalogue and bake its magnitude-separated sky maps."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

SOURCE_URL = "https://heasarc.gsfc.nasa.gov/FTP/heasarc/dbase/tdat_files/heasarc_sao.tdat.gz"
SOURCE_SHA256 = "8ad1b253efc0b5386b4e3b8e5150eab4c54b61c090cd3eae6a88eed833702a67"
STARS_SHA256 = "cbd2a4c1b0cce77070ad2df23a2276e90d17ddc8ef7ec4166b9275a9b1431644"
OUT = Path(__file__).resolve().parents[1] / "godot/assets/sky"
WIDTH, HEIGHT = 4096, 2048
BAKED_YEAR = 2026.0


def select_stars(rows):
    """Retain the source's inclusive visual cutoff and all finite stellar rows."""
    selected, rejected = [], Counter()
    for row in rows:
        if not re.fullmatch(r"SAO \d+", row.get("name", "")):
            rejected["non_stellar"] += 1
            continue
        try:
            values = [float(row[key]) for key in ("ra", "dec", "vmag", "proper_motion_ra_fk5", "proper_motion_dec_fk5")]
            if not all(math.isfinite(value) for value in values) or not (0 <= values[0] < 360 and -90 <= values[1] <= 90):
                raise ValueError("invalid coordinates")
        except (KeyError, ValueError, TypeError):
            rejected["invalid_fields"] += 1
            continue
        if values[2] > 6.0:
            rejected["fainter_than_limit"] += 1
            continue
        selected.append([int(row["name"].split()[1]), *values, row.get("spect_type", "")])
    selected.sort(key=lambda row: row[0])
    if len({row[0] for row in selected}) != len(selected):
        raise ValueError("duplicate SAO identifiers")
    return selected, dict(sorted(rejected.items()))


def direction(star, year=BAKED_YEAR):
    """J2000 equatorial direction advanced by FK5 dRA/dt and dDec/dt."""
    _, ra, dec, _, pm_ra, pm_dec, _ = star
    ra, dec = math.radians(ra), math.radians(dec)
    years = year - 2000.0
    # HEASARC stores FK5 RA motion in seconds of time/year, not mu-alpha*cos(dec).
    dra, ddec = math.radians(pm_ra * 15 / 3600), math.radians(pm_dec / 3600)
    p = [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    east = [-math.sin(ra), math.cos(ra), 0.0]
    north = [-math.sin(dec) * math.cos(ra), -math.sin(dec) * math.sin(ra), math.cos(dec)]
    moved = [p[i] + years * (east[i] * dra * math.cos(dec) + north[i] * ddec) for i in range(3)]
    length = math.sqrt(sum(value * value for value in moved))
    return [value / length for value in moved]


def encoded_star(magnitude):
    band = max(0, min(6, math.ceil(magnitude)))
    return band, .32 * 10 ** (-.2 * (magnitude - band))


def bake(stars, output=OUT, width=WIDTH, height=HEIGHT):
    from PIL import Image
    import numpy as np

    maps = [np.zeros((height, width, 4), dtype=np.float32) for _ in range(2)]
    for star in stars:
        x, y, z = direction(star)
        ra, dec = math.atan2(y, x) % math.tau, math.asin(z)
        u, v = ra / math.tau * width - .5, (.5 - dec / math.pi) * height - .5
        band, amplitude = encoded_star(star[3])
        sigma_y = .55
        sigma_x = sigma_y / max(.002, math.cos(dec))
        for py in range(math.floor(v - 3 * sigma_y), math.ceil(v + 3 * sigma_y) + 1):
            if py < 0 or py >= height:
                continue
            for px in range(math.floor(u - 3 * sigma_x), math.ceil(u + 3 * sigma_x) + 1):
                value = amplitude * math.exp(-.5 * (((px - u) / sigma_x) ** 2 + ((py - v) / sigma_y) ** 2))
                maps[band // 4][py, px % width, band % 4] += value
    output.mkdir(parents=True, exist_ok=True)
    for index, pixels in enumerate(maps):
        Image.fromarray(np.rint(np.clip(pixels, 0, 1) * 255).astype(np.uint8), "RGBA").save(output / f"stars_{index}.png", optimize=False, compress_level=9)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="pinned official heasarc_sao.tdat.gz; otherwise rebuild from bundled subset")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    if args.source:
        source = args.source.read_bytes()
        if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
            raise SystemExit("SAO source hash does not match the pinned release")
        header, data = gzip.decompress(source).decode("ascii").split("<DATA>\n")
        fields = next(line for line in header.splitlines() if line.startswith("line[1] = ")).split(" = ")[1].split()
        rows = [dict(zip(fields, line.split("|"))) for line in data.splitlines() if line and not line.startswith("<")]
        stars, rejected = select_stars(rows)
        if len(rows) != 258944 or len(stars) != 5092:
            raise SystemExit("unexpected source population")
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "stars.json").write_text(json.dumps(stars, separators=(",", ":")) + "\n", encoding="utf-8")
        manifest = {
            "catalog": "NASA HEASARC SAO I/131A", "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
            "source_count": len(rows), "selected_count": len(stars), "rejected": rejected,
            "license": "US-government-public-domain",
            "rights_evidence": ["https://ntrs.nasa.gov/citations/19660017606", "https://ntrs.nasa.gov/citations/19840015351", "https://data.nasa.gov/dataset/smithsonian-astrophysical-observatory-star-catalog"],
            "epoch": "J2000 FK5", "baked_motion_epoch": BAKED_YEAR, "supported_years": [2020, 2040],
            "fields": ["SAO integer ID", "RA degrees J2000", "Dec degrees J2000", "visual magnitude", "FK5 dRA seconds of time/year", "FK5 dDec arcsec/year", "spectral type"],
            "photometry": "Mixed historical visual/photovisual estimates, 0.1 magnitude precision; not uniformly Johnson V. Inclusive native visual<=6.0; see docs/star-sky.md.",
            "projection": "RA increasing in u; declination +90 to -90 in v; seven independent magnitude bands in two RGBA maps, linear uncompressed no mipmaps",
            "dimensions": [WIDTH, HEIGHT], "color": "neutral white; photographic and visual magnitudes are not treated as B-V",
        }
    else:
        if hashlib.sha256((args.output / "stars.json").read_bytes()).hexdigest() != STARS_SHA256:
            raise SystemExit("bundled SAO subset differs from the pinned filter; rebuild from the original source")
        stars = json.loads((args.output / "stars.json").read_text())
        manifest = json.loads((args.output / "source.json").read_text())
    bake(stars, args.output)
    manifest["asset_sha256"] = {name: hashlib.sha256((args.output / name).read_bytes()).hexdigest() for name in ("stars.json", "stars_0.png", "stars_1.png")}
    (args.output / "source.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"SAO stars: {len(stars)}; atlas: {WIDTH}x{HEIGHT} x 2 RGBA")


if __name__ == "__main__":
    main()
