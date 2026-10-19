"""Nightclub opening hours as weekly intervals (rrt-019-nightclub): what the
client's nightclub music follows. Minutes of the week, 0 = Monday 00:00;
an interval past midnight runs into the next day (past Sunday: wraps).

OSM `opening_hours` in its simple forms ("Fr-Su 22:00-04:30",
"We-Th 00:00-04:30; Fr,Sa 23:00-05:00", "Mo off") is used as mapped; anything
else (holidays, months, comments, "24/7") falls back to DEFAULT_SCHEDULE.
"""
from __future__ import annotations

import re
from typing import List, Optional

DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
WEEK_MIN = 7 * 24 * 60
# Finnish nightclubs mostly open Thursday to Saturday nights, 22-04 (an estimate)
DEFAULT_OPENING_HOURS = "Th-Sa 22:00-04:00"

_RULE = re.compile(r"^(?P<days>[A-Za-z,\- ]+)\s+(?P<times>off|\d{1,2}:\d{2}-\d{1,2}:\d{2}(?:\s*,\s*\d{1,2}:\d{2}-\d{1,2}:\d{2})*)$")


def _days(spec: str) -> Optional[List[int]]:
    days: List[int] = []
    for part in spec.replace(" ", "").split(","):
        if "-" in part:
            first, last = part.split("-", 1)
            if first not in DAYS or last not in DAYS:
                return None
            a, b = DAYS.index(first), DAYS.index(last)
            days += [(a + i) % 7 for i in range((b - a) % 7 + 1)]
        elif part in DAYS:
            days.append(DAYS.index(part))
        else:
            return None
    return days


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def parse_opening_hours(text: Optional[str]) -> Optional[List[List[int]]]:
    """[[start, end], ...] minutes of the week, or None when `text` isn't a
    simple form. A later rule for a day replaces an earlier one (OSM)."""
    if not text:
        return None
    by_day = {}
    for rule in text.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        match = _RULE.match(rule)
        days = _days(match["days"]) if match else None
        if not days:
            return None
        spans = [] if match["times"] == "off" else [
            (_minutes(a), _minutes(b)) for a, b in (span.split("-") for span in match["times"].replace(" ", "").split(","))
        ]
        for day in days:
            by_day[day] = spans
    intervals = []
    for day, spans in sorted(by_day.items()):
        for start, end in spans:
            if end <= start:  # past midnight: into the next day
                end += 24 * 60
            intervals.append([day * 24 * 60 + start, day * 24 * 60 + end])
    return intervals


def nightclub_schedule(opening_hours: Optional[str]) -> List[List[int]]:
    """The venue's weekly open intervals: its mapped hours, else the default."""
    return parse_opening_hours(opening_hours) or parse_opening_hours(DEFAULT_OPENING_HOURS)
