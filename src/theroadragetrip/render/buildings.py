from . import common
from .common import (
    SCREEN_W,
    SCREEN_H,
    PX_PER_M,
    CACHE_PADDING_PX,
    INCREMENTAL_REBUILD_BUDGET_S,
    DEFAULT_SUN_LATITUDE,
    DEFAULT_SUN_LONGITUDE,
    _rebuild_or_stale,
    _blit_stale_static_cache,
    _static_cache_zoom,
    _reusable_alpha_surface,
    solar_altitude_and_events,
    world_to_screen,
    get_viewport_bounds,
)
import math
import time
from typing import List, Optional, Tuple

from ..performance import advance_chunked


from ..geo import dist_point_to_segment, point_in_polygon
from ..osm import Building, ParkingSpace, Place


BUILDING_WALL_COLORS = ((158, 105, 82), (174, 166, 143), (116, 131, 119), (139, 139, 137))
BUILDING_ROOF_COLORS = ((92, 57, 48), (102, 96, 82), (66, 83, 69), (83, 86, 87))
OPEN_ROOF_COLOR = (138, 145, 148, 185)
OPEN_ROOF_EDGE_COLOR = (65, 69, 71, 235)
OPEN_ROOF_POLE_COLOR = (105, 110, 112, 255)
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
ILLUMINATED_WINDOW_CACHE_PADDING_PX = 224
_illuminated_window_cache = None
_illuminated_window_job = None
# Per-frame budget for extending the illuminated-window glow cache with
# newly-indexed buildings (bin-loader-v6.md); dedicated, not TILE_MERGE_BUDGET_S.
ILLUMINATED_WINDOW_CACHE_BUDGET_S = 0.004
GENERATED_DRIVEWAY_MAX_LENGTH_M = 35.0
GENERATED_HOUSE_PARKING_BAYS = 2


def _is_open_roof(building: Building) -> bool:
    """Return whether an OSM building footprint is a drive-through roof."""
    return str(getattr(building, "building_type", "") or "").casefold() == "roof"


def _draw_open_roof(screen, points, px_per_m: float) -> None:
    """Draw the below-vehicle shadow and supports of an open canopy."""
    import pygame

    shadow_offset = max(1, round(px_per_m * 0.35))
    pygame.draw.polygon(
        screen,
        (30, 32, 33, 75),
        [(x + shadow_offset, y + shadow_offset) for x, y in points],
    )
    # OSM roof outlines do not normally map each individual support. Corner
    # posts give the canopy a readable structure while leaving its footprint
    # open for the taxi and the fuel-pump scenery beneath it.
    pole_radius = max(1, round(px_per_m * 0.18))
    for point in points:
        pygame.draw.circle(screen, OPEN_ROOF_EDGE_COLOR, point, pole_radius + 1)
        pygame.draw.circle(screen, OPEN_ROOF_POLE_COLOR, point, pole_radius)


def draw_open_roof_overlays(
    screen,
    buildings: List[Building],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw canopies above vehicles so they pass underneath. Returns the
    roofs drawn, as RoofCover, so whatever is underneath can be outlined."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(
        camx, camy, px_per_m, screen_w, screen_h, 20.0
    )
    visible_buildings = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else buildings
    )
    drawn = []
    for building in visible_buildings:
        if not _is_open_roof(building) or len(building.points_m) < 3:
            continue
        bbox = getattr(building, "bbox", None)
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
            if bbox[2] < vminx or bbox[0] > vmaxx or bbox[3] < vminy or bbox[1] > vmaxy:
                continue
        drawn.append(building)
        points = [
            world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h)
            for x, y in building.points_m
        ]
        pygame.draw.polygon(screen, OPEN_ROOF_COLOR, points)
        pygame.draw.lines(
            screen,
            OPEN_ROOF_EDGE_COLOR,
            True,
            points,
            max(1, round(px_per_m * 0.12)),
        )
    return RoofCover(drawn)


class RoofCover:
    """The open roofs drawn this frame: is a world point underneath one?
    (bounding box first, then the footprint)."""

    def __init__(self, roofs) -> None:
        self.roofs = []
        for roof in roofs:
            xs, ys = zip(*roof.points_m)
            self.roofs.append(((min(xs), min(ys), max(xs), max(ys)), roof.points_m))

    def __bool__(self) -> bool:
        return bool(self.roofs)

    def covers(self, x: float, y: float) -> bool:
        return any(
            bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3] and point_in_polygon(x, y, points)
            for bbox, points in self.roofs
        )

# Facade sign colors by venue category, loosely matching real-world signage
# conventions (warm red for dining, a pharmacy-style green cross, navy and
# gold for banks/hotels, ...). Each entry is (background, border, text).
# Anything not covered by SIGN_CATEGORY_BY_VENUE_TYPE below falls back to
# SIGN_THEME_DEFAULT, the original dark-wood-and-gold look.
SIGN_THEME_DEFAULT = ((40, 31, 22), (211, 169, 70), (250, 239, 190))
SIGN_THEMES = {
    "food": ((92, 24, 22), (219, 150, 60), (250, 235, 210)),
    "drink": ((46, 20, 56), (176, 120, 200), (240, 225, 245)),
    "grocery": ((22, 58, 30), (140, 200, 110), (235, 245, 225)),
    "health": ((16, 66, 56), (120, 220, 170), (230, 250, 240)),
    "finance": ((18, 28, 48), (190, 170, 90), (230, 232, 240)),
    "lodging": ((26, 34, 58), (200, 190, 150), (235, 235, 225)),
    "beauty": ((70, 28, 46), (230, 160, 190), (250, 235, 240)),
    "automotive": ((54, 40, 20), (230, 150, 60), (245, 230, 205)),
    "retail": ((20, 34, 58), (130, 170, 220), (230, 238, 248)),
}
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


def _building_sign_theme(venue_type) -> tuple:
    """Return the (background, border, text) sign colors for a venue kind."""
    key = str(venue_type or "").lower()
    category = SIGN_CATEGORY_BY_VENUE_TYPE.get(key)
    if category is None and key in COMMERCIAL_BUILDING_TYPES:
        category = "retail"
    return SIGN_THEMES.get(category, SIGN_THEME_DEFAULT)


_building_sign_font_cache = {}
_building_sign_surface_cache = {}
_building_visual_plan_cache = {}
# In-progress incremental buildings-cache rebuild, or None - same mechanism
# as roads.py's _road_wip (see its docstring for the full rationale): a
# real drive showed draw_buildings' rebuild routinely costing 15-27ms on
# its own, past a whole frame's 16.67ms budget, every time the camera
# crossed a cache-grid boundary. Unlike roads, buildings' per-item drawing
# loop is the only expensive phase (no separate O(n^2) precompute like
# roads' endpoint-join), so this only needs the one chunked stage.
_building_wip = None
MIN_BUILDING_SIGN_WIDTH_PX = 24
MIN_BUILDING_SIGN_DEPTH_PX = 8
MAX_BUILDING_SIGN_FONT_SIZE = 32
# Real-world fascia-sign size (a shopfront board spanning most of a single
# storefront, roughly eye-level tall) rather than a fixed pixel cap, so signs
# stay a believable size at every zoom level instead of ballooning at low
# zoom or shrinking to nothing at high zoom.
MAX_BUILDING_SIGN_WIDTH_M = 3.0
MAX_BUILDING_SIGN_HEIGHT_M = 1.0
# A door itself is always ground-anchored and one storey tall (see the
# entrance-drawing loop below) - this ratio no longer describes the door,
# only where a facade sign is anchored: comfortably above where even a
# tall building's ground-floor door reaches, with a little clearance, so
# a sign never covers a doorway.
DOOR_TOP_V_RATIO = 0.48
SIGN_V_CLEARANCE = 0.04
# Cap on the on-screen facade "depth" (the pseudo-3D roof-offset used to draw
# walls). Previously capped at 30px, which - at the default 9.0 px/m zoom -
# is reached by any building taller than ~9.5m (about 3 storeys), so taller
# buildings all rendered at the same visual height regardless of their real
# height_m/levels. Raised well past the height of a typical multi-storey
# building in the bundled Finnish city data so height differences stay
# visible across more of the realistic range; very tall buildings still cap
# out rather than growing without bound.
MAX_BUILDING_DEPTH_PX = 100
# Minimum on-screen height for one drawn floor row before floors start
# visually merging together; used to cap how many of a tall building's
# storeys are actually drawn as separate window rows within MAX_BUILDING_DEPTH_PX,
# so a many-storey building doesn't garble its facade into overlapping bands.
MIN_FLOOR_HEIGHT_PX = 3.0


