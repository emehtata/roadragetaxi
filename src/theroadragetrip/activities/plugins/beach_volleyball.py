"""Two teams of two on mapped sand courts, under the shared beach weather gate."""
import math

from ..base import ActivityDefinition, ActivityGroup, ActivityInstance, ActivityLocation
from ..beach import BeachPlugin
from ..grouping import next_group_id, other_group_members
from .ice_skating import glide
from .tennis import point
from ...viewport import in_bounds

RALLY_S = 1.8
HITTERS = (0, 2, 1, 3)
POSITIONS = ((-.30, -.23), (-.30, .23), (.30, -.23), (.30, .23))


def is_beach_court(tags):
    sports = tags.get("sport", "").split(";")
    return (tags.get("leisure") == "pitch"
            and ("beachvolleyball" in sports or "volleyball" in sports and tags.get("surface") == "sand")
            and tags.get("layer", "0") == "0" and tags.get("level", "0") == "0"
            and tags.get("indoor", "no") == "no" and tags.get("covered") != "yes")


class BeachVolleyballPlugin(BeachPlugin):
    definition = ActivityDefinition(id="beach_volleyball", name="Playing beach volleyball",
                                    min_participants=4, max_participants=4, cooldown_s=90)

    def find_location(self, context):
        # Court groups are populated within the visible-sports budget, not on arbitrary beach spots.
        return None

    def start(self, context, instance):
        context.pedestrian.speed = 0
        context.pedestrian.animation_state = "idle"

    def update(self, context, instance, dt):
        group = instance.group
        if not self.can_start(context) or group is None:
            return True
        players = [p for p in [context.pedestrian, *other_group_members(context, group)]
                   if p.activity is not None and p.activity.group is group]
        data = group.data
        if len(players) != 4:
            return data["ready"] or context.sim_time - group.formed_sim_time > 20
        players.sort(key=lambda p: p.activity.data["slot"])
        data["ready"] = True
        if data["updated"] != context.sim_time:
            data["updated"] = context.sim_time
            data["elapsed"] += dt
            turn = int(data["elapsed"] / RALLY_S)
            if turn != data["turn"]:
                a, b = players[HITTERS[turn % 4]], players[HITTERS[(turn + 1) % 4]]
                data.update(turn=turn, start=(a.x, a.y), end=(b.x, b.y))
                context.pedestrian_manager.play_sound("sport.beach_ball", (a.x, a.y))
            t = (data["elapsed"] % RALLY_S) / RALLY_S
            a, b = data["start"], data["end"]
            # shortcut: continuous rallies without scores; add serves and points when match results are needed.
            data["ball"] = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                            1.5 + 3.0 * math.sin(math.pi * t)]
        p = context.pedestrian
        slot = instance.data["slot"]
        u, v = POSITIONS[slot]
        target = point(instance.location.extra.volleyball_frame, u, v + .12 * math.sin(data["elapsed"] + slot))
        glide(p, target, dt, 1.6)
        p.heading = math.atan2(data["ball"][1] - p.y, data["ball"][0] - p.x)
        p.animation_state = "volleyball"
        t = (data["elapsed"] % RALLY_S) / RALLY_S
        p.stick_swing = max(0.0, 1.0 - t * 5) if slot == HITTERS[data["turn"] % 4] else 0.0
        return data["elapsed"] >= 180

    def finish(self, context, instance):
        context.pedestrian.stick_swing = 0
        if instance.group and context.pedestrian.resident_id in instance.group.member_resident_ids:
            instance.group.member_resident_ids.remove(context.pedestrian.resident_id)

    def populate(self, manager, court, bounds, budget):
        if not manager.beach_open or budget <= 0 or not court.volleyball_frame:
            return 0
        people = [p for p in manager.pedestrians if p.activity and p.activity.plugin_id == self.definition.id
                  and p.activity.location.extra is court]
        if len(people) >= 4:
            return 0
        positions = [point(court.volleyball_frame, *uv) for uv in POSITIONS]
        if not all(in_bounds(bounds, *position) for position in positions):
            return 0
        group = people[0].activity.group if people else ActivityGroup(
            next_group_id(), self.definition.id, [], manager.sim_time,
            {"elapsed": 0.0, "updated": None, "turn": -1, "ready": False})
        # Join over multiple checks: four players must not exceed the two-spawn frame budget.
        occupied = {p.activity.data["slot"] for p in people}
        attempts = 0
        for slot, position in enumerate(positions):
            if slot in occupied:
                continue
            if attempts >= budget:
                break
            attempts += 1
            p = manager.spawn_pedestrian_at(*position)
            if p is None or not manager.add_pedestrian(p):
                continue
            group.member_resident_ids.append(p.resident_id)
            p.activity = ActivityInstance(self.definition.id, ActivityLocation(*position, extra=court),
                                          manager.sim_time, data={"slot": slot}, group=group)
            p.state = "performing_activity"
            self.start(manager._activity_context(p), p.activity)
        return attempts


PLUGIN = BeachVolleyballPlugin()
