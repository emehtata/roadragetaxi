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
from typing import List


from ..geo import clip_polygon_to_rect
from ..osm import Water


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
    if _rebuild_or_stale(screen, "water", common._water_frame_cache_surface, common._water_frame_cache_camera, camx, camy, cache_zoom):
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
