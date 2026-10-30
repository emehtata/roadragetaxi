"""Retail window lighting from mapped hours and Finnish simulation time."""
from datetime import datetime
from functools import lru_cache

from opening_hours import OpeningHours, ParserError, State

from .building_style import SIGN_CATEGORY_BY_VENUE_TYPE
from .calendar import FINLAND_TZ


def retail_hours(building) -> tuple:
    """Own shop hours, or those of retail tenants inside a mixed-use building."""
    kind = str(getattr(building, "building_type", "") or "").casefold()
    venue = str(getattr(building, "venue_type", "") or "").casefold()
    own = getattr(building, "opening_hours", None)
    if own and (getattr(building, "shop_type", None) or kind in {"retail", "shop", "supermarket"}
                or SIGN_CATEGORY_BY_VENUE_TYPE.get(venue) in {"grocery", "retail"}):
        return (own,)
    return tuple(sorted({place.opening_hours for place in getattr(building, "associated_places", ())
                         if getattr(place, "opening_hours", None) and
                         (getattr(place, "shop_type", None) or SIGN_CATEGORY_BY_VENUE_TYPE.get(place.kind) in {"grocery", "retail"})}))


@lru_cache(maxsize=1024)
def _schedule(text: str, latitude: float, longitude: float):
    try:
        return OpeningHours(text, country="FI", coords=(latitude, longitude))
    except (ParserError, ValueError):
        return None


def opening_state(hours: tuple, moment: datetime, latitude: float, longitude: float) -> int:
    """1 open, 0 closed, -1 unknown; never substitute guessed shop hours."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(FINLAND_TZ).replace(tzinfo=None)
    return _opening_state(hours, moment.replace(second=0, microsecond=0), latitude, longitude)


@lru_cache(maxsize=4096)
def _opening_state(hours: tuple, moment: datetime, latitude: float, longitude: float) -> int:
    states = []
    for text in hours:
        schedule = _schedule(text, latitude, longitude)
        states.append(schedule.state(moment)[0] if schedule is not None else State.UNKNOWN)
    if State.OPEN in states:
        return 1
    return 0 if states and all(state == State.CLOSED for state in states) else -1
