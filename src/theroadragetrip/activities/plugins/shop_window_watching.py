"""Stop at a commercial building's frontage and look (residents-live.md section 6).

Reuses PedestrianManager.amenity_entrance_locations - already exactly
"the entrance of a building with a truthy venue_type" (set_venue_buildings
extends it for any building where getattr(building, "venue_type", None)
is truthy, a broader set than eating_drinking's food/drink-only
venue_locations).
"""
from __future__ import annotations

import math
import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin

SEARCH_RADIUS_M = 50.0


class ShopWindowWatchingPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="shop_window_watching",
        name="Window shopping",
        min_duration_s=15.0,
        max_duration_s=45.0,
        cooldown_s=90.0,
        base_weight=0.6,
    )

    def find_location(self, context: ActivityContext):
        pedestrian = context.pedestrian
        nearby_entrances = [
            entrance
            for entrance in context.pedestrian_manager.amenity_entrance_locations
            if math.hypot(entrance[0] - pedestrian.x, entrance[1] - pedestrian.y) <= SEARCH_RADIUS_M
        ]
        if not nearby_entrances:
            return None
        entrance_x, entrance_y = random.choice(nearby_entrances)
        # No reservation - several people can window-shop the same storefront.
        return ActivityLocation(x=entrance_x, y=entrance_y, reservation_key=None)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0
        # _walk_route_to already leaves pedestrian.heading pointing from
        # the approach direction straight at the entrance on arrival -
        # exactly "facing the shop" already, nothing more to set here.

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = ShopWindowWatchingPlugin()