def mask_buildings_from_light_surface(
    surface, buildings, camx, camy, px_per_m, screen_w=SCREEN_W, screen_h=SCREEN_H,
) -> None:
    """Remove ground-level lighting from building walls and roofs."""
    import pygame

    for building in buildings or ():
        if len(getattr(building, "points_m", ())) < 3:
            continue
        if _is_open_roof(building):
            # Headlights and yard lighting remain visible beneath a canopy;
            # only solid buildings should erase the ground-level light map.
            continue
        footprint = [
            world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h)
            for x, y in building.points_m
        ]
        pygame.draw.polygon(surface, (0, 0, 0, 0), footprint)
        if px_per_m <= 0.45:
            continue
        height = _building_render_height(building)
        depth = min(MAX_BUILDING_DEPTH_PX, max(3, int(height * 0.35 * px_per_m)))
        roof = [(x - depth * 0.7, y - depth) for x, y in footprint]
        pygame.draw.polygon(surface, (0, 0, 0, 0), roof)
        for index, point in enumerate(footprint):
            pygame.draw.polygon(
                surface, (0, 0, 0, 0),
                [point, footprint[(index + 1) % len(footprint)], roof[(index + 1) % len(roof)], roof[index]],
            )


def _building_visual_plan(building):
    """Cache camera-independent facade measurements for one building."""
    points = tuple(getattr(building, "points_m", ()))
    entrances = tuple(getattr(building, "entrances", ()))
    cache_key = (
        id(building),
        points,
        entrances,
        getattr(building, "levels", None),
        getattr(building, "height_m", 8.0),
        getattr(building, "venue_type", None),
        tuple((place.x, place.y, place.name) for place in getattr(building, "associated_places", ())),
    )
    cached = _building_visual_plan_cache.get(id(building))
    if cached is not None and cached[0] == cache_key:
        return cached[1]

    edge_lengths = []
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        edge_lengths.append(math.hypot(next_point[0] - point[0], next_point[1] - point[1]))
    entrance_edges = set()
    for entrance_x, entrance_y in entrances:
        entrance_edges.add(min(
            range(len(points)),
            key=lambda candidate: dist_point_to_segment(
                entrance_x,
                entrance_y,
                points[candidate][0],
                points[candidate][1],
                points[(candidate + 1) % len(points)][0],
                points[(candidate + 1) % len(points)][1],
            ),
            default=-1,
        ))
    plan = (tuple(edge_lengths), frozenset(entrance_edges))
    _building_visual_plan_cache[id(building)] = (cache_key, plan)
    return plan


MIN_SIGN_FORESHORTEN = 0.35


def _building_sign_foreshorten(edge_x: float, edge_y: float, wall_normal_x: float, wall_normal_y: float) -> float:
    """Return how strongly a facade sign should be squashed for this wall.

    `draw_buildings` fakes a 3D facade by offsetting every building's roof by
    one fixed screen-space vector rather than a true per-wall normal, so a
    wall's on-screen "depth" side (point -> roof_point) is not generally
    perpendicular to its "width" side (point -> next_point). The sign quad
    already reflects that (its corners follow both directions), but the sign
    *text* was only ever rotated to match the width direction, never
    foreshortened to match the depth direction - so it kept its normal,
    unsquashed aspect ratio no matter how obliquely the wall sat relative to
    the fixed extrusion, making it look pasted on flat instead of lying on
    the wall. The sine of the angle between the two unit directions is 1.0
    when they're perpendicular (no correction needed) and shrinks toward 0.0
    as the wall becomes edge-on to the extrusion direction (most oblique);
    clamped to a floor so text never disappears entirely.
    """
    sine = abs(edge_x * wall_normal_y - edge_y * wall_normal_x)
    return max(MIN_SIGN_FORESHORTEN, min(1.0, sine))


def _building_sign_surface(pygame, font, text, sign_width, sign_depth, angle, foreshorten=1.0, text_color=(250, 239, 190)):
    """Reuse static venue sign text across viewport cache rebuilds."""
    key = (id(font), text, sign_width, sign_depth, round(angle, 3), round(foreshorten, 3), text_color)
    cached = _building_sign_surface_cache.get(key)
    if cached is not None:
        return cached
    text_surface = font.render(text, True, text_color)
    target_width = max(4, sign_width - 8)
    # Always rescale to the wall-foreshortened height, not just when the
    # rendered text is too wide, so the sign is squashed to match the wall's
    # perspective even when the glyphs would otherwise already fit.
    target_height = max(4, int(round((sign_depth - 2) * foreshorten)))
    if text_surface.get_width() != target_width or text_surface.get_height() != target_height:
        text_surface = pygame.transform.smoothscale(text_surface, (target_width, target_height))
    cached = pygame.transform.rotate(text_surface, angle)
    _building_sign_surface_cache[key] = cached
    return cached


def _building_window_story_count(building: Building) -> int:
    """Return the OSM floor count, or a height-based fallback."""
    levels = getattr(building, "levels", None)
    if levels is not None:
        try:
            return max(1, min(40, int(levels)))
        except (TypeError, ValueError):
            pass
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
HOUSE_BUILDING_TYPES = {"house", "detached", "bungalow", "cabin", "semidetached_house", "farm"}


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
    """Use a Finnish 1.5-storey fallback for untagged detached houses."""
    if (
        _building_is_house_by_tag(building)
        and getattr(building, "levels", None) is None
        and not getattr(building, "height_is_explicit", False)
    ):
        return 4.5
    return max(3.0, float(getattr(building, "height_m", 8.0)))


def _building_is_house_by_tag(building: Building) -> bool:
    return str(getattr(building, "building_type", "") or "").lower() in HOUSE_BUILDING_TYPES


def _uses_gabled_roof(building: Building) -> bool:
    roof_shape = str(getattr(building, "roof_shape", "") or "").casefold()
    if roof_shape:
        return roof_shape in {"gabled", "gable", "pitched"}
    return _building_is_house_by_tag(building)


