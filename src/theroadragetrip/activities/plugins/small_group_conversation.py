"""A small group (3-5) of nearby Residents gathers to talk
(residents-live.md section 7) - the same recruit-at-start() mechanism as
two_person_conversation, just recruiting several partners at once instead
of exactly one, and facing the group's centroid instead of a single
partner.
"""
from __future__ import annotations

import math
import random

from ..base import ActivityContext, ActivityDefinition, ActivityGroup, ActivityInstance, ActivityLocation, ActivityPlugin
from ..grouping import nearby_free_pedestrians, next_group_id, other_group_members, recruit

SEARCH_RADIUS_M = 20.0


class SmallGroupConversationPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="small_group_conversation",
        name="Group chat",
        min_duration_s=25.0,
        max_duration_s=75.0,
        cooldown_s=120.0,
        base_weight=0.4,
        min_participants=3,
        max_participants=5,
    )

    def find_location(self, context: ActivityContext):
        # min_participants - 1 other free people already nearby - a
        # group can't form around an empty street.
        candidates = nearby_free_pedestrians(
            context, SEARCH_RADIUS_M, limit=self.definition.max_participants - 1
        )
        if len(candidates) < self.definition.min_participants - 1:
            return None
        pedestrian = context.pedestrian
        all_x = [pedestrian.x] + [candidate.x for candidate in candidates]
        all_y = [pedestrian.y] + [candidate.y for candidate in candidates]
        centroid = (sum(all_x) / len(all_x), sum(all_y) / len(all_y))
        return ActivityLocation(x=centroid[0], y=centroid[1], reservation_key=None, extra=candidates)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        if instance.group is None:
            partners = instance.location.extra if instance.location is not None else None
            available = [
                partner for partner in (partners or [])
                if partner.activity is None and partner.linked_vehicle_id is None
            ]
            if len(available) < self.definition.min_participants - 1:
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
            for partner in available:
                recruit(
                    context, self.definition.id, group, partner, instance.location,
                    (self.definition.min_duration_s, self.definition.max_duration_s),
                )

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        if instance.group is None:
            return True
        instance.data["elapsed_s"] += dt
        arrived_others = [
            other for other in other_group_members(context, instance.group) if other.state == "performing_activity"
        ]
        if arrived_others:
            pedestrian = context.pedestrian
            centroid_x = sum(other.x for other in arrived_others) / len(arrived_others)
            centroid_y = sum(other.y for other in arrived_others) / len(arrived_others)
            pedestrian.heading = math.atan2(centroid_y - pedestrian.y, centroid_x - pedestrian.x)
        return instance.data["elapsed_s"] >= instance.data["duration_s"]

    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None:
        if instance.group is not None and context.pedestrian.resident_id in instance.group.member_resident_ids:
            instance.group.member_resident_ids.remove(context.pedestrian.resident_id)


PLUGIN = SmallGroupConversationPlugin()
