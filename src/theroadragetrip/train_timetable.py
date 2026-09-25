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
SUPPORTED_VERSION = 4
# How close a train's station-to-station path must pass a route's midpoint.
# Straight lines between stations cut corners, so this is generous; lines
# closer together than this would share trains (Finnish lines rarely are).
MATCH_RADIUS_M = 2000.0
# Commuter lines run every few minutes around Helsinki; following only
# long-distance trains keeps traffic (and the next-train box) meaningful.
FOLLOWED_CATEGORIES = {"long_distance"}
# A timetable station counts as on this map within this distance of a route.
STATION_ON_ROUTE_M = 1500.0
# Dwell at a journey's first/last station, where GTFS gives no stop length
# (arrival == departure): long enough to read as "terminates/starts here".
TERMINAL_DWELL_S = 120
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class ScheduledPass:
    """One timetable train crossing one of this map's train routes."""

    train_type: str
    number: str
    origin: str
    destination: str
    days: int  # bit 0 = Monday ... bit 6 = Sunday, of the service day
    seconds: int  # GTFS arrival at the first stop on the route, else time at its midpoint (may exceed 24 h)
    route_index: int
    direction: int  # +1 enters at the route start, -1 at its end
    heading: str  # compass direction of travel, for debugging
    # Stops on this route in travel order: (distance of the station along
    # the route, dwell in timetable seconds, station name, GTFS arrival,
    # GTFS departure, stopping position (the platform's, else the
    # station's), platform track number or "", "origin"/"terminus"/"" when
    # the journey starts/ends there). Timing points are absent.
    stops: Tuple[tuple, ...] = ()
    # Journey positions just before / after this map's part of the trip
    # (None where it starts / ends here): where it enters and leaves.
    came_from: Optional[Tuple[float, float]] = None
    going_to: Optional[Tuple[float, float]] = None

    @property
    def label(self) -> str:
        hours, rest = divmod(self.seconds, 3600)
        return f"{self.train_type} {self.number} {self.heading} {hours % 24:02d}:{rest // 60:02d}"


@dataclass(frozen=True)
class StationCall:
    """One timetable train arriving at one station on this map."""

    train_type: str
    number: str
    origin: str
    destination: str
    days: int
    seconds: int  # GTFS arrival time at the station
    station: str

    @property
    def label(self) -> str:
        return f"{self.train_type} {self.number} {self.station}"


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
    # The matched OSM station position (entries 3-4) when the importer found
    # one - that is where the platform is on this map - else GTFS's own.
    stations = {code: to_metres(*(entry[3:5] if len(entry) >= 5 else entry[:2])) for code, entry in timetable["stations"].items()}
    # Where on the station the train stops: its timetable platform (a
    # position on that very track), else the station itself.
    platforms = {
        (code, track): to_metres(lat, lon)
        for code, tracks in timetable.get("platforms", {}).items() for track, (lat, lon) in tracks.items()
    }
    prepared = []
    for train in timetable["trains"]:
        if train.get("category") not in FOLLOWED_CATEGORIES:
            continue
        # (station position, arrival, code, departure, stops here, platform
        # track number, stopping position)
        stops = [
            (stations[code], arrival, code, departure, stops_here, track, platforms.get((code, track), stations[code]))
            for code, arrival, departure, stops_here, track in train["stops"] if code in stations
        ]
        if len(stops) < 2:
            continue
        path = [stop[0] for stop in stops]
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
    has_track: Optional[Callable[[Tuple[float, float]], bool]] = None,
) -> List[ScheduledPass]:
    """Every timetable train that passes near a route, with its entry end
    and its time there. Runs once per route rebuild, never per frame.
    has_track(point): whether any track of the map is near a station - it
    may be a stop even off the network's longest line (e.g. a terminus
    beside a yard)."""
    if prepared is None:
        prepared = prepare_timetable(timetable, to_metres)
    ends = []
    for route in routes:
        mx, my, _ = route.point_at(route.length / 2)
        ends.append((route.points[0], (mx, my), route.points[-1]))
    passes = []
    on_route: List[Dict[str, Optional[float]]] = [{} for _ in routes]  # code -> distance along route

    def station_along(index: int, code: str, point) -> Optional[float]:
        if code not in on_route[index]:
            route = routes[index]
            distance, along, _, _ = _project(point, route.points, route.cumulative)
            near = distance <= STATION_ON_ROUTE_M or (has_track is not None and has_track(point))
            on_route[index][code] = along if near else None
        return on_route[index][code]

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
            route_stops = []
            local_calls = []
            for call_index, (point, arrival, code, departure, stops_here, track, stop_point) in enumerate(stops):
                along = station_along(index, code, point) if stops_here else None
                if along is None:
                    continue
                terminal = call_index in (0, len(stops) - 1)
                dwell = TERMINAL_DWELL_S if terminal else departure - arrival
                if dwell > 0:
                    local_calls.append(call_index)
                    end = "origin" if call_index == 0 else "terminus" if call_index == len(stops) - 1 else ""
                    route_stops.append((along, dwell, timetable["stations"][code][2], arrival, departure, stop_point, track, end))
            # Journey order is travel order (projections onto the network
            # line can misorder stations it only passes nearby).
            first, last = (min(local_calls), max(local_calls)) if local_calls else (segment + 1, segment)
            came_from = stops[first - 1][0] if first > 0 else None
            going_to = stops[last + 1][0] if last + 1 < len(stops) else None
            passes.append(ScheduledPass(
                train_type=train["type"], number=train["number"],
                origin=train["origin"], destination=train["destination"], days=train["days"],
                # When the train should be at its first stop here (so it
                # can be spawned to arrive on time), else mid-route.
                seconds=route_stops[0][3] if route_stops else round(seconds_a + (seconds_b - seconds_a) * t),
                route_index=index, direction=direction,
                heading=COMPASS[round(bearing / 45) % 8],
                stops=tuple(route_stops),
                came_from=came_from, going_to=going_to,
            ))
    return passes


