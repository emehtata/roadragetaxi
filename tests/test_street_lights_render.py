import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from theroadragetrip.osm import Way
import theroadragetrip.render as render
from theroadragetrip.render import draw_day_night_overlay, draw_street_lights, world_to_screen


def test_lit_road_renders_visible_lamp_and_light_pool():
    pygame.init()
    try:
        screen = pygame.Surface((240, 180), pygame.SRCALPHA)
        screen.fill((10, 10, 20, 255))
        road = Way(
            points_m=[(0.0, 0.0), (100.0, 0.0)],
            highway="tertiary",
            half_width_m=4.0,
            lit="yes",
        )

        screen.fill((180, 170, 140, 255))
        draw_day_night_overlay(
            screen,
            game_time_seconds=0.0,
            visible_road_count=100,
            latitude=65.0,
            longitude=25.0,
        )
        dark_pixel = screen.get_at((120, 90))[:3]
        draw_street_lights(
            screen,
            [road],
            camx=50.0,
            camy=0.0,
            game_time_seconds=0.0,
            px_per_m=2.0,
            screen_w=240,
            screen_h=180,
            daylight_surface=None,
            buildings=[],
        )

        lamp_x, lamp_y = world_to_screen(0.0, -5.0, 50.0, 0.0, 2.0, 240, 180)
        lamp_pixel = screen.get_at((int(lamp_x), int(lamp_y)))[:3]
        assert lamp_pixel[0] > 200
        assert lamp_pixel[1] > 180

        pool_pixel = screen.get_at((int(lamp_x + 4), int(lamp_y)))[:3]
        assert sum(pool_pixel) > sum(dark_pixel)
    finally:
        pygame.quit()


def test_lamps_are_outside_the_road_edges():
    pygame.init()
    try:
        screen = pygame.Surface((240, 180), pygame.SRCALPHA)
        screen.fill((20, 20, 30, 255))
        road = Way(
            points_m=[(0.0, 0.0), (100.0, 0.0)],
            highway="tertiary",
            half_width_m=4.0,
            lit="yes",
        )

        draw_street_lights(
            screen,
            [road],
            camx=50.0,
            camy=0.0,
            game_time_seconds=0.0,
            px_per_m=2.0,
            screen_w=240,
            screen_h=180,
            daylight_surface=None,
            buildings=[],
        )

        assert render._street_light_frame_world_positions
        assert all(abs(y) >= road.half_width_m for _, y in render._street_light_frame_world_positions)
    finally:
        pygame.quit()


def test_lamp_fixture_never_lands_on_crossing_road():
    pygame.init()
    try:
        screen = pygame.Surface((300, 200), pygame.SRCALPHA)
        screen.fill((20, 20, 30, 255))
        horizontal = Way(
            points_m=[(-50.0, 0.0), (50.0, 0.0)],
            highway="tertiary",
            half_width_m=4.0,
            lit="yes",
        )
        vertical = Way(
            points_m=[(0.0, -50.0), (0.0, 50.0)],
            highway="tertiary",
            half_width_m=4.0,
            lit="yes",
        )
        draw_street_lights(
            screen,
            [horizontal, vertical],
            camx=0.0,
            camy=0.0,
            game_time_seconds=0.0,
            px_per_m=2.0,
            screen_w=300,
            screen_h=200,
            daylight_surface=None,
            buildings=[],
        )

        for lamp_x, lamp_y in render._street_light_frame_world_positions:
            assert abs(lamp_y) > horizontal.half_width_m
            assert abs(lamp_x) > vertical.half_width_m
    finally:
        pygame.quit()


def test_lamp_pool_is_directional_270_degree_seven_meter_beam():
    pygame.init()
    try:
        screen = pygame.Surface((300, 200), pygame.SRCALPHA)
        screen.fill((180, 170, 140, 255))
        draw_day_night_overlay(screen, 0.0, 100, latitude=65.0, longitude=25.0)
        road = Way(
            points_m=[(0.0, 0.0), (100.0, 0.0)],
            highway="tertiary",
            half_width_m=4.0,
            lit="yes",
        )
        draw_street_lights(
            screen, [road], 50.0, 0.0, 0.0,
            px_per_m=4.0, screen_w=300, screen_h=200,
            daylight_surface=None, buildings=[],
        )
        lamp_x, lamp_y = world_to_screen(48.0, -5.0, 50.0, 0.0, 4.0, 300, 200)
        forward = screen.get_at((int(lamp_x + 20), int(lamp_y)))[:3]
        side = screen.get_at((int(lamp_x), int(lamp_y + 20)))[:3]
        assert sum(forward) > 250
        assert sum(side) > 250
    finally:
        pygame.quit()


def test_lamp_pool_reaches_the_far_edge_of_a_wide_road():
    pygame.init()
    try:
        screen = pygame.Surface((400, 240), pygame.SRCALPHA)
        screen.fill((180, 170, 140, 255))
        draw_day_night_overlay(screen, 0.0, 100, latitude=65.0, longitude=25.0)
        baseline = screen.copy()
        road = Way(
            points_m=[(0.0, 0.0), (100.0, 0.0)],
            highway="primary",
            half_width_m=12.0,
            lit="yes",
        )
        draw_street_lights(
            screen, [road], 50.0, 0.0, 0.0,
            px_per_m=4.0, screen_w=400, screen_h=240,
            daylight_surface=None, buildings=[],
        )
        lamp_x, lamp_y = world_to_screen(48.0, -13.0, 50.0, 0.0, 4.0, 400, 240)
        far_edge = screen.get_at((int(lamp_x), int(lamp_y - 90)))[:3]
        baseline_far_edge = baseline.get_at((int(lamp_x), int(lamp_y - 90)))[:3]
        assert sum(far_edge) > sum(baseline_far_edge)
    finally:
        pygame.quit()


def test_cached_streetlight_frame_keeps_pool_without_flicker():
    pygame.init()
    try:
        road = Way(
            points_m=[(0.0, 0.0), (100.0, 0.0)],
            highway="tertiary",
            half_width_m=4.0,
            lit="yes",
        )
        first = pygame.Surface((240, 180), pygame.SRCALPHA)
        second = pygame.Surface((240, 180), pygame.SRCALPHA)
        for surface in (first, second):
            surface.fill((180, 170, 140, 255))
            draw_day_night_overlay(surface, 0.0, 100, latitude=65.0, longitude=25.0)
        draw_street_lights(
            first, [road], 50.0, 0.0, 0.0,
            px_per_m=2.0, screen_w=240, screen_h=180,
            daylight_surface=None, buildings=[],
        )
        draw_street_lights(
            second, [road], 50.0, 0.0, 0.0,
            px_per_m=2.0, screen_w=240, screen_h=180,
            daylight_surface=None, buildings=[],
        )

        assert pygame.image.tostring(first, "RGB") == pygame.image.tostring(second, "RGB")
    finally:
        pygame.quit()