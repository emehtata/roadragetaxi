import math
import logging
import os
import random
import subprocess
from datetime import date
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import List, Optional, Tuple

from .geo import clip_polygon_to_rect, compute_bbox, dist_point_to_segment, meters_to_latlon, point_in_polygon
from .osm import Building, BusStop, Place, Scenery, TaxiStop, Water, Way
from .physics import Car, MAX_SPEED
from .taxi import TaxiManager, TaxiState
from .localization import tr

SCREEN_W, SCREEN_H = 1280, 720
FPS = 60
PX_PER_M = 0.7  # Default zoom level (pixels per meter)

SCENERY_COLORS = {
    "forest": (32, 95, 32),
    "wood": (32, 95, 32),
    "park": (42, 120, 42),
    "garden": (45, 125, 45),
    "meadow": (38, 110, 38),
    "grass": (36, 105, 36),
    "pitch": (48, 115, 55),
    "playground": (48, 115, 55),
    "sand": (160, 150, 110),
    "beach": (170, 160, 115),
    "parking": (92, 96, 94),
}
TREE_CROWN_COLORS = ((25, 78, 29), (34, 101, 35), (48, 119, 42), (63, 112, 34))
BUILDING_WALL_COLORS = ((158, 105, 82), (174, 166, 143), (116, 131, 119), (139, 139, 137))
BUILDING_ROOF_COLORS = ((92, 57, 48), (102, 96, 82), (66, 83, 69), (83, 86, 87))
MAX_VISIBLE_STREET_LIGHTS = 400
STREET_LIGHT_SPACING_M = 12.0
STREET_LIGHT_JUNCTION_CLEARANCE_M = 10.0
STREET_LIGHT_REFLECTOR_RADIUS_M = 10.0
STREET_LIGHT_SHADE_COLOR = (0, 0, 0)
SOLAR_UPDATE_INTERVAL_SECONDS = 15.0 * 60.0
GAME_DATE = date(2026, 8, 31)
FINLAND_SUMMER_TIME_OFFSET = 3.0
DEFAULT_SUN_LATITUDE = 65.012
DEFAULT_SUN_LONGITUDE = 25.468

_loading_image = None
_loading_image_path = os.path.join(os.path.dirname(__file__), "img", "theroadragetrip_1672_941.png")
_cyclist_sprite = None
_motorcycle_sprite = None
_moped_sprite = None
_two_wheeler_tinted_sprites = {}
_two_wheeler_render_cache = {}
_npc_debug_font = None
_cyclist_tinted_sprites = {}
_grass_texture_tile = None
_asphalt_texture_tile = None
_asphalt_texture_source = None
_asphalt_texture_tile_size = None
_street_light_junction_cache = None
_street_light_junction_grid_cache = None
_street_light_building_grid_cache = None
_taxi_sign_text = None
_bus_stop_geometry_cache = None
_bus_stop_font_cache = {}
_bus_stop_label_cache = {}
_traffic_light_surface_cache = {}
_street_light_glow_cache = {}
_street_light_frame_cache_key = None
_street_light_frame_cache_surface = None
_street_light_frame_cache_camera = None
_street_light_frame_world_positions = []
_day_night_overlay_cache = {}
_solar_position_cache = {}
_street_light_last_debug_log_ms = 0
_road_frame_cache_key = None
_road_frame_cache_surface = None
_render_logger = logging.getLogger(__name__)
_rage_face_frames = None
_rage_face_path = os.path.join(os.path.dirname(__file__), "assets", "ragefaceatlas.png")
_speedometer_font = None
_speedometer_label_font = None


def _load_rage_face_frames(pygame):
    global _rage_face_frames
    if _rage_face_frames is not None:
        return _rage_face_frames
    try:
        atlas = pygame.image.load(_rage_face_path).convert()
        atlas_width, atlas_height = atlas.get_size()
        frame_size = (170, 180)
        frames = []
        crop_rects = [(0, 80, 296, 486), (296, 80, 592, 486), (592, 80, 888, 486)]
        crop_rects.extend([(888, 80, 1188, 486), (1188, 80, 1484, 486)])
        crop_rects.extend(
            (column * (atlas_width // 6), 576, (column + 1) * (atlas_width // 6), 990)
            for column in range(6)
        )
        for left, top, right, bottom in crop_rects:
            crop = atlas.subsurface((left, top, right - left, bottom - top))
            scale = min(frame_size[0] / crop.get_width(), frame_size[1] / crop.get_height())
            scaled_size = (round(crop.get_width() * scale), round(crop.get_height() * scale))
            scaled_crop = pygame.transform.smoothscale(crop, scaled_size)
            frame = pygame.Surface(frame_size).convert()
            frame.fill(atlas.get_at((0, 0)))
            frame.blit(
                scaled_crop,
                ((frame_size[0] - scaled_size[0]) // 2, (frame_size[1] - scaled_size[1]) // 2),
            )
            frames.append(frame)
        _rage_face_frames = frames
    except (pygame.error, OSError) as exc:
        _render_logger.warning("Could not load rage face atlas: %s", exc)
        _rage_face_frames = []
    return _rage_face_frames


def default_hud_layout(screen_width: int, screen_height: int) -> dict[str, Tuple[int, int]]:
    return {
        "meters": (10, 10),
        "rage": (screen_width - 190, screen_height - 246),
        "speedometer": (10, screen_height - 180),
    }


def _draw_analog_speedometer(screen, speed_mps: float, position: Tuple[int, int]):
    import pygame

    global _speedometer_font
    global _speedometer_label_font
    if _speedometer_font is None:
        _speedometer_font = pygame.font.SysFont(None, 18)
    if _speedometer_label_font is None:
        _speedometer_label_font = pygame.font.SysFont(None, 14)
    font = _speedometer_font
    label_font = _speedometer_label_font
    width, height = 190, 170
    x, y = position
    center = (x + width // 2, y + 88)
    radius = 68
    pygame.draw.rect(screen, (20, 25, 30, 220), (x, y, width, height), border_radius=4)
    pygame.draw.rect(screen, (130, 140, 150), (x, y, width, height), width=1, border_radius=4)
    pygame.draw.circle(screen, (12, 16, 20), center, radius)
    pygame.draw.circle(screen, (130, 140, 150), center, radius, 2)

    speed_kmh = max(0.0, min(MAX_SPEED * 3.6, speed_mps * 3.6))
    for speed_mark in range(0, 211, 10):
        angle = math.radians(135.0 + speed_mark / 210.0 * 270.0)
        is_major = speed_mark % 20 == 0
        outer_radius = radius - 5
        inner_radius = radius - (18 if is_major else 11)
        outer = (center[0] + math.cos(angle) * outer_radius, center[1] + math.sin(angle) * outer_radius)
        inner = (center[0] + math.cos(angle) * inner_radius, center[1] + math.sin(angle) * inner_radius)
        pygame.draw.line(screen, (235, 220, 170), inner, outer, 3 if is_major else 2)
        if is_major:
            label_center = (
                center[0] + math.cos(angle) * (radius - 25),
                center[1] + math.sin(angle) * (radius - 25),
            )
            label = label_font.render(str(speed_mark), True, (220, 225, 215))
            screen.blit(label, label.get_rect(center=label_center))

    needle_angle = math.radians(135.0 + (speed_kmh / (MAX_SPEED * 3.6)) * 270.0)
    needle_end = (
        center[0] + math.cos(needle_angle) * (radius - 20),
        center[1] + math.sin(needle_angle) * (radius - 20),
    )
    pygame.draw.line(screen, (230, 65, 45), center, needle_end, 4)
    pygame.draw.circle(screen, (240, 220, 170), center, 6)
    speed_text = font.render(f"{speed_kmh:.0f}", True, (240, 240, 240))
    screen.blit(speed_text, speed_text.get_rect(center=(center[0], y + 132)))
    unit_text = font.render("km/h", True, (190, 200, 205))
    screen.blit(unit_text, unit_text.get_rect(center=(center[0], y + 153)))
    return pygame.Rect(x, y, width, height)


def solar_altitude_and_events(
    game_time_seconds: float,
    latitude: float = DEFAULT_SUN_LATITUDE,
    longitude: float = DEFAULT_SUN_LONGITUDE,
) -> Tuple[float, float, float]:
    """Return sun altitude and local sunrise/sunset minutes for the fixed game date."""
    cache_key = (
        int(game_time_seconds // SOLAR_UPDATE_INTERVAL_SECONDS),
        round(latitude, 6),
        round(longitude, 6),
    )
    cached_result = _solar_position_cache.get(cache_key)
    if cached_result is not None:
        return cached_result
    day_of_year = GAME_DATE.timetuple().tm_yday
    declination = math.radians(
        23.45 * math.sin(math.radians(360.0 * (284.0 + day_of_year) / 365.0))
    )
    latitude_radians = math.radians(latitude)
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1.0)
    equation_of_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2.0 * gamma)
        - 0.040849 * math.sin(2.0 * gamma)
    )
    solar_minutes = game_time_seconds / 60.0 + equation_of_time + 4.0 * longitude - 60.0 * FINLAND_SUMMER_TIME_OFFSET
    hour_angle = math.radians(solar_minutes / 4.0 - 180.0)
    altitude = math.degrees(
        math.asin(
            math.sin(latitude_radians) * math.sin(declination)
            + math.cos(latitude_radians) * math.cos(declination) * math.cos(hour_angle)
        )
    )
    sunrise_cosine = (
        math.cos(math.radians(90.833)) / (math.cos(latitude_radians) * math.cos(declination))
        - math.tan(latitude_radians) * math.tan(declination)
    )
    if sunrise_cosine <= -1.0:
        sunrise_minutes, sunset_minutes = 0.0, 1440.0
    elif sunrise_cosine >= 1.0:
        sunrise_minutes = sunset_minutes = float("nan")
    else:
        solar_noon = 720.0 - 4.0 * longitude - equation_of_time + 60.0 * FINLAND_SUMMER_TIME_OFFSET
        hour_angle_minutes = 4.0 * math.degrees(math.acos(sunrise_cosine))
        sunrise_minutes = solar_noon - hour_angle_minutes
        sunset_minutes = solar_noon + hour_angle_minutes
    result = altitude, sunrise_minutes, sunset_minutes
    _solar_position_cache[cache_key] = result
    return result


def _format_solar_time(minutes: float) -> str:
    if not math.isfinite(minutes):
        return "--:--"
    total_minutes = int(round(minutes)) % (24 * 60)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _tinted_two_wheeler_sprite(sprite, color, cache_key):
    import pygame

    cache_key = (cache_key, tuple(color))
    cached_sprite = _two_wheeler_tinted_sprites.get(cache_key)
    if cached_sprite is not None:
        return cached_sprite

    tinted_sprite = sprite.copy()
    for pixel_x in range(tinted_sprite.get_width()):
        for pixel_y in range(tinted_sprite.get_height()):
            red, green, blue, alpha = tinted_sprite.get_at((pixel_x, pixel_y))
            if alpha == 0 or max(red, green, blue) - min(red, green, blue) <= 25:
                continue
            brightness = (red + green + blue) / (3.0 * 255.0)
            tinted_sprite.set_at(
                (pixel_x, pixel_y),
                (*[min(255, int(channel * (0.65 + brightness * 0.55))) for channel in color], alpha),
            )

    _two_wheeler_tinted_sprites[cache_key] = tinted_sprite
    return tinted_sprite


def _tinted_cyclist_sprite(sprite, color):
    import pygame

    cache_key = tuple(color)
    cached_sprite = _cyclist_tinted_sprites.get(cache_key)
    if cached_sprite is not None:
        return cached_sprite

    tinted_sprite = sprite.copy()
    for pixel_x in range(tinted_sprite.get_width()):
        for pixel_y in range(tinted_sprite.get_height()):
            red, green, blue, alpha = tinted_sprite.get_at((pixel_x, pixel_y))
            is_blue_clothing = blue > red and blue > green
            is_yellow_clothing = red > 200 and 130 <= green <= 210 and blue < 100
            if alpha == 0 or not (is_blue_clothing or is_yellow_clothing):
                continue
            brightness = (red + green + blue) / (3.0 * 255.0)
            tinted_sprite.set_at(
                (pixel_x, pixel_y),
                (*[min(255, int(channel * (0.65 + brightness * 0.55))) for channel in color], alpha),
            )

    _cyclist_tinted_sprites[cache_key] = tinted_sprite
    return tinted_sprite


def _get_game_version() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    try:
        git_version = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_version = ""
    if git_version:
        return git_version
    try:
        return f"v{package_version('theroadragetrip')}"
    except PackageNotFoundError:
        return "v0.6.1beta"


GAME_VERSION = _get_game_version()


def _draw_version(screen, font, screen_w: int, screen_h: int) -> None:
    version_surface = font.render(GAME_VERSION, True, (130, 145, 160))
    screen.blit(version_surface, (screen_w - version_surface.get_width() - 12, screen_h - version_surface.get_height() - 12))


def world_to_screen(
    wx: float,
    wy: float,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> tuple[int, int]:
    """Convert world meters -> screen pixels with north-up orientation."""
    sx = (wx - camx) * px_per_m + screen_w / 2
    sy = screen_h / 2 - (wy - camy) * px_per_m
    return int(sx), int(sy)


def asphalt_texture_tile_size(px_per_m: float) -> int:
    """Return the screen-space tile size for a zoom level."""
    return max(24, min(256, round(64.0 * px_per_m / PX_PER_M)))


def road_color_for_way(way: Way) -> Tuple[int, int, int]:
    """Return a road color from OSM surface, with highway as fallback."""
    surface = str(getattr(way, "surface", "") or "").lower().split(";")[0].strip()
    surface_colors = {
        "asphalt": (70, 70, 70),
        "concrete": (142, 142, 138),
        "concrete:lanes": (142, 142, 138),
        "paving_stones": (125, 120, 112),
        "sett": (105, 100, 94),
        "cobblestone": (105, 100, 94),
        "compacted": (125, 112, 92),
        "fine_gravel": (145, 132, 108),
        "gravel": (150, 135, 105),
        "unpaved": (155, 140, 108),
        "dirt": (125, 98, 68),
        "ground": (130, 105, 75),
        "earth": (130, 105, 75),
        "sand": (190, 170, 120),
        "grass": (75, 125, 62),
        "wood": (112, 83, 55),
    }
    if surface in surface_colors:
        return surface_colors[surface]
    if not way.is_drivable:
        return (115, 145, 150) if way.highway == "cycleway" else (150, 150, 142)
    if getattr(way, "is_ice_road", False):
        return (160, 200, 225)
    if getattr(way, "is_busway", False) or way.highway == "busway":
        return (80, 72, 60)
    if way.highway == "living_street":
        return (85, 80, 78)
    return (70, 70, 70)


def road_render_priority(way: Way) -> int:
    """Return same-layer draw priority so major roads cover minor roads."""
    return {
        "motorway": 100,
        "motorway_link": 95,
        "trunk": 90,
        "trunk_link": 85,
        "primary": 80,
        "primary_link": 75,
        "secondary": 70,
        "secondary_link": 65,
        "tertiary": 60,
        "tertiary_link": 55,
        "unclassified": 50,
        "residential": 40,
        "living_street": 35,
        "service": 30,
        "track": 20,
    }.get(getattr(way, "highway", ""), 10)


def get_viewport_bounds(
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    margin_m: float = 60.0,
) -> tuple[float, float, float, float]:
    """Calculate world coordinates (minx, miny, maxx, maxy) visible in the viewport."""
    half_w = (screen_w / 2.0) / px_per_m + margin_m
    half_h = (screen_h / 2.0) / px_per_m + margin_m
    return camx - half_w, camy - half_h, camx + half_w, camy + half_h


def _covered_by_higher_road(x: float, y: float, layer: int, ways: Optional[List[Way]], spatial_grid=None) -> bool:
    if spatial_grid is not None:
        candidates = (way for way, _ in spatial_grid._candidate_ways(x, y))
    else:
        candidates = ways or []
    if not ways and spatial_grid is None:
        return False
    for way in candidates:
        if getattr(way, "layer", 0) <= layer or len(way.points_m) < 2:
            continue
        half_width = getattr(way, "half_width_m", 3.0)
        bbox = getattr(way, "bbox", None)
        if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
            bbox = compute_bbox(way.points_m)
        if bbox and not (bbox[0] - half_width <= x <= bbox[2] + half_width and bbox[1] - half_width <= y <= bbox[3] + half_width):
            continue
        if any(dist_point_to_segment(x, y, p1[0], p1[1], p2[0], p2[1]) <= half_width for p1, p2 in zip(way.points_m, way.points_m[1:])):
            return True
    return False


def _vehicle_is_on_bridge(vehicle, active_way=None) -> bool:
    way = active_way or getattr(vehicle, "way", None)
    return bool(getattr(way, "is_bridge", False))


def draw_scenery(
    screen,
    sceneries: List[Scenery],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    tree_effects=None,
    fallen_trees=None,
    spatial_grid=None,
) -> None:
    """Draw parks, forests, and green spaces intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 80.0)

    tree_budget = max(600, screen_w * screen_h // 400)
    visible_sceneries = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else sceneries
    )
    for sc in visible_sceneries:
        bb = getattr(sc, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(sc.points_m) < 3:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in sc.points_m]
        color = SCENERY_COLORS.get(sc.kind.lower(), (38, 105, 38))
        pygame.draw.polygon(screen, color, pts)
        trees = getattr(sc, "trees", [])
        visible_tree_count = sum(
            1 for tree_x, tree_y in trees
            if vminx <= tree_x <= vmaxx and vminy <= tree_y <= vmaxy
        )
        tree_step = max(1, math.ceil(visible_tree_count / tree_budget))
        for tree_index, (tree_x, tree_y) in enumerate(trees):
            if not (vminx <= tree_x <= vmaxx and vminy <= tree_y <= vmaxy):
                continue
            tree_key = (id(sc), tree_index)
            effect = (tree_effects or {}).get(tree_key, {})
            if tree_step > 1 and tree_index % tree_step and tree_key not in (fallen_trees or set()) and effect.get("shake", 0.0) <= 0.0:
                continue
            sx, sy = world_to_screen(tree_x, tree_y, camx, camy, px_per_m, screen_w, screen_h)
            shake = effect.get("shake", 0.0)
            if shake > 0.0:
                sx += math.sin(shake * 42.0) * max(1, int(2.0 * px_per_m))
            tree_variations = getattr(sc, "tree_variations", ())
            variation = (
                tree_variations[tree_index]
                if tree_index < len(tree_variations)
                else abs(math.sin(tree_x * 12.9898 + tree_y * 78.233))
            )
            size = 0.72 + variation * 0.62
            trunk = max(1, int(0.7 * size * px_per_m))
            trunk_height = max(2, int(1.5 * size * px_per_m))
            crown = max(2, int(2.2 * size * px_per_m))
            trunk_color = (78 + int(22 * variation), 52 + int(18 * variation), 27)
            crown_color = TREE_CROWN_COLORS[min(len(TREE_CROWN_COLORS) - 1, int(variation * len(TREE_CROWN_COLORS)))]
            if tree_key in (fallen_trees or set()):
                fall_heading = effect.get("angle", 0.0)
                fall_x = sx + math.cos(fall_heading) * 3.2 * px_per_m
                fall_y = sy - math.sin(fall_heading) * 3.2 * px_per_m
                pygame.draw.line(screen, trunk_color, (sx, sy), (fall_x, fall_y), max(2, trunk))
                pygame.draw.circle(screen, crown_color, (int(fall_x), int(fall_y)), crown)
            else:
                pygame.draw.rect(screen, trunk_color, (sx - trunk // 2, sy, trunk, trunk_height))
                pygame.draw.circle(screen, crown_color, (sx, sy - crown // 2), crown)
            leaves_left = effect.get("leaves", 0.0)
            if leaves_left > 0.0:
                for leaf_index in range(8):
                    drift_x = math.sin(leaf_index * 2.7 + (1.2 - leaves_left) * 8.0) * 12.0 * px_per_m
                    drift_y = -(1.2 - leaves_left) * 20.0 * px_per_m + math.cos(leaf_index * 1.9) * 5.0 * px_per_m
                    pygame.draw.circle(screen, (82, 145, 44), (int(sx + drift_x), int(sy - crown + drift_y)), max(1, int(px_per_m * 0.22)))


def draw_parking_spaces(screen, parking_spaces, camx: float, camy: float, px_per_m: float = PX_PER_M,
                        screen_w: int = SCREEN_W, screen_h: int = SCREEN_H) -> None:
    """Draw OSM parking spaces as small asphalt-colored polygons."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    for space in parking_spaces:
        min_x, min_y, max_x, max_y = space.bbox
        if max_x < vminx or min_x > vmaxx or max_y < vminy or min_y > vmaxy:
            continue
        points = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for x, y in space.points_m]
        pygame.draw.polygon(screen, (72, 75, 74), points)
        pygame.draw.lines(screen, (125, 128, 124), True, points, max(1, int(px_per_m * 0.12)))


def draw_grass_texture(screen, camx: float, camy: float, px_per_m: float = PX_PER_M) -> None:
    """Fill screen with a subtle repeating grass texture."""
    import pygame

    global _grass_texture_tile
    if _grass_texture_tile is None:
        tile_size = 96
        _grass_texture_tile = pygame.Surface((tile_size, tile_size))
        _grass_texture_tile.fill((25, 80, 25))
        rng = random.Random(17)
        for _ in range(150):
            x = rng.randrange(tile_size)
            y = rng.randrange(tile_size)
            color = rng.choice(((35, 96, 31), (42, 105, 35), (20, 70, 24), (58, 112, 39)))
            pygame.draw.line(_grass_texture_tile, color, (x, y), (x + rng.choice((-1, 0, 1)), y - rng.randrange(1, 4)), 1)

    tile_width, tile_height = _grass_texture_tile.get_size()
    screen_width, screen_height = screen.get_size()
    origin_x = screen_width // 2 - int(camx * px_per_m)
    origin_y = screen_height // 2 + int(camy * px_per_m)
    start_x = origin_x % tile_width - tile_width
    start_y = origin_y % tile_height - tile_height
    for x in range(start_x, screen_width, tile_width):
        for y in range(start_y, screen_height, tile_height):
            screen.blit(_grass_texture_tile, (x, y))


def draw_taxi_smoke(screen, car: Car, camx: float, camy: float, px_per_m: float = PX_PER_M, timer: float = 0.0) -> None:
    """Draw the same animated crash smoke used for NPC cars."""
    if timer <= 0.0:
        return
    import pygame

    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m, SCREEN_W, SCREEN_H)
    length_m = getattr(car, "length_m", 4.0)
    length_px = max(5.0, length_m * px_per_m)
    t = 5.0 - timer
    fx = math.cos(car.heading)
    fy = -math.sin(car.heading)
    rx = math.sin(car.heading)
    ry = math.cos(car.heading)
    front_cx = cx + fx * (length_px * 0.4)
    front_cy = cy + fy * (length_px * 0.4)
    for puff_idx in range(4):
        offset_t = (t * 2.5 + puff_idx * 0.7) % 2.0
        drift = math.sin(t * 3.0 + puff_idx) * (4.0 * offset_t)
        puff_x = front_cx + rx * drift
        puff_y = front_cy + ry * drift - offset_t * 14.0
        radius = int(3.0 + offset_t * 5.0)
        alpha = int(max(0, min(160, (1.0 - offset_t / 2.0) * 160)))
        smoke_surf = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(smoke_surf, (180, 180, 180, alpha), (radius + 1, radius + 1), radius)
        screen.blit(smoke_surf, (int(puff_x - radius - 1), int(puff_y - radius - 1)))


def draw_taxi_exhaust(screen, car: Car, camx: float, camy: float, px_per_m: float = PX_PER_M) -> None:
    """Draw four animated smoke puffs behind the taxi as exhaust."""
    import pygame

    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m, SCREEN_W, SCREEN_H)
    length_px = max(5.0, getattr(car, "length_m", 4.0) * px_per_m)
    t = pygame.time.get_ticks() / 1000.0
    fx = math.cos(car.heading)
    fy = -math.sin(car.heading)
    rx = math.sin(car.heading)
    ry = math.cos(car.heading)
    rear_cx = cx - fx * (length_px * 0.4)
    rear_cy = cy - fy * (length_px * 0.4)
    for puff_idx in range(4):
        offset_t = (t * 2.5 + puff_idx * 0.7) % 2.0
        trail_distance = offset_t * 14.0
        puff_x = rear_cx - fx * trail_distance
        puff_y = rear_cy - fy * trail_distance - offset_t * 3.0
        drift = math.sin(t * 3.0 + puff_idx) * (2.0 * offset_t)
        puff_x += rx * drift
        puff_y += ry * drift
        radius = int(3.0 + offset_t * 5.0)
        alpha = int(max(0, min(160, (1.0 - offset_t / 2.0) * 160)))
        smoke_surf = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(smoke_surf, (180, 180, 180, alpha), (radius + 1, radius + 1), radius)
        screen.blit(smoke_surf, (int(puff_x - radius - 1), int(puff_y - radius - 1)))


