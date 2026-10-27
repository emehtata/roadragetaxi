"""Lunar phase and daily rise/transit/set calculations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import degrees
from typing import Optional

import ephem

from .calendar import finnish_local_time, finnish_utc


@dataclass(frozen=True)
class MoonInfo:
    rise: Optional[datetime]
    transit: Optional[datetime]
    set: Optional[datetime]
    phase: str
    illumination: float
    age_days: float


def moon_position_at(moment: datetime, latitude: float, longitude: float) -> tuple[float, float, float]:
    """Apparent altitude, true-north azimuth and illuminated fraction."""
    observer = ephem.Observer()
    observer.lat, observer.lon = str(latitude), str(longitude)
    observer.date = ephem.Date(finnish_utc(moment))
    moon = ephem.Moon(observer)
    return degrees(float(moon.alt)), degrees(float(moon.az)), moon.phase / 100.0


def moon_info_on(day: date, latitude: float, longitude: float) -> MoonInfo:
    """Moon events and phase for one Finnish local calendar day."""
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    observer = ephem.Observer()
    observer.lat, observer.lon = str(latitude), str(longitude)
    observer.date = ephem.Date(finnish_utc(start))

    def event(method: str) -> Optional[datetime]:
        try:
            utc = getattr(observer, method)(ephem.Moon()).datetime()
        except (ephem.AlwaysUpError, ephem.NeverUpError):
            return None
        local = finnish_local_time(utc)
        return local if start <= local < end else None

    noon_utc = ephem.Date(finnish_utc(start + timedelta(hours=12)))
    moon = ephem.Moon(noon_utc)
    age_days = float(noon_utc - ephem.previous_new_moon(noon_utc))
    names = ("new", "waxing crescent", "first quarter", "waxing gibbous", "full",
             "waning gibbous", "last quarter", "waning crescent")
    phase = names[int(age_days / 29.530588 * 8 + 0.5) % 8]
    return MoonInfo(event("next_rising"), event("next_transit"), event("next_setting"),
                    phase, moon.phase / 100.0, age_days)
