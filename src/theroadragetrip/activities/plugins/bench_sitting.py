"""Sit on a nearby OSM bench for a while (residents-live.md section 6)."""
from __future__ import annotations

import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin

SEARCH_RADIUS_M = 40.0


class BenchSittingPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="bench_sitting",
        name="Sitting on a bench",
        min_duration_s=15.0,
        max_duration_s=90.0,
        cooldown_s=120.0,
        base_weight=1.0,
    )

    def find_location(self, context: ActivityContext):
        pedestrian = context.pedestrian
        benches = [
            scenery_object
            for scenery_object in context.pedestrian_manager.nearby_scenery_objects(
                pedestrian.x, pedestrian.y, SEARCH_RADIUS_M
            )
            if scenery_object.kind == "bench"
        ]
        if not benches:
            return None
        bench = random.choice(benches)
        return ActivityLocation(x=bench.x, y=bench.y, reservation_key=("bench", id(bench)), extra=bench)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0
        bench = instance.location.extra if instance.location is not None else None
        if bench is not None and bench.direction_angle is not None:
            context.pedestrian.heading = bench.direction_angle

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = BenchSittingPlugin()
