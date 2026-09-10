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


def test_build_ways_marks_railway_bridge_yes_as_is_bridge():
    """A rail line tagged bridge=yes (or a positive layer with no bridge
    tag) is a structure spanning whatever's below it, not ground-level
    track - same detection as roads' is_bridge (osm/build.py)."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 30, "nodes": [1, 2], "tags": {"railway": "rail", "bridge": "yes", "layer": "1"}},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.0},
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 31, "nodes": [3, 4], "tags": {"railway": "rail"}},
    ]

    result = build_ways(elements)

    assert len(result.railways) == 2
    assert result.railways[0].is_bridge is True
    assert result.railways[1].is_bridge is False


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


def test_railway_is_bridge_round_trips_through_world_cache(tmp_path):
    """Regression: a Railway loaded from a cached .rwc written before
    is_bridge existed on the dataclass silently reconstructs with
    is_bridge=False (Railway(**record) just uses the field's default for
    a missing key) - no error, no warning. That's exactly what
    FORMAT_VERSION (world_cache.py) exists to catch by forcing a rebuild
    instead of a silent wrong reload; this only confirms today's format
    actually carries the field through, not the version-bump discipline
    itself (see test_stale_format_version_forces_a_rebuild_even_within_
    the_ttl in test_world_cache.py for that)."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 30, "nodes": [1, 2], "tags": {"railway": "rail", "bridge": "yes"}},
    ]
    world = build_ways(elements)
    assert world.railways[0].is_bridge is True
    path = tmp_path / "bridge.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="bridge")
    loaded = BinaryWorldCacheLoader().load(path)

    assert loaded.railways[0].is_bridge is True


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


def test_draw_railways_gives_a_bridge_track_deck_edges():
    """A rail line marked is_bridge must render with the same guardrail
    cue road bridges use (BRIDGE_GUARDRAIL_COLOR) - otherwise a bridge and
    ground-level track look identical, which is exactly the bug this
    covers (a rail bridge over a road rendered as if painted on it)."""
    import pygame
    from theroadragetrip.render.roads import BRIDGE_GUARDRAIL_COLOR
    pygame.init()

    def guardrail_pixel_count(is_bridge: bool) -> int:
        surf = pygame.Surface((800, 600))
        surf.fill((0, 0, 0))
        railway = Railway(
            points_m=[(80.0, 100.0), (120.0, 100.0)],
            bbox=(80.0, 100.0, 120.0, 100.0),
            is_bridge=is_bridge,
        )
        draw_railways(surf, [railway], camx=100.0, camy=100.0, px_per_m=8.0, screen_w=800, screen_h=600)
        return sum(
            1
            for x in range(800)
            for y in range(600)
            if tuple(surf.get_at((x, y)))[:3] == BRIDGE_GUARDRAIL_COLOR
        )

    assert guardrail_pixel_count(is_bridge=False) == 0
    assert guardrail_pixel_count(is_bridge=True) > 0
    pygame.quit()


def test_draw_railways_bridge_deck_is_a_solid_fill_not_just_thin_lines():
    """Regression: rails+ties+edges alone are thin lines with real gaps
    between them - not enough to actually hide something underneath the
    bridge (reported: the taxi still fully visible under a rail bridge
    even with the only_bridges late-redraw pass, because that pass only
    painted the same sparse lines on top of it). The deck needs a solid
    ballast-bed fill spanning its full width, so nothing sentinel-colored
    survives anywhere under a straight, unobstructed stretch of bridge."""
    import pygame
    pygame.init()
    surf = pygame.Surface((800, 600))
    sentinel = (1, 2, 3)
    surf.fill(sentinel)
    railway = Railway(
        points_m=[(50.0, 100.0), (150.0, 100.0)],
        bbox=(50.0, 100.0, 150.0, 100.0),
        is_bridge=True,
    )
    draw_railways(surf, [railway], camx=100.0, camy=100.0, px_per_m=8.0, screen_w=800, screen_h=600)

    # A band around the centerline, away from the segment's own endpoints
    # (ballast fill is only drawn within the visible t-range, and a plain
    # line has flat, not rounded, end caps).
    remaining_sentinel = sum(
        1
        for x in range(300, 500)
        for y in range(290, 311)
        if tuple(surf.get_at((x, y)))[:3] == sentinel
    )
    assert remaining_sentinel == 0
    pygame.quit()


def test_draw_railways_only_bridges_filters_ground_track_and_bridge_track():
    """Regression: main.py draws ground-level track once early (before the
    car) and bridge track again once late (after the car/pedestrians), so
    a bridge actually covers what's underneath it instead of the car
    rendering on top of a bridge it's really driving under (the bug
    reported: a taxi visible through a rail bridge). That split only works
    if only_bridges=False/True actually excludes the other kind - not just
    "renders fine when both are drawn together", which the deck-edges test
    above already covers."""
    import pygame
    from theroadragetrip.render.roads import RAILWAY_RAIL_COLOR
    pygame.init()

    def rail_pixel_count(only_bridges) -> int:
        surf = pygame.Surface((800, 600))
        surf.fill((0, 0, 0))
        ground = Railway(points_m=[(80.0, 100.0), (120.0, 100.0)], bbox=(80.0, 100.0, 120.0, 100.0), is_bridge=False)
        bridge = Railway(points_m=[(80.0, 130.0), (120.0, 130.0)], bbox=(80.0, 130.0, 120.0, 130.0), is_bridge=True)
        draw_railways(
            surf, [ground, bridge], camx=100.0, camy=115.0, px_per_m=8.0, screen_w=800, screen_h=600,
            only_bridges=only_bridges,
        )
        return sum(
            1
            for x in range(800)
            for y in range(600)
            if tuple(surf.get_at((x, y)))[:3] == RAILWAY_RAIL_COLOR
        )

    ground_and_bridge = rail_pixel_count(None)
    only_ground = rail_pixel_count(False)
    only_bridge = rail_pixel_count(True)

    assert only_ground > 0
    assert only_bridge > 0
    assert only_ground < ground_and_bridge
    assert only_bridge < ground_and_bridge
    assert only_ground + only_bridge == ground_and_bridge
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
