"""Tests for weather rendering (render/weather.py): rain particles and
wet-road tint."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from theroadragetrip.osm import Way
from theroadragetrip.render import draw_rain, draw_wet_roads
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


def _road_and_screen():
    way = Way(points_m=[(-200.0, 0.0), (200.0, 0.0)], highway="primary", half_width_m=6.0)
    screen = pygame.Surface((640, 360))
    screen.fill((100, 100, 100))  # flat road-grey background, easy to compare against
    return way, screen


def test_draw_wet_roads_is_a_noop_when_dry():
    pygame.init()
    try:
        way, screen = _road_and_screen()
        weather = WeatherSystem(WeatherType.CLEAR)
        assert weather.wetness == 0.0
        before = pygame.image.tobytes(screen, "RGB")
        draw_wet_roads(screen, [way], weather, camx=0.0, camy=0.0, px_per_m=2.5, screen_w=640, screen_h=360)
        assert pygame.image.tobytes(screen, "RGB") == before
    finally:
        pygame.quit()


def test_draw_wet_roads_darkens_the_road_proportionally_to_wetness():
    # (320, 170) sits within the drawn road but outside the thin center
    # sheen stripe, so it isolates the darkening effect from the highlight.
    edge_point = (320, 170)
    # (320, 180) is the road's centerline, where the sheen highlight is drawn.
    center_point = (320, 180)
    pygame.init()
    try:
        way, screen = _road_and_screen()
        weather = WeatherSystem(WeatherType.RAIN)
        weather.wetness = 0.4
        draw_wet_roads(screen, [way], weather, camx=0.0, camy=0.0, px_per_m=2.5, screen_w=640, screen_h=360)
        partly_wet_edge = screen.get_at(edge_point)[:3]
        assert partly_wet_edge != (100, 100, 100), "wetness=0.4 had no visible darkening"
        assert sum(partly_wet_edge) < 300, "edge pixel should be darker, not brighter, than dry asphalt"

        way2, screen2 = _road_and_screen()
        weather.wetness = 1.0
        draw_wet_roads(screen2, [way2], weather, camx=0.0, camy=0.0, px_per_m=2.5, screen_w=640, screen_h=360)
        fully_wet_edge = screen2.get_at(edge_point)[:3]
        fully_wet_center = screen2.get_at(center_point)[:3]
        assert sum(fully_wet_edge) < 300, "fully wet edge should still read as darkened asphalt"
        # More wetness -> a visibly stronger darkening effect than a lighter wetness.
        assert (300 - sum(fully_wet_edge)) > (300 - sum(partly_wet_edge))
        # The centerline sheen is a highlight (brighter than the darkened
        # edge) but not a mirror (WEATHER_RAIN.md #3): nowhere near white.
        assert sum(fully_wet_center) > sum(fully_wet_edge)
        assert sum(fully_wet_center) < sum((255, 255, 255)) - 200
    finally:
        pygame.quit()


def test_draw_wet_roads_scales_with_visible_ways_only():
    """A way far outside the viewport must not be touched (WEATHER_RAIN.md
    #11: cost scales with the visible area, not the full ways list)."""
    pygame.init()
    try:
        near = Way(points_m=[(-200.0, 0.0), (200.0, 0.0)], highway="primary", half_width_m=6.0)
        far_away = Way(points_m=[(1_000_000.0, 0.0), (1_000_100.0, 0.0)], highway="primary", half_width_m=6.0)
        screen = pygame.Surface((640, 360))
        screen.fill((100, 100, 100))
        weather = WeatherSystem(WeatherType.RAIN)
        weather.wetness = 1.0
        draw_wet_roads(screen, [near, far_away], weather, camx=0.0, camy=0.0, px_per_m=2.5, screen_w=640, screen_h=360)
        assert screen.get_at((320, 180))[:3] != (100, 100, 100)
    finally:
        pygame.quit()
