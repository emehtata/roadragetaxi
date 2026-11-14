"""Collision spec phase 1: category filter and deterministic scenarios 1, 1b and 3 (no map load)."""
import math
from types import SimpleNamespace

from theroadragetrip.collision import COLLIDES, Category, can_collide, same_plane
from theroadragetrip.geo import get_oriented_box_corners, point_in_polygon
from theroadragetrip.npc import NPCState, NPCVehicleManager, place_parked_npc
from theroadragetrip.osm import Building
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.physics import Car
from theroadragetrip.residents import ResidentManager
from theroadragetrip.taxi import TaxiManager

C = Category
SOLID_STATIC = (C.BUILDING, C.POST, C.BARRIER, C.ROADWORKS)


def test_matrix_symmetric():
    cats = list(COLLIDES)
    for a in cats:
        for b in cats:
            assert can_collide(a, b) == can_collide(b, a), (a, b)
    for b in (C.VEHICLE, C.PEDESTRIAN, C.ANIMAL, *SOLID_STATIC):
        assert can_collide(C.VEHICLE, b)
    assert {b for b in cats if can_collide(C.PEDESTRIAN, b)} == {C.VEHICLE, C.BUILDING, C.BARRIER}
    for a in SOLID_STATIC:
        for b in SOLID_STATIC:
            assert not can_collide(a, b)
    assert not any(can_collide(C.NONSOLID, b) for b in cats)


def test_same_plane_levels():
    assert same_plane(SimpleNamespace(), SimpleNamespace())
    assert same_plane(SimpleNamespace(layer=0, map_level=0), SimpleNamespace())
    assert not same_plane(SimpleNamespace(layer=1), SimpleNamespace(layer=0))
    assert not same_plane(SimpleNamespace(map_level=-1), SimpleNamespace(map_level=0))


def _head_on(level_b):
    residents, manager = ResidentManager(), NPCVehicleManager(target_count=2)
    cars = []
    for vid, x, heading in ((1, 0.0, 0.0), (2, 20.0, math.pi)):
        v = place_parked_npc(vid, (x, 0.0), None)
        v.car.heading, v.car.speed = heading, 10.0
        driver = residents.create(mode="driving")
        v.owner_id, driver.active_vehicle_id = driver.resident_id, vid
        cars.append(v)
    a, b = cars
    b.car.map_level = level_b
    manager.vehicles.extend(cars)
    peds, dt = PedestrianManager([], target_count=0), 1.0 / 30.0
    responded = lambda v: v.state == NPCState.CRASHED or v.knock_vx or v.knock_vy
    max_overlap = 0.0
    for frame in range(90):
        for v in cars:
            if not responded(v):
                v.car.x += math.cos(v.car.heading) * v.car.speed * dt
        prev = {v.vehicle_id: (v.car.x, v.car.y, v.car.heading) for v in cars}
        manager._check_vehicle_collision(a, [b], residents, peds, sim_time=frame * dt,
                                         previous_obstacle_poses=prev)
        max_overlap = max(max_overlap, a.car.length_m - (b.car.x - a.car.x))
    return a, b, max_overlap, responded


def test_vehicles_head_on_resolve():
    a, b, overlap, responded = _head_on(0)
    assert responded(a) and responded(b)
    assert overlap <= 2 * 10.0 / 30.0 + 1e-6  # both close in one frame at most


def test_vehicles_other_level_pass():
    a, b, _, responded = _head_on(1)
    assert not responded(a) and not responded(b)


def test_taxi_hits_building_stops():
    building = Building(points_m=[(10.0, -5.0), (20.0, -5.0), (20.0, 5.0), (10.0, 5.0)])
    car, manager, dt = Car(x=0.0, y=0.0, heading=0.0, speed=15.0), TaxiManager(ways=[]), 1.0 / 30.0
    hit = False
    for frame in range(60):
        prev = (car.x, car.y)
        car.x += car.speed * dt
        if manager.check_building_collision(car, [building], sim_time=frame * dt, previous_position=prev):
            hit = True
            break
    assert hit
    corners = get_oriented_box_corners(car.x, car.y, car.heading, car.length_m, car.width_m)
    assert not any(point_in_polygon(px, py, building.points_m) for px, py in corners)


# Phase 2: shared shape helpers and scenarios 4, 14.
import random
from types import SimpleNamespace as NS

from theroadragetrip.collision import box_hits_polygon, box_hits_polyline, post_box_depth
from theroadragetrip.taxi import POST_KNOCK_DOWN_KMH, POST_RADIUS_M

