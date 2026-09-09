"""Tests for kerb (curb) extraction, rendering, and the speed-bump on impact."""
from theroadragetrip.osm import Curb, Way, build_ways
from theroadragetrip.physics import Car
from theroadragetrip.render import draw_curbs
from theroadragetrip.taxi import TaxiManager
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def test_build_ways_parses_barrier_kerb_as_curb():
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 14, "nodes": [1, 2], "tags": {"barrier": "kerb", "kerb": "raised"}},
    ]

    result = build_ways(elements)

    assert len(result.curbs) == 1
    assert len(result.curbs[0].points_m) == 2


def test_build_ways_classifies_curb_over_landuse_tag():
    # A kerb way that also carries a landuse tag (common in real OSM data,
    # describing the adjacent lawn) must still be classified as a curb, not
    # absorbed as grass scenery.
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 15, "nodes": [1, 2], "tags": {"barrier": "kerb", "landuse": "grass"}},
    ]

    result = build_ways(elements)

    assert len(result.curbs) == 1
    assert len(result.sceneries) == 0


def test_curbs_round_trip_through_world_cache(tmp_path):
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 14, "nodes": [1, 2], "tags": {"barrier": "kerb"}},
    ]
    world = build_ways(elements)
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)

    assert len(loaded.curbs) == 1
    assert loaded.curbs[0].points_m == world.curbs[0].points_m


def test_draw_curbs_runs_without_error():
    import pygame
    pygame.init()
    surf = pygame.Surface((800, 600))
    curb = Curb(points_m=[(90.0, 100.0), (110.0, 100.0)], bbox=(90.0, 100.0, 110.0, 100.0))
    draw_curbs(surf, [curb], camx=100.0, camy=100.0, px_per_m=5.0, screen_w=800, screen_h=600)
    pygame.quit()


def test_check_curb_bump_slows_car_when_crossed():
    curb = Curb(points_m=[(10.0, -5.0), (10.0, 5.0)], bbox=(10.0, -5.0, 10.0, 5.0))
    car = Car(x=15.0, y=0.0, heading=0.0, speed=20.0)
    taxi_mgr = TaxiManager(ways=[])

    hit = taxi_mgr.check_curb_bump(car, [curb], previous_position=(5.0, 0.0), sim_time=0.0)

    assert hit is True
    assert car.speed < 20.0


def test_check_curb_bump_ignores_a_move_that_does_not_cross_the_line():
    curb = Curb(points_m=[(10.0, -5.0), (10.0, 5.0)], bbox=(10.0, -5.0, 10.0, 5.0))
    car = Car(x=6.0, y=0.0, heading=0.0, speed=20.0)
    taxi_mgr = TaxiManager(ways=[])

    hit = taxi_mgr.check_curb_bump(car, [curb], previous_position=(5.0, 0.0), sim_time=0.0)

    assert hit is False
    assert car.speed == 20.0


def test_check_curb_bump_has_a_cooldown_per_curb():
    # Without a cooldown, a car scraping back and forth across the same
    # curb point (position jitter, tight cornering) would get the 15%
    # speed cut re-applied every single frame and stall almost instantly.
    curb = Curb(points_m=[(10.0, -5.0), (10.0, 5.0)], bbox=(10.0, -5.0, 10.0, 5.0))
    car = Car(x=15.0, y=0.0, heading=0.0, speed=20.0)
    taxi_mgr = TaxiManager(ways=[])

    assert taxi_mgr.check_curb_bump(car, [curb], previous_position=(5.0, 0.0), sim_time=0.0) is True
    speed_after_first_hit = car.speed

    # Immediately cross back over the same curb - still within the cooldown.
    car.x = 5.0
    assert taxi_mgr.check_curb_bump(car, [curb], previous_position=(15.0, 0.0), sim_time=0.1) is False
    assert car.speed == speed_after_first_hit

    # Well past the cooldown, the same curb can bump the car again.
    car.x = 15.0
    assert taxi_mgr.check_curb_bump(car, [curb], previous_position=(5.0, 0.0), sim_time=1.0) is True
    assert car.speed < speed_after_first_hit
