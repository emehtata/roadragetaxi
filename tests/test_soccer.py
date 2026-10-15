import math
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


def _foul(manager, players, ball, fouled_team, x, y):
    fouled = next(p for p in players if ball.players[id(p)] == fouled_team and p is not ball.goalies.get(fouled_team))
    by = next(p for p in players if ball.players[id(p)] == 1 - fouled_team and p is not ball.goalies.get(1 - fouled_team))
    fouled.x, fouled.y, fouled.speed = x, y, 0.0
    by.x, by.y, by.speed = x - 0.5, y, 6.0
    from theroadragetrip.activities.plugins.ice_skating import collide
    for fallen, knocker in collide(by, [fouled]):
        ball.foul(ball.players[id(fallen)], fallen.x, fallen.y, manager.sim_time)
    return fouled


def test_a_player_knocked_down_by_an_opponent_wins_a_free_kick_there():
    manager, players, ball = _game(4, checks=12)
    fouled = _foul(manager, players, ball, 0, 50.0, 40.0)  # midfield
    team = ball.players[id(fouled)]
    assert ball.set_pieces == (1, 0) and ball.restart_team == team and not ball.penalty
    assert (round(ball.x), round(ball.y)) == (50, 40) and (ball.vx, ball.vy) == (0.0, 0.0)
    for _ in range(80):  # the fouled team takes it; the others wait
        manager.sim_time += 0.1
        for player in players:
            manager._update_activity(player, 0.1)
        if ball.held_by is not None or ball.last_hit == manager.sim_time:
            break
    taker = ball.held_by
    assert taker is not None and ball.players[id(taker)] == team


def test_a_foul_in_the_penalty_area_is_a_penalty_from_the_spot():
    manager, players, ball = _game(5, checks=12)
    attack = -1.0 if ball.defends_u(0) > 0 else 1.0  # team 0's goal to attack
    x, y = ball.world(attack * (soccer.GOAL_U - 8.0), 4.0)  # inside the box
    _foul(manager, players, ball, 0, x, y)
    assert ball.set_pieces == (0, 1) and ball.penalty
    spot_u, spot_v = ball.uv(ball.x, ball.y)
    assert round(spot_u * attack, 1) == soccer.GOAL_U - 11.0 and abs(spot_v) < 1e-6
    for _ in range(100):  # taken: a shot straight away
        manager.sim_time += 0.1
        for player in players:
            manager._update_activity(player, 0.1)
        if not ball.penalty:
            break
    assert not ball.penalty and ball.shots[0] >= 1


def _play(manager, players, seconds, until=None):
    for _ in range(int(seconds / 0.1)):
        manager.sim_time += 0.1
        for player in players:
            manager._update_activity(player, 0.1)
        if until is not None and until():
            return True
    return False


def test_after_a_goal_a_kickoff_from_the_centre_everyone_in_their_own_half():
    manager, players, ball = _game(6, checks=12)
    _play(manager, players, 0.2)
    ball._goal(0, manager.sim_time)  # team 0 conceded: team 0 kicks off
    assert ball.set_piece == "kickoff" and ball.restart_team == 0
    assert [round(c) for c in ball.uv(ball.x, ball.y)] == [0, 0]
    places = None
    for _ in range(400):  # until kicked off: where everyone stood just before
        places = [(p, ball.uv(p.x, p.y)) for p in players]
        if _play(manager, players, 0.1, until=lambda: ball.set_piece is None):
            break
    assert ball.set_piece is None and ball.last_team == 0  # kicked off by team 0...
    assert ball.held_by is None and math.hypot(ball.vx, ball.vy) > 0.0  # ...with a pass
    for player, (u, v) in places:
        if player is ball.goalies.get(ball.players[id(player)]) or player.activity.data.get("fallen_s", 0.0) > 0.0:
            continue
        if math.hypot(u, v) < 1.5:
            continue  # the taker, on the ball
        own = math.copysign(1.0, ball.defends_u(ball.players[id(player)]))
        assert u * own > 0.0, "in their own half"
        assert math.hypot(u, v) >= soccer.RULES.centre_circle_m, "outside the centre circle"


def test_at_a_penalty_everyone_but_the_taker_and_the_goalie_leaves_the_box():
    manager, players, ball = _game(7, checks=12)
    _play(manager, players, 0.2)  # (the goalies take their goals)
    attack = -math.copysign(1.0, ball.defends_u(0))
    _foul(manager, players, ball, 0, *ball.world(attack * (soccer.GOAL_U - 8.0), 4.0))
    assert ball.set_piece == "penalty"
    keeper, shots, places = ball.goalies[1], ball.shots, None
    for _ in range(400):
        places = [(p, ball.uv(p.x, p.y)) for p in players]
        if _play(manager, players, 0.1, until=lambda: ball.set_piece is None):
            break
    assert ball.shots[0] == shots[0] + 1  # the kick: a shot
    inside = [p for p, (u, v) in places if p is not keeper and u * attack > soccer.GOAL_U - 16.5 and abs(v) <= 20.16]
    assert len(inside) == 1  # the taker alone, at the spot
