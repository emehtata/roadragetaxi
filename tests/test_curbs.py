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
    # describing the adjacent lawn) must still be classified as a curb.
    # This particular way is just a 2-point open line (not a closed area),
    # so it can never form scenery either way - see
    # test_kerb_around_a_real_planting_island_renders_both_curb_and_fill
    # below for the case that actually matters: a *closed* kerb+landuse
    # way, which must produce both.
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 15, "nodes": [1, 2], "tags": {"barrier": "kerb", "landuse": "grass"}},
    ]

    result = build_ways(elements)

    assert len(result.curbs) == 1
    assert len(result.sceneries) == 0


def test_kerb_around_a_real_planting_island_renders_both_curb_and_fill():
    """Regression: a real Oulu parking lot has small planting islands
    mapped as ONE closed way carrying both barrier=kerb (the physical
    raised edge) and natural=scrub or landuse=grass (what's growing
    inside it) - e.g. {barrier=kerb, kerb=raised, natural=scrub}. Kerb
    used to be checked in the same elif chain as the area tags, so it
    matched first and the area tag was never even looked at: the kerb
    outline rendered but its scrub/grass fill silently never existed."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0005, "lon": 25.0},
        {"type": "node", "id": 3, "lat": 60.0005, "lon": 25.0005},
        {"type": "node", "id": 4, "lat": 60.0, "lon": 25.0005},
        {
            "type": "way", "id": 16, "nodes": [1, 2, 3, 4, 1],
            "tags": {"barrier": "kerb", "kerb": "raised", "natural": "scrub"},
        },
    ]

    result = build_ways(elements)

    assert len(result.curbs) == 1
    assert len(result.sceneries) == 1
    assert result.sceneries[0].kind == "scrub"
    assert len(result.sceneries[0].points_m) == 5


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


def test_draw_curbs_skips_segments_far_outside_the_viewport():
    """A curb can run continuously for kilometers along a road (real OSM
    barrier=kerb data has a vertex every few meters following the road
    curve) - without per-segment culling, a way that merely clips the
    viewport corner would still convert its entire point list through
    world_to_screen and draw every segment, almost all of them off-screen
    (same class of bug test_draw_railways_skips_sleeper_ties_far_outside_
    the_viewport covers for railways)."""
    import pygame
    from theroadragetrip.render import roads as roads_module

    pygame.init()
    surf = pygame.Surface((800, 600))

    # 200 points spread over ~10km, all far off-screen, then a short
    # segment actually crossing the visible area near the camera.
    points = [(-10000.0 + i * 50.0, 100.0) for i in range(200)]
    points += [(80.0, 100.0), (120.0, 100.0)]
    curb = Curb(points_m=points, bbox=(-10000.0, 100.0, 120.0, 100.0))

    conversions = []
    real_world_to_screen = roads_module.world_to_screen
    try:
        roads_module.world_to_screen = lambda *a, **k: (conversions.append(1), real_world_to_screen(*a, **k))[1]
        draw_curbs(surf, [curb], camx=100.0, camy=100.0, px_per_m=8.0, screen_w=800, screen_h=600)
    finally:
        roads_module.world_to_screen = real_world_to_screen
    pygame.quit()

    # Only the one segment crossing the viewport should be converted; the
    # 200 far-off-screen segments must be skipped, not walked point by
    # point through world_to_screen.
    assert len(conversions) <= 4


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


def test_check_curb_bump_pushes_the_car_back_onto_the_road_at_low_speed():
    """A real curb is a hard stop at parking/walking speed - the car
    shouldn't just slow down and keep climbing it, it should stop dead at
    the curb, back on the side it approached from."""
    curb = Curb(points_m=[(10.0, -5.0), (10.0, 5.0)], bbox=(10.0, -5.0, 10.0, 5.0))
    car = Car(x=15.0, y=0.0, heading=0.0, speed=3.0)  # 10.8 km/h
    taxi_mgr = TaxiManager(ways=[])

    hit = taxi_mgr.check_curb_bump(car, [curb], previous_position=(5.0, 0.0), sim_time=0.0)

    assert hit is True
    assert (car.x, car.y) == (5.0, 0.0)
    assert car.speed == 0.0


def test_check_curb_bump_only_slows_down_at_higher_speed():
    """Fast enough to have the momentum to climb the curb: no hard stop,
    the car keeps its position and just loses speed (existing behavior)."""
    curb = Curb(points_m=[(10.0, -5.0), (10.0, 5.0)], bbox=(10.0, -5.0, 10.0, 5.0))
    car = Car(x=15.0, y=0.0, heading=0.0, speed=20.0)  # 72 km/h
    taxi_mgr = TaxiManager(ways=[])

    hit = taxi_mgr.check_curb_bump(car, [curb], previous_position=(5.0, 0.0), sim_time=0.0)

    assert hit is True
    assert (car.x, car.y) == (15.0, 0.0)
    assert 0.0 < car.speed < 20.0


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
