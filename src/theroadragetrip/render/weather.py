import math

from .common import SCREEN_W, SCREEN_H

from ..weather import RAIN_DRIFT_FRACTION_PER_S, RAIN_FALL_FRACTION_PER_S, RAIN_SPEED_VARIATION, WeatherSystem

RAIN_COLOR = (196, 206, 222)
RAIN_STREAK_LEN_MIN_PX = 9.0
RAIN_STREAK_LEN_MAX_PX = 20.0


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
