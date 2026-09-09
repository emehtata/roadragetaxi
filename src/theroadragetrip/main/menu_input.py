import logging
from typing import Optional, Tuple

import pygame



logger = logging.getLogger(__name__)


CITY_MENU_KEYS = "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _city_menu_index(key: int, city_count: int) -> Optional[int]:
    """Return the city index for a menu shortcut key."""
    index = next(
        (index for index, shortcut in enumerate(CITY_MENU_KEYS)
         if key in (getattr(pygame, f"K_{shortcut.lower()}"),
                    getattr(pygame, f"K_KP{shortcut}") if shortcut.isdigit() else -1)),
        None,
    )
    if index is None:
        return None
    return index if index < city_count else None


def _respawn_allowed(on_foot: bool) -> bool:
    """Only allow taxi respawn while the driver is in the taxi."""
    return not on_foot


# Keep in sync with draw_mode_selection_menu()'s options list
# (career, gig_driver, reset_career, clear_cache).
MODE_MENU_OPTION_COUNT = 4


def _mode_menu_navigate(current: int, direction: int) -> int:
    """Cycle the mode-selection menu's highlighted option, wrapping around.

    Regression: this used to hardcode a modulo of 3 while the menu has 4
    options, so arrow-key navigation could never reach the last one
    (clear_cache) - only a mouse click, or the undocumented "4" shortcut
    key, could select it.
    """
    return (current + direction) % MODE_MENU_OPTION_COUNT


def _menu_item_at_y(pos_y: int, start_y: int, item_h: int, gap_y: int, count: int) -> Optional[int]:
    for index in range(count):
        item_y = start_y + index * (item_h + gap_y)
        if item_y <= pos_y <= item_y + item_h:
            return index
    return None


def _city_item_at(pos: Tuple[int, int], city_count: int, screen_w: int) -> Optional[int]:
    cols = 2
    rows = (city_count + cols - 1) // cols
    item_w, item_h = 320, 42
    gap_x, gap_y = 24, 10
    total_w = cols * item_w + (cols - 1) * gap_x
    start_x, start_y = (screen_w - total_w) // 2, 115
    x, y = pos
    col = (x - start_x) // (item_w + gap_x)
    row = (y - start_y) // (item_h + gap_y)
    if not (0 <= col < cols and 0 <= row < rows):
        return None
    item_x = start_x + col * (item_w + gap_x)
    item_y = start_y + row * (item_h + gap_y)
    if item_x <= x <= item_x + item_w and item_y <= y <= item_y + item_h:
        index = col * rows + row
        return index if index < city_count else None
    return None


def _city_horizontal_index(index: int, direction: int, city_count: int) -> int:
    rows = (city_count + 1) // 2
    return (index + direction * rows) % city_count


def _city_refresh_at(pos: Tuple[int, int], screen_w: int, screen_h: int, city_count: int) -> bool:
    cols = 2
    rows = (city_count + cols - 1) // cols
    item_h = 42
    gap_y = 10
    checkbox_rect = pygame.Rect(screen_w // 2 - 150, 115 + rows * (item_h + gap_y) + 12, 22, 22)
    return checkbox_rect.collidepoint(pos)


def _city_edit_at(pos: Tuple[int, int], screen_w: int, screen_h: int, city_count: int) -> bool:
    rows = (city_count + 1) // 2
    top = 115 + rows * 52 + 12 + 38
    return pygame.Rect(screen_w // 2 - 150, top, 300, 36).collidepoint(pos)


def _pause_item_at(pos: Tuple[int, int], option_count: int, screen_w: int, screen_h: int) -> Optional[int]:
    panel_w = min(420, screen_w - 40)
    panel_h = min(screen_h - 40, max(280, 110 + option_count * 56))
    panel_x, panel_y = (screen_w - panel_w) // 2, (screen_h - panel_h) // 2
    item_w, item_h = 340, 44
    item_x = panel_x + (panel_w - item_w) // 2
    if not (item_x <= pos[0] <= item_x + item_w):
        return None
    return _menu_item_at_y(pos[1], panel_y + 80, item_h, 12, option_count)


def _city_editor_suggestion_at(pos: Tuple[int, int], suggestion_count: int, screen_w: int, screen_h: int) -> Optional[int]:
    rows = 5
    input_y = 72 + rows * 46 + 20
    input_rect = (screen_w // 2 - 250, input_y, 500, 42)
    if not (input_rect[0] <= pos[0] <= input_rect[0] + input_rect[2] and input_rect[1] <= pos[1] <= input_rect[1] + input_rect[3] + 8):
        return None
    index = (pos[1] - input_rect[1] - input_rect[3] - 8) // 34
    return index if 0 <= index < suggestion_count else None


def _city_editor_item_at(pos: Tuple[int, int], city_count: int, screen_w: int) -> Optional[int]:
    cols = 2
    rows = (city_count + cols - 1) // cols
    item_w, item_h, gap_x, gap_y = 300, 38, 20, 8
    start_x, start_y = (screen_w - (2 * item_w + gap_x)) // 2, 72
    x, y = pos
    col = (x - start_x) // (item_w + gap_x)
    row = (y - start_y) // (item_h + gap_y)
    if not (0 <= col < cols and 0 <= row < rows):
        return None
    item_x = start_x + col * (item_w + gap_x)
    item_y = start_y + row * (item_h + gap_y)
    if item_x <= x <= item_x + item_w and item_y <= y <= item_y + item_h:
        index = col * rows + row
        return index if index < city_count else None
    return None
