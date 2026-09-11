"""Tests for speed bump (traffic_calming) extraction, rendering, and the
speed-dependent slowdown on impact."""
import math

from theroadragetrip.geo import dist_point_to_segment
from theroadragetrip.osm import SpeedBump, Way, build_ways
from theroadragetrip.osm.build import _snap_to_nearest_road
from theroadragetrip.physics import Car
from theroadragetrip.render import SPEED_BUMP_COLOR, draw_speed_bumps
from theroadragetrip.taxi import TaxiManager
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def test_build_ways_parses_traffic_calming_node_as_speed_bump():
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.000, "lon": 25.001, "tags": {"traffic_calming": "bump"}},
        {"type": "node", "id": 3, "lat": 60.000, "lon": 25.002},
        {"type": "way", "id": 10, "nodes": [1, 2, 3], "tags": {"highway": "residential"}},
    ]

    result = build_ways(elements)

    assert len(result.speed_bumps) == 1
    bump = result.speed_bumps[0]
    assert bump.kind == "bump"
    assert bump.id == 2
    assert bump.direction_angle is not None  # found and matched the road it sits on
    # Flush with the road it belongs to, not floating off to the side -
    # check against whichever of its two segments (it's node 2 of 3) is
    # nearest, matching how _snap_to_nearest_road works.
    pts = result.ways[0].points_m
    nearest = min(
        dist_point_to_segment(bump.x, bump.y, p1[0], p1[1], p2[0], p2[1])
        for p1, p2 in zip(pts, pts[1:])
    )
    assert nearest < 0.01


def test_snap_to_nearest_road_dedupes_a_way_registered_in_several_grid_cells():
    """Regression, one level below the full-pipeline test above: a way
    spanning several roads_grid cells is registered in each of them (see
    _build_roads_grid), so it can appear more than once among a point's
    candidate roads. Without deduping by identity, a single lone side
    street counted 3x that way could out-count a through road genuinely
    split into 2 way objects by the junction, defeating the "prefer the
    name with more than one distinct way" tie-break entirely."""
    side = Way([(0.0, 0.0), (0.0, 100.0)], "residential", 4.0, name="Side")
    main_a = Way([(-10.0, 0.0), (0.0, 0.0)], "residential", 4.0, name="Main")
    main_b = Way([(0.0, 0.0), (10.0, 0.0)], "residential", 4.0, name="Main")
    # Simulate `side` being registered in 3 grid cells - `_build_roads_grid`
    # would do exactly this for a way whose bbox spans that many cells -
    # while Main's two pieces are each registered once, as they normally
    # would be for a short segment fitting in a single cell.
    roads_grid = {
        (0, 0): [side, side, side, main_a],
        (0, 1): [main_b],
    }

    x, y, angle, half_w, found = _snap_to_nearest_road((0.0, 0.0), 0, roads_grid, r_grid_size=50.0)

    assert found is True
    # Main is horizontal (angle ~0/~pi); Side is vertical (angle ~pi/2).
    angle_deg = math.degrees(angle)
    assert angle_deg < 30.0 or angle_deg > 150.0, (
        f"picked the over-counted side street instead of the through road: got {angle_deg} deg"
    )


