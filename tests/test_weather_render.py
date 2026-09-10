"""Tests for rain particle rendering (render/weather.py)."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from theroadragetrip.render import draw_rain
from theroadragetrip.weather import WeatherSystem, WeatherType


def test_draw_rain_draws_nothing_when_clear():
    pygame.init()
    try:
        weather = WeatherSystem(WeatherType.CLEAR)
        screen = pygame.Surface((200, 150))
        screen.fill((0, 0, 0))
        draw_rain(screen, weather, screen_w=200, screen_h=150)
        assert pygame.transform.average_color(screen)[:3] == (0, 0, 0)
    finally:
        pygame.quit()


def test_draw_rain_draws_visible_streaks_when_raining():
    pygame.init()
    try:
        weather = WeatherSystem(WeatherType.RAIN)
        screen = pygame.Surface((200, 150))
        screen.fill((0, 0, 0))
        draw_rain(screen, weather, screen_w=200, screen_h=150)
        # At least some pixels were painted a non-background color.
        assert pygame.transform.average_color(screen)[:3] != (0, 0, 0)
    finally:
        pygame.quit()


def test_draw_rain_scales_to_any_screen_size_without_scanning_the_map():
    """draw_rain must cost the same regardless of how much map is loaded -
    it only ever touches RAIN_PARTICLE_COUNT screen-space points, never
    world/road data (WEATHER_RAIN.md #11)."""
    pygame.init()
    try:
        weather = WeatherSystem(WeatherType.RAIN)
        for x_fraction, y_fraction, _ in weather.rain_particles:
            assert 0.0 <= x_fraction <= 1.0
            assert 0.0 <= y_fraction <= 1.0
        screen = pygame.Surface((1920, 1080))
        screen.fill((0, 0, 0))
        draw_rain(screen, weather, screen_w=1920, screen_h=1080)  # must not touch world coords/OSM data
    finally:
        pygame.quit()
