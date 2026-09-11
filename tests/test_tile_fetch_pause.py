"""Tests for the loading-screen pause while a background tile fetch is in
flight - the whole point being that this covers the *entire* fetch, with
no small in-HUD progress bar and no gameplay resuming while it's still
running (see the removed "Ladataan maisemaa" bar)."""
import os
import time

import pygame

from theroadragetrip.main import _wait_for_active_tile_fetch


class _FakeAutoFetchManager:
    """get_fetching() reports True for a fixed number of checks, then False -
    like a real background fetch that eventually completes."""

    def __init__(self, fetching_checks: int):
        self._remaining = fetching_checks

    def get_fetching(self) -> bool:
        if self._remaining > 0:
            self._remaining -= 1
            return True
        return False

    def get_progress(self) -> float:
        return 0.5

    def get_progress_message(self) -> str:
        return ""


def _screen_and_font():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    screen = pygame.display.set_mode((320, 240))
    font = pygame.font.SysFont(None, 24)
    clock = pygame.time.Clock()
    return screen, font, clock


def test_wait_for_active_tile_fetch_returns_once_fetch_completes():
    screen, font, clock = _screen_and_font()
    try:
        manager = _FakeAutoFetchManager(fetching_checks=3)
        _wait_for_active_tile_fetch(manager, clock, screen, font, "en")
        assert manager._remaining == 0, "did not wait for the fetch to finish"
    finally:
        pygame.quit()


def test_wait_for_active_tile_fetch_does_not_give_up_early():
    """Regression target: the wait used to have its own UI-level deadline
    (independent of the fetch's real progress) that let gameplay resume
    with the fetch still running, covered by a small in-HUD progress bar.
    That bar is gone now, so the wait itself must not bail out while
    get_fetching() still reports True - only the fetch's own HTTP timeout
    (osm/overpass.py) should ever end it."""
    screen, font, clock = _screen_and_font()
    try:
        # A slow fetch - many checks before it reports done - must still be
        # waited out in full, not cut off after some fixed short window.
        manager = _FakeAutoFetchManager(fetching_checks=50)
        _wait_for_active_tile_fetch(manager, clock, screen, font, "en")
        assert manager._remaining == 0
    finally:
        pygame.quit()
