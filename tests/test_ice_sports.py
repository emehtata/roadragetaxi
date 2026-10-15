import math
from theroadragetrip.osm import Scenery, Way
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager

RINK = [(0.0, 10.0), (40.0, 10.0), (40.0, 30.0), (0.0, 30.0)]


def _manager(kind="ice_rink"):
    sidewalk = Way(points_m=[(-10.0, 5.0), (60.0, 5.0)], highway="footway", half_width_m=2.0)
    manager = PedestrianManager([sidewalk], target_count=0)
    manager.set_scenery_features([], [Scenery(RINK, kind, bbox=(0.0, 10.0, 40.0, 30.0))])
    return manager


def _inside(ped):
    return 0.0 <= ped.x <= 40.0 and 10.0 <= ped.y <= 30.0


def test_open_ice_gets_hockey_players_who_stay_on_it_and_leave_when_it_closes():
    manager = _manager()
    car = Car(x=20.0, y=0.0, heading=0.0, speed=0.0)
    manager.ensure_sports_players(car)
    assert not manager.pedestrians  # the ice is not open (summer, or dark and unlit)

    manager.sports_ice_open = True
    for step in range(3):
        manager.sim_time = step * 2.0
        manager.ensure_sports_players(car)
    players = [p for p in manager.pedestrians if p.activity and p.activity.plugin_id == "ice_hockey"]
    assert len(players) >= 2 and all(_inside(p) for p in players)

    for _ in range(100):  # 10 s of hockey: everyone stays on the ice, skating
        manager.sim_time += 0.1
        for player in players:
            manager._update_activity(player, 0.1)
    assert all(_inside(p) and p.activity is not None for p in players)

    manager.sports_ice_open = False  # dusk past 22:00, or a thaw
    for player in players:
        manager._update_activity(player, 0.1)
    assert all(p.activity is None for p in players)


def test_a_frozen_pitch_gets_skaters():
    manager = _manager("pitch")
    manager.sports_ice_open = True
    manager.ensure_sports_players(Car(x=20.0, y=0.0, heading=0.0, speed=0.0))
    assert [p.activity.plugin_id for p in manager.pedestrians] == ["ice_skating"] * 2  # two a check


def test_an_ice_rink_is_closed_you_crash_into_its_boards():
    taxi = TaxiManager([Way([(0.0, 0.0), (100.0, 0.0)], "residential", 4.0)])
    rink = Scenery(RINK, "ice_rink", bbox=(0.0, 10.0, 40.0, 30.0))
    car = Car(x=20.0, y=11.0, heading=1.57, speed=8.0)
    assert taxi.check_fence_collision(car, [rink], 1.0, previous_position=(20.0, 6.0))
    assert (car.x, car.y, car.speed) == (20.0, 6.0, 0.0)


def _hockey_game(seed):
    import random

    from theroadragetrip.activities.plugins import ice_hockey

    random.seed(seed)
    ice_hockey._pucks.clear()  # module state: other tests' rinks
    manager = _manager()
    manager.sports_ice_open = True
    car = Car(x=20.0, y=0.0, heading=0.0, speed=0.0)
    for step in range(8):  # a check every 2 s, one player each
        manager.sim_time = step * 2.0
        manager.ensure_sports_players(car)
    players = [p for p in manager.pedestrians if p.activity and p.activity.plugin_id == "ice_hockey"]
    for player in players:
        player.activity.data["duration_s"] = 1e9  # the whole test long
    return manager, players, next(iter(ice_hockey._pucks.values()))


def test_pond_hockey_two_teams_with_goalies_hit_the_puck_around_the_rink():
    from theroadragetrip.activities.plugins import ice_hockey
    from theroadragetrip.geo import point_in_polygon

    manager, players, puck = _hockey_game(3)
    assert len(players) >= 6
    assert {tuple(p.color) for p in players} == set(ice_hockey.TEAM_COLORS)  # two teams
    seen, swings = set(), 0
    for _ in range(300):  # 30 s
        manager.sim_time += 0.1
        for player in players:
            manager._update_activity(player, 0.1)
            swings += player.stick_swing == ice_hockey.STICK_SWING_S
        seen.add((round(puck.x), round(puck.y)))
        assert point_in_polygon(puck.x, puck.y, RINK)
    assert sorted(puck.goalies) == [0, 1] and sum(p.hockey_goalie for p in players) == 2
    assert swings >= 3 and len(seen) > 20  # hit around, not sitting still
    assert ice_hockey.puck_positions() == [[round(puck.x, 2), round(puck.y, 2)]]


