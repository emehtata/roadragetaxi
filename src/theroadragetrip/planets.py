"""Mercury..Uranus for the 3D sky (docs/planet-sky.md): PyEphem (VSOP87), airless apparent topocentric."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from functools import lru_cache

import ephem

from .calendar import finnish_utc, grid_azimuth

logger = logging.getLogger(__name__)

BODIES = ("mercury", "venus", "mars", "jupiter", "saturn", "uranus")
SOURCE = f"PyEphem {ephem.__version__} VSOP87 apparent topocentric, airless"
SUPPORTED_YEARS = (2020, 2040)
BUCKET_S = 10  # game seconds; with 0.0001 deg of position and 10 m of height it is the cache key
CACHE_SIZE = 128
MAX_ELEVATION_M = (-500.0, 9000.0)


def planet_sky_state(moment: datetime, latitude: float, longitude: float, elevation: float = 0.0) -> dict:
    """Six-body state for a Finnish local game time, at most 10 s/0.0001 deg old; unavailable ones carry a reason."""
    utc = finnish_utc(moment).replace(tzinfo=timezone.utc)
    height = float(elevation) if isinstance(elevation, (int, float)) and MAX_ELEVATION_M[0] <= elevation <= MAX_ELEVATION_M[1] else 0.0
    if not (isinstance(latitude, (int, float)) and isinstance(longitude, (int, float))
            and math.isfinite(latitude) and math.isfinite(longitude) and abs(latitude) <= 90 and abs(longitude) <= 180):
        logger.warning("Planet sky unavailable: invalid observer %r, %r", latitude, longitude)
        return _unavailable(utc, [latitude, longitude], "invalid observer coordinates")
    return _planet_sky_state(int(utc.timestamp()) // BUCKET_S * BUCKET_S, round(latitude, 4), round(longitude, 4), round(height / 10.0) * 10.0)


def _unavailable(utc: datetime, observer: list, reason: str) -> dict:
    return {"supported": False, "reason": reason, "utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "observer": observer, "source": SOURCE, "bodies": []}


@lru_cache(maxsize=CACHE_SIZE)
def _planet_sky_state(timestamp: int, latitude: float, longitude: float, elevation: float) -> dict:
    utc = datetime.fromtimestamp(timestamp, timezone.utc)
    observer_state = [latitude, longitude, elevation]
    if not SUPPORTED_YEARS[0] <= utc.year <= SUPPORTED_YEARS[1]:
        logger.warning("Planet sky unavailable: %s is outside %d-%d", utc.year, *SUPPORTED_YEARS)
        return _unavailable(utc, observer_state, "date outside the validated 2020-2040 range")
    observer = ephem.Observer()
    observer.lat, observer.lon, observer.elevation = math.radians(latitude), math.radians(longitude), elevation
    observer.pressure = 0  # airless: refraction is omitted, the shader fades 0-5 degrees instead
    observer.date = ephem.Date(utc.replace(tzinfo=None))
    bodies = []
    for name in BODIES:
        try:
            body = getattr(ephem, name.capitalize())(observer)
            alt, true_az, mag = math.degrees(float(body.alt)), math.degrees(float(body.az)), float(body.mag)
        except Exception as error:  # noqa: BLE001 - one body must not take the game down
            logger.warning("Planet sky: %s unavailable: %s", name, error)
            bodies.append({"id": name, "unavailable": "provider error"})
            continue
        if not all(map(math.isfinite, (alt, true_az, mag))):
            logger.warning("Planet sky: %s has a non-finite position or magnitude", name)
            bodies.append({"id": name, "unavailable": "non-finite position or magnitude"})
            continue
        az = grid_azimuth(true_az, latitude, longitude)
        a, z = math.radians(alt), math.radians(az)
        bodies.append({"id": name, "alt": round(alt, 4), "az": round(az, 4), "mag": round(mag, 2),
                       "dir": [round(math.sin(z) * math.cos(a), 6), round(math.sin(a), 6), round(-math.cos(z) * math.cos(a), 6)]})
    return {"supported": True, "utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "observer": observer_state,
            "source": SOURCE, "bodies": bodies}
