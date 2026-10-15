"""Play ice hockey on a frozen ice rink. Each player is an ordinary solo
activity; the game is the shared puck: every player on a rink chases the
same point, which the puck's module-level state moves every few seconds -
a crowd around the puck without group recruiting.
"""
from __future__ import annotations

import random
from typing import Dict, Tuple

from ..base import ActivityContext, ActivityDefinition, ActivityInstance, ActivityLocation, ActivityPlugin
from .ice_skating import SKATING_SPEED_MPS, glide, open_ice
from .park_leisure import sample_interior_point

PUCK_MOVE_S = 3.0
# id(rink) -> (puck x, y, sim time it moved); stale entries are just
# overwritten when that rink is played on again.
_pucks: Dict[int, Tuple[float, float, float]] = {}


def puck(rink, sim_time: float) -> Tuple[float, float]:
    x, y, moved = _pucks.get(id(rink), (0.0, 0.0, -1e9))
    if sim_time - moved >= PUCK_MOVE_S:
        point = sample_interior_point(rink)
        if point is not None:
            x, y, moved = point[0], point[1], sim_time
            _pucks[id(rink)] = (x, y, moved)
    return x, y


class IceHockeyPlugin(ActivityPlugin):
    definition = ActivityDefinition(
        id="ice_hockey",
        name="Ice hockey",
        min_duration_s=90.0,
        max_duration_s=300.0,
        cooldown_s=300.0,
        base_weight=2.0,
    )

    def find_location(self, context: ActivityContext):
        rinks = open_ice(context, kinds=("ice_rink",))
        if not rinks:
            return None
        rink = random.choice(rinks)
        point = sample_interior_point(rink)
        return ActivityLocation(x=point[0], y=point[1], extra=rink) if point else None

    def start(self, context: ActivityContext, instance: ActivityInstance) -> None:
        instance.data["duration_s"] = random.uniform(self.definition.min_duration_s, self.definition.max_duration_s)
        instance.data["elapsed_s"] = 0.0
        instance.data["rink"] = instance.location.extra if instance.location is not None else None
        instance.data["offset"] = (random.uniform(-4.0, 4.0), random.uniform(-4.0, 4.0))  # not all on one spot

    def update(self, context: ActivityContext, instance: ActivityInstance, dt: float) -> bool:
        instance.data["elapsed_s"] += dt
        rink = instance.data.get("rink")
        if rink is None or not getattr(context.pedestrian_manager, "sports_ice_open", False):
            return True
        x, y = puck(rink, context.sim_time)
        ox, oy = instance.data["offset"]
        glide(context.pedestrian, (x + ox, y + oy), dt, SKATING_SPEED_MPS * 1.3)
        return instance.data["elapsed_s"] >= instance.data["duration_s"]


PLUGIN = IceHockeyPlugin()
