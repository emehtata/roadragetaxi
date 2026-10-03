"""The taxi stops at bollards and lamp posts (OSM point features)."""
from types import SimpleNamespace

from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager


def test_driving_into_a_bollard_stops_once_per_impact_and_benches_dont_count():
    taxi = TaxiManager(ways=[])
    objects = [SimpleNamespace(x=2.0, y=0.0, kind="bollard"), SimpleNamespace(x=0.0, y=5.0, kind="bench")]
    car = Car(x=0.5, y=0.0, heading=0.0, speed=5.0)
    assert taxi.check_post_collision(car, objects, 0.0, previous_position=(0.0, 0.0))
    assert (car.x, car.y, car.speed) == (0.0, 0.0, 0.0) and taxi.total_score == -50
    car.x, car.speed = 0.5, 5.0
    assert taxi.check_post_collision(car, objects, 1.0, previous_position=(0.0, 0.0))
    assert taxi.total_score == -50  # same impact: no second penalty

    lamp_beside = [SimpleNamespace(x=0.0, y=3.0, kind="street_lamp")]
    assert not taxi.check_post_collision(Car(x=0.0, y=0.0, heading=0.0, speed=5.0), lamp_beside, 2.0)
    lamp_ahead = lamp_beside + [SimpleNamespace(x=1.9, y=0.0, kind="street_lamp")]
    assert taxi.check_post_collision(Car(x=0.0, y=0.0, heading=0.0, speed=5.0), lamp_ahead, 2.0)  # another scenery list: re-indexed


def test_hit_hard_a_lamp_bends_over_breaks_and_lets_the_taxi_through():
    taxi = TaxiManager(ways=[])
    lamp = SimpleNamespace(x=2.0, y=0.0, kind="street_lamp")
    car = Car(x=0.5, y=0.0, heading=0.0, speed=60.0 / 3.6)
    assert taxi.check_post_collision(car, [lamp], 0.0, previous_position=(0.0, 0.0))
    assert lamp.knocked_angle == 0.0 and taxi.broken_lamps == {(2.0, 0.0)} and taxi.knocked_posts == 1
    assert car.x == 0.5 and 0.0 < car.speed < 60.0 / 3.6  # not stopped, slowed
    assert taxi.total_score == -50
    assert not taxi.check_post_collision(car, [lamp], 5.0, previous_position=(0.0, 0.0))  # lies flat now


def test_a_broken_lamp_gives_no_light(monkeypatch):
    import pygame

    from theroadragetrip.osm import Way
    import theroadragetrip.render as render
    from theroadragetrip.render import draw_street_lights

    # One call finishes the lamp layout, starting from no cached state.
    for name, value in (("STREET_LIGHT_PREP_BUDGET_S", 10.0), ("STREET_LIGHT_CACHE_BUDGET_S", 10.0),
                        ("_street_light_frame_cache_key", None), ("_street_light_geometry_cache_key", None),
                        ("_street_light_geometry_wip", None)):
        monkeypatch.setattr(render.roads, name, value)
    pygame.init()
    try:
        screen = pygame.Surface((400, 300), pygame.SRCALPHA)
        road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="tertiary", half_width_m=4.0, lit="yes")
        draw_street_lights(screen, [road], 50.0, 0.0, 0.0, px_per_m=2.0, screen_w=400, screen_h=300, buildings=[])
        lamps = list(render._street_light_frame_world_positions)
        assert lamps
        draw_street_lights(screen, [road], 50.0, 0.0, 0.0, px_per_m=2.0, screen_w=400, screen_h=300, buildings=[],
                           broken_lamps={lamps[0]})
        assert render._street_light_frame_world_positions == lamps[1:]
    finally:
        pygame.quit()
