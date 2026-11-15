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


# Phase 3: trees on the server (scenarios 4, 10).
from theroadragetrip.taxi import TREE_RADIUS_M


def _drive_at_tree(speed, tree_y=0.0, seconds=2.0, dt=1.0 / 30.0, level=0):
    sceneries = [NS(trees=[(10.0, tree_y)])]
    manager, car = TaxiManager(ways=[]), Car(x=0.0, y=0.0, heading=0.0, speed=speed)
    car.map_level = level
    felled = 0
    for frame in range(int(seconds / dt)):
        car.x += car.speed * dt
        if car.map_level == 0:  # the simulation calls it only on the surface
            felled += manager.check_tree_collision(car, sceneries, frame * dt)
    return manager, car, felled


def test_taxi_fells_tree_keeps_speed():
    for speed in (8.0, 20.0):
        manager, car, felled = _drive_at_tree(speed)
        assert felled == 1 and len(manager.felled_trees) == 1
        tree = manager.felled_trees[0]
        assert (tree.x, tree.y, tree.kind) == (10.0, 0.0, "tree") and tree.knocked_angle == 0.0
        assert abs(car.speed - speed) < 1e-6 and manager.total_score == 0


def test_tree_miss_beyond_reach():
    car = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    manager, _, felled = _drive_at_tree(10.0, tree_y=car.width_m / 2 + TREE_RADIUS_M + 0.5)
    assert felled == 0 and manager.felled_trees == []


def test_tree_fast_no_tunnel():
    manager, _, felled = _drive_at_tree(69.0, seconds=1.0)
    assert felled == 1


def test_tree_off_surface_ignored():
    manager, _, felled = _drive_at_tree(10.0, level=-1)
    assert felled == 0


def test_tree_felling_deterministic():
    runs = []
    for _ in range(2):
        sceneries = [NS(trees=[(10.0, 0.5), (20.0, -0.5)])]
        manager, car = TaxiManager(ways=[]), Car(x=0.0, y=0.0, heading=0.0, speed=10.0)
        for frame in range(90):
            car.x += car.speed / 30.0
            if frame == 10:
                sceneries.append(NS(trees=[(25.0, 0.0)]))
            manager.check_tree_collision(car, sceneries, frame / 30.0)
        runs.append([(t.x, t.y, t.knocked_angle) for t in manager.felled_trees])
        indexed = [t for cell in manager._post_grid.values() for t in cell]
        assert len(indexed) == len({id(t) for t in indexed}) == 3
    assert runs[0] == runs[1] and len(runs[0]) == 3


def test_post_check_keeps_the_tree_index():
    posts, sceneries = [NS(x=50.0, y=0.0, kind="bollard")], [NS(trees=[(10.0, 0.0)])]
    manager, car = TaxiManager(ways=[]), Car(x=0.0, y=0.0, heading=0.0, speed=10.0)
    felled = 0
    for frame in range(60):  # the simulation's order: trees, then posts
        car.x += car.speed / 30.0
        felled += manager.check_tree_collision(car, sceneries, frame / 30.0)
        manager.check_post_collision(car, posts, frame / 30.0)
    assert felled == 1


def test_unloaded_chunk_trees_stand_and_stay_up():
    from theroadragetrip.map_chunks import cell_of
    from theroadragetrip.protocol import _knocked_trees

    sceneries = [NS(trees=[(10.0, 0.0), (300.0, 0.0)])]
    manager, car = TaxiManager(ways=[]), Car(x=0.0, y=0.0, heading=0.0, speed=10.0)
    for frame in range(60):
        car.x += car.speed / 30.0
        manager.check_tree_collision(car, sceneries, frame / 30.0)
    assert [(t.x, t.y) for t in manager.felled_trees] == [(10.0, 0.0)]
    manager.stand_trees_in(cell_of(10.0, 0.0), cell_of)  # the server unloads that chunk
    world = NS(taxi_mgr=manager)
    assert manager.felled_trees == [] and _knocked_trees(world, 10.0, 0.0) == []  # reloaded: standing
    car.x, car.y = 285.0, 0.0  # a later felling elsewhere
    for frame in range(60):
        car.x += car.speed / 30.0
        manager.check_tree_collision(car, sceneries, 2.0 + frame / 30.0)
    assert _knocked_trees(world, 300.0, 0.0) == [[300.0, 0.0, 0.0]]  # the first does not fall again


# Phase 4: one static-obstacle index, scenarios 9 and 12.
from theroadragetrip.collision import StaticObstacleIndex
from theroadragetrip.map_chunks import CHUNK_SIZE_M
from theroadragetrip.osm.models import Railing

_EDGE = CHUNK_SIZE_M  # a chunk boundary at x = 500 m
_STRADDLE = [(_EDGE - 5.0, -5.0), (_EDGE + 5.0, -5.0), (_EDGE + 5.0, 5.0), (_EDGE - 5.0, 5.0)]


def _approach_from_next_chunk(check, objects, frames=120, dt=1.0 / 30.0):
    manager, car = TaxiManager(ways=[]), Car(x=_EDGE + 30.0, y=0.0, heading=math.pi, speed=15.0)
    for frame in range(frames):
        prev = (car.x, car.y)
        car.x -= car.speed * dt
        if check(manager)(car, objects, frame * dt, prev):
            return frame
    return None