BOX = get_oriented_box_corners(0.0, 0.0, 0.0, 4.0, 2.0)  # x in [-2, 2], y in [-1, 1]


def _square(cx, cy, h):
    return [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]


def test_box_hits_polygon_cases():
    assert box_hits_polygon(BOX, _square(2.5, 0.0, 0.7))  # corner in
    assert box_hits_polygon(BOX, _square(0.5, 0.0, 0.2))  # small polygon wholly under the box
    assert box_hits_polygon(BOX, [(-0.5, -3.0), (0.5, -3.0), (0.5, 3.0), (-0.5, 3.0)])  # X-crossing
    big = _square(0.0, 0.0, 50.0)
    assert box_hits_polygon(BOX, big, centre=(0.0, 0.0))  # centre in
    assert not box_hits_polygon(BOX, _square(10.0, 0.0, 1.0))
    assert not box_hits_polygon(BOX, [(3.0, 3.0), (9.0, 3.0), (6.0, 8.0)])  # outside the AABB


def test_box_hits_polyline_is_open():
    u = [(2.0, -1.5), (-3.0, -1.5), (-3.0, 1.5), (2.0, 1.5)]  # open end at the box's front
    assert not box_hits_polyline(BOX, u)
    assert box_hits_polygon(BOX, u)  # closed, the last edge crosses the box
    assert box_hits_polyline(BOX, [(0.0, -3.0), (0.0, 3.0)])


def test_post_box_depth_matches_old_formula():
    rng = random.Random(7)
    for _ in range(20):
        px, py, x, y = (rng.uniform(-5, 5) for _ in range(4))
        heading, length, width, r = rng.uniform(-math.pi, math.pi), rng.uniform(3, 6), rng.uniform(1.5, 2.5), 0.15
        c, s = math.cos(heading), math.sin(heading)
        dx, dy = px - x, py - y
        old = min(length / 2 + r - abs(dx * c + dy * s), width / 2 + r - abs(-dx * s + dy * c))
        assert abs(post_box_depth(px, py, r, x, y, heading, length, width) - old) < 1e-9


def _depth(car, post):
    return post_box_depth(post.x, post.y, POST_RADIUS_M, car.x, car.y, car.heading, car.length_m, car.width_m)


def test_taxi_hits_pole_stops_or_knocks():
    dt = 1.0 / 30.0
    for speed in (8.0, 15.0):
        post, manager = NS(x=10.0, y=0.0, kind="bollard"), TaxiManager(ways=[])
        car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
        for frame in range(60):
            prev = (car.x, car.y)
            car.x += car.speed * dt
            first = _depth(car, post)
            if manager.check_post_collision(car, [post], frame * dt, previous_position=prev):
                break
        else:
            raise AssertionError("no contact")
        if speed * 3.6 < POST_KNOCK_DOWN_KMH:
            assert car.speed == 0.0 and _depth(car, post) <= first
            assert getattr(post, "knocked_angle", None) is None
        else:
            assert post.knocked_angle is not None and car.speed > 0.0


def test_initial_overlap_building_drive_out():
    car, manager = Car(x=0.0, y=0.0, heading=0.0, speed=-2.0), TaxiManager(ways=[])
    building = Building(points_m=_square(car.length_m / 2 - 0.3 + 10.0, 0.0, 10.0))  # front 0.3 m inside
    car.x = -0.1  # backing away
    assert not manager.check_building_collision(car, [building], 0.0, previous_position=(0.0, 0.0))
    assert car.x == -0.1 and manager.total_score == 0
    car.x, car.speed = 0.1, 2.0  # deeper
    assert manager.check_building_collision(car, [building], 0.1, previous_position=(0.0, 0.0))
    assert (car.x, car.y) == (0.0, 0.0)


def test_initial_overlap_pole_drive_out():
    car, manager = Car(x=0.0, y=0.0, heading=0.0, speed=-2.0), TaxiManager(ways=[])
    post = NS(x=car.length_m / 2 + POST_RADIUS_M - 0.1, y=0.0, kind="bollard")  # depth 0.1
    assert abs(_depth(car, post) - 0.1) < 1e-9
    car.x = -0.1
    assert not manager.check_post_collision(car, [post], 0.0, previous_position=(0.0, 0.0))
    assert car.x == -0.1 and manager.total_score == 0
    car.x, car.speed = 0.1, 2.0
    assert manager.check_post_collision(car, [post], 0.1, previous_position=(0.0, 0.0))
    assert (car.x, car.y) == (0.0, 0.0)
