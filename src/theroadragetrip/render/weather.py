import math
import random
from typing import List, Optional

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

# Puddles: at most one deterministic candidate spot per way, so the count
# scales with the number of visible roads, not with rain duration or map
# size. PUDDLE_CHANCE_PER_WAY keeps it from looking like literally every
# road segment grows a puddle. There's no elevation/flatness data in this
# game's road model (Way has no z-height), so "low/flat area" placement
# (WEATHER_RAIN.md #4) isn't modeled - positions are otherwise randomized
# per-way instead.
PUDDLE_CHANCE_PER_WAY = 0.4
PUDDLE_MIN_RADIUS_M = 0.6
PUDDLE_MAX_RADIUS_M = 2.2
# Each candidate only starts showing once wetness passes its own
# threshold in this range, and grows to full strength by wetness == 1.0 -
# spreads puddles out so they visibly appear one by one as rain continues
# rather than all popping in together the moment it starts raining.
PUDDLE_REVEAL_WETNESS_MIN = 0.2
PUDDLE_REVEAL_WETNESS_MAX = 0.75
PUDDLE_COLOR = (32, 40, 54)
PUDDLE_MAX_ALPHA = 150
PUDDLE_SHAPE_POINTS = 7
PUDDLE_SHAPE_JITTER = 0.35  # +/- fraction of radius per vertex - an irregular outline, not a perfect circle

# id(way) -> puddle spec dict, or None if this way has no puddle candidate.
# Computed once per way and never recomputed, so puddles stay put rather
# than jittering to a new random spot every frame (WEATHER_RAIN.md #4).
_puddle_cache: dict = {}


def _puddle_for_way(way: Way) -> Optional[dict]:
    key = id(way)
    if key in _puddle_cache:
        return _puddle_cache[key]

    points = way.points_m
    # Seed from osm_id (stable map data) rather than id(way) (a memory
    # address, which - unlike the way this identity is used as the cache
    # key above, purely for this-session memoization - would make the
    # puddle reroll if the same road's Way object were ever recreated,
    # e.g. across a reload) when available, falling back to id(way) for
    # synthetic ways that have none.
    rng = random.Random(getattr(way, "osm_id", None) if getattr(way, "osm_id", None) is not None else key)
    spot = None
    if len(points) >= 2 and rng.random() <= PUDDLE_CHANCE_PER_WAY:
        segment_index = rng.randrange(len(points) - 1)
        ax, ay = points[segment_index]
        bx, by = points[segment_index + 1]
        t = rng.uniform(0.2, 0.8)
        seg_dx, seg_dy = bx - ax, by - ay
        seg_len = math.hypot(seg_dx, seg_dy) or 1.0
        half_width = getattr(way, "half_width_m", 3.0)
        # Offset laterally off the centerline so the puddle sits inside
        # the road surface rather than always dead-center on the line.
        perp_x, perp_y = -seg_dy / seg_len, seg_dx / seg_len
        lateral = rng.uniform(-0.5, 0.5) * half_width * 0.6
        spot = {
            "x": ax + seg_dx * t + perp_x * lateral,
            "y": ay + seg_dy * t + perp_y * lateral,
            "radius_m": rng.uniform(PUDDLE_MIN_RADIUS_M, min(PUDDLE_MAX_RADIUS_M, half_width * 0.9)),
            "reveal_wetness": rng.uniform(PUDDLE_REVEAL_WETNESS_MIN, PUDDLE_REVEAL_WETNESS_MAX),
            "shape": [1.0 + rng.uniform(-PUDDLE_SHAPE_JITTER, PUDDLE_SHAPE_JITTER) for _ in range(PUDDLE_SHAPE_POINTS)],
            "ripple_phase": rng.random(),  # not yet animated - reserved for the puddle-ripple step
        }
    _puddle_cache[key] = spot
    return spot


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


def _visible_drivable_ways(ways: List[Way], vminx, vminy, vmaxx, vmaxy, spatial_grid=None) -> List[Way]:
    """Shared viewport culling for the weather-on-roads effects below (wet
    tint, puddles) - same approach draw_ways/render/roads.py uses,
    duplicated here rather than factored out of that already FPS-tuned
    function (WEATHER_RAIN.md #11: cost must scale with the visible area,
    not the full ways list)."""
    if spatial_grid is not None:
        return [
            w for w in spatial_grid.ways_in_rect(vminx, vminy, vmaxx, vmaxy)
            if len(w.points_m) >= 2 and getattr(w, "is_drivable", True)
        ]
    visible_ways = []
    for w in ways:
        if not getattr(w, "is_drivable", True) or len(w.points_m) < 2:
            continue
        bbox = getattr(w, "bbox", None)
        if bbox and bbox != (0.0, 0.0, 0.0, 0.0):
            if bbox[2] < vminx or bbox[0] > vmaxx or bbox[3] < vminy or bbox[1] > vmaxy:
                continue
        visible_ways.append(w)
    return visible_ways


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

    No-ops entirely while the road is dry.
    """
    if weather.wetness <= 0.0 or not ways:
        return
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    visible_ways = _visible_drivable_ways(ways, vminx, vminy, vmaxx, vmaxy, spatial_grid)
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


def draw_puddles(
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
    """Draw puddles that gradually appear on visible roads as wetness rises,
    and fade out as it falls - each puddle's position/size/shape is fixed
    once computed (see _puddle_for_way), only its visible strength changes
    frame to frame, so puddles never relocate or reroll (WEATHER_RAIN.md #4).

    Same live-per-frame, viewport-culled approach as draw_wet_roads, for
    the same reasons (continuous wetness doesn't fit the static road
    cache; cost must scale with the visible area, not the full map).
    """
    if weather.wetness <= 0.0 or not ways:
        return
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 30.0)
    visible_ways = _visible_drivable_ways(ways, vminx, vminy, vmaxx, vmaxy, spatial_grid)
    if not visible_ways:
        return

    overlay = _reusable_alpha_surface(pygame, "puddles", (screen_w, screen_h))
    drew_any = False
    for way in visible_ways:
        spot = _puddle_for_way(way)
        if spot is None:
            continue
        strength = (weather.wetness - spot["reveal_wetness"]) / (1.0 - spot["reveal_wetness"])
        if strength <= 0.0:
            continue
        strength = min(1.0, strength)
        alpha = round(PUDDLE_MAX_ALPHA * strength)
        if alpha <= 0:
            continue
        center_x, center_y = world_to_screen(spot["x"], spot["y"], camx, camy, px_per_m, screen_w, screen_h)
        # Grows in as it strengthens rather than popping in at full size.
        radius_px = spot["radius_m"] * px_per_m * (0.4 + 0.6 * strength)
        if radius_px < 1.0:
            continue
        vertex_count = len(spot["shape"])
        polygon = [
            (
                center_x + math.cos(2.0 * math.pi * i / vertex_count) * radius_px * jitter,
                center_y + math.sin(2.0 * math.pi * i / vertex_count) * radius_px * jitter,
            )
            for i, jitter in enumerate(spot["shape"])
        ]
        pygame.draw.polygon(overlay, (*PUDDLE_COLOR, alpha), polygon)
        drew_any = True
    if drew_any:
        screen.blit(overlay, (0, 0))
