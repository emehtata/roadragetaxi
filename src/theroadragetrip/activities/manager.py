"""Activity selection, location reservation and cooldown - the only place
that contains generic activity orchestration. Never branches on which
activity it's driving; see base.py's ActivityPlugin for the hooks this
calls."""
from __future__ import annotations

import random
from typing import Dict, Hashable, Optional, Tuple

from .base import ActivityContext, ActivityLocation, ActivityPlugin
from .registry import ActivityRegistry, default_registry

# Any activity not matching the pedestrian's last one is still gated by this
# flat grace period, so residents don't chain straight from one activity
# into an unrelated one with no ordinary walking in between.
GLOBAL_ACTIVITY_COOLDOWN_S = 20.0


class ActivityManager:
    def __init__(self, registry: Optional[ActivityRegistry] = None) -> None:
        self.registry = registry or default_registry()
        self._reservations: Dict[Hashable, int] = {}  # reservation_key -> id(pedestrian)

    def select_activity(
        self, context: ActivityContext
    ) -> Optional[Tuple[ActivityPlugin, Optional[ActivityLocation]]]:
        candidates = []
        for plugin in self.registry.all_plugins():
            definition = plugin.definition
            if not self._eligible_for(plugin, context):
                continue
            if not plugin.can_start(context):
                continue
            location = plugin.find_location(context) if definition.requires_location else None
            if definition.requires_location and location is None:
                continue
            if location is not None and location.reservation_key is not None:
                holder = self._reservations.get(location.reservation_key)
                if holder is not None and holder != id(context.pedestrian):
                    continue
            weight = definition.base_weight * plugin.score(context, location)
            if weight > 0.0:
                candidates.append((plugin, location, weight))
        if not candidates:
            return None
        plugin, location, _ = random.choices(
            candidates, weights=[candidate[2] for candidate in candidates], k=1
        )[0]
        if location is not None and location.reservation_key is not None:
            self._reservations[location.reservation_key] = id(context.pedestrian)
        return plugin, location

    def release(self, location: Optional[ActivityLocation]) -> None:
        if location is not None and location.reservation_key is not None:
            self._reservations.pop(location.reservation_key, None)

    @staticmethod
    def _eligible_for(plugin: ActivityPlugin, context: ActivityContext) -> bool:
        flags = context.pedestrian.activity_flags
        last_id = flags.get("last_activity_id")
        last_end = flags.get("last_activity_end_time", -1e9)
        cooldown = plugin.definition.cooldown_s if last_id == plugin.definition.id else GLOBAL_ACTIVITY_COOLDOWN_S
        return context.sim_time - last_end >= cooldown