def _clip_polygon_to_roof_half(points, center, axis, keep_positive):
    """Clip a convex roof footprint to one side of its longitudinal ridge."""
    if not points:
        return []
    normal = (-axis[1], axis[0])

    def signed(point):
        value = (point[0] - center[0]) * normal[0] + (point[1] - center[1]) * normal[1]
        return value if keep_positive else -value

    output = []
    previous = points[-1]
    previous_value = signed(previous)
    for current in points:
        current_value = signed(current)
        if current_value >= 0.0:
            if previous_value < 0.0:
                ratio = previous_value / (previous_value - current_value)
                output.append((
                    previous[0] + (current[0] - previous[0]) * ratio,
                    previous[1] + (current[1] - previous[1]) * ratio,
                ))
            output.append(current)
        elif previous_value >= 0.0:
            ratio = previous_value / (previous_value - current_value)
            output.append((
                previous[0] + (current[0] - previous[0]) * ratio,
                previous[1] + (current[1] - previous[1]) * ratio,
            ))
        previous, previous_value = current, current_value
    return output


def _draw_gabled_roof(screen, roof, roof_color):
    """Draw two pitched facets and a ridge along the footprint's long axis."""
    import pygame

    if len(roof) < 3:
        return
    longest = max(
        zip(roof, roof[1:] + roof[:1]),
        key=lambda edge: (edge[1][0] - edge[0][0]) ** 2 + (edge[1][1] - edge[0][1]) ** 2,
    )
    dx, dy = longest[1][0] - longest[0][0], longest[1][1] - longest[0][1]
    length = max(1e-6, math.hypot(dx, dy))
    axis = (dx / length, dy / length)
    center = (
        sum(point[0] for point in roof) / len(roof),
        sum(point[1] for point in roof) / len(roof),
    )
    light = tuple(min(255, channel + 14) for channel in roof_color)
    dark = tuple(max(0, channel - 12) for channel in roof_color)
    for keep_positive, color in ((True, light), (False, dark)):
        facet = _clip_polygon_to_roof_half(roof, center, axis, keep_positive)
        if len(facet) >= 3:
            pygame.draw.polygon(screen, color, facet)
    projections = [(point[0] - center[0]) * axis[0] + (point[1] - center[1]) * axis[1] for point in roof]
    ridge_start = (center[0] + axis[0] * min(projections), center[1] + axis[1] * min(projections))
    ridge_end = (center[0] + axis[0] * max(projections), center[1] + axis[1] * max(projections))
    pygame.draw.line(screen, (58, 55, 52), ridge_start, ridge_end, 2)


def _nearest_house_driveway(building, ways, road_spatial_grid=None):
    """Return a synthetic (house edge, road edge) driveway when OSM has none."""
    if not _building_is_house_by_tag(building) or len(building.points_m) < 3:
        return None
    minx, miny, maxx, maxy = building.bbox
    margin = GENERATED_DRIVEWAY_MAX_LENGTH_M
    candidates = (
        road_spatial_grid.ways_in_rect(minx - margin, miny - margin, maxx + margin, maxy + margin)
        if road_spatial_grid is not None
        else ways
    )
    candidates = [way for way in candidates if getattr(way, "is_drivable", True)]
    # A mapped driveway wins; never paint a duplicate procedural one.
    for way in candidates:
        if getattr(way, "service", None) != "driveway":
            continue
        for point in way.points_m:
            if minx - 4.0 <= point[0] <= maxx + 4.0 and miny - 4.0 <= point[1] <= maxy + 4.0:
                return None

    facade_points = list(getattr(building, "entrances", ()) or ())
    facade_points.extend(
        ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
        for a, b in zip(building.points_m, building.points_m[1:] + building.points_m[:1])
    )
    best = None
    for way in candidates:
        if getattr(way, "highway", "") in {"motorway", "motorway_link", "trunk", "trunk_link"}:
            continue
        for ax, ay in facade_points:
            for (x1, y1), (x2, y2) in zip(way.points_m, way.points_m[1:]):
                dx, dy = x2 - x1, y2 - y1
                length_sq = dx * dx + dy * dy
                if length_sq <= 1e-9:
                    continue
                t = max(0.0, min(1.0, ((ax - x1) * dx + (ay - y1) * dy) / length_sq))
                centerline_point = (x1 + dx * t, y1 + dy * t)
                to_house_x, to_house_y = ax - centerline_point[0], ay - centerline_point[1]
                centerline_distance = math.hypot(to_house_x, to_house_y)
                edge_offset = min(centerline_distance, max(0.0, getattr(way, "half_width_m", 0.0)))
                if centerline_distance > 1e-9:
                    road_point = (
                        centerline_point[0] + to_house_x / centerline_distance * edge_offset,
                        centerline_point[1] + to_house_y / centerline_distance * edge_offset,
                    )
                else:
                    road_point = centerline_point
                distance = math.hypot(road_point[0] - ax, road_point[1] - ay)
                if distance <= GENERATED_DRIVEWAY_MAX_LENGTH_M and (best is None or distance < best[0]):
                    best = (distance, (ax, ay), road_point)
    return None if best is None else (best[1], best[2])


def _house_parking_key(building):
    bbox = getattr(building, "bbox", (0.0, 0.0, 0.0, 0.0))
    return tuple(round(float(value), 2) for value in bbox)


def _add_house_parking_for_building(building, ways, road_spatial_grid, parking_spaces, existing_keys) -> int:
    """Add two reservable residential bays for one building's driveway
    access, if it has one and doesn't already. Returns bays added (0 or
    GENERATED_HOUSE_PARKING_BAYS). Shared by the synchronous
    generate_detached_house_parking() and its chunked counterpart below."""
    key = _house_parking_key(building)
    if key in existing_keys:
        return 0
    access = _nearest_house_driveway(building, ways, road_spatial_grid)
    if access is None:
        return 0
    house_edge, road_edge = access
    dx, dy = road_edge[0] - house_edge[0], road_edge[1] - house_edge[1]
    access_length = math.hypot(dx, dy)
    if access_length < 5.5:
        return 0
    ux, uy = dx / access_length, dy / access_length
    lateral_x, lateral_y = -uy, ux
    bay_length, bay_width = 5.0, 2.5
    center_distance = bay_length * 0.5 + 0.5
    added = 0
    for bay_index in range(GENERATED_HOUSE_PARKING_BAYS):
        lateral_offset = (bay_index - (GENERATED_HOUSE_PARKING_BAYS - 1) * 0.5) * (bay_width + 0.3)
        center_x = house_edge[0] + ux * center_distance + lateral_x * lateral_offset
        center_y = house_edge[1] + uy * center_distance + lateral_y * lateral_offset
        half_length, half_width = bay_length * 0.5, bay_width * 0.5
        points = [
            (center_x + ux * half_length + lateral_x * half_width, center_y + uy * half_length + lateral_y * half_width),
            (center_x + ux * half_length - lateral_x * half_width, center_y + uy * half_length - lateral_y * half_width),
            (center_x - ux * half_length - lateral_x * half_width, center_y - uy * half_length - lateral_y * half_width),
            (center_x - ux * half_length + lateral_x * half_width, center_y - uy * half_length + lateral_y * half_width),
        ]
        xs, ys = [point[0] for point in points], [point[1] for point in points]
        parking_spaces.append(ParkingSpace(
            points_m=points,
            bbox=(min(xs), min(ys), max(xs), max(ys)),
            orientation=math.atan2(uy, ux),
            source_building_key=key,
            access_path=[house_edge, road_edge],
        ))
        added += 1
    existing_keys.add(key)
    return added


def _existing_house_parking_keys(parking_spaces) -> set:
    return {
        getattr(space, "source_building_key", None)
        for space in parking_spaces
        if getattr(space, "source_building_key", None) is not None
    }


