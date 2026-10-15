"""Soccer on a pitch in summer (activities/team_game.py: the game) - while
there is no snow on the field and it is light. A white ball on grass: it
rolls shorter than a puck and goes out over the touchline (the other team
puts it back in); the attacking zone is the final third. Up to 10 field
players a side and a goalie in their own colours.
"""
from __future__ import annotations

from ..team_game import Rules, TeamGamePlugin

# On a 105 x 68 m FIFA pitch (chunk_detail.gd's markings): team 0 attacks +u.
GOAL_U, GOAL_HALF_WIDTH = 52.5, 3.66
FINAL_THIRD_U = 17.5
TEAM_COLORS = ((200, 30, 40), (30, 70, 190))
GOALIE_COLORS = ((230, 200, 40), (40, 160, 70))
FIELD_PLAYERS_MAX = 10  # a side, besides the goalie


def is_soccer_pitch(scenery) -> bool:
    return scenery.kind == "pitch" and "soccer" in (getattr(scenery, "sport", None) or "")


RULES = Rules(
    plugin_id="soccer", name="Soccer", open_flag="soccer_open", is_field=is_soccer_pitch,
    length=105.0, width=68.0, goal_u=GOAL_U, goal_half_width=GOAL_HALF_WIDTH,
    goalie_out_u=1.5, goalie_half_range_v=3.0, zone_u=FINAL_THIRD_U, boards=False,
    friction_mps2=1.6, bounce=0.0, reach_m=1.0, cooldown_s=0.6,
    pass_speed_mps=(8.0, 14.0), shot_speed_mps=(18.0, 28.0), shot_aim_v=3.0,
    run_speed_mps=3.2, chase_factor=1.5, carry_speed_mps=2.8,
    ball_ahead_m=0.5, ball_side_m=0.0,  # at the feet
    zone_shot_rate=0.5, zone_pass_rate=0.5, neutral_pass_rate=0.4, long_shot_rate=0.012,
    steal_chance=0.35, shot_scores=0.15, goalie_hold_s=1.2, restart_s=4.0, spot_move_s=6.0,
    support_ahead_u=15.0, team_colors=TEAM_COLORS, goalie_colors=GOALIE_COLORS,
    max_players=2 * (FIELD_PLAYERS_MAX + 1),
    kickoff=True, centre_circle_m=9.15, set_piece_s=6.0,
    fouls=True, knockdown_chance=0.002, penalty_area_u=16.5, penalty_area_half_v=20.16, penalty_spot_u=11.0, penalty_scores=0.75,
)

PLUGIN = TeamGamePlugin(RULES, base_weight=1.5)
ball_positions = PLUGIN.ball_positions  # state "balls"
