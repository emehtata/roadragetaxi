import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
from theroadragetrip.geo import compute_bbox
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car, SpatialWayGrid, get_road_layer_at_point, is_on_road
from theroadragetrip.osm import Building, Scenery, Water
from theroadragetrip.render import (
    SCREEN_H,
    SCREEN_W,
    _covered_by_higher_road,
    _vehicle_is_on_bridge,
    asphalt_texture_tile_size,
    begin_static_cache_frame,
    draw_buildings,
    draw_car,
    draw_headlight_beams,
    draw_bus_stops,
    draw_scenery,
    draw_waters,
    draw_ways,
    draw_vehicle_lights,
    get_viewport_bounds,
        minimum_px_per_m_for_viewport_width,
    invalidate_static_caches_for_camera_jump,
    road_color_for_way,
    road_render_priority,
    world_to_screen,
)


def test_compute_bbox():
    pts = [(10.0, 20.0), (30.0, 5.0), (-5.0, 15.0)]
    minx, miny, maxx, maxy = compute_bbox(pts)
    assert minx == -5.0
    assert miny == 5.0
    assert maxx == 30.0
    assert maxy == 20.0


def test_get_viewport_bounds():
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx=100.0, camy=200.0, px_per_m=1.0, screen_w=800, screen_h=600, margin_m=50.0)
    # half_w = 400 + 50 = 450 -> [ -350, 550 ]
    # half_h = 300 + 50 = 350 -> [ -150, 550 ]
    assert vminx == -350.0
    assert vmaxx == 550.0
    assert vminy == -150.0
    assert vmaxy == 550.0


def test_minimum_zoom_keeps_viewport_width_at_or_below_limit():
    min_px_per_m = minimum_px_per_m_for_viewport_width(
        max_width_m=500.0, screen_w=1280, margin_m=30.0
    )
    vminx, _, vmaxx, _ = get_viewport_bounds(
        camx=0.0, camy=0.0, px_per_m=min_px_per_m, screen_w=1280, screen_h=720, margin_m=30.0
    )

    assert vmaxx - vminx == 500.0


def test_spatial_way_grid_detection():
    w1 = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0)
    w2 = Way(points_m=[(500.0, 500.0), (600.0, 500.0)], highway="residential", half_width_m=3.0)

    grid = SpatialWayGrid(cell_size=200.0)
    grid.rebuild([w1, w2])

    car_on = Car(x=50.0, y=1.0, heading=0.0, speed=0.0)
    car_off = Car(x=50.0, y=50.0, heading=0.0, speed=0.0)
    car_on_w2 = Car(x=550.0, y=502.0, heading=0.0, speed=0.0)

    assert grid.is_on_road(car_on) is True
    assert grid.is_on_road(car_off) is False
    assert grid.is_on_road(car_on_w2) is True
    assert is_on_road(car_on, [w1, w2], spatial_grid=grid) is True
    assert is_on_road(car_off, [w1, w2], spatial_grid=grid) is False


def test_higher_layer_road_covers_lower_layer_vehicle():
    bridge = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=5.0, layer=1)
    ways = [bridge]

    assert _covered_by_higher_road(50.0, 0.0, layer=0, ways=ways) is True
    assert _covered_by_higher_road(50.0, 0.0, layer=1, ways=ways) is False


def test_vehicle_on_bridge_is_not_hidden_by_overlapping_higher_bridge():
    lower_bridge = Way(
        points_m=[(-50.0, 0.0), (50.0, 0.0)],
        highway="primary",
        half_width_m=5.0,
        layer=1,
        is_bridge=True,
    )
    upper_bridge = Way(
        points_m=[(-50.0, 0.0), (50.0, 0.0)],
        highway="primary",
        half_width_m=5.0,
        layer=2,
        is_bridge=True,
    )
    car_on_lower_bridge = Car(x=0.0, y=0.0, heading=0.0, speed=10.0, layer=1)

    assert _covered_by_higher_road(
        car_on_lower_bridge.x,
        car_on_lower_bridge.y,
        car_on_lower_bridge.layer,
        [lower_bridge, upper_bridge],
    ) is True

    assert _vehicle_is_on_bridge(car_on_lower_bridge, lower_bridge)


def test_layer_transition_prefers_way_matching_vehicle_heading():
    east_west = Way(points_m=[(-20.0, 0.0), (20.0, 0.0)], highway="primary", half_width_m=5.0, layer=0)
    north_south_bridge = Way(
        points_m=[(0.0, -20.0), (0.0, 20.0)],
        highway="primary",
        half_width_m=5.0,
        layer=1,
        is_bridge=True,
    )
    grid = SpatialWayGrid([east_west, north_south_bridge])

    assert get_road_layer_at_point(0.0, 0.0, current_layer=2, heading=1.5708, spatial_grid=grid) == 1
    assert get_road_layer_at_point(0.0, 0.0, current_layer=2, heading=0.0, spatial_grid=grid) == 0


