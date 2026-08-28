"""Tests for pedestrian crossing (suojatie) extraction and rendering."""
import math
from theroadragetrip.osm import Crossing, Way, build_ways
from theroadragetrip.render import draw_crossings


def test_build_ways_extracts_crossings_and_aligns_with_road():
    elements = [
        # Road going East-West (from x=0, y=100 to x=100, y=100)
        {
            "type": "node",
            "id": 1,
            "lat": 65.0,
            "lon": 25.0,
        },
        {
            "type": "node",
            "id": 2,
            "lat": 65.0,
            "lon": 25.01,
        },
        {
            "type": "way",
            "id": 10,
            "nodes": [1, 2],
            "tags": {"highway": "residential", "name": "Torikatu"},
        },
        # Crossing node located near middle of the road
        {
            "type": "node",
            "id": 3,
            "lat": 65.0,
            "lon": 25.005,
            "tags": {"highway": "crossing", "crossing": "zebra"},
        },
    ]

    res = build_ways(elements)
    assert hasattr(res, "crossings")
    assert len(res.crossings) == 1
    c = res.crossings[0]
    assert isinstance(c, Crossing)
    assert c.id == 3
    assert c.crossing_type == "zebra"
    # Direction angle should be aligned with the road (roughly horizontal / 0 radians)
    assert c.direction_angle is not None
    assert abs(c.direction_angle) < 0.2 or abs(c.direction_angle - math.pi) < 0.2


def test_draw_crossings_runs_without_error():
    import pygame
    pygame.init()
    surf = pygame.Surface((800, 600))
    crossing = Crossing(
        x=100.0,
        y=100.0,
        direction_angle=0.0,
        width_m=6.0,
        length_m=2.4,
    )
    # Should draw crossing stripes without exceptions
    draw_crossings(surf, [crossing], camx=100.0, camy=100.0, px_per_m=5.0, screen_w=800, screen_h=600)
    pygame.quit()
