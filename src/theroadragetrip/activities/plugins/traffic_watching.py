"""Stop near a crossing and watch traffic go by (residents-live.md section 6).

Reuses PedestrianManager.crossings directly (a plain list, same linear-
distance-filter idiom this file already uses elsewhere for
venue_locations/entrance_locations) rather than scanning every OSM way for
a "busy road" - a mapped pedestrian crossing already *is* a busy-road
vantage point.
"""
from __future__ import annotations

import math
import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin

SEARCH_RADIUS_M = 60.0


class TrafficWatchingPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="traffic_watching",
        name="Watching traffic",
        min_duration_s=15.0,
        max_duration_s=40.0,
        cooldown_s=90.0,
        base_weight=0.5,
    )

    def find_location(self, context: ActivityContext):
        pedestrian = context.pedestrian
        nearby_crossings = [
            crossing
            for crossing in context.pedestrian_manager.crossings
            if math.hypot(crossing.x - pedestrian.x, crossing.y - pedestrian.y) <= SEARCH_RADIUS_M
        ]
        if not nearby_crossings:
            return None
        crossing = random.choice(nearby_crossings)
        # No reservation - a busy street can have several onlookers.
        return ActivityLocation(x=crossing.x, y=crossing.y, reservation_key=None, extra=crossing)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0
        crossing = instance.location.extra if instance.location is not None else None
        road_axis_angle = getattr(crossing, "direction_angle", None)
        if road_axis_angle is not None:
            # Face across the road (perpendicular to its own axis), the
            # way someone actually watching cars pass would stand.
            context.pedestrian.heading = road_axis_angle + math.pi / 2.0

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = TrafficWatchingPlugin()
