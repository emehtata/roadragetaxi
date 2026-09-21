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
import time
import math
import random
from typing import List


from ..calendar import Season
from ..geo import clip_polygon_to_rect, point_in_polygon
from ..osm import Water


WATER_COLOR = (30, 100, 200)
WATER_EDGE_COLOR = (20, 80, 160)
WINTER_ICE_COLOR = (232, 240, 244)
WINTER_ICE_EDGE_COLOR = (185, 207, 218)
SPRING_ICE_COLORS = ((225, 236, 241), (205, 224, 232), (238, 243, 244))


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
    season: Season = Season.SUMMER,
) -> None:
    """Draw cached water, full winter ice, or spring water with ice floes."""
    import pygame
    cache_zoom = _static_cache_zoom(px_per_m)

    frame_cache_key = (
        id(waters), len(waters), id(waters[-1]) if waters else None,
        id(spatial_grid), *common._phased_cache_grid_cell("water", camx, camy, cache_zoom),
        cache_zoom, screen.get_size(), season,
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
    if _rebuild_or_stale(screen, "water", common._water_frame_cache_surface, common._water_frame_cache_camera, camx, camy, cache_zoom):
        return
    cache_width = screen_w + CACHE_PADDING_PX * 2
    cache_height = screen_h + CACHE_PADDING_PX * 2
    cache_surface = pygame.Surface((cache_width, cache_height), pygame.SRCALPHA)
    rebuild_started = time.perf_counter() if profiler is not None else 0.0
    _draw_waters_uncached(
        cache_surface, waters, camx, camy, cache_zoom, cache_width, cache_height, spatial_grid, season,
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
    season: Season = Season.SUMMER,
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
            fill_color = WINTER_ICE_COLOR if season == Season.WINTER else WATER_COLOR
            edge_color = WINTER_ICE_EDGE_COLOR if season == Season.WINTER else WATER_EDGE_COLOR
            pygame.draw.polygon(screen, fill_color, pts)
            pygame.draw.lines(screen, edge_color, True, pts, 1)
            if season == Season.SPRING:
                _draw_spring_ice_floes(
                    screen, w.points_m, camx, camy, px_per_m, screen_w, screen_h,
                    vminx, vminy, vmaxx, vmaxy,
                )
        else:
            if len(w.points_m) >= 2:
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]
                color = WINTER_ICE_COLOR if season == Season.WINTER else WATER_COLOR
                pygame.draw.lines(screen, color, False, pts, max(2, int(3 * px_per_m)))
                if season == Season.SPRING:
                    _draw_spring_stream_ice(screen, pts, px_per_m)


def _draw_spring_ice_floes(
    screen, polygon, camx, camy, px_per_m, screen_w, screen_h,
    vminx, vminy, vmaxx, vmaxy,
) -> None:
    """Draw sparse position-seeded ice plates without per-frame movement."""
    import pygame

    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    minx, maxx = max(min(xs), vminx), min(max(xs), vmaxx)
    miny, maxy = max(min(ys), vminy), min(max(ys), vmaxy)
    if minx >= maxx or miny >= maxy:
        return
    spacing = 24.0
    start_x = math.floor(minx / spacing)
    end_x = math.ceil(maxx / spacing)
    start_y = math.floor(miny / spacing)
    end_y = math.ceil(maxy / spacing)
    for grid_x in range(start_x, end_x + 1):
        for grid_y in range(start_y, end_y + 1):
            seed = (grid_x * 73856093) ^ (grid_y * 19349663)
            rng = random.Random(seed)
            # Only some cells contain residual ice: spring water remains
            # visibly open rather than looking frozen like winter.
            if rng.random() > 0.34:
                continue
            world_x = (grid_x + 0.15 + rng.random() * 0.7) * spacing
            world_y = (grid_y + 0.15 + rng.random() * 0.7) * spacing
            if not point_in_polygon(world_x, world_y, polygon):
                continue
            sx, sy = world_to_screen(world_x, world_y, camx, camy, px_per_m, screen_w, screen_h)
            radius_x = max(2, round(rng.uniform(1.3, 3.2) * px_per_m))
            radius_y = max(1, round(rng.uniform(0.7, 1.8) * px_per_m))
            floe = pygame.Rect(sx - radius_x, sy - radius_y, radius_x * 2, radius_y * 2)
            pygame.draw.ellipse(screen, rng.choice(SPRING_ICE_COLORS), floe)
            pygame.draw.ellipse(screen, WINTER_ICE_EDGE_COLOR, floe, 1)


def _draw_spring_stream_ice(screen, points, px_per_m) -> None:
    """Add occasional small ice plates to narrow linear waterways."""
    import pygame

    for index, ((ax, ay), (bx, by)) in enumerate(zip(points, points[1:])):
        if index % 3:
            continue
        cx, cy = (ax + bx) // 2, (ay + by) // 2
        radius = max(2, round(0.8 * px_per_m))
        pygame.draw.circle(screen, SPRING_ICE_COLORS[index % len(SPRING_ICE_COLORS)], (cx, cy), radius)
