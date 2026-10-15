"""Pond hockey on a frozen ice rink. Each player is an ordinary solo
activity; the game is the rink's Puck: it slides with ice friction and
bounces off the boards. Two teams (red and blue jerseys), each with a
goalie - the team's first player - who stays in the crease, slides across
with the puck, catches what comes at the goal and passes it up ice. Of
the skaters the nearest of each team chases the puck, the rest hold spots
in the play; whoever reaches it hits it - a pass, or a shot at the other
goal. A shot's fate is decided when it is hit: SHOT_SCORES of them go in,
the goalie saves the rest (and any loose puck reaching the goal). After a
goal there is no face-off, as on a pond: the conceding goalie takes the
puck out of the net while the scorers back off, and passes it to offence.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin
from .ice_skating import SKATING_SPEED_MPS, collide, glide, is_down, open_ice, others_on
from .park_leisure import sample_interior_point

PUCK_FRICTION_MPS2 = 1.0
PUCK_BOUNCE = 0.6  # speed kept off the boards
HIT_REACH_M = 1.2
HIT_COOLDOWN_S = 0.6
PASS_SPEED_MPS = (7.0, 12.0)
SHOT_SPEED_MPS = (16.0, 26.0)
SHOT_CHANCE = 0.35  # of a skater's hits; the rest are passes
SHOT_SCORES = 0.20  # of shots: past the goalie
GOALIE_HOLD_S = 0.8  # a caught puck, before the goalie passes it out
RESTART_S = 3.0  # after a goal: only the conceding team may touch the puck
STICK_SWING_S = 0.3  # how long the client shows a stick swinging (state pedestrian stick_swing)
SPOT_MOVE_S = 5.0
TEAM_COLORS = ((200, 30, 40), (30, 70, 190))
# On a 60 x 30 m IIHF rink (chunk_detail.gd's markings): team 0 attacks +u.
GOAL_U, GOAL_HALF_WIDTH = 26.0, 0.915
GOALIE_OUT_U = 1.0  # in front of the goal line
GOALIE_HALF_RANGE_V = 1.1


@dataclass
class Puck:
    rink: object
    frame: list  # map_chunks.rink_frame: [cx, cy, angle, length, width]
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    updated: float = 0.0
    last_hit: float = -1e9
    players: Dict[int, int] = field(default_factory=dict)  # id(pedestrian) -> team 0/1
    goalies: Dict[int, object] = field(default_factory=dict)  # team -> its goalie pedestrian
    shot_scores: bool = False  # the puck in flight is a shot that goes in
    restart_team: Optional[int] = None  # after a goal, until restart_until: only this team plays it
    restart_until: float = -1e9
    held_by: object = None  # a goalie holding a caught puck
    held_since: float = 0.0
    goals: Tuple[int, int] = (0, 0)

    def uv(self, x: float, y: float) -> Tuple[float, float]:
        """(x, y) in IIHF rink metres: u along the rink (goals at +-26), v across."""
        cx, cy, angle, length, width = self.frame
        dx, dy = x - cx, y - cy
        return ((dx * math.cos(angle) + dy * math.sin(angle)) * 60.0 / length,
                (-dx * math.sin(angle) + dy * math.cos(angle)) * 30.0 / width)

    def world(self, u: float, v: float) -> Tuple[float, float]:
        cx, cy, angle, length, width = self.frame
        u, v = u * length / 60.0, v * width / 30.0
        return cx + u * math.cos(angle) - v * math.sin(angle), cy + u * math.sin(angle) + v * math.cos(angle)

    @staticmethod
    def defends_u(team: int) -> float:
        """The u of the goal `team` defends (team 0 attacks +u)."""
        return -GOAL_U if team == 0 else GOAL_U

    def goalie_spot(self, team: int) -> Tuple[float, float]:
        goal_u = self.defends_u(team)
        v = max(-GOALIE_HALF_RANGE_V, min(GOALIE_HALF_RANGE_V, self.uv(self.x, self.y)[1]))
        return self.world(goal_u - math.copysign(GOALIE_OUT_U, goal_u), v)

    def stop_at(self, x: float, y: float) -> None:
        self.x, self.y, self.vx, self.vy = x, y, 0.0, 0.0
        self.shot_scores = False

    def advance(self, sim_time: float) -> None:
        """Slide to `sim_time` (once per tick, whichever player asks first)."""
        from ...geo import point_in_polygon

        dt = min(0.5, sim_time - self.updated)
        self.updated = sim_time
        if self.held_by is not None:
            self.x, self.y = self.held_by.x, self.held_by.y
            return
        speed = math.hypot(self.vx, self.vy)
        if dt <= 0.0 or speed <= 0.0:
            return
        slowed = max(0.0, speed - PUCK_FRICTION_MPS2 * dt) / speed
        self.vx, self.vy = self.vx * slowed, self.vy * slowed
        x, y = self.x + self.vx * dt, self.y + self.vy * dt
        u, v = self.uv(x, y)
        if abs(u) >= GOAL_U - GOALIE_OUT_U and abs(v) <= GOALIE_HALF_RANGE_V and abs(self.uv(self.x, self.y)[0]) < GOAL_U - GOALIE_OUT_U:
            defending = 0 if u < 0.0 else 1
            goalie = self.goalies.get(defending)
            if self.shot_scores or goalie is None:
                self._goal(defending, sim_time)
            else:  # the save: the goalie catches it
                self.stop_at(goalie.x, goalie.y)
                self.held_by, self.held_since = goalie, sim_time
            return
        if point_in_polygon(x, y, self.rink.points_m):
            self.x, self.y = x, y
        else:  # the boards: back the way it came, slower, a little off-line
            turn = random.uniform(-0.6, 0.6)
            vx, vy = -self.vx * PUCK_BOUNCE, -self.vy * PUCK_BOUNCE
            self.vx, self.vy = vx * math.cos(turn) - vy * math.sin(turn), vx * math.sin(turn) + vy * math.cos(turn)
            self.shot_scores = False

    def _goal(self, conceding: int, sim_time: float) -> None:
        """In the net: the conceding team restarts from its goal mouth, no face-off."""
        scorer = 1 - conceding
        self.goals = (self.goals[0] + (scorer == 0), self.goals[1] + (scorer == 1))
        goal_u = self.defends_u(conceding)
        self.stop_at(*self.world(goal_u - math.copysign(0.3, goal_u), 0.0))
        self.restart_team, self.restart_until = conceding, sim_time + RESTART_S

    def hit_toward(self, pedestrian, target: Tuple[float, float], speed: float, sim_time: float) -> None:
        dx, dy = target[0] - self.x, target[1] - self.y
        distance = math.hypot(dx, dy) or 1.0
        self.vx, self.vy = dx / distance * speed, dy / distance * speed
        self.last_hit = sim_time
        self.held_by = None
        self.shot_scores = False
        pedestrian.heading = math.atan2(dy, dx)
        pedestrian.stick_swing = STICK_SWING_S

    def skater_hit(self, pedestrian, team: int, sim_time: float, mates: List) -> None:
        """A shot at the other goal (decided now: in, or saved), or a pass."""
        if mates and random.random() >= SHOT_CHANCE:
            mate = random.choice(mates)
            self.hit_toward(pedestrian, (mate.x, mate.y), random.uniform(*PASS_SPEED_MPS), sim_time)
            return
        scores = random.random() < SHOT_SCORES
        self.hit_toward(pedestrian, self.world(-self.defends_u(team), random.uniform(-0.6, 0.6)),
                        random.uniform(*SHOT_SPEED_MPS), sim_time)
        self.shot_scores = scores

    def goalie_pass(self, goalie, team: int, sim_time: float, mates: List) -> None:
        """Out of the crease to offence: to the teammate furthest up ice."""
        attack = -math.copysign(1.0, self.defends_u(team))
        if mates:
            mate = max(mates, key=lambda m: self.uv(m.x, m.y)[0] * attack)
            target = (mate.x, mate.y)
        else:
            target = self.world(0.0, random.uniform(-8.0, 8.0))
        self.hit_toward(goalie, target, random.uniform(*PASS_SPEED_MPS), sim_time)


# id(rink) -> its Puck. A rink no one plays on keeps its (still) puck.
_pucks: Dict[int, Puck] = {}


def puck_for(rink, sim_time: float) -> Optional[Puck]:
    puck = _pucks.get(id(rink))
    if puck is None or puck.rink is not rink:
        from ...map_chunks import rink_frame

        frame = rink_frame(rink.points_m)
        if frame is None:
            return None
        puck = _pucks[id(rink)] = Puck(rink=rink, frame=frame, x=frame[0], y=frame[1], updated=sim_time)
    return puck


def puck_positions() -> list:
    """Every puck in play (state "pucks"): [[x, y], ...]."""
    return [[round(p.x, 2), round(p.y, 2)] for p in _pucks.values() if p.players]


class IceHockeyPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="ice_hockey",
        name="Ice hockey",
        min_duration_s=90.0,
        max_duration_s=300.0,
        cooldown_s=300.0,
        base_weight=2.0,
    )

    def find_location(self, context: ActivityContext):
        rinks = open_ice(context, kinds=("ice_rink",))
        if not rinks:
            return None
        rink = random.choice(rinks)
        point = sample_interior_point(rink)
        return ActivityLocation(x=point[0], y=point[1], extra=rink) if point else None

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        pedestrian = context.pedestrian
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0
        rink = instance.location.extra if instance.location is not None else None
        puck = puck_for(rink, context.sim_time) if rink is not None else None
        instance.data["puck"] = puck
        if puck is None:
            return
        teams = list(puck.players.values())
        team = 0 if teams.count(0) <= teams.count(1) else 1
        puck.players[id(pedestrian)] = team
        instance.data["team"] = team
        instance.data["own_color"] = pedestrian.color
        pedestrian.color = TEAM_COLORS[team]
        instance.data["spot"] = None
        instance.data["spot_elapsed_s"] = SPOT_MOVE_S

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        puck: Optional[Puck] = instance.data.get("puck")
        if puck is None or not getattr(context.pedestrian_manager, "sports_ice_open", False):
            return True
        pedestrian = context.pedestrian
        pedestrian.stick_swing = max(0.0, pedestrian.stick_swing - dt)
        team = instance.data["team"]
        roster = [p for p in context.pedestrian_manager.pedestrians if id(p) in puck.players]
        if len(roster) < len(puck.players):  # despawned players never finish(): drop them
            puck.players = {id(p): puck.players[id(p)] for p in roster}
            puck.goalies = {t: g for t, g in puck.goalies.items() if id(g) in puck.players}
            if puck.held_by is not None and id(puck.held_by) not in puck.players:
                puck.held_by = None
        if team not in puck.goalies:  # every team has a goalie: the first to notice it has none
            puck.goalies[team] = pedestrian
        pedestrian.hockey_goalie = puck.goalies[team] is pedestrian
        puck.advance(context.sim_time)
        if is_down(pedestrian, instance, dt):  # knocked over: on the ice a moment, the play goes on
            return False
        mates = [p for p in roster if puck.players[id(p)] == team and p is not pedestrian]
        skating_mates = [p for p in mates if p is not puck.goalies.get(team)]
        if pedestrian.hockey_goalie:
            self._goalie(context, puck, team, skating_mates, dt)
        else:
            self._skater(context, instance, puck, team, skating_mates, dt)
        collide(pedestrian, others_on(puck.rink, pedestrian, roster))
        return instance.data["elapsed_s"] >= instance.data["duration_s"]

    @staticmethod
    def _goalie(context: ActivityContext, puck: Puck, team: int, mates: List, dt: float) -> None:
        goalie = context.pedestrian
        now = context.sim_time
        restart = puck.restart_team == team and now < puck.restart_until
        near = math.hypot(puck.x - goalie.x, puck.y - goalie.y) <= HIT_REACH_M
        if puck.held_by is goalie and now - puck.held_since >= GOALIE_HOLD_S:
            puck.goalie_pass(goalie, team, now, mates)
        elif restart and puck.held_by is None:  # out of the net with it
            if near:
                puck.held_by, puck.held_since = goalie, now
            else:
                glide(goalie, (puck.x, puck.y), dt, SKATING_SPEED_MPS)
        elif puck.held_by is None and near and math.hypot(puck.vx, puck.vy) < 2.0 and now - puck.last_hit >= HIT_COOLDOWN_S:
            puck.goalie_pass(goalie, team, now, mates)  # a loose puck in the crease: clear it
        elif puck.held_by is not goalie:
            if glide(goalie, puck.goalie_spot(team), dt, SKATING_SPEED_MPS):
                goalie.heading = math.atan2(puck.y - goalie.y, puck.x - goalie.x)

    @staticmethod
    def _skater(context: ActivityContext, instance: ActivityInstance, puck: Puck, team: int, mates: List, dt: float) -> None:
        pedestrian = context.pedestrian
        now = context.sim_time
        waiting = puck.restart_team is not None and puck.restart_team != team and now < puck.restart_until
        to_puck = math.hypot(puck.x - pedestrian.x, puck.y - pedestrian.y)
        chaser = (puck.held_by is None and not waiting
                  and all(to_puck <= math.hypot(puck.x - m.x, puck.y - m.y) for m in mates))
        if chaser:
            if to_puck <= HIT_REACH_M and now - puck.last_hit >= HIT_COOLDOWN_S:
                puck.skater_hit(pedestrian, team, now, mates)
            else:
                glide(pedestrian, (puck.x, puck.y), dt, SKATING_SPEED_MPS * 1.4)
            return
        # Hold a spot in the play: between a place on the ice and the puck
        # (back toward centre ice while the other team restarts).
        instance.data["spot_elapsed_s"] += dt
        if instance.data["spot"] is None or instance.data["spot_elapsed_s"] >= SPOT_MOVE_S:
            instance.data["spot_elapsed_s"] = 0.0
            instance.data["spot"] = sample_interior_point(puck.rink)
        spot = instance.data["spot"] or (puck.x, puck.y)
        focus = puck.world(0.0, 0.0) if waiting else (puck.x, puck.y)
        if glide(pedestrian, ((spot[0] + focus[0]) / 2.0, (spot[1] + focus[1]) / 2.0), dt, SKATING_SPEED_MPS):
            pedestrian.heading = math.atan2(puck.y - pedestrian.y, puck.x - pedestrian.x)

    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None:
        puck: Optional[Puck] = instance.data.get("puck")
        pedestrian = context.pedestrian
        if puck is not None:
            puck.players.pop(id(pedestrian), None)
            puck.goalies = {t: g for t, g in puck.goalies.items() if g is not pedestrian}
            if puck.held_by is pedestrian:
                puck.held_by = None
        if "own_color" in instance.data:
            pedestrian.color = instance.data["own_color"]
        pedestrian.stick_swing = 0.0
        pedestrian.hockey_goalie = False


PLUGIN = IceHockeyPlugin()
