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
    LEGACY_HIGHWAY_COLORS,
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


def test_ways_in_rect_draw_order_is_stable_across_different_viewports():
    """Regression: a real Oulu park (small, nested inside a much bigger
    landuse polygon that's far larger than the screen) rendered fine from
    one camera position and vanished - fully painted over by the big
    polygon's own fill - from a camera position only ~24m away, with
    nothing about the map having changed. ways_in_rect() used to yield
    results in grid-scan order: a small viewport only ever sees a *few*
    of a huge polygon's many indexed cells, and *which* of those cells it
    happens to reach first (deciding whether the huge polygon is "seen"
    before or only at the same cell as the small one nested inside it)
    depends on the query rectangle's own corner - not on anything about
    the ways themselves. Two viewports panned a few meters apart, both
    still fully inside the huge polygon and both still containing the
    small one, could get them back in a different relative order.

    Reproduces the exact mechanism: `big` is much larger than either
    viewport (as a real landuse polygon is next to a car's view), so
    neither viewport sees its far edge - one starts west of `small`'s own
    cell (finding `big` there first, before ever reaching `small`'s
    cell); the other starts exactly at `small`'s cell (finding both there
    together, at the mercy of insertion order)."""
    cell_size = 100.0
    big = Scenery(
        [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)],
        "parking", bbox=(0.0, 0.0, 1000.0, 1000.0),
    )
    small = Scenery(
        [(410.0, 410.0), (490.0, 410.0), (490.0, 490.0), (410.0, 490.0)],
        "park", bbox=(410.0, 410.0, 490.0, 490.0),
    )

    grid = SpatialWayGrid(cell_size=cell_size)
    grid.rebuild([small, big])  # `small` listed first - must not decide anything on its own

    # Viewport A starts west of `small`'s cell (reaches `big` via a cell
    # `small` isn't in, first). Viewport B starts exactly at `small`'s own
    # cell corner (reaches both together). Both fully contain `small` and
    # are entirely inside `big`'s extent - neither sees `big`'s far edge.
    viewport_a = (0.0, 400.0, 600.0, 600.0)
    viewport_b = (400.0, 400.0, 600.0, 600.0)

    order_a = [sc.kind for sc in grid.ways_in_rect(*viewport_a)]
    order_b = [sc.kind for sc in grid.ways_in_rect(*viewport_b)]

    assert order_a == order_b == ["parking", "park"], (
        f"draw order must not depend on the viewport: got {order_a!r} vs {order_b!r} "
        "for the same two overlapping polygons"
    )


def test_ways_in_rect_draws_the_smaller_more_specific_area_last():
    """Independent of the stability fix above: a small, specific area
    (a named park) nested inside a large, general one (a landuse polygon
    far bigger than the current view) must draw on top of it, not be at
    the mercy of whichever happened to come first in the source OSM data
    or of grid-scan order - a real hand-drawn map layers the specific
    feature over its surroundings. Uses the same "big bigger than the
    viewport, small nested in one of its cells" shape as the stability
    test above, which is exactly the layout where insertion order (small
    listed first) used to win the scan and draw the small area first -
    i.e. underneath."""
    cell_size = 100.0
    small = Scenery(
        [(410.0, 410.0), (490.0, 410.0), (490.0, 490.0), (410.0, 490.0)],
        "grass", bbox=(410.0, 410.0, 490.0, 490.0),
    )
    big = Scenery(
        [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)],
        "residential", bbox=(0.0, 0.0, 1000.0, 1000.0),
    )

    grid = SpatialWayGrid(cell_size=cell_size)
    grid.rebuild([small, big])  # small listed FIRST in the source data - must not matter

    # A viewport starting exactly at small's own cell corner, entirely
    # inside big's extent - the case where both are first found together,
    # at the mercy of insertion order rather than area.
    order = [sc.kind for sc in grid.ways_in_rect(400.0, 400.0, 600.0, 600.0)]

    assert order == ["residential", "grass"]


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
    # No recognized surface - falls back to the legacy per-highway-class
    # color (residential), not a flat generic grey.
    assert road_color_for_way(unknown) == LEGACY_HIGHWAY_COLORS["residential"]
    assert road_color_for_way(sidewalk) == (70, 70, 70)
    assert road_color_for_way(cycleway) == (115, 145, 150)


def test_road_color_falls_back_to_legacy_highway_class_without_a_surface_tag():
    """No surface tag at all (common in real OSM data) must still
    differentiate by road class, not collapse every highway type to the
    same flat grey."""
    motorway = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="motorway", half_width_m=6.0)
    residential = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=4.0)
    track = Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="track", half_width_m=2.0)

    assert road_color_for_way(motorway) == LEGACY_HIGHWAY_COLORS["motorway"]
    assert road_color_for_way(residential) == LEGACY_HIGHWAY_COLORS["residential"]
    assert road_color_for_way(track) == LEGACY_HIGHWAY_COLORS["track"]
    # Different classes must actually look different, not all the same grey.
    assert len({road_color_for_way(motorway), road_color_for_way(residential), road_color_for_way(track)}) == 3


def test_major_same_layer_road_renders_over_minor_road():
    assert road_render_priority(Way([(0.0, 0.0), (10.0, 0.0)], "primary", 4.0)) > road_render_priority(
        Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0)
    )

    import pygame
    from theroadragetrip.render import common as common_module

    pygame.init()
    screen = pygame.display.set_mode((240, 160))
    screen.fill((20, 120, 40))
    minor = Way([(-60.0, -60.0), (60.0, 60.0)], "residential", 4.0)
    major = Way([(-60.0, 0.0), (60.0, 0.0)], "primary", 4.0, surface="concrete")

    # Unlike most other tests in this file, this one previously skipped
    # resetting the shared static-cache throttle - relying on the "roads"
    # layer's surface still being None (so _allow_static_rebuild's
    # first-build exemption bypasses the throttle) whenever this test
    # happened to run before any other test had ever built one. Order- and
    # leftover-state-dependent; reset explicitly like the other tests here do.
    begin_static_cache_frame()
    common_module._pending_static_rebuilds.clear()
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
        # Static-cache keys include id(list) - a stable list reference, like
        # real gameplay's persistent ways/buildings lists, not a fresh
        # literal rebuilt every call (which would make every layer look
        # "dirty" every single frame and starve everything behind whichever
        # is drawn first).
        ways = [road]
        buildings = [building]

        for step in range(120):
            camx = step * 15.0  # crosses a cache-padding/zoom-bucket boundary every few frames
            begin_static_cache_frame()
            screen = pygame.Surface((screen_w, screen_h))
            screen.fill((20, 120, 40))
            draw_ways(screen, ways, camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
            draw_buildings(screen, buildings, camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)

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

        # Static-cache keys include id(list) - stable list references, like
        # real gameplay's persistent lists, not a fresh literal rebuilt on
        # every call (which would make every layer look "dirty" every
        # single frame and starve everything behind whichever draws first).
        ways = [road]
        buildings = [building]
        sceneries = [scenery]
        waters = [water]

        def render_frame(camx):
            screen = pygame.Surface((screen_w, screen_h))
            screen.fill((20, 120, 40))
            draw_ways(screen, ways, camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
            draw_buildings(screen, buildings, camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
            draw_scenery(screen, sceneries, camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
            draw_waters(screen, waters, camx, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)
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
