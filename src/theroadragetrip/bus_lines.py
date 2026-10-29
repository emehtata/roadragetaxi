"""Bus lines: NPC buses drive the OSM bus routes stop to stop (docs/bus-lines.md).

A line is one route=bus relation: its stops in order (osm/build.py puts
[route key, index, ref] on every BusStop the route calls at). A line bus
is an ordinary NPC vehicle of vehicle_kind "bus_line" (npc.py drives it,
with all the traffic rules); this module only walks its BusJob from stop
to stop. No timetable: it leaves a stop after STOP_DWELL_S. At the last
stop the job ends and the bus is retired out of sight (npc.py); each
direction of a line is its own OSM route, joined by new buses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Sequence

LINE_BUSES = 3  # of the NPC population's moving-traffic spawns, while lines are loaded
STOP_DWELL_S = 12.0  # at a stop: passengers board and leave
MAX_ROUTE_ATTEMPTS = 3  # a stop that cannot be routed to this often is skipped
AT_STOP_M = 30.0  # stopped this near its next stop: it is at it (else stopped elsewhere, e.g. after a recovery)
START_NEAR_STOP_M = 60.0  # a line bus appears only this near one of its stops: a line knows only its stops, not the streets between


@dataclass
class Line:
    key: str  # the route relation's id
    ref: str  # what the bus shows ("18", "5N")
    stops: List[object]  # BusStops in route order (those loaded)


def lines(bus_stops: Sequence) -> Dict[str, Line]:
    """Every route with at least two loaded stops, keyed by route key."""
    calls: Dict[str, list] = {}
    for stop in bus_stops:
        for key, index, ref in getattr(stop, "routes", ()):
            calls.setdefault(key, []).append((index, ref, stop))
    found = {}
    for key, entries in calls.items():
        if len(entries) >= 2:
            entries.sort(key=lambda entry: entry[0])
            found[key] = Line(key, entries[0][1], [entry[2] for entry in entries])
    return found


@dataclass
class BusJob:
    line: Line
    next_stop: int  # index into line.stops: the stop it drives to
    state: str = "driving"  # "await_departure" -> "driving" -> "stopped" (as competitor_taxis.TaxiJob)
    stop_until: float = 0.0
    route_attempts: int = 0
    stopped_at: Optional[object] = field(default=None, repr=False)  # the stop it stands at
    finished: bool = False
    failure_reason: str = ""

    @property
    def target_stop(self):
        return self.line.stops[self.next_stop]

    def departing(self) -> None:
        if not self.finished and self.state == "await_departure":
            self.state = "driving"

    def route_failed(self) -> bool:
        """No route to the next stop: try the one after. True: the line is over."""
        if self.finished:
            return True
        self.route_attempts += 1
        if self.route_attempts < MAX_ROUTE_ATTEMPTS:
            return False
        self.route_attempts = 0
        self.next_stop += 1
        self.finished = self.next_stop >= len(self.line.stops)
        return self.finished

    def at_stop(self, now: float, x: float, y: float) -> bool:
        """The bus has stopped at (x, y): arrived, or still dwelling. True
        when it has served the line's last stop (its trip is over).
        Stopped away from its stop, it needs a route there again."""
        if self.finished:
            return True
        stop = self.target_stop
        if self.state == "driving" and (stop.x - x) ** 2 + (stop.y - y) ** 2 > AT_STOP_M ** 2:
            self.state = "await_departure"
        elif self.state == "driving":
            self.state, self.stop_until, self.stopped_at = "stopped", now + STOP_DWELL_S, self.target_stop
        elif self.state == "stopped" and now >= self.stop_until:
            self.next_stop += 1
            self.state, self.route_attempts = "await_departure", 0
            self.finished = self.next_stop >= len(self.line.stops)
            return self.finished
        return False


def nearest_stop_index(line: Line, x: float, y: float) -> int:
    return min(range(len(line.stops)), key=lambda i: (line.stops[i].x - x) ** 2 + (line.stops[i].y - y) ** 2)


def start_job(all_lines: Dict[str, Line], x: float, y: float) -> Optional[BusJob]:
    """A job on the line with a stop nearest (x, y), driving to that stop
    (or the next one, when it is the last) - or None when no line's stop is
    within START_NEAR_STOP_M: a bus started anywhere else appeared on streets
    its line never runs (line 4 on Tervakukkatie, Oulu)."""
    best = None
    for line in all_lines.values():
        index = nearest_stop_index(line, x, y)
        stop = line.stops[index]
        distance_sq = (stop.x - x) ** 2 + (stop.y - y) ** 2
        if best is None or distance_sq < best[0]:
            best = (distance_sq, line, index)
    if best is None or best[0] > START_NEAR_STOP_M ** 2:
        return None
    return BusJob(best[1], best[2])


def is_line_bus(vehicle) -> bool:
    return getattr(vehicle, "vehicle_kind", None) == "bus_line"
