import pygame

from theroadragetrip.main import (
    _city_horizontal_index,
    _city_menu_index,
    _mode_menu_navigate,
    _rage_from_speeding,
    _respawn_allowed,
    MODE_MENU_OPTION_COUNT,
)


def test_respawn_is_blocked_while_driver_is_on_foot():
    assert _respawn_allowed(True) is False
    assert _respawn_allowed(False) is True


def test_speeding_builds_rage():
    limit_mps = 50.0 / 3.6  # 50 km/h
    rage = _rage_from_speeding(0.0, speed_mps=70.0 / 3.6, road_limit_mps=limit_mps, driven_distance_m=100.0)
    assert rage > 0.0


def test_driving_under_the_limit_reduces_rage():
    limit_mps = 50.0 / 3.6
    rage = _rage_from_speeding(0.5, speed_mps=30.0 / 3.6, road_limit_mps=limit_mps, driven_distance_m=100.0)
    assert rage < 0.5


def test_rage_from_speeding_is_clamped_to_0_1():
    limit_mps = 50.0 / 3.6
    assert _rage_from_speeding(0.99, speed_mps=90.0 / 3.6, road_limit_mps=limit_mps, driven_distance_m=1000.0) == 1.0
    assert _rage_from_speeding(0.01, speed_mps=10.0 / 3.6, road_limit_mps=limit_mps, driven_distance_m=1000.0) == 0.0


def test_rage_unaffected_without_a_known_speed_limit():
    assert _rage_from_speeding(0.4, speed_mps=100.0, road_limit_mps=None, driven_distance_m=100.0) == 0.4


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
