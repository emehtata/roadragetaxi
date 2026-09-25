"""Real weekly passenger-train timetable -> scheduled trains on this map.

assets/railway_timetable.json.gz is made by tools/import_railway_timetable.py
from Digitraffic's GTFS (no network at runtime). Matching is geometric and
generic (no city special cases): a train's ordered stations form a rough
path; it concerns this map if that path passes near a train route's
midpoint, and it enters from whichever route end comes first along its own
journey - north, south, east, west or anything between.
"""
from __future__ import annotations

import bisect
import gzip
import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

try:
    from zoneinfo import ZoneInfo
    FINLAND = ZoneInfo("Europe/Helsinki")
except Exception:  # pragma: no cover - tzdata missing: DST handling degrades to EET
    FINLAND = timezone(timedelta(hours=2))

logger = logging.getLogger(__name__)

DEFAULT_TIMETABLE_PATH = Path(__file__).with_name("assets") / "railway_timetable.json.gz"
SUPPORTED_VERSION = 1
# How close a train's station-to-station path must pass a route's midpoint.
# Straight lines between stations cut corners, so this is generous; lines
# closer together than this would share trains (Finnish lines rarely are).
MATCH_RADIUS_M = 2000.0
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class ScheduledPass:
    """One timetable train crossing one of this map's train routes."""

    train_type: str
    number: str
    origin: str
    destination: str
    days: int  # bit 0 = Monday ... bit 6 = Sunday, of the service day
    seconds: int  # GTFS time at the route midpoint (may exceed 24 h)
    route_index: int
    direction: int  # +1 enters at the route start, -1 at its end
    heading: str  # compass direction of travel, for debugging

    @property
    def label(self) -> str:
        hours, rest = divmod(self.seconds, 3600)
        return f"{self.train_type} {self.number} {self.heading} {hours % 24:02d}:{rest // 60:02d}"


def load_timetable(path: Optional[Path] = None) -> Optional[dict]:
    """The imported timetable, or None (missing/broken) - trains then fall
    back to the phase-1 fixed interval."""
    path = Path(path) if path is not None else DEFAULT_TIMETABLE_PATH
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            document = json.load(source)
        if document.get("version") != SUPPORTED_VERSION:
            raise ValueError(f"unsupported version {document.get('version')!r}")
    except FileNotFoundError:
        logger.warning("Railway timetable missing (%s): run tools/import_railway_timetable.py", path)
        return None
    except (OSError, ValueError, EOFError) as exc:
        logger.warning("Railway timetable unusable (%s): %s", exc, path)
        return None
    logger.info(
        "Railway timetable %s: %d trains, valid %s..%s, downloaded %s",
        document.get("feed_version"), len(document["trains"]),
        document.get("valid_from"), document.get("valid_until"), document.get("downloaded_at"),
    )
    return document


def service_time(service_day: date, seconds: int) -> datetime:
    """GTFS time -> naive Finnish local time (the game clock's convention).
    GTFS counts from "noon minus 12 h" of the service day, which differs
    from midnight on DST-change days, and may run past 24 h."""
    noon = datetime.combine(service_day, time(12), FINLAND).astimezone(timezone.utc)
    return (noon + timedelta(seconds=seconds - 12 * 3600)).astimezone(FINLAND).replace(tzinfo=None)


def _project(point, path: List[Tuple[float, float]], cumulative: List[float]) -> Tuple[float, float, int, float]:
    """(distance to path, distance along path, segment index, t) of the
    closest point of `path` to `point`."""
    best = (math.inf, 0.0, 0, 0.0)
    px, py = point
    for i, ((ax, ay), (bx, by)) in enumerate(zip(path, path[1:])):
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq == 0 else min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        d = math.hypot(ax + dx * t - px, ay + dy * t - py)
        if d < best[0]:
            best = (d, cumulative[i] + t * (cumulative[i + 1] - cumulative[i]), i, t)
    return best