def draw_passenger_nausea_bubble(
    screen,
    font,
    car: Car,
    taxi_mgr: Optional[TaxiManager],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    language: str = "fi",
) -> None:
    """Draw a speech bubble above the taxi during nausea warning."""
    import pygame

    passenger = taxi_mgr.current_passenger if taxi_mgr is not None else None
    if (
        passenger is None
        or taxi_mgr.state != TaxiState.DRIVING_TO_DROPOFF
        or passenger.nausea_warning_timer <= 0.0
    ):
        return

    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m)
    text_surface = font.render(tr(language, "passenger_nausea_bubble"), True, (210, 35, 35))
    text_width, text_height = text_surface.get_size()
    bubble_width, bubble_height = text_width + 18, text_height + 10
    bubble_x = cx - bubble_width // 2
    bubble_y = cy - max(34, int(2.5 * px_per_m)) - bubble_height

    bubble_surface = pygame.Surface((bubble_width, bubble_height), pygame.SRCALPHA)
    pygame.draw.rect(
        bubble_surface,
        (255, 255, 255, 245),
        (0, 0, bubble_width, bubble_height),
        border_radius=7,
    )
    pygame.draw.rect(
        bubble_surface,
        (210, 35, 35, 255),
        (0, 0, bubble_width, bubble_height),
        width=2,
        border_radius=7,
    )
    bubble_surface.blit(text_surface, (9, 5))
    screen.blit(bubble_surface, (bubble_x, bubble_y))
    pygame.draw.polygon(
        screen,
        (255, 255, 255),
        [(cx - 7, bubble_y + bubble_height), (cx + 7, bubble_y + bubble_height), (cx, bubble_y + bubble_height + 8)],
    )
    pygame.draw.line(screen, (210, 35, 35), (cx - 7, bubble_y + bubble_height), (cx, bubble_y + bubble_height + 8), 2)
    pygame.draw.line(screen, (210, 35, 35), (cx, bubble_y + bubble_height + 8), (cx + 7, bubble_y + bubble_height), 2)


def draw_waters(
    screen,
    waters: List[Water],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw water polygons and waterways intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 80.0)

    visible_waters = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else waters
    )
    for w in visible_waters:
        bb = getattr(w, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue

        is_closed = len(w.points_m) >= 4 and w.points_m[0] == w.points_m[-1]
        if w.is_polygon and is_closed and len(w.points_m) >= 3:
            # Clip large water polygons to viewport to avoid software scanline lag
            if len(w.points_m) > 40:
                clipped = clip_polygon_to_rect(w.points_m, vminx, vminy, vmaxx, vmaxy)
                if len(clipped) < 3:
                    continue
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in clipped]
            else:
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]
            pygame.draw.polygon(screen, (30, 100, 200), pts)
            pygame.draw.lines(screen, (20, 80, 160), True, pts, 1)
        else:
            if len(w.points_m) >= 2:
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]
                pygame.draw.lines(screen, (30, 100, 200), False, pts, max(2, int(3 * px_per_m)))