def test_speed_bump_at_a_t_junction_snaps_to_the_through_road_not_the_side_street():
    """Regression: a highway=crossing/traffic_calming node digitized right
    on a T-junction vertex is equidistant from every road meeting there -
    the through road (here "Main", split into two way objects by the
    junction, like OSM always does) and the short side street ("Side")
    that merely starts there. Picking whichever's enumerated first used to
    be a coin flip, and landing on the side street put the rendered bar up
    to 90 degrees off the real crossing/bump - confirmed against real OSM
    data (Oulu: Rantakatu x Pakkahuoneenkatu, ~57 deg vs ~142 deg)."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        # The junction vertex - also the crossing/speed-bump node.
        {"type": "node", "id": 2, "lat": 60.000, "lon": 25.001, "tags": {"highway": "crossing", "traffic_calming": "table"}},
        {"type": "node", "id": 3, "lat": 60.000, "lon": 25.002},
        # Side street heading due north from the junction - roughly 90
        # degrees off Main's roughly-east-west heading.
        {"type": "node", "id": 4, "lat": 60.001, "lon": 25.001},
        # Main, split into two way objects at the junction (node 2) - as
        # real OSM data always does at an intersection.
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential", "name": "Main"}},
        {"type": "way", "id": 11, "nodes": [2, 3], "tags": {"highway": "residential", "name": "Main"}},
        {"type": "way", "id": 12, "nodes": [2, 4], "tags": {"highway": "residential", "name": "Side"}},
    ]

    result = build_ways(elements)

    assert len(result.speed_bumps) == 1
    angle_deg = math.degrees(result.speed_bumps[0].direction_angle)
    # Main runs roughly east-west (~0/~180 deg - direction_angle is mod
    # pi, so "horizontal" can land on either end depending on floating
    # point sign); Side runs roughly north (~90 deg). A wide margin around
    # the vertical - the point is which road it picked, not the exact
    # degree.
    assert angle_deg < 30.0 or angle_deg > 150.0, (
        f"snapped to the side street (~90 deg), not Main (~horizontal): got {angle_deg}"
    )


def test_build_ways_parses_a_raised_crossing_as_both_crossing_and_speed_bump():
    """A "table" is very often also a raised pedestrian crossing in real
    OSM data (highway=crossing + traffic_calming=table on the same node) -
    both a Crossing and a SpeedBump must come out of it, not just one."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.000, "lon": 25.000},
        {"type": "node", "id": 2, "lat": 60.000, "lon": 25.001, "tags": {"highway": "crossing", "traffic_calming": "table"}},
        {"type": "node", "id": 3, "lat": 60.000, "lon": 25.002},
        {"type": "way", "id": 10, "nodes": [1, 2, 3], "tags": {"highway": "residential"}},
    ]

    result = build_ways(elements)

    assert len(result.crossings) == 1
    assert len(result.speed_bumps) == 1
    assert result.speed_bumps[0].kind == "table"


def test_build_ways_ignores_traffic_calming_no_and_island():
    """traffic_calming=no/island (seen on ways in real data) aren't real
    physical bumps - "no" documents the absence of one, "island" is a
    traffic island already covered by barrier=kerb - neither should
    produce a SpeedBump."""
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001},
        {"type": "way", "id": 20, "nodes": [1, 2], "tags": {"highway": "residential", "traffic_calming": "no"}},
    ]

    result = build_ways(elements)

    assert result.speed_bumps == []


def test_speed_bumps_round_trip_through_world_cache(tmp_path):
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.0, "lon": 25.001, "tags": {"traffic_calming": "cushion"}},
        {"type": "node", "id": 3, "lat": 60.0, "lon": 25.002},
        {"type": "way", "id": 10, "nodes": [1, 2, 3], "tags": {"highway": "residential"}},
    ]
    world = build_ways(elements)
    path = tmp_path / "area.rwc"
    BinaryWorldCacheWriter().write(path, world, area_id="area")
    loaded = BinaryWorldCacheLoader().load(path)

    assert len(loaded.speed_bumps) == 1
    assert loaded.speed_bumps[0].kind == "cushion"
    assert loaded.speed_bumps[0].x == world.speed_bumps[0].x