def generate_detached_house_parking(buildings, ways, parking_spaces, road_spatial_grid=None) -> int:
    """Add two reservable residential bays to each generated house access."""
    existing_keys = _existing_house_parking_keys(parking_spaces)
    added = 0
    for building in buildings:
        added += _add_house_parking_for_building(building, ways, road_spatial_grid, parking_spaces, existing_keys)
    return added


def generate_detached_house_parking_chunk(
    buildings, ways, parking_spaces, road_spatial_grid, index: int, budget_s: float,
) -> Tuple[int, int]:
    """Budgeted version of generate_detached_house_parking (bin-loader-
    v3.md: measured up to ~1.9s in one frame against a dense real city
    load, 2376 bays over 20k buildings). Processes buildings[index:] until
    budget_s elapses. Returns (new_index, bays_added_this_call) -
    new_index == len(buildings) once finished. The caller owns `index`
    across calls; parking_spaces is mutated in place exactly like the
    synchronous version, so a partially-processed building list is always
    valid to query (just fewer bays exist yet, never wrong ones)."""
    existing_keys = _existing_house_parking_keys(parking_spaces)
    added = [0]

    def _process(building) -> None:
        added[0] += _add_house_parking_for_building(building, ways, road_spatial_grid, parking_spaces, existing_keys)

    new_index = advance_chunked(buildings, index, budget_s, _process)
    return new_index, added[0]


def _draw_generated_driveways(screen, buildings, ways, road_spatial_grid, camx, camy, px_per_m, screen_w, screen_h):
    import pygame

    border_width = max(2, round(6.2 * px_per_m))
    fill_width = max(1, round(5.6 * px_per_m))
    for building in buildings:
        driveway = _nearest_house_driveway(building, ways, road_spatial_grid)
        if driveway is None:
            continue
        points = [
            world_to_screen(point[0], point[1], camx, camy, px_per_m, screen_w, screen_h)
            for point in driveway
        ]
        pygame.draw.line(screen, (72, 70, 66), points[0], points[1], border_width)
        pygame.draw.line(screen, (126, 121, 111), points[0], points[1], fill_width)


def _visible_building_edges(points, roof) -> set[int]:
    """Return facade edges whose wall projection is not covered by the roof."""
    if not points or len(points) != len(roof):
        return set()
    visible = set()
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        roof_point = roof[index]
        next_roof = roof[(index + 1) % len(roof)]
        wall_midpoint = (
            (point[0] + next_point[0] + roof_point[0] + next_roof[0]) * 0.25,
            (point[1] + next_point[1] + roof_point[1] + next_roof[1]) * 0.25,
        )
        if not point_in_polygon(wall_midpoint[0], wall_midpoint[1], roof):
            visible.add(index)
    return visible


