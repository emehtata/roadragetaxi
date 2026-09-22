"""In-game calendar and Finnish thermal seasons."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum


class Season(str, Enum):
    WINTER = "winter"
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"


def season_for_month(month: int) -> Season:
    """Return the legacy fixed season for callers that only have a month."""
    if not 1 <= month <= 12:
        raise ValueError(f"month must be in 1..12, got {month}")
    if month in (12, 1, 2):
        return Season.WINTER
    if month <= 5:
        return Season.SPRING
    if month <= 8:
        return Season.SUMMER
    return Season.AUTUMN


@dataclass
class GameCalendar:
    """Mutable local game datetime advanced in game seconds."""

    current: datetime
    latitude: float = 60.17

    @classmethod
    def from_date_and_seconds(cls, day: date, seconds: float) -> "GameCalendar":
        midnight = datetime.combine(day, datetime.min.time())
        return cls(midnight + timedelta(seconds=seconds))

    @property
    def date(self) -> date:
        return self.current.date()

    @property
    def time_seconds(self) -> float:
        midnight = datetime.combine(self.date, datetime.min.time())
        return (self.current - midnight).total_seconds()

    @property
    def season(self) -> Season:
        # Local import avoids a module cycle: climate imports the shared enum.
        from .climate import thermal_season_for_date

        return thermal_season_for_date(self.date, self.latitude)

    def advance(self, game_seconds: float) -> None:
        self.current += timedelta(seconds=game_seconds)