def draw_buildings(
    screen,
    buildings: List[Building],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw building footprints intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 50.0)

    visible_buildings = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else buildings
    )
    for b in visible_buildings:
        bb = getattr(b, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(b.points_m) < 3:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in b.points_m]
        if px_per_m <= 1.5:
            pygame.draw.polygon(screen, BUILDING_ROOF_COLORS[0], pts)
            continue
        height = max(3.0, float(getattr(b, "height_m", 8.0)))
        depth = min(30, max(3, int(height * 0.35 * px_per_m)))
        roof = [(x - depth * 0.7, y - depth) for x, y in pts]

        center_x, center_y = getattr(b, "center_m", (0.0, 0.0))
        if center_x == 0.0 and center_y == 0.0 and b.points_m:
            center_x = sum(point[0] for point in b.points_m) / len(b.points_m)
            center_y = sum(point[1] for point in b.points_m) / len(b.points_m)
        texture_seed = getattr(b, "texture_seed", None)
        if texture_seed is None:
            texture_seed = abs(math.sin(center_x * 0.013 + center_y * 0.017))
        texture_index = min(len(BUILDING_WALL_COLORS) - 1, int(texture_seed * len(BUILDING_WALL_COLORS)))
        pygame.draw.polygon(screen, (45, 42, 39), [(x + 2, y + 3) for x, y in roof])
        for index, point in enumerate(pts):
            next_point = pts[(index + 1) % len(pts)]
            next_roof = roof[(index + 1) % len(roof)]
            pygame.draw.polygon(screen, BUILDING_WALL_COLORS[texture_index], [point, next_point, next_roof, roof[index]])
        roof_color = BUILDING_ROOF_COLORS[texture_index]
        pygame.draw.polygon(screen, roof_color, roof)
        pygame.draw.lines(screen, (70, 66, 61), True, roof, 1)

        # Add small facade details after the roof so they remain visible at low zoom.
        roof_dx = roof[0][0] - pts[0][0]
        roof_dy = roof[0][1] - pts[0][1]
        centroid_x = sum(point[0] for point in pts) / len(pts)
        centroid_y = sum(point[1] for point in pts) / len(pts)
        visible_edges = []
        for index, point in enumerate(pts):
            next_point = pts[(index + 1) % len(pts)]
            midpoint_x = (point[0] + next_point[0]) * 0.5
            midpoint_y = (point[1] + next_point[1]) * 0.5
            frontness = (midpoint_x - centroid_x) * -roof_dx + (midpoint_y - centroid_y) * -roof_dy
            if frontness > 0:
                visible_edges.append(index)
        window_edge = max(
            visible_edges,
            key=lambda index: math.hypot(
                b.points_m[(index + 1) % len(pts)][0] - b.points_m[index][0],
                b.points_m[(index + 1) % len(pts)][1] - b.points_m[index][1],
            ),
            default=-1,
        )
        for index, point in enumerate(pts):
            next_point = pts[(index + 1) % len(pts)]
            roof_point = roof[index]
            next_roof = roof[(index + 1) % len(roof)]
            midpoint_x = (point[0] + next_point[0]) * 0.5
            midpoint_y = (point[1] + next_point[1]) * 0.5
            frontness = (midpoint_x - centroid_x) * -roof_dx + (midpoint_y - centroid_y) * -roof_dy
            if frontness <= 0 or index != window_edge:
                continue
            edge_x = next_point[0] - point[0]
            edge_y = next_point[1] - point[1]
            edge_length = math.hypot(edge_x, edge_y)
            if edge_length < 8:
                continue
            edge_x /= edge_length
            edge_y /= edge_length
            roof_x = roof_point[0] - point[0]
            roof_y = roof_point[1] - point[1]
            window_count = min(3, max(1, int(edge_length // 32)))

            for window_index in range(window_count):
                center = (window_index + 1) / (window_count + 1)
                center_x = point[0] + (next_point[0] - point[0]) * center + roof_x * 0.42
                center_y = point[1] + (next_point[1] - point[1]) * center + roof_y * 0.42
                window_width = min(10.0, edge_length / (window_count + 2) * 0.45)
                half_width = window_width / 2
                window_height = max(3.0, min(7.0, abs(roof_y) * 0.22))
                pane_x = -roof_x * window_height / max(abs(roof_y), 1.0)
                pane_y = -roof_y * window_height / max(abs(roof_y), 1.0)
                window = [
                    (center_x - edge_x * half_width, center_y - edge_y * half_width),
                    (center_x + edge_x * half_width, center_y + edge_y * half_width),
                    (center_x + edge_x * half_width + pane_x, center_y + edge_y * half_width + pane_y),
                    (center_x - edge_x * half_width + pane_x, center_y - edge_y * half_width + pane_y),
                ]
                pygame.draw.polygon(screen, (52, 82, 91), window)
                pygame.draw.lines(screen, (25, 42, 47), True, window, 1)
                pygame.draw.line(screen, (155, 180, 178), window[0], window[2], 1)

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
            door_height = max(5.0, min(13.0, abs(roof_y) * 0.68))
            door_x, door_y = world_to_screen(
                entrance_x, entrance_y, camx, camy, px_per_m, screen_w, screen_h
            )
            door_x += roof_x * 0.48
            door_y += roof_y * 0.48
            door_shift_x = -roof_x * door_height / max(abs(roof_y), 1.0)
            door_shift_y = -roof_y * door_height / max(abs(roof_y), 1.0)
            half_door = door_width / 2
            door = [
                (door_x - edge_x * half_door, door_y - edge_y * half_door),
                (door_x + edge_x * half_door, door_y + edge_y * half_door),
                (door_x + edge_x * half_door + door_shift_x, door_y + edge_y * half_door + door_shift_y),
                (door_x - edge_x * half_door + door_shift_x, door_y - edge_y * half_door + door_shift_y),
            ]
            pygame.draw.polygon(screen, (58, 48, 42), door)
            pygame.draw.lines(screen, (32, 28, 25), True, door, 1)


def draw_ways(
    screen,
    ways: List[Way],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw road ways intersecting viewport with highway-type proportional thickness and layer ordering."""
    import pygame

    global _road_frame_cache_key, _road_frame_cache_surface
    road_cache_key = (
        id(ways),
        len(ways),
        id(ways[-1]) if ways else None,
        round(camx, 3),
        round(camy, 3),
        px_per_m,
        screen_w,
        screen_h,
    )
    if road_cache_key == _road_frame_cache_key and _road_frame_cache_surface is not None:
        screen.blit(_road_frame_cache_surface, (0, 0))
        return
    destination_screen = screen
    screen = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 60.0)


    # Filter visible ways first, then sort only visible ways by layer
    if spatial_grid is not None:
        visible_ways = [w for w in spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy) if len(w.points_m) >= 2]
    else:
        visible_ways = []
        for w in ways:
            bb = getattr(w, "bbox", None)
            if bb and bb != (0.0, 0.0, 0.0, 0.0):
                if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                    continue
            if len(w.points_m) >= 2:
                visible_ways.append(w)

    visible_ways.sort(
        key=lambda w: (
            getattr(w, "layer", 0),
            getattr(w, "is_drivable", True),
            road_render_priority(w),
        )
    )

    endpoints = []
    for way in visible_ways:
        if len(way.points_m) < 2:
            continue
        for endpoint_index in (0, -1):
            endpoints.append((
                way,
                endpoint_index,
                way.points_m[endpoint_index],
                getattr(way, "layer", 0),
                bool(way.is_drivable),
            ))

    endpoint_connections = {}
    endpoint_cell_size = 32.0
    endpoint_cells = {}
    for endpoint in endpoints:
        way, endpoint_index, point, layer, is_drivable = endpoint
        cell = (math.floor(point[0] / endpoint_cell_size), math.floor(point[1] / endpoint_cell_size), layer, is_drivable)
        endpoint_cells.setdefault(cell, []).append(endpoint)

    if px_per_m > 1.5:
        for way, endpoint_index, point, layer, is_drivable in endpoints:
            nearest = None
            nearest_distance = float("inf")
            join_distance = max(8.0, 2.0 * getattr(way, "half_width_m", 4.0) + 4.0)
            cell_x = math.floor(point[0] / endpoint_cell_size)
            cell_y = math.floor(point[1] / endpoint_cell_size)
            search_radius = max(1, math.ceil(join_distance / endpoint_cell_size))
            for nearby_cell_x in range(cell_x - search_radius, cell_x + search_radius + 1):
                for nearby_cell_y in range(cell_y - search_radius, cell_y + search_radius + 1):
                    for other_way, other_index, other_point, other_layer, other_is_drivable in endpoint_cells.get(
                        (nearby_cell_x, nearby_cell_y, layer, is_drivable), ()
                    ):
                        if way is other_way:
                            continue
                        distance = math.hypot(point[0] - other_point[0], point[1] - other_point[1])
                        if distance < nearest_distance:
                            nearest = (other_way, other_index, other_point)
                            nearest_distance = distance
            if nearest is not None and nearest_distance <= join_distance:
                endpoint_connections[(id(way), endpoint_index)] = nearest[2]

    asphalt_polygons = []
    center_lines = []

    def draw_joined_line(color, points, width, connections=()):
        if len(points) < 2:
            return
        if px_per_m <= 1.5:
            pygame.draw.lines(screen, color, False, points, max(1, round(width)))
            for start, end in connections:
                pygame.draw.line(screen, color, start, end, max(1, round(width)))
            return
        half_width = width * 0.5
        left_edge = []
        right_edge = []

        def offset_point(point, direction, side):
            return (
                point[0] - direction[1] * half_width * side,
                point[1] + direction[0] * half_width * side,
            )

        for index, point in enumerate(points):
            if index == 0:
                dx = points[1][0] - point[0]
                dy = points[1][1] - point[1]
                length = math.hypot(dx, dy)
                direction = (dx / length, dy / length) if length > 1e-9 else (1.0, 0.0)
                left_edge.append(offset_point(point, direction, 1.0))
                right_edge.append(offset_point(point, direction, -1.0))
                continue
            if index == len(points) - 1:
                dx = point[0] - points[index - 1][0]
                dy = point[1] - points[index - 1][1]
                length = math.hypot(dx, dy)
                direction = (dx / length, dy / length) if length > 1e-9 else (1.0, 0.0)
                left_edge.append(offset_point(point, direction, 1.0))
                right_edge.append(offset_point(point, direction, -1.0))
                continue

            previous_dx = point[0] - points[index - 1][0]
            previous_dy = point[1] - points[index - 1][1]
            next_dx = points[index + 1][0] - point[0]
            next_dy = points[index + 1][1] - point[1]
            previous_length = math.hypot(previous_dx, previous_dy)
            next_length = math.hypot(next_dx, next_dy)
            if previous_length <= 1e-9 or next_length <= 1e-9:
                direction = (
                    next_dx / next_length,
                    next_dy / next_length,
                ) if next_length > 1e-9 else (1.0, 0.0)
                left_edge.append(offset_point(point, direction, 1.0))
                right_edge.append(offset_point(point, direction, -1.0))
                continue

            previous_direction = (previous_dx / previous_length, previous_dy / previous_length)
            next_direction = (next_dx / next_length, next_dy / next_length)
            left_start = offset_point(point, previous_direction, 1.0)
            left_end = offset_point(point, next_direction, 1.0)
            right_start = offset_point(point, previous_direction, -1.0)
            right_end = offset_point(point, next_direction, -1.0)

            def intersect(first, first_direction, second, second_direction):
                cross = first_direction[0] * second_direction[1] - first_direction[1] * second_direction[0]
                if abs(cross) <= 1e-9:
                    return ((first[0] + second[0]) * 0.5, (first[1] + second[1]) * 0.5)
                delta_x = second[0] - first[0]
                delta_y = second[1] - first[1]
                distance = (delta_x * second_direction[1] - delta_y * second_direction[0]) / cross
                result = (first[0] + first_direction[0] * distance, first[1] + first_direction[1] * distance)
                if math.hypot(result[0] - point[0], result[1] - point[1]) > half_width * 4.0:
                    return ((first[0] + second[0]) * 0.5, (first[1] + second[1]) * 0.5)
                return result

            left_edge.append(intersect(left_start, previous_direction, left_end, next_direction))
            right_edge.append(intersect(right_start, previous_direction, right_end, next_direction))

        polygon = left_edge + list(reversed(right_edge))
        pygame.draw.polygon(screen, color, polygon)
        for start, end in connections:
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            if length <= 1e-9:
                continue
            normal_x = -dy / length * half_width
            normal_y = dx / length * half_width
            connection_polygon = [
                (start[0] + normal_x, start[1] + normal_y),
                (end[0] + normal_x, end[1] + normal_y),
                (end[0] - normal_x, end[1] - normal_y),
                (start[0] - normal_x, start[1] - normal_y),
            ]
            pygame.draw.polygon(screen, color, connection_polygon)

        if False and color == (70, 70, 70) and width >= 2:
            asphalt_polygons.append(polygon)
            asphalt_polygons.extend(
                [
                    (start[0] + normal_x, start[1] + normal_y),
                    (end[0] + normal_x, end[1] + normal_y),
                    (end[0] - normal_x, end[1] - normal_y),
                    (start[0] - normal_x, start[1] - normal_y),
                ]
                for start, end in connections
                for dx, dy in [(end[0] - start[0], end[1] - start[1])]
                for length in [math.hypot(dx, dy)]
                if length > 1e-9
                for normal_x, normal_y in [(-dy / length * half_width, dx / length * half_width)]
            )
            return

        if False:
            texture_tile_size = max(24, min(256, round(64.0 * px_per_m / 0.7)))
            if _asphalt_texture_source is None:
                texture_path = os.path.join(os.path.dirname(__file__), "assets", "asphalt128.png")
                try:
                    _asphalt_texture_source = pygame.image.load(texture_path).convert()
                except (pygame.error, OSError):
                    _asphalt_texture_source = False
            if _asphalt_texture_source:
                if _asphalt_texture_tile_size != texture_tile_size:
                    _asphalt_texture_tile = pygame.transform.smoothscale(
                        _asphalt_texture_source,
                        (texture_tile_size, texture_tile_size),
                    )
                    _asphalt_texture_tile_size = texture_tile_size
                all_polygons = [polygon]
                all_polygons.extend(
                    [
                        (start[0] + normal_x, start[1] + normal_y),
                        (end[0] + normal_x, end[1] + normal_y),
                        (end[0] - normal_x, end[1] - normal_y),
                        (start[0] - normal_x, start[1] - normal_y),
                    ]
                    for start, end in connections
                    for dx, dy in [(end[0] - start[0], end[1] - start[1])]
                    for length in [math.hypot(dx, dy)]
                    if length > 1e-9
                    for normal_x, normal_y in [(-dy / length * half_width, dx / length * half_width)]
                )
                min_x = max(0, int(math.floor(min(point[0] for shape in all_polygons for point in shape))))
                min_y = max(0, int(math.floor(min(point[1] for shape in all_polygons for point in shape))))
                max_x = min(screen.get_width(), int(math.ceil(max(point[0] for shape in all_polygons for point in shape))) + 1)
                max_y = min(screen.get_height(), int(math.ceil(max(point[1] for shape in all_polygons for point in shape))) + 1)
                if max_x > min_x and max_y > min_y:
                    size = (max_x - min_x, max_y - min_y)
                    texture_surface = pygame.Surface(size, pygame.SRCALPHA)
                    texture_origin_x = screen_w * 0.5 - camx * px_per_m
                    texture_origin_y = screen_h * 0.5 + camy * px_per_m
                    first_tile_x = -int((min_x - texture_origin_x) % texture_tile_size)
                    first_tile_y = -int((min_y - texture_origin_y) % texture_tile_size)
                    for tile_x in range(first_tile_x - texture_tile_size, size[0] + texture_tile_size, texture_tile_size):
                        for tile_y in range(first_tile_y - texture_tile_size, size[1] + texture_tile_size, texture_tile_size):
                            texture_surface.blit(_asphalt_texture_tile, (tile_x, tile_y))
                    mask = pygame.Surface(size, pygame.SRCALPHA)
                    for shape in all_polygons:
                        pygame.draw.polygon(
                            mask,
                            (255, 255, 255, 255),
                            [(point[0] - min_x, point[1] - min_y) for point in shape],
                        )
                    texture_surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                    screen.blit(texture_surface, (min_x, min_y))

    for w in visible_ways:
        if px_per_m <= 1.5 and not w.is_drivable:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]

        thickness = max(1, int(w.half_width_m * 2 * px_per_m))

        if not w.is_drivable:
            # Pedestrian paths, footways, cycleways, sidewalks.
            ped_thickness = max(1, int(getattr(w, "half_width_m", 1.2) * 2 * px_per_m))
            ped_color = road_color_for_way(w)
            connections = [
                (pts[0], world_to_screen(*endpoint_connections[(id(w), 0)], camx, camy, px_per_m, screen_w, screen_h))
                for endpoint in (0,)
                if (id(w), endpoint) in endpoint_connections
            ] + [
                (pts[-1], world_to_screen(*endpoint_connections[(id(w), -1)], camx, camy, px_per_m, screen_w, screen_h))
                for endpoint in (-1,)
                if (id(w), endpoint) in endpoint_connections
            ]
            draw_joined_line(ped_color, pts, ped_thickness, connections)
            continue

        connections = [
            (pts[0], world_to_screen(*endpoint_connections[(id(w), 0)], camx, camy, px_per_m, screen_w, screen_h))
            for endpoint in (0,)
            if (id(w), endpoint) in endpoint_connections
        ] + [
            (pts[-1], world_to_screen(*endpoint_connections[(id(w), -1)], camx, camy, px_per_m, screen_w, screen_h))
            for endpoint in (-1,)
            if (id(w), endpoint) in endpoint_connections
        ]
        road_color = road_color_for_way(w)
        if w.is_ice_road:
            center_color = (210, 235, 250)
        elif getattr(w, "is_busway", False) or w.highway == "busway":
            center_color = (220, 180, 60)
        elif w.highway == "living_street":
            center_color = (130, 125, 120)
        else:
            center_color = (110, 110, 110)

        draw_joined_line(road_color, pts, thickness, connections)
        if thickness >= 6:
            center_lines.append((center_color, pts, connections))

        # Draw one-way directional chevron indicators if zoomed in
        oneway_val = getattr(w, "oneway", 0)
        if oneway_val != 0 and px_per_m > 1.5:
            pts_world = w.points_m if oneway_val > 0 else list(reversed(w.points_m))
            arrow_color = (200, 200, 200)
            step_dist = 40.0  # meters between arrows
            cum_dist = 0.0
            segment_lengths = getattr(w, "segment_lengths", ())
            segment_headings = getattr(w, "segment_headings", ())
            for i in range(len(pts_world) - 1):
                ax, ay = pts_world[i]
                bx, by = pts_world[i + 1]
                seg_len = segment_lengths[i] if i < len(segment_lengths) else math.hypot(bx - ax, by - ay)
                if seg_len < 1.0:
                    continue
                seg_angle = segment_headings[i] if i < len(segment_headings) else math.atan2(by - ay, bx - ax)
                if oneway_val < 0:
                    seg_angle += math.pi
                while cum_dist < seg_len:
                    if cum_dist > 5.0:  # avoid right at vertices
                        px_w = ax + (cum_dist / seg_len) * (bx - ax)
                        py_w = ay + (cum_dist / seg_len) * (by - ay)
                        if vminx <= px_w <= vmaxx and vminy <= py_w <= vmaxy:
                            sc_x, sc_y = world_to_screen(px_w, py_w, camx, camy, px_per_m, screen_w, screen_h)
                            arr_len = max(3.0, 4.0 * px_per_m)
                            # Draw chevron >
                            left_x = sc_x - math.cos(seg_angle - 0.6) * arr_len
                            left_y = sc_y + math.sin(seg_angle - 0.6) * arr_len
                            right_x = sc_x - math.cos(seg_angle + 0.6) * arr_len
                            right_y = sc_y + math.sin(seg_angle + 0.6) * arr_len
                            pygame.draw.lines(
                                screen,
                                arrow_color,
                                False,
                                [(left_x, left_y), (sc_x, sc_y), (right_x, right_y)],
                                2,
                            )
                    cum_dist += step_dist
                cum_dist -= seg_len

    global _asphalt_texture_source, _asphalt_texture_tile, _asphalt_texture_tile_size
    if False and asphalt_polygons:
        texture_tile_size = asphalt_texture_tile_size(px_per_m)
        if _asphalt_texture_source is None:
            texture_path = os.path.join(os.path.dirname(__file__), "assets", "asphalt128.png")
            try:
                _asphalt_texture_source = pygame.image.load(texture_path).convert()
            except (pygame.error, OSError):
                _asphalt_texture_source = False
        if _asphalt_texture_source:
            if _asphalt_texture_tile_size != texture_tile_size:
                _asphalt_texture_tile = pygame.transform.smoothscale(
                    _asphalt_texture_source, (texture_tile_size, texture_tile_size)
                )
                _asphalt_texture_tile_size = texture_tile_size
            texture_origin_x = screen_w * 0.5 - camx * px_per_m
            texture_origin_y = screen_h * 0.5 + camy * px_per_m
            texture_surface = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
            first_tile_x = int(texture_origin_x % texture_tile_size) - texture_tile_size
            first_tile_y = int(texture_origin_y % texture_tile_size) - texture_tile_size
            for tile_x in range(first_tile_x, screen_w, texture_tile_size):
                for tile_y in range(first_tile_y, screen_h, texture_tile_size):
                    texture_surface.blit(_asphalt_texture_tile, (tile_x, tile_y))
            mask = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
            for shape in asphalt_polygons:
                pygame.draw.polygon(mask, (255, 255, 255, 255), shape)
            texture_surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            screen.blit(texture_surface, (0, 0))

    for center_color, points, connections in center_lines:
        draw_joined_line(center_color, points, 1, connections)

    destination_screen.blit(screen, (0, 0))
    _road_frame_cache_key = road_cache_key
    _road_frame_cache_surface = screen


def _way_has_street_lighting(way: Way) -> bool:
    """Use explicit OSM lighting, with residential streets as the fallback."""
    lit = getattr(way, "lit", None)
    return lit == "yes" or (lit is None and getattr(way, "highway", "") in {"residential", "living_street"})


def _point_is_near_building(
    point: Tuple[float, float],
    buildings: Optional[List[Building]],
    building_grid=None,
) -> bool:
    """Return whether a point is within 100 m of a building footprint."""
    if not buildings:
        return False
    point_x, point_y = point
    candidates = buildings
    if building_grid is not None:
        cell_size = 100.0
        cell_x = math.floor(point_x / cell_size)
        cell_y = math.floor(point_y / cell_size)
        candidates = building_grid.get((cell_x, cell_y), ())
    for building in candidates:
        bbox = getattr(building, "bbox", None)
        if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
            continue
        nearest_x = min(max(point_x, bbox[0]), bbox[2])
        nearest_y = min(max(point_y, bbox[1]), bbox[3])
        if (point_x - nearest_x) ** 2 + (point_y - nearest_y) ** 2 < 100.0 * 100.0:
            return True
    return False


def _way_should_have_street_lighting(
    way: Way,
    buildings: Optional[List[Building]],
    point: Optional[Tuple[float, float]] = None,
    building_grid=None,
) -> bool:
    return _way_has_street_lighting(way) or (
        getattr(way, "lit", None) is None
        and getattr(way, "highway", "") == "secondary"
        and point is not None
        and _point_is_near_building(point, buildings, building_grid)
    )


def draw_street_lights(
    screen,
    ways: List[Way],
    camx: float,
    camy: float,
    game_time_seconds: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    visible_road_count: Optional[int] = None,
    daylight_surface=None,
    latitude: float = DEFAULT_SUN_LATITUDE,
    longitude: float = DEFAULT_SUN_LONGITUDE,
    buildings: Optional[List[Building]] = None,
) -> None:
    """Draw simple roadside lamps on visible urban roads."""
    import pygame
    global _street_light_last_debug_log_ms

    hour = (game_time_seconds / 3600.0) % 24.0
    sun_altitude, sunrise_minutes, sunset_minutes = solar_altitude_and_events(
        game_time_seconds, latitude, longitude
    )
    twilight = max(0.0, min(1.0, (sun_altitude + 12.0) / 18.0))
    darkness = 1.0 - twilight
    street_light_brightness = int(45.0 + 190.0 * min(1.0, (darkness - 0.25) / 0.75))
    street_lighting_enabled = darkness > 0.25
    if not street_lighting_enabled:
        global _street_light_frame_world_positions
        _street_light_frame_world_positions = []
        if _render_logger.isEnabledFor(logging.DEBUG):
            now_ms = pygame.time.get_ticks()
            if now_ms - _street_light_last_debug_log_ms >= 1000:
                _render_logger.debug(
                    "Street lights: off time=%02d:%02d sun_altitude=%.2f sunrise=%s sunset=%s brightness=%d",
                    int(hour),
                    int((hour % 1.0) * 60.0),
                    sun_altitude,
                    _format_solar_time(sunrise_minutes),
                    _format_solar_time(sunset_minutes),
                    0,
                )
                _street_light_last_debug_log_ms = now_ms
        return
    cache_pixel_size = 16
    frame_cache_key = (
        id(ways),
        len(ways),
        id(ways[-1]) if ways else None,
        id(buildings),
        round(camx * px_per_m / cache_pixel_size),
        round(camy * px_per_m / cache_pixel_size),
        px_per_m,
        round(darkness * 32.0),
        screen.get_size(),
    )
    global _street_light_frame_cache_key, _street_light_frame_cache_surface, _street_light_frame_cache_camera
    if (
        daylight_surface is None
        and frame_cache_key == _street_light_frame_cache_key
        and _street_light_frame_cache_surface is not None
    ):
        cached_camx, cached_camy = _street_light_frame_cache_camera
        offset_x = round((cached_camx - camx) * px_per_m)
        offset_y = round((camy - cached_camy) * px_per_m)
        screen.blit(_street_light_frame_cache_surface, (offset_x, offset_y))
        if _render_logger.isEnabledFor(logging.DEBUG):
            now_ms = pygame.time.get_ticks()
            if now_ms - _street_light_last_debug_log_ms >= 1000:
                _render_logger.debug(
                    "Street lights: cache-hit time=%02d:%02d darkness=%.2f brightness=%d camera=(%.1f,%.1f)",
                    int(hour),
                    int((hour % 1.0) * 60.0),
                    darkness,
                    street_light_brightness,
                    camx,
                    camy,
                )
                _street_light_last_debug_log_ms = now_ms
        return
    # Build the lighting layer beyond the visible edge so lamps are ready before entering view.
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 40.0)
    if spatial_grid is not None:
        visible_ways = spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
    else:
        visible_ways = ways

    global _street_light_junction_cache, _street_light_junction_grid_cache, _street_light_building_grid_cache
    building_cache_key = (id(buildings), len(buildings) if buildings else 0, id(buildings[-1]) if buildings else None)
    if _street_light_building_grid_cache is None or _street_light_building_grid_cache[0] != building_cache_key:
        building_grid = {}
        for building in buildings or ():
            bbox = getattr(building, "bbox", None)
            if not bbox or bbox == (0.0, 0.0, 0.0, 0.0):
                continue
            min_cell_x = math.floor((bbox[0] - 100.0) / 100.0)
            max_cell_x = math.floor((bbox[2] + 100.0) / 100.0)
            min_cell_y = math.floor((bbox[1] - 100.0) / 100.0)
            max_cell_y = math.floor((bbox[3] + 100.0) / 100.0)
            for cell_x in range(min_cell_x, max_cell_x + 1):
                for cell_y in range(min_cell_y, max_cell_y + 1):
                    building_grid.setdefault((cell_x, cell_y), []).append(building)
        _street_light_building_grid_cache = (building_cache_key, building_grid)
    building_grid = _street_light_building_grid_cache[1]
    cache_key = (id(ways), len(ways), id(ways[-1]) if ways else None, id(buildings))
    if _street_light_junction_cache is None or _street_light_junction_cache[0] != cache_key:
        point_ways = {}
        ways_by_object_id = {id(way): way for way in ways}
        for way in ways:
            if getattr(way, "is_drivable", True):
                for point in way.points_m:
                    key = (round(point[0] / 5.0), round(point[1] / 5.0))
                    point_ways.setdefault(key, set()).add(id(way))
        junction_points = [
            (key[0] * 5.0, key[1] * 5.0)
            for key, junction_way_ids in point_ways.items()
            if len(junction_way_ids) >= 2
            and any(
                _way_should_have_street_lighting(
                    ways_by_object_id[way_id], buildings, (key[0] * 5.0, key[1] * 5.0), building_grid
                )
                for way_id in junction_way_ids
            )
        ]
        _street_light_junction_cache = (cache_key, junction_points)
        junction_grid = {}
        junction_cell_size = 40.0
        for junction_x, junction_y in junction_points:
            cell = (math.floor(junction_x / junction_cell_size), math.floor(junction_y / junction_cell_size))
            junction_grid.setdefault(cell, []).append((junction_x, junction_y))
        _street_light_junction_grid_cache = (cache_key, junction_grid)
    else:
        junction_points = _street_light_junction_cache[1]
    junction_grid = _street_light_junction_grid_cache[1]
    light_layer = pygame.Surface(screen.get_size(), pygame.SRCALPHA) if street_lighting_enabled else None
    _street_light_frame_world_positions = []
    lamp_centers = []
    lamp_directions = []
    lamp_spacing = STREET_LIGHT_SPACING_M
    visible_way_count = 0
    junction_cell_size = 40.0
    junction_min_x = math.floor(vminx / junction_cell_size)
    junction_max_x = math.floor(vmaxx / junction_cell_size)
    junction_min_y = math.floor(vminy / junction_cell_size)
    junction_max_y = math.floor(vmaxy / junction_cell_size)
    for junction_cell_x in range(junction_min_x, junction_max_x + 1):
        for junction_cell_y in range(junction_min_y, junction_max_y + 1):
            for junction_x, junction_y in junction_grid.get((junction_cell_x, junction_cell_y), ()):
                if len(lamp_centers) >= MAX_VISIBLE_STREET_LIGHTS:
                    break
                if not (vminx <= junction_x <= vmaxx and vminy <= junction_y <= vmaxy):
                    continue
                screen_x, screen_y = world_to_screen(
                    junction_x, junction_y, camx, camy, px_per_m, screen_w, screen_h
                )
                lamp_centers.append((int(screen_x), int(screen_y)))
                lamp_directions.append(0.0)
                _street_light_frame_world_positions.append((junction_x, junction_y))
    for way in visible_ways:
        visible_way_count += 1
        if len(lamp_centers) >= MAX_VISIBLE_STREET_LIGHTS:
            break
        if (
            not getattr(way, "is_drivable", True)
            or (
                not _way_has_street_lighting(way)
                and getattr(way, "highway", "") != "secondary"
            )
            or len(way.points_m) < 2
        ):
            continue
        distance_to_lamp = 0.0
        segment_lengths = getattr(way, "segment_lengths", ())
        for segment_index, (start, end) in enumerate(zip(way.points_m, way.points_m[1:])):
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            segment_length = (
                segment_lengths[segment_index]
                if segment_index < len(segment_lengths)
                else math.hypot(dx, dy)
            )
            if segment_length < 1.0:
                continue
            while distance_to_lamp <= segment_length:
                if len(lamp_centers) >= MAX_VISIBLE_STREET_LIGHTS:
                    break
                fraction = distance_to_lamp / segment_length
                lamp_x = start[0] + dx * fraction
                lamp_y = start[1] + dy * fraction
                normal_x = -dy / segment_length
                normal_y = dx / segment_length
                edge_distance = getattr(way, "half_width_m", 4.0) + 1.0
                if not _way_should_have_street_lighting(way, buildings, (lamp_x, lamp_y), building_grid):
                    distance_to_lamp += lamp_spacing
                    continue
                for side in (-1.0, 1.0):
                    if len(lamp_centers) >= MAX_VISIBLE_STREET_LIGHTS:
                        break
                    world_x = lamp_x + normal_x * edge_distance * side
                    world_y = lamp_y + normal_y * edge_distance * side
                    junction_cell_size = 40.0
                    junction_cell_x = math.floor(world_x / junction_cell_size)
                    junction_cell_y = math.floor(world_y / junction_cell_size)
                    if any(
                        (world_x - junction_x) ** 2 + (world_y - junction_y) ** 2
                        < STREET_LIGHT_JUNCTION_CLEARANCE_M * STREET_LIGHT_JUNCTION_CLEARANCE_M
                        for cell_x in (junction_cell_x - 1, junction_cell_x, junction_cell_x + 1)
                        for cell_y in (junction_cell_y - 1, junction_cell_y, junction_cell_y + 1)
                        for junction_x, junction_y in junction_grid.get((cell_x, cell_y), ())
                    ):
                        continue
                    if not (vminx <= world_x <= vmaxx and vminy <= world_y <= vmaxy):
                        continue
                    screen_x, screen_y = world_to_screen(
                        world_x, world_y, camx, camy, px_per_m, screen_w, screen_h
                    )
                    lamp_center = (int(screen_x), int(screen_y))
                    lamp_radius = max(1, int(px_per_m * 0.28))
                    lamp_color = STREET_LIGHT_SHADE_COLOR
                    road_direction = math.atan2(-normal_y * side, -normal_x * side)
                    pygame.draw.circle(screen, lamp_color, lamp_center, lamp_radius)
                    lamp_centers.append(lamp_center)
                    lamp_directions.append(road_direction)
                    _street_light_frame_world_positions.append((world_x, world_y))
                distance_to_lamp += lamp_spacing
            distance_to_lamp -= segment_length

    if light_layer is not None:
        lamp_radius = max(1, int(px_per_m * 0.28))
        for lamp_center in lamp_centers:
            pygame.draw.circle(light_layer, STREET_LIGHT_SHADE_COLOR, lamp_center, lamp_radius)
        _street_light_frame_cache_key = frame_cache_key
        _street_light_frame_cache_surface = light_layer
        _street_light_frame_cache_camera = (camx, camy)
        screen.blit(light_layer, (0, 0))
        if _render_logger.isEnabledFor(logging.DEBUG):
            now_ms = pygame.time.get_ticks()
            if now_ms - _street_light_last_debug_log_ms >= 1000:
                _render_logger.debug(
                    "Street lights: rendered time=%02d:%02d sun_altitude=%.2f sunrise=%s sunset=%s roads=%d lamps=%d glows=%d darkness=%.2f brightness=%d",
                    int(hour),
                    int((hour % 1.0) * 60.0),
                    sun_altitude,
                    _format_solar_time(sunrise_minutes),
                    _format_solar_time(sunset_minutes),
                    visible_way_count,
                    len(lamp_centers),
                    0,
                    darkness,
                    street_light_brightness,
                )
                _street_light_last_debug_log_ms = now_ms
        if daylight_surface is not None and lamp_centers:
            daylight_mask = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            restoration_radius = max(2, int(10.0 * px_per_m))
            for lamp_center, road_direction in zip(lamp_centers, lamp_directions):
                sector_points = [lamp_center]
                half_sector_angle = math.radians(135.0)
                for angle_step in range(49):
                    angle = (
                        road_direction - half_sector_angle
                        + angle_step * (2.0 * half_sector_angle / 48.0)
                    )
                    sector_points.append(
                        (
                            int(lamp_center[0] + math.cos(angle) * restoration_radius),
                            int(lamp_center[1] - math.sin(angle) * restoration_radius),
                        )
                    )
                pygame.draw.polygon(daylight_mask, (255, 255, 255, 255), sector_points)
            restored_daylight = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            restored_daylight.blit(daylight_surface, (0, 0))
            restored_daylight.blit(daylight_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            screen.blit(restored_daylight, (0, 0))
            for lamp_center in lamp_centers:
                pygame.draw.circle(screen, STREET_LIGHT_SHADE_COLOR, lamp_center, lamp_radius)


def draw_headlight_beams(
    screen,
    vehicles,
    camx: float,
    camy: float,
    game_time_seconds: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    daylight_surface=None,
    latitude: float = DEFAULT_SUN_LATITUDE,
    longitude: float = DEFAULT_SUN_LONGITUDE,
    npc_vehicles=None,
    street_light_positions=None,
    bicycles=None,
    ways: Optional[List[Way]] = None,
    spatial_grid=None,
    current_way=None,
) -> None:
    """Draw lightweight forward-facing headlight beams for visible vehicles at night."""
    import pygame

    sun_altitude, _, _ = solar_altitude_and_events(game_time_seconds, latitude, longitude)
    twilight = max(0.0, min(1.0, (sun_altitude + 12.0) / 18.0))
    darkness = 1.0 - twilight
    if darkness <= 0.25:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    beam_mask = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    beam_length = 15.0 * px_per_m
    beam_near = 1.0 * px_per_m
    beam_width = 4.5 * px_per_m
    crossing_offset = 3.0 * px_per_m
    long_beam_length = beam_length * 3.0
    oncoming_detection_distance = 45.0
    street_light_radius = 22.0
    active_street_light_positions = (
        _street_light_frame_world_positions
        if street_light_positions is None
        else street_light_positions
    )
    npc_ids = {id(vehicle) for vehicle in npc_vehicles or ()}
    bicycle_ids = {id(bicycle) for bicycle in bicycles or ()}

    def draw_beam(origin, near_edge, far_edge, tip, cap_center, cap_radius):
        pygame.draw.polygon(
            beam_mask,
            (255, 255, 255, 255),
            [
                (int(origin[0]), int(origin[1])),
                (int(near_edge[0]), int(near_edge[1])),
                (int(far_edge[0]), int(far_edge[1])),
                (int(tip[0]), int(tip[1])),
            ],
        )
        pygame.draw.circle(
            beam_mask,
            (255, 255, 255, 255),
            (int(cap_center[0]), int(cap_center[1])),
            max(1, int(cap_radius)),
        )

    def has_oncoming_vehicle(vehicle, x: float, y: float, heading: float) -> bool:
        forward_x = math.cos(heading)
        forward_y = math.sin(heading)
        for other in vehicles:
            if other is vehicle:
                continue
            other_x = getattr(other, "x", None)
            other_y = getattr(other, "y", None)
            other_heading = getattr(other, "heading", None)
            if other_x is None or other_y is None or other_heading is None:
                continue
            delta_x = other_x - x
            delta_y = other_y - y
            distance = math.hypot(delta_x, delta_y)
            if distance <= 0.1 or distance > oncoming_detection_distance:
                continue
            ahead = (delta_x * forward_x + delta_y * forward_y) / distance
            other_forward_x = math.cos(other_heading)
            other_forward_y = math.sin(other_heading)
            opposing = forward_x * other_forward_x + forward_y * other_forward_y
            if ahead > 0.2 and opposing < -0.5:
                return True
        return False

    def is_near_street_light(x: float, y: float) -> bool:
        return any(
            (x - light_x) ** 2 + (y - light_y) ** 2 <= (street_light_radius ** 2)
            for light_x, light_y in active_street_light_positions
        )

    drawn = 0
    for vehicle in [*vehicles, *(bicycles or ())]:
        if drawn >= 80:
            break
        x = getattr(vehicle, "x", None)
        y = getattr(vehicle, "y", None)
        heading = getattr(vehicle, "heading", None)
        if x is None or y is None or heading is None or not (vminx <= x <= vmaxx and vminy <= y <= vmaxy):
            continue
        vehicle_layer = getattr(vehicle, "layer", getattr(getattr(vehicle, "way", None), "layer", 0))
        active_way = current_way if vehicle is vehicles[0] else None
        if not _vehicle_is_on_bridge(vehicle, active_way) and _covered_by_higher_road(
            x, y, vehicle_layer, ways, spatial_grid
        ):
            continue
        cx, cy = world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h)
        forward_x = math.cos(heading)
        forward_y = -math.sin(heading)
        right_x = math.sin(heading)
        right_y = math.cos(heading)
        is_bicycle = id(vehicle) in bicycle_ids
        beam_length_for_vehicle = 6.0 * px_per_m if is_bicycle else beam_length
        if (
            not is_bicycle
            and id(vehicle) in npc_ids
            and not is_near_street_light(x, y)
            and not has_oncoming_vehicle(vehicle, x, y, heading)
        ):
            beam_length_for_vehicle = long_beam_length
        vehicle_width = max(3.0, getattr(vehicle, "width_m", 1.8) * px_per_m)
        if is_bicycle:
            vehicle_width = max(2.0, getattr(vehicle, "radius_m", 0.6) * px_per_m)
        headlight_offset = vehicle_width * 0.35
        bicycle_front_offset = 0.7 * px_per_m if is_bicycle else beam_near
        front_x = cx + forward_x * (bicycle_front_offset + max(0.0, vehicle_width * 0.55))
        front_y = cy + forward_y * (bicycle_front_offset + max(0.0, vehicle_width * 0.55))
        if is_bicycle:
            origin_x = front_x
            origin_y = front_y
            tip_x = cx + forward_x * beam_length_for_vehicle
            tip_y = cy + forward_y * beam_length_for_vehicle
            near_spread = min(0.20 * px_per_m, vehicle_width * 0.20)
            far_width = 0.80 * px_per_m
            near_left_x = origin_x - right_x * near_spread
            near_left_y = origin_y - right_y * near_spread
            near_right_x = origin_x + right_x * near_spread
            near_right_y = origin_y + right_y * near_spread
            far_left_x = tip_x - right_x * far_width
            far_left_y = tip_y - right_y * far_width
            far_right_x = tip_x + right_x * far_width
            far_right_y = tip_y + right_y * far_width
            draw_beam(
                (near_left_x, near_left_y),
                (near_right_x, near_right_y),
                (far_right_x, far_right_y),
                (far_left_x, far_left_y),
                (tip_x, tip_y),
                far_width,
            )
            drawn += 1
            continue
        for side in (-1.0, 1.0):
            side_x = right_x * side
            side_y = right_y * side
            origin_x = front_x + side_x * headlight_offset
            origin_y = front_y + side_y * headlight_offset
            tip_shift = crossing_offset if side < 0.0 else crossing_offset * 0.75
            tip_x = cx + forward_x * beam_length_for_vehicle + right_x * tip_shift
            tip_y = cy + forward_y * beam_length_for_vehicle + right_y * tip_shift
            near_spread = min(beam_width * 0.08, vehicle_width * 0.10)
            far_width = beam_width * 1.7
            near_x = origin_x + side_x * near_spread
            near_y = origin_y + side_y * near_spread
            far_x = tip_x + side_x * far_width
            far_y = tip_y + side_y * far_width
            cap_x = tip_x + side_x * far_width * 0.5
            cap_y = tip_y + side_y * far_width * 0.5
            draw_beam(
                (origin_x, origin_y),
                (near_x, near_y),
                (far_x, far_y),
                (tip_x, tip_y),
                (cap_x, cap_y),
                far_width * 0.5,
            )
        drawn += 1
    if drawn:
        if daylight_surface is not None:
            restored_daylight = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            restored_daylight.blit(daylight_surface, (0, 0))
            restored_daylight.blit(beam_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            screen.blit(restored_daylight, (0, 0))
    lamp_radius = max(1, int(px_per_m * 0.28))
    for light_x, light_y in active_street_light_positions:
        if not (vminx <= light_x <= vmaxx and vminy <= light_y <= vmaxy):
            continue
        lamp_center = world_to_screen(light_x, light_y, camx, camy, px_per_m, screen_w, screen_h)
        pygame.draw.circle(screen, STREET_LIGHT_SHADE_COLOR, (int(lamp_center[0]), int(lamp_center[1])), lamp_radius)


def draw_tire_tracks(
    screen,
    tracks,
    camx: float,
    camy: float,
    grass: bool,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw persistent tire marks either on grass or on paved roads."""
    import pygame

    color = (105, 68, 38) if grass else (28, 28, 28)
    width = max(3, int((0.75 if grass else 0.24) * px_per_m))
    previous_tires = None
    previous_sequence = None
    for track_x, track_y, heading, is_grass, sequence in tracks:
        if is_grass != grass:
            previous_tires = None
            previous_sequence = None
            continue
        center_x, center_y = world_to_screen(track_x, track_y, camx, camy, px_per_m, screen_w, screen_h)
        side_x = -math.sin(heading)
        side_y = math.cos(heading)
        current_tires = []
        for side in (-1.0, 1.0):
            tire_x = center_x + side_x * side * 0.72 * px_per_m
            tire_y = center_y + side_y * side * 0.72 * px_per_m
            current_tires.append((int(tire_x), int(tire_y)))
        if previous_tires is not None and sequence == previous_sequence:
            for previous_tire, current_tire in zip(previous_tires, current_tires):
                pygame.draw.line(screen, color, previous_tire, current_tire, width)
        previous_tires = current_tires
        previous_sequence = sequence


def draw_vomit_puddles(screen, puddles, camx: float, camy: float, px_per_m: float = PX_PER_M) -> None:
    """Draw persistent passenger sickness spots beside the taxi route."""
    import pygame

    for puddle_x, puddle_y in puddles:
        x, y = world_to_screen(puddle_x, puddle_y, camx, camy, px_per_m, SCREEN_W, SCREEN_H)
        radius_x = max(3, int(1.2 * px_per_m))
        radius_y = max(2, int(0.7 * px_per_m))
        pygame.draw.ellipse(
            screen,
            (105, 115, 62),
            (x - radius_x, y - radius_y, radius_x * 2, radius_y * 2),
        )


def draw_roadworks(
    screen,
    roadworks,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw temporary barriers and warning cones over roadwork sections."""
    import pygame

    for work in roadworks:
        start = world_to_screen(work.start[0], work.start[1], camx, camy, px_per_m, screen_w, screen_h)
        end = world_to_screen(work.end[0], work.end[1], camx, camy, px_per_m, screen_w, screen_h)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy) or 1.0
        normal_x = -dy / length
        normal_y = dx / length
        barrier_width = max(2, int(getattr(work.way, "half_width_m", 4.0) * px_per_m))
        for point in (start, end):
            if work.lane_closed:
                barrier_start = point
                barrier_end = (
                    int(point[0] + normal_x * barrier_width),
                    int(point[1] + normal_y * barrier_width),
                )
            else:
                barrier_start = (
                    int(point[0] - normal_x * barrier_width),
                    int(point[1] - normal_y * barrier_width),
                )
                barrier_end = (
                    int(point[0] + normal_x * barrier_width),
                    int(point[1] + normal_y * barrier_width),
                )
            pygame.draw.line(
                screen,
                (235, 190, 35),
                barrier_start,
                barrier_end,
                max(2, int(2 * px_per_m)),
            )
        step_count = max(2, int(length / max(18.0, 25.0 * px_per_m)))
        for index in range(step_count + 1):
            fraction = index / step_count
            cone_x = start[0] + dx * fraction
            cone_y = start[1] + dy * fraction
            if work.lane_closed:
                cone_x += normal_x * barrier_width * 0.5
                cone_y += normal_y * barrier_width * 0.5
            cone_radius = max(2, int(0.35 * px_per_m))
            cone_center = (int(cone_x), int(cone_y))
            pygame.draw.polygon(
                screen,
                (245, 105, 25),
                [
                    (cone_center[0], cone_center[1] - cone_radius * 2),
                    (cone_center[0] - cone_radius, cone_center[1] + cone_radius),
                    (cone_center[0] + cone_radius, cone_center[1] + cone_radius),
                ],
            )
            pygame.draw.line(
                screen,
                (255, 220, 120),
                (cone_center[0] - cone_radius // 2, cone_center[1]),
                (cone_center[0] + cone_radius // 2, cone_center[1]),
                max(1, cone_radius // 2),
            )


def draw_crossings(
    screen,
    crossings: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw Finnish zebra pedestrian crossings (suojatiet) with white road stripes aligned to road geometry."""
    import pygame

    if not crossings:
        return

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)

    visible_crossings = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else crossings
    )
    for c in visible_crossings:
        cx_w = getattr(c, "x", 0.0)
        cy_w = getattr(c, "y", 0.0)
        if not (vminx <= cx_w <= vmaxx and vminy <= cy_w <= vmaxy):
            continue

        sc_x, sc_y = world_to_screen(cx_w, cy_w, camx, camy, px_per_m, screen_w, screen_h)

        road_angle = getattr(c, "direction_angle", None)
        if road_angle is None:
            road_angle = 0.0

        # Finnish standard zebra crossing:
        # Crosswalk spans across road width (perpendicular to road axis)
        # Stripes run along road length (parallel to road traffic direction)
        # Each stripe is ~0.5m wide with ~0.5m gap, stripe length ~2.0 - 2.5m
        cross_width_m = getattr(c, "width_m", 5.0)
        stripe_len_m = getattr(c, "length_m", 2.2)

        # Unit vectors:
        # u_along: parallel to road traffic direction (direction of zebra stripes)
        # u_across: perpendicular to road (lateral across the crosswalk)
        # Note: In Pygame screen space, positive Y is down, so world Y is inverted (-sin)
        u_along_x = math.cos(road_angle)
        u_along_y = -math.sin(road_angle)

        u_across_x = -u_along_y  # perpendicular (90 deg counter-clockwise)
        u_across_y = u_along_x

        stripe_len_px = max(2.0, stripe_len_m * px_per_m)
        stripe_width_m = 0.5
        stripe_spacing_m = 0.9

        num_stripes = max(3, int(cross_width_m / stripe_spacing_m))
        span_total_m = (num_stripes - 1) * stripe_spacing_m
        start_offset_m = -span_total_m / 2.0

        stripe_thickness = max(1, int(stripe_width_m * px_per_m))
        stripe_color = (245, 245, 245)

        for i in range(num_stripes):
            lat_m = start_offset_m + i * stripe_spacing_m
            lat_px_x = u_across_x * (lat_m * px_per_m)
            lat_px_y = u_across_y * (lat_m * px_per_m)

            stripe_center_x = sc_x + lat_px_x
            stripe_center_y = sc_y + lat_px_y

            half_len_x = u_along_x * (stripe_len_px / 2.0)
            half_len_y = u_along_y * (stripe_len_px / 2.0)

            p1 = (stripe_center_x - half_len_x, stripe_center_y - half_len_y)
            p2 = (stripe_center_x + half_len_x, stripe_center_y + half_len_y)

            pygame.draw.line(screen, stripe_color, p1, p2, stripe_thickness)


def draw_labels(
    screen,
    font,
    ways: List[Way],
    waters: List[Water],
    buildings: List[Building],
    sceneries: List[Scenery],
    places: List[Place],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    max_labels: int = 35,
    spatial_grid=None,
    scenery_grid=None,
    building_grid=None,
    label_mode: int = 2,
) -> None:
    """Draw selected map labels with decluttering and collision avoidance."""
    _draw_labels_uncached(
        screen,
        font,
        ways,
        waters,
        buildings,
        sceneries,
        places,
        camx,
        camy,
        px_per_m,
        screen_w,
        screen_h,
        max_labels,
        spatial_grid,
        scenery_grid,
        building_grid,
        label_mode,
    )


def _draw_labels_uncached(
    screen,
    font,
    ways: List[Way],
    waters: List[Water],
    buildings: List[Building],
    sceneries: List[Scenery],
    places: List[Place],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    max_labels: int = 35,
    spatial_grid=None,
    scenery_grid=None,
    building_grid=None,
    label_mode: int = 2,
) -> None:
    """Draw selected map labels with decluttering and collision avoidance."""
    import pygame

    if label_mode <= 0:
        return
    placed_rects: List[pygame.Rect] = []
    seen_names: set[str] = set()
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)

    district_font = font
    building_font = font
    try:
        district_font = pygame.font.SysFont(None, 20, bold=True)
        building_font = pygame.font.SysFont(None, 16)
    except Exception:
        pass

    count = 0
    label_sceneries = (
        scenery_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if scenery_grid is not None
        else sceneries
    )
    label_buildings = (
        building_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if building_grid is not None
        else buildings
    )

    def render_label(
        text: str,
        wx: float,
        wy: float,
        text_color,
        bg_color=(20, 20, 20, 190),
        use_font=None,
        border_color=None,
    ) -> bool:
        nonlocal count
        if count >= max_labels:
            return False
        if not (vminx <= wx <= vmaxx and vminy <= wy <= vmaxy):
            return False

        sx, sy = world_to_screen(wx, wy, camx, camy, px_per_m, screen_w, screen_h)
        # Avoid HUD / top bar area
        if not (10 <= sx <= screen_w - 10 and 80 <= sy <= screen_h - 20):
            return False

        f = use_font or font
        txt_surf = f.render(text, True, text_color)
        rect = txt_surf.get_rect(center=(sx, sy))
        bg_rect = rect.inflate(10, 6)

        # Check collision with already placed labels
        for pr in placed_rects:
            if bg_rect.colliderect(pr):
                return False

        placed_rects.append(bg_rect)
        bg_surface = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg_surface.fill(bg_color)
        screen.blit(bg_surface, bg_rect.topleft)
        if border_color:
            pygame.draw.rect(screen, border_color, bg_rect, width=1, border_radius=3)
        screen.blit(txt_surf, rect)
        count += 1
        return True

    if label_mode >= 2:
        # 1. Kaupunginosat / Districts & Suburbs (high prominence, warm gold/amber)
        for p in places:
            if count >= max_labels:
                break
            name = getattr(p, "name", None)
            if name and name not in seen_names:
                if render_label(
                    name,
                    p.x,
                    p.y,
                    (255, 230, 120),
                    (30, 25, 10, 220),
                    use_font=district_font,
                    border_color=(200, 170, 70),
                ):
                    seen_names.add(name)

        # 2. Water bodies (cyan)
        for wat in waters:
            if count >= max_labels:
                break
            name = getattr(wat, "name", None)
            if not name or name in seen_names:
                continue
            bb = getattr(wat, "bbox", None)
            if bb and bb != (0.0, 0.0, 0.0, 0.0):
                if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                    continue
            if wat.points_m:
                cx = (bb[0] + bb[2]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[0] for p in wat.points_m) / len(wat.points_m))
                cy = (bb[1] + bb[3]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[1] for p in wat.points_m) / len(wat.points_m))
                if render_label(name, cx, cy, (160, 225, 255), (10, 30, 50, 210)):
                    seen_names.add(name)

        # 3. Scenery / Parks (green)
        for sc in label_sceneries:
            if count >= max_labels:
                break
            name = getattr(sc, "name", None)
            if not name or name in seen_names:
                continue
            bb = getattr(sc, "bbox", None)
            if bb and bb != (0.0, 0.0, 0.0, 0.0):
                if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                    continue
            if sc.points_m:
                cx = (bb[0] + bb[2]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[0] for p in sc.points_m) / len(sc.points_m))
                cy = (bb[1] + bb[3]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[1] for p in sc.points_m) / len(sc.points_m))
                if render_label(name, cx, cy, (190, 255, 190), (15, 45, 15, 210)):
                    seen_names.add(name)

    # 4. Road / street names (white, only when sufficiently zoomed in)
    if px_per_m >= 0.35:
        label_ways = (
            spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
            if spatial_grid is not None
            else ways
        )
        for w in label_ways:
            if count >= max_labels:
                break
            name = getattr(w, "name", None)
            if not name or name in seen_names:
                continue
            bb = getattr(w, "bbox", None)
            if bb and bb != (0.0, 0.0, 0.0, 0.0):
                if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                    continue
            pts = w.points_m
            if len(pts) >= 2:
                mid_idx = len(pts) // 2
                mx = (pts[mid_idx - 1][0] + pts[mid_idx][0]) * 0.5
                my = (pts[mid_idx - 1][1] + pts[mid_idx][1]) * 0.5
                if render_label(name, mx, my, (255, 255, 255), (25, 25, 25, 210)):
                    seen_names.add(name)

    # 5. Buildings (warm yellow, only when sufficiently zoomed in and room left)
    if label_mode >= 2 and px_per_m >= 0.45 and count < max_labels:
        for b in label_buildings:
            if count >= max_labels:
                break
            name = getattr(b, "name", None)
            if not name or name in seen_names:
                continue
            bb = getattr(b, "bbox", None)
            if bb and bb != (0.0, 0.0, 0.0, 0.0):
                if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                    continue
            if b.points_m:
                cx = (bb[0] + bb[2]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[0] for p in b.points_m) / len(b.points_m))
                cy = (bb[1] + bb[3]) * 0.5 if bb and bb != (0.0, 0.0, 0.0, 0.0) else (sum(p[1] for p in b.points_m) / len(b.points_m))
                if render_label(name, cx, cy, (255, 240, 180), (35, 30, 25, 210), use_font=building_font):
                    seen_names.add(name)


