"""Jog around the neighbourhood for a while, then resume walking
(residents-live.md section 6).

Unlike the other activities, this one has no single destination to
arrive at and sit still - "jogging" *is* movement. requires_location=False
so the core's WALK_TO_LOCATION step never runs (there's nowhere to walk
to yet); instead update() drives the pedestrian itself, picking a new
nearby footway waypoint each time the last one is reached and reusing
PedestrianManager._walk_route_to for the actual stepping - the exact same
sidewalk-network routing every other activity's approach leg uses, just
called repeatedly here instead of once.
"""
from __future__ import annotations

import math
import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityPlugin

JOG_SPEED_MULTIPLIER = 1.8
JOG_LEG_MIN_M = 30.0
JOG_LEG_MAX_M = 80.0


class ExerciseJoggingPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="exercise_jogging",
        name="Jogging",
        requires_location=False,
        min_duration_s=20.0,
        max_duration_s=60.0,
        cooldown_s=150.0,
        base_weight=0.5,
    )

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        pedestrian = context.pedestrian
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0
        instance.data["pre_jog_base_speed"] = pedestrian.base_speed
        instance.data["waypoint"] = None
        pedestrian.base_speed *= JOG_SPEED_MULTIPLIER

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        pedestrian = context.pedestrian
        manager = context.pedestrian_manager
        instance.data["elapsed_s"] += dt
        if instance.data["elapsed_s"] >= instance.data["duration_s"]:
            return True
        waypoint = instance.data["waypoint"]
        if waypoint is None or manager._walk_route_to(pedestrian, dt, waypoint):
            angle = random.uniform(0.0, 2.0 * math.pi)
            distance = random.uniform(JOG_LEG_MIN_M, JOG_LEG_MAX_M)
            raw_point = (pedestrian.x + math.cos(angle) * distance, pedestrian.y + math.sin(angle) * distance)
            instance.data["waypoint"] = manager.network.nearest_point(raw_point) or (pedestrian.x, pedestrian.y)
        return False

    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None:
        context.pedestrian.base_speed = instance.data.get("pre_jog_base_speed", context.pedestrian.base_speed)


PLUGIN = ExerciseJoggingPlugin()