def station_calls(timetable: dict, prepared: list, routes: Sequence) -> List[Tuple[str, Tuple[float, float], List[StationCall]]]:
    """(name, position, arrivals) for each timetable station within
    STATION_ON_ROUTE_M of a train route - where passengers will get off.
    Trains starting at a station bring nobody, so their first stop is
    skipped. Built once per route rebuild."""
    route_points = [point for route in routes for point in route.points]
    if not route_points:
        return []
    minx = min(p[0] for p in route_points) - STATION_ON_ROUTE_M
    maxx = max(p[0] for p in route_points) + STATION_ON_ROUTE_M
    miny = min(p[1] for p in route_points) - STATION_ON_ROUTE_M
    maxy = max(p[1] for p in route_points) + STATION_ON_ROUTE_M
    near: Dict[str, Optional[Tuple[Tuple[float, float], List[StationCall]]]] = {}
    for train, stops, _, _, _ in prepared:
        for point, seconds, code, _, stops_here, _, _ in stops[1:]:
            if not stops_here:
                continue
            if code not in near:
                if not (minx <= point[0] <= maxx and miny <= point[1] <= maxy) or not any(
                    math.dist(point, p) <= STATION_ON_ROUTE_M for p in route_points
                ):
                    near[code] = None
                    continue
                near[code] = (point, [])
            if near[code] is not None:
                near[code][1].append(StationCall(
                    train["type"], train["number"], train["origin"], train["destination"],
                    train["days"], seconds, timetable["stations"][code][2],
                ))
    return [(timetable["stations"][code][2], point, calls) for code, entry in sorted(near.items()) if entry for point, calls in [entry]]


class TimetableClock:
    """Turns ScheduledPasses (or StationCalls) into concrete local times around the game
    date and hands out those crossed since the previous call - a bisect
    per frame, the day's list rebuilt only when the date changes."""

    def __init__(self, passes: Sequence[ScheduledPass]) -> None:
        self.passes = list(passes)
        self._day: Optional[date] = None
        self._times: List[datetime] = []
        self._events: List[ScheduledPass] = []
        self._last: Optional[datetime] = None
        self._until: Optional[datetime] = None

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

    def next_after(self, now: datetime) -> Optional[Tuple[datetime, ScheduledPass]]:
        """The next scheduled pass after now (within the built window)."""
        if self._day != now.date():
            self._build(now.date())
        index = bisect.bisect_right(self._times, now)
        return (self._times[index], self._events[index]) if index < len(self._times) else None

    def continue_from(self, other: "TimetableClock") -> None:
        self._last, self._until = other._last, other._until

    @property
    def started(self) -> bool:
        """False until the first due() call - the game-start moment."""
        return self._last is not None

    def events_between(self, start: datetime, end: datetime) -> List[Tuple[datetime, ScheduledPass]]:
        """(time, pass) for passes scheduled in [start, end] - a window of
        at most a day ending near now."""
        if self._day != end.date():
            self._build(end.date())
        lo, hi = bisect.bisect_left(self._times, start), bisect.bisect_right(self._times, end)
        return list(zip(self._times[lo:hi], self._events[lo:hi]))

    def due(self, now: datetime, lookahead: timedelta = timedelta(0)) -> List[ScheduledPass]:
        """Passes scheduled in (end of the previous window, now + lookahead]
        - each handed out once, even as the lookahead changes with the game
        speed. The first call only starts the clock (no backlog burst on
        load or after a clock jump)."""
        last, self._last = self._last, now
        until = now + min(lookahead, timedelta(hours=6))
        if last is None or now < last or now - last > timedelta(hours=6):
            self._until = until
            return []
        start = self._until
        if until <= start:
            return []
        self._until = until
        if self._day != now.date():
            self._build(now.date())
        return self._events[bisect.bisect_right(self._times, start):bisect.bisect_right(self._times, until)]