def test_goalies_save_most_shots_and_restart_play_after_a_goal():
    goals, saves, restarts = 0, 0, []
    for seed in range(4):
        manager, players, puck = _hockey_game(seed)
        held = conceding = None
        for _ in range(3000):  # 5 min a game
            manager.sim_time += 0.1
            scored_before = sum(puck.goals)
            for player in players:
                manager._update_activity(player, 0.1)
            if sum(puck.goals) > scored_before:
                goals += 1
                conceding = puck.restart_team
            if puck.held_by is not None and puck.held_by is not held:
                if conceding is not None:  # the first to take the puck after a goal
                    restarts.append(puck.held_by is puck.goalies.get(conceding))
                    conceding = None
                elif puck.held_by in puck.goalies.values():  # a goalie caught it (skaters carry it too)
                    saves += 1
            held = puck.held_by
    assert goals > 0 and saves > goals  # most shots are saved
    assert restarts and all(restarts)  # out of the net by the conceding goalie


def test_most_shots_come_from_the_offensive_zone_after_carrying_and_passing():
    in_zone = outside = 0
    for seed in range(4):
        manager, players, puck = _hockey_game(seed)
        for _ in range(3000):  # 5 min a game
            manager.sim_time += 0.1
            for player in players:
                manager._update_activity(player, 0.1)
        in_zone, outside = in_zone + puck.shots[0], outside + puck.shots[1]
    assert in_zone + outside > 50 and in_zone / (in_zone + outside) >= 0.85  # about 90 %


def test_ice_sports_play_only_where_the_camera_looks():
    from theroadragetrip.activities.plugins import ice_hockey

    ice_hockey._pucks.clear()
    manager = _manager()
    manager.sports_ice_open = True
    car = Car(x=20.0, y=0.0, heading=0.0, speed=0.0)
    far_view = (1000.0, 1000.0, 1200.0, 1150.0)
    manager.ensure_sports_players(car, far_view)
    assert not manager.pedestrians  # the rink is not in view: no game there

    for step in range(1, 4):
        manager.sim_time = step * 2.0
        manager.ensure_sports_players(car, (-50.0, -50.0, 150.0, 90.0))  # the camera over the rink
    assert len(manager.pedestrians) == 6 and ice_hockey.puck_positions()  # two a check

    manager.sim_time += 2.0
    manager.ensure_sports_players(car, far_view)  # the camera moved on (the taxi did not)
    assert not manager.pedestrians and not ice_hockey.puck_positions()


def test_skaters_never_overlap_and_a_faster_one_knocks_the_slower_down():
    from theroadragetrip.activities.plugins.ice_skating import FALL_S, SKATER_RADIUS_M

    manager = _manager("pitch")
    manager.sports_ice_open = True
    car = Car(x=20.0, y=0.0, heading=0.0, speed=0.0)
    for step in range(2):
        manager.sim_time = step * 2.0
        manager.ensure_sports_players(car)
    fast, slow = manager.pedestrians
    fast.x, fast.y, slow.x, slow.y = 10.0, 20.0, 12.0, 20.0
    fast.activity.data["target"] = (30.0, 20.0)  # straight through the slow one
    for _ in range(10):
        manager.sim_time += 0.1
        slow.activity.data["target"] = (slow.x, slow.y)  # standing still on the ice
        manager._update_activity(slow, 0.1)
        manager._update_activity(fast, 0.1)
        assert math.hypot(fast.x - slow.x, fast.y - slow.y) >= 2 * SKATER_RADIUS_M - 1e-6
    assert slow.animation_state == "fallen" and fast.animation_state != "fallen"
    fast.x, fast.y = 35.0, 28.0  # skated off
    for _ in range(int(FALL_S / 0.1) + 2):  # up again after the fall
        manager.sim_time += 0.1
        manager._update_activity(slow, 0.1)
    assert slow.animation_state != "fallen"
