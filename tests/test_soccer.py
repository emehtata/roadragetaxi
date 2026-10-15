import random

from theroadragetrip.activities.plugins import soccer
from theroadragetrip.geo import point_in_polygon
from theroadragetrip.osm import Scenery, Way
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.physics import Car

PITCH = [(0.0, 10.0), (100.0, 10.0), (100.0, 74.0), (0.0, 74.0)]


def _game(seed, sport="soccer", checks=12):
    random.seed(seed)
    soccer.PLUGIN.balls.clear()  # module state: other tests' pitches
    sidewalk = Way(points_m=[(-10.0, 5.0), (110.0, 5.0)], highway="footway", half_width_m=2.0)
    manager = PedestrianManager([sidewalk], target_count=0)
    manager.set_scenery_features([], [Scenery(PITCH, "pitch", bbox=(0.0, 10.0, 100.0, 74.0), sport=sport)])
    manager.soccer_open = True
    car = Car(x=50.0, y=0.0, heading=0.0, speed=0.0)
    view = (-20.0, -20.0, 120.0, 100.0)
    for step in range(1, checks + 1):
        manager.sim_time = step * 2.0
        manager.ensure_sports_players(car, view)
    players = [p for p in manager.pedestrians if p.activity and p.activity.plugin_id == "soccer"]
    for player in players:
        player.activity.data["duration_s"] = 1e9
    ball = next(iter(soccer.PLUGIN.balls.values()), None)
    return manager, players, ball


def test_only_soccer_pitches_get_a_game_and_at_most_ten_field_players_a_side():
    assert not _game(0, sport="tennis")[1]
    manager, players, ball = _game(0, checks=20)
    assert 16 <= len(players) <= soccer.FIELD_PLAYERS_MAX * 2 + 2  # sized by the pitch: up to 10 a side and the goalies
    teams = [ball.players[id(p)] for p in players]
    assert max(teams.count(0), teams.count(1)) <= soccer.FIELD_PLAYERS_MAX + 1
    # A full game takes no more, however many walk by.
    for extra in range(30):
        ball.players[-extra - 1] = extra % 2
    walker = manager.spawn_pedestrian_at(50.0, 5.0)
    context = manager._activity_context(walker)
    assert soccer.PLUGIN.find_location(context) is None


def test_soccer_is_played_with_a_white_ball_that_stays_on_the_pitch():
    manager, players, ball = _game(1)
    seen, goals = set(), 0
    for _ in range(6000):  # 10 min
        manager.sim_time += 0.1
        for player in players:
            manager._update_activity(player, 0.1)
        seen.add((round(ball.x / 5), round(ball.y / 5)))
        assert point_in_polygon(ball.x, ball.y, PITCH) or ball.held_by is not None
    assert len(seen) > 30 and sum(ball.goals) >= 1  # all over the pitch, and goals
    assert sorted(ball.goalies) == [0, 1] and {tuple(g.color) for g in ball.goalies.values()} == set(soccer.GOALIE_COLORS)
    assert ball.shots[0] / max(1, sum(ball.shots)) >= 0.8  # mostly from the final third
    assert soccer.ball_positions() == [[round(ball.x, 2), round(ball.y, 2)]]


def test_a_ball_over_the_touchline_goes_to_the_other_team():
    manager, players, ball = _game(2, checks=4)
    kicker = next(p for p in players if p is not ball.goalies.get(ball.players[id(p)]))
    ball.held_by = None
    ball.x, ball.y = 50.0, 70.0
    ball.hit_toward(kicker, (50.0, 200.0), 10.0, manager.sim_time)  # out over the far touchline
    for _ in range(10):
        manager.sim_time += 0.1
        ball.advance(manager.sim_time)
    assert (ball.vx, ball.vy) == (0.0, 0.0) and point_in_polygon(ball.x, ball.y, PITCH)
    assert ball.restart_team == 1 - ball.players[id(kicker)]


def test_no_soccer_while_the_pitch_is_closed():
    manager, players, ball = _game(3, checks=2)
    manager.soccer_open = False  # snow on it, or dark and unlit
    for player in players:
        manager._update_activity(player, 0.1)
    assert all(p.activity is None for p in players)
