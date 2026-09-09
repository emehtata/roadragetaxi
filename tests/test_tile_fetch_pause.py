"""Tests for the loading-screen pause while a background tile fetch is in flight."""
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


class _StuckAutoFetchManager:
    """Simulates a fetch that never completes (e.g. a hung connection)."""

    def get_fetching(self) -> bool:
        return True

    def get_progress(self) -> float:
        return 0.1


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
        started = time.monotonic()
        _wait_for_active_tile_fetch(manager, clock, screen, font, "en", deadline_s=5.0)
        elapsed = time.monotonic() - started

        assert manager._remaining == 0, "did not wait for the fetch to finish"
        assert elapsed < 5.0, "waited past what the fetch actually needed"
    finally:
        pygame.quit()


def test_wait_for_active_tile_fetch_gives_up_after_its_deadline():
    """Regression: a genuinely stuck fetch (e.g. a hung connection, well
    under the fetch's own 60s-per-attempt HTTP timeout) must not freeze the
    game outright - the wait has its own bounded deadline."""
    screen, font, clock = _screen_and_font()
    try:
        started = time.monotonic()
        _wait_for_active_tile_fetch(_StuckAutoFetchManager(), clock, screen, font, "en", deadline_s=0.1)
        elapsed = time.monotonic() - started

        assert elapsed < 2.0, "did not honor the wait deadline"
    finally:
        pygame.quit()
