"""Two nearby Residents stop and talk for a while (residents-live.md section 7).

See activities/grouping.py's module docstring for how recruitment works:
the plugin only *identifies* a candidate partner in find_location() (a
pure read - the candidate might not be chosen), and only actually claims
them in start() (which fires exclusively for the instance that won
selection). Once claimed, the partner is driven by the exact same core
dispatch as any self-selected activity - nothing group-specific in
pedestrian.py at all.
"""
from __future__ import annotations

import math
import random

from ..base import ActivityContext, ActivityDefinition, ActivityGroup, ActivityInstance, ActivityLocation, ActivityPlugin
from ..grouping import nearby_free_pedestrians, next_group_id, other_group_members, recruit

SEARCH_RADIUS_M = 15.0


class TwoPersonConversationPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="two_person_conversation",
        name="Chatting",
        min_duration_s=20.0,
        max_duration_s=60.0,
        cooldown_s=90.0,
        base_weight=0.7,
        min_participants=2,
        max_participants=2,
    )

    def find_location(self, context: ActivityContext):
        # "1. notice each other" - only proposable when a free partner is
        # already nearby right now, not "wait around hoping someone comes".
        candidates = nearby_free_pedestrians(context, SEARCH_RADIUS_M, limit=1)
        if not candidates:
            return None
        partner = candidates[0]
        pedestrian = context.pedestrian
        midpoint = ((pedestrian.x + partner.x) / 2.0, (pedestrian.y + partner.y) / 2.0)
        return ActivityLocation(x=midpoint[0], y=midpoint[1], reservation_key=None, extra=partner)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        if instance.group is None:
            # Arriving first - this is the initiator. The candidate
            # partner noted back in find_location may have wandered off,
            # been claimed by someone else, or started something else in
            # the meantime - re-check before committing to anything.
            partner = instance.location.extra if instance.location is not None else None
            if partner is None or partner.activity is not None or partner.linked_vehicle_id is not None:
                instance.data["duration_s"] = 0.0
                instance.data["elapsed_s"] = 0.0
                return
            group = ActivityGroup(
                group_id=next_group_id(),
                plugin_id=self.definition.id,
                member_resident_ids=[context.pedestrian.resident_id],
                formed_sim_time=context.sim_time,
            )
            instance.group = group
            instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
            instance.data["elapsed_s"] = 0.0
            recruit(
                context, self.definition.id, group, partner, instance.location,
                (self.definition.min_duration_s, self.definition.max_duration_s),
            )

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        if instance.group is None:
            return True  # recruitment failed at start() - nothing to do
        instance.data["elapsed_s"] += dt
        other = next(iter(other_group_members(context, instance.group)), None)
        if other is not None and other.state == "performing_activity":
            # Face each other only once the partner has actually arrived -
            # otherwise this would aim at a still-moving target.
            context.pedestrian.heading = math.atan2(other.y - context.pedestrian.y, other.x - context.pedestrian.x)
        return instance.data["elapsed_s"] >= instance.data["duration_s"]

    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None:
        # "7. leave independently" - just remove this one participant;
        # the other's own countdown is unaffected.
        if instance.group is not None and context.pedestrian.resident_id in instance.group.member_resident_ids:
            instance.group.member_resident_ids.remove(context.pedestrian.resident_id)


PLUGIN = TwoPersonConversationPlugin()
