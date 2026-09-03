import pygame

from theroadragetrip.main import _city_horizontal_index, _city_menu_index, _respawn_allowed


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
