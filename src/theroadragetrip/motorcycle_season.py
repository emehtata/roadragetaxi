"""How much motorcycle traffic the in-game date allows (docs/motorcycles.md).

One factor, 0..1, multiplies the motorcycle traffic weight; every other
vehicle type keeps its own. Finnish riding season: bikes come out in April as
the roads dry, peak from June to August, thin out through the autumn, and are
off the road from November to March - the winter exclusion is absolute.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Tuple

MonthDay = Tuple[int, int]


@dataclass(frozen=True)
class MotorcycleSeason:
    season_start: MonthDay = (4, 1)  # the winter exclusion ends: the first bikes
    summer_start: MonthDay = (6, 1)  # spring's ramp reaches the summer peak
    autumn_start: MonthDay = (9, 1)  # the peak ends: the autumn ramp down
    winter_start: MonthDay = (11, 1)  # the winter exclusion begins: none at all
    spring_multiplier: float = 0.1  # at season_start, rising to summer_multiplier
    summer_multiplier: float = 1.0  # the peak, held through the summer
    autumn_multiplier: float = 0.1  # at the end of autumn, falling from summer_multiplier

    def factor(self, day: date) -> float:
        """The motorcycle traffic multiplier on `day` (the game date, never the host's):
        0 in winter, linear ramps in spring and autumn, the peak in summer."""
        key = (day.month, day.day)
        if not self.season_start <= key < self.winter_start:
            return 0.0
        if key < self.summer_start:
            return _ramp(day, self.season_start, self.summer_start, self.spring_multiplier, self.summer_multiplier)
        if key < self.autumn_start:
            return self.summer_multiplier
        return _ramp(day, self.autumn_start, self.winter_start, self.summer_multiplier, self.autumn_multiplier)


def _ramp(day: date, start: MonthDay, end: MonthDay, low: float, high: float) -> float:
    begin, finish = date(day.year, *start), date(day.year, *end)
    return low + (high - low) * (day - begin).days / max(1, (finish - begin).days)


def _month_day(text: str) -> MonthDay:
    month, day = (int(part) for part in text.strip().split("-"))
    date(2001, month, day)  # validates it (no leap day: the season must exist every year)
    return month, day


def from_config(config) -> MotorcycleSeason:
    """[motorcycles] in the game config; a missing or bad value keeps its default."""
    default = MotorcycleSeason()
    if config is None or not config.has_section("motorcycles"):
        return default
    section = config["motorcycles"]
    values = {}
    for name in ("season_start", "summer_start", "autumn_start", "winter_start"):
        try:
            values[name] = _month_day(section.get(name, ""))
        except ValueError:
            values[name] = getattr(default, name)
    for name in ("spring_multiplier", "summer_multiplier", "autumn_multiplier"):
        try:
            values[name] = max(0.0, float(section.get(name, "")))
        except ValueError:
            values[name] = getattr(default, name)
    season = MotorcycleSeason(**values)
    if not season.season_start < season.summer_start <= season.autumn_start < season.winter_start:
        return default  # out of order: the defaults rather than a nonsense year
    return season
