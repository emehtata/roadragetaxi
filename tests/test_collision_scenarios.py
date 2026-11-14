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
