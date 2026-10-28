"""Map styling shared by the headless server and rendering clients."""

from typing import Optional, Tuple

from .osm import Way


SURFACE_COLORS = {
    "asphalt": (70, 70, 70),
    "paved": (70, 70, 70),
    "chipseal": (90, 88, 82),
    "concrete": (142, 142, 138),
    "concrete:lanes": (142, 142, 138),
    "concrete:plates": (142, 142, 138),
    "paving_stones": (150, 137, 117),
    "paving_stones:lanes": (150, 137, 117),
    "sett": (145, 139, 129),
    "cobblestone": (125, 120, 112),
    "unhewn_cobblestone": (125, 120, 112),
    "grass_paver": (105, 128, 90),
    "grass_paver:lanes": (105, 128, 90),
    "metal": (115, 126, 132),
    "compacted": (125, 112, 92),
    "fine_gravel": (145, 132, 108),
    "gravel": (150, 135, 105),
    "pebblestone": (155, 145, 125),
    "rock": (135, 131, 122),
    "unpaved": (155, 140, 108),
    "dirt": (125, 98, 68),
    "ground": (130, 105, 75),
    "earth": (130, 105, 75),
    "clay": (155, 112, 78),
    "mud": (95, 76, 55),
    "sand": (190, 170, 120),
    "grass": (75, 125, 62),
    "wood": (112, 83, 55),
    "woodchips": (146, 112, 72),
    "snow": (220, 229, 232),
    "ice": (160, 200, 225),
}


