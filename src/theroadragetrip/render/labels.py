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


DISTRICT_PLACE_KINDS = {
    "suburb", "neighbourhood", "quarter", "village", "town", "city", "hamlet",
}
_label_surface_cache = {}


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
    profiler=None,
) -> None:
    """Draw cached map labels with decluttering and collision avoidance."""
    import pygame
    cache_zoom = _static_cache_zoom(px_per_m)

    frame_cache_key = (
        id(font),
        id(ways),
        len(ways),
        id(waters),
        len(waters),
        id(buildings),
        len(buildings),
        id(sceneries),
        len(sceneries),
        id(places),
        len(places),
        id(spatial_grid),
        id(scenery_grid),
        id(building_grid),
        round(camx * cache_zoom / 128.0),
        round(camy * cache_zoom / 128.0),
        cache_zoom,
        max_labels,
        label_mode,
        screen.get_size(),
    )
    if frame_cache_key == common._label_frame_cache_key and common._label_frame_cache_surface is not None:
        cached_camx, cached_camy = common._label_frame_cache_camera
        offset_x = round((cached_camx - camx) * cache_zoom) - CACHE_PADDING_PX
        offset_y = round((camy - cached_camy) * cache_zoom) - CACHE_PADDING_PX
        screen.blit(common._label_frame_cache_surface, (offset_x, offset_y))
        return

    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2
    cache_surface = pygame.Surface((cache_width, cache_height), pygame.SRCALPHA)
    rebuild_started = time.perf_counter() if profiler is not None else 0.0
    _draw_labels_uncached(
        cache_surface,
        font,
        ways,
        waters,
        buildings,
        sceneries,
        places,
        camx,
        camy,
        cache_zoom,
        cache_width,
        cache_height,
        max_labels,
        spatial_grid,
        scenery_grid,
        building_grid,
        label_mode,
    )
    if profiler is not None:
        profiler.record("render:labels_cache_rebuild", (time.perf_counter() - rebuild_started) * 1000.0)
    common._label_frame_cache_key = frame_cache_key
    common._label_frame_cache_surface = cache_surface
    common._label_frame_cache_camera = (camx, camy)
    screen.blit(cache_surface, (-CACHE_PADDING_PX, -CACHE_PADDING_PX))


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
        building_font = pygame.font.SysFont(None, 24, bold=True)
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
        cache_key = (id(f), text, tuple(text_color), tuple(bg_color), border_color)
        label_surface = _label_surface_cache.get(cache_key)
        if label_surface is None:
            text_surface = f.render(text, True, text_color)
            label_surface = pygame.Surface(
                (text_surface.get_width() + 10, text_surface.get_height() + 6),
                pygame.SRCALPHA,
            )
            label_surface.fill(bg_color)
            if border_color:
                pygame.draw.rect(
                    label_surface,
                    border_color,
                    label_surface.get_rect(),
                    width=1,
                    border_radius=3,
                )
            label_surface.blit(text_surface, (5, 3))
            _label_surface_cache[cache_key] = label_surface
        bg_rect = label_surface.get_rect(center=(sx, sy))

        # Check collision with already placed labels
        for pr in placed_rects:
            if bg_rect.colliderect(pr):
                return False

        placed_rects.append(bg_rect)
        screen.blit(label_surface, bg_rect.topleft)
        count += 1
        return True

    if label_mode >= 2:
        # 1. Kaupunginosat / Districts & Suburbs (high prominence, warm gold/amber)
        for p in places:
            if count >= max_labels:
                break
            name = getattr(p, "name", None)
            if name and getattr(p, "kind", None) in DISTRICT_PLACE_KINDS and name not in seen_names:
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
