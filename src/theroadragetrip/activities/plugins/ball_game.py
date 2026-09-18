"""Children gather in an open space and play with a ball
(residents-live.md section 7) - not a hardcoded child state on Resident,
just an ordinary activity plugin gated by age (the same age_of() < 18
check ResidentManager.create() already uses to decide who's a minor).

Combines two things already built for other plugins: park_leisure's
interior-point sampling (an "open space" is just a park/grass Scenery)
and the recruit-at-start() group mechanism two_person_conversation/
small_group_conversation use. "Move around the area" during play is
handled like exercise_jogging's self-directed movement, just bounded to
resampling points inside the one chosen park instead of anywhere nearby.
"""
from __future__ import annotations

import math
import random

from ..base import ActivityContext, ActivityDefinition, ActivityGroup, ActivityInstance, ActivityLocation, ActivityPlugin
from ..grouping import nearby_free_pedestrians, next_group_id, other_group_members, recruit
from .park_leisure import PARK_KINDS, sample_interior_point

SEARCH_RADIUS_M = 60.0
MOVE_INTERVAL_S = 4.0


class BallGamePlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="ball_game",
        name="Playing ball",
        min_duration_s=45.0,
        max_duration_s=150.0,
        cooldown_s=180.0,
        base_weight=0.5,
        min_participants=2,
        max_participants=5,
    )

    def can_start(self, context: ActivityContext) -> bool:
        resident = context.residents.get(context.pedestrian.resident_id)
        return resident is not None and context.residents.age_of(resident) < 18

    def find_location(self, context: ActivityContext):
        pedestrian = context.pedestrian
        parks = [
            scenery
            for scenery in context.pedestrian_manager.nearby_sceneries(pedestrian.x, pedestrian.y, SEARCH_RADIUS_M)
            if scenery.kind in PARK_KINDS and len(scenery.points_m) >= 3
        ]
        if not parks:
            return None
        park = random.choice(parks)
        point = sample_interior_point(park)
        if point is None:
            return None
        other_children = nearby_free_pedestrians(
            context, SEARCH_RADIUS_M, limit=self.definition.max_participants - 1, children_only=True
        )
        if len(other_children) < self.definition.min_participants - 1:
            return None
        return ActivityLocation(x=point[0], y=point[1], reservation_key=None, extra=(park, other_children))

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        if instance.group is None:
            park, partners = instance.location.extra if instance.location is not None else (None, [])
            available = [
                partner for partner in (partners or [])
                if partner.activity is None and partner.linked_vehicle_id is None
            ]
            if park is None or len(available) < self.definition.min_participants - 1:
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
            instance.data["park"] = park
            instance.data["move_elapsed_s"] = 0.0
            for partner in available:
                recruit(
                    context, self.definition.id, group, partner, instance.location,
                    (self.definition.min_duration_s, self.definition.max_duration_s),
                )
                # Every recruited child moves around the same park too.
                partner.activity.data["park"] = park
                partner.activity.data["move_elapsed_s"] = 0.0

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        if instance.group is None:
            return True
        instance.data["elapsed_s"] += dt
        instance.data["move_elapsed_s"] += dt
        pedestrian = context.pedestrian
        park = instance.data.get("park")
        if park is not None and instance.data["move_elapsed_s"] >= MOVE_INTERVAL_S:
            instance.data["move_elapsed_s"] = 0.0
            point = sample_interior_point(park)
            if point is not None:
                context.pedestrian_manager._walk_route_to(pedestrian, dt, point)
        arrived_others = [
            other for other in other_group_members(context, instance.group) if other.state == "performing_activity"
        ]
        if arrived_others:
            centroid_x = sum(other.x for other in arrived_others) / len(arrived_others)
            centroid_y = sum(other.y for other in arrived_others) / len(arrived_others)
            pedestrian.heading = math.atan2(centroid_y - pedestrian.y, centroid_x - pedestrian.x)
        return instance.data["elapsed_s"] >= instance.data["duration_s"]

    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None:
        if instance.group is not None and context.pedestrian.resident_id in instance.group.member_resident_ids:
            instance.group.member_resident_ids.remove(context.pedestrian.resident_id)


PLUGIN = BallGamePlugin()
