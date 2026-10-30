"""New SFX follow simulation transitions and reach clients exactly once."""
from collections import Counter

import pytest

from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.physics import Car
from test_activities import _make_manager_and_pedestrian
from test_server_headless import _build_server
from test_tennis import tennis_world


def test_tennis_hits_and_bounces_are_once_per_turn_not_per_player():
    manager,court,car,view = tennis_world()
    manager.tennis_open = True
    manager.sim_time = 2
    manager.ensure_sports_players(car,view)
    for _ in range(72):  # 3.6 s of point 0, two shots into the net: hits at 0/1.6, a bounce at 1.2, then the pause
        manager.sim_time += .05
        for player in manager.pedestrians:
            manager._update_activity(player,.05)
    assert Counter(group for group,_ in manager.sound_events) == {'sport.tennis_hit':2,'sport.tennis_bounce':1}
    before = list(manager.sound_events)
    manager.tennis_open = False
    for player in manager.pedestrians:
        manager._update_activity(player,.05)
    assert manager.sound_events == before


def test_beach_ball_hit_is_shared_by_both_players():
    from theroadragetrip.activities import ActivityManager, ActivityRegistry
    from theroadragetrip.activities.plugins.beach_games import BeachGamesPlugin
    from test_beach_activities import beach_world
    manager,beach,water,car,view = beach_world()
    registry = ActivityRegistry()
    registry.register(BeachGamesPlugin())
    manager.activity_manager = ActivityManager(registry)
    manager.beach_open = True
    manager.sim_time = 2
    manager.ensure_sports_players(car,view)
    assert len(manager.pedestrians) == 2
    for _ in range(72):
        manager.sim_time += .05
        for p in manager.pedestrians:
            manager._update_activity(p,.05)
    assert [g for g,_ in manager.sound_events] == ['sport.beach_ball','sport.beach_ball']


def test_drink_sequence_only_when_a_fresh_bottle_is_opened():
    manager,ped = _make_manager_and_pedestrian()
    ped.bottles = 2
    ped.animation_state = 'sitting'
    car = Car(x=-100,y=-100,heading=0,speed=0)
    # Keep the sitter in place; use the real manager update for drinking and cue emission.
    manager._update_activity = lambda *_: True
    for _ in range(5):
        manager.update(car,.1)
    assert [g for g,_ in manager.sound_events] == ['pedestrian.bottle_drink']
    assert 0 < ped.bottle_left < 1
    ped.animation_state = 'walking'
    manager.update(car,.1)
    ped.animation_state = 'sitting'
    manager.update(car,.1)
    assert len(manager.sound_events) == 1  # resuming the same open bottle is silent
    ped.bottle_left = 1
    manager.update(car,.1)
    assert len(manager.sound_events) == 2
    assert not PedestrianManager.drink(ped,0)


def test_queued_sound_events_reach_the_wire_once_and_clear(tmp_path,monkeypatch):
    server = _build_server(tmp_path,monkeypatch)
    sent = []
    monkeypatch.setattr(server,'_broadcast_state',lambda **kw: sent.extend(kw.get('events') or []))
    at = (server.car.x,server.car.y)
    server.world.pedestrian_mgr.play_sound('sport.beach_ball',at)
    server.world.npc_manager.bus_brakes.append(at)
    server.world.npc_manager.bicycle_bells.append(at)
    server.tick(1/30)
    server.tick(1/30)
    for group in ['sport.beach_ball','vehicle.bus_air_brake','vehicle.bus_doors','vehicle.bicycle_bell']:
        assert [e for e in sent if e.get('group') == group] == [{'type':'sound','group':group,'at':list(at)}]
    assert not server.world.pedestrian_mgr.sound_events and not server.world.npc_manager.bus_brakes
    assert not server.world.npc_manager.bicycle_bells


@pytest.mark.parametrize('kind,expected',[('hedge','collision.hedge_break'),('fence','collision.fence')])
def test_hedge_breaks_use_their_own_sound(tmp_path,monkeypatch,kind,expected):
    from theroadragetrip.osm import Railing
    server = _build_server(tmp_path,monkeypatch)
    server._on_foot = False
    server.car.x = server.car.y = 1_000_000
    server.car.speed = 5
    server.car.heading = 0
    x,y = server.car.x,server.car.y
    barrier_x = x + server.car.length_m / 2 + .05
    server.world.railings = [Railing([(barrier_x,y-5),(barrier_x,y+5)],bbox=(barrier_x,y-5,barrier_x,y+5),kind=kind)]
    sent = []
    monkeypatch.setattr(server,'_broadcast_state',lambda **kw: sent.extend(kw.get('events') or []))
    for _ in range(3):
        server.tick(1/30)
    collision = [e['group'] for e in sent if e.get('group','').startswith('collision.')]
    assert collision == [expected]


def test_activity_sound_queue_is_bounded():
    manager,_ = _make_manager_and_pedestrian()
    for _ in range(100):
        manager.play_sound('sport.beach_ball',(0,0))
    assert len(manager.sound_events) == 64
