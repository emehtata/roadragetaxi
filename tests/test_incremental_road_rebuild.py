"""Regression tests for roads.py's incremental static-cache rebuild
(see SMOOTHNESS.md / render/roads.py's _road_wip docstring).

Unlike every other static-cache layer, a stale roads cache does not
rebuild atomically the one frame its turn comes up - a real drive showed
that costing 15-40ms on its own, well past a single frame's 16.67ms
budget, every time the camera crossed a cache-grid boundary (~once a
second while driving). draw_ways() now spreads a rebuild across as many
calls as it needs, in small time-budgeted chunks, while continuing to
blit the last fully-drawn cache in the meantime.
"""
import pygame
import pytest

from theroadragetrip.osm import Way
from theroadragetrip.render import common as common_module
from theroadragetrip.render import roads as roads_module
from theroadragetrip.render.roads import draw_ways


def _make_ways(count: int, spacing: float = 8.0) -> list:
    """`count` short, parallel residential segments, close enough together
    that all of them land in view at once."""
    return [
        Way(points_m=[(0.0, y), (30.0, y)], highway="residential", half_width_m=3.0)
        for y in (i * spacing for i in range(count))
    ]


def test_first_ever_build_stays_synchronous():
    """The very first roads-cache build (nothing committed yet to fall
    back to) must still finish in one call, exactly like every other
    layer's own no-existing-cache exemption - there's nothing to show in
    the meantime regardless of how large the scene is."""
    ways = _make_ways(80)
    screen = pygame.Surface((300, 200), pygame.SRCALPHA)

    draw_ways(screen, ways, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)

    assert roads_module._road_wip is None
    assert common_module._road_frame_cache_surface is not None


def _wip_progress(job: dict) -> tuple:
    """Total progress markers across both of a WIP's chunked stages
    (endpoint-join precompute, then per-way drawing) - a single
    comparable measure of "how far along is this job", since a 0-budget
    call advances exactly one of the two, never both."""
    return (job["endpoint_progress"], job["index"])


def test_rebuild_spreads_across_multiple_calls_and_makes_guaranteed_progress(monkeypatch):
    """A rebuild that can't finish in one time-budgeted chunk must resume
    exactly where it left off on the next call (never restart from zero),
    and must make real, monotonic progress every single call - even with
    the smallest possible budget - so it can never get permanently stuck."""
    monkeypatch.setattr(roads_module, "INCREMENTAL_REBUILD_BUDGET_S", 0.0)
    ways = _make_ways(40)
    screen = pygame.Surface((300, 200), pygame.SRCALPHA)

    # A trivial first-ever build so the *real* scene's first call already
    # takes the incremental path, not the no-existing-cache exemption.
    draw_ways(screen, [], 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    assert roads_module._road_wip is None

    draw_ways(screen, ways, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    assert roads_module._road_wip is not None, "a 0-budget, 40-way rebuild must not finish in one call"
    assert roads_module._road_wip["endpoint_progress"] == 1, (
        "a 0 budget must still process exactly one endpoint on the first call, not zero"
    )

    previous_progress = _wip_progress(roads_module._road_wip)
    # Upper bound: one endpoint-join step per way endpoint, plus one
    # drawing step per way, plus slack - a real, finite ceiling, not an
    # arbitrarily large "just in case" number.
    max_calls = len(roads_module._road_wip["endpoints"]) + len(ways) + 2
    calls = 1
    while roads_module._road_wip is not None:
        draw_ways(screen, ways, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
        calls += 1
        if roads_module._road_wip is not None:
            progress = _wip_progress(roads_module._road_wip)
            assert progress > previous_progress, (
                "no forward progress this call - looks stalled, not just slow"
            )
            previous_progress = progress
        assert calls <= max_calls, "rebuild did not converge within its own known bound - looks permanently stuck"

    assert calls > 1, "expected this scene to need more than one call at a 0 budget"
    assert common_module._road_frame_cache_surface is not None


def test_stale_cache_keeps_blitting_while_a_rebuild_is_in_progress(monkeypatch):
    """While a rebuild is mid-flight, draw_ways() must still blit the
    previous, fully-drawn cache (positioned correctly for the current
    camera) rather than leaving the destination screen untouched or
    showing a half-drawn surface with missing roads."""
    monkeypatch.setattr(roads_module, "INCREMENTAL_REBUILD_BUDGET_S", 0.0)
    screen = pygame.Surface((300, 200), pygame.SRCALPHA)
    terrain_color = (12, 120, 34)

    first_way = Way(points_m=[(-50.0, 0.0), (50.0, 0.0)], highway="primary", half_width_m=5.0)
    screen.fill(terrain_color)
    draw_ways(screen, [first_way], 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    assert roads_module._road_wip is None
    first_cache_surface = common_module._road_frame_cache_surface
    assert first_cache_surface is not None

    # A bigger, different scene now goes stale and starts an incremental
    # rebuild - but the *previous* cache (first_way) must still render.
    many_ways = _make_ways(30)
    screen.fill(terrain_color)
    draw_ways(screen, many_ways, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)

    assert roads_module._road_wip is not None, "expected the bigger scene to still be mid-rebuild"
    assert common_module._road_frame_cache_surface is first_cache_surface, (
        "the previous cache must stay committed until the new one actually finishes"
    )
    # The road drawn by the *old*, still-committed cache must actually have
    # been blitted onto the screen this frame - not left blank.
    assert screen.get_at((150, 100))[:3] != terrain_color


def test_camera_jump_discards_an_in_progress_rebuild_instead_of_getting_stuck(monkeypatch):
    """A genuine camera jump (or any other cause of the cache key
    changing before a rebuild finishes) must discard the now-irrelevant
    in-progress job and start a fresh one for the new key - not keep
    trying to finish a rebuild for a camera position that's no longer
    current, and not sit stuck forever."""
    monkeypatch.setattr(roads_module, "INCREMENTAL_REBUILD_BUDGET_S", 0.0)
    ways = _make_ways(40)
    screen = pygame.Surface((300, 200), pygame.SRCALPHA)

    draw_ways(screen, [], 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    draw_ways(screen, ways, 0.0, 0.0, px_per_m=2.0, screen_w=300, screen_h=200)
    assert roads_module._road_wip is not None
    stale_key = roads_module._road_wip["key"]

    # A big jump - a respawn/city-change equivalent - lands far enough away
    # that the cache-grid cell (part of the key) is now different.
    draw_ways(screen, ways, 5000.0, 5000.0, px_per_m=2.0, screen_w=300, screen_h=200)

    assert roads_module._road_wip is not None
    assert roads_module._road_wip["key"] != stale_key, "must have restarted for the new position, not kept the stale job"
    assert roads_module._road_wip["index"] <= 1, "a freshly restarted job must not carry over the old job's progress"
