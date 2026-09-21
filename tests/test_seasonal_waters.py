import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from theroadragetrip.calendar import Season
from theroadragetrip.osm import Water
from theroadragetrip.render.waters import (
    SPRING_ICE_COLORS,
    WATER_COLOR,
    WINTER_ICE_COLOR,
    _draw_waters_uncached,
)


def _lake() -> Water:
    return Water(
        [(-50, -50), (50, -50), (50, 50), (-50, 50), (-50, -50)],
        kind="water",
        is_polygon=True,
        bbox=(-50, -50, 50, 50),
    )


def _render(season: Season) -> pygame.Surface:
    pygame.init()
    screen = pygame.Surface((300, 300))
    screen.fill((1, 2, 3))
    _draw_waters_uncached(
        screen, [_lake()], 0, 0, px_per_m=2.0,
        screen_w=300, screen_h=300, season=season,
    )
    return screen


def test_winter_water_is_an_opaque_white_ice_surface():
    winter = _render(Season.WINTER)
    assert winter.get_at((150, 150))[:3] == WINTER_ICE_COLOR
    assert WATER_COLOR not in {winter.get_at((x, y))[:3] for x in range(75, 226) for y in range(75, 226)}


def test_spring_water_stays_open_with_occasional_ice_plates():
    spring = _render(Season.SPRING)
    colors = {spring.get_at((x, y))[:3] for x in range(50, 251) for y in range(50, 251)}
    assert WATER_COLOR in colors
    assert colors.intersection(SPRING_ICE_COLORS)
    assert spring.get_at((150, 150))[:3] != WINTER_ICE_COLOR