def test_vehicle_lights_and_headlight_beams_hidden_under_bridge():
    import pygame

    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))

    bridge = Way(points_m=[(-50.0, 0.0), (50.0, 0.0)], highway="primary", half_width_m=5.0, layer=1)
    ways = [bridge]
    car_under_bridge = Car(x=0.0, y=0.0, heading=0.0, speed=10.0, layer=0)

    screen.fill((0, 0, 0))
    draw_vehicle_lights(screen, [car_under_bridge], camx=0.0, camy=0.0, px_per_m=9.0, ways=ways)
    assert screen.get_at((SCREEN_W // 2, SCREEN_H // 2))[:3] == (0, 0, 0)

    screen.fill((0, 0, 0))
    draw_headlight_beams(
        screen,
        [car_under_bridge],
        camx=0.0,
        camy=0.0,
        game_time_seconds=0.0,
        px_per_m=9.0,
        daylight_surface=screen.copy(),
        ways=ways,
    )
    assert screen.get_at((SCREEN_W // 2, SCREEN_H // 2 - 40))[:3] == (0, 0, 0)

    pygame.quit()


def test_asphalt_texture_does_not_cover_terrain():
    import pygame

    pygame.init()
    screen = pygame.display.set_mode((320, 200))
    terrain_color = (12, 120, 34)
    screen.fill(terrain_color)
    way = Way(points_m=[(-100.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=5.0)

    draw_ways(screen, [way], 0.0, 0.0, px_per_m=1.0, screen_w=320, screen_h=200)

    assert screen.get_at((0, 0))[:3] == terrain_color
    pygame.quit()


def test_asphalt_texture_is_anchored_to_world_coordinates():
    import pygame

    pygame.init()
    way = Way(points_m=[(-500.0, 0.0), (500.0, 0.0)], highway="primary", half_width_m=20.0)
    colors = []
    for camx in (0.0, 10.0):
        screen = pygame.display.set_mode((320, 200))
        screen.fill((12, 120, 34))
        draw_ways(screen, [way], camx, 0.0, px_per_m=1.0, screen_w=320, screen_h=200)
        screen_x, screen_y = world_to_screen(0.0, 5.0, camx, 0.0, 1.0, 320, 200)
        colors.append(screen.get_at((screen_x, screen_y))[:3])

    assert colors[0] == colors[1]
    pygame.quit()


def test_asphalt_texture_zoom_keeps_world_scale():
    default_tile_size = asphalt_texture_tile_size(0.7)
    zoomed_tile_size = asphalt_texture_tile_size(1.4)

    assert default_tile_size == 64
    assert zoomed_tile_size == 128
    assert default_tile_size / 0.7 == zoomed_tile_size / 1.4

def test_road_color_prefers_osm_surface_over_highway():
    asphalt = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.0, surface="concrete")
    unknown = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.0, surface="new_material")
    sidewalk = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="footway", half_width_m=1.2, is_drivable=False, surface="asphalt")
    cycleway = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="cycleway", half_width_m=1.5, is_drivable=False)

    assert road_color_for_way(asphalt) == (142, 142, 138)
    assert road_color_for_way(unknown) == (70, 70, 70)
    assert road_color_for_way(sidewalk) == (70, 70, 70)
    assert road_color_for_way(cycleway) == (115, 145, 150)


def test_major_same_layer_road_renders_over_minor_road():
    assert road_render_priority(Way([(0.0, 0.0), (10.0, 0.0)], "primary", 4.0)) > road_render_priority(
        Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0)
    )

    import pygame

    pygame.init()
    screen = pygame.display.set_mode((240, 160))
    screen.fill((20, 120, 40))
    minor = Way([(-60.0, -60.0), (60.0, 60.0)], "residential", 4.0)
    major = Way([(-60.0, 0.0), (60.0, 0.0)], "primary", 4.0, surface="concrete")

    draw_ways(screen, [minor, major], 0.0, 0.0, px_per_m=1.0, screen_w=240, screen_h=160)

    assert screen.get_at((120, 77))[:3] == (142, 142, 138)
    pygame.quit()


def test_draw_bus_stop_adds_roadside_bay_and_shelter():
    import pygame

    pygame.init()
    screen = pygame.display.set_mode((240, 160))
    screen.fill((20, 120, 40))
    way = Way(points_m=[(-60.0, 0.0), (60.0, 0.0)], highway="residential", half_width_m=4.0)
    stop = type("Stop", (), {"x": 0.0, "y": 0.0, "layer": 0, "shelter": True})()

    draw_bus_stops(screen, [stop], [way], 0.0, 0.0, px_per_m=1.0, screen_w=240, screen_h=160)

    assert screen.get_at((120, 155))[:3] == (20, 120, 40)
    assert any(
        screen.get_at((x, y))[:3] == (82, 82, 78)
        for x in range(112, 129)
        for y in range(73, 77)
    )
    assert any(
        screen.get_at((x, y))[:3] != (20, 120, 40)
        for x in range(116, 125)
        for y in range(70, 75)
    )
    pygame.quit()


def test_draw_car_is_unaffected_by_an_unrelated_layers_throttle_state():
    """Regression: draw_car used to carry its own "skip drawing this frame
    if the *labels* cache hasn't gotten its turn to rebuild yet" branch - a
    leftover that (a) had nothing to do with drawing the car, (b) referenced
    an undefined cache_zoom (a NameError once reachable), and (c) when
    reachable, replaced the car with a stale labels-layer blit instead of
    drawing it at all. draw_car should draw the car every time regardless of
    any other layer's throttle state."""
    import pygame
    from theroadragetrip.render import common as common_module
    from theroadragetrip.physics import Car

    pygame.init()
    try:
        screen = pygame.Surface((240, 160), pygame.SRCALPHA)
        screen.fill((0, 0, 0))
        common_module._label_frame_cache_surface = pygame.Surface((100, 100))
        common_module._label_frame_cache_camera = (0.0, 0.0)
        common_module.begin_static_cache_frame()
        # Spend this frame's one allowed rebuild on an unrelated layer, so
        # any leftover cross-layer check in draw_car would be denied - this
        # used to be exactly the branch that raised NameError, or, once
        # "fixed" to not crash, silently skipped the car.
        common_module._allow_static_rebuild("some_other_layer", object())

        car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
        draw_car(screen, car, 0.0, 0.0, px_per_m=9.0, screen_w=240, screen_h=160)
        assert screen.get_at((120, 80))[:3] != (0, 0, 0), (
            "draw_car did not draw the car when an unrelated layer's "
            "throttle was denied"
        )
    finally:
        pygame.quit()


def test_road_and_buildings_stay_visible_through_continuous_camera_panning():
    """Regression: an earlier version of the static-cache rebuild throttle
    denied *any* layer's routine cache miss once another, unrelated layer
    had used up the frame's one allowed rebuild - and since every layer's
    frame_cache_key shares the same camera-position component, panning the
    camera (ordinary driving, not just a big jump) makes several of them go
    stale on the very same frame routinely, so drawing more than one layer
    per frame (as main.py always does) made them compete for that one
    slot. A layer that lost the race stayed stuck showing whatever was
    last on screen, at the wrong offset, for as long as new staleness kept
    arriving before it got a turn - which under continuous panning is
    indefinitely. Reproduces that by drawing roads *and* buildings
    together while panning the camera in small steps across many
    cache-padding/zoom-bucket boundaries, exactly like main.py does once
    per real frame (begin_static_cache_frame() before each draw), and
    checking both are actually visible on every single frame, not just
    eventually."""
    import pygame

    pygame.init()
    try:
        road = Way([(-5000.0, 0.0), (5000.0, 0.0)], "primary", 4.0, surface="concrete")
        # A building strip alongside the road, long enough to stay in view
        # for the whole panning range below (an unrealistic shape, but
        # buildings don't need to look real to exercise the cache).
        building = Building(
            [(-5000.0, 10.0), (5000.0, 10.0), (5000.0, 20.0), (-5000.0, 20.0)],
            bbox=(-5000.0, 10.0, 5000.0, 20.0),
        )
        px_per_m = 1.0
        screen_w, screen_h = 240, 160

        for step in range(120):
            camx = step * 15.0  # crosses a cache-padding/zoom-bucket boundary every few frames
            begin_static_cache_frame()
            screen = pygame.Surface((screen_w, screen_h))
            screen.fill((20, 120, 40))
            draw_ways(screen, [road], camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
            draw_buildings(screen, [building], camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)

            # The road passes directly under the camera at every step; check
            # the same screen offset from center the road-priority test above
            # uses (a few pixels off true center, to land on the road body
            # rather than a lane-marking pixel).
            assert screen.get_at((screen_w // 2, screen_h // 2 - 3))[:3] == (142, 142, 138), (
                f"road not visible at step {step} (camx={camx})"
            )
            building_px = world_to_screen(camx, 15.0, camx, 0.0, px_per_m, screen_w, screen_h)
            assert screen.get_at(building_px)[:3] != (20, 120, 40), (
                f"building not visible at step {step} (camx={camx})"
            )
    finally:
        pygame.quit()


def test_all_static_layers_recover_visibly_after_a_camera_jump():
    """After a respawn-style camera jump, every static layer must actually
    reappear within a small, bounded number of frames - not just "some
    layer eventually" while others stay stuck. Builds one of each kind of
    static content at a distant "new" location, warms every cache at the
    old location, jumps (mirroring what main.py's respawn handlers do:
    snap camx/camy, then invalidate_static_caches_for_camera_jump()), and
    asserts each layer is visible again well within the number of frames
    the shared one-rebuild-per-frame queue needs to drain."""
    import pygame

    pygame.init()
    try:
        old_x, new_x = 0.0, 50000.0
        px_per_m = 9.0
        screen_w, screen_h = 400, 400
        # Keep every shape within roughly +/-20m of the camera: the
        # viewport's world half-height here is 200px / 9 px-per-m ~= 22m.

        road = Way([(new_x - 100.0, 0.0), (new_x + 100.0, 0.0)], "primary", 4.0, surface="concrete")
        building = Building(
            [(new_x + 5.0, 5.0), (new_x + 15.0, 5.0), (new_x + 15.0, 15.0), (new_x + 5.0, 15.0)],
            bbox=(new_x + 5.0, 5.0, new_x + 15.0, 15.0),
        )
        scenery = Scenery(
            [(new_x - 15.0, -15.0), (new_x - 5.0, -15.0), (new_x - 5.0, -5.0), (new_x - 15.0, -5.0)],
            kind="forest",
            bbox=(new_x - 15.0, -15.0, new_x - 5.0, -5.0),
        )
        water = Water(
            # Explicitly closed ring (first point repeated at the end):
            # draw_waters only fills a water shape as a polygon when it's
            # closed this way, otherwise it's drawn as a thin waterway line.
            [
                (new_x - 15.0, 5.0), (new_x - 5.0, 5.0), (new_x - 5.0, 15.0),
                (new_x - 15.0, 15.0), (new_x - 15.0, 5.0),
            ],
            kind="water",
            is_polygon=True,
            bbox=(new_x - 15.0, 5.0, new_x - 5.0, 15.0),
        )

        def render_frame(camx):
            screen = pygame.Surface((screen_w, screen_h))
            screen.fill((20, 120, 40))
            draw_ways(screen, [road], camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
            draw_buildings(screen, [building], camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
            draw_scenery(screen, [scenery], camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
            draw_waters(screen, [water], camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
            return screen

        background = (20, 120, 40)
        road_color = (142, 142, 138)
        # Pixel at the center of each shape, computed the same way the
        # renderer projects world coordinates to screen space.
        building_px = world_to_screen(new_x + 10.0, 10.0, new_x, 0.0, px_per_m, screen_w, screen_h)
        scenery_px = world_to_screen(new_x - 10.0, -10.0, new_x, 0.0, px_per_m, screen_w, screen_h)
        water_px = world_to_screen(new_x - 10.0, 10.0, new_x, 0.0, px_per_m, screen_w, screen_h)
        # A few pixels off the road's exact centerline, like the
        # road-priority test above, to land on the road body rather than a
        # lane-marking pixel drawn exactly down the middle.
        road_center_x, road_center_y = world_to_screen(new_x, 0.0, new_x, 0.0, px_per_m, screen_w, screen_h)
        road_px = (road_center_x, road_center_y - 3)

        # Warm every cache at the old (now irrelevant) location.
        begin_static_cache_frame()
        render_frame(old_x)

        # Jump, exactly like a respawn: snap the camera, then tell the
        # static caches a jump happened.
        invalidate_static_caches_for_camera_jump()

        seen_road = seen_building = seen_scenery = seen_water = False
        for _frame in range(8):
            begin_static_cache_frame()
            screen = render_frame(new_x)
            seen_road = seen_road or screen.get_at(road_px)[:3] == road_color
            seen_building = seen_building or screen.get_at(building_px)[:3] != background
            seen_scenery = seen_scenery or screen.get_at(scenery_px)[:3] != background
            seen_water = seen_water or screen.get_at(water_px)[:3] != background

        assert seen_road, "road never reappeared after the camera jump"
        assert seen_building, "building never reappeared after the camera jump"
        assert seen_scenery, "scenery never reappeared after the camera jump"
        assert seen_water, "water never reappeared after the camera jump"
    finally:
        pygame.quit()
