"""Rebuild tests/data/planet_sky_reference.json from Skyfield + JPL DE421 (dev-only, not shipped):
    python -m venv /tmp/sf && /tmp/sf/bin/pip install skyfield==1.55 skyfield-data==7.0.0 && /tmp/sf/bin/python tools/build_planet_reference.py
Same calls as the sibling sky-api reference (commit 10ad0a3): (earth + wgs84.latlon).at(t).observe(target).apparent().altaz()."""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from theroadragetrip.calendar import FINLAND_TZ  # run with PYTHONPATH=src
from skyfield.api import Loader, wgs84
from skyfield.magnitudelib import planetary_magnitude
from skyfield_data import get_skyfield_data_path

BODIES = ("mercury", "venus", "mars", "jupiter", "saturn", "uranus")
TARGETS = {"mercury": "mercury", "venus": "venus", "mars": "mars barycenter", "jupiter": "jupiter barycenter",
           "saturn": "saturn barycenter", "uranus": "uranus barycenter"}
SITES = {"site_n1": (65.0, 25.0, 15.0), "site_s": (60.0, 25.0, 10.0), "site_n2": (69.0, 27.0, 90.0),
         "site_e": (62.5, 29.5, 80.0)}
# (site, Finnish local time, fold): spread over 2020-2040, DST gaps/folds, dusk/dawn horizon crossings
CASES = [(site, when, 0) for site in SITES for when in (
    "2020-01-15T05:30", "2021-04-02T21:00", "2023-08-20T23:30", "2024-12-05T07:00", "2026-03-29T04:30",
    "2026-06-20T22:30", "2026-11-09T00:30", "2026-11-09T03:30", "2028-02-10T18:00", "2031-09-01T04:45",
    "2035-05-05T03:15", "2039-12-31T23:59")] + [
    ("site_n1", "2026-10-25T03:30", 0), ("site_n1", "2026-10-25T03:30", 1), ("site_s", "2026-03-29T02:30", 0),
    ("site_s", "2026-03-29T03:30", 0), ("site_s", "2026-10-25T03:30", 1)]


def main() -> None:
    loader = Loader(get_skyfield_data_path())
    # Fresh IERS UT1-UTC (downloaded here, dev-only): the bundled finals file expires and then skews times by up to 14 s (0.06 degrees)
    import tempfile
    eph, ts = loader("de421.bsp"), Loader(tempfile.mkdtemp()).timescale(builtin=False)
    rows = []
    for site, when, fold in CASES:
        lat, lon, elevation = SITES[site]
        local = datetime.fromisoformat(when).replace(tzinfo=FINLAND_TZ, fold=fold)
        utc = local.astimezone(timezone.utc)
        observer, t = eph["earth"] + wgs84.latlon(lat, lon, elevation_m=elevation), ts.from_datetime(utc)
        bodies = {}
        for name in BODIES:
            astrometric = observer.at(t).observe(eph[TARGETS[name]])
            alt, az, _ = astrometric.apparent().altaz()
            bodies[name] = {"alt": round(float(alt.degrees), 5), "true_az": round(float(az.degrees), 5),
                            "mag": round(float(planetary_magnitude(observer.at(t).observe(eph[name if name in ("mercury", "venus") else TARGETS[name]]).apparent())), 3)}
        rows.append({"site": site, "lat": lat, "lon": lon, "elevation": elevation, "local": when, "fold": fold,
                     "utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "bodies": bodies})
    out = {"source": "Skyfield 1.55 + JPL DE421 (airless apparent altaz)", "rows": rows}
    Path(__file__).resolve().parents[1].joinpath("tests/data/planet_sky_reference.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
