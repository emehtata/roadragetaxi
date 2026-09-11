"""Regression tests for scenery.py's incremental static-cache rebuild -
the same mechanism as roads.py's/buildings.py's (see
tests/test_incremental_road_rebuild.py and render/roads.py's _road_wip
docstring), applied to draw_scenery after a real drive showed its ordinary
rebuild routinely costing 15-77ms on its own, well past a single frame's
16.67ms budget.
"""
import pygame

from theroadragetrip.osm import Scenery
from theroadragetrip.render import common as common_module
from theroadragetrip.render import scenery as scenery_module
from theroadragetrip.render.scenery import draw_scenery


def _make_sceneries(count: int, spacing: float = 20.0) -> list:
    """`count` small square parcels spread along a line, close enough
    together that all of them land in view at once."""
    sceneries = []
    for i in range(count):
        x = i * spacing
        pts = [(x, 0.0), (x + 8.0, 0.0), (x + 8.0, 8.0), (x, 8.0)]
        sceneries.append(Scenery(pts, "commercial", bbox=(x, 0.0, x + 8.0, 8.0)))
    return sceneries


def test_first_ever_build_stays_synchronous():
    """The very first scenery-cache build (nothing committed yet to fall
    back to) must still finish in one call - nothing to show in the
    meantime regardless of scene size, same as every other layer's own
    no-existing-cache exemption."""
    sceneries = _make_sceneries(80)
    screen = pygame.Surface((300, 200), pygame.SRCALPHA)

    draw_scenery(screen, sceneries, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)

    assert scenery_module._scenery_wip is None
    assert common_module._scenery_frame_cache_surface is not None


def test_rebuild_spreads_across_multiple_calls_and_makes_guaranteed_progress(monkeypatch):
    """A rebuild that can't finish in one time-budgeted chunk must resume
    exactly where it left off on the next call (never restart from zero),
    and must make real, monotonic progress every single call - even with
    the smallest possible budget - so it can never get permanently stuck."""
    monkeypatch.setattr(scenery_module, "INCREMENTAL_REBUILD_BUDGET_S", 0.0)
    sceneries = _make_sceneries(40)
    screen = pygame.Surface((300, 200), pygame.SRCALPHA)

    # A trivial first-ever build so the *real* scene's first call already
    # takes the incremental path, not the no-existing-cache exemption.
    draw_scenery(screen, [], 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    assert scenery_module._scenery_wip is None

    draw_scenery(screen, sceneries, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    assert scenery_module._scenery_wip is not None, "a 0-budget, 40-scenery rebuild must not finish in one call"
    assert scenery_module._scenery_wip["index"] == 1, "a 0 budget must still draw exactly one scenery per call"

    previous_index = scenery_module._scenery_wip["index"]
    calls = 1
    while scenery_module._scenery_wip is not None:
        draw_scenery(screen, sceneries, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
        calls += 1
        if scenery_module._scenery_wip is not None:
            assert scenery_module._scenery_wip["index"] == previous_index + 1, (
                "progress must be monotonic, one scenery per call at this budget - "
                "no restart, no stall, no skipping"
            )
            previous_index = scenery_module._scenery_wip["index"]
        assert calls <= len(sceneries) + 1, "rebuild did not converge - looks permanently stuck"

    assert calls == len(sceneries)
    assert common_module._scenery_frame_cache_surface is not None


def test_stale_cache_keeps_blitting_while_a_rebuild_is_in_progress(monkeypatch):
    """While a rebuild is mid-flight, draw_scenery() must still blit the
    previous, fully-drawn cache rather than leaving the destination screen
    untouched or showing a half-drawn surface with missing scenery."""
    monkeypatch.setattr(scenery_module, "INCREMENTAL_REBUILD_BUDGET_S", 0.0)
    screen = pygame.Surface((300, 200), pygame.SRCALPHA)
    empty_color = (0, 0, 0, 0)

    first_scenery = Scenery(
        [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
        "commercial",
        bbox=(-10.0, -10.0, 10.0, 10.0),
    )
    draw_scenery(screen, [first_scenery], 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    assert scenery_module._scenery_wip is None
    first_cache_surface = common_module._scenery_frame_cache_surface
    assert first_cache_surface is not None

    many_sceneries = _make_sceneries(30)
    draw_scenery(screen, many_sceneries, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)

    assert scenery_module._scenery_wip is not None, "expected the bigger scene to still be mid-rebuild"
    assert common_module._scenery_frame_cache_surface is first_cache_surface, (
        "the previous cache must stay committed until the new one actually finishes"
    )
    assert screen.get_at((150, 100))[:3] != empty_color[:3]


def test_camera_jump_discards_an_in_progress_rebuild_instead_of_getting_stuck(monkeypatch):
    """A genuine camera jump (or any other cause of the cache key changing
    before a rebuild finishes) must discard the now-irrelevant in-progress
    job and start a fresh one for the new key - not keep trying to finish
    a rebuild for a camera position that's no longer current."""
    monkeypatch.setattr(scenery_module, "INCREMENTAL_REBUILD_BUDGET_S", 0.0)
    sceneries = _make_sceneries(40)
    screen = pygame.Surface((300, 200), pygame.SRCALPHA)

    draw_scenery(screen, [], 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    draw_scenery(screen, sceneries, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    assert scenery_module._scenery_wip is not None
    stale_key = scenery_module._scenery_wip["key"]

    draw_scenery(screen, sceneries, 5000.0, 5000.0, px_per_m=2.0, screen_w=300, screen_h=200)

    assert scenery_module._scenery_wip is not None
    assert scenery_module._scenery_wip["key"] != stale_key, "must have restarted for the new position"
    assert scenery_module._scenery_wip["index"] <= 1, "a freshly restarted job must not carry over old progress"
