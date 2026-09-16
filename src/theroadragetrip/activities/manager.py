"""Activity selection, location reservation and cooldown - the only place
that contains generic activity orchestration. Never branches on which
activity it's driving; see base.py's ActivityPlugin for the hooks this
calls."""
from __future__ import annotations

import random
from typing import Dict, Hashable, List, Optional, Tuple

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

    def explain_candidates(self, context: ActivityContext) -> List[Tuple[str, str]]:
        """Debug-only introspection (residents-live.md section 18's "why
        an activity was rejected"): for each registered plugin, one line
        on whether it would be picked for context.pedestrian right now
        and why/why not - without reserving anything or mutating state.
        Never called from select_activity's own hot path; a debug panel
        calls this on demand for whichever pedestrian is selected.

        Calls find_location()/score() same as a real selection would, so
        for a location-seeking plugin this does consume from the shared
        `random` stream (e.g. random.choice among several candidate
        benches) - harmless for a user-triggered debug view, but why this
        is never wired into the actual per-tick selection loop."""
        explanations = []
        for plugin in self.registry.all_plugins():
            definition = plugin.definition
            if not self._eligible_for(plugin, context):
                flags = context.pedestrian.activity_flags
                last_id = flags.get("last_activity_id")
                cooldown = definition.cooldown_s if last_id == definition.id else GLOBAL_ACTIVITY_COOLDOWN_S
                remaining = cooldown - (context.sim_time - flags.get("last_activity_end_time", -1e9))
                explanations.append((definition.id, f"cooldown, {max(0.0, remaining):.0f}s left"))
                continue
            if not plugin.can_start(context):
                explanations.append((definition.id, "can_start() is False"))
                continue
            location = plugin.find_location(context) if definition.requires_location else None
            if definition.requires_location and location is None:
                explanations.append((definition.id, "no suitable location nearby"))
                continue
            if location is not None and location.reservation_key is not None:
                holder = self._reservations.get(location.reservation_key)
                if holder is not None and holder != id(context.pedestrian):
                    explanations.append((definition.id, "location already reserved"))
                    continue
            weight = definition.base_weight * plugin.score(context, location)
            if weight <= 0.0:
                explanations.append((definition.id, f"score is {weight:.2f} (<= 0)"))
                continue
            explanations.append((definition.id, f"OK, weight={weight:.2f}"))
        return explanations

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
