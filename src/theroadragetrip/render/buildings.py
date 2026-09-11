from . import common
from .common import (
    SCREEN_W,
    SCREEN_H,
    PX_PER_M,
    CACHE_PADDING_PX,
    _rebuild_or_stale,
    _static_cache_zoom,
    world_to_screen,
    get_viewport_bounds,
)
import math
import time
from typing import List, Optional


from ..geo import dist_point_to_segment, point_in_polygon
from ..osm import Building, Place


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
    height = max(3.0, float(getattr(building, "height_m", 8.0)))
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
    """Return whether the building should render a storefront ground floor."""
    venue_type = str(getattr(building, "venue_type", "") or "").lower()
    if venue_type in COMMERCIAL_AMENITIES or venue_type in COMMERCIAL_BUILDING_TYPES:
        return True
    for place in getattr(building, "associated_places", ()):
        place_type = str(getattr(place, "kind", "") or "").lower()
        if place_type in COMMERCIAL_AMENITIES or place_type in COMMERCIAL_BUILDING_TYPES:
            return True
    return False


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


def draw_buildings(
    screen,
    buildings: List[Building],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    places: Optional[List[Place]] = None,
    profiler=None,
) -> None:
    """Draw cached static building geometry and facade details."""
    import pygame
    cache_zoom = _static_cache_zoom(px_per_m)

    frame_cache_key = (
        id(buildings),
        len(buildings),
        id(buildings[-1]) if buildings else None,
        id(places),
        len(places) if places else 0,
        id(spatial_grid),
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
    if _rebuild_or_stale(screen, "buildings", common._building_frame_cache_surface, common._building_frame_cache_camera, camx, camy, cache_zoom):
        return

    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2
    cache_surface = pygame.Surface((cache_width, cache_height), pygame.SRCALPHA)
    rebuild_started = time.perf_counter() if profiler is not None else 0.0
    _draw_buildings_uncached(
        cache_surface,
        buildings,
        camx,
        camy,
        px_per_m=cache_zoom,
        screen_w=cache_width,
        screen_h=cache_height,
        spatial_grid=spatial_grid,
        places=places,
    )
    if profiler is not None:
        profiler.record("render:buildings_cache_rebuild", (time.perf_counter() - rebuild_started) * 1000.0)
    common._building_frame_cache_key = frame_cache_key
    common._building_frame_cache_surface = cache_surface
    common._building_frame_cache_camera = (camx, camy)
    screen.blit(cache_surface, (-CACHE_PADDING_PX, -CACHE_PADDING_PX))


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
) -> None:
    """Draw building footprints intersecting viewport."""
    import pygame

    # screen_w/screen_h here are already the padded cache surface's own
    # dimensions (CACHE_PADDING_PX baked in by the caller), so this margin
    # is pure extra beyond that - and the cache's offset-blit reuse can
    # never take advantage of more than CACHE_PADDING_PX/px_per_m of it
    # anyway (~11m at a typical driving zoom), regardless of how big any
    # individual building is: a rebuild always re-queries with the
    # *current* camera position, so it catches a huge building astride
    # the edge just as correctly with a small margin as a large one - the
    # margin only needs to cover the in-between-rebuilds camera drift, not
    # the building's own size. A wide margin here was selecting and fully
    # drawing buildings tens of meters past anything the cache could ever
    # actually show before its next rebuild, in a real city with tens of
    # thousands of buildings loaded - real cost (the same "culprit:
    # rendering" FPS-drop pattern already fixed for roads) for no visual
    # benefit.
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 20.0)

    visible_buildings = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else buildings
    )
    placed_sign_rects = []
    for b in visible_buildings:
        bb = getattr(b, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(b.points_m) < 3:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in b.points_m]
        if px_per_m <= 0.45:
            pygame.draw.polygon(screen, BUILDING_ROOF_COLORS[0], pts)
            continue
        height = max(3.0, float(getattr(b, "height_m", 8.0)))
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
        pygame.draw.polygon(screen, roof_color, roof)
        pygame.draw.lines(screen, (70, 66, 61), True, roof, 1)

        # Add small facade details after the roof so they remain visible at low zoom.
        visible_edges = _visible_building_edges(pts, roof)
        # `depth` (== abs(roof_y) for every point, since the roof offset is
        # the same fixed vector everywhere) bounds how many separate floor
        # rows can actually be drawn without them visually merging together.
        story_count = min(_building_window_story_count(b), max(1, int(depth / MIN_FLOOR_HEIGHT_PX)))
        is_commercial = _building_is_commercial(b)
        for index in visible_edges:
            point = pts[index]
            next_point = pts[(index + 1) % len(pts)]
            roof_point = roof[index]
            edge_x = next_point[0] - point[0]
            edge_y = next_point[1] - point[1]
            edge_length = math.hypot(edge_x, edge_y)
            if edge_length < 12.0:
                continue
            edge_x /= edge_length
            edge_y /= edge_length
            roof_x = roof_point[0] - point[0]
            roof_y = roof_point[1] - point[1]
            window_count = max(1, min(3, int(edge_length // 32.0)))
            for floor_index in range(story_count):
                floor_position = 0.18 + 0.64 * (floor_index + 0.5) / story_count
                floor_height = abs(roof_y) / story_count
                storefront_row = is_commercial and floor_index == 0
                # Keep separate rows visible on tall buildings; a fixed 3 px
                # minimum makes closely spaced floors merge into one band.
                window_height = max(1.0, min(7.0, floor_height * 0.55))
                if storefront_row:
                    window_height *= 1.45
                for window_index in range(window_count):
                    center = (window_index + 1) / (window_count + 1)
                    center_x = point[0] + (next_point[0] - point[0]) * center + roof_x * floor_position
                    center_y = point[1] + (next_point[1] - point[1]) * center + roof_y * floor_position
                    half_width = min(10.0, edge_length / (window_count + 2) * 0.45) / 2
                    if storefront_row:
                        half_width *= 1.35
                    pane_x = -roof_x * window_height / max(abs(roof_y), 1.0)
                    pane_y = -roof_y * window_height / max(abs(roof_y), 1.0)
                    window_color = (58, 80, 94) if not storefront_row else (84, 106, 122)
                    frame_color = (25, 42, 47) if not storefront_row else (29, 42, 48)
                    window = [
                        (center_x - edge_x * half_width, center_y - edge_y * half_width),
                        (center_x + edge_x * half_width, center_y + edge_y * half_width),
                        (center_x + edge_x * half_width + pane_x, center_y + edge_y * half_width + pane_y),
                        (center_x - edge_x * half_width + pane_x, center_y - edge_y * half_width + pane_y),
                    ]
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