def _draw_vehicle_lights(
    screen,
    cx: float,
    cy: float,
    heading: float,
    length_px: float,
    width_px: float,
    turn_signal: str = "",
    turn_signal_elapsed: float = 0.0,
    braking: bool = False,
    reversing: bool = False,
) -> None:
    import pygame

    fx = math.cos(heading)
    fy = -math.sin(heading)
    rx = math.sin(heading)
    ry = math.cos(heading)
    hl = length_px / 2.0
    hw = width_px / 2.0
    light_inset = hw * 0.7
    light_r = max(1.2, width_px * 0.18)
    def draw_light_rectangle(color, light, length, width):
        half_length = length * 0.5
        half_width = width * 0.5
        corners = [
            (light[0] + fx * half_length + rx * half_width, light[1] + fy * half_length + ry * half_width),
            (light[0] + fx * half_length - rx * half_width, light[1] + fy * half_length - ry * half_width),
            (light[0] - fx * half_length - rx * half_width, light[1] - fy * half_length - ry * half_width),
            (light[0] - fx * half_length + rx * half_width, light[1] - fy * half_length + ry * half_width),
        ]
        pygame.draw.polygon(screen, color, corners)

    front_right = (cx + fx * (hl - 0.5) + rx * light_inset, cy + fy * (hl - 0.5) + ry * light_inset)
    front_left = (cx + fx * (hl - 0.5) - rx * light_inset, cy + fy * (hl - 0.5) - ry * light_inset)
    rear_right = (cx - fx * (hl - 0.5) + rx * light_inset, cy - fy * (hl - 0.5) + ry * light_inset)
    rear_left = (cx - fx * (hl - 0.5) - rx * light_inset, cy - fy * (hl - 0.5) - ry * light_inset)
    # Keep the lamp span inside the vehicle's side edge.
    light_length = min(width_px * 0.25, max(1.0, light_r * 2.4))
    light_width = min(length_px * 0.08, max(1.0, light_r * 0.75))
    for light in (front_right, front_left):
        draw_light_rectangle((255, 255, 230), light, light_width, light_length)
    for light in (rear_right, rear_left):
        brake_scale = 1.2 if braking else 1.0
        draw_light_rectangle(
            (255, 0, 0) if braking else (230, 30, 30),
            light,
            light_width * brake_scale,
            light_length * brake_scale,
        )
    if reversing:
        reverse_r = max(1.0, light_r * 0.65)
        reverse_x = (rear_right[0] + rear_left[0]) * 0.5
        reverse_y = (rear_right[1] + rear_left[1]) * 0.5
        draw_light_rectangle((245, 245, 235), (reverse_x, reverse_y), reverse_r, light_length * 0.65)
    turn_signal_on = turn_signal and (turn_signal_elapsed % 0.9 < 0.45)
    if turn_signal_on:
        signal_side = 1.0 if turn_signal == "right" else -1.0
        for signal_x, signal_y in (
            (
                cx + fx * (hl - 0.5) + rx * (light_inset * signal_side),
                cy + fy * (hl - 0.5) + ry * (light_inset * signal_side),
            ),
            (
                cx - fx * (hl - 0.5) + rx * (light_inset * signal_side),
                cy - fy * (hl - 0.5) + ry * (light_inset * signal_side),
            ),
        ):
            draw_light_rectangle((255, 170, 20), (signal_x, signal_y), light_width, light_length)


