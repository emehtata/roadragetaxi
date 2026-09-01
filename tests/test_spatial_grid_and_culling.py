import os

from theroadragetrip.geo import compute_bbox
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car, SpatialWayGrid, get_road_layer_at_point, is_on_road
from theroadragetrip.render import (
    SCREEN_H,
    SCREEN_W,
    _covered_by_higher_road,
    _vehicle_is_on_bridge,
    asphalt_texture_tile_size,
    draw_headlight_beams,
    draw_bus_stops,
    draw_ways,
    draw_vehicle_lights,
    get_viewport_bounds,
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
