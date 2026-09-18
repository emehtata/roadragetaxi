"""A child visits an actual OSM playground (residents-live.md section 6).

Solo-shaped (unlike ball_game): the spec's own description here - "walk
there, enter the usable area, play, remain, leave" - never says the child
needs to coordinate with other children, only ball_game explicitly does
("gather into a small group"). A Scenery with kind="playground" already
exists from OSM leisure=playground data via the same kind mapping
park_leisure's PARK_KINDS draws from - no new OSM parsing needed.
"""
from __future__ import annotations

import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin
from .park_leisure import sample_interior_point

SEARCH_RADIUS_M = 80.0


class PlaygroundPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="playground",
        name="Playing at the playground",
        min_duration_s=45.0,
        max_duration_s=150.0,
        cooldown_s=180.0,
        base_weight=0.6,
    )

    def can_start(self, context: ActivityContext) -> bool:
        resident = context.residents.get(context.pedestrian.resident_id)
        return resident is not None and context.residents.age_of(resident) < 18

    def find_location(self, context: ActivityContext):
        pedestrian = context.pedestrian
        playgrounds = [
            scenery
            for scenery in context.pedestrian_manager.nearby_sceneries(pedestrian.x, pedestrian.y, SEARCH_RADIUS_M)
            if scenery.kind == "playground" and len(scenery.points_m) >= 3
        ]
        if not playgrounds:
            return None
        playground = random.choice(playgrounds)
        point = sample_interior_point(playground)
        if point is None:
            return None
        return ActivityLocation(x=point[0], y=point[1], reservation_key=None, extra=playground)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = PlaygroundPlugin()