def _iter_building_window_slots(b: Building, pts, roof, visible_edges, depth: float):
    """Yield (edge_index, floor_index, window_index, storefront_row, window_quad)
    for every window slot on `b`'s visible facades, in the exact screen-space
    geometry the static day render uses - shared with the night illumination
    overlay (draw_illuminated_windows) so a lit window's glow lines up
    pixel-for-pixel with the window baked into the cached building surface."""
    is_commercial = _building_is_commercial(b)
    is_house = _building_is_house(b)
    story_count = min(_building_window_story_count(b), max(1, int(depth / MIN_FLOOR_HEIGHT_PX)))
    max_windows_per_edge = 2 if is_house else 3
    min_window_gap_px = 44.0 if is_house else 32.0
    for edge_index in visible_edges:
        point = pts[edge_index]
        next_point = pts[(edge_index + 1) % len(pts)]
        roof_point = roof[edge_index]
        edge_x = next_point[0] - point[0]
        edge_y = next_point[1] - point[1]
        edge_length = math.hypot(edge_x, edge_y)
        if edge_length < 12.0:
            continue
        edge_x /= edge_length
        edge_y /= edge_length
        roof_x = roof_point[0] - point[0]
        roof_y = roof_point[1] - point[1]
        window_count = max(1, min(max_windows_per_edge, int(edge_length // min_window_gap_px)))
        for floor_index in range(story_count):
            if is_house and story_count > 1 and floor_index % 2 == 1:
                # windows.md section 3: houses read as sparser than an
                # apartment block - skip alternating upper floors.
                continue
            floor_position = 0.18 + 0.64 * (floor_index + 0.5) / story_count
            floor_height = abs(roof_y) / story_count
            storefront_row = is_commercial and floor_index == 0
            # Proportional to floor_height/edge_length (both already scale
            # with px_per_m via the screen-space pts/roof passed in), so
            # windows grow and shrink with zoom instead of pinning to a
            # fixed pixel size - only a lower floor for visibility at low
            # zoom, no upper cap.
            window_height = max(1.0, floor_height * 0.55)
            if storefront_row:
                window_height *= 1.45
            elif is_house:
                window_height *= 0.75
            for window_index in range(window_count):
                center = (window_index + 1) / (window_count + 1)
                center_x = point[0] + (next_point[0] - point[0]) * center + roof_x * floor_position
                center_y = point[1] + (next_point[1] - point[1]) * center + roof_y * floor_position
                half_width = max(0.5, edge_length / (window_count + 2) * 0.45) / 2
                if storefront_row:
                    half_width *= 1.35
                elif is_house:
                    half_width *= 0.75
                pane_x = -roof_x * window_height / max(abs(roof_y), 1.0)
                pane_y = -roof_y * window_height / max(abs(roof_y), 1.0)
                window = [
                    (center_x - edge_x * half_width, center_y - edge_y * half_width),
                    (center_x + edge_x * half_width, center_y + edge_y * half_width),
                    (center_x + edge_x * half_width + pane_x, center_y + edge_y * half_width + pane_y),
                    (center_x - edge_x * half_width + pane_x, center_y - edge_y * half_width + pane_y),
                ]
                yield edge_index, floor_index, window_index, storefront_row, window


def _building_sign_anchor(building: Building, place_x: float, place_y: float, edge_index: int):
    """Project a venue point inside a building onto its facade edge."""
    start = building.points_m[edge_index]
    end = building.points_m[(edge_index + 1) % len(building.points_m)]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    ratio = 0.5
    if length_sq > 1e-9:
        ratio = max(0.0, min(1.0, ((place_x - start[0]) * dx + (place_y - start[1]) * dy) / length_sq))
    return start[0] + dx * ratio, start[1] + dy * ratio


def _building_sign_corners(point, next_point, roof_point, next_roof, center_ratio, width_px, depth_px):
    """Return a sign quad lying on the projected facade wall."""
    edge_x = next_point[0] - point[0]
    edge_y = next_point[1] - point[1]
    edge_length = math.hypot(edge_x, edge_y)
    wall_x = roof_point[0] - point[0]
    wall_y = roof_point[1] - point[1]
    wall_depth = math.hypot(wall_x, wall_y)
    if edge_length <= 1e-9 or wall_depth <= 1e-9:
        return None
    half_u = min(0.36, width_px / (2.0 * edge_length))
    half_v = min(0.16, depth_px / (2.0 * wall_depth))
    # Anchor above where doors are drawn (see DOOR_TOP_V_RATIO) so a sign
    # never covers a doorway, with a small gap and a ceiling that keeps it
    # clear of the roofline.
    center_v = min(0.88 - half_v, DOOR_TOP_V_RATIO + SIGN_V_CLEARANCE + half_v)

    def point_at(u, v):
        base_x = point[0] + edge_x * u
        base_y = point[1] + edge_y * u
        top_x = roof_point[0] + (next_roof[0] - roof_point[0]) * u
        top_y = roof_point[1] + (next_roof[1] - roof_point[1]) * u
        return (
            base_x + (top_x - base_x) * v,
            base_y + (top_y - base_y) * v,
        )

    return [
        point_at(center_ratio - half_u, center_v - half_v),
        point_at(center_ratio + half_u, center_v - half_v),
        point_at(center_ratio + half_u, center_v + half_v),
        point_at(center_ratio - half_u, center_v + half_v),
    ]


def _building_sign_angle(point, next_point) -> float:
    """Return the upright screen-space tangent angle for a facade sign."""
    angle = math.degrees(math.atan2(-(next_point[1] - point[1]), next_point[0] - point[0]))
    if angle > 90.0:
        angle -= 180.0
    elif angle < -90.0:
        angle += 180.0
    return angle


# windows.md section 5/6: night-time window illumination.
#
# Lit/unlit is decided per window slot from a fast deterministic hash of
# (building identity, edge, floor, window index) - the same GLSL-style
# fract(sin(x)*C) trick _advance_building_rebuild already uses for its
# per-building texture_seed - instead of the `random` module, so a given
# window's state never changes as the camera moves or the building cache
# gets rebuilt (it depends on none of that), and needs no per-frame
# regeneration or stored state.
WINDOW_LIT_COLOR = (232, 189, 108)
# Deliberately dimmer than STREET_LIGHT_CORE_COLOR (215, 215, 200) in
# roads.py - windows.md asks that illuminated windows not outshine street
# lighting.
WINDOW_ILLUMINATION_ALPHA = 165


def _pseudo_random_unit(seed: float) -> float:
    """Deterministic pseudo-random value in [0, 1) for a float seed."""
    fractional = math.sin(seed * 12.9898) * 43758.5453
    return fractional - math.floor(fractional)


def _window_illumination_probability(b: Building, storefront_row: bool) -> float:
    """Fraction of a category's windows lit at night. Real cities read as
    mostly dark with only a scattering of occupied/awake windows lit -
    storefronts (already bright in the day render) go dark like any closed
    shop almost always; houses have fewer occupied rooms lit than an
    apartment block's many units."""
    if storefront_row:
        return 0.03
    if _building_is_house(b):
        return 0.08
    return 0.12


def _window_is_illuminated(building_id: int, edge_index: int, floor_index: int, window_index: int, probability: float) -> bool:
    seed = building_id * 0.0001 + edge_index * 7.13 + floor_index * 3.71 + window_index * 1.37
    return _pseudo_random_unit(seed) < probability


def draw_buildings(
    screen,
    buildings: List[Building],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    road_ways=None,
    road_spatial_grid=None,
    places: Optional[List[Place]] = None,
    profiler=None,
) -> None:
    """Draw cached static building geometry and facade details.

    Like roads.py's draw_ways (see its docstring for the full rationale),
    a stale buildings cache does not rebuild atomically - it advances an
    incremental rebuild by one time-budgeted chunk per call, blitting
    whatever's currently committed (the previous cache, until the new one
    finishes) either way, except for the very first build ever (nothing to
    fall back to), which stays a one-time synchronous cost.
    """
    cache_zoom = _static_cache_zoom(px_per_m)

    frame_cache_key = (
        id(buildings),
        len(buildings),
        id(buildings[-1]) if buildings else None,
        id(places),
        len(places) if places else 0,
        id(spatial_grid),
        id(road_ways),
        id(road_spatial_grid),
        *common._phased_cache_grid_cell("buildings", camx, camy, cache_zoom),
        cache_zoom,
        screen.get_size(),
    )
    if frame_cache_key == common._building_frame_cache_key and common._building_frame_cache_surface is not None:
        cached_camx, cached_camy = common._building_frame_cache_camera
        offset_x = round((cached_camx - camx) * cache_zoom) - CACHE_PADDING_PX
        offset_y = round((camy - cached_camy) * cache_zoom) - CACHE_PADDING_PX
        screen.blit(common._building_frame_cache_surface, (offset_x, offset_y))
        return

    global _building_wip
    if _building_wip is not None and _building_wip["key"] != frame_cache_key:
        # The world/zoom bucket this WIP was mid-drawing for is no longer
        # the one we need (invalidate_static_caches() fired under it, or -
        # rare - the grid cell moved on again before the WIP finished).
        # Restart clean rather than trying to patch up a stale snapshot.
        _building_wip = None

    is_first_ever_build = common._building_frame_cache_surface is None
    if _building_wip is None:
        _building_wip = _start_building_rebuild(
            buildings, spatial_grid, places, frame_cache_key, camx, camy, cache_zoom, screen_w, screen_h,
            road_ways=road_ways, road_spatial_grid=road_spatial_grid,
        )

    rebuild_started = time.perf_counter() if profiler is not None else None
    deadline = common._incremental_rebuild_deadline(
        "buildings", is_first_ever_build, INCREMENTAL_REBUILD_BUDGET_S,
    )
    finished = _advance_building_rebuild(_building_wip, deadline)
    common._finish_incremental_rebuild("buildings", finished)
    if profiler is not None:
        profiler.record("render:buildings_cache_rebuild", (time.perf_counter() - rebuild_started) * 1000.0)

    if finished:
        common._building_frame_cache_key = _building_wip["key"]
        common._building_frame_cache_surface = _building_wip["surface"]
        common._building_frame_cache_camera = _building_wip["camera"]
        _building_wip = None

    if common._building_frame_cache_surface is not None:
        _blit_stale_static_cache(
            screen, common._building_frame_cache_surface, common._building_frame_cache_camera, camx, camy, cache_zoom
        )


def _draw_buildings_uncached(
    screen,
    buildings: List[Building],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    places: Optional[List[Place]] = None,
    road_ways=None,
    road_spatial_grid=None,
) -> None:
    """Draw building footprints intersecting viewport, unconditionally and
    in one call, directly onto `screen` at the given screen_w/screen_h (no
    cache padding) - the pre-incremental-rebuild contract this function
    always had, kept for tests that exercise the per-building drawing
    logic directly without going through draw_buildings' caching/
    incremental wrapper. Shares that logic (_advance_building_rebuild)
    rather than duplicating it: a plain job with an infinite deadline runs
    to full completion in this one call, same as the old unbounded loop
    did."""
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 20.0)
    visible_buildings = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else buildings
    )
    job = {
        "surface": screen,
        "camera": (camx, camy),
        "px_per_m": px_per_m,
        "screen_w": screen_w,
        "screen_h": screen_h,
        "vminx": vminx, "vminy": vminy, "vmaxx": vmaxx, "vmaxy": vmaxy,
        "visible_buildings": list(visible_buildings),
        "places": places,
        "index": 0,
        "placed_sign_rects": [],
        "driveways_drawn": False,
        "road_ways": road_ways or (),
        "road_spatial_grid": road_spatial_grid,
    }
    _advance_building_rebuild(job, deadline=float("inf"))


def _start_building_rebuild(
    buildings: List[Building], spatial_grid, places: Optional[List[Place]], frame_cache_key,
    camx: float, camy: float, cache_zoom: float, screen_w: int, screen_h: int,
    road_ways=None, road_spatial_grid=None,
) -> dict:
    """Begin a new incremental buildings-cache rebuild job: select the
    visible buildings (cheap, O(visible buildings), no nested search - see
    roads.py's endpoint-join precompute for a case where that wasn't true)
    and snapshot the camera/zoom this job's every chunk (see
    _advance_building_rebuild, which may run across several frames) must
    draw into, consistently - never whatever live camx/camy draw_buildings()
    happens to be called with on a later frame."""
    import pygame

    px_per_m = cache_zoom
    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2

    # See draw_buildings' historical note (kept from the previous
    # single-shot version): this margin is pure extra beyond
    # CACHE_PADDING_PX, which already bounds how much of it a cache reuse
    # could ever take advantage of regardless of any individual building's
    # size - a small fixed margin only needs to cover the in-between-
    # rebuilds camera drift.
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, cache_width, cache_height, 20.0)

    visible_buildings = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else buildings
    )

    return {
        "key": frame_cache_key,
        "camera": (camx, camy),
        "px_per_m": px_per_m,
        "screen_w": cache_width,
        "screen_h": cache_height,
        "vminx": vminx, "vminy": vminy, "vmaxx": vmaxx, "vmaxy": vmaxy,
        "surface": pygame.Surface((cache_width, cache_height), pygame.SRCALPHA),
        "visible_buildings": list(visible_buildings),
        "places": places,
        "index": 0,
        "placed_sign_rects": [],
        "driveways_drawn": False,
        "road_ways": road_ways or (),
        "road_spatial_grid": road_spatial_grid,
    }


