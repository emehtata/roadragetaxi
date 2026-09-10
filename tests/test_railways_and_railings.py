"""Tests for railway (railway=rail/tram/...) and railing (barrier=fence/railing) extraction and rendering."""
from theroadragetrip.osm import Railing, Railway, Way, build_ways
from theroadragetrip.render import draw_railings, draw_railways
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def test_build_ways_parses_railway_rail_as_railway():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 30, "nodes": [1, 2], "tags": {"railway": "rail"}},
    ]

    result = build_ways(elements)

    assert len(result.railways) == 1
    assert result.railways[0].kind == "rail"
    assert len(result.railways[0].points_m) == 2


def test_build_ways_ignores_subway_railway():
    """Subway is underground and invisible from street level - must not
    render as a surface rail line."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 31, "nodes": [1, 2], "tags": {"railway": "subway"}},
    ]

    result = build_ways(elements)

    assert len(result.railways) == 0


def test_build_ways_parses_barrier_fence_and_railing():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 32, "nodes": [1, 2], "tags": {"barrier": "fence"}},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 33, "nodes": [3, 4], "tags": {"barrier": "railing"}},
    ]

    result = build_ways(elements)

    assert len(result.railings) == 2


def test_railways_and_railings_round_trip_through_world_cache(tmp_path):
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 30, "nodes": [1, 2], "tags": {"railway": "tram"}},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 32, "nodes": [3, 4], "tags": {"barrier": "fence"}},
    ]
    world = build_ways(elements)
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)

    assert len(loaded.railways) == 1
    assert loaded.railways[0].kind == "tram"
    assert loaded.railways[0].points_m == world.railways[0].points_m
    assert len(loaded.railings) == 1
    assert loaded.railings[0].points_m == world.railings[0].points_m


def test_draw_railways_runs_without_error():
    import pygame
    pygame.init()
    surf = pygame.Surface((800, 600))
    railway = Railway(points_m=[(90.0, 100.0), (110.0, 100.0)], bbox=(90.0, 100.0, 110.0, 100.0))
    draw_railways(surf, [railway], camx=100.0, camy=100.0, px_per_m=5.0, screen_w=800, screen_h=600)
    pygame.quit()


def test_draw_railways_paints_rail_colored_pixels():
    import pygame
    from theroadragetrip.render import RAILWAY_RAIL_COLOR
    pygame.init()
    surf = pygame.Surface((800, 600))
    surf.fill((0, 0, 0))
    railway = Railway(points_m=[(80.0, 100.0), (120.0, 100.0)], bbox=(80.0, 100.0, 120.0, 100.0))
    draw_railways(surf, [railway], camx=100.0, camy=100.0, px_per_m=8.0, screen_w=800, screen_h=600)
    rail_pixels = sum(
        1
        for x in range(800)
        for y in range(600)
        if tuple(surf.get_at((x, y)))[:3] == RAILWAY_RAIL_COLOR
    )
    assert rail_pixels > 0
    pygame.quit()


def test_draw_railings_runs_without_error():
    import pygame
    pygame.init()
    surf = pygame.Surface((800, 600))
    railing = Railing(points_m=[(90.0, 100.0), (110.0, 100.0)], bbox=(90.0, 100.0, 110.0, 100.0))
    draw_railings(surf, [railing], camx=100.0, camy=100.0, px_per_m=5.0, screen_w=800, screen_h=600)
    pygame.quit()


def test_draw_railways_skips_sleeper_ties_far_outside_the_viewport():
    """A rail line's whole-way bbox check only says "this way touches the
    viewport somewhere" - a real rail yard siding can run for kilometers,
    so without per-segment culling a way that merely clips the viewport
    corner would still walk its *entire* length generating a sleeper tie
    every 2m, almost all of them off-screen (measured: one dense real-data
    rail yard cost 5.8ms/frame before this fix, ~1.1ms after)."""
    import pygame
    pygame.init()
    surf = pygame.Surface((800, 600))

    # One segment stretching 10km straight off to the west (every 2m would
    # be ~5000 sleeper ties if not culled), then a short segment actually
    # crossing the visible area near the camera.
    railway = Railway(
        points_m=[(-9900.0, 100.0), (80.0, 100.0), (120.0, 100.0)],
        bbox=(-9900.0, 100.0, 120.0, 100.0),
    )

    draw_calls = []
    real_line = pygame.draw.line
    try:
        pygame.draw.line = lambda *a, **k: (draw_calls.append(1), real_line(*a, **k))[1]
        draw_railways(surf, [railway], camx=100.0, camy=100.0, px_per_m=8.0, screen_w=800, screen_h=600)
    finally:
        pygame.draw.line = real_line
    pygame.quit()

    # The visible ~120m segment alone draws on the order of a few dozen
    # lines (ties + 2 rails); if the far-off-screen 10km segment wasn't
    # culled it would add thousands more.
    assert len(draw_calls) < 200


def test_draw_railings_skips_dashes_far_outside_the_viewport():
    """A fence/railing way can run continuously for kilometers (a highway
    median barrier) - _draw_dashed_polyline used to walk a dash every
    dash_m+gap_m along a segment's *entire* length with no viewport check
    at all, so a way that merely clips the viewport corner would generate
    thousands of off-screen dashes."""
    import pygame
    pygame.init()
    surf = pygame.Surface((800, 600))

    # One segment stretching 10km off to the west (at dash+gap=1.2m that's
    # over 8000 dashes if not culled), then a short segment actually
    # crossing the visible area near the camera.
    railing = Railing(
        points_m=[(-9900.0, 100.0), (80.0, 100.0), (120.0, 100.0)],
        bbox=(-9900.0, 100.0, 120.0, 100.0),
    )

    draw_calls = []
    real_line = pygame.draw.line
    try:
        pygame.draw.line = lambda *a, **k: (draw_calls.append(1), real_line(*a, **k))[1]
        draw_railings(surf, [railing], camx=100.0, camy=100.0, px_per_m=8.0, screen_w=800, screen_h=600)
    finally:
        pygame.draw.line = real_line
    pygame.quit()

    # The visible ~120m segment alone draws on the order of dozens of
    # dashes; if the far-off-screen 10km segment wasn't culled it would
    # add thousands more.
    assert len(draw_calls) < 200
