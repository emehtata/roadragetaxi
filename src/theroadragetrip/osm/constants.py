import logging
import math
from typing import Dict, Optional, Tuple



logger = logging.getLogger(__name__)


# Superseded by config.py's catalog-based city list (load_city_catalog/
# cities_from_config, backed by the bundled municipality data) for actual
# city selection - kept here, private, only to seed BBOX_PRESETS/
# DEFAULT_BBOX below. Nothing outside this module reads it.
_CITY_CENTERS: Dict[str, Tuple[float, float]] = {
    "Helsinki": (60.169525, 24.935446),
    "Espoo": (60.205000, 24.652000),
    "Tampere": (61.499113, 23.787117),
    "Vantaa": (60.294000, 25.041000),
    "Oulu": (65.012000, 25.468000),
    "Turku": (60.451483, 22.268686),
    "Jyväskylä": (62.241470, 25.720880),
    "Kuopio": (62.892382, 27.677028),
    "Lahti": (60.982674, 25.661509),
    "Sysmä": (61.502271, 25.680613),
}


def bbox_from_center(lat: float, lon: float, size_km: float = 4.0) -> Tuple[float, float, float, float]:
    """Calculate (south, west, north, east) bbox around a center coordinate of size_km x size_km."""
    half_size_km = size_km / 2.0
    # 1 deg latitude is approx 111.0 km
    dlat = half_size_km / 111.0
    # 1 deg longitude varies with latitude
    dlon = half_size_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return (
        round(lat - dlat, 6),
        round(lon - dlon, 6),
        round(lat + dlat, 6),
        round(lon + dlon, 6),
    )


BBOX_PRESETS: Dict[str, Tuple[float, float, float, float]] = {
    name.lower(): bbox_from_center(lat, lon, size_km=3.0)
    for name, (lat, lon) in _CITY_CENTERS.items()
}


DEFAULT_BBOX = BBOX_PRESETS["oulu"]


# natural=* ground-cover values that count as Scenery (osm/build.py). Unlike
# landuse=*/leisure=* (any value is safe to treat as generic ground-cover
# scenery - see build.py), natural=* also covers values that must NOT become
# a Scenery polygon: water/bay/strait (their own Water feature, handled
# first), tree (a point, not an area), coastline/peak/cliff/ridge (not
# ground cover at all - unhandled here). So natural genuinely needs a
# whitelist, unlike the other two - kept in exactly one place and shared by
# both the Overpass query (overpass.py builds its regex from this) and
# build_ways()'s classification, so the two can't drift apart the way
# landuse/leisure did (see git history: overpass.py once hand-maintained
# its own separate landuse/leisure whitelist that fell out of sync with
# what build_ways() actually classified).
NATURAL_SCENERY_KINDS: Tuple[str, ...] = ("wood", "scrub", "grass", "sand", "heath")


DEFAULT_ROAD_HALF_WIDTH_M = 3.0

# A crossing's own road can be wide enough that its rendered zebra-stripe
# width overlaps a *different* crossing nearby - real, compact junctions
# routinely map one highway=crossing node per leg within a few meters of
# each other, and each one sized to its own road's width bleeds into the
# open junction interior and into its neighbors. Search this far for the
# nearest other crossing and clip width_m to that distance, so no
# crossing's stripes extend past the midpoint toward another one.
CROSSING_OVERLAP_SEARCH_RADIUS_M = 25.0


HIGHWAY_HALF_WIDTH = {
    "motorway": 7.0,
    "trunk": 6.5,
    "primary": 6.0,
    "secondary": 5.5,
    "tertiary": 5.0,
    "unclassified": 4.5,
    "residential": 4.5,
    "living_street": 4.0,
    "busway": 4.0,
    "service": 3.5,
    "track": 2.0,
    "path": 1.2,
    "footway": 1.2,
    "cycleway": 1.5,
}


DEFAULT_SPEED_LIMITS_KMH = {
    "motorway": 100,
    "trunk": 80,
    "primary": 80,
    "secondary": 80,
    "tertiary": 60,
    "unclassified": 50,
    "residential": 40,
    "living_street": 20,
    "busway": 50,
    "service": 30,
    "track": 30,
    "path": 20,
    "footway": 20,
    "cycleway": 20,
}


def parse_speed_limit_kmh(maxspeed_tag: Optional[str], highway_type: str) -> int:
    """Parse OSM maxspeed tag into integer km/h with Finnish statutory fallbacks."""
    if maxspeed_tag:
        tag_str = str(maxspeed_tag).strip().lower().split(";")[0].strip()
        unit_multiplier = 1.609344 if "mph" in tag_str else 1.0
        numeric = tag_str.replace("km/h", "").replace("kph", "").replace("mph", "").strip()
        try:
            value = float(numeric)
            if value > 0.0:
                return round(value * unit_multiplier)
        except ValueError:
            pass
        if "urban" in tag_str:
            return 50
        if "rural" in tag_str:
            return 80
        if "motorway" in tag_str:
            return 100
        if "living_street" in tag_str:
            return 20

    return DEFAULT_SPEED_LIMITS_KMH.get(highway_type, 50)
