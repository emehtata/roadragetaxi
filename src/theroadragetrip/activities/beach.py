"""Shared beach eligibility, locations and bounded visible-beach population."""
import math
import random

from .base import ActivityInstance, ActivityLocation, ActivityPlugin
from ..viewport import in_bounds

BEACH_ACTIVITIES = ("sunbathing", "beach_games", "swimming")


class BeachPlugin(ActivityPlugin):
    def can_start(self, context):
        return context.pedestrian_manager.beach_open

    def find_location(self, context):
        if not self.can_start(context):
            return None
        p = context.pedestrian
        choices = [(beach, point) for beach in context.pedestrian_manager.nearby_sceneries(p.x, p.y, 120)
                   if beach.kind == "beach" for point in beach.beach_spots
                   if math.dist(point, (p.x, p.y)) <= 120]
        if not choices:
            return None
        beach, point = random.choice(choices)
        return ActivityLocation(*point, reservation_key=("beach", *point), extra=beach)

    def start(self, context, instance):
        context.pedestrian.speed = 0.0
        context.pedestrian.animation_state = "idle"
        instance.data.update(beach=instance.location.extra, elapsed=0.0,
                             duration=random.uniform(self.definition.min_duration_s, self.definition.max_duration_s))

    def update(self, context, instance, dt):
        instance.data["elapsed"] += dt
        return not self.can_start(context) or instance.data["elapsed"] >= instance.data["duration"]


def populate_beach(manager, beach, bounds, budget):
    people = [p for p in manager.pedestrians if p.activity and p.activity.plugin_id in BEACH_ACTIVITIES
              and p.activity.location.extra is beach]
    if not manager.beach_open or len(people) >= 16:
        return 0
    counts = {kind: sum(p.activity.plugin_id == kind for p in people) for kind in BEACH_ACTIVITIES}
    for kind in sorted(BEACH_ACTIVITIES, key=counts.get):
        number = 2 if kind == "beach_games" else 1
        if number > budget or len(people) + number > 16:
            continue
        candidates = [route[0] for route in beach.swim_routes] if kind == "swimming" else beach.beach_spots
        points = [point for point in candidates if in_bounds(bounds, *point)
                  and all(math.dist(point, (p.x, p.y)) >= 4 for p in people)]
        plugin = manager.activity_manager.registry.get(kind)
        if not points or plugin is None:
            continue
        point = random.choice(points)
        spawned = []
        for offset in ([-1.5, 1.5] if number == 2 else [0.0]):
            p = manager.spawn_pedestrian_at(point[0]+offset, point[1])
            if p is not None and manager.add_pedestrian(p):
                spawned.append(p)
        if len(spawned) != number:
            for p in spawned:
                manager.pedestrians.remove(p)
            return number
        player = spawned[0]
        context = manager._activity_context(player)
        location = ActivityLocation(*point, reservation_key=("beach", *point), extra=beach)
        if manager.activity_manager.reserve(context, location):
            player.activity = ActivityInstance(kind, location, manager.sim_time)
            player.state = "performing_activity"
            plugin.start(context, player.activity)
        else:
            for p in spawned:
                manager.pedestrians.remove(p)
        return number
    return 0