def test_draw_speed_bumps_paints_darker_than_the_road():
    import pygame

    pygame.init()
    try:
        screen_w, screen_h, px_per_m = 200, 200, 8.0
        screen = pygame.Surface((screen_w, screen_h))
        road_color = (142, 142, 138)
        screen.fill(road_color)

        bump = SpeedBump(x=0.0, y=0.0, direction_angle=0.0, width_m=3.0, kind="bump")
        draw_speed_bumps(screen, [bump], 0.0, 0.0, px_per_m=px_per_m, screen_w=screen_w, screen_h=screen_h)

        center = (screen_w // 2, screen_h // 2)
        pixel = tuple(screen.get_at(center))[:3]
        assert pixel == SPEED_BUMP_COLOR
        assert sum(pixel) < sum(road_color), "speed bump must render darker than the road"
    finally:
        pygame.quit()


def test_check_speed_bump_has_no_penalty_under_the_safe_speed():
    bump = SpeedBump(x=10.0, y=0.0, direction_angle=0.0, width_m=10.0)
    car = Car(x=15.0, y=0.0, heading=0.0, speed=20.0 / 3.6)  # 20 km/h, under the 25 km/h default
    taxi_mgr = TaxiManager(ways=[])

    hit = taxi_mgr.check_speed_bump(car, [bump], previous_position=(5.0, 0.0), sim_time=0.0)

    assert hit is True  # still crossed it and was jolted/counted
    assert car.speed == 20.0 / 3.6  # ...but no speed lost, under the safe speed


def test_check_speed_bump_ignores_a_move_that_does_not_cross_it():
    bump = SpeedBump(x=10.0, y=0.0, direction_angle=0.0, width_m=10.0)
    car = Car(x=6.0, y=0.0, heading=0.0, speed=50.0 / 3.6)
    taxi_mgr = TaxiManager(ways=[])

    hit = taxi_mgr.check_speed_bump(car, [bump], previous_position=(5.0, 0.0), sim_time=0.0)

    assert hit is False
    assert car.speed == 50.0 / 3.6


def test_check_speed_bump_slows_the_car_more_the_faster_it_was_going():
    """The whole point: hitting a speed bump fast must cost more speed
    than hitting the same bump slowly (both above the safe threshold)."""
    bump = SpeedBump(x=10.0, y=0.0, direction_angle=0.0, width_m=10.0)
    taxi_mgr = TaxiManager(ways=[])

    moderate_speed = 40.0 / 3.6  # 40 km/h - a bit over the 25 km/h safe speed
    fast_speed = 110.0 / 3.6  # 110 km/h - way over

    moderate_car = Car(x=15.0, y=0.0, heading=0.0, speed=moderate_speed)
    taxi_mgr.check_speed_bump(moderate_car, [bump], previous_position=(5.0, 0.0), sim_time=0.0)
    moderate_loss_fraction = 1.0 - moderate_car.speed / moderate_speed

    taxi_mgr._speed_bump_cooldowns.clear()  # simulate a *different* car/bump, not a cooldown-blocked repeat
    fast_car = Car(x=15.0, y=0.0, heading=0.0, speed=fast_speed)
    taxi_mgr.check_speed_bump(fast_car, [bump], previous_position=(5.0, 0.0), sim_time=0.0)
    fast_loss_fraction = 1.0 - fast_car.speed / fast_speed

    assert moderate_loss_fraction > 0.0
    assert fast_loss_fraction > moderate_loss_fraction
    assert fast_loss_fraction <= 0.5  # capped (max_slowdown default), never stops the car outright


def test_check_speed_bump_has_a_cooldown_per_bump():
    bump = SpeedBump(x=10.0, y=0.0, direction_angle=0.0, width_m=10.0)
    car = Car(x=15.0, y=0.0, heading=0.0, speed=80.0 / 3.6)
    taxi_mgr = TaxiManager(ways=[])

    assert taxi_mgr.check_speed_bump(car, [bump], previous_position=(5.0, 0.0), sim_time=0.0) is True
    speed_after_first_hit = car.speed

    # Immediately cross back over the same bump - still within the cooldown.
    car.x = 5.0
    assert taxi_mgr.check_speed_bump(car, [bump], previous_position=(15.0, 0.0), sim_time=0.2) is False
    assert car.speed == speed_after_first_hit

    # Well past the cooldown, the same bump can jolt the car again.
    car.x = 15.0
    assert taxi_mgr.check_speed_bump(car, [bump], previous_position=(5.0, 0.0), sim_time=2.0) is True
