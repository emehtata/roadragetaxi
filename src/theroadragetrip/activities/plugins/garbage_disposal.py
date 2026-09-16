"""Walk to the nearest waste basket and throw something away
(residents-live.md section 6).

Nothing in this codebase models a pedestrian inventory, so "carrying
something disposable" is the smallest plausible stand-in: a stateless
per-consideration probability roll, not a persistent trait - nothing
renders a carried item, so there's no visible inconsistency in a
pedestrian sometimes being caught carrying trash and sometimes not.
"""
from __future__ import annotations

import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin

SEARCH_RADIUS_M = 40.0
CARRYING_DISPOSABLE_PROBABILITY = 0.2


class GarbageDisposalPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="garbage_disposal",
        name="Throwing away trash",
        min_duration_s=3.0,
        max_duration_s=6.0,
        cooldown_s=180.0,
        base_weight=0.6,
    )

    def can_start(self, context: ActivityContext) -> bool:
        return random.random() < CARRYING_DISPOSABLE_PROBABILITY

    def find_location(self, context: ActivityContext):
        pedestrian = context.pedestrian
        baskets = [
            scenery_object
            for scenery_object in context.pedestrian_manager.nearby_scenery_objects(
                pedestrian.x, pedestrian.y, SEARCH_RADIUS_M
            )
            if scenery_object.kind == "waste_basket"
        ]
        if not baskets:
            return None
        basket = min(baskets, key=lambda o: (o.x - pedestrian.x) ** 2 + (o.y - pedestrian.y) ** 2)
        return ActivityLocation(x=basket.x, y=basket.y, reservation_key=("waste_basket", id(basket)), extra=basket)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = GarbageDisposalPlugin()
