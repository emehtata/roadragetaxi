"""Tests for the outdated-cache confirmation dialog shown at startup."""
import os

import pygame
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from theroadragetrip.main.startup_screens import confirm_outdated_cache


class _StopDraw(Exception):
    """Raised from a patched pygame.display.flip() to inspect one drawn frame."""


def _screen_font_clock():
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    font = pygame.font.SysFont(None, 24)
    clock = pygame.time.Clock()
    return screen, font, clock


def _button_rects(screen):
    button_width, button_height = 130, 42
    screen_w, screen_h = screen.get_size()
    ok_rect = pygame.Rect(screen_w // 2 - button_width - 10, screen_h // 2 + 55, button_width, button_height)
    cancel_rect = pygame.Rect(screen_w // 2 + 10, screen_h // 2 + 55, button_width, button_height)
    return ok_rect, cancel_rect


def test_enter_confirms_ok_by_default():
    screen, font, clock = _screen_font_clock()
    try:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        assert confirm_outdated_cache(screen, font, clock, "en") is True
    finally:
        pygame.quit()


def test_arrow_keys_move_selection_to_cancel():
    """Regression: Enter used to always confirm OK regardless of arrow-key
    navigation, and neither button showed which one was selected - so a
    keyboard user had no way to tell (or actually choose) Cancel."""
    screen, font, clock = _screen_font_clock()
    try:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        with pytest.raises(SystemExit):
            confirm_outdated_cache(screen, font, clock, "en")
    finally:
        pygame.quit()


def test_arrow_keys_round_trip_back_to_ok():
    screen, font, clock = _screen_font_clock()
    try:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT))
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        assert confirm_outdated_cache(screen, font, clock, "en") is True
    finally:
        pygame.quit()


def test_selected_button_is_visibly_highlighted():
    """Regression: neither button showed which one was selected, making
    the dialog look mouse-only even though keyboard activation worked -
    the selected button must render with the same gold accent border
    used to mark the selected item in the other menus."""
    screen, font, clock = _screen_font_clock()
    try:
        orig_flip = pygame.display.flip
        pygame.display.flip = lambda: (_ for _ in ()).throw(_StopDraw())
        try:
            with pytest.raises(_StopDraw):
                confirm_outdated_cache(screen, font, clock, "en")
        finally:
            pygame.display.flip = orig_flip

        ok_rect, cancel_rect = _button_rects(screen)
        gold = (255, 215, 95)
        assert screen.get_at((ok_rect.left + 1, ok_rect.centery))[:3] == gold
        assert screen.get_at((cancel_rect.left + 1, cancel_rect.centery))[:3] != gold
    finally:
        pygame.quit()
