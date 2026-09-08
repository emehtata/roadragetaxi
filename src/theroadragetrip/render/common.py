import math
import logging
import os
import random
import subprocess
import time
from datetime import date
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import List, Optional, Tuple

from shapely.geometry import LineString
from shapely.ops import unary_union

from ..geo import clip_polygon_to_rect, compute_bbox, dist_point_to_segment, meters_to_latlon, point_in_polygon
from ..osm import Building, BusStop, Place, Scenery, TaxiStop, Water, Way
from ..physics import Car, MAX_SPEED, is_point_on_road
from ..taxi import TaxiManager, TaxiState
from ..localization import tr


SCREEN_W, SCREEN_H = 1280, 720
FPS = 60
PX_PER_M = 0.7
CACHE_PADDING_PX = 96
STATIC_ZOOM_STEP = 0.05
SOLAR_UPDATE_INTERVAL_SECONDS = 15.0 * 60.0
GAME_DATE = date(2026, 8, 31)
FINLAND_SUMMER_TIME_OFFSET = 3.0
DEFAULT_SUN_LATITUDE = 65.012
DEFAULT_SUN_LONGITUDE = 25.468
_street_light_frame_world_positions = []
_solar_position_cache = {}
_reusable_alpha_surfaces = {}
_smoke_surface_cache = {}
_label_frame_cache_key = None
_label_frame_cache_surface = None
_label_frame_cache_camera = None
_building_frame_cache_key = None
_building_frame_cache_surface = None
_building_frame_cache_camera = None
_scenery_frame_cache_key = None
_scenery_frame_cache_surface = None
_scenery_frame_cache_camera = None
_water_frame_cache_key = None
_water_frame_cache_surface = None
_water_frame_cache_camera = None
_road_frame_cache_key = None
_road_frame_cache_surface = None
_road_frame_cache_camera = None
# The grass background doesn't depend on any streamed world data (it's a
# fixed tile pattern positioned purely by camera/zoom), so unlike the other
# five layers it never needs invalidate_static_caches() - it only goes stale
# when the camera moves past its padding or the zoom changes, exactly like
# CACHE_PADDING_PX already does for the others.
_grass_frame_cache_key = None
_grass_frame_cache_surface = None
_grass_frame_cache_camera = None
_render_logger = logging.getLogger(__name__)
_pending_static_rebuilds = set()
_static_rebuilds_this_frame = 0


def invalidate_static_caches() -> None:
    """Discard viewport surfaces after streamed world data changes."""
    global _label_frame_cache_key, _building_frame_cache_key
    global _scenery_frame_cache_key, _water_frame_cache_key, _road_frame_cache_key
    _label_frame_cache_key = None
    _building_frame_cache_key = None
    _scenery_frame_cache_key = None
    _water_frame_cache_key = None
    _road_frame_cache_key = None
    _pending_static_rebuilds.update({"labels", "buildings", "scenery", "water", "roads"})


def begin_static_cache_frame() -> None:
    global _static_rebuilds_this_frame
    _static_rebuilds_this_frame = 0


def _allow_static_rebuild(layer: str, surface) -> bool:
    global _static_rebuilds_this_frame
    if surface is None or layer not in _pending_static_rebuilds:
        return True
    if _static_rebuilds_this_frame >= 1:
        return False
    _static_rebuilds_this_frame += 1
    _pending_static_rebuilds.discard(layer)
    return True


def _blit_stale_static_cache(screen, surface, camera, camx, camy, cache_zoom) -> None:
    cached_camx, cached_camy = camera
    screen.blit(
        surface,
        (
            round((cached_camx - camx) * cache_zoom) - CACHE_PADDING_PX,
            round((camy - cached_camy) * cache_zoom) - CACHE_PADDING_PX,
        ),
    )


def _static_cache_zoom(px_per_m: float) -> float:
    """Quantize static-layer zoom to avoid rebuilding during smooth zoom animation."""
    return max(STATIC_ZOOM_STEP, round(px_per_m / STATIC_ZOOM_STEP) * STATIC_ZOOM_STEP)


def _reusable_alpha_surface(pygame, key, size):
    surface = _reusable_alpha_surfaces.get(key)
    if surface is None or surface.get_size() != size:
        surface = pygame.Surface(size, pygame.SRCALPHA)
        _reusable_alpha_surfaces[key] = surface
    else:
        surface.fill((0, 0, 0, 0))
    return surface


def _smoke_surface(pygame, radius: int, alpha: int):
    key = (radius, alpha)
    surface = _smoke_surface_cache.get(key)
    if surface is None:
        surface = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(surface, (180, 180, 180, alpha), (radius + 1, radius + 1), radius)
        _smoke_surface_cache[key] = surface
    return surface


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


def _get_game_version() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
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
        return "v0.9.0alpha"


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


def minimum_px_per_m_for_viewport_width(
    max_width_m: float = 500.0,
    screen_w: int = SCREEN_W,
    margin_m: float = 30.0,
) -> float:
    """Return the minimum zoom that keeps the viewport width within its limit."""
    drawable_width_m = max(1.0, max_width_m - 2.0 * margin_m)
    return screen_w / drawable_width_m


def _covered_by_higher_road(
    x: float,
    y: float,
    layer: int,
    ways: Optional[List[Way]],
    spatial_grid=None,
    active_way=None,
) -> bool:
    if spatial_grid is not None:
        candidates = (way for way, _ in spatial_grid._candidate_ways(x, y))
    else:
        candidates = ways or []
    if not ways and spatial_grid is None:
        return False
    for way in candidates:
        if getattr(way, "layer", 0) <= layer or len(way.points_m) < 2:
            continue
        if (
            active_way is not None
            and getattr(active_way, "name", None)
            and getattr(way, "name", None) == getattr(active_way, "name", None)
        ):
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


GAME_VERSION = _get_game_version()
