"""Tests for weather rendering (render/weather.py): rain particles,
wet-road tint, and puddles."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from theroadragetrip.osm import Way
from theroadragetrip.render import draw_puddles, draw_rain, draw_splashes, draw_wet_roads, find_puddle_overlap
from theroadragetrip.render import weather as weather_render
from theroadragetrip.weather import SPLASH_LIFETIME_S, WeatherSystem, WeatherType


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
    # (320, 170) and (320, 180) are both within the drawn road's full width
    # (half_width_m=6.0 @ px_per_m=2.5 -> 15px either side of the y=180
    # centerline) - the darken+sheen overlay now covers the whole road, not
    # just a thin centerline stripe, so both points should look the same.
    edge_point = (320, 170)
    center_point = (320, 180)
    pygame.init()
    try:
        way, screen = _road_and_screen()
        weather = WeatherSystem(WeatherType.RAIN)
        weather.wetness = 0.4
        draw_wet_roads(screen, [way], weather, camx=0.0, camy=0.0, px_per_m=2.5, screen_w=640, screen_h=360)
        partly_wet_edge = screen.get_at(edge_point)[:3]
        assert partly_wet_edge != (100, 100, 100), "wetness=0.4 had no visible change"

        way2, screen2 = _road_and_screen()
        weather.wetness = 1.0
        draw_wet_roads(screen2, [way2], weather, camx=0.0, camy=0.0, px_per_m=2.5, screen_w=640, screen_h=360)
        fully_wet_edge = screen2.get_at(edge_point)[:3]
        fully_wet_center = screen2.get_at(center_point)[:3]
        # No more distinct centerline highlight - the whole road reads as
        # one uniformly wet surface, not a light "dry" stripe down the
        # middle of a lane.
        assert fully_wet_edge == fully_wet_center
        # Regression: the sheen pass used to be drawn onto the same
        # SRCALPHA overlay surface as the darken pass, which *replaces*
        # pixels rather than blending with them - once the sheen covered
        # the full road width it silently wiped out the darkening
        # everywhere, leaving a road that never visibly got darker in the
        # rain despite puddles still showing. Must still read as clearly
        # darker than the dry (100, 100, 100) background.
        assert sum(fully_wet_edge) < 250, "fully wet road should read as clearly darker than dry asphalt"
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


def _way_with_known_puddle(osm_id=9002, reveal_wetness=0.3):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="residential", half_width_m=5.0, osm_id=osm_id)
    weather_render._puddle_cache[id(way)] = {
        "x": 50.0, "y": 0.0, "radius_m": 2.0,
        "reveal_wetness": reveal_wetness, "shape": [1.0] * 7, "ripple_phase": 0.0,
    }
    return way


def test_find_puddle_overlap_requires_actual_distance_overlap():
    way = _way_with_known_puddle()
    weather = WeatherSystem(WeatherType.RAIN)
    weather.wetness = 0.9  # well above the puddle's reveal threshold

    # Far from the puddle (50, 0): no overlap.
    assert find_puddle_overlap([way], weather, x=0.0, y=0.0, probe_radius_m=1.0) is None
    # Right on top of it: overlap.
    assert find_puddle_overlap([way], weather, x=50.0, y=0.0, probe_radius_m=1.0) is not None


def test_find_puddle_overlap_ignores_a_puddle_not_yet_revealed():
    """A puddle candidate that exists but hasn't appeared yet (wetness
    below its reveal threshold) must not be considered a real hazard."""
    way = _way_with_known_puddle(reveal_wetness=0.6)
    weather = WeatherSystem(WeatherType.RAIN)
    weather.wetness = 0.2  # below the puddle's reveal threshold
    assert find_puddle_overlap([way], weather, x=50.0, y=0.0, probe_radius_m=1.0) is None


def test_draw_splashes_draws_nothing_with_no_active_splashes():
    pygame.init()
    try:
        weather = WeatherSystem()
        screen = pygame.Surface((200, 150))
        screen.fill((0, 0, 0))
        draw_splashes(screen, weather, camx=0.0, camy=0.0, screen_w=200, screen_h=150)
        assert pygame.transform.average_color(screen)[:3] == (0, 0, 0)
    finally:
        pygame.quit()


def _region_has_a_nonblack_pixel(screen, cx, cy, half=6):
    for dx in range(-half, half + 1):
        for dy in range(-half, half + 1):
            if screen.get_at((cx + dx, cy + dy))[:3] != (0, 0, 0):
                return True
    return False


def test_draw_splashes_draws_a_visible_ring_then_fades_out():
    pygame.init()
    try:
        # Give the splash a few frames of age so its ring has expanded past
        # the ~2px radius at spawn - big enough to reliably sample pixels
        # from, mid-life rather than the very first instant.
        weather = WeatherSystem()
        weather.spawn_splash(0.0, 0.0, 1.0)
        weather.update(0.0, SPLASH_LIFETIME_S * 0.4)
        screen = pygame.Surface((200, 150))
        screen.fill((0, 0, 0))
        draw_splashes(screen, weather, camx=0.0, camy=0.0, px_per_m=9.0, screen_w=200, screen_h=150)
        assert _region_has_a_nonblack_pixel(screen, 100, 75, half=10), "no splash ring pixels found"

        weather.update(0.0, 10.0)  # well past SPLASH_LIFETIME_S
        screen.fill((0, 0, 0))
        draw_splashes(screen, weather, camx=0.0, camy=0.0, px_per_m=9.0, screen_w=200, screen_h=150)
        assert not _region_has_a_nonblack_pixel(screen, 100, 75, half=15), "expired splash still drew"
    finally:
        pygame.quit()


def _puddle_scan_row(way, weather, scan_half=20):
    """Render just this puddle and return the red-channel value along a
    horizontal line through its center, as a list. Comparing two such
    scans (identical puddle geometry, different ripple state) isolates
    exactly the ripple ring's visual contribution."""
    screen = pygame.Surface((300, 300))
    screen.fill((100, 100, 100))
    draw_puddles(screen, [way], weather, camx=50.0, camy=0.0, px_per_m=9.0, screen_w=300, screen_h=300)
    center = (150, 150)
    return [screen.get_at((center[0] + dx, center[1]))[0] for dx in range(-scan_half, scan_half + 1)]