def test_static_index_cross_chunk_approach():
    bbox = (_EDGE - 5.0, -5.0, _EDGE + 5.0, 5.0)
    cases = [  # expected tick: what the phase 3 grids reported
        (lambda m: m.check_building_collision, [Building(points_m=_STRADDLE)], 45),
        (lambda m: m.check_fence_collision, [NS(kind="construction", points_m=_STRADDLE, bbox=bbox)], 45),
        (lambda m: m.check_barrier_collision,
         [Railing(points_m=[(_EDGE - 3.0, -6.0), (_EDGE + 3.0, 6.0)], bbox=(_EDGE - 3.0, -6.0, _EDGE + 3.0, 6.0), kind="wall")], 55),
        (lambda m: m.check_post_collision, [NS(x=_EDGE - 0.1, y=0.0, kind="bollard", knocked_angle=None)], 55),
    ]
    for check, objects, tick in cases:
        assert _approach_from_next_chunk(check, objects) == tick
    index = StaticObstacleIndex()
    index.sync("buildings", [Building(points_m=_STRADDLE)], Category.BUILDING)
    cells = [cell for cell, entries in index.grid.grid.items() if entries]
    assert len(cells) >= 2  # the straddling bbox is spread over the cells of both chunks


def test_static_index_unload_and_reload():
    far = [Building(points_m=[(x, 200.0), (x + 8.0, 200.0), (x + 8.0, 208.0), (x, 208.0)]) for x in range(0, 400, 20)]
    here = Building(points_m=[(10.0, -5.0), (20.0, -5.0), (20.0, 5.0), (10.0, 5.0)])
    manager = TaxiManager(ways=[])
    inserts = []
    original = manager.static_index.grid.insert
    manager.static_index.grid.insert = lambda item: (inserts.append(item), original(item))[1]

    def drive(buildings):
        car = Car(x=0.0, y=0.0, heading=0.0, speed=15.0)
        for frame in range(60):
            prev = (car.x, car.y)
            car.x += car.speed / 30.0
            if manager.check_building_collision(car, buildings, sim_time=100.0 * len(inserts) + frame, previous_position=prev):
                return True
        return False

    assert drive(far + [here])
    assert len(inserts) == len(far) + 1
    inserts.clear()
    assert drive(list(far)) is False  # the tile with `here` unloaded
    assert manager.static_index.query(15.0, 0.0, 1.0, Category.BUILDING) == []
    assert inserts == []
    assert drive(far + [here])  # reloaded
    assert [entry.obj for entry in inserts] == [here]


def test_static_index_level_and_layer_filter():
    index = StaticObstacleIndex()
    garage = Building(points_m=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)], map_level=-1)
    deck = Railing(points_m=[(0.0, 5.0), (10.0, 5.0)], bbox=(0.0, 5.0, 10.0, 5.0), layer=1)
    index.sync("buildings", [garage], Category.BUILDING)
    index.sync("railings", [deck], Category.BARRIER)
    both = Category.BUILDING | Category.BARRIER
    assert index.query(5.0, 5.0, 2.0, both, level=0, layer=0) == []
    assert index.query(5.0, 5.0, 2.0, both) == [garage, deck]


def test_felled_tree_survives_tile_unload():
    near, far = NS(trees=[(10.0, 0.0)]), NS(trees=[(300.0, 0.0)])
    manager = TaxiManager(ways=[])

    def drive(sceneries, t0):
        car, felled = Car(x=0.0, y=0.0, heading=0.0, speed=10.0), 0
        for frame in range(60):
            car.x += car.speed / 30.0
            felled += manager.check_tree_collision(car, sceneries, t0 + frame / 30.0)
        return felled

    assert drive([near, far], 0.0) == 1
    tree = manager.felled_trees[0]
    angle = tree.knocked_angle
    assert drive([near], 10.0) == 0  # the far tile unloaded: a new list, the near tree still lies felled
    assert manager.felled_trees == [tree] and tree.knocked_angle == angle
    assert tree in manager.static_index.query(10.0, 0.0, 1.0, Category.POST)


def test_static_index_forget_is_proportional_to_the_removed():
    """autofetch hands over the unloaded objects: the next sync of the same, in-place filtered
    list needs no id-set diff, and the removed are gone from queries at once."""
    keep = [Building(points_m=[(x, 200.0), (x + 8.0, 200.0), (x + 8.0, 208.0), (x, 208.0)]) for x in range(0, 400, 20)]
    gone = Building(points_m=[(10.0, -5.0), (20.0, -5.0), (20.0, 5.0), (10.0, 5.0)])
    buildings = keep[:5] + [gone] + keep[5:]
    index = StaticObstacleIndex()
    index.sync("buildings", buildings, Category.BUILDING)
    buildings[:] = [b for b in buildings if b is not gone]  # autofetch filters in place
    index.forget("buildings", [gone])
    assert index.query(15.0, 0.0, 1.0, Category.BUILDING) == []
    index._diff = None  # a diff now would fail
    index.sync("buildings", buildings, Category.BUILDING)
    assert index.query(4.0, 204.0, 1.0, Category.BUILDING) == [keep[0]]


def test_autofetch_unload_hands_over_the_removed():
    from theroadragetrip.osm.autofetch import AutoFetchManager

    manager = AutoFetchManager.__new__(AutoFetchManager)
    calls = []
    manager.unload_listeners = [lambda section, removed: calls.append((section, removed))]
    building = Building(points_m=_STRADDLE)
    manager._notify_unloaded("buildings", [building])
    assert calls == [("buildings", [building])]
