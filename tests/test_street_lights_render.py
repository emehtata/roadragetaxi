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


def test_draw_street_lights_geometry_region_survives_small_camera_moves():
    """Regression: an earlier version of the geometry-rebuild scoping fix
    re-triggered a full rebuild every time the camera crossed a *fixed 20m
    grid line*, in either axis - cheap in isolation (bounded by the
    viewport region, not the whole city), but at normal driving speed
    that's a real synchronous rebuild roughly every 1-2 seconds, each one
    a small stall - reported as a periodic flicker/fps-drop while driving.
    The fix rebuilds only once the *tight* viewport is no longer contained
    in the last-rebuilt (much wider) region, so small moves reuse it and
    only a real, large move triggers a rebuild."""
    import theroadragetrip.render.roads as roads_module
    from theroadragetrip.physics import SpatialWayGrid

    pygame.init()
    try:
        road = Way(
            points_m=[(-500.0, 0.0), (500.0, 0.0)],
            highway="tertiary",
            half_width_m=4.0,
            lit="yes",
        )
        ways = [road]
        spatial_grid = SpatialWayGrid(ways)
        screen = pygame.Surface((240, 180), pygame.SRCALPHA)
        # A stable reference, not a fresh `[]` literal per call: real
        # gameplay passes the same buildings list every frame (main.py
        # mutates it in place as autofetch streams tiles in), and
        # geometry_cache_key below is keyed in part by id(buildings) - a
        # new empty list's own identity differs every call, which forced
        # a "changed" cache key (and therefore a rebuild) on every single
        # render_at() regardless of region_covers_viewport, defeating the
        # exact behavior this test means to check.
        buildings = []

        def render_at(camx):
            screen.fill((180, 170, 140, 255))
            draw_day_night_overlay(screen, 0.0, 100, latitude=65.0, longitude=25.0)
            draw_street_lights(
                screen, ways, camx=camx, camy=0.0, game_time_seconds=0.0,
                px_per_m=2.0, screen_w=240, screen_h=180,
                daylight_surface=None, buildings=buildings, spatial_grid=spatial_grid,
            )

        roads_module._street_light_geometry_region = None
        roads_module._street_light_geometry_cache_key = None
        roads_module._street_light_way_lit_cache_key = None
        roads_module._street_light_junction_cache = None
        roads_module._street_light_junction_grid_cache = None

        render_at(0.0)
        region_after_first = roads_module._street_light_geometry_region
        assert region_after_first is not None

        # A handful of small moves - well inside the region padding - must
        # not touch the cached region at all.
        for camx in (5.0, 12.0, 20.0, 30.0):
            render_at(camx)
            assert roads_module._street_light_geometry_region == region_after_first, (
                f"region rebuilt after a {camx}m move - rebuilds too eagerly"
            )

        # A move past the region's own padding must trigger a real rebuild.
        render_at(400.0)
        assert roads_module._street_light_geometry_region != region_after_first, (
            "region never rebuilt even after driving well past it"
        )
    finally:
        pygame.quit()


def test_draw_street_lights_building_lookup_is_scoped_when_a_spatial_grid_is_given():
    """The lit-segment classification (does this road pass close enough to
    a building to count as "lit" even without an explicit lit= tag) used
    to build its building_grid from *every* loaded building, every time
    the building list changed - ~67ms against a real ~21k-building Oulu
    extract, and since autofetch grows `buildings` the same way it grows
    `ways`, that kept recurring. Passing a building_spatial_grid (the same
    kind of index main.py already maintains for building collision) scopes
    that lookup to the region instead. Confirm many far-away buildings are
    never visited when the index is given."""
    import theroadragetrip.render.roads as roads_module
    from theroadragetrip.physics import SpatialWayGrid
    from theroadragetrip.osm import Building

    pygame.init()
    try:
        # No explicit lit=yes here - this road only becomes "lit" via
        # proximity to the near building, so the building lookup actually
        # has to run and find it.
        near_road = Way(
            points_m=[(0.0, 0.0), (100.0, 0.0)],
            highway="tertiary",
            half_width_m=4.0,
        )
        near_building = Building(
            points_m=[(10.0, 5.0), (20.0, 5.0), (20.0, 15.0), (10.0, 15.0)],
            bbox=(10.0, 5.0, 20.0, 15.0),
        )
        far_buildings = [
            Building(
                points_m=[(100_000.0 + i * 50.0, 0.0)] * 3,
                bbox=(100_000.0 + i * 50.0, 0.0, 100_000.0 + i * 50.0 + 10.0, 10.0),
            )
            for i in range(500)
        ]
        buildings = [near_building] + far_buildings
        ways = [near_road]
        spatial_grid = SpatialWayGrid(ways)
        building_spatial_grid = SpatialWayGrid(buildings)

        seen_grids = []
        real_fn = roads_module._point_is_near_building

        def counting_fn(point, buildings_arg, building_grid):
            seen_grids.append(building_grid)
            return real_fn(point, buildings_arg, building_grid)

        screen = pygame.Surface((240, 180), pygame.SRCALPHA)
        screen.fill((180, 170, 140, 255))
        draw_day_night_overlay(screen, 0.0, 100, latitude=65.0, longitude=25.0)

        roads_module._point_is_near_building = counting_fn
        try:
            draw_street_lights(
                screen, ways, camx=50.0, camy=0.0, game_time_seconds=0.0,
                px_per_m=2.0, screen_w=240, screen_h=180,
                daylight_surface=None, buildings=buildings, spatial_grid=spatial_grid,
                building_spatial_grid=building_spatial_grid,
            )
        finally:
            roads_module._point_is_near_building = real_fn

        assert seen_grids, "lit-segment classification never ran"
        # The building_grid actually built and used must contain the near
        # building but never anywhere near all 501 - if it were built from
        # the unscoped full `buildings` list, every one of the far
        # buildings would be in there too (each in its own distant cell).
        total_entries = sum(len(v) for v in seen_grids[0].values())
        assert 0 < total_entries < 50, f"building_grid held {total_entries} building-cell entries - not scoped to the region"
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