"""Pond hockey on a frozen ice rink (activities/team_game.py: the game).
A puck on ice with sticks: it slides far and bounces off the boards, red
and blue jerseys, the goalie in the crease. The offensive zone starts at
the other team's blue line.
"""
from __future__ import annotations

from ..team_game import STICK_SWING_S, Ball, Rules, TeamGamePlugin
from .ice_skating import SKATING_SPEED_MPS

Puck = Ball
TEAM_COLORS = ((200, 30, 40), (30, 70, 190))
# On a 60 x 30 m IIHF rink (chunk_detail.gd's markings): team 0 attacks +u.
GOAL_U, GOAL_HALF_WIDTH = 26.0, 0.915
BLUE_LINE_U = 8.75

RULES = Rules(
    plugin_id="ice_hockey", name="Ice hockey", open_flag="sports_ice_open",
    is_field=lambda scenery: scenery.kind == "ice_rink",
    length=60.0, width=30.0, goal_u=GOAL_U, goal_half_width=GOAL_HALF_WIDTH,
    goalie_out_u=1.0, goalie_half_range_v=1.1, zone_u=BLUE_LINE_U, boards=True,
    friction_mps2=1.0, bounce=0.6, reach_m=1.2, cooldown_s=0.6,
    pass_speed_mps=(6.0, 10.0), shot_speed_mps=(16.0, 26.0), shot_aim_v=0.6,
    run_speed_mps=SKATING_SPEED_MPS, chase_factor=1.4, carry_speed_mps=3.0,
    # On the stick's blade (entity_layer.gd _hockey_stick draws it there).
    ball_ahead_m=1.0, ball_side_m=0.2,
    zone_shot_rate=0.9, zone_pass_rate=0.35, neutral_pass_rate=0.3, long_shot_rate=0.03,
    steal_chance=0.4, shot_scores=0.20, goalie_hold_s=0.8, restart_s=3.0, spot_move_s=5.0,
    support_ahead_u=10.0, team_colors=TEAM_COLORS, max_players=10,
)

PLUGIN = TeamGamePlugin(RULES)
_pucks = PLUGIN.balls  # id(rink) -> its Puck
puck_positions = PLUGIN.ball_positions  # state "pucks"
__all__ = ["PLUGIN", "Puck", "RULES", "STICK_SWING_S", "TEAM_COLORS", "puck_positions"]
