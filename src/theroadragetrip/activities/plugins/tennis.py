"""A bounded two-player rally on a mapped outdoor tennis court."""
import math

from shapely.geometry import Polygon

from ..base import ActivityDefinition, ActivityGroup, ActivityInstance, ActivityLocation, ActivityPlugin
from ..grouping import next_group_id, other_group_members
from .ice_skating import glide
from ...viewport import in_bounds


def prepare_court(court):
    from ...map_chunks import rink_frame
    frame = rink_frame(court.points_m)
    if frame is None:
        return
    x, y, angle, length, width = frame
    # Keep the marked court and players inside irregular OSM outlines too.
    def at(u, v):
        return (x + math.cos(angle)*u - math.sin(angle)*v, y + math.sin(angle)*u + math.cos(angle)*v)
    rectangle = Polygon([at(u*length, v*width) for u, v in [(-.48,-.48),(.48,-.48),(.48,.48),(-.48,.48)]])
    if Polygon(court.points_m).buffer(.05).covers(rectangle):
        court.tennis_frame = frame


def point(frame, u, v):
    x, y, angle, length, width = frame
    return x + math.cos(angle)*u*length - math.sin(angle)*v*width, y + math.sin(angle)*u*length + math.cos(angle)*v*width


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
        if data["updated"] != context.sim_time:
            data["updated"] = context.sim_time
            data["elapsed"] += dt
        elapsed = data["elapsed"]
        turn, t = int(elapsed / 1.6), (elapsed % 1.6) / 1.6
        side = instance.data["side"]
        frame = instance.location.extra.tennis_frame
        target = point(frame, -.46 if side == 0 else .46, .20 * math.sin(turn*.8 + side))
        p = context.pedestrian
        p.speed = 0
        glide(p, target, dt, 2.0)
        other = other_group_members(context, group)[0]
        p.heading = math.atan2(other.y-p.y, other.x-p.x)
        p.animation_state = "tennis"
        p.stick_swing = max(0, 1-t*6) if side == turn % 2 else 0.0
        # shortcut: continuous rallies without scoring; add serves and points when match results are needed.
        players = sorted([p, other], key=lambda player: player.activity.data["side"])
        a, b = players[turn % 2], players[(turn+1) % 2]
        height = max(0, 1 + 2.5*t - (46/9)*t*t) if t <= .75 else 3.2*(t-.75)
        data["ball"] = [a.x+(b.x-a.x)*t, a.y+(b.y-a.y)*t, height]
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
        positions = [point(court.tennis_frame, u, 0) for u in [-.46, .46]]
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
                              {"elapsed": 0., "updated": None, "ball": [*positions[0], 1.]})
        for side, p in enumerate(players):
            p.activity = ActivityInstance("tennis", ActivityLocation(p.x, p.y, extra=court), manager.sim_time,
                                          data={"side": side}, group=group)
            p.state = "performing_activity"
            self.start(manager._activity_context(p), p.activity)
        return 2


PLUGIN = TennisPlugin()
