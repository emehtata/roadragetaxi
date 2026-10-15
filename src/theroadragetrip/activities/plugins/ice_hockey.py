"""Play ice hockey on a frozen ice rink. Each player is an ordinary solo
activity; the game is the rink's Puck: it slides with ice friction and
bounces off the boards, two teams (red and blue jerseys) chase it - the
nearest player of each team goes for it, the rest hold a spot in the play -
and whoever reaches it hits it with the stick: a pass to a teammate or a
shot at the other goal. A goal puts the puck back on centre ice.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin
from .ice_skating import SKATING_SPEED_MPS, glide, open_ice
from .park_leisure import sample_interior_point

PUCK_FRICTION_MPS2 = 1.0
PUCK_BOUNCE = 0.6  # speed kept off the boards
HIT_REACH_M = 1.2
HIT_COOLDOWN_S = 0.6
PASS_SPEED_MPS = (7.0, 12.0)
SHOT_SPEED_MPS = (16.0, 26.0)
SHOT_CHANCE = 0.35
STICK_SWING_S = 0.3  # how long the client shows a stick swinging (state pedestrian stick_swing)
SPOT_MOVE_S = 5.0
TEAM_COLORS = ((200, 30, 40), (30, 70, 190))
IIHF_GOAL_U, IIHF_GOAL_HALF_WIDTH = 26.0, 0.915  # on a 60 x 30 m rink (chunk_detail.gd's markings)


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

    def goal(self, team: int) -> Tuple[float, float]:
        """The goal `team` shoots at: team 0 attacks +u, team 1 -u."""
        return self.world(IIHF_GOAL_U if team == 0 else -IIHF_GOAL_U, 0.0)

    def face_off(self, sim_time: float) -> None:
        self.x, self.y = self.world(0.0, 0.0)
        self.vx = self.vy = 0.0
        self.updated = sim_time

    def advance(self, sim_time: float) -> None:
        """Slide to `sim_time` (once per tick, whichever player asks first)."""
        from ...geo import point_in_polygon

        dt = min(0.5, sim_time - self.updated)
        self.updated = sim_time
        speed = math.hypot(self.vx, self.vy)
        if dt <= 0.0 or speed <= 0.0:
            return
        slowed = max(0.0, speed - PUCK_FRICTION_MPS2 * dt) / speed
        self.vx, self.vy = self.vx * slowed, self.vy * slowed
        x, y = self.x + self.vx * dt, self.y + self.vy * dt
        u, v = self.uv(x, y)
        if abs(u) >= IIHF_GOAL_U and abs(v) <= IIHF_GOAL_HALF_WIDTH and abs(self.uv(self.x, self.y)[0]) < IIHF_GOAL_U:
            scorer = 0 if u > 0.0 else 1
            self.goals = (self.goals[0] + (scorer == 0), self.goals[1] + (scorer == 1))
            self.face_off(sim_time)
            return
        if point_in_polygon(x, y, self.rink.points_m):
            self.x, self.y = x, y
        else:  # the boards: back the way it came, slower, a little off-line
            turn = random.uniform(-0.6, 0.6)
            vx, vy = -self.vx * PUCK_BOUNCE, -self.vy * PUCK_BOUNCE
            self.vx, self.vy = vx * math.cos(turn) - vy * math.sin(turn), vx * math.sin(turn) + vy * math.cos(turn)

    def hit(self, pedestrian, team: int, sim_time: float, teammates) -> None:
        """Shoot at the other goal, or pass to a teammate (or just ahead)."""
        if teammates and random.random() >= SHOT_CHANCE:
            mate = random.choice(teammates)
            target, speed = (mate.x, mate.y), random.uniform(*PASS_SPEED_MPS)
        else:
            gx, gy = self.goal(team)
            target, speed = (gx, gy + random.uniform(-1.5, 1.5)), random.uniform(*SHOT_SPEED_MPS)
        dx, dy = target[0] - self.x, target[1] - self.y
        distance = math.hypot(dx, dy) or 1.0
        self.vx, self.vy = dx / distance * speed, dy / distance * speed
        self.last_hit = sim_time
        pedestrian.heading = math.atan2(dy, dx)
        pedestrian.stick_swing = STICK_SWING_S


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
        pedestrian.stick_swing = max(0.0, getattr(pedestrian, "stick_swing", 0.0) - dt)
        puck.advance(context.sim_time)
        team = instance.data["team"]
        roster = [p for p in context.pedestrian_manager.pedestrians if id(p) in puck.players]
        if len(roster) < len(puck.players):  # despawned players never finish(): drop them
            puck.players = {id(p): puck.players[id(p)] for p in roster}
        mates = [p for p in roster if puck.players[id(p)] == team and p is not pedestrian]
        to_puck = math.hypot(puck.x - pedestrian.x, puck.y - pedestrian.y)
        chaser = all(to_puck <= math.hypot(puck.x - m.x, puck.y - m.y) for m in mates)
        if chaser:
            if to_puck <= HIT_REACH_M and context.sim_time - puck.last_hit >= HIT_COOLDOWN_S:
                puck.hit(pedestrian, team, context.sim_time, mates)
            else:
                glide(pedestrian, (puck.x, puck.y), dt, SKATING_SPEED_MPS * 1.4)
        else:  # hold a spot in the play: between a place on the ice and the puck
            instance.data["spot_elapsed_s"] += dt
            if instance.data["spot"] is None or instance.data["spot_elapsed_s"] >= SPOT_MOVE_S:
                instance.data["spot_elapsed_s"] = 0.0
                instance.data["spot"] = sample_interior_point(puck.rink)
            spot = instance.data["spot"] or (puck.x, puck.y)
            target = ((spot[0] + puck.x) / 2.0, (spot[1] + puck.y) / 2.0)
            if glide(pedestrian, target, dt, SKATING_SPEED_MPS):
                pedestrian.heading = math.atan2(puck.y - pedestrian.y, puck.x - pedestrian.x)
        return instance.data["elapsed_s"] >= instance.data["duration_s"]

    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None:
        puck: Optional[Puck] = instance.data.get("puck")
        if puck is not None:
            puck.players.pop(id(context.pedestrian), None)
        if "own_color" in instance.data:
            context.pedestrian.color = instance.data["own_color"]
        context.pedestrian.stick_swing = 0.0


PLUGIN = IceHockeyPlugin()
