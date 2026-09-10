import math
from typing import List

from .common import PX_PER_M, SCREEN_W, SCREEN_H, _reusable_alpha_surface, get_viewport_bounds, world_to_screen

from ..osm import Way
from ..weather import RAIN_DRIFT_FRACTION_PER_S, RAIN_FALL_FRACTION_PER_S, RAIN_SPEED_VARIATION, WeatherSystem

RAIN_COLOR = (196, 206, 222)
RAIN_STREAK_LEN_MIN_PX = 9.0
RAIN_STREAK_LEN_MAX_PX = 20.0

# Wet-road tint: a translucent dark fill over the road plus a thin, fainter
# sheen line - subtle by design (WEATHER_RAIN.md #3: "do not make the road
# look like a mirror"). Alpha values are the max, reached only at
# wetness == 1.0; scaled down linearly below that.
WET_ROAD_DARKEN_COLOR = (8, 10, 14)
WET_ROAD_DARKEN_MAX_ALPHA = 90
WET_ROAD_SHEEN_COLOR = (205, 215, 230)
WET_ROAD_SHEEN_MAX_ALPHA = 55
WET_ROAD_SHEEN_MIN_WETNESS = 0.15  # no sheen at all below this - just darkening


def draw_rain(screen, weather: WeatherSystem, screen_w: int = SCREEN_W, screen_h: int = SCREEN_H) -> None:
    """Draw the rain particle pool as short falling streaks, in screen space.

    Screen-space and camera-independent by design (WEATHER_RAIN.md #2):
    positions come from weather.rain_particles as screen fractions, not
    world coordinates, so this never touches the OSM/road data and its
    cost is exactly RAIN_PARTICLE_COUNT line draws regardless of map size
    or camera position.
    """
    if not weather.is_precipitating or not weather.rain_particles:
        return
    import pygame

    # Pixel-space fall direction (screen fraction rates scaled by the
    # actual screen size, since width/height differ - a naive fraction
    # ratio would streak at the wrong visual angle on a non-square screen).
    dx_px = RAIN_DRIFT_FRACTION_PER_S * screen_w
    dy_px = RAIN_FALL_FRACTION_PER_S * screen_h
    direction_len = math.hypot(dx_px, dy_px) or 1.0
    unit_x, unit_y = dx_px / direction_len, dy_px / direction_len

    speed_lo, speed_hi = RAIN_SPEED_VARIATION
    speed_span = (speed_hi - speed_lo) or 1.0
    length_span = RAIN_STREAK_LEN_MAX_PX - RAIN_STREAK_LEN_MIN_PX

    for x_fraction, y_fraction, speed_factor in weather.rain_particles:
        head_x = x_fraction * screen_w
        head_y = y_fraction * screen_h
        length = RAIN_STREAK_LEN_MIN_PX + length_span * (speed_factor - speed_lo) / speed_span
        tail_x = head_x - unit_x * length
        tail_y = head_y - unit_y * length
        pygame.draw.line(screen, RAIN_COLOR, (tail_x, tail_y), (head_x, head_y), 1)


def draw_wet_roads(
    screen,
    ways: List[Way],
    weather: WeatherSystem,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    spatial_grid=None,
) -> None:
    """Darken visible road surfaces and add a faint sheen, scaled by
    weather.wetness.

    Drawn live every frame rather than folded into render/roads.py's
    static road cache: that cache's key is purely camera/zoom/streamed-
    data dependent (see render/common.py's _allow_static_rebuild), and
    wetness changes continuously and independently of all of those -
    adding it to the cache key would force a rebuild every time wetness
    ticks, defeating the whole point of that cache's rebuild throttle.

    Cost scales with the visible viewport (same spatial-grid/bbox culling
    draw_ways uses - duplicated here rather than factored out, to avoid
    touching that already FPS-tuned function), never the full ways list
    (WEATHER_RAIN.md #11). No-ops entirely while the road is dry.
    """
    if weather.wetness <= 0.0 or not ways:
        return
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    if spatial_grid is not None:
        visible_ways = [
            w for w in spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
            if len(w.points_m) >= 2 and getattr(w, "is_drivable", True)
        ]
    else:
        visible_ways = []
        for w in ways:
            if not getattr(w, "is_drivable", True) or len(w.points_m) < 2:
                continue
            bbox = getattr(w, "bbox", None)
            if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
                if bbox[2] < vminx or bbox[0] > vmaxx or bbox[3] < vminy or bbox[1] > vmaxy:
                    continue
            visible_ways.append(w)
    if not visible_ways:
        return

    darken_alpha = round(WET_ROAD_DARKEN_MAX_ALPHA * weather.wetness)
    sheen_wetness = max(0.0, weather.wetness - WET_ROAD_SHEEN_MIN_WETNESS) / (1.0 - WET_ROAD_SHEEN_MIN_WETNESS)
    sheen_alpha = round(WET_ROAD_SHEEN_MAX_ALPHA * sheen_wetness)

    overlay = _reusable_alpha_surface(pygame, "wet_roads", (screen_w, screen_h))
    for way in visible_ways:
        points = [
            world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h)
            for x, y in way.points_m
        ]
        thickness = max(1, round(way.half_width_m * 2 * px_per_m))
        if darken_alpha > 0:
            pygame.draw.lines(overlay, (*WET_ROAD_DARKEN_COLOR, darken_alpha), False, points, thickness)
        if sheen_alpha > 0:
            pygame.draw.lines(overlay, (*WET_ROAD_SHEEN_COLOR, sheen_alpha), False, points, max(1, thickness // 5))
    screen.blit(overlay, (0, 0))
