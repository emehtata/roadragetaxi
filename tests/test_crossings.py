"""Tests for pedestrian crossing (suojatie) extraction and rendering."""
import math
from theroadragetrip.osm import Building, Crossing, Way, build_ways
from theroadragetrip.render import (
    _way_should_have_street_lighting,
    draw_crossings,
    draw_pedestrian_reflectors,
)


def test_secondary_street_lighting_defaults_to_built_up_areas():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="secondary", half_width_m=4.0)
    building = Building(
        points_m=[(20.0, 20.0), (30.0, 20.0), (30.0, 30.0), (20.0, 30.0)],
        bbox=(20.0, 20.0, 30.0, 30.0),
    )

    assert _way_should_have_street_lighting(road, [building], (0.0, 0.0))
    assert not _way_should_have_street_lighting(road, [], (0.0, 0.0))


def test_secondary_explicit_lighting_overrides_area_fallback():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="secondary", half_width_m=4.0)

    road.lit = "yes"
    assert _way_should_have_street_lighting(road, [])
    road.lit = "no"
    assert not _way_should_have_street_lighting(road, [Building([], bbox=(0.0, 0.0, 1.0, 1.0))])


def test_building_proximity_does_not_light_other_unlit_road_types():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="tertiary", half_width_m=4.0)
    building = Building([], bbox=(0.0, 0.0, 1.0, 1.0))

    assert not _way_should_have_street_lighting(road, [building], (0.0, 0.0))


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


def test_draw_pedestrian_reflector_marks_visible_pedestrian():
    import pygame
    from types import SimpleNamespace

    pygame.init()
    surf = pygame.Surface((100, 100))
    surf.fill((0, 0, 0))
    ped = SimpleNamespace(x=50.0, y=50.0, way=SimpleNamespace(layer=0))

    draw_pedestrian_reflectors(surf, [ped], camx=50.0, camy=50.0, px_per_m=1.0, screen_w=100, screen_h=100, ways=[])

    assert surf.get_at((50, 50))[:3] == (255, 255, 245)
    pygame.quit()


def test_draw_pedestrian_reflector_turns_off_in_car_beam_or_street_light():
    import pygame
    from types import SimpleNamespace

    pygame.init()
    ped = SimpleNamespace(x=50.0, y=50.0, way=SimpleNamespace(layer=0))
    car = SimpleNamespace(x=40.0, y=50.0, heading=0.0)

    car_lit = pygame.Surface((100, 100))
    car_lit.fill((0, 0, 0))
    draw_pedestrian_reflectors(
        car_lit, [ped], 50.0, 50.0, px_per_m=1.0, screen_w=100, screen_h=100,
        ways=[], light_vehicles=[car], street_light_positions=[],
    )
    assert car_lit.get_at((50, 50))[:3] == (0, 0, 0)

    lamp_lit = pygame.Surface((100, 100))
    lamp_lit.fill((0, 0, 0))
    draw_pedestrian_reflectors(
        lamp_lit, [ped], 50.0, 50.0, px_per_m=1.0, screen_w=100, screen_h=100,
        ways=[], light_vehicles=[], street_light_positions=[(50.0, 60.0)],
    )
    assert lamp_lit.get_at((50, 50))[:3] == (0, 0, 0)

    shadowed = pygame.Surface((100, 100))
    shadowed.fill((0, 0, 0))
    shadow_ped = SimpleNamespace(x=50.0, y=50.0, way=SimpleNamespace(layer=0))
    draw_pedestrian_reflectors(
        shadowed, [shadow_ped], 50.0, 50.0, px_per_m=1.0, screen_w=100, screen_h=100,
        ways=[], light_vehicles=[], street_light_positions=[(50.0, 65.0)],
    )
    assert shadowed.get_at((50, 50))[:3] == (255, 255, 245)

    boundary = pygame.Surface((100, 100))
    boundary.fill((0, 0, 0))
    boundary_ped = SimpleNamespace(x=50.0, y=50.0, way=SimpleNamespace(layer=0))
    draw_pedestrian_reflectors(
        boundary, [boundary_ped], 50.0, 50.0, px_per_m=1.0, screen_w=100, screen_h=100,
        ways=[], light_vehicles=[], street_light_positions=[(50.0, 60.0)],
    )
    assert boundary.get_at((50, 50))[:3] == (0, 0, 0)

    outside = pygame.Surface((100, 100))
    outside.fill((0, 0, 0))
    outside_ped = SimpleNamespace(x=50.0, y=50.0, way=SimpleNamespace(layer=0))
    draw_pedestrian_reflectors(
        outside, [outside_ped], 50.0, 50.0, px_per_m=1.0, screen_w=100, screen_h=100,
        ways=[], light_vehicles=[], street_light_positions=[(50.0, 60.1)],
    )
    assert outside.get_at((50, 50))[:3] == (255, 255, 245)
    pygame.quit()


def test_headlight_beam_does_not_erase_street_light_shade(monkeypatch):
    import pygame
    import theroadragetrip.render as render

    pygame.init()
    monkeypatch.setattr(render, "solar_altitude_and_events", lambda *args: (-20.0, 0.0, 0.0))
    surf = pygame.Surface((100, 100))
    surf.fill((255, 255, 255))
    daylight = surf.copy()

    render.draw_headlight_beams(
        surf, [], camx=50.0, camy=50.0, game_time_seconds=0.0, px_per_m=1.0,
        screen_w=100, screen_h=100, daylight_surface=daylight,
        street_light_positions=[(50.0, 50.0)],
    )

    assert surf.get_at((50, 50))[:3] == (0, 0, 0)
    pygame.quit()
