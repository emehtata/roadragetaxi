"""Building appearance rules shared by the simulation server and the
Godot client's map chunks (static_world.py): colours (named in Finnish or
the per-building palette), heights, roofs, windows and categories. No
drawing here - pure functions of a Building."""

from __future__ import annotations

from .osm import Building
from .osm.constants import OPEN_ROOF_BUILDING_TYPES


BUILDING_WALL_COLORS = ((158, 105, 82), (174, 166, 143), (116, 131, 119), (139, 139, 137))


BUILDING_ROOF_COLORS = ((92, 57, 48), (102, 96, 82), (66, 83, 69), (83, 86, 87))


# A Finnish building name naming its own color (e.g. "Sininen talo",
# "Punatalo", "Valkea Kartano") should render in that color rather than the
# usual per-building pseudo-random wall/roof pick. Keyed by the color's
# root/prefix so both the adjective ("sininen") and compound-name form
# ("Sinikoti") match via substring search.
FINNISH_BUILDING_COLOR_NAMES = {
    "sininen": (70, 110, 160),
    "sini": (70, 110, 160),
    "punainen": (150, 60, 55),
    "puna": (150, 60, 55),
    "valkoinen": (215, 212, 200),
    "valkea": (215, 212, 200),
    "valko": (215, 212, 200),
    "vihreä": (80, 120, 85),
    "viher": (80, 120, 85),
    "keltainen": (200, 175, 90),
    "kelta": (200, 175, 90),
    "musta": (55, 55, 58),
    "harmaa": (140, 140, 138),
    "ruskea": (120, 85, 60),
    "oranssi": (195, 120, 60),
    "vaaleanpunainen": (200, 140, 150),
    "pinkki": (200, 140, 150),
    "violetti": (110, 80, 130),
    "purppura": (110, 80, 130),
    "hopea": (170, 172, 175),
    "kulta": (185, 155, 80),
}


COMMERCIAL_AMENITIES = {
    "bar", "biergarten", "cafe", "fast_food", "food_court", "ice_cream",
    "nightclub", "pub", "restaurant",
}


COMMERCIAL_BUILDING_TYPES = {"commercial", "retail", "shop"}


def _is_open_roof(building: Building) -> bool:
    """Return whether an OSM building footprint is a drive-through roof."""
    return str(getattr(building, "building_type", "") or "").casefold() in OPEN_ROOF_BUILDING_TYPES


def _building_window_story_count(building: Building) -> int:
    """Return the OSM floor count, or a height-based fallback."""
    levels = getattr(building, "levels", None)
    if levels is not None:
        try:
            return max(1, min(40, int(levels)))
        except (TypeError, ValueError):
            pass
    if _building_type(building) in HALL_TYPES:
        return 1
    height = _building_render_height(building)
    return max(1, min(40, int(round(height / 3.0))))


def _building_colors_from_name(name):
    """Return (wall_color, roof_color) if `name` names a color in Finnish,
    else None. The roof is a darkened tint of the same color, matching how
    BUILDING_ROOF_COLORS pairs with BUILDING_WALL_COLORS."""
    if not name:
        return None
    lowered = name.lower()
    for word, wall_color in FINNISH_BUILDING_COLOR_NAMES.items():
        if word in lowered:
            roof_color = tuple(max(0, int(channel * 0.58)) for channel in wall_color)
            return wall_color, roof_color
    return None


def _building_is_commercial(building: Building) -> bool:
    """Return whether the building should render a storefront ground floor -
    shops, supermarkets, restaurants, cafes, pharmacies, banks, hotels, and
    other retail/commercial premises (windows.md section 1), via the
    existing venue_type/associated_places OSM data - never a bare
    building=* tag alone (a building=commercial with no actual venue still
    isn't necessarily a storefront)."""
    venue_type = str(getattr(building, "venue_type", "") or "").lower()
    if venue_type in COMMERCIAL_VENUE_TYPES or venue_type in COMMERCIAL_BUILDING_TYPES:
        return True
    for place in getattr(building, "associated_places", ()):
        place_type = str(getattr(place, "kind", "") or "").lower()
        if place_type in COMMERCIAL_VENUE_TYPES or place_type in COMMERCIAL_BUILDING_TYPES:
            return True
    return False