def test_draw_puddles_shows_a_ripple_ring_mid_cycle_while_raining(monkeypatch):
    """WEATHER_RAIN.md #6: raindrops hitting a puddle create occasional
    ripple rings while it's actively raining."""
    pygame.init()
    try:
        way = _way_with_known_puddle(reveal_wetness=0.1)
        weather = WeatherSystem(WeatherType.RAIN)
        weather.wetness = 0.9

        monkeypatch.setattr(pygame.time, "get_ticks", lambda: 2000)  # between ripples (cycle 2400ms, duration 1000ms)
        silent_row = _puddle_scan_row(way, weather)

        monkeypatch.setattr(pygame.time, "get_ticks", lambda: 500)  # mid-way through a ripple (phase 0)
        active_row = _puddle_scan_row(way, weather)

        max_diff = max(abs(a - s) for a, s in zip(active_row, silent_row))
        assert max_diff > 15, "no ripple ring pixel found mid-cycle"
    finally:
        pygame.quit()


def test_draw_puddles_ripple_is_silent_once_rain_stops_even_if_still_wet(monkeypatch):
    """WEATHER_RAIN.md #6/#9: the puddle itself persists while wet, but
    ambient ripples require actively-falling rain, not just wetness."""
    pygame.init()
    try:
        way = _way_with_known_puddle(reveal_wetness=0.1)
        monkeypatch.setattr(pygame.time, "get_ticks", lambda: 500)  # would be mid-ripple if it were raining

        raining = WeatherSystem(WeatherType.RAIN)
        raining.wetness = 0.9
        active_row = _puddle_scan_row(way, raining)

        stopped = WeatherSystem(WeatherType.CLEAR)
        stopped.wetness = 0.9  # still very wet, just not raining anymore
        quiet_row = _puddle_scan_row(way, stopped)

        max_diff = max(abs(a - q) for a, q in zip(active_row, quiet_row))
        assert max_diff > 15, "ripple appeared even though it isn't raining"

        screen = pygame.Surface((300, 300))
        screen.fill((100, 100, 100))
        draw_puddles(screen, [way], stopped, camx=50.0, camy=0.0, px_per_m=9.0, screen_w=300, screen_h=300)
        assert pygame.transform.average_color(screen)[:3] != (100, 100, 100), "the puddle itself should still show"
    finally:
        pygame.quit()
