"""Sit somewhere and eat/drink (residents-live.md section 6).

Generic enough to cover both an outdoor picnic table (SceneryObject) and a
cafe/restaurant/bar frontage (Building.venue_type) - the same two location
kinds bench_sitting/shop_window_watching already draw on, just combined
into one candidate pool here.
"""
from __future__ import annotations

import math
import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin

PICNIC_TABLE_SEARCH_RADIUS_M = 40.0
VENUE_SEARCH_RADIUS_M = 60.0


class EatingDrinkingPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="eating_drinking",
        name="Eating and drinking",
        min_duration_s=30.0,
        max_duration_s=90.0,
        cooldown_s=150.0,
        base_weight=0.8,
    )

    def find_location(self, context: ActivityContext):
        pedestrian = context.pedestrian
        manager = context.pedestrian_manager
        picnic_tables = [
            scenery_object
            for scenery_object in manager.nearby_scenery_objects(pedestrian.x, pedestrian.y, PICNIC_TABLE_SEARCH_RADIUS_M)
            if scenery_object.kind == "picnic_table"
        ]
        if picnic_tables:
            table = random.choice(picnic_tables)
            return ActivityLocation(x=table.x, y=table.y, reservation_key=("picnic_table", id(table)), extra=table)
        # No picnic table nearby - fall back to a cafe/restaurant/bar
        # frontage (self.venue_locations, already computed by
        # set_venue_buildings for exactly these OSM venue_type kinds - a
        # cafe/restaurant serves many customers, so no reservation).
        nearby_venues = [
            location for location in manager.venue_locations
            if math.hypot(location[0] - pedestrian.x, location[1] - pedestrian.y) <= VENUE_SEARCH_RADIUS_M
        ]
        if not nearby_venues:
            return None
        venue_x, venue_y = random.choice(nearby_venues)
        return ActivityLocation(x=venue_x, y=venue_y, reservation_key=None)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = EatingDrinkingPlugin()