def _draw_vehicle(
    screen,
    cx: float,
    cy: float,
    heading: float,
    length_px: float,
    width_px: float,
    body_color: Tuple[int, int, int],
    outline_color: Tuple[int, int, int] = (20, 20, 20),
    is_taxi: bool = False,
    turn_signal: str = "",
    turn_signal_elapsed: float = 0.0,
    door_open_progress: float = 0.0,
) -> None:
    """Draw an oriented vehicle box on scale with headlights (white) and taillights (red)."""
    import pygame

    cos_h = math.cos(heading)
    sin_h = math.sin(heading)

    # Local vehicle axes:
    # Forward vector in screen coordinates (screen y is inverted relative to world y)
    fx = cos_h
    fy = -sin_h

    # Right perpendicular vector
    rx = sin_h
    ry = cos_h

    hl = length_px / 2.0
    hw = width_px / 2.0

    # 4 corners of rectangle: Front-Right, Front-Left, Rear-Left, Rear-Right
    c_fr = (cx + fx * hl + rx * hw, cy + fy * hl + ry * hw)
    c_fl = (cx + fx * hl - rx * hw, cy + fy * hl - ry * hw)
    c_rl = (cx - fx * hl - rx * hw, cy - fy * hl - ry * hw)
    c_rr = (cx - fx * hl + rx * hw, cy - fy * hl + ry * hw)

    # Vehicle body
    pygame.draw.polygon(screen, body_color, [c_fr, c_fl, c_rl, c_rr])
    pygame.draw.polygon(screen, outline_color, [c_fr, c_fl, c_rl, c_rr], 1)

    # Windshield / cabin accent
    if length_px >= 6.0:
        cabin_hl = hl * 0.45
        cabin_hw = hw * 0.75
        cab_fr = (cx + fx * (cabin_hl * 0.4) + rx * cabin_hw, cy + fy * (cabin_hl * 0.4) + ry * cabin_hw)
        cab_fl = (cx + fx * (cabin_hl * 0.4) - rx * cabin_hw, cy + fy * (cabin_hl * 0.4) - ry * cabin_hw)
        cab_rl = (cx - fx * (cabin_hl * 0.8) - rx * cabin_hw, cy - fy * (cabin_hl * 0.8) - ry * cabin_hw)
        cab_rr = (cx - fx * (cabin_hl * 0.8) + rx * cabin_hw, cy - fy * (cabin_hl * 0.8) + ry * cabin_hw)
        pygame.draw.polygon(screen, (30, 35, 45), [cab_fr, cab_fl, cab_rl, cab_rr])

    # Taxi sign on roof
    if is_taxi and length_px >= 6.0:
        tx_hl = hl * 0.2
        tx_hw = hw * 0.4
        t_fr = (cx + fx * tx_hl + rx * tx_hw, cy + fy * tx_hl + ry * tx_hw)
        t_fl = (cx + fx * tx_hl - rx * tx_hw, cy + fy * tx_hl - ry * tx_hw)
        t_rl = (cx - fx * tx_hl - rx * tx_hw, cy - fy * tx_hl - ry * tx_hw)
        t_rr = (cx - fx * tx_hl + rx * tx_hw, cy - fy * tx_hl + ry * tx_hw)
        pygame.draw.polygon(screen, (240, 220, 20), [t_fr, t_fl, t_rl, t_rr])
        pygame.draw.polygon(screen, (30, 30, 30), [t_fr, t_fl, t_rl, t_rr], 1)

    if is_taxi and door_open_progress > 0.0:
        # Driver-side front door swings outward from the left side of the taxi.
        door_progress = max(0.0, min(1.0, door_open_progress))
        door_center = (cx + fx * hl * 0.2 - rx * hw, cy + fy * hl * 0.2 - ry * hw)
        door_half_length = max(2.0, hl * 0.22)
        door_inner_front = (
            door_center[0] + fx * door_half_length,
            door_center[1] + fy * door_half_length,
        )
        door_inner_rear = (
            door_center[0] - fx * door_half_length,
            door_center[1] - fy * door_half_length,
        )
        door_swing = width_px * 0.95 * door_progress
        door_outer_front = (
            door_inner_front[0] - rx * door_swing,
            door_inner_front[1] - ry * door_swing,
        )
        door_outer_rear = (
            door_inner_rear[0] - rx * door_swing,
            door_inner_rear[1] - ry * door_swing,
        )
        pygame.draw.polygon(
            screen,
            (245, 205, 45),
            [door_inner_front, door_outer_front, door_outer_rear, door_inner_rear],
        )
        pygame.draw.line(screen, outline_color, door_inner_front, door_outer_front, 1)
        pygame.draw.line(screen, outline_color, door_inner_rear, door_outer_rear, 1)

    _draw_vehicle_lights(screen, cx, cy, heading, length_px, width_px, turn_signal, turn_signal_elapsed)


def draw_car(
    screen,
    car: Car,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
    shout_timer: float = 0.0,
    font=None,
    shout_text: str = "PRKL!",
    door_open_progress: float = 0.0,
    spatial_grid=None,
    current_way=None,
) -> None:
    """Draw player taxi scaled in meters with headlights and taillights."""
    import pygame

    if not _vehicle_is_on_bridge(car, current_way) and _covered_by_higher_road(
        car.x, car.y, getattr(car, "layer", 0), ways, spatial_grid
    ):
        return
    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m, screen_w, screen_h)
    length_m = getattr(car, "length_m", 4.0)
    width_m = getattr(car, "width_m", 1.8)
    length_px = max(6.0, length_m * px_per_m)
    width_px = max(3.0, width_m * px_per_m)

    _draw_vehicle(
        screen,
        cx=cx,
        cy=cy,
        heading=car.heading,
        length_px=length_px,
        width_px=width_px,
        body_color=(235, 195, 30),  # Yellow taxi
        outline_color=(30, 30, 30),
        is_taxi=True,
        door_open_progress=door_open_progress,
    )

    if shout_timer > 0.0 and font:
        alpha = int(min(255, (shout_timer / 0.5) * 255)) if shout_timer < 0.5 else 255
        shout_surf = font.render(shout_text, True, (240, 40, 40))
        shout_surf.set_alpha(alpha)
        text_width, text_height = shout_surf.get_size()
        bubble_width, bubble_height = text_width + 8, text_height + 4
        bubble_x = cx - bubble_width / 2
        bubble_y = cy - max(22, int(length_px * 0.7)) - bubble_height - 6
        bubble_surf = pygame.Surface((bubble_width, bubble_height), pygame.SRCALPHA)
        pygame.draw.rect(
            bubble_surf,
            (255, 255, 255, min(240, alpha)),
            (0, 0, bubble_width, bubble_height),
            border_radius=4,
        )
        pygame.draw.rect(
            bubble_surf,
            (200, 30, 30, alpha),
            (0, 0, bubble_width, bubble_height),
            width=1,
            border_radius=4,
        )
        bubble_surf.blit(shout_surf, (4, 2))
        screen.blit(bubble_surf, (int(bubble_x), int(bubble_y)))


def draw_vehicle_lights(
    screen,
    vehicles,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    ways: Optional[List[Way]] = None,
    spatial_grid=None,
    current_way=None,
) -> None:
    """Redraw vehicle lamps after night tinting so they remain visible in darkness."""
    for vehicle in vehicles:
        if getattr(vehicle, "is_police", False):
            continue
        vehicle_layer = getattr(vehicle, "layer", getattr(getattr(vehicle, "way", None), "layer", 0))
        active_way = current_way if vehicle is vehicles[0] else None
        if not _vehicle_is_on_bridge(vehicle, active_way) and _covered_by_higher_road(
            vehicle.x, vehicle.y, vehicle_layer, ways, spatial_grid
        ):
            continue
        cx, cy = world_to_screen(vehicle.x, vehicle.y, camx, camy, px_per_m)
        length_px = max(5.0, getattr(vehicle, "length_m", 4.0) * px_per_m)
        width_px = max(2.5, getattr(vehicle, "width_m", 1.8) * px_per_m)
        _draw_vehicle_lights(
            screen,
            cx,
            cy,
            vehicle.heading,
            length_px,
            width_px,
            getattr(vehicle, "turn_signal", ""),
            getattr(vehicle, "turn_signal_elapsed", 0.0),
            braking=getattr(vehicle, "braking", False),
            reversing=getattr(vehicle, "speed", 0.0) < -0.05,
        )


def draw_npc_cars(
    screen,
    npcs: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
    spatial_grid=None,
    show_debug: bool = False,
) -> None:
    """Draw autonomous NPC cars scaled in meters with headlights and taillights."""
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    global _motorcycle_sprite, _moped_sprite
    global _npc_debug_font
    import pygame

    if show_debug and _npc_debug_font is None:
        _npc_debug_font = pygame.font.Font(None, 16)
    debug_font = _npc_debug_font

    if _motorcycle_sprite is None:
        _motorcycle_sprite = pygame.image.load(
            os.path.join(os.path.dirname(__file__), "assets", "motorcycle.xpm")
        ).convert_alpha()
    if _moped_sprite is None:
        _moped_sprite = pygame.image.load(
            os.path.join(os.path.dirname(__file__), "assets", "moped.xpm")
        ).convert_alpha()

    for npc in npcs:
        if getattr(npc, "is_police", False) or getattr(npc, "is_on_foot", False):
            continue
        if not (vminx <= npc.x <= vmaxx and vminy <= npc.y <= vmaxy):
            continue
        if not _vehicle_is_on_bridge(npc) and _covered_by_higher_road(
            npc.x,
            npc.y,
            getattr(npc, "layer", getattr(npc.way, "layer", 0)),
            ways,
            spatial_grid,
        ):
            continue

        cx, cy = world_to_screen(npc.x, npc.y, camx, camy, px_per_m, screen_w, screen_h)
        length_m = getattr(npc, "length_m", 4.0)
        width_m = getattr(npc, "width_m", 1.8)
        length_px = max(5.0, length_m * px_per_m)
        width_px = max(2.5, width_m * px_per_m)

        vehicle_type = getattr(npc, "vehicle_type", "car")
        if vehicle_type in ("motorcycle", "moped"):
            sprite = _motorcycle_sprite if vehicle_type == "motorcycle" else _moped_sprite
            sprite_length = max(6, int(1.8 * px_per_m))
            sprite_width = max(4, int(0.6 * px_per_m))
            fallen_angle = 90.0 if getattr(npc, "fallen", False) else 0.0
            render_angle = round((math.degrees(npc.heading) - 90.0 + fallen_angle) / 15.0) * 15.0
            render_key = (
                vehicle_type,
                tuple(npc.color),
                sprite_width,
                sprite_length,
                render_angle,
            )
            rotated_sprite = _two_wheeler_render_cache.get(render_key)
            if rotated_sprite is None:
                tinted_sprite = _tinted_two_wheeler_sprite(sprite, npc.color, vehicle_type)
                scaled_sprite = pygame.transform.smoothscale(tinted_sprite, (sprite_width, sprite_length))
                rotated_sprite = pygame.transform.rotate(scaled_sprite, render_angle)
                _two_wheeler_render_cache[render_key] = rotated_sprite
            screen.blit(rotated_sprite, rotated_sprite.get_rect(center=(int(cx), int(cy))))
        else:
            _draw_vehicle(
                screen,
                cx=cx,
                cy=cy,
                heading=npc.heading,
                length_px=length_px,
                width_px=width_px,
                body_color=npc.color,
                outline_color=(20, 20, 20),
                is_taxi=getattr(npc, "is_taxi", False),
                turn_signal=getattr(npc, "turn_signal", ""),
                turn_signal_elapsed=getattr(npc, "turn_signal_elapsed", 0.0),
            )

        if show_debug:
            lod_colors = ((70, 220, 100), (240, 190, 60), (230, 90, 80))
            debug_color = lod_colors[min(2, max(0, getattr(npc, "lod_level", 0)))]
            collider_radius = max(length_px, width_px) * 0.5
            pygame.draw.circle(screen, debug_color, (int(cx), int(cy)), max(2, int(collider_radius)), 1)
            pts = getattr(npc.way, "points_m", None)
            target_pt = None
            if pts and getattr(npc, "direction", 1) == 1 and getattr(npc, "segment_idx", 0) + 1 < len(pts):
                target_pt = pts[npc.segment_idx + 1]
            elif pts and getattr(npc, "direction", 1) == -1 and getattr(npc, "segment_idx", 0) < len(pts):
                target_pt = pts[npc.segment_idx]
            if target_pt is not None:
                target_screen = world_to_screen(
                    target_pt[0], target_pt[1], camx, camy, px_per_m, screen_w, screen_h
                )
                pygame.draw.line(screen, debug_color, (int(cx), int(cy)),
                                 (int(target_screen[0]), int(target_screen[1])), 1)
            if debug_font is not None:
                debug_text = debug_font.render(
                    f"{id(npc) % 1000} {getattr(npc, 'state', 'driving')} "
                    f"L{getattr(npc, 'lod_level', 0)} {getattr(npc, 'speed', 0.0) * 3.6:.0f} km/h",
                    True,
                    debug_color,
                )
                screen.blit(debug_text, (int(cx + collider_radius + 2), int(cy - debug_text.get_height() / 2)))

        # Draw animated smoke puff effect if NPC is disabled from a crash
        crashed_timer = getattr(npc, "crashed_timer", 0.0)
        if crashed_timer > 0.0:
            import pygame
            t = 5.0 - crashed_timer
            # 3 animated puff particles floating upwards from engine bay
            fx = math.cos(npc.heading)
            fy = -math.sin(npc.heading)
            rx = math.sin(npc.heading)
            ry = math.cos(npc.heading)
            front_cx = cx + fx * (length_px * 0.4)
            front_cy = cy + fy * (length_px * 0.4)
            for puff_idx in range(4):
                offset_t = (t * 2.5 + puff_idx * 0.7) % 2.0
                drift = math.sin(t * 3.0 + puff_idx) * (4.0 * offset_t)
                puff_x = front_cx + rx * drift
                puff_y = front_cy + ry * drift - offset_t * 14.0  # drifts upwards
                radius = int(3.0 + offset_t * 5.0)
                alpha = int(max(0, min(160, (1.0 - offset_t / 2.0) * 160)))
                smoke_surf = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
                pygame.draw.circle(smoke_surf, (180, 180, 180, alpha), (radius + 1, radius + 1), radius)
                screen.blit(smoke_surf, (int(puff_x - radius - 1), int(puff_y - radius - 1)))


def draw_police_cars(screen, police_cars, camx: float, camy: float, px_per_m: float = PX_PER_M) -> None:
    """Draw patrol cars and their blue emergency lights."""
    import pygame

    for police in police_cars:
        cx, cy = world_to_screen(police.x, police.y, camx, camy, px_per_m)
        length_px = max(7.0, 4.3 * px_per_m)
        width_px = max(3.0, 1.9 * px_per_m)
        _draw_vehicle(
            screen,
            cx=cx,
            cy=cy,
            heading=police.heading,
            length_px=length_px,
            width_px=width_px,
            body_color=(235, 235, 240),
            outline_color=(20, 25, 35),
        )
        if getattr(police, "pursuing", False) and not getattr(police, "penalty_given", False):
            right_x = math.sin(police.heading)
            right_y = math.cos(police.heading)
            light_spacing = max(1.5, width_px * 0.32)
            light_radius = max(1.5, min(3.0, width_px * 0.25))
            phase = (pygame.time.get_ticks() // 180) % 2
            left_color = (255, 35, 35) if phase == 0 else (90, 20, 20)
            right_color = (40, 110, 255) if phase == 1 else (20, 45, 110)
            bar_start = (cx - right_x * light_spacing, cy - right_y * light_spacing)
            bar_end = (cx + right_x * light_spacing, cy + right_y * light_spacing)
            pygame.draw.line(screen, (25, 30, 40), bar_start, bar_end, max(2, int(light_radius * 2.2)))
            pygame.draw.circle(screen, left_color, (int(bar_start[0]), int(bar_start[1])), int(light_radius))
            pygame.draw.circle(screen, right_color, (int(bar_end[0]), int(bar_end[1])), int(light_radius))


def draw_pedestrians(
    screen,
    pedestrians: List,
    camx: float,
    camy: float,
    font=None,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
) -> None:
    """Draw pedestrians as small top-down characters and comic cursing bubbles."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 15.0)

    for ped in pedestrians:
        if not (vminx <= ped.x <= vmaxx and vminy <= ped.y <= vmaxy):
            continue
        if _covered_by_higher_road(ped.x, ped.y, getattr(ped, "layer", getattr(ped.way, "layer", 0)), ways):
            continue

        cx, cy = world_to_screen(ped.x, ped.y, camx, camy, px_per_m, screen_w, screen_h)
        radius_px = max(4.0, getattr(ped, "radius_m", 0.45) * px_per_m)
        heading_x = math.cos(ped.heading)
        heading_y = -math.sin(ped.heading)
        side_x = -heading_y
        side_y = heading_x

        # Shadow, legs, body, and head make direction readable without a detached marker.
        pygame.draw.ellipse(
            screen,
            (20, 20, 20),
            (int(cx - radius_px * 0.8), int(cy + radius_px * 0.35),
             max(2, int(radius_px * 1.6)), max(2, int(radius_px * 0.65))),
        )
        leg_start_x = cx - heading_x * radius_px * 0.15
        leg_start_y = cy - heading_y * radius_px * 0.15 + radius_px * 0.45
        for leg_side in (-1, 1):
            leg_end_x = leg_start_x + side_x * radius_px * 0.42 * leg_side + heading_x * radius_px * 0.12
            leg_end_y = leg_start_y + side_y * radius_px * 0.42 * leg_side + heading_y * radius_px * 0.12 + radius_px * 0.45
            pygame.draw.line(
                screen, (35, 35, 45),
                (int(leg_start_x), int(leg_start_y)),
                (int(leg_end_x), int(leg_end_y)),
                max(1, int(radius_px * 0.28)),
            )

        pygame.draw.ellipse(
            screen,
            (20, 20, 20),
            (int(cx - radius_px * 0.72), int(cy - radius_px * 0.35),
             max(2, int(radius_px * 1.44)), max(2, int(radius_px * 1.55))),
        )
        pygame.draw.ellipse(
            screen,
            ped.color,
            (int(cx - radius_px * 0.58), int(cy - radius_px * 0.22),
             max(2, int(radius_px * 1.16)), max(2, int(radius_px * 1.25))),
        )

        head_x = cx + heading_x * radius_px * 0.6
        head_y = cy + heading_y * radius_px * 0.6
        pygame.draw.circle(screen, (20, 20, 20), (int(head_x), int(head_y)), max(2, int(radius_px * 0.48)))
        pygame.draw.circle(screen, (238, 185, 145), (int(head_x), int(head_y)), max(1, int(radius_px * 0.35)))

        # Comic cursing bubble when startled/dodging
        curse_timer = getattr(ped, "curse_timer", 0.0)
        if curse_timer > 0.0 and font:
            curse_txt = getattr(ped, "curse_text", "@#*!%")
            # Alpha fadeout in last 0.5s
            alpha = int(min(255, (curse_timer / 0.5) * 255)) if curse_timer < 0.5 else 255

            txt_surf = font.render(curse_txt, True, (240, 40, 40))
            tw, th = txt_surf.get_size()
            bw, bh = tw + 8, th + 4
            bx = cx - bw / 2
            by = cy - radius_px - bh - 6

            # Speech bubble background
            bubble_surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
            pygame.draw.rect(bubble_surf, (255, 255, 255, min(240, alpha)), (0, 0, bw, bh), border_radius=4)
            pygame.draw.rect(bubble_surf, (200, 30, 30, alpha), (0, 0, bw, bh), width=1, border_radius=4)
            if alpha < 255:
                txt_surf.set_alpha(alpha)
            bubble_surf.blit(txt_surf, (4, 2))
            screen.blit(bubble_surf, (int(bx), int(by)))


def draw_pedestrian_reflectors(
    screen,
    pedestrians: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
    light_vehicles: Optional[List] = None,
    street_light_positions: Optional[List[Tuple[float, float]]] = None,
) -> None:
    """Draw a bright nighttime reflector point on visible pedestrians."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 15.0)
    street_light_positions = (
        _street_light_frame_world_positions
        if street_light_positions is None
        else street_light_positions
    )

    def is_lit(pedestrian) -> bool:
        for vehicle in light_vehicles or ():
            vehicle_x = getattr(vehicle, "x", None)
            vehicle_y = getattr(vehicle, "y", None)
            heading = getattr(vehicle, "heading", None)
            if vehicle_x is None or vehicle_y is None or heading is None:
                continue
            delta_x = pedestrian.x - vehicle_x
            delta_y = pedestrian.y - vehicle_y
            forward_distance = delta_x * math.cos(heading) + delta_y * math.sin(heading)
            if not 0.0 < forward_distance <= 15.0:
                continue
            lateral_distance = abs(-delta_x * math.sin(heading) + delta_y * math.cos(heading))
            if lateral_distance <= 1.5 + forward_distance * 0.35:
                return True
        return any(
            (pedestrian.x - light_x) ** 2 + (pedestrian.y - light_y) ** 2 <= STREET_LIGHT_REFLECTOR_RADIUS_M ** 2
            for light_x, light_y in street_light_positions
        )

    for ped in pedestrians:
        if not (vminx <= ped.x <= vmaxx and vminy <= ped.y <= vmaxy):
            continue
        if is_lit(ped):
            continue
        cx, cy = world_to_screen(ped.x, ped.y, camx, camy, px_per_m, screen_w, screen_h)
        pygame.draw.circle(screen, (255, 255, 245), (int(cx), int(cy)), max(1, int(px_per_m * 0.35)))


def draw_cyclists(
    screen,
    cyclists: List,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    ways: Optional[List[Way]] = None,
) -> None:
    """Draw cyclists as compact riders with bicycle wheels."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 15.0)
    for cyclist in cyclists:
        if not (vminx <= cyclist.x <= vmaxx and vminy <= cyclist.y <= vmaxy):
            continue
        if _covered_by_higher_road(cyclist.x, cyclist.y, getattr(cyclist.way, "layer", 0), ways):
            continue
        cx, cy = world_to_screen(cyclist.x, cyclist.y, camx, camy, px_per_m, screen_w, screen_h)
        global _cyclist_sprite
        if _cyclist_sprite is None:
            _cyclist_sprite = pygame.image.load(
                os.path.join(os.path.dirname(__file__), "assets", "cyclist.xpm")
            ).convert_alpha()
        sprite_scale = max(0.15, px_per_m * 3.2 / _cyclist_sprite.get_width())
        tinted_sprite = _tinted_cyclist_sprite(_cyclist_sprite, cyclist.color)
        sprite = pygame.transform.rotozoom(tinted_sprite, math.degrees(cyclist.heading) - 90.0, sprite_scale)
        screen.blit(sprite, sprite.get_rect(center=(int(cx), int(cy))))


def draw_taxi_brawl(screen, brawl, camx: float, camy: float, px_per_m: float = PX_PER_M) -> None:
    """Draw two drivers, a dust cloud, and a visible brawl status banner."""
    import pygame

    if brawl is None:
        return
    screen_w, screen_h = screen.get_size()
    phase_text = {
        "offer": "PAINA Z HAASTAAKSESI",
        "approach": "TAXI APPROACHING",
        "approach_player": "KUSKI LÄHESTYY",
        "reaction": "NYT! PAINA Z!",
        "fight": "TAXI BRAWL",
        "return": "DRIVERS RETURNING",
        "drive": "WINNER DRIVING",
    }.get(brawl.state, "TAXI DRIVER CHALLENGE")
    phase_color = (
        (130, 205, 255) if brawl.state == "approach"
        else (255, 110, 80) if brawl.state in ("fight", "reaction")
        else (130, 255, 170) if brawl.state in ("return", "drive")
        else (255, 215, 95)
    )
    banner_font = pygame.font.Font(None, 30)
    banner = banner_font.render(phase_text, True, phase_color)
    banner_rect = banner.get_rect(center=(screen_w // 2, 44))
    banner_bg = pygame.Surface((banner_rect.width + 24, banner_rect.height + 12), pygame.SRCALPHA)
    banner_bg.fill((15, 15, 18, 220))
    screen.blit(banner_bg, (banner_rect.x - 12, banner_rect.y - 6))
    screen.blit(banner, banner_rect)
    timer_font = pygame.font.Font(None, 22)
    timer = timer_font.render(f"{max(0.0, brawl.timer):.1f}s", True, (240, 240, 240))
    screen.blit(timer, timer.get_rect(center=(screen_w // 2, 70)))

    player = world_to_screen(brawl.player_x, brawl.player_y, camx, camy, px_per_m)
    opponent = world_to_screen(brawl.opponent_x, brawl.opponent_y, camx, camy, px_per_m)
    for center, color in ((player, (245, 205, 35)), (opponent, (70, 130, 240))):
        radius = max(6, int(0.85 * px_per_m))
        pygame.draw.circle(screen, color, (int(center[0]), int(center[1])), radius)
        pygame.draw.circle(screen, (25, 25, 25), (int(center[0]), int(center[1])), radius, 2)
    if brawl.dust_timer > 0.0:
        middle_x = (player[0] + opponent[0]) * 0.5
        middle_y = (player[1] + opponent[1]) * 0.5
        radius = max(18, int(10 * px_per_m))
        dust = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(dust, (185, 155, 105, 170), (radius, radius), radius)
        pygame.draw.circle(dust, (220, 195, 145, 120), (radius // 2, radius), max(8, radius // 2))
        screen.blit(dust, (int(middle_x - radius), int(middle_y - radius)))
    if brawl.curse_timer > 0.0:
        font = pygame.font.Font(None, 22)
        bubble = font.render("@#*!%", True, (220, 40, 40))
        screen.blit(bubble, bubble.get_rect(center=(int(opponent[0]), int(opponent[1] - 18))))


def draw_traffic_lights(
    screen,
    traffic_lights: List,
    sim_time: float,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw traffic signal posts and active lights."""
    import pygame

    global _traffic_light_surface_cache

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)

    visible_traffic_lights = (
        spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
        if spatial_grid is not None
        else traffic_lights
    )
    for tl in visible_traffic_lights:
        if not (vminx <= tl.x <= vmaxx and vminy <= tl.y <= vmaxy):
            continue

        cx, cy = world_to_screen(tl.x, tl.y, camx, camy, px_per_m, screen_w, screen_h)
        state = tl.get_state(sim_time)

        # Colors for 3 lamps (dim when off, bright with glow when on)
        is_red = state in ("red", "red+yellow")
        is_yellow = state in ("yellow", "red+yellow")
        is_green = state == "green"

        r_col = (255, 30, 30) if is_red else (60, 10, 10)
        y_col = (255, 210, 0) if is_yellow else (60, 50, 0)
        g_col = (40, 240, 60) if is_green else (10, 50, 15)

        lamp_r = 2
        rotation = 90.0 - math.degrees(tl.direction_angle or 0.0)
        cache_key = (id(tl), state, round(rotation, 3), px_per_m)
        rotated = _traffic_light_surface_cache.get(cache_key)
        if rotated is None:
            signal_surface = pygame.Surface((7, 18), pygame.SRCALPHA)
            signal_surface.fill((15, 15, 15, 255))
            pygame.draw.rect(signal_surface, (70, 70, 70), signal_surface.get_rect(), width=1, border_radius=2)
            for y, color, active in ((4, r_col, is_red), (9, y_col, is_yellow), (14, g_col, is_green)):
                if active:
                    pygame.draw.circle(signal_surface, (*color, 90), (3, y), 4)
                pygame.draw.circle(signal_surface, color, (3, y), lamp_r)
            rotated = pygame.transform.rotate(signal_surface, rotation)
            _traffic_light_surface_cache[cache_key] = rotated
        screen.blit(rotated, rotated.get_rect(center=(int(cx), int(cy))))