def _advance_building_rebuild(job: dict, deadline: float) -> bool:
    """Draw job's remaining visible buildings one at a time, checking
    `deadline` (a time.perf_counter() cutoff) before each - once at least
    one building has already been drawn this call, so a deadline computed
    as "now + a tiny/zero budget" can never cause a call to make zero
    progress (see roads.py's _advance_road_rebuild, which needed the exact
    same guarantee for the same reason). Returns True once every building
    is drawn - job["surface"] is then ready to commit as the new cache."""
    import pygame

    screen = job["surface"]
    camx, camy = job["camera"]
    px_per_m = job["px_per_m"]
    screen_w, screen_h = job["screen_w"], job["screen_h"]
    vminx, vminy, vmaxx, vmaxy = job["vminx"], job["vminy"], job["vmaxx"], job["vmaxy"]
    visible_buildings = job["visible_buildings"]
    placed_sign_rects = job["placed_sign_rects"]

    if not job.get("driveways_drawn", False):
        _draw_generated_driveways(
            screen,
            visible_buildings,
            job.get("road_ways", ()),
            job.get("road_spatial_grid"),
            camx,
            camy,
            px_per_m,
            screen_w,
            screen_h,
        )
        job["driveways_drawn"] = True

    made_progress_this_call = False
    while job["index"] < len(visible_buildings):
        if made_progress_this_call and time.perf_counter() >= deadline:
            return False
        b = visible_buildings[job["index"]]
        job["index"] += 1
        made_progress_this_call = True
        bb = getattr(b, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(b.points_m) < 3:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in b.points_m]
        if _is_open_roof(b):
            _draw_open_roof(screen, pts, px_per_m)
            continue
        if px_per_m <= 0.45:
            pygame.draw.polygon(screen, BUILDING_ROOF_COLORS[0], pts)
            continue
        height = _building_render_height(b)
        depth = min(MAX_BUILDING_DEPTH_PX, max(3, int(height * 0.35 * px_per_m)))
        roof = [(x - depth * 0.7, y - depth) for x, y in pts]

        center_x, center_y = getattr(b, "center_m", (0.0, 0.0))
        if center_x == 0.0 and center_y == 0.0 and b.points_m:
            center_x = sum(point[0] for point in b.points_m) / len(b.points_m)
            center_y = sum(point[1] for point in b.points_m) / len(b.points_m)
        named_colors = _building_colors_from_name(getattr(b, "name", None))
        if named_colors is not None:
            wall_color, roof_color = named_colors
        else:
            texture_seed = getattr(b, "texture_seed", None)
            if texture_seed is None:
                texture_seed = abs(math.sin(center_x * 0.013 + center_y * 0.017))
            texture_index = min(len(BUILDING_WALL_COLORS) - 1, int(texture_seed * len(BUILDING_WALL_COLORS)))
            wall_color = BUILDING_WALL_COLORS[texture_index]
            roof_color = BUILDING_ROOF_COLORS[texture_index]
        pygame.draw.polygon(screen, (45, 42, 39), [(x + 2, y + 3) for x, y in roof])
        for index, point in enumerate(pts):
            next_point = pts[(index + 1) % len(pts)]
            next_roof = roof[(index + 1) % len(roof)]
            pygame.draw.polygon(screen, wall_color, [point, next_point, next_roof, roof[index]])
        if _uses_gabled_roof(b):
            _draw_gabled_roof(screen, roof, roof_color)
        else:
            pygame.draw.polygon(screen, roof_color, roof)
        pygame.draw.lines(screen, (70, 66, 61), True, roof, 1)

        # Add small facade details after the roof so they remain visible at low zoom.
        visible_edges = _visible_building_edges(pts, roof)
        # `depth` bounds how many floor rows fit without visually merging;
        # kept here for the door sizing below (one_story_px), even though
        # the window loop itself now lives in _iter_building_window_slots.
        story_count = min(_building_window_story_count(b), max(1, int(depth / MIN_FLOOR_HEIGHT_PX)))
        for _edge_index, _floor_index, _window_index, storefront_row, window in _iter_building_window_slots(
            b, pts, roof, visible_edges, depth
        ):
            window_color = (58, 80, 94) if not storefront_row else (84, 106, 122)
            frame_color = (25, 42, 47) if not storefront_row else (29, 42, 48)
            pygame.draw.polygon(screen, window_color, window)
            pygame.draw.lines(screen, frame_color, True, window, 1)
            pygame.draw.line(screen, (155, 180, 178), window[0], window[2], 1)
            if storefront_row:
                pygame.draw.line(screen, (118, 120, 122), window[1], window[3], 1)
        for entrance_x, entrance_y in getattr(b, "entrances", ()):
            edge_distances = [
                dist_point_to_segment(
                    entrance_x,
                    entrance_y,
                    b.points_m[candidate][0],
                    b.points_m[candidate][1],
                    b.points_m[(candidate + 1) % len(pts)][0],
                    b.points_m[(candidate + 1) % len(pts)][1],
                )
                for candidate in range(len(pts))
            ]
            nearest_distance = min(edge_distances, default=float("inf"))
            edge_index = min(
                (candidate for candidate in range(len(pts)) if edge_distances[candidate] <= nearest_distance + 0.01),
                key=edge_distances.__getitem__,
                default=-1,
            )
            if edge_index < 0 or edge_index not in visible_edges:
                continue
            point = pts[edge_index]
            next_point = pts[(edge_index + 1) % len(pts)]
            roof_point = roof[edge_index]
            edge_x = next_point[0] - point[0]
            edge_y = next_point[1] - point[1]
            edge_length = math.hypot(edge_x, edge_y)
            if edge_length < 2:
                continue
            edge_x /= edge_length
            edge_y /= edge_length
            roof_x = roof_point[0] - point[0]
            roof_y = roof_point[1] - point[1]
            door_width = min(11.0, max(3.0, edge_length * 0.22))
            # A door is one story tall, never a fraction of the *whole*
            # building's facade - sizing/anchoring it off the full wall
            # depth (as DOOR_TOP_V_RATIO of abs(roof_y) used to) put it
            # floating well above the ground on anything taller than one
            # storey. Ground_x/y (the entrance's own point, v=0 on the
            # wall) is always the door's base; it only ever extends
            # upward by one storey's worth of the facade.
            one_story_px = abs(roof_y) / max(1, story_count)
            door_height = max(5.0, min(13.0, one_story_px * 0.68))
            ground_x, ground_y = world_to_screen(
                entrance_x, entrance_y, camx, camy, px_per_m, screen_w, screen_h
            )
            door_shift_x = roof_x * door_height / max(abs(roof_y), 1.0)
            door_shift_y = roof_y * door_height / max(abs(roof_y), 1.0)
            half_door = door_width / 2
            door = [
                (ground_x - edge_x * half_door, ground_y - edge_y * half_door),
                (ground_x + edge_x * half_door, ground_y + edge_y * half_door),
                (ground_x + edge_x * half_door + door_shift_x, ground_y + edge_y * half_door + door_shift_y),
                (ground_x - edge_x * half_door + door_shift_x, ground_y - edge_y * half_door + door_shift_y),
            ]
            pygame.draw.polygon(screen, (58, 48, 42), door)
            pygame.draw.lines(screen, (32, 28, 25), True, door, 1)

        if px_per_m > 0.45:
            global _building_sign_font_cache
            sign_font_size = max(16, min(MAX_BUILDING_SIGN_FONT_SIZE, round(18.0 * px_per_m / 0.7)))
            sign_font = _building_sign_font_cache.get(sign_font_size)
            if sign_font is None:
                sign_font = pygame.font.SysFont(None, sign_font_size, bold=True)
                _building_sign_font_cache[sign_font_size] = sign_font
            building_places = list(getattr(b, "associated_places", ()))
            building_name = getattr(b, "name", None)
            sign_entries = [
                (place.name, place.x, place.y, getattr(place, "kind", None))
                for place in building_places
            ]
            if building_name and not any(name == building_name for name, _, _, _ in sign_entries):
                sign_entries.append(
                    (building_name, b.center_m[0], b.center_m[1], getattr(b, "venue_type", None))
                )
            for place_name, place_x, place_y, venue_kind in sign_entries:
                anchor_x, anchor_y = place_x, place_y
                entrances = getattr(b, "entrances", ())
                if entrances:
                    anchor_x, anchor_y = min(
                        entrances,
                        key=lambda entrance: (entrance[0] - place_x) ** 2 + (entrance[1] - place_y) ** 2,
                    )
                edge_index = min(
                    visible_edges,
                    key=lambda candidate: dist_point_to_segment(
                        anchor_x,
                        anchor_y,
                        b.points_m[candidate][0],
                        b.points_m[candidate][1],
                        b.points_m[(candidate + 1) % len(b.points_m)][0],
                        b.points_m[(candidate + 1) % len(b.points_m)][1],
                    ),
                    default=-1,
                )
                if edge_index < 0 or edge_index not in visible_edges:
                    continue
                point = pts[edge_index]
                next_point = pts[(edge_index + 1) % len(pts)]
                roof_point = roof[edge_index]
                next_roof = roof[(edge_index + 1) % len(roof)]
                edge_x = next_point[0] - point[0]
                edge_y = next_point[1] - point[1]
                edge_length = math.hypot(edge_x, edge_y)
                if edge_length < 14.0:
                    continue
                edge_x /= edge_length
                edge_y /= edge_length
                wall_depth_x = roof_point[0] - point[0]
                wall_depth_y = roof_point[1] - point[1]
                wall_depth = math.hypot(wall_depth_x, wall_depth_y)
                if wall_depth < 4.0:
                    continue
                wall_normal_x = wall_depth_x / wall_depth
                wall_normal_y = wall_depth_y / wall_depth
                world_start = b.points_m[edge_index]
                world_end = b.points_m[(edge_index + 1) % len(b.points_m)]
                segment_dx = world_end[0] - world_start[0]
                segment_dy = world_end[1] - world_start[1]
                segment_length_sq = segment_dx * segment_dx + segment_dy * segment_dy
                wall_anchor_x, wall_anchor_y = _building_sign_anchor(
                    b, anchor_x, anchor_y, edge_index,
                )
                segment_ratio = 0.5
                if segment_length_sq > 1e-9:
                    segment_ratio = max(
                        0.0,
                        min(
                            1.0,
                            ((anchor_x - world_start[0]) * segment_dx
                             + (anchor_y - world_start[1]) * segment_dy)
                            / segment_length_sq,
                        ),
                    )
                sign_center_x, sign_center_y = world_to_screen(
                    wall_anchor_x, wall_anchor_y, camx, camy, px_per_m, screen_w, screen_h
                )
                sign_text = place_name.upper()
                text_width = sign_font.size(sign_text)[0]
                sign_width = min(
                    int(MAX_BUILDING_SIGN_WIDTH_M * px_per_m),
                    text_width + 8,
                    int(edge_length * 0.72),
                )
                sign_depth = min(int(MAX_BUILDING_SIGN_HEIGHT_M * px_per_m), int(wall_depth * 0.28))
                if sign_width < MIN_BUILDING_SIGN_WIDTH_PX or sign_depth < MIN_BUILDING_SIGN_DEPTH_PX:
                    continue
                angle = _building_sign_angle(point, next_point)
                foreshorten = _building_sign_foreshorten(edge_x, edge_y, wall_normal_x, wall_normal_y)
                sign_background, sign_border, sign_text_color = _building_sign_theme(venue_kind)
                text_surface = _building_sign_surface(
                    pygame, sign_font, sign_text, sign_width, sign_depth, angle, foreshorten, sign_text_color,
                )
                sign_corners_world = _building_sign_corners(
                    point,
                    next_point,
                    roof_point,
                    next_roof,
                    segment_ratio,
                    sign_width,
                    sign_depth,
                )
                if sign_corners_world is None:
                    continue
                sign_corners = [
                    tuple(round(value) for value in corner)
                    for corner in sign_corners_world
                ]
                sign_center_x = sum(corner[0] for corner in sign_corners) / 4.0
                sign_center_y = sum(corner[1] for corner in sign_corners) / 4.0
                sign_rect = pygame.Rect(
                    min(corner[0] for corner in sign_corners),
                    min(corner[1] for corner in sign_corners),
                    max(corner[0] for corner in sign_corners) - min(corner[0] for corner in sign_corners) + 1,
                    max(corner[1] for corner in sign_corners) - min(corner[1] for corner in sign_corners) + 1,
                ).inflate(4, 4)
                if any(sign_rect.colliderect(existing) for existing in placed_sign_rects):
                    continue
                placed_sign_rects.append(sign_rect)
                pygame.draw.polygon(screen, (*sign_background, 245), sign_corners)
                pygame.draw.lines(screen, (*sign_border, 255), True, sign_corners, 1)
                screen.blit(text_surface, text_surface.get_rect(center=(round(sign_center_x), round(sign_center_y))))

    return True


