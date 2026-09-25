import math

import pygame

from theroadragetrip.osm.models import Railway
from theroadragetrip.render.vehicles import TRAIN_LOCOMOTIVE_COLOR, draw_trains
from theroadragetrip.trains import (
    MAX_ACTIVE_TRAINS,
    TRAIN_SPAWN_INTERVAL_S,
    RailwayManager,
    Train,
    TrainRoute,
    build_train_routes,
)


def rail(points, kind="rail"):
    return Railway(points_m=points, kind=kind)


def test_no_railways_means_no_routes_or_trains():
    manager = RailwayManager([rail([(0, 0), (5000, 0)], kind="tram")])
    manager.update(1.0, TRAIN_SPAWN_INTERVAL_S * 3)
    assert manager.routes == [] and manager.trains == []


def test_route_follows_track_geometry_across_joined_ways_and_skips_fragments():
    curve = [(2000 * math.cos(a / 20), 2000 * math.sin(a / 20)) for a in range(21)]  # ~2 km arc
    routes = build_train_routes([
        rail(curve[:11]), rail(curve[10:]),  # one line split in two ways
        rail([(0, 0), (50, 0)]),  # 50 m fragment
    ])
    assert len(routes) == 1
    route = routes[0]
    # Every OSM point is on the route (plus densified points between them).
    assert {tuple(map(round, p)) for p in curve} <= {tuple(map(round, p)) for p in route.points}
    x, y, _ = route.point_at(route.length / 2)
    assert math.hypot(x, y) > 1990  # on the arc, not a straight A->B chord


def test_two_separate_networks_get_their_own_routes():
    routes = build_train_routes([rail([(0, 0), (3000, 0)]), rail([(0, 100), (2000, 100)])])
    assert sorted(round(r.length) for r in routes) == [2000, 3000]


def test_train_reverses_at_the_end_and_comes_back():
    train = Train(TrainRoute([(0, 0), (1000, 0)]), 990.0, 1, speed_mps=20.0)
    train.update(1.0)
    assert (train.distance_m, train.direction) == (1000.0, -1)
    train.update(10.0)
    assert (train.distance_m, train.direction) == (800.0, -1)
    assert train.cars()[0][2] == math.pi  # locomotive faces its travel direction


def test_spawns_follow_game_time_and_never_exceed_the_cap():
    manager = RailwayManager([rail([(0, 0), (20_000, 0)])])
    manager.update(0.0, 1.0)
    assert len(manager.trains) == 2  # one from each end, straight away
    manager.update(0.0, TRAIN_SPAWN_INTERVAL_S / 2)
    assert len(manager.trains) == 2  # interval not over yet
    for _ in range(2000):  # long session: many intervals and turnarounds
        manager.update(5.0, TRAIN_SPAWN_INTERVAL_S)
        assert len(manager.trains) <= MAX_ACTIVE_TRAINS
    assert len(manager.trains) == MAX_ACTIVE_TRAINS


def test_trains_on_a_replaced_route_retire_at_their_turnaround():
    track = [rail([(0, 0), (2000, 0)])]
    manager = RailwayManager(track)
    manager.update(0.0, 1.0)
    manager.rebuild(track + [rail([(2000, 0), (4000, 0)])])
    manager.update(1.0, 0.0)
    assert len(manager.trains) == 4  # old ones keep running (no mid-view vanish)
    for _ in range(200):
        manager.update(1.0, 0.0)
    assert all(train.route is manager.routes[0] for train in manager.trains)


def test_train_renders_through_the_camera_offset():
    pygame.init()
    manager = RailwayManager([rail([(0, 0), (2000, 0)])])
    manager.update(0.0, 1.0)
    manager.trains[:] = [manager.trains[0]]
    manager.trains[0].distance_m = 1000.0
    screen = pygame.Surface((200, 200))
    draw_trains(screen, manager, camx=990.0, camy=0.0, px_per_m=1.0, screen_w=200, screen_h=200)
    # Locomotive centre is 12 m behind the nose at x=1000 -> x=988 -> screen x=98.
    assert screen.get_at((98, 100))[:3] == TRAIN_LOCOMOTIVE_COLOR
    blank = pygame.Surface((200, 200))
    draw_trains(blank, manager, camx=50_000.0, camy=0.0, px_per_m=1.0, screen_w=200, screen_h=200)
    assert pygame.transform.average_color(blank)[:3] == (0, 0, 0)  # far off-screen: nothing drawn
