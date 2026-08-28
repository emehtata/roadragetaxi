"""Tests for pause menu rendering and navigation."""
import os
import pygame
from theroadragetrip.render import SCREEN_W, SCREEN_H, draw_pause_menu


def test_draw_pause_menu_headless():
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    font = pygame.font.SysFont(None, 24)

    options = ["Continue Game", "Change City", "Exit Game"]
    # Verify drawing with option 0 selected
    draw_pause_menu(screen, font, options, selected_idx=0, screen_w=SCREEN_W, screen_h=SCREEN_H)
    # Verify drawing with option 1 selected
    draw_pause_menu(screen, font, options, selected_idx=1, screen_w=SCREEN_W, screen_h=SCREEN_H)
    pygame.quit()
