"""Parking facility classification and ParkingGarage construction from OSM
tags (garage-00.md). See docs/parking-garages.md for the tag rules."""

from __future__ import annotations

from typing import List, Optional, Tuple

from .models import ParkingGarage

PARKING_SURFACE = "surface"
PARKING_UNDERGROUND = "underground"
PARKING_MULTI_STOREY = "multi-storey"
PARKING_UNKNOWN = "unknown"
GARAGE_TYPES = frozenset({PARKING_UNDERGROUND, PARKING_MULTI_STOREY})

# parking=* values that are open-air parking, not a structure you drive into.
_SURFACE_VALUES = frozenset({
    "surface", "street_side", "lane", "layby", "on_kerb", "half_on_kerb",
    "rooftop", "carports", "garage_boxes", "sheds",
})
_MULTI_STOREY_VALUES = frozenset({"multi-storey", "multi_storey", "multistorey"})


def parking_facility_type(tags: dict) -> Optional[str]:
    """PARKING_* class of an amenity=parking / building=parking element,
    None for anything else. amenity=parking with no parking=* is surface
    (OSM's documented default); building=parking with none is a parking
    structure, i.e. multi-storey. Nothing is inferred from geometry."""
    is_amenity = tags.get("amenity") == "parking"
    is_building = tags.get("building") == "parking"
    if not (is_amenity or is_building):
        return None
    parking = str(tags.get("parking", "")).split(";")[0].strip().casefold()
    if parking == "underground":
        return PARKING_UNDERGROUND
    if parking in _MULTI_STOREY_VALUES:
        return PARKING_MULTI_STOREY
    if parking in _SURFACE_VALUES:
        return PARKING_SURFACE
    if parking:
        return PARKING_UNKNOWN
    return PARKING_MULTI_STOREY if is_building else PARKING_SURFACE


def _count(value) -> Optional[int]:
    """A non-negative level/capacity count, or None when missing/garbled
    ("2", "2.0", "2;3" -> 2; "-1", "many", "" -> None)."""
    try:
        number = float(str(value).split(";")[0].strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number >= 0 and number == int(number) else None


def garage_levels(tags: dict, garage_type: str) -> Tuple[Tuple[int, ...], str]:
    """Logical levels + the tag they came from. Conservative: unknown stays
    (), and building:levels only counts as parking levels because the
    garage type already says the whole building is a parking structure."""
    parking = _count(tags.get("parking:levels"))
    above = _count(tags.get("building:levels"))
    below = _count(tags.get("building:levels:underground"))
    if garage_type == PARKING_UNDERGROUND:
        if parking:
            return tuple(range(-parking, 0)), "parking:levels"
        if below:
            return tuple(range(-below, 0)), "building:levels:underground"
        return (), ""
    if parking:
        return tuple(range(parking)), "parking:levels"
    if above or below:
        return tuple(range(-(below or 0), above or 0)), "building:levels"
    return (), ""


def make_parking_garage(
    tags: dict, osm_type: str, osm_id: int, points: List[Tuple[float, float]],
) -> Optional[ParkingGarage]:
    """ParkingGarage for a garage-type element with its outer ring (or one
    point for a node), else None."""
    garage_type = parking_facility_type(tags)
    if garage_type not in GARAGE_TYPES or not points:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    ring = points[:-1] if len(points) > 1 and points[0] == points[-1] else points  # closing point once
    levels, source = garage_levels(tags, garage_type)
    return ParkingGarage(
        osm_type=osm_type, osm_id=osm_id, garage_type=garage_type, points_m=points,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        center_m=(sum(x for x, _ in ring) / len(ring), sum(y for _, y in ring) / len(ring)),
        levels=levels, levels_source=source,
        parking_levels=_count(tags.get("parking:levels")),
        building_levels=_count(tags.get("building:levels")),
        underground_levels=_count(tags.get("building:levels:underground")),
        capacity=_count(tags.get("capacity")),
        name=tags.get("name"), operator=tags.get("operator"), access=tags.get("access"),
        fee=tags.get("fee"), maxheight=tags.get("maxheight"), maxweight=tags.get("maxweight"),
        opening_hours=tags.get("opening_hours"), covered=tags.get("covered"),
    )
