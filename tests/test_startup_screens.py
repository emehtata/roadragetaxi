"""Tests for the outdated-cache confirmation dialog shown at startup."""
import os
from datetime import date, datetime

import pygame
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from theroadragetrip.main.startup_screens import (
    _clamp_start_datetime,
    _date_field_arrow_rects,
    _one_calendar_year_ago,
    confirm_outdated_cache,
)


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


def test_calendar_picker_date_range_is_only_one_year_backwards():
    today = date(2026, 9, 23)
    assert _one_calendar_year_ago(today) == date(2025, 9, 23)
    assert _clamp_start_datetime(datetime(2020, 1, 1, 12, 30), today) == datetime(2025, 9, 23, 12, 30)
    assert _clamp_start_datetime(datetime(2027, 1, 1, 8, 15), today) == datetime(2026, 9, 23, 8, 15)


def test_calendar_picker_one_year_back_handles_leap_day():
    assert _one_calendar_year_ago(date(2024, 2, 29)) == date(2023, 2, 28)


def test_calendar_picker_has_separate_clickable_arrow_regions():
    field = pygame.Rect(100, 200, 380, 44)
    left, right = _date_field_arrow_rects(field)
    assert field.contains(left)
    assert field.contains(right)
    assert left.right < right.left


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
