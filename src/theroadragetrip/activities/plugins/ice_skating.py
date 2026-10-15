"""Skate on a frozen sports field (a Finnish winter: pitches and rinks are
flooded for skating). Only while the server says the ice is open
(PedestrianManager.sports_ice_open: frozen, and daylight or floodlit
hours); skaters leave when it closes. They glide straight between points
on the ice - not along footways - at skating speed.
"""
from __future__ import annotations

import math
import random
from typing import Optional, Tuple

from ...map_style import FROZEN_IN_WINTER_KINDS
from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin
from .park_leisure import sample_interior_point

SEARCH_RADIUS_M = 120.0
SKATING_SPEED_MPS = 3.5
SKATER_RADIUS_M = 0.45  # two skaters closer than twice this collide
KNOCKDOWN_SPEED_DIFF_MPS = 1.5  # this much faster than the other: the slower one falls
FALL_S = 2.5  # down on the ice before getting up
# Played on a sports field: these people collide, and go when the field leaves the view.
FIELD_ACTIVITIES = ("ice_skating", "ice_hockey", "soccer")


def open_ice(context: ActivityContext, radius_m: float = SEARCH_RADIUS_M, kinds=FROZEN_IN_WINTER_KINDS) -> list:
    """Frozen fields of `kinds` near the pedestrian, while the ice is open."""
    manager = context.pedestrian_manager
    if not getattr(manager, "sports_ice_open", False):
        return []
    pedestrian = context.pedestrian
    return [s for s in manager.nearby_sceneries(pedestrian.x, pedestrian.y, radius_m)
            if s.kind in kinds and len(s.points_m) >= 3]


def glide(pedestrian, target: Tuple[float, float], dt: float, speed: float = SKATING_SPEED_MPS) -> bool:
    """Straight across the ice toward `target`; True once there."""
    dx, dy = target[0] - pedestrian.x, target[1] - pedestrian.y
    distance = math.hypot(dx, dy)
    if distance <= 0.5:
        return True
    pedestrian.heading = math.atan2(dy, dx)
    step = min(distance, speed * dt)
    pedestrian.x += dx / distance * step
    pedestrian.y += dy / distance * step
    pedestrian.speed = speed
    pedestrian.animation_state = "walking"
    return False


def others_on(field, pedestrian, pedestrians) -> list:
    """The other people skating or playing on `field`."""
    return [p for p in pedestrians
            if p is not pedestrian and p.activity is not None and p.activity.plugin_id in FIELD_ACTIVITIES
            and p.activity.location is not None and p.activity.location.extra is field]


def knock_down(pedestrian) -> bool:
    """Down they go; False if they already were."""
    if pedestrian.activity is not None:
        if pedestrian.activity.data.get("fallen_s", 0.0) > 0.0:
            return False  # already down: skating into them doesn't start the fall over
        pedestrian.activity.data["fallen_s"] = FALL_S
    pedestrian.animation_state = "fallen"
    pedestrian.speed = 0.0
    return True


def is_down(pedestrian, instance, dt: float) -> bool:
    """Whether `pedestrian` is still lying on the ice after a fall (this tick
    spent getting up counts as down too)."""
    left = instance.data.get("fallen_s", 0.0)
    if left <= 0.0:
        return False
    instance.data["fallen_s"] = left - dt
    pedestrian.speed = 0.0
    pedestrian.animation_state = "fallen" if left - dt > 0.0 else "walking"
    return True


def collide(pedestrian, others, knockdown_chance: float = 1.0) -> list:
    """Skaters don't overlap: two too close are pushed apart, and one at
    least KNOCKDOWN_SPEED_DIFF_MPS faster knocks the slower one down (with
    `knockdown_chance`: on grass most such bumps are only shoulders).
    Returns the knockdowns: [(who fell, who knocked them down)]."""
    knocked = []
    reach = 2.0 * SKATER_RADIUS_M
    for other in others:
        dx, dy = other.x - pedestrian.x, other.y - pedestrian.y
        distance = math.hypot(dx, dy)
        if distance >= reach:
            continue
        nx, ny = (dx / distance, dy / distance) if distance > 1e-6 else (math.cos(pedestrian.heading), math.sin(pedestrian.heading))
        push = (reach - distance) / 2.0
        pedestrian.x, pedestrian.y = pedestrian.x - nx * push, pedestrian.y - ny * push
        other.x, other.y = other.x + nx * push, other.y + ny * push
        if knockdown_chance < 1.0 and random.random() >= knockdown_chance:
            continue
        if pedestrian.speed - other.speed >= KNOCKDOWN_SPEED_DIFF_MPS:
            if knock_down(other):
                knocked.append((other, pedestrian))
        elif other.speed - pedestrian.speed >= KNOCKDOWN_SPEED_DIFF_MPS:
            if knock_down(pedestrian):
                knocked.append((pedestrian, other))
    return knocked


class IceSkatingPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="ice_skating",
        name="Ice skating",
        min_duration_s=60.0,
        max_duration_s=240.0,
        cooldown_s=300.0,
        base_weight=1.5,
    )

    def find_location(self, context: ActivityContext) -> Optional[ActivityLocation]:
        fields = open_ice(context)
        if not fields:
            return None
        field = random.choice(fields)
        point = sample_interior_point(field)
        return ActivityLocation(x=point[0], y=point[1], extra=field) if point else None

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0
        instance.data["field"] = instance.location.extra if instance.location is not None else None
        instance.data["target"] = None

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        field = instance.data.get("field")
        if field is None or not getattr(context.pedestrian_manager, "sports_ice_open", False):
            return True  # the ice closed (dark, or thawed): off home
        if is_down(context.pedestrian, instance, dt):
            return False
        target = instance.data.get("target")
        if target is None or glide(context.pedestrian, target, dt):
            instance.data["target"] = sample_interior_point(field)  # a new lap
        collide(context.pedestrian, others_on(field, context.pedestrian, context.pedestrian_manager.pedestrians))
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = IceSkatingPlugin()
