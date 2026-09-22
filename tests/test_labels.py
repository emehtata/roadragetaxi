import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from theroadragetrip.osm import Building, Place
from theroadragetrip.render.labels import _draw_labels_uncached


def _render_building_labels(label_mode: int) -> bytes:
    pygame.init()
    screen = pygame.Surface((400, 300), pygame.SRCALPHA)
    font = pygame.font.Font(None, 20)
    venue = Place(0.0, 0.0, "Kahvila Testi", "cafe")
    building = Building(
        [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)],
        bbox=(-10.0, -10.0, 10.0, 10.0),
        center_m=(0.0, 0.0),
        associated_places=[venue],
    )
    _draw_labels_uncached(
        screen,
        font,
        ways=[],
        waters=[],
        buildings=[building],
        sceneries=[],
        places=[],
        camx=0.0,
        camy=0.0,
        px_per_m=9.0,
        screen_w=400,
        screen_h=300,
        label_mode=label_mode,
    )
    return pygame.image.tostring(screen, "RGBA")


def test_full_label_mode_draws_building_associated_place_names():
    labels_off = _render_building_labels(0)
    roads_only = _render_building_labels(1)
    all_labels = _render_building_labels(2)

    assert roads_only == labels_off
    assert all_labels != labels_off
