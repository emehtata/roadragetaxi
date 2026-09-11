import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from theroadragetrip.osm import Way
import theroadragetrip.render as render
from theroadragetrip.render import draw_day_night_overlay, draw_street_lights, world_to_screen


def test_lit_road_renders_neutral_light_without_yellow_pool():
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
        baseline = screen.copy()
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

        outside_pixel = screen.get_at((int(lamp_x + 4), int(lamp_y)))[:3]
        baseline_pixel = baseline.get_at((int(lamp_x + 4), int(lamp_y)))[:3]
        assert sum(outside_pixel) > sum(baseline_pixel)
        assert max(outside_pixel) - min(outside_pixel) < 35
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


def test_lamp_has_directional_neutral_pool():
    pygame.init()
    try:
        screen = pygame.Surface((300, 200), pygame.SRCALPHA)
        screen.fill((180, 170, 140, 255))
        draw_day_night_overlay(screen, 0.0, 100, latitude=65.0, longitude=25.0)
        baseline = screen.copy()
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
        side = screen.get_at((int(lamp_x), int(lamp_y - 20)))[:3]
        assert sum(forward) > sum(baseline.get_at((int(lamp_x + 20), int(lamp_y)))[:3])
        assert sum(side) > sum(baseline.get_at((int(lamp_x), int(lamp_y - 20)))[:3])
        assert max(forward) - min(forward) < 35
        assert max(side) - min(side) < 35
    finally:
        pygame.quit()


def test_wide_road_has_neutral_pool_at_far_edge():
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
        assert max(far_edge) - min(far_edge) < 35
    finally:
        pygame.quit()


def test_cached_streetlight_frame_keeps_lamp_without_flicker():
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


def test_draw_street_lights_geometry_rebuild_is_scoped_to_visible_ways():
    """Regression: the lamp-geometry rebuild (junctions, lit-segment cache,
    lamp placement) used to walk the *entire* `ways` list on every cache
    miss, not the viewport-scoped subset it already computes for exactly
    this purpose (`visible_ways` - it was built and then never read).
    `ways` is the whole session's loaded world, which only grows as
    autofetch streams in tiles while driving - against a real ~31k-way
    Oulu extract this cost ~19 SECONDS per rebuild. Build one lit road
    near the camera plus many lit roads far away (outside the viewport +
    padding) and confirm the far ones are never even visited."""
    import theroadragetrip.render.roads as roads_module
    from theroadragetrip.render import common as common_module
    from theroadragetrip.physics import SpatialWayGrid

    pygame.init()
    try:
        near_road = Way(
            points_m=[(0.0, 0.0), (100.0, 0.0)],
            highway="tertiary",
            half_width_m=4.0,
            lit="yes",
        )
        far_roads = [
            Way(
                points_m=[(100_000.0 + i * 200.0, 0.0), (100_000.0 + i * 200.0 + 100.0, 0.0)],
                highway="tertiary",
                half_width_m=4.0,
                lit="yes",
            )
            for i in range(500)
        ]
        ways = [near_road] + far_roads
        spatial_grid = SpatialWayGrid(ways)

        call_count = 0
        real_fn = roads_module._way_has_street_lighting

        def counting_fn(way):
            nonlocal call_count
            call_count += 1
            return real_fn(way)

        screen = pygame.Surface((240, 180), pygame.SRCALPHA)
        screen.fill((180, 170, 140, 255))
        draw_day_night_overlay(screen, 0.0, 100, latitude=65.0, longitude=25.0)

        roads_module._way_has_street_lighting = counting_fn
        try:
            draw_street_lights(
                screen, ways, camx=50.0, camy=0.0, game_time_seconds=0.0,
                px_per_m=2.0, screen_w=240, screen_h=180,
                daylight_surface=None, buildings=[], spatial_grid=spatial_grid,
            )
        finally:
            roads_module._way_has_street_lighting = real_fn

        # Only the near road (and maybe a couple of near-boundary calls)
        # should ever reach this - nowhere close to visiting all 501 ways.
        assert call_count < 20, f"visited {call_count} ways - geometry rebuild is not scoped to visible_ways"
        # And the near road's lamps must actually still get placed - a
        # scoped `visible_ways` that's a generator instead of a list would
        # pass the call-count check above (only visited once) while
        # silently placing zero lamps, since it gets walked three times
        # and a generator only yields once.
        assert common_module._street_light_frame_world_positions, "no lamps were drawn for the near road"
    finally:
        pygame.quit()


def test_street_light_pool_does_not_amplify_headlight_brightness():
    pygame.init()
    try:
        screen = pygame.Surface((240, 180), pygame.SRCALPHA)
        screen.fill((240, 240, 240, 255))
        pre_headlight = pygame.Surface((240, 180), pygame.SRCALPHA)
        pre_headlight.fill((10, 10, 10, 255))
        road = Way(
            points_m=[(0.0, 0.0), (100.0, 0.0)],
            highway="tertiary",
            half_width_m=4.0,
            lit="yes",
        )

        draw_street_lights(
            screen, [road], 50.0, 0.0, 0.0,
            px_per_m=2.0, screen_w=240, screen_h=180,
            buildings=[], base_surface=pre_headlight,
        )

        assert max(screen.get_at((120, 90))[:3]) <= 240
    finally:
        pygame.quit()