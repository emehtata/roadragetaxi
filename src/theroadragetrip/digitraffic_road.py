"""Real road data from Fintraffic's Digitraffic Road API (docs/digitraffic-road-data.md).

Opt-in (Settings -> realtime road data, --road-digitraffic). Live roadworks
for the area around the player at the game time: fetched on a background
thread, never on the simulation tick, and matched onto the loaded OSM roads
as game Roadwork zones with their real restrictions (speed limit, closed
lane, closed road). Without the setting, offline or outside the state road
network, the game keeps its generated roadworks.

Every query is cached in SQLite forever (no expiration): the same area and
15-minute game-time window is never fetched twice, so a replay of a past
day, or a restart, reads exactly what was fetched before. The time window is
part of each query, so live play still sees new data every window.

Source: Fintraffic / digitraffic.fi, license CC 4.0 BY.
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

BASE_URL = "https://tie.digitraffic.fi"
USER_AGENT = "RoadRageTrip/road-data"
ATTRIBUTION = "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY"
TIMEOUT_S = 20.0
RETRY_S = (30.0, 60.0, 120.0, 300.0)  # backoff after failed fetches of one query
WINDOW_MIN = 15  # game-time window of one roadworks query
TILE_DEG = (0.4, 0.2)  # lon, lat: ~19 x 22 km query tiles, snapped so queries repeat exactly
TILE_MARGIN_M = 5000.0  # the player this near a tile edge: fetch the neighbour too

# Matching onto the game's roads
SAMPLE_M = 10.0  # a roadwork line is sampled this often
MATCH_DISTANCE_M = 15.0
MATCH_HEADING_DEG = 30.0
MIN_MATCHED_SHARE = 0.6  # of a line's samples, or the line is not placed
POINT_ZONE_M = 40.0  # a point roadwork without a stated length
PIECE_M = 50.0  # zones are cut into pieces this long (Roadwork.contains is a straight box)

CLOSED_LANE = {"single lane closed", "multiple lanes closed", "single alternate line traffic"}
CLOSED_ROAD = {"road closed", "single carriageway closed"}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# -- the HTTP client and its permanent cache ----------------------------------

def _default_opener(url: str, headers: dict) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        body = response.read()
        if response.headers.get("Deprecation"):
            logger.warning("Digitraffic marks %s deprecated (sunset %s)", url.split("?")[0],
                           response.headers.get("Sunset"))
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return body


class DigitrafficClient:
    """GET JSON from Digitraffic, answering repeated queries from the cache.

    A query is its exact path and parameters. A successful answer (an empty
    one too) is stored and served from then on without expiry; failures are
    not stored, and the same query is retried only after a backoff."""

    def __init__(self, cache_path: Optional[Path], opener: Callable[[str, dict], bytes] = _default_opener,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.opener, self.clock = opener, clock
        self.fetched = 0  # network requests made (diagnostics, tests)
        self._failures: Dict[str, Tuple[int, float]] = {}  # url -> (count, retry at)
        self._lock = threading.Lock()
        self._db = None
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(cache_path), check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS responses (url TEXT PRIMARY KEY, fetched_at TEXT, body BLOB)")
            self._db.commit()
        self._memory: Dict[str, bytes] = {}  # without a database file (tests)

    @staticmethod
    def url(path: str, params: Optional[dict] = None) -> str:
        query = urllib.parse.urlencode(sorted((params or {}).items()))
        return f"{BASE_URL}{path}" + (f"?{query}" if query else "")

    def cached(self, url: str) -> Optional[bytes]:
        with self._lock:
            if self._db is None:
                return self._memory.get(url)
            row = self._db.execute("SELECT body FROM responses WHERE url = ?", (url,)).fetchone()
        return gzip.decompress(row[0]) if row else None

    def _store(self, url: str, body: bytes) -> None:
        with self._lock:
            if self._db is None:
                self._memory[url] = body
                return
            self._db.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?)",
                             (url, datetime.now(timezone.utc).isoformat(timespec="seconds"), gzip.compress(body)))
            self._db.commit()

    def get_json(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        url = self.url(path, params)
        body = self.cached(url)
        if body is None:
            failures, retry_at = self._failures.get(url, (0, 0.0))
            if self.clock() < retry_at:
                return None
            try:
                self.fetched += 1
                body = self.opener(url, {"Accept-Encoding": "gzip", "Digitraffic-User": USER_AGENT})
                json.loads(body)  # only valid JSON is cached
            except Exception as exc:  # offline, HTTP error, bad JSON: try again later
                wait = RETRY_S[min(failures, len(RETRY_S) - 1)]
                self._failures[url] = (failures + 1, self.clock() + wait)
                logger.warning("Digitraffic %s failed (%s); retry in %.0f s", path, exc, wait)
                return None
            self._failures.pop(url, None)
            self._store(url, body)
        return json.loads(body)


# -- roadworks: parsing and timing ---------------------------------------------

@dataclass
class RoadworkPhase:
    start: datetime  # UTC
    end: Optional[datetime]
    working_hours: List[Tuple[int, int, int]] = field(default_factory=list)  # (weekday 0=Mon, start min, end min) local
    liftable: bool = False  # restrictions lift outside working hours
    restrictions: Dict[str, Optional[float]] = field(default_factory=dict)  # type -> quantity
    work_types: List[str] = field(default_factory=list)
    severity: str = ""

    def active(self, moment_utc: datetime, local: datetime) -> bool:
        """In force at this moment: within its dates and, if its
        restrictions lift outside working hours, within those hours."""
        if moment_utc < self.start or (self.end is not None and moment_utc > self.end):
            return False
        if not (self.liftable and self.working_hours):
            return True
        minute = local.hour * 60 + local.minute
        return any(day == local.weekday() and start <= minute < end for day, start, end in self.working_hours)


@dataclass
class LiveRoadwork:
    situation_id: str
    version: int
    title: str
    road: Optional[int]  # the road number, when the data has one
    lines_ll: List[List[Tuple[float, float]]]  # [(lon, lat), ...] per line; a point is a one-point line
    phases: List[RoadworkPhase]

    def phase_at(self, moment_utc: datetime, local: datetime) -> Optional[RoadworkPhase]:
        return next((p for p in self.phases if p.active(moment_utc, local)), None)


def _time(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")[:2]
    return int(hours) * 60 + int(minutes)


def parse_roadworks(collection: Optional[dict]) -> List[LiveRoadwork]:
    """Traffic message V2 roadworks GeoJSON -> LiveRoadwork, the newest
    version of each situation. Malformed features are skipped, never fatal."""
    newest: Dict[str, LiveRoadwork] = {}
    for feature in (collection or {}).get("features", []):
        try:
            props = feature["properties"]
            geometry = feature.get("geometry") or {}
            kind, coords = geometry.get("type"), geometry.get("coordinates") or []
            lines = ([[(c[0], c[1]) for c in line] for line in coords] if kind == "MultiLineString"
                     else [[(c[0], c[1]) for c in coords]] if kind == "LineString"
                     else [[(coords[0], coords[1])]] if kind == "Point" else [])
            if not lines:
                continue
            announcement = next((a for a in props.get("announcements", []) if a.get("language") == "fi"),
                                (props.get("announcements") or [None])[0])
            if announcement is None:
                continue
            point = ((announcement.get("locationDetails") or {}).get("roadAddressLocation") or {}).get("primaryPoint") or {}
            phases = []
            for phase in announcement.get("roadWorkPhases", []):
                timing = phase.get("timeAndDuration") or announcement.get("timeAndDuration") or {}
                start = _time(timing.get("startTime"))
                if start is None:
                    continue
                phases.append(RoadworkPhase(
                    start, _time(timing.get("endTime")),
                    [(WEEKDAYS.index(h["weekday"]), _minutes(h["startTime"]), _minutes(h["endTime"]))
                     for h in phase.get("workingHours", []) if h.get("weekday") in WEEKDAYS],
                    bool(phase.get("restrictionsLiftable")),
                    {r["type"]: (r.get("restriction") or {}).get("quantity") for r in phase.get("restrictions", [])},
                    [w.get("type", "") for w in phase.get("workTypes", [])],
                    phase.get("severity") or "",
                ))
            work = LiveRoadwork(props["situationId"], int(props.get("version") or 0), announcement.get("title", ""),
                                (point.get("roadAddress") or {}).get("road"), lines, phases)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            logger.debug("Skipping a malformed roadwork: %s", exc)
            continue
        if work.phases and (work.situation_id not in newest or work.version > newest[work.situation_id].version):
            newest[work.situation_id] = work
    return list(newest.values())


# -- queries --------------------------------------------------------------------

def window_start(moment_utc: datetime) -> datetime:
    return moment_utc.replace(minute=moment_utc.minute - moment_utc.minute % WINDOW_MIN, second=0, microsecond=0)


def tile_of(lon: float, lat: float) -> Tuple[int, int]:
    return math.floor(lon / TILE_DEG[0]), math.floor(lat / TILE_DEG[1])


def roadworks_params(tile: Tuple[int, int], start: datetime) -> dict:
    """The query for one tile and one game-time window: exact, so it repeats."""
    end = start + timedelta(minutes=WINDOW_MIN)
    return {
        "xMin": round(tile[0] * TILE_DEG[0], 4), "xMax": round((tile[0] + 1) * TILE_DEG[0], 4),
        "yMin": round(tile[1] * TILE_DEG[1], 4), "yMax": round((tile[1] + 1) * TILE_DEG[1], 4),
        "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def tiles_near(lon: float, lat: float, margin_deg: Tuple[float, float]) -> List[Tuple[int, int]]:
    xs = range(math.floor((lon - margin_deg[0]) / TILE_DEG[0]), math.floor((lon + margin_deg[0]) / TILE_DEG[0]) + 1)
    ys = range(math.floor((lat - margin_deg[1]) / TILE_DEG[1]), math.floor((lat + margin_deg[1]) / TILE_DEG[1]) + 1)
    return [(x, y) for x in xs for y in ys]


class RoadDataService:
    """Fetches the roadworks around the player for the current game-time
    window on its own thread. `request()` is cheap and called from the
    simulation; `roadworks` is the latest result (replaced whole, never
    mutated), and `revision` grows whenever it changes."""

    def __init__(self, client: DigitrafficClient, to_lonlat: Callable[[float, float], Tuple[float, float]]) -> None:
        self.client, self.to_lonlat = client, to_lonlat
        self.roadworks: List[LiveRoadwork] = []
        self.revision = 0
        self._wanted: Optional[Tuple[tuple, datetime]] = None
        self._done: Optional[Tuple[tuple, datetime]] = None
        self._wake = threading.Event()
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="digitraffic-road", daemon=True)
        self._thread.start()

    def request(self, x: float, y: float, moment_utc: datetime) -> None:
        lon, lat = self.to_lonlat(x, y)
        margin = (TILE_MARGIN_M / (111320.0 * max(0.2, math.cos(math.radians(lat)))), TILE_MARGIN_M / 111320.0)
        wanted = (tuple(sorted(tiles_near(lon, lat, margin))), window_start(moment_utc))
        if wanted != self._wanted:
            self._wanted = wanted
            self._wake.set()

    def _run(self) -> None:
        while not self._stop:
            self._wake.wait(timeout=30.0)  # also retries failed fetches
            self._wake.clear()
            wanted = self._wanted
            if wanted is None or wanted == self._done:
                continue
            tiles, start = wanted
            works, complete = [], True
            for tile in tiles:
                data = self.client.get_json("/api/traffic-message/v2/roadworks", roadworks_params(tile, start))
                complete &= data is not None
                works.extend(parse_roadworks(data))
            unique = {}
            for work in works:  # neighbouring tiles (including cached ones) may have different versions
                previous = unique.get(work.situation_id)
                if previous is None or work.version > previous.version:
                    unique[work.situation_id] = work
            self.roadworks = list(unique.values())
            self.revision += 1
            if complete:
                self._done = wanted

    def wait_idle(self, timeout_s: float) -> None:
        """Tests and start-up: wait until the wanted window is fetched."""
        deadline = time.monotonic() + timeout_s
        while self._wanted is not None and self._done != self._wanted and time.monotonic() < deadline:
            time.sleep(0.01)

    def close(self) -> None:
        self._stop = True
        self._wake.set()


# -- matching onto the game's roads ---------------------------------------------

def _road_numbers(way) -> set:
    return {part.strip() for part in str(getattr(way, "ref", None) or "").replace(",", ";").split(";") if part.strip()}


def _project_on_way(way, x: float, y: float):
    """(distance along, lateral distance, segment heading) of the closest point."""
    best, along = None, 0.0
    for index, (a, b) in enumerate(zip(way.points_m, way.points_m[1:])):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq <= 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / length_sq))
        px, py = a[0] + dx * t, a[1] + dy * t
        distance = math.hypot(x - px, y - py)
        if best is None or distance < best[1]:
            best = (along + math.sqrt(length_sq) * t, distance, math.atan2(dy, dx))
        along += math.sqrt(length_sq)
    return best


def _samples(line: Sequence[Tuple[float, float]]) -> List[Tuple[float, float, Optional[float]]]:
    """(x, y, heading) every SAMPLE_M along a line; a point has no heading."""
    if len(line) == 1:
        return [(line[0][0], line[0][1], None)]
    out = []
    for a, b in zip(line, line[1:]):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        heading = math.atan2(b[1] - a[1], b[0] - a[0])
        for i in range(max(1, int(length // SAMPLE_M))):
            t = i * SAMPLE_M / length if length > 0 else 0.0
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, heading))
    out.append((line[-1][0], line[-1][1], out[-1][2] if out else None))
    return out


def _match_sample(x, y, heading, road, grid):
    """The best (way, along) for one sample, or None."""
    best = None
    for way in grid.ways_in_rect(x - MATCH_DISTANCE_M, y - MATCH_DISTANCE_M, x + MATCH_DISTANCE_M, y + MATCH_DISTANCE_M):
        if not getattr(way, "is_drivable", False) or getattr(way, "map_level", None) is not None or len(way.points_m) < 2:
            continue
        along, distance, segment = _project_on_way(way, x, y)
        if distance > MATCH_DISTANCE_M:
            continue
        if heading is not None:
            turn = abs((heading - segment + math.pi) % (2 * math.pi) - math.pi)
            if min(turn, math.pi - turn) > math.radians(MATCH_HEADING_DEG):  # either direction of the road
                continue
        score = distance - (10.0 if road is not None and str(road) in _road_numbers(way) else 0.0)
        if best is None or score < best[0]:
            best = (score, way, along)
    return best and best[1:]


def work_samples(work: LiveRoadwork, project) -> List[List[Tuple[float, float, Optional[float]]]]:
    """A roadwork's lines in world metres, sampled every SAMPLE_M (projection
    is the costly part: LiveRoadworks keeps these per situation version)."""
    return [_samples([project(lon, lat) for lon, lat in line]) for line in work.lines_ll]


def match_roadwork(work: LiveRoadwork, phase: RoadworkPhase, project, grid, samples=None) -> list:
    """The game Roadwork zones for one live roadwork's active phase, cut into
    PIECE_M pieces along the matched ways. [] when it doesn't fit the loaded
    roads well enough (MIN_MATCHED_SHARE)."""
    from .roadworks import Roadwork, _point_at, _way_length
    spans: Dict[int, list] = {}
    total = matched = 0
    for line in (samples if samples is not None else work_samples(work, project)):
        previous = None
        for x, y, heading in line:
            total += 1
            hit = _match_sample(x, y, heading, work.road, grid)
            if hit is None:
                previous = None  # an unmatched stretch is not a road closure
                continue
            matched += 1
            way, along = hit
            _, runs = spans.setdefault(id(way), [way, []])
            if previous is not None and previous[0] is way and abs(along - previous[1]) <= 2 * SAMPLE_M + 1e-6:
                run = runs[-1]
                run[0], run[1] = min(run[0], along), max(run[1], along)
            else:
                runs.append([along, along])
            previous = (way, along)
    if total == 0 or matched / total < MIN_MATCHED_SHARE:
        return []
    restrictions = phase.restrictions
    speed = restrictions.get("speed limit")
    stated = restrictions.get("speed limit length")
    closed = any(kind in restrictions for kind in CLOSED_ROAD)
    lane_closed = not closed and any(kind in restrictions for kind in CLOSED_LANE)
    zones = []

    def pieces(way, a_m, b_m, works):
        count = max(1, math.ceil((b_m - a_m) / PIECE_M - 1e-9))
        for i in range(count):
            a, b = a_m + (b_m - a_m) * i / count, a_m + (b_m - a_m) * (i + 1) / count
            zones.append(Roadwork(way, a, b, lane_closed and works, _point_at(way, a), _point_at(way, b),
                                  blocks=closed and works, speed_limit_kmh=int(speed) if speed else None,
                                  source="digitraffic", situation_id=work.situation_id, title=work.title))

    for way, runs in spans.values():
        length = _way_length(way)
        expanded = []
        for start_m, end_m in runs:
            if end_m - start_m < 1e-6:  # a point needs an extent; short lines keep their actual bounds
                middle = (start_m + end_m) / 2.0
                start_m, end_m = max(0.0, middle - POINT_ZONE_M / 2), min(length, middle + POINT_ZONE_M / 2)
            expanded.append((start_m, end_m))
        merged = []
        for start_m, end_m in sorted(expanded):
            if merged and start_m <= merged[-1][1] + 1e-6:
                merged[-1][1] = max(merged[-1][1], end_m)
            else:
                merged.append([start_m, end_m])
        for start_m, end_m in merged:
            pieces(way, start_m, end_m, True)
        start_m, end_m = merged[0][0], merged[-1][1]
        if speed and stated and float(stated) > end_m - start_m:  # the speed limit reaches beyond the works
            extra = (float(stated) - (end_m - start_m)) / 2.0
            before, after = max(0.0, start_m - extra), min(length, end_m + extra)
            # One speed-limit interval per way, without duplicating zones or closing the gaps.
            cursor = before
            for a, b in merged:
                if a - cursor > 1.0:
                    pieces(way, cursor, a, False)
                cursor = b
            if after - cursor > 1.0:
                pieces(way, cursor, after, False)
    return zones


REMATCH_ON_MAP_GROWTH_S = 5.0  # the loaded roads change almost every tick while the map streams in


class LiveRoadworks:
    """The live roadworks placed on the loaded map at the game time. The
    simulation calls update() every tick; matching runs only when the
    fetched data or the active phases change, and for newly loaded roads
    at most once per REMATCH_ON_MAP_GROWTH_S."""

    def __init__(self, service: RoadDataService, project: Callable[[float, float], Tuple[float, float]],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.service, self.project, self.clock = service, project, clock
        self.zones: list = []
        self.matches = 0  # matching runs (diagnostics, tests)
        self._key = None
        self._ways_revision = None
        self._matched_at = float("-inf")
        self._samples: Dict[Tuple[str, int], list] = {}  # (situation, version) -> projected samples
        self._summary = None

    def update(self, x: float, y: float, moment_utc: datetime, local: datetime, ways_revision, grid) -> None:
        self.service.request(x, y, moment_utc)
        if grid is None:
            return
        works = self.service.roadworks
        phases = tuple((w.situation_id, w.phases.index(p)) for w in works if (p := w.phase_at(moment_utc, local)))
        key = (self.service.revision, phases)
        now = self.clock()
        roads_grew = ways_revision != self._ways_revision and now - self._matched_at >= REMATCH_ON_MAP_GROWTH_S
        if key == self._key and not roads_grew:
            return
        self._key, self._ways_revision, self._matched_at = key, ways_revision, now
        self.matches += 1
        live = {(w.situation_id, w.version) for w in works}
        self._samples = {k: v for k, v in self._samples.items() if k in live}
        zones = []
        for work in works:
            phase = work.phase_at(moment_utc, local)
            if phase is not None:
                version = (work.situation_id, work.version)
                if version not in self._samples:  # (not setdefault: that would project every time)
                    self._samples[version] = work_samples(work, self.project)
                samples = self._samples[version]
                zones.extend(match_roadwork(work, phase, self.project, grid, samples))
        self.zones = zones
        summary = (len(works), len(phases), len(zones))
        if summary != self._summary:  # logged when the placement changes, not every re-match
            self._summary = summary
            logger.info("Digitraffic roadworks: %d live, %d active, %d zones placed", *summary)

    def speed_limit_at(self, x: float, y: float, *, layer: int = 0, map_level: int = 0) -> Optional[int]:
        limits = [z.speed_limit_kmh for z in self.zones
                  if z.speed_limit_kmh and z.applies_to(layer, map_level) and z.contains(x, y)]
        return min(limits) if limits else None
