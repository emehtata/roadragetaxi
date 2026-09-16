"""Relax in a nearby park/grass area (residents-live.md section 6).

An area, not a point - proves the framework also handles a location that's
a whole polygon, not just a single reservable object. No reservation: an
open lawn fits many people at once, unlike a bench or a waste basket.
"""
from __future__ import annotations

import random

from ...geo import point_in_polygon
from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin

SEARCH_RADIUS_M = 80.0
MAX_INTERIOR_SAMPLE_ATTEMPTS = 20
# Raw OSM leisure=*/landuse=*/natural=* values treated as suitable for
# leisure (see osm/build.py's kind mapping and osm/constants.py's
# NATURAL_SCENERY_KINDS) - deliberately excludes lookalike kinds sharing
# the same Scenery class, like "parking"/"forest"/"water".
PARK_KINDS = {"park", "garden", "grass", "grassland", "recreation_ground", "common"}


class ParkLeisurePlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="park_leisure",
        name="Relaxing in the park",
        min_duration_s=30.0,
        max_duration_s=120.0,
        cooldown_s=180.0,
        base_weight=0.8,
    )

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
        minx, miny, maxx, maxy = park.bbox
        for _ in range(MAX_INTERIOR_SAMPLE_ATTEMPTS):
            x, y = random.uniform(minx, maxx), random.uniform(miny, maxy)
            if point_in_polygon(x, y, park.points_m):
                return ActivityLocation(x=x, y=y, reservation_key=None, extra=park)
        return None

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = ParkLeisurePlugin()
