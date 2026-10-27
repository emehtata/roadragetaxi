"""Enter beside a mapped beach, swim near shore, then walk back onto land."""
import math
import random

from ..base import ActivityDefinition, ActivityLocation
from ..beach import BeachPlugin
from .ice_skating import glide


class SwimmingPlugin(BeachPlugin):
    definition = ActivityDefinition(id="swimming", name="Swimming", min_duration_s=45,
                                    max_duration_s=120, cooldown_s=120)

    def find_location(self, context):
        if not self.can_start(context):
            return None
        p = context.pedestrian
        routes = [(beach, route) for beach in context.pedestrian_manager.nearby_sceneries(p.x, p.y, 120)
                  if beach.kind == "beach" for route in beach.swim_routes
                  if math.dist(route[0], (p.x, p.y)) <= 120]
        if not routes:
            return None
        beach, route = random.choice(routes)
        return ActivityLocation(*route[0], reservation_key=("beach", *route[0]), extra=beach)

    def start(self, context, instance):
        super().start(context, instance)
        beach = instance.location.extra
        instance.data["route"] = min(beach.swim_routes, key=lambda route: math.dist(route[0], (instance.location.x, instance.location.y)))
        instance.data.update(phase="enter", target=instance.data["route"][-1])

    def update(self, context, instance, dt):
        data = instance.data
        data["elapsed"] += dt
        land, entry, outer = data["route"]
        if not self.can_start(context) or data["elapsed"] >= data["duration"]:
            data.update(phase="leave", target=land)
        p = context.pedestrian
        arrived = glide(p, data["target"], dt, 0.9)
        if math.dist((p.x, p.y), land) >= math.dist(entry, land):
            p.animation_state = "swimming"
        if arrived:
            if data["phase"] == "leave":
                p.x, p.y = land
                return True
            data["phase"] = "swim"
            fraction = random.uniform(0.15, 1.0)
            data["target"] = entry[0]+(outer[0]-entry[0])*fraction, entry[1]+(outer[1]-entry[1])*fraction
        return False


PLUGIN = SwimmingPlugin()
