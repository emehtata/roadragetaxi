"""Solar eclipse for the 3D sky (docs/planet-sky.md): PyEphem Sun and Moon, topocentric, airless."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from functools import lru_cache

import ephem

from .calendar import finnish_utc, grid_azimuth
from .planets import BUCKET_S, CACHE_SIZE, MAX_ELEVATION_M

HORIZON_DEG = -0.833  # the Sun's upper limb on the horizon


def obscuration(separation: float, r_sun: float, r_moon: float) -> float:
    """Fraction of the Sun disc the Moon disc covers (lens area / Sun area); any one unit of angle."""
    if separation >= r_sun + r_moon:
        return 0.0
    if separation <= abs(r_moon - r_sun):
        return min(1.0, (r_moon / r_sun) ** 2)
    a = r_sun * r_sun * math.acos((separation ** 2 + r_sun ** 2 - r_moon ** 2) / (2 * separation * r_sun))
    b = r_moon * r_moon * math.acos((separation ** 2 + r_moon ** 2 - r_sun ** 2) / (2 * separation * r_moon))
    c = 0.5 * math.sqrt((-separation + r_sun + r_moon) * (separation + r_sun - r_moon)
                        * (separation - r_sun + r_moon) * (separation + r_sun + r_moon))
    return (a + b - c) / (math.pi * r_sun * r_sun)


def solar_eclipse_state(moment: datetime, latitude: float, longitude: float, elevation: float = 0.0) -> dict:
    """The eclipse for a Finnish local game time and an observer, at most 10 s/0.0001 deg old; angles in degrees."""
    utc = finnish_utc(moment).replace(tzinfo=timezone.utc)
    height = float(elevation) if isinstance(elevation, (int, float)) and MAX_ELEVATION_M[0] <= elevation <= MAX_ELEVATION_M[1] else 0.0
    if not (isinstance(latitude, (int, float)) and isinstance(longitude, (int, float))
            and math.isfinite(latitude) and math.isfinite(longitude) and abs(latitude) <= 90 and abs(longitude) <= 180):
        return _none()
    return _solar_eclipse_state(int(utc.timestamp()) // BUCKET_S * BUCKET_S, round(latitude, 4), round(longitude, 4), round(height / 10.0) * 10.0)


def _none() -> dict:
    return {"active": False, "phase": "none", "separation": 0.0, "sun_radius": 0.0, "moon_radius": 0.0,
            "magnitude": 0.0, "obscuration": 0.0}


@lru_cache(maxsize=CACHE_SIZE)
def _solar_eclipse_state(timestamp: int, latitude: float, longitude: float, elevation: float) -> dict:
    observer = ephem.Observer()
    observer.lat, observer.lon, observer.elevation = math.radians(latitude), math.radians(longitude), elevation
    observer.pressure = 0  # the same airless sky as the planets
    observer.date = ephem.Date(datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None))
    sun, moon = ephem.Sun(observer), ephem.Moon(observer)  # one ephemeris for both bodies
    sun_alt = math.degrees(float(sun.alt))
    r_sun, r_moon = math.degrees(float(sun.radius)), math.degrees(float(moon.radius))
    separation = math.degrees(float(ephem.separation((sun.az, sun.alt), (moon.az, moon.alt))))
    magnitude = (r_sun + r_moon - separation) / (2 * r_sun)
    if magnitude <= 0 or sun_alt <= HORIZON_DEG:
        return _none()
    phase = "total" if separation <= r_moon - r_sun else "annular" if separation <= r_sun - r_moon else "partial"
    state = {"active": True, "phase": phase, "separation": round(separation, 5), "sun_radius": round(r_sun, 5),
             "moon_radius": round(r_moon, 5), "magnitude": round(magnitude, 4),
             "obscuration": round(obscuration(separation, r_sun, r_moon), 4)}
    for name, body in (("sun", sun), ("moon", moon)):  # grid alt/az for the sky shader
        state[name + "_alt"] = round(math.degrees(float(body.alt)), 4)
        state[name + "_az"] = round(grid_azimuth(math.degrees(float(body.az)), latitude, longitude), 4)
    return state


def forced_total(state: dict) -> dict:
    """Test-only (--test-eclipse): the Moon centred on the Sun and wider, whatever the real sky shows."""
    return {**state, "active": True, "phase": "total", "separation": 0.0, "obscuration": 1.0,
            "moon_radius": max(state["moon_radius"], state["sun_radius"] * 1.03),
            "moon_alt": state["sun_alt"], "moon_az": state["sun_az"]} if state.get("active") else state
