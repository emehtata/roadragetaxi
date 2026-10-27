"""Walk an owned dog using the ordinary pedestrian route network."""
from __future__ import annotations

import math
import random

from ...pedestrian import Dog
from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityPlugin
from .park_leisure import PARK_KINDS

DOG_WALKER_MAX = 12
LEASH_MAX_M = 2.8
WALK_LEG_MIN_M = 35.0
WALK_LEG_MAX_M = 90.0
UNSUITABLE_HIGHWAYS = {"motorway", "motorway_link", "trunk", "trunk_link"}


def time_activity(game_time_seconds: float | None) -> float:
    """Smooth simulated-time weight with morning and evening peaks."""
    if game_time_seconds is None:
        return 0.7
    hour = game_time_seconds / 3600.0 % 24.0
    distance = lambda peak: min(abs(hour - peak), 24.0 - abs(hour - peak))
    return 0.22 + 0.55 * math.exp(-(distance(8.0) / 2.0) ** 2) + 0.75 * math.exp(-(distance(18.5) / 3.0) ** 2)


class DogWalkingPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="dog_walking", name="Walking a dog", requires_location=False,
        min_duration_s=45.0, max_duration_s=150.0, cooldown_s=300.0, base_weight=0.55,
    )

    def can_start(self, context: ActivityContext) -> bool:
        pedestrian = context.pedestrian
        return (
            pedestrian.dog is None
            and pedestrian.way.highway not in UNSUITABLE_HIGHWAYS
            and sum(candidate.dog is not None for candidate in context.pedestrian_manager.pedestrians) < DOG_WALKER_MAX
        )

    def score(self, context: ActivityContext, location) -> float:
        pedestrian = context.pedestrian
        near_green = any(
            scenery.kind in PARK_KINDS
            for scenery in context.pedestrian_manager.nearby_sceneries(pedestrian.x, pedestrian.y, 80.0)
        )
        return time_activity(context.pedestrian_manager._last_game_time_seconds) * (1.5 if near_green else 1.0)

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        pedestrian = context.pedestrian
        side = -1.0 if random.random() < 0.5 else 1.0
        dog = Dog(
            x=pedestrian.x - math.cos(pedestrian.heading) * 1.2 - math.sin(pedestrian.heading) * side * 0.5,
            y=pedestrian.y - math.sin(pedestrian.heading) * 1.2 + math.cos(pedestrian.heading) * side * 0.5,
            heading=pedestrian.heading,
            size=random.choice(("small", "medium", "large")),
            color=random.choice(((86, 57, 37), (42, 38, 35), (188, 148, 94), (225, 218, 199))),
        )
        pedestrian.dog = dog
        pedestrian.animation_state = "walking"
        instance.data.update({
            "duration_s": random.uniform(self.definition.min_duration_s, self.definition.max_duration_s),
            "elapsed_s": 0.0,
            "waypoint": None,
            "next_sniff_s": random.uniform(8.0, 20.0),
            "sniff_s": 0.0,
            "side": side,
            "phase": random.uniform(0.0, math.tau),
        })

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        pedestrian = context.pedestrian
        dog = pedestrian.dog
        if dog is None:
            return True
        instance.data["elapsed_s"] += dt
        elapsed = instance.data["elapsed_s"]
        if elapsed >= instance.data["duration_s"]:
            return True

        if instance.data["sniff_s"] > 0.0:
            instance.data["sniff_s"] = max(0.0, instance.data["sniff_s"] - dt)
            pedestrian.speed = 0.0
            pedestrian.animation_state = "idle"
        else:
            pedestrian.animation_state = "walking"
            waypoint = instance.data["waypoint"]
            if waypoint is None or context.pedestrian_manager._walk_route_to(pedestrian, dt, waypoint):
                angle = pedestrian.heading + random.uniform(-1.0, 1.0)
                distance = random.uniform(WALK_LEG_MIN_M, WALK_LEG_MAX_M)
                raw = (pedestrian.x + math.cos(angle) * distance, pedestrian.y + math.sin(angle) * distance)
                instance.data["waypoint"] = context.pedestrian_manager.network.nearest_point(raw) or (pedestrian.x, pedestrian.y)
            if elapsed >= instance.data["next_sniff_s"]:
                instance.data["sniff_s"] = random.uniform(1.5, 4.0)
                instance.data["next_sniff_s"] = elapsed + random.uniform(10.0, 24.0)

        heading = pedestrian.heading
        forward = (math.cos(heading), math.sin(heading))
        side = (-forward[1], forward[0])
        lateral = instance.data["side"] * (0.55 + 0.25 * math.sin(elapsed * 1.7 + instance.data["phase"]))
        target_x = pedestrian.x - forward[0] * 1.15 + side[0] * lateral
        target_y = pedestrian.y - forward[1] * 1.15 + side[1] * lateral
        blend = 1.0 - math.exp(-5.0 * dt)
        old_x, old_y = dog.x, dog.y
        dog.x += (target_x - dog.x) * blend
        dog.y += (target_y - dog.y) * blend
        leash = math.hypot(dog.x - pedestrian.x, dog.y - pedestrian.y)
        if leash > LEASH_MAX_M:
            scale = LEASH_MAX_M / leash
            dog.x = pedestrian.x + (dog.x - pedestrian.x) * scale
            dog.y = pedestrian.y + (dog.y - pedestrian.y) * scale
        if math.hypot(dog.x - old_x, dog.y - old_y) > 0.001:
            dog.heading = math.atan2(dog.y - old_y, dog.x - old_x)
        dog.sniffing = instance.data["sniff_s"] > 0.0
        return False

    def finish(self, context: ActivityContext, instance: ActivityInstance) -> None:
        context.pedestrian.dog = None
        context.pedestrian.route = None


PLUGIN = DogWalkingPlugin()