def surface_color(surface: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """Shared road/area material palette; unknown surfaces keep their existing fallback."""
    key = str(surface or "").lower().split(";")[0].strip()
    return SURFACE_COLORS.get(key)


LEGACY_HIGHWAY_COLORS = {
    "motorway": (58, 58, 60), "motorway_link": (58, 58, 60),
    "trunk": (60, 60, 60), "trunk_link": (60, 60, 60),
    "primary": (63, 61, 58), "primary_link": (63, 61, 58),
    "secondary": (66, 64, 60), "secondary_link": (66, 64, 60),
    "tertiary": (68, 66, 62), "tertiary_link": (68, 66, 62),
    "unclassified": (70, 68, 63), "residential": (72, 70, 65),
    "service": (78, 75, 68), "track": (120, 105, 80),
}


# Draw order among roads on the same level: the more important road on top
# where two meet, then paved over unpaved, then (godot/map_chunk.gd) the wider.
ROAD_CLASS_RANK = {
    "motorway": 9, "motorway_link": 9, "trunk": 8, "trunk_link": 8, "primary": 7, "primary_link": 7,
    "secondary": 6, "secondary_link": 6, "tertiary": 5, "tertiary_link": 5, "unclassified": 4,
    "residential": 4, "busway": 4, "living_street": 3, "service": 2, "track": 1,
}
UNPAVED_SURFACES = frozenset({"unpaved", "compacted", "gravel", "fine_gravel", "dirt", "earth", "ground", "grass",
                              "sand", "mud", "pebblestone", "woodchips", "rock"})


def road_draw_rank(way: Way) -> int:
    """Class, then paved: twice the class rank, plus one if paved (unknown counts as paved, a track as not)."""
    surface = str(getattr(way, "surface", "") or "").lower().split(";")[0].strip()
    paved = surface not in UNPAVED_SURFACES and (surface or way.highway != "track")
    return ROAD_CLASS_RANK.get(way.highway, 0) * 2 + int(bool(paved))


def road_color_for_way(way: Way) -> Tuple[int, int, int]:
    """Return a road color from OSM surface, then highway-class fallback."""
    color = surface_color(getattr(way, "surface", None))
    if color is not None:
        return color
    if not way.is_drivable:
        return (115, 145, 150) if way.highway == "cycleway" else (150, 150, 142)
    if getattr(way, "is_ice_road", False):
        return (160, 200, 225)
    if getattr(way, "is_busway", False) or way.highway == "busway":
        return (80, 72, 60)
    if way.highway == "living_street":
        return (85, 80, 78)
    return LEGACY_HIGHWAY_COLORS.get(way.highway, (70, 70, 70))


SCENERY_COLORS = {
    "camp_site": (106, 140, 79), "caravan_site": (120, 143, 94), "camp_pitch": (117, 148, 88),
    "theme_park": (188, 174, 139),
    "forest": (40, 78, 42), "wood": (40, 78, 42), "scrub": (108, 120, 78),
    "heath": (136, 124, 92), "park": (100, 145, 80), "garden": (104, 150, 86),
    "meadow": (152, 160, 92), "grass": (112, 150, 86), "greenfield": (150, 165, 110),
    "nature_reserve": (62, 102, 56), "pitch": (80, 150, 64), "playground": (150, 138, 104),
    "dog_park": (100, 142, 82), "track": (176, 96, 70), "sand": (196, 180, 130),
    "beach": (206, 192, 150), "grassland": (146, 158, 96), "shrubbery": (100, 118, 76),
    "wetland": (118, 130, 96), "farmland": (172, 148, 88), "farmyard": (146, 130, 100),
    "allotments": (142, 132, 82), "flowerbed": (150, 90, 120),
    "greenhouse_horticulture": (208, 210, 202), "residential": (108, 138, 92),
    "commercial": (112, 108, 104), "retail": (118, 104, 96), "industrial": (98, 96, 94),
    "institutional": (108, 104, 96), "education": (108, 104, 96), "civil": (108, 104, 96),
    "religious": (98, 94, 86), "military": (98, 102, 82), "railway": (108, 100, 92),
    "recreation_ground": (98, 142, 78), "brownfield": (142, 122, 96),
    "construction": (170, 142, 96), "quarry": (130, 124, 116), "landfill": (112, 102, 82),
    "cemetery": (88, 112, 82), "grave_yard": (88, 112, 82), "biergarten": (146, 136, 110),
    "marina": (132, 130, 122), "slipway": (132, 130, 122),
    "bathing_place": (152, 168, 128), "swimming_pool": (68, 165, 185),
    "sports_centre": (122, 110, 94), "sports_hall": (122, 110, 94),
    "fitness_centre": (122, 110, 94), "fitness_station": (98, 142, 78),
    "stadium": (122, 110, 94), "bleachers": (150, 146, 140), "horse_riding": (152, 132, 92),
    "ice_rink": (150, 140, 120),  # gravel/asphalt; ice in winter
    "firepit": (100, 90, 70), "outdoor_seating": (112, 102, 92), "sauna": (112, 92, 72),
    "parking": (98, 98, 98), "pedestrian_area": (125, 120, 112), "fuel": (92, 88, 84),
    "traffic_island": (112, 150, 86),
    "miniature_golf": (168, 154, 116),
    "golf_course": (88, 128, 64), "golf_fairway": (106, 156, 75),
    "golf_tee": (126, 172, 88), "golf_green": (142, 188, 100),
}

SPECKLE_SCENERY_KINDS = frozenset({
    "forest", "wood", "scrub", "heath", "park", "garden", "meadow", "grass",
    "greenfield", "nature_reserve", "recreation_ground", "dog_park",
    "fitness_station", "cemetery", "farmland", "farmyard", "allotments",
    "sand", "beach", "grassland", "shrubbery", "wetland", "traffic_island",
})

# Open ground without speckles that still follows the season (snow in
# winter): flowerbeds stayed pink under snow before.
SEASONAL_GROUND_KINDS = frozenset({
    "residential", "recreation_ground", "flowerbed", "playground", "horse_riding",
    "sports_centre", "stadium", "grave_yard", "biergarten",
    "golf_course", "golf_fairway", "golf_tee", "golf_green", "miniature_golf",
})

# Finnish winter: sports fields and rinks are flooded and frozen for
# skating - ice, not snow, once the winter (snow) weight reaches
# FIELDS_FROZEN_WINTER_WEIGHT: drawn as ice and driven on with ice grip.
FROZEN_IN_WINTER_KINDS = frozenset({"pitch", "ice_rink"})
FIELDS_FROZEN_WINTER_WEIGHT = 0.5  # godot chunk_detail.gd uses the same

# Floodlit when dark, 07-22 (server: sports_lights_on).
FLOODLIT_KINDS = frozenset({"pitch", "ice_rink", "track", "stadium"})

DISTRICT_PLACE_KINDS = {
    "suburb", "neighbourhood", "quarter", "village", "town", "city", "hamlet",
}
