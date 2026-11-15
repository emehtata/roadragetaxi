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
    # Phase 5 amendment: crowds stop walking through each other (PEDESTRIAN with PEDESTRIAN).
    assert {b for b in cats if can_collide(C.PEDESTRIAN, b)} == {C.VEHICLE, C.PEDESTRIAN, C.BUILDING, C.BARRIER}
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


# Phase 5: pedestrians through their own grid, separation and walls (scenarios 5, 7, 8).
import random  # noqa: E402

from theroadragetrip.osm import Way  # noqa: E402
from theroadragetrip.pedestrian import Pedestrian, CURSE_SYMBOLS  # noqa: E402

_FOOTWAY = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)


def _ped(x, y, way=_FOOTWAY, direction=1):
    return Pedestrian(x, y, 0.0 if direction == 1 else math.pi, 1.4, 1.4, way, 0, direction, (255, 0, 0))


def _old_avoidance(peds, curses, player_car, dt):
    """A reference copy of the pre-phase-5 loop over every pedestrian."""
    car_speed = player_car.speed
    car_moving = abs(car_speed) > 1.5
    travel = 1.0 if car_speed >= 0.0 else -1.0
    car_dir_x = math.cos(player_car.heading) * travel
    # Car forward is (cos, sin) (physics.py); the old loop's -sin skewed this frame off the axes
    # (a trigger 20 m away at 45 degrees), which no bounded query can reproduce: fixed in both.
    car_dir_y = math.sin(player_car.heading) * travel
    car_perp_x = math.sin(player_car.heading)
    car_perp_y = -math.cos(player_car.heading)
    cyclist_collision = False
    for ped in peds:
        if getattr(ped, "is_walking_to_taxi_stop", False):
            continue
        was_dodging = ped.dodge_timer > 0.0
        if ped.curse_timer > 0.0:
            ped.curse_timer = max(0.0, ped.curse_timer - dt)
        if ped.dodge_timer > 0.0:
            ped.dodge_timer = max(0.0, ped.dodge_timer - dt)
            ped.x += ped.dodge_vx * dt
            ped.y += ped.dodge_vy * dt
        dx, dy = ped.x - player_car.x, ped.y - player_car.y
        dist_sq = dx * dx + dy * dy
        long_dist = dx * car_dir_x + dy * car_dir_y
        lat_offset = abs(dx * car_perp_x + dy * car_perp_y)
        is_directly_ahead = car_moving and 0.0 < long_dist < 3.5 and lat_offset < 1.8
        if is_directly_ahead or dist_sq < 1.25 * 1.25:
            dist = math.sqrt(dist_sq) or 1.0
            side_sign = 1.0 if (dx * car_perp_x + dy * car_perp_y) >= 0 else -1.0
            fx = dx / dist * 0.3 + car_perp_x * side_sign
            fy = dy / dist * 0.3 + car_perp_y * side_sign
            mag = math.hypot(fx, fy) or 1.0
            ped.dodge_vx, ped.dodge_vy, ped.dodge_timer = fx / mag * 3.5, fy / mag * 3.5, 0.4
            if getattr(ped, "is_cyclist", False) and not was_dodging:
                cyclist_collision = True
            if is_directly_ahead and ped.curse_timer <= 0.0:
                curses.append((ped.x, ped.y))
                ped.curse_timer = 2.0
                ped.curse_text = random.choice(CURSE_SYMBOLS)
    return cyclist_collision


def test_taxi_avoidance_uses_pedestrian_grid():
    manager = PedestrianManager([_FOOTWAY], target_count=0)
    manager.pedestrians = [_ped(1000.0 + i * 3.0, 500.0) for i in range(500)]
    calls = []
    original = manager._avoid_trigger
    manager._avoid_trigger = lambda *a: (calls.append(a), original(*a))[1]
    manager.check_player_avoidance(Car(x=0.0, y=0.0, heading=0.0, speed=10.0), 1.0 / 30.0)
    assert calls == []


def _scenario5(level):
    manager = PedestrianManager([_FOOTWAY], target_count=0)
    ped = _ped(20.0, 0.0)
    ped.map_level = level
    manager.pedestrians = [ped]
    car, dt, started = Car(x=0.0, y=0.0, heading=0.0, speed=10.0), 1.0 / 30.0, None
    for tick in range(120):
        car.x += car.speed * dt
        manager.check_player_avoidance(car, dt)
        if started is None and ped.dodge_timer > 0.0:
            started = tick
    return manager, ped, car, started


