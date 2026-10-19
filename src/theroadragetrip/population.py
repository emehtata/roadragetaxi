"""How many people are around a point: the settlement model shared by the
pedestrian and NPC traffic managers (docs/population-model.md).

People live in, or visit, the mapped buildings around a point. Each building's
OSM type gives its residents or visitors; the municipality the point is in
(kunnat.json.gz, nearest centre) gives how many of those are out walking:
a dense town walks, a rural municipality drives. Pure functions over the
loaded buildings - no per-frame state, and the callers recount only when the
player moves on (a population check, a new 100 m cell).
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

from .residents import CITY_DATA

HOME_TYPES = {"house", "detached", "semidetached_house", "bungalow", "farm"}
FLAT_TYPES = {"apartments", "residential", "terrace", "dormitory"}
SEASONAL_TYPES = {"cabin", "hut"}  # summer cottages: mostly empty
DESTINATION_TYPES = {
    "commercial", "retail", "office", "supermarket", "kiosk", "hotel", "school",
    "university", "college", "kindergarten", "hospital", "public", "civic",
    "church", "train_station", "transportation", "sports_hall", "sports_centre",
}
EMPTY_TYPES = {
    "garage", "garages", "shed", "barn", "sauna", "carport", "farm_auxiliary",
    "roof", "service", "greenhouse", "outbuilding", "storage_tank", "boathouse",
    "cowshed", "stable", "hangar", "ruins", "construction", "bunker", "silo",
}
PEOPLE_PER_HOME = 2.5
SEASONAL_PEOPLE = 0.3
SUMMER_CABIN_PEOPLE = 2.0  # June-August: the cottages are lived in
SUMMER_MONTHS = {6, 7, 8}
FLAT_M2_PER_PERSON = 40.0
DESTINATION_M2_PER_VISITOR = 50.0
SMALL_UNTAGGED_M2 = 40.0  # an untagged building smaller than this is a shed or sauna
HOUSE_SIZED_UNTAGGED_M2 = 200.0
OUTDOOR_SHARE = 0.04  # of the people around, how many are out walking at once
URBAN_DENSITY_PER_KM2 = 100.0  # at and above: the full walking share


def footprint_m2(building) -> float:
    points = building.points_m
    return abs(sum(
        x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1])
    )) / 2.0


def building_people(building, month: Optional[int] = None) -> float:
    """Residents or visitors the building accounts for (in `month`, when known)."""
    kind = (getattr(building, "building_type", None) or "yes").lower()
    if kind in EMPTY_TYPES:
        return 0.0
    if kind in SEASONAL_TYPES:
        return SUMMER_CABIN_PEOPLE if month in SUMMER_MONTHS else SEASONAL_PEOPLE
    if kind in HOME_TYPES:
        return PEOPLE_PER_HOME
    area = footprint_m2(building)
    levels = getattr(building, "levels", None) or (
        max(1, round(building.height_m / 3.0)) if getattr(building, "height_is_explicit", False) else None
    )
    if kind in FLAT_TYPES:
        return area * (levels or 3) / FLAT_M2_PER_PERSON
    if kind in DESTINATION_TYPES:
        return area * (levels or 1) / DESTINATION_M2_PER_VISITOR
    # "yes" and everything else: judged by its size
    if area < SMALL_UNTAGGED_M2:
        return 0.0
    if area < HOUSE_SIZED_UNTAGGED_M2 and not levels:
        return PEOPLE_PER_HOME
    return area * (levels or 1) / FLAT_M2_PER_PERSON


def people_within(buildings: Iterable, x: float, y: float, radius: float, month: Optional[int] = None) -> float:
    """People the buildings whose centre is within `radius` account for.
    Each building is counted once, even when it comes from several cells."""
    seen = set()
    total = 0.0
    r_sq = radius * radius
    for building in buildings:
        min_x, min_y, max_x, max_y = building.bbox
        if id(building) in seen or ((min_x + max_x) / 2 - x) ** 2 + ((min_y + max_y) / 2 - y) ** 2 > r_sq:
            continue
        seen.add(id(building))
        total += building_people(building, month)
    return total


def municipality_at(x: float, y: float) -> Optional[dict]:
    """The kunnat.json.gz entry whose centre is nearest (x, y), None without the data."""
    from .taxi import municipality_points  # its projected centres; imported late, taxi is heavy
    nearest = min(
        (p for p in municipality_points() if p[4] is None),
        key=lambda p: (p[1] - x) ** 2 + (p[2] - y) ** 2,
        default=None,
    )
    return CITY_DATA.get(nearest[0].casefold()) if nearest else None


def walking_share(municipality: Optional[dict]) -> float:
    """OUTDOOR_SHARE, less where the municipality is sparse (1.9/km2 in Sysmä
    walks 0.42 of it, Helsinki all). Unknown: the full share."""
    if not municipality:
        return OUTDOOR_SHARE
    density = float(municipality.get("väestöntiheys_henkiloa_km2") or 0.0)
    return OUTDOOR_SHARE * (0.4 + 0.6 * min(1.0, density / URBAN_DENSITY_PER_KM2))


def walkers_within(buildings: Iterable, x: float, y: float, radius: float, municipality: Optional[dict]) -> int:
    """People out walking within `radius`: none without buildings, at least
    one where anybody lives."""
    people = people_within(buildings, x, y, radius)
    return math.ceil(people * walking_share(municipality)) if people else 0


# --- Traffic demand (docs/population-model.md, "Traffic demand") ---------
# Share of the day's peak hour, by hour. ESTIMATES shaped like Finnish
# automatic traffic counts (Fintraffic LAM): weekday peaks 7-8 and 15-17, a
# night trough near 2-3 % of the peak; weekends without a morning peak.
WEEKDAY_HOURLY = [0.04, 0.025, 0.02, 0.02, 0.04, 0.15, 0.45, 0.85, 0.8, 0.6, 0.6, 0.65,
                  0.7, 0.7, 0.75, 0.9, 1.0, 0.85, 0.65, 0.5, 0.4, 0.3, 0.18, 0.09]
WEEKEND_HOURLY = [0.08, 0.06, 0.04, 0.03, 0.03, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.75,
                  0.8, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.45, 0.35, 0.25, 0.18, 0.12]
# Month: less in deep winter, most in summer (estimate)
MONTH_FACTOR = {1: 0.88, 2: 0.9, 3: 0.95, 4: 0.97, 5: 1.0, 6: 1.05, 7: 1.0, 8: 1.05, 9: 1.0, 10: 0.97, 11: 0.95, 12: 0.92}
# Passing traffic a road carries whoever lives along it, as a share of a
# town centre's moving traffic (estimate, by OSM highway class).
THROUGH_TRAFFIC = {"motorway": 0.6, "trunk": 0.45, "primary": 0.3, "secondary": 0.15, "tertiary": 0.06}
FIXED_PUBLIC_HOLIDAYS = {(1, 1), (1, 6), (5, 1), (12, 6), (12, 24), (12, 25), (12, 26)}


def is_public_holiday(day) -> bool:
    """Finland's fixed-date public holidays and Midsummer Eve and Day (Fri
    and Sat between 19 and 26 June). Easter and Ascension are not covered."""
    if (day.month, day.day) in FIXED_PUBLIC_HOLIDAYS:
        return True
    return day.month == 6 and (19 <= day.day <= 25 and day.weekday() == 4 or 20 <= day.day <= 26 and day.weekday() == 5)


def hour_demand(moment) -> float:
    """Traffic at `moment` as a share of a weekday peak hour; 1.0 without a clock."""
    if moment is None:
        return 1.0
    free_day = moment.weekday() >= 5 or is_public_holiday(moment)
    curve = WEEKEND_HOURLY if free_day else WEEKDAY_HOURLY
    return curve[moment.hour] * MONTH_FACTOR[moment.month]


def traffic_demand(local_fraction: float, highway: Optional[str], moment) -> dict:
    """Moving-traffic demand around the player as a share of the city's
    town-centre peak: the local people's trips plus the road's passing
    traffic, both following the clock. Returns the parts, for diagnostics."""
    hour = hour_demand(moment)
    through = THROUGH_TRAFFIC.get(highway or "", 0.0)
    local = min(1.0, local_fraction)
    # Gameplay nightlife, not commuter traffic counts: Friday/Saturday 18–05.
    nightlife = local * 0.5 if moment is not None and (
        moment.hour >= 18 and moment.weekday() in (4, 5)
        or moment.hour < 5 and moment.weekday() in (5, 6)
    ) else 0.0
    return {
        "local": local, "through": through, "hour": hour, "nightlife": nightlife,
        "demand": max(min(1.0, max(local, through)) * hour, nightlife),
    }
