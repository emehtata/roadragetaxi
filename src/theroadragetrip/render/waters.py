from . import common
from .common import (
    SCREEN_W,
    SCREEN_H,
    FPS,
    PX_PER_M,
    CACHE_PADDING_PX,
    STATIC_ZOOM_STEP,
    SOLAR_UPDATE_INTERVAL_SECONDS,
    GAME_DATE,
    FINLAND_SUMMER_TIME_OFFSET,
    DEFAULT_SUN_LATITUDE,
    DEFAULT_SUN_LONGITUDE,
    _solar_position_cache,
    _reusable_alpha_surfaces,
    _smoke_surface_cache,
    _render_logger,
    _pending_static_rebuilds,
    _static_rebuilds_this_frame,
    invalidate_static_caches,
    begin_static_cache_frame,
    _allow_static_rebuild,
    _blit_stale_static_cache,
    _static_cache_zoom,
    _reusable_alpha_surface,
    _smoke_surface,
    solar_altitude_and_events,
    _format_solar_time,
    _get_game_version,
    _draw_version,
    world_to_screen,
    asphalt_texture_tile_size,
    road_color_for_way,
    road_render_priority,
    get_viewport_bounds,
    minimum_px_per_m_for_viewport_width,
    _covered_by_higher_road,
    _vehicle_is_on_bridge,
    GAME_VERSION,
)
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


def draw_waters(
    screen,
    waters: List[Water],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
    profiler=None,
) -> None:
    """Draw cached static water geometry."""
    import pygame
    cache_zoom = _static_cache_zoom(px_per_m)

    frame_cache_key = (
        id(waters), len(waters), id(waters[-1]) if waters else None,
        id(spatial_grid), round(camx * cache_zoom / 128.0), round(camy * cache_zoom / 128.0),
        cache_zoom, screen.get_size(),
    )
    if frame_cache_key == common._water_frame_cache_key and common._water_frame_cache_surface is not None:
        cached_camx, cached_camy = common._water_frame_cache_camera
        screen.blit(
            common._water_frame_cache_surface,
            (
                round((cached_camx - camx) * cache_zoom) - CACHE_PADDING_PX,
                round((camy - cached_camy) * cache_zoom) - CACHE_PADDING_PX,
            ),
        )
        return
    if not _allow_static_rebuild("water", common._water_frame_cache_surface):
        _blit_stale_static_cache(screen, common._water_frame_cache_surface, common._water_frame_cache_camera, camx, camy, cache_zoom)
        return
    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2
    cache_surface = pygame.Surface((cache_width, cache_height), pygame.SRCALPHA)
    rebuild_started = time.perf_counter() if profiler is not None else 0.0
    _draw_waters_uncached(
        cache_surface, waters, camx, camy, cache_zoom, cache_width, cache_height, spatial_grid,
    )
    if profiler is not None:
        profiler.record("render:water_cache_rebuild", (time.perf_counter() - rebuild_started) * 1000.0)
    common._water_frame_cache_key = frame_cache_key
    common._water_frame_cache_surface = cache_surface
    common._water_frame_cache_camera = (camx, camy)
    screen.blit(cache_surface, (-CACHE_PADDING_PX, -CACHE_PADDING_PX))


def _draw_waters_uncached(
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