def test_scenario5_taxi_approaches_pedestrian():
    manager, ped, car, started = _scenario5(0)
    assert started == 49  # the tick the old full scan started the dodge (car 3.33 m short)
    corners = get_oriented_box_corners(car.x, car.y, car.heading, car.length_m, car.width_m)
    assert not point_in_polygon(ped.x, ped.y, corners)
    assert len(manager.curses) == 1


def test_scenario5_other_level_no_dodge():
    manager, ped, _, started = _scenario5(-1)
    assert started is None and manager.curses == [] and (ped.x, ped.y) == (20.0, 0.0)


def test_scenario7_pedestrians_cross_without_overlap():
    random.seed(7)
    way = Way(points_m=[(0.0, 0.0), (20.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager([way], target_count=0)
    a, b = _ped(2.0, 0.0, way, 1), _ped(18.0, 0.0, way, -1)
    b.segment_idx = 0
    for p in (a, b):
        p.lateral_speed_mps = 0.0  # both stay on the one line
    manager.pedestrians = [a, b]
    manager._consider_activities = lambda: None  # just walking: no jog or bench picked up mid-test
    far = Car(x=10.0, y=30.0, heading=0.0, speed=0.0)  # parked nearby: nobody despawns
    closest, reached = 99.0, set()
    for _ in range(600):
        manager.update(far, 1.0 / 30.0)
        closest = min(closest, math.hypot(a.x - b.x, a.y - b.y))
        if a.x > 19.0:
            reached.add("a")
        if b.x < 1.0:
            reached.add("b")
    assert closest >= 2 * a.radius_m - 0.05
    assert reached == {"a", "b"}


_WALL = [(15.0, -6.0), (25.0, -6.0), (25.0, -1.0), (15.0, -1.0)]


def _pedestrians_by_wall(with_index):
    wall = Building(points_m=list(_WALL), bbox=(15.0, -6.0, 25.0, -1.0))
    manager = PedestrianManager([_FOOTWAY], target_count=0)
    if with_index:
        taxi = TaxiManager(ways=[])
        taxi.static_index.sync("buildings", [wall], Category.BUILDING)
        manager.static_index = taxi.static_index
    else:
        manager.set_venue_buildings([wall])
    return manager


def test_scenario8_pedestrian_dodge_stops_at_wall():
    for with_index in (True, False):
        manager = _pedestrians_by_wall(with_index)
        ped = _ped(20.0, -0.5)  # the dodge goes to the taxi's right: into the wall
        manager.pedestrians = [ped]
        car, dt = Car(x=10.0, y=0.0, heading=0.0, speed=10.0), 1.0 / 30.0
        for _ in range(40):
            car.x += car.speed * dt
            manager.check_player_avoidance(car, dt)
            assert not point_in_polygon(ped.x, ped.y, _WALL), with_index
        assert ped.x != 20.0  # it slid along the wall
        # Pushed toward the wall by an overlapping neighbour: stays out too.
        manager = _pedestrians_by_wall(with_index)
        a, b = _ped(20.0, -0.9), _ped(20.0, -0.5)
        manager.pedestrians = [a, b]
        manager.rebuild_spatial_grid()
        manager._separate_pedestrians(dt)
        assert not point_in_polygon(a.x, a.y, _WALL) and not point_in_polygon(b.x, b.y, _WALL), with_index


def test_avoidance_identical_to_scan():
    rng = random.Random(5)
    poses = [(rng.uniform(-8.0, 8.0), rng.uniform(-8.0, 8.0), rng.random() < 0.2, rng.random() < 0.3) for _ in range(50)]

    def crowd():
        peds = []
        for x, y, cyclist, dodging in poses:
            p = _ped(x * 3.0, y * 3.0)  # spread out: no separation contacts
            p.is_cyclist = cyclist
            if dodging:
                p.dodge_timer, p.dodge_vx, p.curse_timer = 0.2, 1.0, 0.5
            peds.append(p)
        return peds

    manager = PedestrianManager([_FOOTWAY], target_count=0)
    manager.pedestrians, reference, ref_curses = crowd(), crowd(), []
    dt = 1.0 / 30.0
    for tick in range(60):
        car = Car(x=-30.0 + tick, y=tick * 0.3, heading=0.1 * tick, speed=10.0 if tick % 7 else -4.0)
        random.seed(tick)
        got = manager.check_player_avoidance(car, dt)
        random.seed(tick)
        want = _old_avoidance(reference, ref_curses, car, dt)
        assert got == want
    fields = lambda p: (p.x, p.y, p.dodge_vx, p.dodge_vy, p.dodge_timer, p.curse_timer, p.curse_text)
    assert [fields(p) for p in manager.pedestrians] == [fields(p) for p in reference]
    assert manager.curses == ref_curses


def test_taxi_dodge_respects_way_layer():
    deck = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5, layer=1)
    for car_layer, dodger in ((1, "deck"), (0, "footway")):
        manager = PedestrianManager([_FOOTWAY], target_count=0)
        walkers = {"deck": _ped(20.0, 0.0, deck), "footway": _ped(20.0, 0.0)}
        manager.pedestrians = list(walkers.values())
        car = Car(x=17.0, y=0.0, heading=0.0, speed=10.0)
        car.layer = car_layer
        manager.check_player_avoidance(car, 1.0 / 30.0)
        assert {k for k, p in walkers.items() if p.dodge_timer > 0.0} == {dodger}


def test_separation_only_on_one_layer():
    deck = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5, layer=1)
    manager = PedestrianManager([_FOOTWAY], target_count=0)
    a, b = _ped(20.0, 0.0, deck), _ped(20.2, 0.0)
    manager.pedestrians = [a, b]
    manager.rebuild_spatial_grid()
    manager._separate_pedestrians(1.0 / 30.0)
    assert (a.x, a.y, b.x, b.y) == (20.0, 0.0, 20.2, 0.0)


# Phase 6: NPC static collisions and swept taxi steps (scenarios 2, 10, 13, 15).
from theroadragetrip import npc as npc_module
from theroadragetrip.collision import StaticObstacleIndex
from theroadragetrip.npc import Driver, update_knocked
from theroadragetrip.osm.models import Railing


def _index(buildings=(), posts=(), railings=()):
    index = StaticObstacleIndex()
    index.sync("buildings", list(buildings), C.BUILDING)
    index.sync("scenery_objects", list(posts), C.POST)
    index.sync("railings", list(railings), C.BARRIER)
    return index


def _npc(vid, x, y, heading, speed=0.0):
    v = place_parked_npc(vid, (x, y), None)
    v.car.x, v.car.y, v.car.heading, v.car.speed = x, y, heading, speed
    return v, Driver(resident_id=vid, vehicle_id=vid, path=[], destination=(x, y))


def _corner_in(v, building):
    return any(point_in_polygon(px, py, building.points_m)
               for px, py in get_oriented_box_corners(v.x, v.y, v.heading, v.length_m, v.width_m))


def _npc_depth(v, post):
    return post_box_depth(post.x, post.y, POST_RADIUS_M, v.x, v.y, v.heading, v.length_m, v.width_m)


def test_sweep_samples_counts():
    from theroadragetrip.collision import sweep_samples
    assert [sweep_samples(d, 0.0, 4.0, 1.8) for d in (0.5, 2.3, 9.0, 100.0)] == [1, 3, 10, 16]


def test_scenario2_junction_crash_slide_stops_at_static():
    residents, manager = ResidentManager(), NPCVehicleManager(target_count=2)
    a, _ = _npc(1, -8.0, 0.0, 0.0, 12.0)
    b, _ = _npc(2, 0.0, -8.0, math.pi / 2, 12.0)
    manager.vehicles.extend([a, b])
    peds, dt = PedestrianManager([], target_count=0), 1.0 / 30.0
    for frame in range(60):
        prev = {id(v): (v.x, v.y, v.heading) for v in (a, b)}
        for v in (a, b):
            v.car.x += math.cos(v.heading) * v.car.speed * dt
            v.car.y += math.sin(v.heading) * v.car.speed * dt
        manager._check_vehicle_collision(a, [b], residents, peds, frame * dt, prev[id(a)], prev)
        if a.knock_vx or a.knock_vy:
            break
    assert (a.knock_vx or a.knock_vy) and (b.knock_vx or b.knock_vy)
    # A bollard in a's slide path, a building corner in b's.
    da = math.atan2(a.knock_vy, a.knock_vx)
    post = NS(x=a.x + math.cos(da) * (a.length_m / 2 + 1.0), y=a.y + math.sin(da) * (a.length_m / 2 + 1.0), kind="bollard")
    db = math.atan2(b.knock_vy, b.knock_vx)
    bx, by = b.x + math.cos(db) * (b.length_m / 2 + 1.5), b.y + math.sin(db) * (b.length_m / 2 + 1.5)
    building = Building(points_m=[(bx, by), (bx + 10 * math.cos(db - 0.6), by + 10 * math.sin(db - 0.6)),
                                  (bx + 14 * math.cos(db), by + 14 * math.sin(db)),
                                  (bx + 10 * math.cos(db + 0.6), by + 10 * math.sin(db + 0.6))])
    index = _index([building], [post])
    for _ in range(90):
        for v in (a, b):
            update_knocked(v, dt, static_index=index)
    assert not (a.knock_vx or a.knock_vy or b.knock_vx or b.knock_vy)
    assert _npc_depth(a, post) < 0.0 and not _corner_in(b, building)


def _taxi_step(dt, speed=69.0, heading_v=0.0):
    car = Car(x=0.0, y=0.0, heading=0.0, speed=speed)
    prev = (car.x, car.y, car.heading)
    car.x += math.cos(heading_v) * speed * dt
    car.y += math.sin(heading_v) * speed * dt
    return car, prev


def test_scenario10_taxi_stall_step_hits_bollard():
    for dt in (1.0 / 30.0, 0.13):
        post = NS(x=2.1, y=0.0, kind="bollard")
        car, prev = _taxi_step(dt)
        manager = TaxiManager(ways=[])
        previous = manager.sweep_static(car, prev, [], [], [], [post])
        assert manager.check_post_collision(car, [post], 0.0, previous_position=previous), dt
        assert post.knocked_angle is not None  # 69 m/s: knocked down as today
        fence = Railing(points_m=[(2.1, -5.0), (2.1, 5.0)], bbox=(2.1, -5.0, 2.1, 5.0), kind="wall")
        car, prev = _taxi_step(dt)
        manager = TaxiManager(ways=[])
        previous = manager.sweep_static(car, prev, [], [], [fence], [])
        assert manager.check_barrier_collision(car, [fence], 0.0, previous_position=previous), dt
        assert car.speed == 0.0 and car.x + car.length_m / 2 < 2.1 + 1.0
        sceneries = [NS(trees=[(2.1, 0.0)])]
        car, prev = _taxi_step(dt)
        manager = TaxiManager(ways=[])
        manager.sweep_static(car, prev, [], sceneries, [], [])
        assert manager.check_tree_collision(car, sceneries, 0.0) == 1, dt
        assert car.speed == 69.0  # trees never stop the taxi


def test_scenario10_taxi_sideways_hits_bollard():
    post = NS(x=0.0, y=1.3, kind="bollard")
    car, prev = _taxi_step(0.13, speed=20.0, heading_v=math.pi / 2)
    car.speed = 5.0  # sliding sideways, slow forwards: a stop, not a knock-down
    manager = TaxiManager(ways=[])
    assert _depth(car, post) < 0.0  # the end pose alone misses it
    previous = manager.sweep_static(car, prev, [], [], [], [post])
    assert manager.check_post_collision(car, [post], 0.0, previous_position=previous)
    assert car.speed == 0.0 and _depth(car, post) < 0.0


def test_scenario10_far_npc_stops_at_bollard():
    manager = NPCVehicleManager(target_count=1)
    v, driver = _npc(1, 0.0, 0.0, 0.0, 25.0)
    manager.vehicles.append(v)
    manager.drivers[1] = driver
    post = NS(x=v.length_m / 2 + 1.0, y=0.0, kind="bollard")
    manager.static_index = _index(posts=[post])
    prev = (v.x, v.y, v.heading)
    v.car.x += 25.0 * 4 / 30.0  # FAR_TRAFFIC_STEP x dt: 3.3 m, the post ends behind the front
    manager._static_collisions([v], {id(v): prev}, NS(sim_time=0.0, ways=[]), None)
    assert v.car.speed == 0.0 and _npc_depth(v, post) < 0.0
    assert v.debug_waiting_for == "static obstacle" and driver.recovery_stage == "STUCK"


def _scenario13():
    residents, npcs = ResidentManager(), NPCVehicleManager(target_count=1)
    peds, dt = PedestrianManager([], target_count=0), 1.0 / 30.0
    taxi_mgr, car = TaxiManager(ways=[]), Car(x=0.0, y=0.0, heading=0.0, speed=12.0)
    v, driver = _npc(1, car.length_m + 0.2, 0.0, math.pi / 2)
    npcs.vehicles.append(v)
    npcs.drivers[1] = driver
    post = NS(x=car.length_m / 2 + 0.3, y=car.width_m / 2 + 0.05, kind="bollard")
    building = Building(points_m=_square(v.x + v.length_m / 2 + 5.0, 0.0, 4.0))
    index = _index([building], [post])
    npcs.static_index = index
    impulses, posts_hit = 0, 0
    for frame in range(60):
        prev_car = (car.x, car.y, car.heading)
        car.x += car.speed * dt
        previous = taxi_mgr.sweep_static(car, prev_car, [building], [], [], [post])
        score = taxi_mgr.total_score
        taxi_mgr.check_post_collision(car, [post], frame * dt, previous_position=previous)
        posts_hit += taxi_mgr.total_score < score
        knocked = bool(v.knock_vx or v.knock_vy)
        npcs._check_vehicle_collision(v, [car], residents, peds, frame * dt, (v.x, v.y, v.heading),
                                      {id(car): prev_car, id(v): (v.x, v.y, v.heading)})
        impulses += not knocked and bool(v.knock_vx or v.knock_vy)
        update_knocked(v, dt, static_index=index)
    return posts_hit, impulses, (v.x, v.y, v.heading), (car.x, car.y), not _corner_in(v, building)


def test_scenario13_simultaneous_post_vehicle_building():
    first = _scenario13()
    assert first == _scenario13()
    posts_hit, impulses, _, _, outside = first
    assert posts_hit == 1 and impulses <= 1 and outside


def test_scenario15_dense_traffic_no_static_overlap():
    rng, dt = random.Random(15), 1.0 / 30.0
    streets = [i * 60.0 for i in range(6)]  # 300 x 300 m: streets every 60 m, 10 m wide
    buildings = [Building(points_m=_square(sx + 30.0, sy + 30.0, 22.0)) for sx in streets[:-1] for sy in streets[:-1]]
    posts, railings = [], []
    while len(posts) < 200:
        s, t = rng.choice(streets), rng.uniform(5.0, 295.0)
        if min(abs(t - u) for u in streets) < 8.0:
            continue  # kerbs only, not across a junction
        side = rng.choice((-1, 1)) * 4.6
        posts.append(NS(x=t, y=s + side, kind="bollard") if rng.random() < 0.5 else NS(x=s + side, y=t, kind="bollard"))
    for s in streets:
        for t in range(15, 290, 60):  # 15..35 m along each block's kerb
            railings.append(Railing(points_m=[(t, s + 5.2), (t + 20.0, s + 5.2)], bbox=(t, s + 5.2, t + 20.0, s + 5.2)))
    manager = NPCVehicleManager(target_count=150)
    manager.static_index = _index(buildings, posts, railings)
    world = NS(sim_time=0.0, ways=[])
    lanes = []
    for vid in range(150):
        along_x, s = rng.random() < 0.5, rng.choice(streets)
        heading = rng.choice((0.0, math.pi)) + (0.0 if along_x else math.pi / 2)
        t = rng.uniform(0.0, 300.0)
        s += rng.choice((-2.0, 2.0))  # in a lane
        v, driver = _npc(vid, t if along_x else s, s if along_x else t, heading, rng.uniform(8.0, 14.0))
        manager.vehicles.append(v)
        manager.drivers[vid] = driver
        lanes.append([rng.uniform(1.0, 2.0), rng.uniform(0.0, 6.0), 0.0, s])  # drift m/s, phase, waiting s, lane
    hits = {v.vehicle_id: [] for v in manager.vehicles}
    for frame in range(int(60 / dt)):
        world.sim_time = frame * dt
        prev = {id(v): (v.x, v.y, v.heading) for v in manager.vehicles}
        for v, lane in zip(manager.vehicles, lanes):
            if lane[2] > 0.0:
                lane[2] -= dt
                continue
            fx, fy = math.cos(v.heading), math.sin(v.heading)
            drift = lane[0] * math.sin(world.sim_time * 0.7 + lane[1])  # wanders toward a kerb and back
            v.car.x = (v.car.x + (fx * 11.0 - fy * drift) * dt) % 300.0
            v.car.y = (v.car.y + (fy * 11.0 + fx * drift) * dt) % 300.0
            prev[id(v)] = (v.x - (fx * 11.0 - fy * drift) * dt, v.y - (fy * 11.0 + fx * drift) * dt, v.heading)
        manager._static_collisions(manager.vehicles, prev, world, None)
        for v, lane in zip(manager.vehicles, lanes):
            if v.car.speed == 0.0 and lane[2] <= 0.0:  # stopped by a hit: the reroute takes a moment
                hits[v.vehicle_id].append(world.sim_time)
                assert not any(_npc_depth(v, p) > 0.0 for p in posts)
                assert not any(_corner_in(v, b) for b in buildings)
                lane[0], lane[2], v.car.speed = 0.0, 1.0, 11.0  # rerouted: back in its lane, no more wandering
                if abs(math.sin(v.heading)) < 0.5:
                    v.car.y = lane[3]
                else:
                    v.car.x = lane[3]
    assert sum(map(len, hits.values())) > 0
    for times in hits.values():
        assert all(sum(1 for u in times if t <= u < t + 10.0) <= 3 for t in times), times


def test_npc_drives_out_of_initial_overlap():
    manager = NPCVehicleManager(target_count=1)
    v, driver = _npc(1, 0.0, 0.0, 0.0, -2.0)
    manager.vehicles.append(v)
    manager.drivers[1] = driver
    post = NS(x=v.length_m / 2 + POST_RADIUS_M - 0.1, y=0.0, kind="bollard")  # depth 0.1
    building = Building(points_m=_square(0.0, v.width_m / 2 + 10.0 - 0.2, 10.0))  # side 0.2 m inside
    manager.static_index = _index([building], [post])
    world = NS(sim_time=0.0, ways=[])
    v.car.x = -0.3  # backing away from both
    manager._static_collisions([v], {id(v): (0.0, 0.0, 0.0)}, world, None)
    assert v.car.x == -0.3 and v.car.speed == -2.0
    v.car.x, v.car.speed = 0.3, 2.0  # deeper into the post
    manager._static_collisions([v], {id(v): (0.0, 0.0, 0.0)}, world, None)
    assert v.car.speed == 0.0 and v.car.x == 0.0


def test_npc_static_hit_no_oscillation(monkeypatch):
    calls = []
    real = npc_module._npc_blocked
    monkeypatch.setattr(npc_module, "_npc_blocked", lambda *a, **k: calls.append(k["manoeuvre"]) or real(*a, **k))
    manager = NPCVehicleManager(target_count=1)
    v, driver = _npc(1, 0.0, 0.0, 0.0, 5.0)
    manager.vehicles.append(v)
    manager.drivers[1] = driver
    post = NS(x=v.length_m / 2 + 0.5, y=0.0, kind="bollard")
    manager.static_index = _index(posts=[post])
    world = NS(sim_time=0.0, ways=[])
    for i in range(4):
        world.sim_time = i * 0.5
        v.car.x, v.car.speed = 1.0, 5.0
        manager._static_collisions([v], {id(v): (0.0, 0.0, 0.0)}, world, None)
        assert v.car.speed == 0.0 and driver.recovery_stage == "STUCK"
    assert calls == [True, True, False, False]  # the third hit within 2 s skips the manoeuvre: reroute
    world.sim_time = 10.0  # long after: counted afresh
    v.car.x = 1.0
    manager._static_collisions([v], {id(v): (0.0, 0.0, 0.0)}, world, None)
    assert calls[-1] is True


def test_taxi_sweep_passage_through_building_not_stopped():
    from theroadragetrip.osm import Way
    road = Way(points_m=[(-20.0, 0.0), (40.0, 0.0)], highway="residential", half_width_m=3.0)
    building = Building(points_m=[(5.0, -8.0), (15.0, -8.0), (15.0, 8.0), (5.0, 8.0)], bbox=(5.0, -8.0, 15.0, 8.0))
    car, prev = _taxi_step(1.0 / 30.0)  # 69 m/s: 2.3 m, the front reaches into the building
    car.x += 1.2
    prev = (1.2, 0.0, 0.0)
    manager = TaxiManager(ways=[road])
    end = car.x
    previous = manager.sweep_static(car, prev, [building], [], [], [], current_way=road)
    assert car.x == end and previous == prev[:2]
    assert not manager.check_building_collision(car, [building], 0.0, previous, ways=[road], current_way=road)
    assert car.x == end
