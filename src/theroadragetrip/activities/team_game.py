"""A two-team ball game on one field - ice hockey on a rink, soccer on a
pitch (plugins/ice_hockey.py, plugins/soccer.py): the same game, its
Rules apart.

Each player is an ordinary solo activity; the game is the field's Ball. It
slides or rolls with friction; off the rink's boards it bounces, over a
soccer touchline it is out and the other team restarts. Two teams, each
with a goalie - the team's first player - who stays in front of the goal,
moves across with the ball, catches what comes at the goal and passes it
up field. A field player who reaches the ball carries it: before the
attacking zone they take it forward or pass to a teammate further up,
with the odd long shot; inside it they shoot or pass - so most shots come
from the zone. The nearest opponent chases the carrier and wins the ball
off them; the carrier's teammates move ahead in support. A shot's fate is
decided when it is hit: rules.shot_scores of them go in, the goalie saves
the rest (and any loose ball reaching the goal). After a goal there is no
kick-off or face-off, as on a pond or a park: the conceding goalie takes
the ball out of the net while the scorers back off, and plays it out.

Positions on the field are (u, v) metres of a standard field
(rules.length x rules.width; u along it, goals at +-goal_u), scaled onto
the real field's rectangle (map_chunks.rink_frame).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin
from .plugins.ice_skating import collide, glide, is_down, others_on
from .plugins.park_leisure import sample_interior_point

SET_PIECE_WAIT_MAX_S = 20.0  # a taker waits no longer than this for the field players to take their places
GOALIE_WAIT_MAX_S = 60.0  # ... and for both goalies in their goals (only so nothing waits forever)
STICK_SWING_S = 0.3  # how long the client shows a stick swing or a kick (state pedestrian stick_swing)


@dataclass(frozen=True)
class Rules:
    plugin_id: str
    name: str
    open_flag: str  # the PedestrianManager attribute saying play is on (ice frozen and lit, ...)
    is_field: Callable  # (scenery) -> whether this game is played on it
    length: float  # the standard field (u, v) positions are laid out on
    width: float
    goal_u: float
    goal_half_width: float
    goalie_out_u: float  # in front of the goal line
    goalie_half_range_v: float
    zone_u: float  # past this (toward the other goal): the attacking zone
    boards: bool  # True: the ball bounces off the edge (a rink); False: it goes out (a pitch)
    friction_mps2: float
    bounce: float
    reach_m: float  # a player reaches the ball
    cooldown_s: float
    pass_speed_mps: Tuple[float, float]
    shot_speed_mps: Tuple[float, float]
    shot_aim_v: float  # shots go at the goal's centre +- this
    run_speed_mps: float
    chase_factor: float  # the chaser's speed over run_speed
    carry_speed_mps: float
    ball_ahead_m: float  # a carried ball: this far ahead of the carrier
    ball_side_m: float  # ... and to their right (a stick's blade)
    zone_shot_rate: float  # a carrier's choices, chances per second
    zone_pass_rate: float
    neutral_pass_rate: float
    long_shot_rate: float
    steal_chance: float
    shot_scores: float  # of shots: past the goalie
    goalie_hold_s: float
    restart_s: float
    spot_move_s: float
    support_ahead_u: float  # teammates of the carrier: this far ahead of the ball
    team_colors: Tuple[Tuple[int, int, int], ...]  # the jersey palette: each game draws its two teams' from it
    max_players: int  # both teams, goalies included: a full game takes no more
    # Fouls (soccer): a player knocked down by an opponent wins their team a
    # free kick where it happened - a penalty kick from the spot inside the
    # penalty area they attack. Off for hockey (bodychecks are the game).
    fouls: bool = False
    knockdown_chance: float = 1.0  # of a hard bump (ice_skating.collide)
    penalty_area_u: float = 0.0  # its depth from the goal line
    penalty_area_half_v: float = 0.0
    penalty_spot_u: float = 0.0  # from the goal line
    penalty_scores: float = 0.0
    # FIFA restarts (soccer): after a goal a kick-off from the centre by the
    # conceding team, the others in their own half outside the centre
    # circle; a penalty with everyone but the taker and the goalie out of the
    # area and its arc. The taker waits set_piece_s for them, then plays it.
    kickoff: bool = False
    centre_circle_m: float = 0.0
    set_piece_s: float = 0.0
    goalie_colors: bool = False  # goalies in jerseys of their own (from the palette, unlike both teams'); else the team's


@dataclass
class Ball:
    rules: Rules
    field: object  # the Scenery played on
    frame: list  # map_chunks.rink_frame: [cx, cy, angle, length, width]
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    updated: float = 0.0
    last_hit: float = -1e9
    last_team: Optional[int] = None  # who touched it last (out of play: the other team restarts)
    players: Dict[int, int] = field(default_factory=dict)  # id(pedestrian) -> team 0/1
    goalies: Dict[int, object] = field(default_factory=dict)  # team -> its goalie pedestrian
    shot_scores: bool = False  # the ball in flight is a shot that goes in
    restart_team: Optional[int] = None  # until restart_until: only this team plays it
    restart_until: float = -1e9
    restart_by_goalie: bool = False  # a goal's restart: the goalie takes it out of the net
    held_by: object = None  # who has the ball: a goalie who caught it, a player carrying it
    held_since: float = 0.0
    goals: Tuple[int, int] = (0, 0)
    shots: Tuple[int, int] = (0, 0)  # (from the attacking zone, from outside it)
    set_piece: Optional[str] = None  # a dead-ball restart under way: "kickoff" or "penalty", until its taker plays it
    in_place: set = field(default_factory=set)  # id(player)s at their set-piece spots
    colors: Tuple = ()  # this game's jerseys: (team 0, team 1, goalie 0, goalie 1)
    set_pieces: Tuple[int, int] = (0, 0)  # (free kicks, penalties) awarded

    @property
    def rink(self):  # (ice hockey's name for the field)
        return self.field

    @property
    def penalty(self) -> bool:
        return self.set_piece == "penalty"

    def set_piece_spot(self, pedestrian, team: int) -> Tuple[float, float]:
        """Where a player not taking the set piece stands for it (FIFA): at a
        kick-off in their own half outside the centre circle; at a penalty
        outside the penalty area and its arc. Already there: where they are."""
        rules = self.rules
        u, v = self.uv(pedestrian.x, pedestrian.y)
        if self.set_piece == "kickoff":
            own = math.copysign(1.0, self.defends_u(team))
            u = own * max(abs(u), 1.5) if u * own > 0.0 else own * 1.5
            clear = rules.centre_circle_m + 1.0
            if math.hypot(u, v) < clear:
                scale = clear / (math.hypot(u, v) or 1.0)
                u, v = (u * scale, v * scale) if math.hypot(u, v) > 0.0 else (own * clear, v)
        elif self.set_piece == "penalty":
            goal = -math.copysign(1.0, self.defends_u(self.restart_team))  # the goal the kick is at
            line = rules.goal_u - rules.penalty_spot_u - rules.centre_circle_m - 1.0  # past the arc, so past the area too
            if u * goal > line:
                u = goal * line
        return self.world(u, v)

    def uv(self, x: float, y: float) -> Tuple[float, float]:
        """(x, y) in standard-field metres: u along it (goals at +-goal_u), v across."""
        cx, cy, angle, length, width = self.frame
        dx, dy = x - cx, y - cy
        return ((dx * math.cos(angle) + dy * math.sin(angle)) * self.rules.length / length,
                (-dx * math.sin(angle) + dy * math.cos(angle)) * self.rules.width / width)

    def world(self, u: float, v: float) -> Tuple[float, float]:
        cx, cy, angle, length, width = self.frame
        u, v = u * length / self.rules.length, v * width / self.rules.width
        return cx + u * math.cos(angle) - v * math.sin(angle), cy + u * math.sin(angle) + v * math.cos(angle)

    def defends_u(self, team: int) -> float:
        """The u of the goal `team` defends (team 0 attacks +u)."""
        return -self.rules.goal_u if team == 0 else self.rules.goal_u

    def attack_u(self, pedestrian, team: int) -> float:
        """How far up field `pedestrian` is for `team`: past rules.zone_u is the attacking zone."""
        return self.uv(pedestrian.x, pedestrian.y)[0] * -math.copysign(1.0, self.defends_u(team))

    def goalie_spot(self, team: int) -> Tuple[float, float]:
        rules = self.rules
        goal_u = self.defends_u(team)
        v = max(-rules.goalie_half_range_v, min(rules.goalie_half_range_v, self.uv(self.x, self.y)[1]))
        return self.world(goal_u - math.copysign(rules.goalie_out_u, goal_u), v)

    def stop_at(self, x: float, y: float) -> None:
        self.x, self.y, self.vx, self.vy = x, y, 0.0, 0.0
        self.shot_scores = False

    def take(self, pedestrian, sim_time: float) -> None:
        self.held_by, self.held_since = pedestrian, sim_time
        self.shot_scores = False
        self.last_team = self.players.get(id(pedestrian), self.last_team)

    def advance(self, sim_time: float) -> None:
        """Move to `sim_time` (once per tick, whichever player asks first)."""
        from ..geo import point_in_polygon

        rules = self.rules
        dt = min(0.5, sim_time - self.updated)
        self.updated = sim_time
        if self.held_by is not None:  # at its holder's feet or stick blade
            holder = self.held_by
            ahead_x, ahead_y = math.cos(holder.heading), math.sin(holder.heading)
            x = holder.x + ahead_x * rules.ball_ahead_m + ahead_y * rules.ball_side_m
            y = holder.y + ahead_y * rules.ball_ahead_m - ahead_x * rules.ball_side_m
            # Never through the boards or over the line: at the holder's feet then.
            self.x, self.y = (x, y) if point_in_polygon(x, y, self.field.points_m) else (holder.x, holder.y)
            return
        speed = math.hypot(self.vx, self.vy)
        if dt <= 0.0 or speed <= 0.0:
            return
        slowed = max(0.0, speed - rules.friction_mps2 * dt) / speed
        self.vx, self.vy = self.vx * slowed, self.vy * slowed
        x, y = self.x + self.vx * dt, self.y + self.vy * dt
        u, v = self.uv(x, y)
        mouth = rules.goal_u - rules.goalie_out_u
        if abs(u) >= mouth and abs(v) <= rules.goalie_half_range_v and abs(self.uv(self.x, self.y)[0]) < mouth:
            defending = 0 if u < 0.0 else 1
            goalie = self.goalies.get(defending)
            if self.shot_scores or goalie is None:
                self._goal(defending, sim_time)
            else:  # the save: the goalie catches it
                self.stop_at(goalie.x, goalie.y)
                self.take(goalie, sim_time)
            return
        if point_in_polygon(x, y, self.field.points_m):
            self.x, self.y = x, y
        elif rules.boards:  # back the way it came, slower, a little off-line
            turn = random.uniform(-0.6, 0.6)
            vx, vy = -self.vx * rules.bounce, -self.vy * rules.bounce
            self.vx, self.vy = vx * math.cos(turn) - vy * math.sin(turn), vx * math.sin(turn) + vy * math.cos(turn)
            self.shot_scores = False
        else:  # out of play: it stops on the line, the other team puts it back in
            self.stop_at(self.x, self.y)
            self.restart_team = None if self.last_team is None else 1 - self.last_team
            self.restart_until, self.restart_by_goalie = sim_time + rules.restart_s, False

    def foul(self, fouled_team: int, x: float, y: float, sim_time: float) -> None:
        """A foul on `fouled_team` at (x, y): their free kick there, or their
        penalty kick from the spot inside the penalty area they attack."""
        rules = self.rules
        u, v = self.uv(x, y)
        attack = -math.copysign(1.0, self.defends_u(fouled_team))
        in_area = u * attack >= rules.goal_u - rules.penalty_area_u and abs(v) <= rules.penalty_area_half_v
        if in_area:
            x, y = self.world(attack * (rules.goal_u - rules.penalty_spot_u), 0.0)
        self.held_by = None
        self.stop_at(x, y)
        self.set_piece = "penalty" if in_area else None
        self.in_place = set()
        self.set_pieces = (self.set_pieces[0] + (not in_area), self.set_pieces[1] + in_area)
        setup = rules.set_piece_s if in_area else rules.restart_s
        self.restart_team, self.restart_until, self.restart_by_goalie = fouled_team, sim_time + setup, False

    def _goal(self, conceding: int, sim_time: float) -> None:
        """In the net: the conceding team restarts from its goal mouth."""
        scorer = 1 - conceding
        self.goals = (self.goals[0] + (scorer == 0), self.goals[1] + (scorer == 1))
        if self.rules.kickoff:  # from the centre spot, by the team that conceded
            self.stop_at(*self.world(0.0, 0.0))
            self.set_piece = "kickoff"
            self.in_place = set()
            self.restart_team, self.restart_until = conceding, sim_time + self.rules.set_piece_s
            self.restart_by_goalie = False
            return
        goal_u = self.defends_u(conceding)
        self.stop_at(*self.world(goal_u - math.copysign(0.3, goal_u), 0.0))
        self.restart_team, self.restart_until = conceding, sim_time + self.rules.restart_s
        self.restart_by_goalie = True

    def hit_toward(self, pedestrian, target: Tuple[float, float], speed: float, sim_time: float) -> None:
        dx, dy = target[0] - self.x, target[1] - self.y
        distance = math.hypot(dx, dy) or 1.0
        self.vx, self.vy = dx / distance * speed, dy / distance * speed
        self.last_hit = sim_time
        self.last_team = self.players.get(id(pedestrian), self.last_team)
        self.held_by = None
        self.shot_scores = False
        pedestrian.heading = math.atan2(dy, dx)
        pedestrian.stick_swing = STICK_SWING_S

    def shoot(self, pedestrian, team: int, sim_time: float, scores_chance: Optional[float] = None) -> None:
        """At the other goal; decided now: in, or saved."""
        rules = self.rules
        in_zone = self.attack_u(pedestrian, team) > rules.zone_u
        self.shots = (self.shots[0] + in_zone, self.shots[1] + (not in_zone))
        scores = random.random() < (rules.shot_scores if scores_chance is None else scores_chance)
        self.hit_toward(pedestrian, self.world(-self.defends_u(team), random.uniform(-rules.shot_aim_v, rules.shot_aim_v)),
                        random.uniform(*rules.shot_speed_mps), sim_time)
        self.shot_scores = scores

    def pass_to(self, pedestrian, mate, sim_time: float) -> None:
        self.hit_toward(pedestrian, (mate.x, mate.y), random.uniform(*self.rules.pass_speed_mps), sim_time)

    def goalie_pass(self, goalie, team: int, sim_time: float, mates: List) -> None:
        """Out of the goal to offence: to the teammate furthest up field."""
        attack = -math.copysign(1.0, self.defends_u(team))
        if mates:
            mate = max(mates, key=lambda m: self.uv(m.x, m.y)[0] * attack)
            target = (mate.x, mate.y)
        else:
            target = self.world(0.0, random.uniform(-0.25, 0.25) * self.rules.width)
        self.hit_toward(goalie, target, random.uniform(*self.rules.pass_speed_mps), sim_time)


class TeamGamePlugin(ActivityPlugin):
    """One game's activity: rules.plugin_id, played on rules.is_field fields."""

    def __init__(self, rules: Rules, base_weight: float = 2.0) -> None:
        self.rules = rules
        self.definition = ActivityDefinition(
            id=rules.plugin_id, name=rules.name, min_duration_s=90.0, max_duration_s=300.0,
            cooldown_s=300.0, base_weight=base_weight)
        self.balls: Dict[int, Ball] = {}  # id(field) -> its Ball; a field no one plays on keeps its (still) ball

    def ball_for(self, field_scenery, sim_time: float) -> Optional[Ball]:
        ball = self.balls.get(id(field_scenery))
        if ball is None or ball.field is not field_scenery:
            from ..map_chunks import rink_frame

            frame = rink_frame(field_scenery.points_m)
            if frame is None:
                return None
            # Each game its own jerseys: two teams', and the goalies' unlike both.
            picks = random.sample(self.rules.team_colors, 4)
            colors = tuple(picks) if self.rules.goalie_colors else (picks[0], picks[1], picks[0], picks[1])
            ball = self.balls[id(field_scenery)] = Ball(
                rules=self.rules, field=field_scenery, frame=frame, x=frame[0], y=frame[1], updated=sim_time,
                colors=colors)
            if self.rules.kickoff:  # a game starts with a kick-off, by either team
                ball.set_piece, ball.in_place = "kickoff", set()
                ball.restart_team, ball.restart_until = random.randint(0, 1), sim_time + self.rules.set_piece_s
        return ball

    def ball_positions(self) -> list:
        """Every ball in play (state): [[x, y], ...]."""
        return [[round(b.x, 2), round(b.y, 2)] for b in self.balls.values() if b.players]

    def _open(self, context: ActivityContext) -> bool:
        return bool(getattr(context.pedestrian_manager, self.rules.open_flag, False))

    def find_location(self, context: ActivityContext):
        if not self._open(context):
            return None
        pedestrian = context.pedestrian
        fields = [s for s in context.pedestrian_manager.nearby_sceneries(pedestrian.x, pedestrian.y, 120.0)
                  if len(s.points_m) >= 3 and self.rules.is_field(s)
                  and len(getattr(self.balls.get(id(s)), "players", ())) < self.rules.max_players]
        if not fields:
            return None
        chosen = random.choice(fields)
        point = sample_interior_point(chosen)
        return ActivityLocation(x=point[0], y=point[1], extra=chosen) if point else None

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        pedestrian = context.pedestrian
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0
        chosen = instance.location.extra if instance.location is not None else None
        ball = self.ball_for(chosen, context.sim_time) if chosen is not None else None
        if ball is not None and len(ball.players) >= self.rules.max_players:
            ball = None  # the game filled up on the way: not this time
        instance.data["puck"] = ball  # (named for the first game, ice hockey)
        if ball is None:
            return
        teams = list(ball.players.values())
        team = 0 if teams.count(0) <= teams.count(1) else 1
        ball.players[id(pedestrian)] = team
        instance.data["team"] = team
        instance.data["own_color"] = pedestrian.color
        pedestrian.color = ball.colors[team]
        instance.data["spot"] = None
        instance.data["spot_elapsed_s"] = self.rules.spot_move_s

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        ball: Optional[Ball] = instance.data.get("puck")
        if ball is None or not self._open(context):
            return True
        pedestrian = context.pedestrian
        pedestrian.stick_swing = max(0.0, pedestrian.stick_swing - dt)
        team = instance.data["team"]
        roster = [p for p in context.pedestrian_manager.pedestrians if id(p) in ball.players]
        if len(roster) < len(ball.players):  # despawned players never finish(): drop them
            ball.players = {id(p): ball.players[id(p)] for p in roster}
            ball.goalies = {t: g for t, g in ball.goalies.items() if id(g) in ball.players}
            if ball.held_by is not None and id(ball.held_by) not in ball.players:
                ball.held_by = None
        if team not in ball.goalies:  # every team has a goalie: the first to notice it has none
            ball.goalies[team] = pedestrian
            pedestrian.color = ball.colors[2 + team]
        pedestrian.hockey_goalie = ball.goalies[team] is pedestrian
        ball.advance(context.sim_time)
        if is_down(pedestrian, instance, dt):  # knocked over: down a moment, the play goes on
            if ball.held_by is pedestrian:
                ball.held_by = None  # the ball comes loose
            return False
        mates = [p for p in roster if ball.players[id(p)] == team and p is not pedestrian]
        # Teammates still up: one lying on the ground isn't "nearer the ball".
        field_mates = [p for p in mates if p is not ball.goalies.get(team)
                       and (p.activity is None or p.activity.data.get("fallen_s", 0.0) <= 0.0)]
        if pedestrian.hockey_goalie:
            self._goalie(context, ball, team, field_mates, dt)
        else:
            self._player(context, instance, ball, team, field_mates, dt)
        for fallen, by in collide(pedestrian, others_on(ball.field, pedestrian, roster), self.rules.knockdown_chance):
            fouled = ball.players.get(id(fallen))
            if (self.rules.fouls and ball.set_piece is None  # (walking to places for a set piece: no fouls)
                    and fouled is not None and ball.players.get(id(by)) == 1 - fouled):
                ball.foul(fouled, fallen.x, fallen.y, context.sim_time)
        return instance.data["elapsed_s"] >= instance.data["duration_s"]

    def _goalie(self, context: ActivityContext, ball: Ball, team: int, mates: List, dt: float) -> None:
        rules = self.rules
        goalie = context.pedestrian
        now = context.sim_time
        restart = ball.restart_by_goalie and ball.restart_team == team and now < ball.restart_until
        near = math.hypot(ball.x - goalie.x, ball.y - goalie.y) <= rules.reach_m
        if ball.held_by is goalie and now - ball.held_since >= rules.goalie_hold_s:
            ball.goalie_pass(goalie, team, now, mates)
        elif restart and ball.held_by is None:  # out of the net with it
            if near:
                ball.take(goalie, now)
            else:
                glide(goalie, (ball.x, ball.y), dt, rules.run_speed_mps)
        elif (ball.held_by is None and near and math.hypot(ball.vx, ball.vy) < 2.0 and now - ball.last_hit >= rules.cooldown_s
              and ball.set_piece is None and not (ball.restart_team not in (None, team) and now < ball.restart_until)):
            ball.goalie_pass(goalie, team, now, mates)  # a loose ball at the goal: clear it (not the others' restart)
        elif ball.held_by is not goalie:
            if glide(goalie, ball.goalie_spot(team), dt, rules.run_speed_mps):
                goalie.heading = math.atan2(ball.y - goalie.y, ball.x - goalie.x)
                ball.in_place.add(id(goalie))  # (a set piece waits for this)
            else:
                ball.in_place.discard(id(goalie))

    def _player(self, context: ActivityContext, instance: ActivityInstance, ball: Ball, team: int, mates: List, dt: float) -> None:
        rules = self.rules
        pedestrian = context.pedestrian
        now = context.sim_time
        if ball.held_by is pedestrian:
            self._carry(pedestrian, ball, team, mates, now, dt)
            return
        if ball.set_piece is not None:
            self._set_piece(pedestrian, ball, team, mates, now, dt)
            return
        restarting = ball.restart_team is not None and now < ball.restart_until
        waiting = restarting and ball.restart_team != team
        goalie_restart = restarting and ball.restart_by_goalie  # the goalie takes it, not us
        holder = ball.held_by
        ours = holder is not None and ball.players.get(id(holder)) == team
        to_ball = math.hypot(ball.x - pedestrian.x, ball.y - pedestrian.y)
        chaser = (not waiting and not goalie_restart and not ours and holder not in ball.goalies.values()
                  and all(to_ball <= math.hypot(ball.x - m.x, ball.y - m.y) for m in mates))
        if chaser:  # a loose ball to take, or the carrier to win it off
            if to_ball <= rules.reach_m and now - ball.last_hit >= rules.cooldown_s:
                ball.last_hit = now
                if holder is None or random.random() < rules.steal_chance:
                    ball.take(pedestrian, now)
                    ball.restart_team = None  # (a throw-in or free kick taken: play on)
                    pedestrian.stick_swing = STICK_SWING_S
            else:
                glide(pedestrian, (ball.x, ball.y), dt, rules.run_speed_mps * rules.chase_factor)
            return
        # Hold a spot in the play: between a place on the field and the
        # ball - ahead of it in support while our team has it, back toward
        # the middle while the other team restarts.
        instance.data["spot_elapsed_s"] += dt
        if instance.data["spot"] is None or instance.data["spot_elapsed_s"] >= rules.spot_move_s:
            instance.data["spot_elapsed_s"] = 0.0
            instance.data["spot"] = sample_interior_point(ball.field)
        spot = instance.data["spot"] or (ball.x, ball.y)
        if waiting:
            focus = ball.world(0.0, 0.0)
        elif ours:
            u, v = ball.uv(ball.x, ball.y)
            ahead = -math.copysign(1.0, ball.defends_u(team))
            limit = rules.goal_u - 6.0
            focus = ball.world(max(-limit, min(limit, u + ahead * rules.support_ahead_u)), v)
        else:
            focus = (ball.x, ball.y)
        if glide(pedestrian, ((spot[0] + focus[0]) / 2.0, (spot[1] + focus[1]) / 2.0), dt, rules.run_speed_mps):
            pedestrian.heading = math.atan2(ball.y - pedestrian.y, ball.x - pedestrian.x)

    def _set_piece(self, pedestrian, ball: Ball, team: int, mates: List, now: float, dt: float) -> None:
        """A kick-off or penalty: the taker - the restarting team's player
        nearest the ball - goes to it and, once everyone has had
        set_piece_s to take their places, kicks: a kick-off a pass to a
        teammate, a penalty a shot. Everyone else to set_piece_spot."""
        rules = self.rules
        to_ball = math.hypot(ball.x - pedestrian.x, ball.y - pedestrian.y)
        taker = team == ball.restart_team and all(to_ball <= math.hypot(ball.x - m.x, ball.y - m.y) for m in mates)
        if not taker:
            if glide(pedestrian, ball.set_piece_spot(pedestrian, team), dt, rules.run_speed_mps):
                pedestrian.heading = math.atan2(ball.y - pedestrian.y, ball.x - pedestrian.x)
                ball.in_place.add(id(pedestrian))
            else:
                ball.in_place.discard(id(pedestrian))
            return
        if to_ball > rules.reach_m:
            glide(pedestrian, (ball.x, ball.y), dt, rules.run_speed_mps)
            return
        # On the ball: wait (set_piece_s at least) until the others are in
        # their places - both goalies in their goals, the field players but
        # the taker in theirs (those no longer than SET_PIECE_WAIT_MAX_S).
        goalie_ids = {id(g) for g in ball.goalies.values()}
        goalies_ready = (len(goalie_ids) == 2 and goalie_ids <= ball.in_place) or now >= ball.restart_until + GOALIE_WAIT_MAX_S
        field_ready = (len(ball.in_place - goalie_ids) >= len(ball.players) - len(goalie_ids) - 1
                       or now >= ball.restart_until + SET_PIECE_WAIT_MAX_S)
        if now < ball.restart_until or not (goalies_ready and field_ready):
            return
        kind, ball.set_piece, ball.restart_team = ball.set_piece, None, None
        ball.take(pedestrian, now)
        if kind == "penalty":
            ball.shoot(pedestrian, team, now, rules.penalty_scores)
        elif mates:  # the kick-off: a pass to a teammate
            ball.pass_to(pedestrian, min(mates, key=lambda m: math.hypot(m.x - ball.x, m.y - ball.y)), now)

    def _carry(self, pedestrian, ball: Ball, team: int, mates: List, now: float, dt: float) -> None:
        """With the ball: shoot or pass in the attacking zone; before it
        take it forward, pass it up, or now and then shoot from far."""
        rules = self.rules
        up = ball.attack_u(pedestrian, team)
        ahead = [m for m in mates if ball.attack_u(m, team) > up + 2.0]
        roll = random.random()
        if up > rules.zone_u:
            if roll < rules.zone_shot_rate * dt or up > rules.goal_u - 3.0:
                ball.shoot(pedestrian, team, now)
                return
            if mates and roll < (rules.zone_shot_rate + rules.zone_pass_rate) * dt:
                ball.pass_to(pedestrian, random.choice(mates), now)
                return
        else:
            if roll < rules.long_shot_rate * dt:
                ball.shoot(pedestrian, team, now)
                return
            if ahead and roll < (rules.long_shot_rate + rules.neutral_pass_rate) * dt:
                ball.pass_to(pedestrian, random.choice(ahead), now)
                return
        attack = -math.copysign(1.0, ball.defends_u(team))
        lane_limit = rules.width * 0.2
        lane = ball.uv(pedestrian.x, pedestrian.y)[1]
        glide(pedestrian, ball.world(attack * (rules.goal_u - 4.0), max(-lane_limit, min(lane_limit, lane))),
              dt, rules.carry_speed_mps)

    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None:
        ball: Optional[Ball] = instance.data.get("puck")
        pedestrian = context.pedestrian
        if ball is not None:
            ball.players.pop(id(pedestrian), None)
            ball.goalies = {t: g for t, g in ball.goalies.items() if g is not pedestrian}
            if ball.held_by is pedestrian:
                ball.held_by = None
        if "own_color" in instance.data:
            pedestrian.color = instance.data["own_color"]
        pedestrian.stick_swing = 0.0
        pedestrian.hockey_goalie = False
