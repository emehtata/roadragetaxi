"""Wait at a real OSM bus stop for a while (residents-live.md section 6).

Reuses PedestrianManager.bus_stops (a plain list, same linear-filter idiom
as crossings/venue_locations elsewhere in this file - bus stop counts per
city are small). The game has no bus arrival/schedule simulation, so this
is cosmetic waiting only, per the spec's own "don't make every Resident
wait indefinitely" - a random duration, then they give up and move on.
"""
from __future__ import annotations

import math
import random

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin

SEARCH_RADIUS_M = 50.0
LOOK_AROUND_INTERVAL_S = 6.0


class BusStopWaitingPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="bus_stop_waiting",
        name="Waiting at a bus stop",
        min_duration_s=20.0,
        max_duration_s=90.0,
        cooldown_s=120.0,
        base_weight=0.5,
    )

    def find_location(self, context: ActivityContext):
        pedestrian = context.pedestrian
        nearby_stops = [
            bus_stop
            for bus_stop in context.pedestrian_manager.bus_stops
            if math.hypot(bus_stop.x - pedestrian.x, bus_stop.y - pedestrian.y) <= SEARCH_RADIUS_M
        ]
        if not nearby_stops:
            return None
        bus_stop = random.choice(nearby_stops)
        # No reservation - several people can wait at the same stop.
        return ActivityLocation(x=bus_stop.x, y=bus_stop.y, reservation_key=None)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0
        instance.data["look_around_elapsed_s"] = 0.0

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        instance.data["look_around_elapsed_s"] += dt
        if instance.data["look_around_elapsed_s"] >= LOOK_AROUND_INTERVAL_S:
            instance.data["look_around_elapsed_s"] = 0.0
            context.pedestrian.heading = random.uniform(0.0, 2.0 * math.pi)
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = BusStopWaitingPlugin()
