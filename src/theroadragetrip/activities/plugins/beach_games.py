"""Two beach visitors toss a ball between each other."""
import math

from ..base import ActivityDefinition, ActivityGroup, ActivityLocation
from ..beach import BeachPlugin
from ..grouping import nearby_free_pedestrians, next_group_id, other_group_members, recruit


class BeachGamesPlugin(BeachPlugin):
    definition = ActivityDefinition(id="beach_games", name="Playing beach ball", min_duration_s=45,
                                    max_duration_s=120, cooldown_s=90, min_participants=2, max_participants=2)

    def start(self, context, instance):
        super().start(context, instance)
        if instance.group is not None:
            return
        others = nearby_free_pedestrians(context, 5, limit=1)
        if not others:
            instance.data["duration"] = 0
            return
        group = ActivityGroup(next_group_id(), "beach_games", [context.pedestrian.resident_id], context.sim_time)
        instance.group = group
        partner = others[0]
        recruit(context, "beach_games", group, partner, instance.location, (45, 120))
        partner.activity.location = ActivityLocation(partner.x, partner.y, extra=instance.location.extra)
        partner.state = "performing_activity"
        super().start(context.pedestrian_manager._activity_context(partner), partner.activity)
        group.data.update(elapsed=0.0, updated=None, ball=[context.pedestrian.x, context.pedestrian.y, 0.0])

    def update(self, context, instance, dt):
        if super().update(context, instance, dt) or instance.group is None:
            return True
        others = other_group_members(context, instance.group)
        if not others:
            return True
        p, other = context.pedestrian, others[0]
        p.heading = math.atan2(other.y-p.y, other.x-p.x)
        data = instance.group.data
        if data["updated"] != context.sim_time:
            data["updated"] = context.sim_time
            previous = data["elapsed"]
            data["elapsed"] += dt
            players = sorted([p, other], key=lambda player: player.resident_id)
            turn = int(data["elapsed"] / 2)
            a, b = players[turn % 2], players[(turn+1) % 2]
            t = min(1.0, data["elapsed"] % 2 / 1.2)
            data["ball"] = [a.x+(b.x-a.x)*t, a.y+(b.y-a.y)*t, 4*t*(1-t)]
            if previous == 0.0 or int(previous / 2) != turn:
                context.pedestrian_manager.play_sound("sport.beach_ball", (a.x, a.y))
        return False

    def finish(self, context, instance):
        if instance.group and context.pedestrian.resident_id in instance.group.member_resident_ids:
            instance.group.member_resident_ids.remove(context.pedestrian.resident_id)


PLUGIN = BeachGamesPlugin()
