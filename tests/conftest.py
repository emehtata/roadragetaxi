import os
import sys

# Ensure src/ is on sys.path so tests can import the package without installing it.
ROOT = os.path.dirname(os.path.dirname(__file__))
src = os.path.join(ROOT, "src")
if src not in sys.path:
    sys.path.insert(0, src)

import pytest


@pytest.fixture(autouse=True)
def _reset_static_render_cache_throttle():
    """Reset the shared per-frame static-cache rebuild budget before every
    test. Real gameplay resets this exactly once per rendered frame via
    render.begin_static_cache_frame(); tests that call draw_*() functions
    directly don't get that natural reset between each other, since the
    throttle counter and cache surfaces live in module-level globals shared
    across the whole test process. Without this, a test can be spuriously
    denied the cache rebuild its own scene legitimately needs just because
    an earlier, unrelated test already spent this "frame's" one-rebuild
    allowance drawing a completely different scene.
    """
    from theroadragetrip.render import common as _render_common

    _render_common.begin_static_cache_frame()
    yield


@pytest.fixture(autouse=True)
def _reset_incremental_rebuild_state():
    """Reset roads' and buildings' cache state (committed cache + any
    in-progress incremental rebuild) before every test.

    Unlike every other static-cache layer, draw_ways()/draw_buildings()
    only do their full, unbounded rebuild synchronously in one call when
    there is no committed cache at all yet (see draw_ways' docstring) -
    otherwise they advance an incremental rebuild by a small time budget
    per call, same as real gameplay across frames. Without this reset, a
    test running after any earlier test that already committed *some*
    cache (a near-certainty in a full test-process run) would see a
    non-None cache and take the incremental path from its very first call
    - fine for the small scenes most tests draw (still finishes within one
    call's time budget), but a real, load-order-dependent flakiness risk
    for any test with enough visible ways/buildings that it doesn't. Real
    gameplay never has this problem: there's always exactly one true
    "first ever build" per process.
    """
    from theroadragetrip.render import common as _render_common
    from theroadragetrip.render import roads as _render_roads
    from theroadragetrip.render import buildings as _render_buildings
    from theroadragetrip.render import scenery as _render_scenery

    _render_common._road_frame_cache_key = None
    _render_common._road_frame_cache_surface = None
    _render_common._road_frame_cache_camera = None
    _render_roads._road_wip = None
    _render_common._building_frame_cache_key = None
    _render_common._building_frame_cache_surface = None
    _render_common._building_frame_cache_camera = None
    _render_buildings._building_wip = None
    _render_common._scenery_frame_cache_key = None
    _render_common._scenery_frame_cache_surface = None
    _render_common._scenery_frame_cache_camera = None
    _render_scenery._scenery_wip = None
    yield


@pytest.fixture(autouse=True)
def _reset_solar_position_cache():
    """Clear the shared sun-position cache before every test.

    solar_altitude_and_events() now caches by (lat, lon) only, refreshing
    at most once per SOLAR_UPDATE_INTERVAL_SECONDS of real time (not
    keyed by game_time_seconds) - without this, a test could get another
    test's stale cached result for the same default lat/lon just because
    it ran within that real-time window, not because the sun actually
    hasn't moved.
    """
    from theroadragetrip.render import common as _render_common

    _render_common._solar_position_cache.clear()
    yield


@pytest.fixture(autouse=True)
def _reset_puddle_cache():
    """Clear the shared id(way) -> puddle-spot cache before every test.

    Keyed by id(way), which Python can reuse for an unrelated Way once an
    earlier test's object is garbage collected - without this, a later
    test could spuriously inherit a stale puddle spot for a different way
    that happens to land on the same id().
    """
    from theroadragetrip.render import weather as _render_weather

    _render_weather._puddle_cache.clear()
    yield