def draw_illuminated_windows(
    screen,
    buildings: List[Building],
    camx: float,
    camy: float,
    game_time_seconds: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    latitude: float = DEFAULT_SUN_LATITUDE,
    longitude: float = DEFAULT_SUN_LONGITUDE,
    profiler=None,
    budget_s: Optional[float] = None,
) -> None:
    """Draw a warm glow over the subset of visible buildings' windows that
    are "lit" at night (windows.md section 5/6).

    Deliberately a separate, lightweight per-frame pass drawn *after*
    draw_day_night_overlay - not baked into the static building cache -
    because darkness changes continuously through dusk/dawn and the cache's
    frame_cache_key must stay time-of-day independent (a full building-
    layer rebuild is too expensive to trigger every darkness tick; see
    draw_buildings). This mirrors exactly how draw_street_lights and
    draw_headlight_beams already layer on top of the darkened scene.
    Which windows are lit never changes frame to frame (_window_is_illuminated
    is a pure function of building/edge/floor/window identity), so this
    only ever spends time on the same small, viewport-culled set of window
    quads _advance_building_rebuild already knows how to compute - no new
    geometry design, no per-pixel work, no per-frame randomness.
    """
    import pygame

    sun_altitude, _sunrise, _sunset = solar_altitude_and_events(game_time_seconds, latitude, longitude)
    twilight = max(0.0, min(1.0, (sun_altitude + 12.0) / 18.0))
    darkness = 1.0 - twilight
    if darkness <= 0.25:
        return
    # Fade in from 0.25->0.5 like street_light_brightness does, then hold -
    # windows shouldn't suddenly pop to full brightness the instant dusk
    # crosses the threshold.
    intensity = min(1.0, (darkness - 0.25) / 0.25)
    alpha = int(WINDOW_ILLUMINATION_ALPHA * intensity)
    if alpha <= 0:
        return

    global _illuminated_window_cache, _illuminated_window_job
    started = time.perf_counter() if profiler is not None else None
    # What the glow surface depends on is the set of buildings the spatial
    # grid can actually return (or the whole list, with no grid) - NOT the
    # live list's length: buildings appended by the incremental tile merge
    # (bin-loader-v5.md) don't reach the grid until map sync's building-grid
    # stage catches up, so keying on len(buildings) rebuilt an identical
    # cache every frame of the merge (bin-loader-v6.md).
    count = spatial_grid.indexed_way_count if spatial_grid is not None else len(buildings)
    static_key = (id(buildings), id(spatial_grid), px_per_m, screen_w, screen_h)
    cache = _illuminated_window_cache
    camera_ok = (
        cache is not None
        and abs((camx - cache["camera"][0]) * px_per_m) <= ILLUMINATED_WINDOW_CACHE_PADDING_PX
        and abs((camy - cache["camera"][1]) * px_per_m) <= ILLUMINATED_WINDOW_CACHE_PADDING_PX
    )
    same_world = cache is not None and cache["key"] == static_key
    # Buildings are append-only between unloads; an unload filters the list
    # in place, which moves the last-indexed building to a lower index, so
    # "still at position count-1" proves nothing before it was removed.
    prefix_intact = (
        same_world
        and count <= len(buildings)
        and (cache["count"] == 0 or (
            cache["count"] <= len(buildings) and id(buildings[cache["count"] - 1]) == cache["last_id"]
        ))
    )
    if same_world and camera_ok and prefix_intact and count == cache["count"]:
        _illuminated_window_job = None
    elif same_world and camera_ok and prefix_intact and count > cache["count"]:
        job = _illuminated_window_job
        if job is None or job["cache"] is not cache:
            job = _illuminated_window_job = {"cache": cache, "cursor": cache["count"], "end": count}
        job["end"] = count
        _extend_illuminated_windows(
            cache, job, buildings, budget_s if budget_s is not None else ILLUMINATED_WINDOW_CACHE_BUDGET_S,
        )
        if job["cursor"] >= job["end"]:
            cache["count"] = job["end"]
            cache["last_id"] = id(buildings[job["end"] - 1]) if job["end"] else None
            _illuminated_window_job = None
    else:
        _illuminated_window_job = None
        cache_w = screen_w + ILLUMINATED_WINDOW_CACHE_PADDING_PX * 2
        cache_h = screen_h + ILLUMINATED_WINDOW_CACHE_PADDING_PX * 2
        vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(
            camx, camy, px_per_m, cache_w, cache_h, 20.0
        )
        visible_buildings = (
            spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
            if spatial_grid is not None
            else buildings
        )
        glow_layer = pygame.Surface((cache_w, cache_h), pygame.SRCALPHA)
        any_lit = False
        for b in visible_buildings:
            if _draw_illuminated_building(
                glow_layer, b, (vminx, vminy, vmaxx, vmaxy), camx, camy, px_per_m, cache_w, cache_h,
            ):
                any_lit = True
        cache = _illuminated_window_cache = {
            "key": static_key,
            "camera": (camx, camy),
            "surface": glow_layer,
            "any_lit": any_lit,
            "count": count,
            "last_id": id(buildings[count - 1]) if 0 < count <= len(buildings) else None,
        }

    if cache["any_lit"]:
        cache["surface"].set_alpha(alpha)
        offset_x = round((cache["camera"][0] - camx) * px_per_m) - ILLUMINATED_WINDOW_CACHE_PADDING_PX
        offset_y = round((camy - cache["camera"][1]) * px_per_m) - ILLUMINATED_WINDOW_CACHE_PADDING_PX
        screen.blit(cache["surface"], (offset_x, offset_y), special_flags=pygame.BLEND_RGB_ADD)
    if profiler is not None:
        profiler.record("render:illuminated_windows", (time.perf_counter() - started) * 1000.0)
        pending = 0 if _illuminated_window_job is None else _illuminated_window_job["end"] - _illuminated_window_job["cursor"]
        profiler.set_metric("window_cache_pending_buildings", pending)


