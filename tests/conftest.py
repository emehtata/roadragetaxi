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