# windows.md section 3: detached/small-residential building=* values - these
# get fewer, smaller windows than an apartment block or office of the same
# height. Not exhaustive of every OSM house-ish tag, just the common ones.
# terrace: a Finnish rivitalo, one storey under a pitched roof like a house.
HOUSE_BUILDING_TYPES = {"house", "detached", "bungalow", "cabin", "semidetached_house", "farm", "terrace"}
# Typical Finnish buildings of a type, used when OSM gives no height or levels
# (the footprint fallback made a garage ~6 m and a warehouse ~20 m tall).
OUTBUILDING_TYPES = {"garage", "garages", "shed", "garbage_shed", "allotment_house", "service", "kiosk"}  # no windows
HALL_TYPES = {"industrial", "warehouse"}  # one storey, one window row
CHURCH_TYPES = {"church", "chapel", "cathedral"}  # a steep pitched roof (gabled flag 2)
TANK_TYPES = {"storage_tank", "tank", "silo"}  # round metal, as tall as 0.8 x its width, no windows
TANK_COLOR = (196, 199, 197)
TYPE_HEIGHT_M = {**{t: 3.0 for t in OUTBUILDING_TYPES}, **{t: 8.0 for t in HALL_TYPES}, "carport": 2.5,
                 "kindergarten": 4.0, "school": 7.0, **{t: 8.0 for t in CHURCH_TYPES}}


def _building_is_house(building: Building) -> bool:
    """Return whether `building` should get a small-house window treatment."""
    building_type = str(getattr(building, "building_type", "") or "").lower()
    if building_type in HOUSE_BUILDING_TYPES:
        return True
    if building_type:
        return False
    # No building=* tag at all: fall back to the same OSM-levels/height
    # signal windows already use elsewhere - a short, 1-2 story building
    # with no commercial venue reads as a detached house.
    return _building_window_story_count(building) <= 2 and not _building_is_commercial(building)


def _building_render_height(building: Building) -> float:
    """Without an OSM height or levels: a Finnish 1.5-storey house, else the
    type's typical height (TYPE_HEIGHT_M), else the footprint fallback."""
    if getattr(building, "levels", None) is None and not getattr(building, "height_is_explicit", False):
        if _building_is_house_by_tag(building):
            return 4.5
        if _building_type(building) in TYPE_HEIGHT_M:
            return TYPE_HEIGHT_M[_building_type(building)]
        if _building_type(building) in TANK_TYPES and len(getattr(building, "points_m", ())) >= 3:
            xs, ys = [x for x, _ in building.points_m], [y for _, y in building.points_m]
            return max(3.0, min(25.0, 0.8 * min(max(xs) - min(xs), max(ys) - min(ys))))
    return max(3.0, float(getattr(building, "height_m", 8.0)))


def _building_type(building: Building) -> str:
    return str(getattr(building, "building_type", "") or "").casefold()


def _building_is_windowless(building: Building) -> bool:
    """Garages, sheds, tanks and other outbuildings: plain walls, no window rows."""
    return _building_type(building) in OUTBUILDING_TYPES or _building_type(building) in TANK_TYPES


def _building_is_house_by_tag(building: Building) -> bool:
    return str(getattr(building, "building_type", "") or "").lower() in HOUSE_BUILDING_TYPES


def _uses_gabled_roof(building: Building) -> bool:
    roof_shape = str(getattr(building, "roof_shape", "") or "").casefold()
    if roof_shape:
        return roof_shape in {"gabled", "gable", "pitched"}
    return _building_is_house_by_tag(building) or _building_type(building) in CHURCH_TYPES | {"greenhouse", "glasshouse"}


SIGN_CATEGORY_BY_VENUE_TYPE = {
    "restaurant": "food", "fast_food": "food", "food_court": "food",
    "cafe": "food", "ice_cream": "food", "bakery": "food",
    "bar": "drink", "pub": "drink", "biergarten": "drink", "nightclub": "drink",
    "supermarket": "grocery", "convenience": "grocery", "grocery": "grocery",
    "greengrocer": "grocery", "butcher": "grocery", "deli": "grocery",
    "pharmacy": "health", "doctors": "health", "dentist": "health",
    "clinic": "health", "hospital": "health", "veterinary": "health",
    "bank": "finance", "atm": "finance", "bureau_de_change": "finance",
    "hotel": "lodging", "hostel": "lodging", "motel": "lodging", "guest_house": "lodging",
    "hairdresser": "beauty", "beauty": "beauty", "spa": "beauty", "massage": "beauty",
    "fuel": "automotive", "car_repair": "automotive", "car": "automotive", "car_wash": "automotive",
    "clothes": "retail", "shoes": "retail", "electronics": "retail", "furniture": "retail",
    "books": "retail", "gift": "retail", "department_store": "retail", "mall": "retail",
    "kiosk": "retail", "florist": "retail", "jewelry": "retail", "toys": "retail",
    "sports": "retail", "mobile_phone": "retail", "hardware": "retail", "variety_store": "retail",
}


# windows.md: _building_is_commercial used to only recognize
# COMMERCIAL_AMENITIES' narrow food/drink list, missing every venue type
# SIGN_CATEGORY_BY_VENUE_TYPE above already classifies as commercial
# signage (supermarkets, pharmacies, banks, hotels, most retail shops) -
# reusing that existing, already-curated mapping's keys instead of a
# second, narrower one keeps the two in sync and covers the spec's own
# examples directly.
COMMERCIAL_VENUE_TYPES = frozenset(SIGN_CATEGORY_BY_VENUE_TYPE) | COMMERCIAL_AMENITIES
