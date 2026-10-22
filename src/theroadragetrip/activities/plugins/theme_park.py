"""Queue, take a lap on an attraction, and disembark at its entrance."""
import math
import random

from shapely.geometry import LineString

from ..base import ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin
from ...viewport import in_bounds


class ThemeParkPlugin(ActivityPlugin):
    definition = ActivityDefinition(id="theme_park", name="Visiting an attraction", cooldown_s=60)

    def can_start(self, context):
        return context.pedestrian_manager.soccer_open

    def find_location(self, context):
        if not self.can_start(context):
            return None
        p = context.pedestrian
        choices = [s for s in context.pedestrian_manager.nearby_sceneries(p.x, p.y, 100)
                   if s.kind.startswith("attraction_") and s.attraction_path]
        random.shuffle(choices)
        for ride in choices:
            for seat in range(6):
                location = self.location(ride, seat)
                if math.dist((p.x, p.y), (location.x, location.y)) <= 100 and location.reservation_key not in context.pedestrian_manager.activity_manager._reservations:
                    return location
        return None

    @staticmethod
    def location(ride, seat):
        # Queue along the validated ride loop, keeping every visitor inside its footprint.
        point = LineString(ride.attraction_path).interpolate(seat * 1.3)
        return ActivityLocation(point.x, point.y, ("attraction", *ride.attraction_path[0], seat), ride)

    def start(self, context, instance):
        instance.data.update(elapsed=0.0, path=LineString(instance.location.extra.attraction_path))
        context.pedestrian.speed = 0
        context.pedestrian.animation_state = "idle"

    def update(self, context, instance, dt):
        instance.data["elapsed"] += dt
        elapsed = instance.data["elapsed"]
        p = context.pedestrian
        seat = instance.location.reservation_key[-1]
        wait = 3 + seat * .6
        path = instance.data["path"]
        if elapsed < wait:
            return not self.can_start(context)
        # shortcut: flat ride loops; add height profiles when the map and renderer support elevated ride tracks.
        progress = min(1.0, (elapsed - wait) / 24)
        # End the lap at the same queue position: no jumping from moving rides.
        point = path.interpolate((seat * 1.3 + progress * path.length) % path.length)
        ahead = path.interpolate((seat * 1.3 + progress * path.length + .2) % path.length)
        p.x, p.y = point.x, point.y
        p.heading = math.atan2(ahead.y-point.y, ahead.x-point.x)
        p.speed = 0
        p.animation_state = "riding"
        return progress >= 1

    def populate(self, manager, ride, bounds, budget):
        if budget <= 0 or not manager.soccer_open or not ride.attraction_path:
            return 0
        for seat in range(6):
            location = self.location(ride, seat)
            if not in_bounds(bounds, location.x, location.y) or location.reservation_key in manager.activity_manager._reservations:
                continue
            p = manager.spawn_pedestrian_at(location.x, location.y)
            if p is None or not manager.add_pedestrian(p):
                return 1
            context = manager._activity_context(p)
            if manager.activity_manager.reserve(context, location):
                p.activity = ActivityInstance(self.definition.id, location, manager.sim_time)
                p.state = "performing_activity"
                self.start(context, p.activity)
            else:
                manager.pedestrians.remove(p)
            return 1
        return 0


PLUGIN = ThemeParkPlugin()
