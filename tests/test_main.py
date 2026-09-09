import pygame

from theroadragetrip.main import (
    _city_horizontal_index,
    _city_menu_index,
    _mode_menu_navigate,
    _respawn_allowed,
    MODE_MENU_OPTION_COUNT,
)


def test_respawn_is_blocked_while_driver_is_on_foot():
    assert _respawn_allowed(True) is False
    assert _respawn_allowed(False) is True


def test_city_menu_supports_numeric_and_letter_shortcuts():
    assert _city_menu_index(pygame.K_0, 18) == 9
    assert _city_menu_index(pygame.K_a, 18) == 10
    assert _city_menu_index(pygame.K_h, 18) == 17
    assert _city_menu_index(pygame.K_i, 18) is None


def test_city_menu_horizontal_navigation_moves_between_columns():
    assert _city_horizontal_index(0, 1, 18) == 9
    assert _city_horizontal_index(9, -1, 18) == 0
    assert _city_horizontal_index(8, 1, 18) == 17


def test_mode_menu_arrow_navigation_reaches_every_option():
    """Regression: arrow-key navigation used to wrap modulo 3 while the
    mode menu has 4 options, so the last one (clear_cache) could never be
    reached by keyboard - only a mouse click, or the undocumented "4"
    shortcut key, could select it."""
    reachable = set()
    index = 0
    for _ in range(MODE_MENU_OPTION_COUNT):
        reachable.add(index)
        index = _mode_menu_navigate(index, 1)
    assert reachable == set(range(MODE_MENU_OPTION_COUNT))

    # Wrapping in both directions lands back where it started.
    assert _mode_menu_navigate(MODE_MENU_OPTION_COUNT - 1, 1) == 0
    assert _mode_menu_navigate(0, -1) == MODE_MENU_OPTION_COUNT - 1
