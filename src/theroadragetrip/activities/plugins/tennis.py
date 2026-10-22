"""A bounded two-player tennis match on a mapped outdoor court: serves, rallies
that end in the net, out or as a winner, and the points scored."""
import math

from shapely.geometry import Polygon

from ..base import ActivityDefinition, ActivityGroup, ActivityInstance, ActivityLocation, ActivityPlugin
from ..grouping import next_group_id, other_group_members
from .ice_skating import glide
from ...viewport import in_bounds


def prepare_court(court):
    court.tennis_frame = court_frame(court.points_m)


def court_frame(points):
    from ...map_chunks import rink_frame
    frame = rink_frame(points)
    if frame is None:
        return []
    x, y, angle, length, width = frame
    # Keep the marked court and players inside irregular OSM outlines too.
    def at(u, v):
        return (x + math.cos(angle)*u - math.sin(angle)*v, y + math.sin(angle)*u + math.cos(angle)*v)
    rectangle = Polygon([at(u*length, v*width) for u, v in [(-.48,-.48),(.48,-.48),(.48,.48),(-.48,.48)]])
    return frame if Polygon(points).buffer(.05).covers(rectangle) else []


def _frame_uv(frame, px, py):
    x, y, angle, length, width = frame
    dx, dy = px - x, py - y
    return ((math.cos(angle)*dx + math.sin(angle)*dy) / length, (-math.sin(angle)*dx + math.cos(angle)*dy) / width)


def point(frame, u, v):
    x, y, angle, length, width = frame
    return x + math.cos(angle)*u*length - math.sin(angle)*v*width, y + math.sin(angle)*u*length + math.cos(angle)*v*width


SHOT_S = 1.6
OUTCOMES = ("net", "out", "winner")


def _roll(point_index, salt):
    return (math.sin(point_index * 12.9898 + salt * 78.233) * 43758.5453) % 1.0


def point_plan(point_index):
    """(shots, outcome) of a point: the last shot goes into the net, lands
    out, or is a winner. One shot is a served ace or fault."""
    return 1 + int(_roll(point_index, 1) * 8), OUTCOMES[int(_roll(point_index, 2) * 3)]


def hitter(server, shot):
    return server if shot % 2 == 0 else 1 - server


def point_winner(server, shots, outcome):
    last = hitter(server, shots - 1)
    return last if outcome == "winner" else 1 - last


def add_point(score, games, won):
    """Tennis scoring: 0, 15, 30, 40, then the game - by two points from deuce."""
    score[won] += 1
    if score[won] >= 4 and score[won] - score[1 - won] >= 2:
        games[won] += 1
        score[0] = score[1] = 0


def rally_spot(side, turn):
    """Where a player takes the `turn`th shot, in court-frame units: inside the
    singles court (baselines at u=+-.42, sidelines at v=+-.3, as
    chunk_detail.gd draws them), from the baseline up to mid-court."""
    depth = .36 + .05 * math.sin(turn * 1.3 + side * 2.1)
    return -depth if side == 0 else depth, .24 * math.sin(turn * .8 + side)


def landing(outcome, receiver, v_from, roll):
    """Where the point's last shot ends (court-frame u, v): at the net, past a
    line, or deep in the receiver's court away from where they were."""
    u_sign = -1 if receiver == 0 else 1
    if outcome == "net":
        return 0.0, v_from * .5
    if outcome == "out":
        return (u_sign * .48, v_from) if roll < .5 else (u_sign * .3, (.36 if v_from <= 0 else -.36))
    return u_sign * .34, (.26 if v_from <= 0 else -.26)


