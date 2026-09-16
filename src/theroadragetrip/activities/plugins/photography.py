"""Stop and photograph a nearby landmark (residents-live.md section 6).

Subjects are kept to what's already reliably identifiable as "interesting"
without inventing a scoring heuristic: statues/memorials/fountains
(SceneryObject) and parks (Scenery, sharing park_leisure's PARK_KINDS) -
not a generic "buildings/traffic/streets" detector, which the spec
explicitly says isn't required ("do not implement a complicated camera
system unless the game already has one" - it doesn't).
"""
from __future__ import annotations

import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin
from .park_leisure import PARK_KINDS, sample_interior_point

SEARCH_RADIUS_M = 50.0
SUBJECT_KINDS = {"statue", "fountain"}


class PhotographyPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="photography",
        name="Taking a photo",
        min_duration_s=4.0,
        max_duration_s=10.0,
        cooldown_s=90.0,
        base_weight=0.5,
    )

    def find_location(self, context: ActivityContext):
        pedestrian = context.pedestrian
        manager = context.pedestrian_manager
        subjects = [
            scenery_object
            for scenery_object in manager.nearby_scenery_objects(pedestrian.x, pedestrian.y, SEARCH_RADIUS_M)
            if scenery_object.kind in SUBJECT_KINDS
        ]
        if subjects:
            subject = random.choice(subjects)
            return ActivityLocation(x=subject.x, y=subject.y, reservation_key=None, extra=subject)
        parks = [
            scenery
            for scenery in manager.nearby_sceneries(pedestrian.x, pedestrian.y, SEARCH_RADIUS_M)
            if scenery.kind in PARK_KINDS
        ]
        if not parks:
            return None
        park = random.choice(parks)
        point = sample_interior_point(park)
        if point is None:
            return None
        return ActivityLocation(x=point[0], y=point[1], reservation_key=None, extra=park)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = PhotographyPlugin()
