"""Regression tests: pedestrians and cyclists hidden behind a higher-layer
way (a bridge above them) must be drawn as an outline, not skipped entirely.

draw_car/draw_npc_cars already do this (see _covered_by_higher_road /
_vehicle_is_on_bridge / _draw_vehicle_outline in render/common.py and
render/vehicles.py) - draw_pedestrians and draw_cyclists used to just
`continue` in this case, so a pedestrian or cyclist walking/riding under a
bridge vanished completely instead of staying visible-enough-to-notice,
same requirement occlusion.md's #7 calls out for every entity type."""
import pygame

from theroadragetrip.osm import Way
from theroadragetrip.pedestrian import Pedestrian
from theroadragetrip.render import draw_cyclists, draw_pedestrians


def _make_ways():
    ground = Way(points_m=[(0.0, -50.0), (0.0, 50.0)], highway="footway", half_width_m=1.5, is_drivable=False)
    bridge = Way(
        points_m=[(-50.0, 0.0), (50.0, 0.0)],
        highway="cycleway",
        half_width_m=3.0,
        is_drivable=False,
        is_bridge=True,
        layer=1,
    )
    return ground, bridge


def test_pedestrian_under_a_bridge_is_outlined_not_invisible():
    pygame.init()
    ground, bridge = _make_ways()
    pedestrian = Pedestrian(0.0, 0.0, 0.0, 0.0, 1.0, ground, 0, 1, (200, 50, 50))
    screen = pygame.Surface((400, 400))
    screen.fill((0, 0, 0))

    draw_pedestrians(screen, [pedestrian], camx=0.0, camy=0.0, px_per_m=8.0, ways=[ground, bridge], screen_w=400, screen_h=400)

    outline_color = (235, 235, 235)
    assert any(
        tuple(screen.get_at((x, y)))[:3] == outline_color
        for x in range(150, 250)
        for y in range(150, 250)
    ), "occluded pedestrian must still draw an outline, not vanish"
    pygame.quit()


def test_pedestrian_not_under_a_bridge_still_renders_normally():
    pygame.init()
    ground, bridge = _make_ways()
    pedestrian = Pedestrian(0.0, 200.0, 0.0, 0.0, 1.0, ground, 0, 1, (200, 50, 50))
    screen = pygame.Surface((400, 400))
    screen.fill((0, 0, 0))

    draw_pedestrians(screen, [pedestrian], camx=0.0, camy=200.0, px_per_m=8.0, ways=[ground, bridge], screen_w=400, screen_h=400)

    # Far from the bridge way - must not be reduced to the occlusion outline.
    outline_color = (235, 235, 235)
    assert not any(
        tuple(screen.get_at((x, y)))[:3] == outline_color
        for x in range(150, 250)
        for y in range(150, 250)
    )
    pygame.quit()


def test_cyclist_under_a_bridge_is_outlined_not_invisible():
    pygame.init()
    ground, bridge = _make_ways()
    cyclist = Pedestrian(0.0, 0.0, 0.0, 0.0, 1.0, ground, 0, 1, (50, 50, 200), is_cyclist=True)
    screen = pygame.Surface((400, 400))
    screen.fill((0, 0, 0))

    draw_cyclists(screen, [cyclist], camx=0.0, camy=0.0, px_per_m=8.0, ways=[ground, bridge], screen_w=400, screen_h=400)

    outline_color = (235, 235, 235)
    assert any(
        tuple(screen.get_at((x, y)))[:3] == outline_color
        for x in range(150, 250)
        for y in range(150, 250)
    ), "occluded cyclist must still draw an outline, not vanish"
    pygame.quit()
