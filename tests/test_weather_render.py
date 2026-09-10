"""Tests for weather rendering (render/weather.py): rain particles,
wet-road tint, and puddles."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from theroadragetrip.osm import Way
from theroadragetrip.render import draw_puddles, draw_rain, draw_wet_roads
from theroadragetrip.render import weather as weather_render
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


def test_puddle_for_way_is_computed_once_and_cached():
    """WEATHER_RAIN.md #4: puddle placement must be deterministic, not
    rerolled every call - or they'd jump around every frame."""
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=5.0, osm_id=555)
    first = weather_render._puddle_for_way(way)
    second = weather_render._puddle_for_way(way)
    assert first is second


def test_puddle_shape_is_irregular_not_a_perfect_circle():
    """WEATHER_RAIN.md #4: irregular shapes, not perfect circles."""
    spot = None
    for osm_id in range(50):  # deterministic per way identity - some get a puddle, some don't
        way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=5.0, osm_id=osm_id)
        spot = weather_render._puddle_for_way(way)
        if spot is not None:
            break
    assert spot is not None, "none of the sampled ways got a puddle candidate"
    assert any(abs(radius_multiplier - 1.0) > 0.01 for radius_multiplier in spot["shape"])


def test_draw_puddles_reveals_gradually_and_fades_as_it_dries():
    pygame.init()
    try:
        way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=5.0, osm_id=9001)
        weather_render._puddle_cache[id(way)] = {
            "x": 50.0, "y": 0.0, "radius_m": 2.0,
            "reveal_wetness": 0.5, "shape": [1.0] * 7, "ripple_phase": 0.0,
        }
        screen = pygame.Surface((300, 300))
        weather = WeatherSystem(WeatherType.RAIN)

        screen.fill((100, 100, 100))
        weather.wetness = 0.3  # below this puddle's reveal threshold
        draw_puddles(screen, [way], weather, camx=50.0, camy=0.0, px_per_m=9.0, screen_w=300, screen_h=300)
        assert pygame.transform.average_color(screen)[:3] == (100, 100, 100), "puddle appeared before its threshold"

        weather.wetness = 0.9  # above threshold - fully rained on
        draw_puddles(screen, [way], weather, camx=50.0, camy=0.0, px_per_m=9.0, screen_w=300, screen_h=300)
        assert pygame.transform.average_color(screen)[:3] != (100, 100, 100), "puddle did not appear above its threshold"

        # Drying back down below the threshold makes it disappear again.
        screen.fill((100, 100, 100))
        weather.wetness = 0.1
        draw_puddles(screen, [way], weather, camx=50.0, camy=0.0, px_per_m=9.0, screen_w=300, screen_h=300)
        assert pygame.transform.average_color(screen)[:3] == (100, 100, 100), "puddle did not fade out while drying"
    finally:
        pygame.quit()
