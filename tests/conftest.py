import os
import sys

# Ensure src/ is on sys.path so tests can import the package without installing it.
ROOT = os.path.dirname(os.path.dirname(__file__))
src = os.path.join(ROOT, "src")
if src not in sys.path:
    sys.path.insert(0, src)

import pytest


@pytest.fixture(autouse=True)
def _reset_overpass_endpoint_cooldowns():
    """Clear both Overpass endpoint-cooldown maps before every test.

    Keyed by URL, shared across the whole test process - without this, a
    test that hits e.g. "https://mirror.example/api" could inherit a
    cooldown (rate-limit or courtesy) another, unrelated test left behind
    for the same URL, spuriously changing which endpoint a later fetch
    picks.
    """
    from theroadragetrip.osm import overpass as _overpass

    _overpass._endpoint_cooldown_until.clear()
    _overpass._endpoint_last_contact.clear()
    yield


@pytest.fixture(autouse=True)
def _no_timetable_refresh(monkeypatch, tmp_path):
    """Tests use the bundled timetable and never download a new one."""
    from theroadragetrip import train_timetable, world_loader

    monkeypatch.setattr(train_timetable, "USER_TIMETABLE_PATH", tmp_path / "no-user-timetable.json.gz")
    monkeypatch.setattr(world_loader, "refresh_if_stale", lambda document: None)
