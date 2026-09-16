"""Tests for stop/yield sign extraction and rendering (RENDER-audit.md
section 21: these were parsed since day one but never had a renderer)."""
from theroadragetrip.osm import StopSign, YieldSign, build_ways
from theroadragetrip.render import draw_stop_signs, draw_yield_signs
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def test_build_ways_parses_a_stop_node_and_snaps_it_beside_the_road():
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.000, "lon": 25.001},
        # Nudged slightly east of the (north-south-ish... here east-west)
        # road centerline - real stop-sign nodes are commonly digitized a
        # touch off-center towards the physical post.
        {"type": "node", "id": 3, "lat": 60.00003, "lon": 25.0005, "tags": {"highway": "stop"}},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
    ]

    result = build_ways(elements)

    assert len(result.stop_signs) == 1
    sign = result.stop_signs[0]
    assert sign.id == 3
    assert sign.direction_angle is not None
    # Pushed out past the road edge, not sitting on the centerline like a
    # Crossing/SpeedBump would.
    road_y = result.ways[0].points_m[0][1]
    assert abs(sign.y - road_y) >= sign.road_half_width_m


def test_build_ways_parses_a_give_way_node():
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.000, "lon": 25.001},
        {"type": "node", "id": 3, "lat": 60.00003, "lon": 25.0005, "tags": {"highway": "give_way"}},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
    ]

    result = build_ways(elements)

    assert len(result.yield_signs) == 1
    assert result.yield_signs[0].id == 3
    assert result.yield_signs[0].direction_angle is not None


def test_stop_and_yield_signs_land_on_opposite_sides_of_the_road():
    """Regression: without reading which side of the centerline the raw
    OSM node leans towards, both signs would collapse onto the same
    snapped point regardless of which side of the road they're really on."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.000, "lon": 25.001},
        {"type": "node", "id": 3, "lat": 60.00004, "lon": 25.0005, "tags": {"highway": "stop"}},
        {"type": "node", "id": 4, "lat": 59.99996, "lon": 25.0005, "tags": {"highway": "give_way"}},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
    ]

    result = build_ways(elements)

    stop_y = result.stop_signs[0].y
    yield_y = result.yield_signs[0].y
    road_y = result.ways[0].points_m[0][1]
    assert (stop_y - road_y) * (yield_y - road_y) < 0.0, "signs on opposite sides must land on opposite sides"


def test_stop_signs_round_trip_through_world_cache(tmp_path):
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "node", "id": 3, "lat": 60.00003, "lon": 25.0005, "tags": {"highway": "stop"}},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
    ]
    world = build_ways(elements)
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)

    assert len(loaded.stop_signs) == 1
    assert loaded.stop_signs[0].x == world.stop_signs[0].x
    assert loaded.stop_signs[0].y == world.stop_signs[0].y


def test_draw_stop_signs_paints_the_octagon_red():
    import pygame

    pygame.init()
    try:
        screen_w, screen_h, px_per_m = 200, 200, 8.0
        screen = pygame.Surface((screen_w, screen_h))
        screen.fill((40, 90, 40))  # grass green background

        sign = StopSign(x=0.0, y=0.0, direction_angle=0.0)
        draw_stop_signs(screen, [sign], 0.0, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)

        center = (screen_w // 2, screen_h // 2)
        pixel = tuple(screen.get_at(center))[:3]
        assert pixel == (220, 30, 30)
    finally:
        pygame.quit()


def test_draw_yield_signs_paints_a_triangle():
    import pygame

    pygame.init()
    try:
        screen_w, screen_h, px_per_m = 200, 200, 8.0
        screen = pygame.Surface((screen_w, screen_h))
        background = (40, 90, 40)
        screen.fill(background)

        sign = YieldSign(x=0.0, y=0.0, direction_angle=0.0)
        draw_yield_signs(screen, [sign], 0.0, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)

        painted = pygame.surfarray.array3d(screen)
        assert (painted != background).any()
    finally:
        pygame.quit()


def test_draw_stop_signs_skips_signs_outside_the_viewport():
    import pygame

    pygame.init()
    try:
        screen_w, screen_h, px_per_m = 200, 200, 8.0
        screen = pygame.Surface((screen_w, screen_h))
        background = (40, 90, 40)
        screen.fill(background)

        far_sign = StopSign(x=10_000.0, y=10_000.0)
        draw_stop_signs(screen, [far_sign], 0.0, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)

        painted = pygame.surfarray.array3d(screen)
        assert (painted == background).all()
    finally:
        pygame.quit()
