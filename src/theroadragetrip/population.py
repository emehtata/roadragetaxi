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


def building_people(building) -> float:
    """Residents or visitors the building accounts for."""
    kind = (getattr(building, "building_type", None) or "yes").lower()
    if kind in EMPTY_TYPES:
        return 0.0
    if kind in SEASONAL_TYPES:
        return SEASONAL_PEOPLE
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


def people_within(buildings: Iterable, x: float, y: float, radius: float) -> float:
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
        total += building_people(building)
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