class TennisPlugin(ActivityPlugin):
    definition = ActivityDefinition(id="tennis", name="Playing tennis", min_participants=2, max_participants=2)

    def can_start(self, context):
        return context.pedestrian_manager.tennis_open

    def start(self, context, instance):
        context.pedestrian.speed = 0
        context.pedestrian.animation_state = "tennis"

    def update(self, context, instance, dt):
        group = instance.group
        if not self.can_start(context) or group is None or not other_group_members(context, group):
            return True
        data = group.data
        previous = data["elapsed"]
        advanced = data["updated"] != context.sim_time
        if advanced:
            data["updated"] = context.sim_time
            data["elapsed"] += dt
        elapsed = data["elapsed"]
        shots, outcome = point_plan(data["point"])
        server = sum(data["games"]) % 2
        if advanced and elapsed - data["point_start"] >= (shots + 1) * SHOT_S:  # the point is over after a pause
            add_point(data["score"], data["games"], point_winner(server, shots, outcome))
            data["point"] += 1
            data["point_start"] = elapsed
            shots, outcome = point_plan(data["point"])
            server = sum(data["games"]) % 2
        local = elapsed - data["point_start"]
        shot, t = int(local / SHOT_S), (local % SHOT_S) / SHOT_S
        local_previous = previous - data["point_start"]
        side = instance.data["side"]
        frame = instance.location.extra.tennis_frame
        deuce_court = 1 if (sum(data["score"]) % 2 == 0) else -1
        if shot == 0 or shot >= shots:  # serve, or back to the line for the next one
            u = .44 if side == server else .40
            spot = (-u if side == 0 else u, (.12 if side == server else -.18) * deuce_court * (1 if side == 0 else -1))
        else:
            spot = rally_spot(side, data["point"] * 10 + shot)
        p = context.pedestrian
        p.speed = 0
        glide(p, point(frame, *spot), dt, 4.0)  # a court-wide run takes one shot's flight
        other = other_group_members(context, group)[0]
        p.heading = math.atan2(other.y-p.y, other.x-p.x)
        p.animation_state = "tennis"
        p.stick_swing = max(0, 1-t*6) if shot < shots and side == hitter(server, shot) else 0.0
        players = sorted([p, other], key=lambda player: player.activity.data["side"])
        if shot >= shots:  # the ball lies where the point ended
            data["ball"][2] = 0.0
        else:
            a, b = players[hitter(server, shot)], players[1 - hitter(server, shot)]
            if shot == shots - 1:
                hx, hy = _frame_uv(frame, a.x, a.y)
                end = point(frame, *landing(outcome, 1 - hitter(server, shot), hy, _roll(data["point"], 3)))
                height = max(0.0, 1 + 2.5*t - 3.5*t*t)
            else:
                end = (b.x, b.y)
                height = max(0, 1 + 2.5*t - (46/9)*t*t) if t <= .75 else 3.2*(t-.75)
            data["ball"] = [a.x+(end[0]-a.x)*t, a.y+(end[1]-a.y)*t, height]
            if advanced and (previous == 0.0 or local_previous // SHOT_S != shot):
                context.pedestrian_manager.play_sound("sport.tennis_hit", (a.x, a.y))
            if advanced and shot < shots - 1 and int((local_previous + .4) / SHOT_S) != int((local + .4) / SHOT_S):
                context.pedestrian_manager.play_sound("sport.tennis_bounce", (data["ball"][0], data["ball"][1]))
        return elapsed >= 180

    def finish(self, context, instance):
        context.pedestrian.stick_swing = 0
        if instance.group and context.pedestrian.resident_id in instance.group.member_resident_ids:
            instance.group.member_resident_ids.remove(context.pedestrian.resident_id)

    def populate(self, manager, court, bounds, budget):
        if not manager.tennis_open or budget < 2 or not court.tennis_frame:
            return 0
        if any(p.activity and p.activity.plugin_id == "tennis" and p.activity.location.extra is court for p in manager.pedestrians):
            return 0
        positions = [point(court.tennis_frame, *rally_spot(side, 0)) for side in (0, 1)]
        if not all(in_bounds(bounds, *position) for position in positions):
            return 0
        players = []
        for position in positions:
            p = manager.spawn_pedestrian_at(*position)
            if p is not None and manager.add_pedestrian(p):
                players.append(p)
        if len(players) != 2:
            for p in players:
                manager.pedestrians.remove(p)
            return 2
        group = ActivityGroup(next_group_id(), "tennis", [p.resident_id for p in players], manager.sim_time,
                              {"elapsed": 0., "updated": None, "ball": [*positions[0], 1.], "point": 0, "point_start": 0., "score": [0, 0], "games": [0, 0]})
        for side, p in enumerate(players):
            p.activity = ActivityInstance("tennis", ActivityLocation(p.x, p.y, extra=court), manager.sim_time,
                                          data={"side": side}, group=group)
            p.state = "performing_activity"
            self.start(manager._activity_context(p), p.activity)
        return 2


PLUGIN = TennisPlugin()