def draw_taxi_stops(
    screen,
    taxi_stops: List[TaxiStop],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw yellow TAXI signs at OSM taxi stops."""
    import pygame

    global _taxi_sign_text
    if _taxi_sign_text is None:
        sign_font = pygame.font.Font(None, 11)
        _taxi_sign_text = sign_font.render("TAXI", True, (20, 20, 20))

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    for stop in taxi_stops:
        if not (vminx <= stop.x <= vmaxx and vminy <= stop.y <= vmaxy):
            continue

        cx, cy = world_to_screen(stop.x, stop.y, camx, camy, px_per_m, screen_w, screen_h)
        pole_bottom = cy + 11
        pygame.draw.line(screen, (55, 55, 55), (cx, cy - 1), (cx, pole_bottom), 2)
        sign = pygame.Rect(cx - 14, cy - 13, 28, 14)
        pygame.draw.rect(screen, (20, 20, 20), sign, border_radius=2)
        inner_sign = sign.inflate(-2, -2)
        pygame.draw.rect(screen, (255, 205, 25), inner_sign, border_radius=1)
        screen.blit(_taxi_sign_text, _taxi_sign_text.get_rect(center=inner_sign.center))


def draw_bus_stops(
    screen,
    bus_stops: List[BusStop],
    ways: List[Way],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Draw roadside bus bays and small road-aligned shelters from OSM stops."""
    import pygame

    global _bus_stop_geometry_cache, _bus_stop_font_cache, _bus_stop_label_cache

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 35.0)
    cache_key = (id(bus_stops), len(bus_stops), id(ways), len(ways), id(spatial_grid))
    if _bus_stop_geometry_cache is None or _bus_stop_geometry_cache[0] != cache_key:
        road_ways = [way for way in ways if way.is_drivable and len(way.points_m) >= 2]
        stop_geometry = []
        for stop in bus_stops:
            nearest = None
            candidate_ways = (
                spatial_grid.ways_in_rect(stop.x - 45.0, stop.y - 45.0, stop.x + 45.0, stop.y + 45.0)
                if spatial_grid is not None
                else road_ways
            )
            for way in candidate_ways:
                if not way.is_drivable or len(way.points_m) < 2:
                    continue
                if getattr(way, "layer", 0) != getattr(stop, "layer", 0):
                    continue
                for start, end in zip(way.points_m, way.points_m[1:]):
                    dx = end[0] - start[0]
                    dy = end[1] - start[1]
                    length_sq = dx * dx + dy * dy
                    if length_sq <= 1e-9:
                        continue
                    fraction = max(0.0, min(1.0, ((stop.x - start[0]) * dx + (stop.y - start[1]) * dy) / length_sq))
                    projected = (start[0] + fraction * dx, start[1] + fraction * dy)
                    distance_sq = (stop.x - projected[0]) ** 2 + (stop.y - projected[1]) ** 2
                    if nearest is None or distance_sq < nearest[0]:
                        length = math.sqrt(length_sq)
                        nearest = (distance_sq, projected, (dx / length, dy / length), way.half_width_m)
            if nearest is None or nearest[0] > 45.0 * 45.0:
                stop_geometry.append(None)
                continue

            _, projected, tangent, half_width = nearest
            normal = (-tangent[1], tangent[0])
            side_sign = 1.0 if (stop.x - projected[0]) * normal[0] + (stop.y - projected[1]) * normal[1] >= 0.0 else -1.0
            stop_geometry.append((stop, projected, tangent, half_width, (normal[0] * side_sign, normal[1] * side_sign)))
        _bus_stop_geometry_cache = (cache_key, stop_geometry)

    font_size = max(8, min(32, round(2.0 * px_per_m)))
    bus_font = _bus_stop_font_cache.get(font_size)
    if bus_font is None:
        bus_font = pygame.font.Font(None, font_size)
        _bus_stop_font_cache[font_size] = bus_font

    for geometry in _bus_stop_geometry_cache[1]:
        if geometry is None:
            continue
        stop, projected, tangent, half_width, normal = geometry
        if not (vminx <= stop.x <= vmaxx and vminy <= stop.y <= vmaxy):
            continue
        bay_half_length = 14.0
        bay_outer_half_length = 10.0
        bay_outer = half_width + 2.2
        bay_points = [
            (projected[0] - tangent[0] * bay_half_length + normal[0] * half_width, projected[1] - tangent[1] * bay_half_length + normal[1] * half_width),
            (projected[0] + tangent[0] * bay_half_length + normal[0] * half_width, projected[1] + tangent[1] * bay_half_length + normal[1] * half_width),
            (projected[0] + tangent[0] * bay_outer_half_length + normal[0] * bay_outer, projected[1] + tangent[1] * bay_outer_half_length + normal[1] * bay_outer),
            (projected[0] - tangent[0] * bay_outer_half_length + normal[0] * bay_outer, projected[1] - tangent[1] * bay_outer_half_length + normal[1] * bay_outer),
        ]
        pygame.draw.polygon(screen, (82, 82, 78), [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for x, y in bay_points])

        shelter_center = (projected[0] + normal[0] * (half_width + 3.2), projected[1] + normal[1] * (half_width + 3.2))
        if stop.shelter:
            shelter_length = 5.0
            shelter_width = 2.0
            shelter_points = [
                (shelter_center[0] - tangent[0] * shelter_length / 2 - normal[0] * shelter_width / 2, shelter_center[1] - tangent[1] * shelter_length / 2 - normal[1] * shelter_width / 2),
                (shelter_center[0] + tangent[0] * shelter_length / 2 - normal[0] * shelter_width / 2, shelter_center[1] + tangent[1] * shelter_length / 2 - normal[1] * shelter_width / 2),
                (shelter_center[0] + tangent[0] * shelter_length / 2 + normal[0] * shelter_width / 2, shelter_center[1] + tangent[1] * shelter_length / 2 + normal[1] * shelter_width / 2),
                (shelter_center[0] - tangent[0] * shelter_length / 2 + normal[0] * shelter_width / 2, shelter_center[1] - tangent[1] * shelter_length / 2 + normal[1] * shelter_width / 2),
            ]
            shelter_screen = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for x, y in shelter_points]
            pygame.draw.polygon(screen, (190, 190, 180), shelter_screen)
            pygame.draw.lines(screen, (45, 45, 42), True, shelter_screen, max(1, int(px_per_m * 0.25)))
        label_angle = round(-math.degrees(math.atan2(tangent[1], tangent[0])))
        label_key = (font_size, label_angle)
        label = _bus_stop_label_cache.get(label_key)
        if label is None:
            label = pygame.transform.rotate(bus_font.render("BUS", True, (25, 25, 25)), label_angle)
            _bus_stop_label_cache[label_key] = label
        label_center = world_to_screen(shelter_center[0], shelter_center[1], camx, camy, px_per_m, screen_w, screen_h)
        screen.blit(label, label.get_rect(center=label_center))


