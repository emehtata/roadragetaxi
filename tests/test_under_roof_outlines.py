"""People and trains under an open roof (a station platform canopy) are
outlined on top of it, everyone else is left alone."""
from types import SimpleNamespace

import pygame

from theroadragetrip.pedestrian import PlayerPedestrian
from theroadragetrip.render.buildings import RoofCover, draw_open_roof_overlays
from theroadragetrip.render.pedestrians import PLAYER_OUTLINE_COLOR, UNDER_ROOF_OUTLINE_COLOR, draw_pedestrians_under_roofs
from theroadragetrip.render.vehicles import UNDER_ROOF_TRAIN_OUTLINE_COLOR, draw_trains

ROOF = SimpleNamespace(points_m=[(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
                       building_type="roof", bbox=(-10.0, -10.0, 10.0, 10.0))
W = H = 400


def count(screen, color):
    return sum(1 for x in range(0, W) for y in range(0, H) if screen.get_at((x, y))[:3] == color)


def test_roof_cover_knows_what_is_underneath():
    cover = RoofCover([ROOF])
    assert cover.covers(0.0, 5.0) and not cover.covers(15.0, 0.0)
    assert not RoofCover([])


def test_people_under_the_roof_are_outlined_over_it_the_driver_in_yellow():
    screen = pygame.Surface((W, H))
    cover = draw_open_roof_overlays(screen, [ROOF], 0.0, 0.0, px_per_m=10.0, screen_w=W, screen_h=H)
    under = SimpleNamespace(x=-5.0, y=0.0, radius_m=0.45)
    outside = SimpleNamespace(x=15.0, y=0.0, radius_m=0.45)
    driver = PlayerPedestrian(x=5.0, y=0.0)
    driver.is_player = True
    draw_pedestrians_under_roofs(screen, [under, outside, driver], cover, 0.0, 0.0, 10.0, W, H)
    assert count(screen, UNDER_ROOF_OUTLINE_COLOR) > 0 and count(screen, PLAYER_OUTLINE_COLOR) > 0
    assert screen.get_at((350, 200))[:3] != UNDER_ROOF_OUTLINE_COLOR  # outside: left to draw_pedestrians


def test_train_under_the_roof_is_only_outlined():
    route = SimpleNamespace()
    train = SimpleNamespace(vehicles=lambda: [(0.0, 0.0, 0.0, 12.0, "standard")], service=None, route=route)
    railway = SimpleNamespace(trains=[train], routes=[])
    screen = pygame.Surface((W, H))
    draw_trains(screen, railway, 0.0, 0.0, px_per_m=10.0, screen_w=W, screen_h=H, roof_cover=RoofCover([ROOF]))
    assert count(screen, UNDER_ROOF_TRAIN_OUTLINE_COLOR) > 0
    assert screen.get_at((200, 200))[:3] == (0, 0, 0)  # the middle stays unfilled: the roof shows through