def _draw_illuminated_building(glow_layer, b, viewport, camx, camy, px_per_m, cache_w, cache_h) -> bool:
    """Draw one building's lit-window quads onto the glow layer, returning
    whether any window was lit. The one per-building implementation shared
    by the full rebuild and the incremental extension, so both draw the
    identical polygons (opaque, same colour: drawing order is irrelevant)."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = viewport
    bb = getattr(b, "bbox", None)
    if bb and bb != (0.0, 0.0, 0.0, 0.0):
        if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
            return False
    if len(b.points_m) < 3 or _is_open_roof(b):
        return False
    pts = [
        world_to_screen(x, y, camx, camy, px_per_m, cache_w, cache_h)
        for x, y in b.points_m
    ]
    height = _building_render_height(b)
    depth = min(MAX_BUILDING_DEPTH_PX, max(3, int(height * 0.35 * px_per_m)))
    roof = [(x - depth * 0.7, y - depth) for x, y in pts]
    visible_edges = _visible_building_edges(pts, roof)
    building_id = id(b)
    any_lit = False
    for edge_index, floor_index, window_index, storefront_row, window in _iter_building_window_slots(
        b, pts, roof, visible_edges, depth
    ):
        probability = _window_illumination_probability(b, storefront_row)
        if not _window_is_illuminated(
            building_id, edge_index, floor_index, window_index, probability
        ):
            continue
        pygame.draw.polygon(glow_layer, (*WINDOW_LIT_COLOR, 255), window)
        any_lit = True
    return any_lit


def _extend_illuminated_windows(cache: dict, job: dict, buildings, budget_s: float) -> None:
    """Advance an incremental extension: draw only buildings[cursor:end] -
    the ones appended since the cache was built - onto the existing glow
    surface at its own snapshot camera, exactly where a full rebuild at
    that camera would have drawn them. The committed surface stays
    displayed meanwhile (partially extended, never blank)."""
    cache_w = cache["surface"].get_width()
    cache_h = cache["surface"].get_height()
    camx, camy = cache["camera"]
    px_per_m = cache["key"][2]
    viewport = get_viewport_bounds(camx, camy, px_per_m, cache_w, cache_h, 20.0)

    def draw(index: int) -> None:
        if _draw_illuminated_building(
            cache["surface"], buildings[index], viewport, camx, camy, px_per_m, cache_w, cache_h,
        ):
            cache["any_lit"] = True

    job["cursor"] = advance_chunked(range(job["end"]), job["cursor"], budget_s, draw)