def draw_speed_cameras(
    screen,
    cameras,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    flash_index: Optional[int] = None,
    flash_active: bool = False,
) -> None:
    """Draw roadside speed-camera boxes and their posts."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    for camera_index, camera in enumerate(cameras):
        if not (vminx <= camera.x <= vmaxx and vminy <= camera.y <= vmaxy):
            continue
        cx, cy = world_to_screen(camera.x, camera.y, camx, camy, px_per_m, screen_w, screen_h)
        scale = max(0.7, min(1.5, px_per_m / PX_PER_M))
        pole_height = max(10, int(18 * scale))
        pygame.draw.line(screen, (48, 52, 56), (cx, cy + 2), (cx, cy + pole_height), max(2, int(2 * scale)))
        direction_x = -math.cos(camera.heading)
        direction_y = math.sin(camera.heading)
        side_x = -direction_y
        side_y = direction_x
        half_width = 8 * scale
        half_height = 5.5 * scale
        front_x = cx + direction_x * half_height
        front_y = cy + direction_y * half_height
        back_x = cx - direction_x * half_height
        back_y = cy - direction_y * half_height
        corners = [
            (back_x + side_x * half_width, back_y + side_y * half_width),
            (front_x + side_x * half_width, front_y + side_y * half_width),
            (front_x - side_x * half_width, front_y - side_y * half_width),
            (back_x - side_x * half_width, back_y - side_y * half_width),
        ]
        pygame.draw.polygon(screen, (35, 40, 44), corners)
        pygame.draw.lines(screen, (190, 198, 202), True, corners, 1)
        lens_x = front_x + direction_x * 1.5 * scale
        lens_y = front_y + direction_y * 1.5 * scale
        pygame.draw.circle(screen, (220, 45, 35), (int(lens_x), int(lens_y)), max(2, int(2.5 * scale)))
        if flash_active and flash_index == camera_index:
            flash = pygame.Surface((70, 70), pygame.SRCALPHA)
            pygame.draw.circle(flash, (255, 255, 235, 150), (35, 35), 30)
            pygame.draw.circle(flash, (255, 255, 255, 235), (35, 35), 12)
            screen.blit(flash, (int(lens_x - 35), int(lens_y - 35)))
        arrow_start = (front_x + direction_x * 3 * scale, front_y + direction_y * 3 * scale)
        arrow_end = (front_x + direction_x * 15 * scale, front_y + direction_y * 15 * scale)
        pygame.draw.line(screen, (245, 205, 35), arrow_start, arrow_end, max(2, int(2 * scale)))
        arrow_side = max(2.5, 4 * scale)
        pygame.draw.polygon(screen, (245, 205, 35), [
            arrow_end,
            (arrow_end[0] - direction_x * arrow_side + side_x * arrow_side, arrow_end[1] - direction_y * arrow_side + side_y * arrow_side),
            (arrow_end[0] - direction_x * arrow_side - side_x * arrow_side, arrow_end[1] - direction_y * arrow_side - side_y * arrow_side),
        ])


def draw_taxi_target(
    screen,
    taxi_mgr: TaxiManager,
    camx: float,
    camy: float,
    font,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw pulsing waypoint circle, pin icon, and on-screen navigation arrow for active pickup/dropoff."""
    import pygame

    target = taxi_mgr.get_current_target()
    if not target:
        return

    is_pickup = taxi_mgr.state in (TaxiState.WAITING_FOR_PICKUP, TaxiState.CLIENT_WALKING_TO_CAR)
    main_color = (255, 200, 0) if is_pickup else (50, 220, 100)
    bg_marker_color = (255, 200, 0, 70) if is_pickup else (50, 220, 100, 70)

    # World position to screen
    sx, sy = world_to_screen(target.x, target.y, camx, camy, px_per_m, screen_w, screen_h)

    # Check if target is inside screen viewport
    in_view = 30 <= sx <= screen_w - 30 and 30 <= sy <= screen_h - 30

    if in_view:
        # Draw radius zone
        rad_px = max(8, int(target.radius_m * px_per_m))
        rad_surf = pygame.Surface((rad_px * 2 + 4, rad_px * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(rad_surf, bg_marker_color, (rad_px + 2, rad_px + 2), rad_px)
        pygame.draw.circle(rad_surf, main_color, (rad_px + 2, rad_px + 2), rad_px, 2)
        screen.blit(rad_surf, (sx - rad_px - 2, sy - rad_px - 2))

        # Center pulsing marker
        pygame.draw.circle(screen, main_color, (sx, sy), 7)
        pygame.draw.circle(screen, (20, 20, 20), (sx, sy), 7, 2)

        # Label above target
        tag_text = tr(language, "pickup") if is_pickup else tr(language, "to")
        lbl_surf = font.render(f"[{tag_text}] {target.address}", True, (255, 255, 255))
        rect = lbl_surf.get_rect(center=(sx, sy - rad_px - 14))
        bg_rect = rect.inflate(8, 4)
        bg = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg.fill((20, 20, 20, 220))
        screen.blit(bg, bg_rect.topleft)
        pygame.draw.rect(screen, main_color, bg_rect, width=1, border_radius=3)
        screen.blit(lbl_surf, rect)


        # Draw client pedestrian waiting or walking into the taxi
        p = taxi_mgr.current_passenger
        if is_pickup and p and not p.boarded:
            ped_sx, ped_sy = world_to_screen(p.ped_x, p.ped_y, camx, camy, px_per_m, screen_w, screen_h)
            ped_r = max(4.0, 0.5 * px_per_m)
            # Outline
            pygame.draw.circle(screen, (20, 20, 20), (int(ped_sx), int(ped_sy)), int(ped_r + 2))
            # Client body in distinct passenger color
            pygame.draw.circle(screen, p.ped_color, (int(ped_sx), int(ped_sy)), int(ped_r))
            # Heading notch
            hx = ped_sx + math.cos(p.ped_heading) * (ped_r * 0.9)
            hy = ped_sy + math.sin(p.ped_heading) * (ped_r * 0.9)
            pygame.draw.circle(screen, (255, 255, 255), (int(hx), int(hy)), max(1, int(ped_r * 0.45)))

            # Passenger name tag over client
            walking_label = "KYYTIIN" if language == "fi" else "TO TAXI"
            p_lbl = font.render(
                f"[{walking_label}] {p.name}" if p.is_walking_to_car else f"[P] {p.name}",
                True,
                (255, 230, 80),
            )
            p_rect = p_lbl.get_rect(center=(int(ped_sx), int(ped_sy - ped_r - 12)))
            p_bg = pygame.Surface((p_rect.width + 6, p_rect.height + 4), pygame.SRCALPHA)
            p_bg.fill((20, 20, 20, 200))
            screen.blit(p_bg, (p_rect.left - 3, p_rect.top - 2))
            screen.blit(p_lbl, p_rect)
    else:
        # Off-screen direction indicator arrow pointing towards target
        dx = target.x - camx
        dy = target.y - camy
        angle = math.atan2(dy, dx)
        dist_m = math.hypot(dx, dy)

        # Screen margin clamp for arrow
        edge_margin = 130
        center_x = screen_w / 2
        center_y = screen_h / 2
        # Ray-intersect with screen bounding rectangle
        dir_x = math.cos(angle)
        dir_y = -math.sin(angle)  # Inverted Y for screen coords

        max_dx = (screen_w / 2) - edge_margin
        max_dy = (screen_h / 2) - edge_margin

        scale_x = abs(max_dx / dir_x) if dir_x != 0 else float("inf")
        scale_y = abs(max_dy / dir_y) if dir_y != 0 else float("inf")
        scale = min(scale_x, scale_y)

        arrow_x = int(center_x + dir_x * scale)
        arrow_y = int(center_y + dir_y * scale)

        # Draw arrow triangle
        a_len = 16
        p1 = (arrow_x + math.cos(angle) * a_len, arrow_y - math.sin(angle) * a_len)
        p2 = (arrow_x + math.cos(angle + 2.5) * a_len * 0.7, arrow_y - math.sin(angle + 2.5) * a_len * 0.7)
        p3 = (arrow_x + math.cos(angle - 2.5) * a_len * 0.7, arrow_y - math.sin(angle - 2.5) * a_len * 0.7)
        pygame.draw.polygon(screen, main_color, [p1, p2, p3])
        pygame.draw.polygon(screen, (20, 20, 20), [p1, p2, p3], 1)

        # Distance tag on edge pointer
        d_str = f"{dist_m:.0f}m" if dist_m < 1000 else f"{dist_m / 1000.0:.1f}km"
        tag = tr(language, "pickup_short") if is_pickup else tr(language, "dropoff_short")
        d_surf = font.render(f"{tag} {d_str}", True, (255, 255, 255))
        d_rect = d_surf.get_rect(center=(arrow_x, arrow_y + 18 if arrow_y < screen_h - 40 else arrow_y - 18))
        d_bg = pygame.Surface((d_rect.width + 6, d_rect.height + 4), pygame.SRCALPHA)
        d_bg.fill((15, 15, 15, 210))
        screen.blit(d_bg, (d_rect.x - 3, d_rect.y - 2))
        screen.blit(d_surf, d_rect)


def draw_navigation_route(
    screen,
    route: Optional[List[Tuple[float, float]]],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw the active taxi route above roads and below gameplay markers."""
    import pygame

    if not route or len(route) < 2:
        return
    points = [
        world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h)
        for x, y in route
    ]
    pygame.draw.lines(screen, (60, 45, 5), False, points, max(5, int(px_per_m * 0.8)))
    pygame.draw.lines(screen, (255, 215, 35), False, points, max(2, int(px_per_m * 0.45)))


def draw_day_night_overlay(
    screen,
    game_time_seconds: float,
    visible_road_count: Optional[int] = None,
    latitude: float = DEFAULT_SUN_LATITUDE,
    longitude: float = DEFAULT_SUN_LONGITUDE,
) -> None:
    """Tint the game world according to the simulated time of day."""
    import pygame

    sun_altitude, _, _ = solar_altitude_and_events(game_time_seconds, latitude, longitude)
    twilight = max(0.0, min(1.0, (sun_altitude + 12.0) / 18.0))
    alpha = int(115.0 * (1.0 - twilight))
    if visible_road_count is not None and alpha > 0:
        sparse_area = max(0.0, min(1.0, (12.0 - visible_road_count) / 12.0))
        alpha += int(95.0 * sparse_area)
    if alpha <= 0:
        return
    cache_key = (screen.get_size(), alpha)
    overlay = _day_night_overlay_cache.get(cache_key)
    if overlay is None:
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((10, 18, 48, alpha))
        _day_night_overlay_cache[cache_key] = overlay
    screen.blit(overlay, (0, 0))


def draw_phone_offers(
    screen,
    taxi_mgr: TaxiManager,
    font,
    small_font,
    screen_w: int,
    screen_h: int,
    language: str = "fi",
    car: Optional[Car] = None,
) -> None:
    """Draw the in-game phone with selectable taxi offers."""
    import pygame

    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((5, 8, 12, 170))
    screen.blit(overlay, (0, 0))

    phone = pygame.Rect(screen_w // 2 - 250, screen_h // 2 - 250, 500, 500)
    pygame.draw.rect(screen, (18, 22, 28), phone, border_radius=18)
    pygame.draw.rect(screen, (92, 105, 116), phone, width=3, border_radius=18)
    pygame.draw.rect(screen, (38, 48, 57), (phone.x + 180, phone.y + 12, 140, 5), border_radius=2)
    title = font.render(tr(language, "taxi_phone"), True, (245, 220, 110))
    screen.blit(title, title.get_rect(center=(phone.centerx, phone.y + 48)))
    subtitle = small_font.render(tr(language, "select_ride"), True, (185, 195, 202))
    screen.blit(subtitle, subtitle.get_rect(center=(phone.centerx, phone.y + 78)))

    if taxi_mgr.current_passenger:
        message = small_font.render(tr(language, "finish_or_cancel"), True, (245, 150, 120))
        screen.blit(message, message.get_rect(center=phone.center))
    elif not taxi_mgr.offers:
        message = small_font.render(tr(language, "no_requests"), True, (220, 220, 220))
        screen.blit(message, message.get_rect(center=phone.center))
    else:
        for index, offer in enumerate(taxi_mgr.offers[:3]):
            y = phone.y + 112 + index * 105
            row = pygame.Rect(phone.x + 28, y, phone.width - 56, 88)
            pygame.draw.rect(screen, (30, 39, 47), row, border_radius=6)
            pygame.draw.rect(screen, (75, 88, 97), row, width=1, border_radius=6)
            passenger = offer.passenger
            distance = (
                math.hypot(car.x - passenger.pickup.x, car.y - passenger.pickup.y)
                if car is not None
                else offer.pickup_distance_m
            )
            distance_text = f"{distance:.0f} m" if distance < 1000 else f"{distance / 1000.0:.2f} km"
            label = small_font.render(f"[{index + 1}]  {passenger.name}", True, (245, 245, 240))
            pickup = small_font.render(f"{tr(language, 'pickup')}: {passenger.pickup.address}", True, (190, 205, 212))
            dropoff = small_font.render(f"{tr(language, 'to')}: {passenger.dropoff.address}", True, (170, 190, 175))
            dist = small_font.render(f"{tr(language, 'distance_client')}: {distance_text}", True, (255, 215, 95))
            screen.blit(label, (row.x + 12, row.y + 8))
            screen.blit(pickup, (row.x + 12, row.y + 29))
            screen.blit(dropoff, (row.x + 12, row.y + 48))
            screen.blit(dist, (row.x + 12, row.y + 67))

    hint_text = tr(language, "close_phone")
    if taxi_mgr.offers:
        hint_text += f"  |  {tr(language, 'reject_phone')}"
    hint = small_font.render(hint_text, True, (180, 185, 190))
    screen.blit(hint, hint.get_rect(center=(phone.centerx, phone.bottom - 20)))


def draw_compass(screen, car: Car, cx: int, cy: int, r: int, font, target_pos: Optional[tuple[float, float]] = None) -> None:
    """Draw circular north-up compass with heading needle, bearing degrees, and taxi nav arrow."""
    import pygame

    pygame.draw.circle(screen, (40, 40, 40), (cx, cy), r)
    pygame.draw.circle(screen, (200, 200, 200), (cx, cy), r, 2)

    n_t = font.render("N", True, (240, 240, 240))
    n_rect = n_t.get_rect(center=(cx, cy - r + 10))
    screen.blit(n_t, n_rect)

    # If taxi destination exists, draw green/gold guidance pointer
    if target_pos:
        tx, ty = target_pos
        dx = tx - car.x
        dy = ty - car.y
        t_ang = math.atan2(dy, dx)
        # Draw destination indicator arrow on compass ring
        t_nx = cx + math.cos(t_ang) * (r - 4)
        t_ny = cy - math.sin(t_ang) * (r - 4)
        t_ah = 8
        t_p1 = (t_nx + math.cos(t_ang + 2.5) * t_ah, t_ny - math.sin(t_ang + 2.5) * t_ah)
        t_p2 = (t_nx + math.cos(t_ang - 2.5) * t_ah, t_ny - math.sin(t_ang - 2.5) * t_ah)
        pygame.draw.polygon(screen, (255, 215, 0), [(t_nx, t_ny), t_p1, t_p2])

    ang = car.heading
    nx = cx + math.cos(ang) * (r - 8)
    ny = cy - math.sin(ang) * (r - 8)
    pygame.draw.line(screen, (220, 40, 40), (cx, cy), (nx, ny), 3)

    ah = 6
    ph1 = (nx + math.cos(ang + 2.4) * ah, ny - math.sin(ang + 2.4) * ah)
    ph2 = (nx + math.cos(ang - 2.4) * ah, ny - math.sin(ang - 2.4) * ah)
    pygame.draw.polygon(screen, (220, 40, 40), [(nx, ny), ph1, ph2])

    deg = (90.0 - math.degrees(ang)) % 360.0
    b_t = font.render(f"{int(deg):03d}\u00B0", True, (240, 240, 240))
    b_rect = b_t.get_rect(center=(cx, cy + r - 12))
    screen.blit(b_t, b_rect)


def draw_loading_screen(
    screen,
    font,
    progress: float,
    message: str = "Loading scenery...",
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    show_details: bool = True,
    language: str = "fi",
) -> None:
    """Draw a standalone loading screen with a progress meter bar and message."""
    import pygame

    global _loading_image

    if _loading_image is None and os.path.exists(_loading_image_path):
        try:
            _loading_image = pygame.image.load(_loading_image_path).convert()
        except pygame.error:
            _loading_image = False

    if _loading_image:
        image_w, image_h = _loading_image.get_size()
        scale = max(screen_w / image_w, screen_h / image_h)
        scaled_size = (round(image_w * scale), round(image_h * scale))
        background = pygame.transform.smoothscale(_loading_image, scaled_size)
        image_x = (screen_w - scaled_size[0]) // 2
        image_y = (screen_h - scaled_size[1]) // 2
        screen.blit(background, (image_x, image_y))
        overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 105))
        screen.blit(overlay, (0, 0))
    else:
        screen.fill((20, 25, 30))

    if not show_details:
        return

    # Title
    title_font = font
    try:
        title_font = pygame.font.SysFont(None, 40, bold=True)
    except Exception:
        pass
    title_surf = title_font.render("THE ROAD RAGE TRIP", True, (240, 240, 240))
    title_rect = title_surf.get_rect(center=(screen_w // 2, screen_h // 2 - 70))
    screen.blit(title_surf, title_rect)

    # Subtitle
    sub_surf = font.render(tr(language, "loading_osm"), True, (160, 175, 190))
    sub_rect = sub_surf.get_rect(center=(screen_w // 2, screen_h // 2 - 35))
    screen.blit(sub_surf, sub_rect)

    # Progress bar dimensions
    bar_w = 440
    bar_h = 24
    bar_x = (screen_w - bar_w) // 2
    bar_y = screen_h // 2 + 5

    # Outer frame and background
    pygame.draw.rect(screen, (35, 42, 50), (bar_x, bar_y, bar_w, bar_h), border_radius=4)
    pygame.draw.rect(screen, (100, 115, 130), (bar_x, bar_y, bar_w, bar_h), width=2, border_radius=4)

    # Fill
    clamped_prog = max(0.0, min(1.0, progress))
    fill_w = int((bar_w - 4) * clamped_prog)
    if fill_w > 0:
        pygame.draw.rect(screen, (40, 180, 100), (bar_x + 2, bar_y + 2, fill_w, bar_h - 4), border_radius=2)

    # Percentage and message
    pct_str = f"{int(clamped_prog * 100)}%"
    msg_surf = font.render(f"{message} ({pct_str})", True, (220, 230, 240))
    msg_rect = msg_surf.get_rect(center=(screen_w // 2, bar_y + bar_h + 22))
    screen.blit(msg_surf, msg_rect)


def draw_city_selection_menu(
    screen,
    font,
    cities: List[str],
    selected_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
    force_refresh: bool = False,
) -> None:
    """Draw city selection menu with 10 largest cities in Finland."""
    import pygame

    draw_loading_screen(screen, font, 1.0, tr(language, "ready"), screen_w, screen_h, show_details=False, language=language)
    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((8, 14, 22, 135))
    screen.blit(overlay, (0, 0))

    # Header / Title
    title_font = font
    try:
        title_font = pygame.font.SysFont(None, 38, bold=True)
    except Exception:
        pass

    t_surf = title_font.render("THE ROAD RAGE TRIP", True, (245, 245, 245))
    t_rect = t_surf.get_rect(center=(screen_w // 2, 45))
    screen.blit(t_surf, t_rect)

    sub_font = font
    try:
        sub_font = pygame.font.SysFont(None, 22)
    except Exception:
        pass

    sub_surf = sub_font.render(tr(language, "select_city"), True, (150, 180, 210))
    sub_rect = sub_surf.get_rect(center=(screen_w // 2, 80))
    screen.blit(sub_surf, sub_rect)

    # 2-column city grid
    cols = 2
    rows = (len(cities) + cols - 1) // cols
    item_w = 320
    item_h = 42
    gap_x = 24
    gap_y = 10
    total_w = cols * item_w + (cols - 1) * gap_x
    start_x = (screen_w - total_w) // 2
    start_y = 115

    for idx, city in enumerate(cities):
        col = idx // rows
        row = idx % rows
        ix = start_x + col * (item_w + gap_x)
        iy = start_y + row * (item_h + gap_y)

        is_sel = idx == selected_idx
        bg_color = (45, 80, 130) if is_sel else (28, 36, 48)
        border_color = (100, 200, 255) if is_sel else (60, 75, 95)
        text_color = (255, 255, 255) if is_sel else (200, 210, 220)

        pygame.draw.rect(screen, bg_color, (ix, iy, item_w, item_h), border_radius=6)
        pygame.draw.rect(screen, border_color, (ix, iy, item_w, item_h), width=2 if is_sel else 1, border_radius=6)

        num_prefix = f"{(idx + 1) % 10}: "
        city_label = f"{num_prefix}{city}"
        if is_sel:
            city_label = f"> {city_label}"

        c_surf = font.render(city_label, True, text_color)
        c_rect = c_surf.get_rect(midleft=(ix + 16, iy + item_h // 2))
        screen.blit(c_surf, c_rect)

    checkbox_rect = pygame.Rect(screen_w // 2 - 150, start_y + rows * (item_h + gap_y) + 12, 22, 22)
    pygame.draw.rect(screen, (28, 36, 48), checkbox_rect, border_radius=3)
    pygame.draw.rect(screen, (100, 200, 255) if force_refresh else (100, 115, 130), checkbox_rect, width=2, border_radius=3)
    if force_refresh:
        pygame.draw.line(screen, (120, 235, 150), checkbox_rect.topleft, checkbox_rect.center, 3)
        pygame.draw.line(screen, (120, 235, 150), checkbox_rect.center, checkbox_rect.bottomright, 3)
    refresh_surf = sub_font.render(tr(language, "refresh_map"), True, (220, 230, 235))
    screen.blit(refresh_surf, refresh_surf.get_rect(midleft=(checkbox_rect.right + 10, checkbox_rect.centery)))

    edit_rect = pygame.Rect(screen_w // 2 - 150, checkbox_rect.bottom + 16, 300, 36)
    pygame.draw.rect(screen, (45, 80, 130), edit_rect, border_radius=5)
    pygame.draw.rect(screen, (100, 200, 255), edit_rect, width=1, border_radius=5)
    edit_surf = sub_font.render(tr(language, "edit_city_list"), True, (255, 255, 255))
    screen.blit(edit_surf, edit_surf.get_rect(center=edit_rect.center))

    # Navigation hint
    hint_surf = sub_font.render(
        tr(language, "city_hint"),
        True,
        (130, 150, 170),
    )
    hint_rect = hint_surf.get_rect(center=(screen_w // 2, screen_h - 35))
    screen.blit(hint_surf, hint_rect)
    _draw_version(screen, sub_font, screen_w, screen_h)


def draw_mode_selection_menu(screen, font, selected_idx: int, screen_w: int = SCREEN_W, screen_h: int = SCREEN_H, language: str = "fi") -> None:
    """Draw the initial game-mode selection menu."""
    import pygame

    draw_loading_screen(screen, font, 1.0, tr(language, "ready"), screen_w, screen_h, show_details=False, language=language)
    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((8, 14, 22, 145))
    screen.blit(overlay, (0, 0))
    title = font.render(tr(language, "select_mode"), True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, 170)))
    options = [
        tr(language, "career"),
        tr(language, "gig_driver"),
        tr(language, "reset_career"),
        tr(language, "clear_cache"),
    ]
    for index, option in enumerate(options):
        color = (255, 215, 95) if index == selected_idx else (210, 220, 230)
        label = font.render(f"{index + 1}. {option}", True, color)
        screen.blit(label, label.get_rect(center=(screen_w // 2, 270 + index * 60)))
    hint = pygame.font.SysFont(None, 18).render(tr(language, "language_hint"), True, (150, 175, 195))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, screen_h - 80)))
    _draw_version(screen, font, screen_w, screen_h)


def draw_city_summary(
    screen, font, city: str, score: int, fares: int, next_city: Optional[str] = None,
    career_total_score: Optional[int] = None,
    screen_w: int = SCREEN_W, screen_h: int = SCREEN_H, language: str = "fi",
) -> None:
    """Draw the completion summary shown before career mode continues."""
    import pygame

    screen.fill((18, 24, 32))
    title = font.render(tr(language, "city_summary"), True, (255, 215, 95))
    screen.blit(title, title.get_rect(center=(screen_w // 2, 180)))
    lines = [
        city,
        tr(language, "city_summary_score", score=score),
        tr(language, "city_summary_fares", fares=fares),
    ]
    if next_city:
        lines.append(tr(language, "next_city", city=next_city))
    else:
        lines.append(tr(language, "career_complete"))
        if career_total_score is not None:
            lines.append(tr(language, "career_total_score", score=career_total_score))
    for index, line in enumerate(lines):
        color = (245, 245, 245) if index == 0 else (205, 215, 225)
        text = font.render(line, True, color)
        screen.blit(text, text.get_rect(center=(screen_w // 2, 260 + index * 42)))
    hint = pygame.font.SysFont(None, 20).render(tr(language, "continue_enter"), True, (255, 215, 95))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, screen_h - 100)))


def draw_tutorial_screen(
    screen,
    font,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw the game's tutorial, objective, and complete control list."""
    import pygame

    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((5, 10, 16, 220))
    screen.blit(overlay, (0, 0))

    panel = pygame.Rect(90, 45, screen_w - 180, screen_h - 90)
    pygame.draw.rect(screen, (22, 30, 40), panel, border_radius=8)
    pygame.draw.rect(screen, (100, 170, 220), panel, width=2, border_radius=8)

    title_font = pygame.font.SysFont(None, 38, bold=True)
    section_font = pygame.font.SysFont(None, 25, bold=True)
    title = title_font.render(tr(language, "tutorial"), True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, panel.y + 38)))

    sections = [
        (tr(language, "story"), [
            "Olet kaiken kokenut taksikuski, joka ajaa keikkaa Suomen eri kaupungeissa." if language == "fi" else "You are a veteran taxi driver working rides across Finnish cities.",
            "Joka paikkaa yhdistävät samat riesat: idiootit kanssakuskit, ääliöt pyöräilijät" if language == "fi" else "Everywhere has the same problems: foolish drivers, awful cyclists",
            "ja eteen pyrkivät jalankulkijat. Vuosien ajo on kehittänyt sinulle supervoiman:" if language == "fi" else "and pedestrians stepping in front of you. Years on the road gave you a superpower:",
            "rattiraivo tyhjentää tien häiriöistä. Rattiraivo-mittari kasvaa rajoitusten mukaan ajaessa" if language == "fi" else "Road Rage clears obstacles. Road Rage grows when you follow limits",
            "ja pienenee, kun käytät rattiraivoa tehdäksesi tietä." if language == "fi" else "and drains when you use Road Rage to clear the way.",
        ]),
        (tr(language, "idea"), [
            "Aja asiakkaan luo, ota hänet kyytiin ja vie perille." if language == "fi" else "Drive to clients, pick them up, and take them to their destination.",
            "Nouda asiakkaat kaduilta, taksiasemilta tai nimetyiltä rakennuksilta." if language == "fi" else "Pick up clients from streets, taxi stops, or named buildings.",
            "Pysy tiellä, vältä kolareita ja kerää pisteitä nopeista onnistuneista kyydeistä." if language == "fi" else "Stay on the road, avoid crashes, and score points for successful rides.",
            "Puhelin näyttää kolme kyytiä: valitse yksi näppäimillä 1-3 tai hylkää tarjous X:llä." if language == "fi" else "The phone shows three rides: select one with 1-3 or reject an offer with X.",
            "Taksitolpan asiakas näyttää KYYTIIN-tekstin, kävelee autolle ja voi päätyä kilpailevalle NPC-taksille." if language == "fi" else "A taxi-stand customer shows TO TAXI, walks to the car, or may choose a rival NPC taxi.",
            "Aja rajoituksen mukaan: se kasvattaa rattiraivoa. Hidas lähestyminen punaista valoa kasvattaa sitä myös." if language == "fi" else "Follow the speed limit to build Road Rage. Approaching a red light slowly also builds it.",
            "Space kuluttaa 25 % mittarista ja siirtää edessä olevat ajoneuvot sivuun 50 metrin säteellä." if language == "fi" else "Space spends 25% of the meter and moves vehicles ahead aside within 50 meters.",
            "Se pysäyttää aktiivisen poliisin takaa-ajon kokonaan; poliisi kääntyy pois kolmeksi sekunniksi." if language == "fi" else "It ends an active police pursuit; the police turn away for three seconds.",
            "Kolarit nollaavat mittarin ja pyöräilijään törmääminen puolittaa sen." if language == "fi" else "Crashes empty the meter and hitting a cyclist halves it.",
            "Zoomaus vähentää kaukana olevia NPC-hahmoja suorituskyvyn parantamiseksi." if language == "fi" else "Zooming in reduces distant NPC characters to improve performance.",
        ]),
    ]
    y = panel.y + 78
    for heading, lines in sections:
        heading_surface = section_font.render(heading, True, (255, 215, 95))
        screen.blit(heading_surface, (panel.x + 28, y))
        y += 30
        for line in lines:
            line_surface = font.render(line, True, (220, 228, 235))
            screen.blit(line_surface, (panel.x + 42, y))
            y += 21
        y += 10

    control_font = pygame.font.SysFont("monospace", 18)
    controls = [
        ("W / Up", tr(language, "drive")),
        ("S / Down", tr(language, "brake")),
        ("A / Left", tr(language, "left")),
        ("D / Right", tr(language, "right")),
        ("P", tr(language, "phone")),
        ("1 - 3", tr(language, "select_ride")),
        ("Space", tr(language, "rage")),
        ("R", tr(language, "respawn")),
        ("X", tr(language, "cancel_ride")),
        ("T", tr(language, "reset_trip")),
        ("L", tr(language, "labels")),
        ("K", tr(language, "lane_assist")),
        ("V", tr(language, "speed_limiter")),
        ("B", tr(language, "red_assist")),
        ("N", "Navigointi" if language == "fi" else "Toggle navigation route"),
        ("+ / -", tr(language, "zoom")),
        ("Esc", tr(language, "pause")),
        ("F1", tr(language, "help_short")),
        ("F3", "Näytä/piilota debug-HUD" if language == "fi" else "Toggle diagnostic HUD"),
        ("F12", tr(language, "screenshot")),
        ("F", tr(language, "exit_car")),
    ]
    heading_surface = section_font.render(tr(language, "controls"), True, (255, 215, 95))
    screen.blit(heading_surface, (panel.x + 28, y))
    y += 30
    column_count = 3
    column_width = panel.width // column_count
    rows_per_column = (len(controls) + column_count - 1) // column_count
    for row in range(rows_per_column):
        for column in range(column_count):
            index = row + column * rows_per_column
            if index >= len(controls):
                continue
            key, action = controls[index]
            column_x = panel.x + 28 + column * column_width
            key_surface = control_font.render(key, True, (255, 215, 95))
            action_surface = pygame.font.SysFont(None, 18).render(action, True, (220, 228, 235))
            screen.blit(key_surface, (column_x, y))
            screen.blit(action_surface, (column_x + 82, y))
        y += 18

    hint = font.render(tr(language, "help_close"), True, (160, 190, 215))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, panel.bottom - 25)))


draw_help_screen = draw_tutorial_screen