def prepare_timetable(timetable: dict, to_metres: Callable[[float, float], Tuple[float, float]]) -> list:
    """Each train's station path in world metres (with cumulative lengths
    and bbox) - route-independent, so done once per world load, not on
    every route rebuild. to_metres(lat, lon) -> (x east, y north)."""
    stations = {code: to_metres(lat, lon) for code, (lat, lon) in timetable["stations"].items()}
    prepared = []
    for train in timetable["trains"]:
        stops = [(stations[code], seconds) for code, seconds in train["stops"] if code in stations]
        if len(stops) < 2:
            continue
        path = [point for point, _ in stops]
        cumulative = [0.0]
        for a, b in zip(path, path[1:]):
            cumulative.append(cumulative[-1] + math.dist(a, b))
        xs, ys = [p[0] for p in path], [p[1] for p in path]
        prepared.append((train, stops, path, cumulative, (min(xs), min(ys), max(xs), max(ys))))
    return prepared


def match_timetable(
    timetable: dict,
    routes: Sequence,
    to_metres: Callable[[float, float], Tuple[float, float]] = None,
    radius_m: float = MATCH_RADIUS_M,
    prepared: Optional[list] = None,
) -> List[ScheduledPass]:
    """Every timetable train that passes near a route, with its entry end
    and its time there. Runs once per route rebuild, never per frame."""
    if prepared is None:
        prepared = prepare_timetable(timetable, to_metres)
    ends = []
    for route in routes:
        mx, my, _ = route.point_at(route.length / 2)
        ends.append((route.points[0], (mx, my), route.points[-1]))
    passes = []
    for train, stops, path, cumulative, (minx, miny, maxx, maxy) in prepared:
        for index, (start, middle, end) in enumerate(ends):
            if not (minx - radius_m <= middle[0] <= maxx + radius_m and miny - radius_m <= middle[1] <= maxy + radius_m):
                continue
            distance, _, segment, t = _project(middle, path, cumulative)
            if distance > radius_m:
                continue
            along_start = _project(start, path, cumulative)[1]
            along_end = _project(end, path, cumulative)[1]
            if along_start == along_end:
                continue  # both ends beyond the same end of the journey
            direction = 1 if along_start < along_end else -1
            entry, exit_ = (start, end) if direction > 0 else (end, start)
            bearing = math.degrees(math.atan2(exit_[0] - entry[0], exit_[1] - entry[1])) % 360
            seconds_a, seconds_b = stops[segment][1], stops[segment + 1][1]
            passes.append(ScheduledPass(
                train_type=train["type"], number=train["number"],
                origin=train["origin"], destination=train["destination"], days=train["days"],
                seconds=round(seconds_a + (seconds_b - seconds_a) * t),
                route_index=index, direction=direction,
                heading=COMPASS[round(bearing / 45) % 8],
            ))
    return passes


class TimetableClock:
    """Turns ScheduledPasses into concrete local times around the game
    date and hands out those crossed since the previous call - a bisect
    per frame, the day's list rebuilt only when the date changes."""

    def __init__(self, passes: Sequence[ScheduledPass]) -> None:
        self.passes = list(passes)
        self._day: Optional[date] = None
        self._times: List[datetime] = []
        self._events: List[ScheduledPass] = []
        self._last: Optional[datetime] = None

    def _build(self, day: date) -> None:
        events = []
        # Yesterday's service can still run today (GTFS times past 24 h).
        for service_day in (day - timedelta(days=1), day, day + timedelta(days=1)):
            bit = 1 << service_day.weekday()
            events.extend((service_time(service_day, p.seconds), p) for p in self.passes if p.days & bit)
        events.sort(key=lambda event: (event[0], event[1].label))
        self._times = [when for when, _ in events]
        self._events = [p for _, p in events]
        self._day = day

    def todays_count(self, now: datetime) -> int:
        if self._day != now.date():
            self._build(now.date())
        start = datetime.combine(now.date(), time())
        return bisect.bisect_left(self._times, start + timedelta(days=1)) - bisect.bisect_left(self._times, start)

    def due(self, now: datetime) -> List[ScheduledPass]:
        """Passes scheduled in (previous now, now]. The first call only
        starts the clock (no backlog burst on load or a clock jump back)."""
        last, self._last = self._last, now
        if last is None or now <= last or now - last > timedelta(hours=6):
            return []
        if self._day != now.date():
            self._build(now.date())
        return self._events[bisect.bisect_right(self._times, last):bisect.bisect_right(self._times, now)]