def draw_pause_menu(
    screen,
    font,
    options: List[str],
    selected_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw semi-transparent pause menu overlay with selectable options."""
    import pygame

    # Semi-transparent dark overlay
    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((10, 15, 20, 190))
    screen.blit(overlay, (0, 0))

    # Menu panel
    panel_w = min(420, screen_w - 40)
    panel_h = min(screen_h - 40, max(280, 110 + len(options) * 56))
    panel_x = (screen_w - panel_w) // 2
    panel_y = (screen_h - panel_h) // 2

    panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel_surf.fill((22, 28, 38, 230))
    screen.blit(panel_surf, (panel_x, panel_y))
    pygame.draw.rect(screen, (70, 120, 180), (panel_x, panel_y, panel_w, panel_h), width=2, border_radius=8)

    # Title
    title_font = font
    try:
        title_font = pygame.font.SysFont(None, 36, bold=True)
    except Exception:
        pass
    t_surf = title_font.render(tr(language, "paused"), True, (245, 245, 245))
    t_rect = t_surf.get_rect(center=(screen_w // 2, panel_y + 40))
    screen.blit(t_surf, t_rect)

    # Options buttons
    item_w = 340
    item_h = 44
    start_y = panel_y + 80
    gap_y = 12

    for idx, opt in enumerate(options):
        iy = start_y + idx * (item_h + gap_y)
        ix = panel_x + (panel_w - item_w) // 2

        is_sel = idx == selected_idx
        bg_color = (45, 85, 140) if is_sel else (32, 40, 52)
        border_color = (100, 200, 255) if is_sel else (65, 80, 100)
        text_color = (255, 255, 255) if is_sel else (200, 210, 220)

        pygame.draw.rect(screen, bg_color, (ix, iy, item_w, item_h), border_radius=6)
        pygame.draw.rect(screen, border_color, (ix, iy, item_w, item_h), width=2 if is_sel else 1, border_radius=6)

        prefix = "> " if is_sel else "   "
        o_surf = font.render(f"{prefix}{opt}", True, text_color)
        o_rect = o_surf.get_rect(midleft=(ix + 20, iy + item_h // 2))
        screen.blit(o_surf, o_rect)

    # Hint
    sub_font = font
    try:
        sub_font = pygame.font.SysFont(None, 18)
    except Exception:
        pass
    h_surf = sub_font.render(tr(language, "select_choose_resume"), True, (140, 160, 180))
    h_rect = h_surf.get_rect(center=(screen_w // 2, panel_y + panel_h - 20))
    screen.blit(h_surf, h_rect)
    _draw_version(screen, font, screen_w, screen_h)


def draw_settings_menu(
    screen,
    font,
    language: str,
    master_volume: float,
    music_volume: float,
    effects_volume: float,
    comments_enabled: bool,
    subtitles_enabled: bool,
    overpass_endpoints: str,
    selected_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw language, audio, and Overpass endpoint settings."""
    import pygame

    screen.fill((18, 24, 32))
    panel = pygame.Rect(100, 70, screen_w - 200, screen_h - 140)
    pygame.draw.rect(screen, (22, 30, 40), panel, border_radius=8)
    pygame.draw.rect(screen, (100, 170, 220), panel, width=2, border_radius=8)
    title_font = pygame.font.SysFont(None, 36, bold=True)
    title = title_font.render(tr(language, "settings"), True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, panel.y + 42)))

    rows = [
        (tr(language, "language"), "Suomi" if language == "fi" else "English", None),
        (tr(language, "master_volume"), f"{master_volume * 100:.0f}%", master_volume),
        (tr(language, "music_volume"), f"{music_volume * 100:.0f}%", music_volume),
        (tr(language, "effects_volume"), f"{effects_volume * 100:.0f}%", effects_volume),
        (tr(language, "comment_audio"), tr(language, "on" if comments_enabled else "off"), None),
        (tr(language, "subtitles"), tr(language, "on" if subtitles_enabled else "off"), None),
        (tr(language, "overpass_endpoints"), overpass_endpoints[-55:] if len(overpass_endpoints) > 55 else overpass_endpoints, None),
    ]
    for idx, (label, value, volume) in enumerate(rows):
        y = panel.y + 100 + idx * 58
        selected = idx == selected_idx
        color = (255, 215, 95) if selected else (220, 228, 235)
        label_surface = font.render(label, True, color)
        screen.blit(label_surface, (panel.x + 38, y))
        if volume is None:
            value_surface = font.render(value, True, color)
            screen.blit(value_surface, (panel.right - 400, y))
        else:
            bar = pygame.Rect(panel.right - 240, y + 5, 150, 16)
            pygame.draw.rect(screen, (45, 55, 65), bar, border_radius=3)
            pygame.draw.rect(screen, (55, 180, 110), (bar.x, bar.y, int(bar.width * volume), bar.height), border_radius=3)
            value_surface = font.render(value, True, color)
            screen.blit(value_surface, (panel.right - 75, y))

    hint = pygame.font.SysFont(None, 18).render(tr(language, "settings_hint"), True, (150, 175, 195))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, panel.bottom - 28)))


def draw_city_editor(
    screen,
    font,
    cities: List[str],
    selected_idx: int,
    query: str,
    suggestions: List[str],
    suggestion_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw the searchable city replacement editor."""
    import pygame

    screen.fill((18, 24, 32))
    title = pygame.font.SysFont(None, 32, bold=True).render(tr(language, "city_editor"), True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, 38)))
    rows = (len(cities) + 1) // 2
    item_w, item_h, gap_x, gap_y = 300, 38, 20, 8
    start_x = (screen_w - (2 * item_w + gap_x)) // 2
    start_y = 72
    for idx, city in enumerate(cities):
        col = idx // rows
        row = idx % rows
        rect = pygame.Rect(start_x + col * (item_w + gap_x), start_y + row * (item_h + gap_y), item_w, item_h)
        selected = idx == selected_idx
        pygame.draw.rect(screen, (45, 80, 130) if selected else (28, 36, 48), rect, border_radius=5)
        pygame.draw.rect(screen, (100, 200, 255) if selected else (60, 75, 95), rect, width=2 if selected else 1, border_radius=5)
        screen.blit(font.render(f"{idx + 1}. {city}", True, (255, 255, 255)), (rect.x + 12, rect.y + 8))

    input_rect = pygame.Rect(screen_w // 2 - 250, start_y + rows * (item_h + gap_y) + 20, 500, 42)
    pygame.draw.rect(screen, (245, 245, 245), input_rect, border_radius=4)
    pygame.draw.rect(screen, (255, 215, 95), input_rect, width=2, border_radius=4)
    screen.blit(font.render(query or tr(language, "city_editor_search"), True, (30, 35, 42) if query else (120, 130, 140)), (input_rect.x + 12, input_rect.y + 9))
    for idx, suggestion in enumerate(suggestions):
        rect = pygame.Rect(input_rect.x, input_rect.bottom + 8 + idx * 34, input_rect.width, 30)
        pygame.draw.rect(screen, (55, 95, 130) if idx == suggestion_idx else (32, 43, 55), rect, border_radius=3)
        screen.blit(font.render(suggestion, True, (255, 255, 255)), (rect.x + 12, rect.y + 5))
    hint = pygame.font.SysFont(None, 18).render(tr(language, "city_editor_hint"), True, (150, 175, 195))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, screen_h - 25)))


def draw_hud(
    screen,
    font,
    car: Car,
    on_road: bool,
    ways_count: int,
    px_per_m: float,
    transformer_to_ll,
    is_auto_fetching: bool = False,
    show_labels: bool = True,
    auto_fetch_progress: float = 0.0,
    taxi_mgr: Optional[TaxiManager] = None,
    current_road_name: Optional[str] = None,
    speed_limit_kmh: Optional[int] = None,
    speed_limiter_enabled: bool = True,
    red_light_assist_enabled: bool = False,
    show_compass: bool = False,
    rage_power: float = 0.0,
    language: str = "fi",
    career_total_distance_m: Optional[float] = None,
    water_time_remaining: Optional[float] = None,
    game_time_seconds: Optional[float] = None,
    game_time_realtime: bool = False,
    comment_text: Optional[str] = None,
    comment_speaker: str = "driver",
    comment_speaker_name: Optional[str] = None,
    subtitles_enabled: bool = True,
    fps: float = 0.0,
    show_debug_hud: bool = False,
    hud_layout: Optional[dict[str, Tuple[int, int]]] = None,
    hud_rects: Optional[dict[str, object]] = None,
) -> None:
    """Draw speed, trip, odometer, on-road status, current road name, lat/lon, taxi mission bar, notifications."""
    import pygame

    screen_width = screen.get_width()
    screen_height = screen.get_height()
    layout = hud_layout if hud_layout is not None else default_hud_layout(screen_width, screen_height)
    if hud_rects is not None:
        hud_rects.clear()

    lat, lon = meters_to_latlon(car.x, car.y, transformer=transformer_to_ll)
    lat_s = f"{lat:.5f}" if lat is not None else "N/A"
    lon_s = f"{lon:.5f}" if lon is not None else "N/A"

    trip_s = f"{car.trip_m:.0f} m" if car.trip_m < 1000 else f"{car.trip_m / 1000.0:.2f} km"
    odo_s = f"{car.odometer_m / 1000.0:.1f} km"

    labels_status = tr(language, "on" if show_labels else "off")
    lane_assist_status = tr(language, "on" if getattr(car, "lane_assist_enabled", False) else "off")
    speed_limiter_status = tr(language, "on" if speed_limiter_enabled else "off")
    red_light_assist_status = tr(language, "on" if red_light_assist_enabled else "off")
    road_name_s = current_road_name if current_road_name else tr(language, "off_road")
    limit_s = f" [{tr(language, 'limit')}: {speed_limit_kmh} km/h]" if speed_limit_kmh is not None else ""
    assist_s = f" | [{tr(language, 'lane_assist_active')}]" if getattr(car, "lane_assist_active", False) else ""
    hud = (
        f"{tr(language, 'road')}: {road_name_s}{limit_s}{assist_s} | {tr(language, 'trip')}: {trip_s} | {tr(language, 'odometer')}: {odo_s} | "
        f"{tr(language, 'ways')}: {ways_count} | {tr(language, 'zoom_level')}: {px_per_m:.2f} px/m | "
        f"{tr(language, 'latitude')}: {lat_s} {tr(language, 'longitude')}: {lon_s}"
    )
    if show_debug_hud:
        text = font.render(hud, True, (240, 240, 240))
        screen.blit(text, (10, 10))

    if game_time_seconds is not None:
        total_minutes = int(game_time_seconds // 60.0) % (24 * 60)
        clock_text = f"Kello {total_minutes // 60:02d}:{total_minutes % 60:02d}"
        clock_text += " *" if game_time_realtime else ""
        clock_surface = font.render(clock_text, True, (255, 230, 120))
        clock_rect = clock_surface.get_rect(topright=(screen.get_width() - 12, 10))
        screen.blit(clock_surface, clock_rect)

    if speed_limit_kmh is not None:
        sign_center = (screen.get_width() - 48, 76)
        pygame.draw.circle(screen, (255, 210, 0), sign_center, 31)
        pygame.draw.circle(screen, (210, 35, 35), sign_center, 31, 8)
        sign_font = pygame.font.Font(None, 38)
        sign_text = sign_font.render(str(speed_limit_kmh), True, (20, 20, 20))
        screen.blit(sign_text, sign_text.get_rect(center=sign_center))

    if water_time_remaining is not None:
        water_text = font.render(
            f"{tr(language, 'water_timer')}: {water_time_remaining:.1f} s",
            True,
            (255, 235, 90),
        )
        water_rect = water_text.get_rect(center=(screen.get_width() // 2, 78))
        water_bg = pygame.Surface((water_rect.width + 24, water_rect.height + 10), pygame.SRCALPHA)
        water_bg.fill((35, 25, 15, 225))
        screen.blit(water_bg, (water_rect.x - 12, water_rect.y - 5))
        pygame.draw.rect(
            screen,
            (255, 190, 40),
            (water_rect.x - 12, water_rect.y - 5, water_rect.width + 24, water_rect.height + 10),
            2,
            border_radius=4,
        )
        screen.blit(water_text, water_rect)

    if subtitles_enabled and comment_text:
        subtitle_font = pygame.font.SysFont(None, max(22, font.get_height()))
        speaker = comment_speaker_name or tr(language, "driver")
        subtitle_surface = subtitle_font.render(f"{speaker}: {comment_text}", True, (255, 255, 255))
        subtitle_rect = subtitle_surface.get_rect(center=(screen.get_width() // 2, screen.get_height() - 82))
        subtitle_bg = pygame.Surface((subtitle_rect.width + 34, subtitle_rect.height + 16), pygame.SRCALPHA)
        subtitle_bg.fill((0, 0, 0, 205))
        screen.blit(subtitle_bg, (subtitle_rect.x - 17, subtitle_rect.y - 8))
        screen.blit(subtitle_surface, subtitle_rect)

    hint = (
        f"{tr(language, 'controls')}: W/S/A/D = {tr(language, 'drive').lower()} | +/- = {tr(language, 'zoom').lower()} | R = {tr(language, 'respawn').lower()} | X = {tr(language, 'cancel_ride').lower()} | T = {tr(language, 'reset_trip').lower()} | "
        f"L = labels ({labels_status}) | K = lane assist ({lane_assist_status}) | V = limiter ({speed_limiter_status}) | B = red assist ({red_light_assist_status}) | C = {tr(language, 'compass')} ({tr(language, 'on' if show_compass else 'off')}) | Space = {tr(language, 'rage')} | ESC = pause"
    )
    if show_debug_hud:
        hint_t = font.render(hint, True, (220, 220, 220))
        screen.blit(hint_t, (10, 34))

    meter_s = (
        f"{tr(language, 'career_meter')}: {odo_s}   |   "
        f"{tr(language, 'trip_meter')}: {trip_s}"
        if career_total_distance_m is None
        else f"{tr(language, 'career_meter')}: {career_total_distance_m / 1000.0:.1f} km   |   "
        f"{tr(language, 'trip_meter')}: {trip_s}"
    )
    meter_surface = font.render(meter_s, True, (255, 245, 190))
    meter_background = pygame.Surface((meter_surface.get_width() + 20, meter_surface.get_height() + 10), pygame.SRCALPHA)
    meter_background.fill((15, 20, 25, 210))
    meter_x, meter_y = layout["meters"]
    meter_rect = pygame.Rect(meter_x, meter_y, meter_background.get_width(), meter_background.get_height())
    if hud_rects is not None:
        hud_rects["meters"] = meter_rect
    screen.blit(meter_background, (meter_x, meter_y))
    screen.blit(meter_surface, (meter_x + 10, meter_y + 5))

    # Taxi mission banner / status bar
    if taxi_mgr:
        taxi_y = 58
        target = taxi_mgr.get_current_target()
        dist_m = math.hypot(car.x - target.x, car.y - target.y) if target else 0.0
        dist_s = f"{dist_m:.0f}m" if dist_m < 1000 else f"{dist_m / 1000.0:.2f}km"

        p = taxi_mgr.current_passenger
        if p is None:
            if taxi_mgr.offers:
                role_text = f"[TAXI] {tr(language, 'phone_available')}"
                role_color = (255, 95, 60)
            else:
                role_text = f"[TAXI] {tr(language, 'no_requests')}"
                role_color = (190, 200, 205)
        elif taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP:
            role_text = tr(language, "fare_pickup", name=p.name if p else tr(language, "client"), address=target.address if target else "...") + f" ({dist_s})"
            role_color = (255, 215, 60)
        else:
            cur_speed_kmh = (dist_m / max(1.0, taxi_mgr.elapsed_time)) * 3.6 if taxi_mgr.elapsed_time > 0 else 0.0
            role_text = (
                tr(language, "fare_dropoff", name=p.name if p else tr(language, "client"), address=target.address if target else "...")
                + f" ({dist_s}, {tr(language, 'elapsed_time')}: {taxi_mgr.elapsed_time:.1f}s)"
            )
            role_color = (100, 240, 140)

        # Draw taxi score and stats on top right
        score_text = f"{tr(language, 'score')}: {taxi_mgr.total_score} {tr(language, 'points')} | {tr(language, 'fares')}: {taxi_mgr.completed_fares}"
        score_surf = font.render(score_text, True, (255, 230, 110))
        score_rect = score_surf.get_rect(topright=(SCREEN_W - 140, 10))
        bg_s = pygame.Surface((score_rect.width + 12, score_rect.height + 6), pygame.SRCALPHA)
        bg_s.fill((20, 20, 20, 200))
        screen.blit(bg_s, (score_rect.x - 6, score_rect.y - 3))
        pygame.draw.rect(screen, (220, 180, 50), (score_rect.x - 6, score_rect.y - 3, score_rect.width + 12, score_rect.height + 6), 1, border_radius=3)
        screen.blit(score_surf, score_rect)

        fps_surf = font.render(f"FPS: {fps:.1f}", True, (170, 245, 180))
        fps_rect = fps_surf.get_rect(topright=(SCREEN_W - 10, score_rect.bottom + 8))
        fps_bg = pygame.Surface((fps_rect.width + 12, fps_rect.height + 6), pygame.SRCALPHA)
        fps_bg.fill((20, 30, 25, 220))
        screen.blit(fps_bg, (fps_rect.x - 6, fps_rect.y - 3))
        pygame.draw.rect(screen, (90, 180, 110), (fps_rect.x - 6, fps_rect.y - 3, fps_rect.width + 12, fps_rect.height + 6), 1, border_radius=3)
        screen.blit(fps_surf, fps_rect)

        # Mission header bar
        mission_surf = font.render(role_text, True, role_color)
        m_rect = mission_surf.get_rect(topleft=(10, taxi_y))
        m_bg = pygame.Surface((m_rect.width + 12, m_rect.height + 6), pygame.SRCALPHA)
        m_bg.fill((25, 30, 35, 220))
        screen.blit(m_bg, (m_rect.x - 6, m_rect.y - 3))
        pygame.draw.rect(screen, role_color, (m_rect.x - 6, m_rect.y - 3, m_rect.width + 12, m_rect.height + 6), 1, border_radius=3)
        screen.blit(mission_surf, m_rect)

        # In-game notification banner (e.g. Fare completed, new pickup)
        if taxi_mgr.notification_timer > 0.0 and taxi_mgr.notification_msg:
            notif_surf = font.render(taxi_mgr.notification_msg, True, (255, 255, 255))
            notif_rect = notif_surf.get_rect(center=(SCREEN_W // 2, SCREEN_H - 45))
            n_bg = pygame.Surface((notif_rect.width + 24, notif_rect.height + 12), pygame.SRCALPHA)
            n_bg.fill((20, 30, 40, 235))
            screen.blit(n_bg, (notif_rect.x - 12, notif_rect.y - 6))
            pygame.draw.rect(screen, (255, 200, 50), (notif_rect.x - 12, notif_rect.y - 6, notif_rect.width + 24, notif_rect.height + 12), 2, border_radius=5)
            screen.blit(notif_surf, notif_rect)

    # Keep the rage face and meter together in the lower-right corner.
    rage_text = font.render(f"{tr(language, 'rage_meter')}: {rage_power * 100:.0f}%", True, (255, 120, 100))
    rage_faces = _load_rage_face_frames(pygame)
    rage_face = None
    if rage_faces:
        rage_index = min(10, max(0, int(max(0.0, min(1.0, rage_power)) * 10.0)))
        rage_face = rage_faces[rage_index]
    face_width = rage_face.get_width() if rage_face else 0
    face_height = rage_face.get_height() if rage_face else 0
    instrument_width = max(rage_text.get_width(), face_width) + 20
    instrument_height = face_height + rage_text.get_height() + 24
    instrument_x, instrument_y = layout["rage"]
    rage_rect = pygame.Rect(instrument_x, instrument_y, instrument_width, instrument_height)
    if hud_rects is not None:
        hud_rects["rage"] = rage_rect
    pygame.draw.rect(
        screen,
        (20, 25, 30, 220),
        (instrument_x, instrument_y, instrument_width, instrument_height),
        border_radius=4,
    )
    pygame.draw.rect(
        screen,
        (130, 140, 150),
        (instrument_x, instrument_y, instrument_width, instrument_height),
        width=1,
        border_radius=4,
    )
    content_x = instrument_x + (instrument_width - face_width) // 2 if rage_face else instrument_x + 10
    if rage_face:
        screen.blit(rage_face, (content_x, instrument_y + 6))
    rage_y = instrument_y + face_height + 10
    screen.blit(rage_text, (instrument_x + 10, rage_y))
    rage_bar = pygame.Rect(instrument_x + 10, rage_y + rage_text.get_height() + 2, instrument_width - 20, 6)
    pygame.draw.rect(screen, (45, 30, 30), rage_bar)
    pygame.draw.rect(
        screen,
        (220, 55, 35),
        (rage_bar.x, rage_bar.y, int(rage_bar.width * max(0.0, min(1.0, rage_power))), rage_bar.height),
    )

    speedometer_rect = _draw_analog_speedometer(screen, car.speed, layout["speedometer"])
    if hud_rects is not None:
        hud_rects["speedometer"] = speedometer_rect

    reset_text = font.render("RESET UI", True, (245, 245, 245))
    reset_rect = reset_text.get_rect(topright=(screen_width - 10, 10)).inflate(18, 10)
    pygame.draw.rect(screen, (30, 35, 40), reset_rect, border_radius=3)
    pygame.draw.rect(screen, (190, 160, 80), reset_rect, width=1, border_radius=3)
    screen.blit(reset_text, reset_text.get_rect(center=reset_rect.center))
    if hud_rects is not None:
        hud_rects["reset"] = reset_rect

    # Auto-fetch scenery loading progress meter
    if is_auto_fetching:
        prog = max(0.0, min(1.0, auto_fetch_progress if auto_fetch_progress > 0.0 else 0.65))
        bar_w = 160
        bar_h = 14
        bar_x = 10
        bar_y = 86 if taxi_mgr else 58

        # Background and border
        pygame.draw.rect(screen, (30, 35, 40), (bar_x, bar_y, bar_w, bar_h), border_radius=3)
        pygame.draw.rect(screen, (140, 150, 160), (bar_x, bar_y, bar_w, bar_h), width=1, border_radius=3)

        # Progress fill
        fill_w = int((bar_w - 2) * prog)
        if fill_w > 0:
            pygame.draw.rect(screen, (255, 190, 40), (bar_x + 1, bar_y + 1, fill_w, bar_h - 2), border_radius=2)

        load_t = font.render(f"{tr(language, 'loading_scenery')} {int(prog * 100)}%", True, (255, 215, 60))
        screen.blit(load_t, (bar_x + bar_w + 10, bar_y - 2))

